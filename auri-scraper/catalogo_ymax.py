#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da marca YMAX, no site da YM Distribuidora (YM Importação).

Uso: python catalogo_ymax.py          ->  catalogos/ymax.jsonl (log em catalogos/ymax.log)
     python catalogo_ymax.py --novo   ->  apaga o arquivo e começa do zero

Loja OpenCart sem preço para visitante. A categoria /ymax (só a marca YMAX; a YM também vende
DELTHY e LENZZO) lista os produtos, todos numa página; a página de cada produto dá o código ("Modelo",
gravado como está, com zero à esquerda: "05065"), o EAN ("Código de Barras"), as fotos e, na aba
"Detalhes", a aplicação ("HONDA" e embaixo "CITY 1.5 6V G4 2015 > 2020"). O "Marca:" da página é a
montadora do veículo, não a marca da peça. As fotos saem do cache em 1000x1000 (.jpg.webp); gravamos
a original de onde o cache é gerado (/image/data/...jpg, ~1268 px).
Retoma de onde parou: produtos cujo id já está no arquivo são pulados.
"""
import argparse
import html
import json
import logging
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
import urllib3.util.connection

from wayap_fotos import n_ean

# vários destes sites só respondem bem em IPv4 (igual ao helper/fotos.py)
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

BASE = "https://www.ymdistribuidora.com.br/"
# a lista inteira numa página só: paginando, a ordem padrão (empates) repete produtos e esconde ~1/4 deles
LISTA = BASE + "ymax?limit=10000&page={}"
PRODUTO = BASE + "index.php?route=product/product&product_id={}"
SAIDA = Path("catalogos/ymax.jsonl")
LOG = Path("catalogos/ymax.log")
MARCA = "YMAX"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
CONEXOES = 2
INTERVALO = 0.6   # no máximo ~1,7 inícios de requisição por segundo
ESPERAS = (5, 15, 30, 60)  # backoff em erro de conexão, 429 e 5xx
SEM_FOTO = ("no_image", "placeholder")
# "2015 > 2020" ou "2020 >" (em aberto)
ANOS_RE = re.compile(r"\b((?:19|20)\d{2})\s*>\s*((?:19|20)\d{2}\b)?")
# montadora como a KarHub escreve no campo "carro" (.title(): "Citroen", "Bmw")
MONTADORAS = {"MERCEDES BENZ": "Mercedes-Benz", "MERCEDES-BENZ": "Mercedes-Benz", "GM": "Chevrolet",
              "GM/CHEVROLET": "Chevrolet", "VW": "Volkswagen", "CITROËN": "Citroen"}

log = logging.getLogger("ymax")
_local = threading.local()


class Ritmo:
    """Espaça os inícios de requisição entre as threads."""

    def __init__(self, intervalo):
        self.intervalo, self.proxima, self.lock = intervalo, 0.0, threading.Lock()

    def esperar(self):
        with self.lock:
            agora = time.monotonic()
            espera = max(0.0, self.proxima - agora)
            self.proxima = max(agora, self.proxima) + self.intervalo
        time.sleep(espera)


ritmo = Ritmo(INTERVALO)


def sessao():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
    return _local.s


def pedir(url):
    """GET com backoff; erro 4xx (fora 429) não adianta repetir."""
    for espera in ESPERAS + (None,):
        ritmo.esperar()
        try:
            r = sessao().get(url, timeout=90)
            if r.status_code == 200:
                return r.text
            erro = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except requests.RequestException as e:
            erro = str(e) or type(e).__name__
        if espera is None:
            break
        log.info("%s em %s; nova tentativa em %ss", erro, url, espera)
        time.sleep(espera)
    raise RuntimeError(f"{erro} em {url}")


def _texto(trecho):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", trecho)).split())


def ids_da_lista(pagina):
    return list(dict.fromkeys(re.findall(r'data-product-id="(\d+)"', pagina)))


def total(pagina):
    m = re.search(r"do total de (\d+)", pagina)
    return int(m.group(1)) if m else 0


def foto_original(url):
    """.../image/cache/data/Produtos/CO/X-1-1000x1000.jpg.webp -> .../image/data/Produtos/CO/X-1.jpg"""
    return re.sub(r"/image/cache/(.+)-\d+x\d+\.(\w+)(?:\.webp)?$", r"/image/\1.\2", url)


def veiculos(pagina):
    """Aba "Detalhes": linha só com a montadora e embaixo um veículo por linha, com "ano > ano" ->
    'Honda CITY 1.5 6V G4 2015-2020; Mercedes-Benz SPRINTER 314 2.2 16V TURBO G2 Após 2020'.
    Linhas sem ano (características, motor, códigos equivalentes "HONDA 164005V5M01") ficam de fora."""
    m = re.search(r'id="tab-description">(.*?)(?:<div class="produto-detalhes"|</div>)', pagina, re.S)
    if not m:
        return None
    linhas = [_texto(l) for l in re.split(r"<br\s*/?>", m.group(1))]
    partes, montadora = [], None
    for i, linha in enumerate(linhas):
        proxima = linhas[i + 1] if i + 1 < len(linhas) else ""
        if not linha:
            montadora = None  # linha em branco fecha o bloco da montadora
        elif not re.search(r"\d", linha) and ANOS_RE.search(proxima):
            nome = linha.upper().split(" - ")[-1]  # "GM - CHEVROLET", "VW - VOLKSWAGEN"
            montadora = MONTADORAS.get(nome, nome.title())
        elif ANOS_RE.search(linha):
            veiculo = ANOS_RE.sub(lambda a: f"{a[1]}-{a[2]}" if a[2] else f"Após {a[1]}", linha)
            partes.append(" ".join(filter(None, (montadora, veiculo))))
    return "; ".join(dict.fromkeys(partes)) or None


def registro(pagina):
    """Página do produto -> registro do catálogo."""
    url = re.search(r'<link rel="canonical" href="([^"]+)"', pagina)
    nome = re.search(r'<h1 class="heading-title" itemprop="name">(.*?)</h1>', pagina, re.S)
    cod = re.search(r'itemprop="model">([^<]*)<', pagina)
    ean = re.search(r"C[óo]digo de Barras:\s*</strong>([^<]*)<", pagina)
    galeria = pagina[pagina.find('class="image-gallery"'):]
    galeria = galeria[:galeria.find("</div>")]
    fotos = re.findall(r'<a href="([^"]+)"[^>]*class="swipebox"', galeria) or \
        re.findall(r'data-largeimg="([^"]+)"', pagina)
    imagens = [foto_original(html.unescape(u)) for u in dict.fromkeys(fotos) if not any(s in u for s in SEM_FOTO)]
    return {"site": "ymax", "url": html.unescape(url.group(1)) if url else None,
            "nome": _texto(nome.group(1)) if nome else None, "marca": MARCA,
            "codigo_fabricante": _texto(cod.group(1)) or None if cod else None,
            "ean": n_ean(ean.group(1)) if ean else None,  # dígito verificador errado fica nulo
            "carro": veiculos(pagina), "imagens": imagens}


def ja_feitos(arquivo):
    """Ids dos produtos já gravados (a URL termina no id: .../corpo-de-borboleta-5443)."""
    feitos = set()
    if Path(arquivo).exists():
        for linha in Path(arquivo).open(encoding="utf-8"):
            try:
                feitos.add(re.search(r"-(\d+)$", json.loads(linha)["url"]).group(1))
            except (ValueError, KeyError, TypeError, AttributeError):
                pass  # linha cortada por interrupção
    return feitos


def listar():
    primeira = pedir(LISTA.format(1))
    esperado, ids = total(primeira), ids_da_lista(primeira)
    paginas = -(-esperado // max(1, len(ids)))
    for p in range(2, paginas + 1):
        ids += [i for i in ids_da_lista(pedir(LISTA.format(p))) if i not in ids]
    (log.info if len(ids) == esperado else log.warning)("lista: %s produtos em %s páginas (o site diz %s)",
                                                         len(ids), paginas, esperado)
    return ids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--novo", action="store_true", help="apaga o arquivo de saída e lê tudo de novo")
    args = ap.parse_args()
    SAIDA.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(LOG, encoding="utf-8")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    if args.novo:
        SAIDA.unlink(missing_ok=True)
    inicio = time.time()
    feitos = ja_feitos(SAIDA)
    pendentes = [i for i in listar() if i not in feitos]
    log.info("início: %s produtos pendentes, %s já no arquivo", len(pendentes), len(feitos))
    n_regs = com_foto = erros = 0
    with ThreadPoolExecutor(max_workers=CONEXOES) as pool, SAIDA.open("a", encoding="utf-8") as f:
        futuros = {pool.submit(pedir, PRODUTO.format(i)): i for i in pendentes}
        for n, fut in enumerate(as_completed(futuros), 1):
            try:
                r = registro(fut.result())
                if not r["url"] or not r["codigo_fabricante"]:
                    raise RuntimeError(f"produto {futuros[fut]} sem URL ou sem código (página mudou?)")
            except Exception as e:  # segue com os outros; o produto fica pendente para a próxima execução
                erros += 1
                log.error("ERRO %s", e)
                continue
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            n_regs += 1
            com_foto += bool(r["imagens"])
            if n % 200 == 0 or n == len(pendentes):
                log.info("[%s/%s] %s gravados, %s com foto, %s erros, %.0f min",
                         n, len(pendentes), n_regs, com_foto, erros, (time.time() - inicio) / 60)
    log.info("fim: %s produtos novos, %s com foto, %s erros, %.1f min -> %s",
             n_regs, com_foto, erros, (time.time() - inicio) / 60, SAIDA)


if __name__ == "__main__":
    main()
