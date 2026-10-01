#!/usr/bin/env python3
"""Catálogo de metadados da KarHub (www.karhub.com.br) para achar fotos das peças do ERP.

A loja é Shopify Hydrogen: a página inicial expõe o token público da Storefront API, que devolve
o catálogo inteiro em páginas de 250 produtos, já com marca, código do fabricante, EAN e fotos
(metafield custom.karhub_ficha_tecnica) e os veículos compatíveis (tags).

Uso:
    python catalogo_karhub.py                    # tudo; retoma do último id gravado no log
    python catalogo_karhub.py --limite 50 -o /tmp/teste.jsonl

Saída: uma linha JSON por produto em catalogos/karhub.jsonl; log (com o último id) em catalogos/karhub.log
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
from scrapling.fetchers import Fetcher

from vtex import faixas

SITE = "https://www.karhub.com.br"
API_VERSAO = "2026-07"
# Lidos da página inicial em 2026-09; usados só se a página não puder ser lida
LOJA_PADRAO, TOKEN_PADRAO = "31a28c-3.myshopify.com", "3861b2db4c0d942b9667744d052cb118"
POR_PAGINA = 250  # máximo da Storefront API
ESPERAS = (5, 15, 30, 60)
EAN_RE = re.compile(r"^\d{8}$|^\d{12,14}$")
# Tags de veículo: "Ford Escort 1995 1.8 16V ZETEC" (uma por ano). As demais tags são códigos
# alternativos ("ga-002", "GAU-1989") e categorias ("lvl1...").
VEICULO_RE = re.compile(r"^(?P<antes>[^\W\d_][^\W\d_]+(?:-[^\W\d_]+)* .+?) (?P<ano>(?:19|20)\d{2})(?: (?P<depois>.+))?$")

# A API não pagina (cursor) além de 25 mil itens por consulta; por isso cada página é uma consulta
# nova a partir do último id lido ("id:>N" compara numericamente).
QUERY = """query($n: Int!, $filtro: String) {
  products(first: $n, sortKey: ID, query: $filtro) {
    pageInfo { hasNextPage }
    nodes {
      id handle title vendor tags
      metafields(identifiers: [{namespace: "custom", key: "karhub_ficha_tecnica"},
                               {namespace: "custom", key: "karhub_partnumber"}]) { key value }
      images(first: 50) { nodes { url } }
      variants(first: 50) { nodes { title barcode selectedOptions { name value } image { url } } }
    }
  }
}"""


class Bloqueado(Exception):
    pass


def credenciais():
    try:
        page = Fetcher.get(SITE + "/", stealthy_headers=True)
        m = re.search(r"publicStoreDomain\W+([\w.-]+\.myshopify\.com)\W+publicStorefrontApiToken\W+([0-9a-f]{32})",
                      page.body.decode("utf-8", "replace"))
        if m:
            return m.groups()
    except Exception:
        pass
    return LOJA_PADRAO, TOKEN_PADRAO


def consultar(sessao, loja, token, variaveis, log):
    """Uma página da API, com novas tentativas; 403/430/captcha = bloqueio, espera 4x mais."""
    url = f"https://{loja}/api/{API_VERSAO}/graphql.json"
    bloqueios = 0
    for espera in (*ESPERAS, None):
        try:
            r = sessao.post(url, json={"query": QUERY, "variables": variaveis},
                            headers={"X-Shopify-Storefront-Access-Token": token}, timeout=120)
            if r.status_code in (403, 430) or "captcha" in r.text[:3000].lower():
                bloqueios += 1
                erro = f"BLOQUEIO HTTP {r.status_code}"
                espera = espera and espera * 4
            elif r.status_code == 429 or r.status_code >= 500:
                erro = f"HTTP {r.status_code}"
                espera = espera and max(espera, int(r.headers.get("Retry-After") or 0))
            else:
                r.raise_for_status()
                dados = r.json()
                codigos = {(e.get("extensions") or {}).get("code") for e in dados.get("errors", [])}
                if not dados.get("errors"):
                    return dados["data"]["products"]
                # Erros internos da Shopify também chegam com HTTP 200, no corpo
                if not codigos & {"THROTTLED", "INTERNAL_SERVER_ERROR"}:
                    raise RuntimeError(f"erro GraphQL: {dados['errors']}")
                erro = f"GraphQL {', '.join(filter(None, codigos))}"
        except (requests.ConnectionError, requests.Timeout) as e:
            erro = f"conexão: {e}"
        if espera is None:
            raise (Bloqueado if bloqueios else RuntimeError)(erro)
        log(f"{erro}; nova tentativa em {espera}s")
        time.sleep(espera)


def veiculos(tags):
    """Tags ano a ano -> "Ford Escort 1981-2003 1.8 16V ZETEC; ..." (anos contínuos viram faixa)."""
    anos = {}
    for tag in tags:
        m = VEICULO_RE.match(tag.strip())
        if m and not tag.startswith("lvl"):
            depois = m["depois"] if m["depois"] and re.search(r"\w", m["depois"]) else None  # "*-*" = qualquer motor
            anos.setdefault((m["antes"], depois), []).append(int(m["ano"]))
    partes = []
    for (antes, depois), lista in anos.items():
        texto = ", ".join(str(a) if a == b else f"{a}-{b}" for a, b in faixas(lista))
        partes.append(" ".join(filter(None, (antes, texto, depois))))
    return "; ".join(partes) or None


def ean_valido(valor):
    valor = (valor or "").strip()
    return valor if EAN_RE.match(valor) and valor.strip("0") else None


def registros(produto):
    """Um registro por variante (quase todos os produtos têm só uma)."""
    mf = {m["key"]: m["value"] for m in produto["metafields"] if m}
    try:
        ficha = {c["key"]: c.get("value") for c in json.loads(mf.get("karhub_ficha_tecnica") or "[]")}
    except (json.JSONDecodeError, TypeError, KeyError):
        ficha = {}
    imagens = [i["url"] for i in produto["images"]["nodes"]]
    variantes = produto["variants"]["nodes"]
    url = f"{SITE}/p/{produto['handle']}"
    comum = {"site": "karhub", "marca": (produto["vendor"] or ficha.get("brand") or "").strip() or None,
             "carro": veiculos(produto["tags"])}
    unica = len(variantes) == 1
    for v in variantes:
        img_v = (v.get("image") or {}).get("url")
        reg = {**comum,
               "url": url if unica else f"{url}?{urlencode({o['name']: o['value'] for o in v['selectedOptions']})}",
               "nome": produto["title"] if unica else f"{produto['title']} - {v['title']}",
               # Ficha técnica e partnumber são do produto: só valem para a variante se ela for a única
               "codigo_fabricante": ((mf.get("karhub_partnumber") or ficha.get("partnumber") or "").strip() or None)
                                    if unica else None,
               "ean": ean_valido(v.get("barcode")) or (ean_valido(ficha.get("ean")) if unica else None),
               "imagens": list(dict.fromkeys(filter(None, [img_v, *imagens])))}
        yield {k: reg[k] for k in ("site", "url", "nome", "marca", "codigo_fabricante", "ean", "imagens", "carro")
               if reg[k]}


def ultimo_id(arq_log):
    if not arq_log.exists():
        return None
    ids = re.findall(r"ultimo_id=(\d+)", arq_log.read_text(encoding="utf-8"))
    return int(ids[-1]) if ids else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="catalogos/karhub.jsonl")
    ap.add_argument("--limite", type=int, help="para depois de N produtos (teste)")
    ap.add_argument("--do-inicio", action="store_true",
                    help="ignora o id salvo e percorre tudo de novo (só grava URLs ainda ausentes)")
    args = ap.parse_args()
    saida = Path(args.output)
    arq_log = saida.with_suffix(".log")
    saida.parent.mkdir(parents=True, exist_ok=True)

    vistos = set()
    if saida.exists():
        texto = saida.read_text(encoding="utf-8")
        if texto and not texto.endswith("\n"):  # última linha cortada por uma interrupção
            texto = texto[:texto.rfind("\n") + 1]
            saida.write_text(texto, encoding="utf-8")
        vistos = {json.loads(linha)["url"] for linha in texto.splitlines() if linha.strip()}
    ultimo = None if args.do_inicio else ultimo_id(arq_log)
    loja, token = credenciais()
    sessao = requests.Session()
    sessao.headers["Content-Type"] = "application/json"

    with open(saida, "a", encoding="utf-8") as out, open(arq_log, "a", encoding="utf-8") as f_log:
        def log(msg):
            linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
            print(linha, flush=True)
            f_log.write(linha + "\n")
            f_log.flush()

        log(f"início: loja {loja}, {len(vistos)} registros já no arquivo, "
            f"{f'retomando após o id {ultimo}' if ultimo else 'do começo'}")
        inicio, pagina_n, produtos, gravados, sem_foto = time.time(), 0, 0, 0, 0
        while True:
            n = min(POR_PAGINA, args.limite - produtos) if args.limite else POR_PAGINA
            try:
                pagina = consultar(sessao, loja, token, {"n": n, "filtro": f"id:>{ultimo}" if ultimo else None}, log)
            except Bloqueado as e:
                log(f"PARADO por bloqueio ({e}). Rode de novo mais tarde; retoma do último id.")
                sys.exit(2)
            for produto in pagina["nodes"]:
                for reg in registros(produto):
                    if reg["url"] in vistos:
                        continue
                    if not reg.get("imagens"):
                        sem_foto += 1
                        continue
                    out.write(json.dumps(reg, ensure_ascii=False) + "\n")
                    vistos.add(reg["url"])
                    gravados += 1
            out.flush()
            pagina_n += 1
            produtos += len(pagina["nodes"])
            # O id só é registrado depois que a página inteira foi gravada
            if pagina["nodes"]:
                ultimo = int(pagina["nodes"][-1]["id"].rsplit("/", 1)[1])
            log(f"página {pagina_n}: {produtos} produtos lidos, {gravados} gravados, {sem_foto} sem foto, "
                f"{time.time() - inicio:.0f}s" + (f" ultimo_id={ultimo}" if ultimo else ""))
            if not pagina["pageInfo"]["hasNextPage"] or (args.limite and produtos >= args.limite):
                break
            time.sleep(0.5)
        log(f"fim: {produtos} produtos lidos, {gravados} registros novos, {sem_foto} sem foto, "
            f"{len(vistos)} no arquivo, {time.time() - inicio:.0f}s")


if __name__ == "__main__":
    main()
