#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da TC Chicotes, direto do site do fabricante.

Uso: python catalogo_tcchicotes.py          ->  catalogos/tcchicotes.jsonl (log em catalogos/tcchicotes.log)
     python catalogo_tcchicotes.py --novo   ->  apaga o arquivo e começa do zero

A lista /produtos/ (12 por página, em ordem de código) dá a URL de cada produto; a página do produto
dá o código, o EAN ("Cód. Barras"), a foto (500x500) e as aplicações (montadora -> modelo, uma linha
por ano). O localizador da marca no pertinhodemim.com tem a mesma foto em 1000x1000 para parte dos
produtos, pelo GTIN (o EAN sem o dígito verificador): quando existe, ela vem primeiro.

O site escreve o código com ponto e sem prefixo ("102.1278"); a KarHub escreve "TC 102.1278" e o
cliente "TC1021278". Gravamos "TC " + código do site, que normaliza para o mesmo "TC1021278".
Retoma de onde parou: produtos cuja URL já está no arquivo são pulados.
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

# o site só responde bem em IPv4 (igual ao helper/fotos.py)
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

BASE = "https://tcchicotes.com.br"
LISTA = BASE + "/produtos/?ordenar=codigo&pagina={}"  # em ordem de código a paginação não muda durante a leitura
PERTINHO = "https://tcchicotes.pertinhodemim.com/products2?cnpj=55567911000197&userLocale=pt-BR"
SAIDA = Path("catalogos/tcchicotes.jsonl")
LOG = Path("catalogos/tcchicotes.log")
MARCA = "TC CHICOTES"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
CONEXOES = 5      # cada página demora 3-4 s para sair; com 5 em paralelo o ritmo fica perto do limite abaixo
INTERVALO = 0.6   # no máximo ~1,7 inícios de requisição por segundo
ESPERAS = (5, 15, 30, 60)  # backoff em erro de conexão, 429 e 5xx
SEM_ANO = "1940"  # o site põe 1940 quando a aplicação não tem ano
SEM_FOTO = "no-image"
# montadoras do site com outro nome na KarHub (que usa .title(): "Citroen", "Bmw"); None = não é aplicação
MONTADORAS = {"GM/CHEVROLET": "Chevrolet", "CITROËN": "Citroen", "KAWAZAKI": "Kawasaki", "DIVERSOS": None, "DIVEROS": None}

log = logging.getLogger("tcchicotes")
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


def cartoes(pagina):
    """Página da lista -> [(código do site, url do produto)]."""
    return re.findall(r'class="bnr-card__sku"[^>]*>.*?<span>([^<]+)</span></span>'
                      r'<a class="bnr-card__media" href="([^"]+)"', pagina, re.S)


def total(pagina):
    m = re.search(r'data-bnr-total="(\d+)"', pagina)
    return int(m.group(1)) if m else 0


def codigo(codigo_site):
    return f"TC {codigo_site.strip()}"


def _anos(anos):
    """[1993, 1994, 1995, 1997] -> '1993-1995, 1997' (mesmo formato da KarHub)."""
    faixas = []
    for a in sorted(set(anos)):
        if faixas and a == faixas[-1][1] + 1:
            faixas[-1][1] = a
        else:
            faixas.append([a, a])
    return ", ".join(str(i) if i == f else f"{i}-{f}" for i, f in faixas)


def veiculos(pagina):
    """Aba "Aplicações": montadora -> linhas "modelo | ano / 2027" (uma por ano; o 2027 é o mesmo em todas)
    -> 'Fiat Elba 1.5 Spi 1993-1997; Fiat Uno 1.5 8V Spi 1994-1996'."""
    modelos = {}
    for grupo in re.findall(r'<section class="bnr-apps__group">(.*?)</section>', pagina, re.S):
        m = re.search(r'class="bnr-apps__automaker">([^<]*)<', grupo)
        nome = _texto(m.group(1)) if m else ""
        montadora = MONTADORAS.get(nome.upper(), nome.title())
        if not montadora:
            continue
        for modelo, anos in re.findall(r'class="bnr-apps__model">(.*?)</span>\s*<span class="bnr-apps__years">([^<]*)<',
                                       grupo, re.S):
            modelo = _texto(modelo)
            if not modelo or modelo.upper() == "DIVERSOS":
                continue
            inicio = anos.split("/")[0].strip()
            lista = modelos.setdefault((montadora, modelo), [])
            if inicio.isdigit() and inicio != SEM_ANO:
                lista.append(int(inicio))
    partes = [" ".join(filter(None, (montadora, modelo, _anos(anos)))) for (montadora, modelo), anos in modelos.items()]
    return "; ".join(partes) or None


def fotos_grandes(itens):
    """JSON do localizador -> {GTIN de 12 dígitos: (nome, url da foto de 1000 px)}; itens sem foto ficam de fora."""
    return {i["gtin"]: (i.get("name") or "", i["imageurl"].split("?")[0])
            for i in itens if i.get("gtin") and i.get("imageurl")}


def _foto_grande(grandes, ean, codigo_site):
    if not ean or ean[:12] not in grandes:
        return None
    nome, url = grandes[ean[:12]]
    primeira = (nome.split() or [""])[0]
    # o nome costuma começar pelo código ("102.1278 - Chicote..."): se começa por outro, não é o mesmo produto
    if re.search(r"\d", primeira) and codigo_site not in nome:
        return None
    return url


def registro(pagina, url, grandes):
    """Página do produto -> registro do catálogo."""
    cod = re.search(r'bnr-ids__chip--code"[^>]*>([^<]+)<', pagina)
    cod = html.unescape(cod.group(1)).strip() if cod else None
    titulo = re.search(r'<h1 class="bnr-product-title">(.*?)</h1>', pagina, re.S)
    ean = re.search(r"<dt>\s*C[óo]d\. Barras\s*</dt>\s*<dd>([^<]*)</dd>", pagina)
    ean = n_ean(ean.group(1)) if ean else None  # dígito verificador errado ou "0" fica nulo
    galeria = pagina[pagina.find('class="bnr-gallery"'):]
    galeria = galeria[:galeria.find("</div>")]
    imagens = [u for u in dict.fromkeys(re.findall(r'(?:data-bnr-zoom|src)="([^"]+)"', galeria)) if SEM_FOTO not in u]
    grande = _foto_grande(grandes, ean, cod) if cod else None
    return {"site": "tcchicotes", "url": url, "nome": _texto(titulo.group(1)) if titulo else None, "marca": MARCA,
            "codigo_fabricante": codigo(cod) if cod else None, "ean": ean, "carro": veiculos(pagina),
            "imagens": ([grande] if grande else []) + imagens}


def ja_feitos(arquivo):
    feitos = set()
    if Path(arquivo).exists():
        for linha in Path(arquivo).open(encoding="utf-8"):
            try:
                feitos.add(json.loads(linha)["url"])
            except (ValueError, KeyError):
                pass  # linha cortada por interrupção
    return feitos


def listar(pool):
    """Todas as páginas da lista -> {url: código do site}."""
    primeira = pedir(LISTA.format(1))
    esperado = total(primeira)
    paginas = -(-esperado // max(1, len(cartoes(primeira))))
    produtos = dict((u, c) for c, u in cartoes(primeira))
    for n, pagina in enumerate(pool.map(pedir, [LISTA.format(p) for p in range(2, paginas + 2)]), 2):
        produtos.update((u, c) for c, u in cartoes(pagina))
        if n % 50 == 0:
            log.info("lista: página %s de %s, %s produtos", n, paginas, len(produtos))
    log.info("lista: %s produtos em %s páginas (o site diz %s)", len(produtos), paginas, esperado)
    return produtos


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
    grandes = fotos_grandes(json.loads(pedir(PERTINHO)))
    log.info("início: %s fotos de 1000 px no localizador; %s produtos já no arquivo", len(grandes), len(feitos))
    with ThreadPoolExecutor(max_workers=CONEXOES) as pool:
        pendentes = [u for u in listar(pool) if u not in feitos]
        n_regs = com_foto = erros = 0
        with SAIDA.open("a", encoding="utf-8") as f:
            futuros = {pool.submit(pedir, u): u for u in pendentes}
            for n, fut in enumerate(as_completed(futuros), 1):
                url = futuros[fut]
                try:
                    r = registro(fut.result(), url, grandes)
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
