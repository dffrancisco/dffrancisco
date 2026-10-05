#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Raven Ferramentas (WordPress).

Uso: python catalogo_raven.py   ->  catalogos/raven.jsonl (andamento em catalogos/raven.log)

A API aberta do WordPress (/wp-json/wp/v2/produto) lista os produtos: o título é o código do fabricante
("141022", "108800-10"), que sai como o site imprime, e a taxonomia "veiculo" (tipo > montadora > modelo) dá a
aplicação. O nome, a galeria (1 a 6 fotos de 1440x1080) e o EAN (no link "Encontrar revendedor") só estão na
página do produto, então cada produto custa uma requisição.
"""
import argparse
import html
import json
import logging
import re
import socket
import time
from pathlib import Path

import requests
import urllib3.util.connection

from wayap_fotos import n_ean

# alguns servidores destes fabricantes só respondem em IPv4 (igual ao helper/fotos.py)
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

BASE = "https://www.ravenferramentas.com.br"
SITE, MARCA = "raven", "RAVEN"
SAIDA = Path("catalogos/raven.jsonl")
INTERVALO = 0.7  # segundos entre requisições: no máximo ~1,5 por segundo
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
MONTADORAS = {"General Motors": "Chevrolet"}  # mesmo nome que a KarHub usa no campo "carro"
SEM_VEICULO = {"Universal"}  # tipo de veículo que não diz aplicação
EXTENSOES_FOTO = (".jpg", ".jpeg", ".png", ".webp")

log = logging.getLogger("raven")
_ultima = 0.0


def baixar(sessao, url, params=None):
    """GET com intervalo mínimo entre requisições; recusa, timeout, 429 e 5xx são tentados de novo com espera."""
    global _ultima
    for espera in (5, 15, 30, 60, None):
        pausa = _ultima + INTERVALO - time.monotonic()
        if INTERVALO and pausa > 0:
            time.sleep(pausa)
        _ultima = time.monotonic()
        try:
            r = sessao.get(url, params=params, timeout=90)
            if r.status_code == 200:
                return r
            erro = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except (requests.ConnectionError, requests.Timeout) as e:
            erro = str(e)
        if espera is None:
            break
        log.warning(f"{erro} em {url}; nova tentativa em {espera}s")
        time.sleep(espera)
    raise RuntimeError(f"{erro} em {url}")


def da_api(sessao, tipo, campos):
    """Todos os itens de /wp-json/wp/v2/<tipo>, 100 por página, só com os campos pedidos."""
    itens, pagina, total = [], 1, 1
    while pagina <= total:
        r = baixar(sessao, f"{BASE}/wp-json/wp/v2/{tipo}", {"per_page": 100, "page": pagina, "_fields": campos})
        itens += r.json()
        total = int(r.headers.get("X-WP-TotalPages") or 1)
        pagina += 1
    return itens


def ean_valido(texto):
    e = n_ean(texto)
    return e if e and len(re.sub(r"\D", "", texto or "")) == 13 else None


def veiculos(ids, termos):
    """Termos da taxonomia 'veiculo' do produto -> 'Renault Clio 1.0 16V; Renault Mégane 2.0 16V'. Só os modelos
    (tipo > montadora > modelo); os termos de tipo e de montadora sozinhos e os universais não dizem aplicação."""
    partes = []
    for i in ids:
        caminho = []
        while i in termos and len(caminho) < 10:
            caminho.insert(0, html.unescape(termos[i]["name"]).strip())
            i = termos[i]["parent"]
        if len(caminho) < 3 or caminho[0] in SEM_VEICULO:
            continue
        montadora, modelo = MONTADORAS.get(caminho[1], caminho[1]), caminho[-1]
        partes.append(modelo if modelo.lower().startswith(montadora.lower()) else f"{montadora} {modelo}")
    return "; ".join(dict.fromkeys(partes)) or None


def _sem_simbolos(codigo):
    return re.sub(r"[^A-Z0-9]", "", codigo.upper())


def fotos(pagina, codigo):
    """Galeria da página (data-images do div sync-galeria), na ordem do site. O arquivo começa pelo código
    ('141022-RAVEN-00-...jpg'); a foto que traz outro código sai."""
    m = re.search(r"data-images='([^']*)'", pagina)
    if not m:
        return []
    saida = []
    for item in json.loads(html.unescape(m[1])):
        url = (item.get("src") or "").strip()
        if not url.lower().endswith(EXTENSOES_FOTO):
            continue
        dono = re.match(r"(.+?)-RAVEN-", url.rsplit("/", 1)[-1], re.I)
        if dono and _sem_simbolos(dono[1]) != _sem_simbolos(codigo):
            log.info(f"foto de outro código descartada em {codigo}: {url}")
            continue
        saida.append(url)
    return list(dict.fromkeys(saida))


def nome_da_pagina(pagina, codigo):
    """Os campos da página vêm em <span class="text-population">: código, nome e peso, nessa ordem."""
    campos = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
              for c in re.findall(r'class="text-population">(.*?)</span>', pagina, re.S)]
    if codigo in campos and campos.index(codigo) + 1 < len(campos):
        return campos[campos.index(codigo) + 1]
    return campos[1] if len(campos) > 1 else None


def registro(produto, pagina, termos):
    codigo = html.unescape(produto["title"]["rendered"]).strip()
    ean = re.search(r"pertinhodemim\.com/produto/([^\"'/?]+)", pagina)
    return {"site": SITE, "url": produto["link"], "nome": nome_da_pagina(pagina, codigo) or codigo, "marca": MARCA,
            "codigo_fabricante": codigo, "ean": ean_valido(ean[1]) if ean else None,
            "imagens": fotos(pagina, codigo), "carro": veiculos(produto.get("veiculo") or [], termos)}


def sem_ean_repetido(regs):
    """EAN em códigos diferentes não dá para saber de qual é, e o errado funde peças diferentes no helper."""
    codigos = {}
    for r in regs:
        if r["ean"]:
            codigos.setdefault(r["ean"], set()).add(r["codigo_fabricante"])
    for r in regs:
        if r["ean"] and len(codigos[r["ean"]]) > 1:
            r["ean"] = None
    return regs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    SAIDA.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(SAIDA.with_suffix(".log"), "w", "utf-8")])
    sessao = requests.Session()
    sessao.headers["User-Agent"] = UA
    termos = {t["id"]: t for t in da_api(sessao, "veiculo", "id,name,parent")}
    produtos = da_api(sessao, "produto", "id,slug,link,title,veiculo")
    log.info(f"{len(produtos)} produtos e {len(termos)} termos de veículo na API")
    regs, falhas, descontinuados, sem_ean_no_link = [], [], 0, 0
    for i, p in enumerate(produtos, 1):
        try:
            pagina = baixar(sessao, p["link"]).text
        except RuntimeError as e:
            log.error(str(e))
            falhas.append(p["link"])
            continue
        r = registro(p, pagina, termos)
        descontinuados += "Produto descontinuado" in pagina
        if not r["ean"]:
            sem_ean_no_link += 1
            log.info(f"sem EAN válido em {r['codigo_fabricante']}: {re.findall(r'pertinhodemim[^\"]*', pagina)[:1]}")
        regs.append(r)
        if i % 100 == 0:
            log.info(f"{i} de {len(produtos)} produtos lidos")
    com_ean = sum(bool(r["ean"]) for r in regs)
    descartados = com_ean - sum(bool(r["ean"]) for r in sem_ean_repetido(regs))
    with SAIDA.open("w", encoding="utf-8") as f:
        for r in regs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.info(f"{len(regs)} produtos -> {SAIDA}: {sum(bool(r['imagens']) for r in regs)} com foto, "
             f"{com_ean - descartados} com EAN ({sem_ean_no_link} sem EAN no link, {descartados} descartados por "
             f"repetição), {sum(bool(r['carro']) for r in regs)} com aplicação, {descontinuados} descontinuados; "
             f"{len(falhas)} falhas {falhas[:20]}")


if __name__ == "__main__":
    main()
