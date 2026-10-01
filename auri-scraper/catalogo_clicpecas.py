#!/usr/bin/env python3
"""Catálogo de metadados da ClicPeças (www.clicpecas.com.br) para casar fotos com o ERP.

A loja roda na plataforma WS Lojas: o HTML é só um template e os dados vêm da API que o
próprio navegador chama (apilojaws.wslojas.com.br/api-loja-v2). O catálogo inteiro é
listado pelas categorias raiz (+ URLs do sitemap que não aparecem em nenhuma categoria) e
cada produto é detalhado em /produtos/dadosproduto (fotos em 1200px, variações, descrição).

A loja NÃO publica EAN nem código do fabricante: o "codigo" do site (e o "mpn" do JSON-LD)
é o código interno da loja, gravado em "codigo_loja". Quando o texto do anúncio traz
explicitamente o código da montadora ("Cód. Original 7743036", "Código Fiat: 100177560")
ele vai em "codigo_original".

Saída: catalogos/clicpecas.jsonl, um registro por produto ou por variação (lado, cor...).
Retoma de onde parou: produtos cuja URL já está no arquivo são pulados.

Uso:
    python catalogo_clicpecas.py              # catálogo completo
    python catalogo_clicpecas.py --limite 50  # teste com poucos produtos
"""
import argparse
import html
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

SITE = "https://www.clicpecas.com.br"
API = "https://apilojaws.wslojas.com.br/api-loja-v2"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CONEXOES = 3                   # limite de requisições simultâneas pedido pelo dono do servidor
INTERVALO = 0.25               # e no máximo ~4 inícios de requisição por segundo
ESPERAS = (5, 15, 30, 60)      # backoff em erro de conexão, 429 e 5xx
ESPERAS_BLOQUEIO = (60, 180, 300)

# Mesmo formato do HdVarInfoListagem das páginas de categoria (só muda o id da categoria)
INFO_LISTAGEM = "_|_{}_|__|__|__|__|__|_1_|__|__|__|__|__|__|_"
# Título da seção sozinho na linha ou seguido de ":" ("Compatível com os dois lados" não é título)
COMPAT_RE = re.compile(r"^(?:COMPAT[ÍI]VEL COM|COMPATIBILIDADE(?: \w+)?|VE[ÍI]CULOS COMPAT[ÍI]VEIS)\s*(?::\s*(.*))?$", re.I)
FIM_COMPAT_RE = re.compile(r"^(ATEN[ÇC]|IMPORTANTE|RECOMENDA|OBS|ESPECIFICA|APLICA[ÇC]|GARANTIA|IMAGENS|NOTA\b|"
                           r"DICA|ITENS|DIMENS|MEDIDAS|INFORMA|CARACTER|CONTE[ÚU]DO|ACOMPANHA)", re.I)
MONTADORAS = (r"Original|Montadora|OEM|Fiat|VW|Volkswagen|GM|Chevrolet|Ford|Renault|Toyota|Honda|Hyundai|"
              r"Nissan|Peugeot|Citro[eë]n|Mitsubishi|Jeep|Kia")
COD_ORIGINAL_RE = re.compile(rf"\bC[óo]d(?:igo|\.)?\s*(?:{MONTADORAS})(?:\s+(?:{MONTADORAS}))?\b\s*[:\-–]?\s*"
                             r"([A-Z0-9]{3} \d{3} \d{3}[A-Z]{0,3}\b|(?=[A-Z0-9.\-]*\d)[A-Z0-9][A-Z0-9.\-]{4,})", re.I)

log = logging.getLogger("clicpecas")
locais = threading.local()


class Ritmo:
    """Espaça os inícios de requisição entre as threads; freia tudo se o site bloquear."""

    def __init__(self, intervalo):
        self.intervalo, self.proxima, self.lock = intervalo, 0.0, threading.Lock()
        self.bloqueios = 0

    def esperar(self):
        with self.lock:
            agora = time.monotonic()
            espera = max(0.0, self.proxima - agora)
            self.proxima = max(agora, self.proxima) + self.intervalo
        time.sleep(espera)

    def frear(self, pausa):
        with self.lock:
            self.bloqueios += 1
            self.intervalo = min(self.intervalo * 2, 5.0)
            self.proxima = time.monotonic() + pausa


ritmo = Ritmo(INTERVALO)


def sessao():
    if not hasattr(locais, "s"):
        locais.s = requests.Session()
        locais.s.headers.update({"User-Agent": UA, "Referer": SITE + "/", "Accept-Language": "pt-BR,pt;q=0.9"})
    return locais.s


def pedir(url, params=None, json_=True):
    """GET com backoff; 404 -> None. Resposta HTML no lugar de JSON (captcha) conta como bloqueio."""
    tentativa, bloqueio = 0, 0
    while True:
        ritmo.esperar()
        motivo, bloqueado = None, False
        try:
            r = sessao().get(url, params=params, timeout=60)
        except requests.RequestException as e:
            motivo = type(e).__name__
        else:
            captcha = "captcha" in r.text[:20000].lower() or "cf-chl" in r.text[:20000]
            if r.status_code == 404:
                return None
            if r.status_code == 403 or (r.status_code == 200 and captcha):
                motivo, bloqueado = f"BLOQUEIO? HTTP {r.status_code}{' captcha' if captcha else ''}", True
            elif r.status_code == 429 or r.status_code >= 500:
                motivo = f"HTTP {r.status_code}"
            elif r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code} em {r.url}")
            elif not json_:
                return r.text
            else:
                try:
                    return r.json()
                except ValueError:
                    motivo = "resposta não-JSON"
        if bloqueado:
            if bloqueio >= len(ESPERAS_BLOQUEIO):
                raise RuntimeError(f"{motivo} em {url}")
            espera = ESPERAS_BLOQUEIO[bloqueio]
            bloqueio += 1
            ritmo.frear(espera)
            log.warning("%s em %s; pausando %ss e reduzindo o ritmo", motivo, url, espera)
        else:
            if tentativa >= len(ESPERAS):
                raise RuntimeError(f"{motivo} em {url}")
            espera = ESPERAS[tentativa]
            tentativa += 1
            log.info("%s em %s; nova tentativa em %ss", motivo, url, espera)
        time.sleep(espera)


def credenciais():
    """Id da loja e token público que a página entrega ao JavaScript da vitrine."""
    pagina = pedir(SITE + "/", json_=False)
    loja = re.search(r"id='HD_LV_ID' value='(\d+)'", pagina)
    token = re.search(r"id='HdTokenLojaTemp' value='([^']+)'", pagina)
    if not (loja and token):
        raise SystemExit("token da API não encontrado na página inicial (layout mudou ou acesso bloqueado)")
    return {"LOJA": loja.group(1), "LVdashview": "0", "LvToken": token.group(1)}


def api(cred, caminho, **params):
    return pedir(API + caminho, {**cred, **params})


def listar_catalogo(cred, pool):
    """{url: id} de todos os produtos, paginando cada categoria raiz (32 por página)."""
    categorias = api(cred, "/categorias", VarsFiltrosListagem="", VarsFiltrosListagemJson="",
                     DptId="", DptTipo="", VarsCategorias="_____False_")["Categorias"]

    def pagina(cat_id, n):
        return api(cred, "/produtos/listagem", SubEtapaWs="", InfoListagem=INFO_LISTAGEM.format(cat_id),
                   VarsFiltrosListagem="", VarsFiltrosListagemJson="", num_pagina=n,
                   productsPerLine=4, shortDescriptionVisibleOnList=0)

    produtos, urls_categorias = {}, set()

    def guardar_categorias(cats):
        for c in cats or []:
            urls_categorias.add(SITE + c["url"])
            guardar_categorias(c.get("subcategorias"))

    guardar_categorias(categorias)
    for cat in categorias:
        primeira = pagina(cat["id"], 1)
        total = primeira["paginacao"]["qtd_paginas"]
        paginas = [primeira] + list(pool.map(lambda n: pagina(cat["id"], n), range(2, total + 1)))
        for p in (p for pg in paginas for p in pg["produtos"] or []):
            produtos[SITE + p["links"]["ver_produto"]] = p["id"]
        log.info("categoria %s: %s páginas, %s produtos no total", cat["nome"], total, len(produtos))
    return produtos, urls_categorias


def id_da_pagina(url):
    pagina = pedir(url, json_=False)
    m = pagina and re.search(r"id='LV_HD_PROD_ID' value='(\d+)'", pagina)
    return m.group(1) if m else None  # páginas institucionais/marcas não têm produto


def linhas_texto(conteudo):
    conteudo = re.sub(r"<(style|script)\b.*?</\1>|<!--.*?-->", "", conteudo, flags=re.S | re.I)
    conteudo = re.sub(r"<(br|hr)\b[^>]*>|</?(p|div|li|ul|ol|h\d|tr|table)\b[^>]*>", "\n", conteudo, flags=re.I)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", conteudo)).replace("\xa0", " ").replace("​", "")
    return [re.sub(r"\s+", " ", l).strip() for l in texto.split("\n") if l.strip()]


def compatibilidade(linhas):
    """Texto da seção "COMPATÍVEL COM:" do anúncio (até o próximo título)."""
    for i, linha in enumerate(linhas):
        m = COMPAT_RE.match(linha)
        if not m:
            continue
        partes = [m.group(1)] if m.group(1) else []
        for seguinte in linhas[i + 1:i + 60]:
            if FIM_COMPAT_RE.match(seguinte) or COMPAT_RE.match(seguinte):
                break
            partes.append(seguinte)
        partes = [p.strip(" -–;•") for p in partes if p.strip(" -–;•")]
        if partes:
            return "; ".join(partes)
    return None


def fotos(lista):
    return [f.get("zoom") or f.get("normal") or f.get("thumb") for f in lista or []
            if f.get("zoom") or f.get("normal") or f.get("thumb")]


def registros(url, d):
    linhas = [l for desc in d.get("descricoes") or [] for l in linhas_texto(desc.get("conteudo") or "")]
    nome = re.sub(r"\s+", " ", d["nome"]).strip()
    cod_original = COD_ORIGINAL_RE.search("\n".join([nome] + linhas))
    base = {"site": "clicpecas", "url": url, "nome": nome,
            "marca": ((d.get("fabricante") or {}).get("nome") or "").strip() or None,
            "codigo_fabricante": None, "ean": None, "imagens": fotos(d.get("fotos")),
            "carro": compatibilidade(linhas), "codigo_loja": d.get("codigo") or None}
    if cod_original:
        base["codigo_original"] = cod_original.group(1).strip(".-")
    if not d.get("variacoes"):
        return [base]
    regs = []
    for v in d["variacoes"]:
        atributos = " / ".join(a["valor"].strip() for a in v.get("atributos") or [] if (a.get("valor") or "").strip())
        # Foto da própria variação primeiro (ex.: lado direito); depois a galeria do produto
        imagens = list(dict.fromkeys(fotos(v.get("fotos")) + base["imagens"]))
        regs.append({**base, "nome": f"{nome} - {atributos}" if atributos else nome, "imagens": imagens,
                     "codigo_loja": v.get("codigo") or base["codigo_loja"]})
    return regs


def detalhar(cred, url, prod_id):
    d = api(cred, "/produtos/dadosproduto", Produto=prod_id)
    if not d or not d.get("nome"):
        return url, []
    return url, registros(url, d)


def ja_feitos(saida):
    feitos = set()
    if saida.exists():
        for linha in saida.read_text(encoding="utf-8").splitlines():
            try:
                feitos.add(json.loads(linha)["url"])
            except (ValueError, KeyError):
                pass  # linha truncada por interrupção
    return feitos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="catalogos/clicpecas.jsonl")
    ap.add_argument("--log", default="catalogos/clicpecas.log")
    ap.add_argument("--limite", type=int, help="processa só os N primeiros produtos pendentes")
    args = ap.parse_args()
    saida = Path(args.output)
    saida.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(args.log, encoding="utf-8")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    inicio = time.time()
    feitos = ja_feitos(saida)
    cred = credenciais()
    with ThreadPoolExecutor(max_workers=CONEXOES) as pool:
        produtos, urls_categorias = listar_catalogo(cred, pool)

        # Anúncios que estão no sitemap mas fora de qualquer categoria
        sitemap = pedir(SITE + "/sitemap.xml", json_=False)
        extras = [u for u in dict.fromkeys(re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap))
                  if u.rstrip("/") != SITE and u not in produtos and u not in urls_categorias and u not in feitos]
        for url, prod_id in zip(extras, pool.map(id_da_pagina, extras)):
            if prod_id and prod_id not in produtos.values():
                produtos[url] = prod_id
        log.info("%s produtos no catálogo (%s URLs extras do sitemap verificadas); %s já no arquivo",
                 len(produtos), len(extras), len(feitos & produtos.keys()))

        pendentes = [(u, i) for u, i in produtos.items() if u not in feitos][:args.limite]
        n_regs = sem_foto = erros = 0
        with saida.open("a", encoding="utf-8") as f:
            futuros = [pool.submit(detalhar, cred, u, i) for u, i in pendentes]
            for n, fut in enumerate(as_completed(futuros), 1):
                try:
                    url, regs = fut.result()
                except Exception as e:  # segue com os outros; o produto fica pendente para a próxima execução
                    erros += 1
                    log.error("ERRO %s", e)
                    continue
                com_foto = [r for r in regs if r["imagens"]]
                sem_foto += len(regs) - len(com_foto)
                if com_foto:
                    f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in com_foto))
                    f.flush()
                n_regs += len(com_foto)
                if n % 100 == 0 or n == len(pendentes):
                    passado = time.time() - inicio
                    log.info("[%s/%s] %s registros gravados, %s sem foto, %s erros, %.0f min",
                             n, len(pendentes), n_regs, sem_foto, erros, passado / 60)
    log.info("fim: %s produtos, %s registros novos, %s sem foto, %s erros, %s bloqueios, %.1f min -> %s",
             len(pendentes), n_regs, sem_foto, erros, ritmo.bloqueios, (time.time() - inicio) / 60, saida)


if __name__ == "__main__":
    main()
