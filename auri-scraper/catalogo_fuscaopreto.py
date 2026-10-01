#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Fuscão Preto Auto Peças (VTEX).

Uso: python catalogo_fuscaopreto.py   ->  catalogos/fuscaopreto.jsonl

A loja não informa o código do fabricante (o RefId é código interno), então só o EAN
serve para casar com o nosso cadastro.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scrapling.fetchers import Fetcher

from vtex import POR_PAGINA, api_get

BASE = "https://www.fuscaopretoautopeca.com.br"
SAIDA = Path("catalogos/fuscaopreto.jsonl")
LIMITE_BUSCA = 2500  # a busca da VTEX não pagina além disso


def total(fq):
    page = Fetcher.get(f"{BASE}/api/catalog_system/pub/products/search?{fq}&_from=0&_to=0", stealthy_headers=True)
    return int((page.headers.get("resources") or "0-0/0").split("/")[-1])


def produtos(fq):
    for inicio in range(0, LIMITE_BUSCA, POR_PAGINA):
        lote = api_get(BASE, f"products/search?{fq}&_from={inicio}&_to={inicio + POR_PAGINA - 1}")
        yield from lote
        if len(lote) < POR_PAGINA:
            return


def filtros_da_marca(marca):
    fq = f"fq=B:{marca['id']}"
    if total(fq) <= LIMITE_BUSCA:
        return [fq]
    # marca grande demais para uma busca só: divide pelas categorias de primeiro nível
    return [f"{fq}&fq=C:/{c['id']}/" for c in api_get(BASE, "category/tree/1")]


def registros(produto):
    for item in produto["items"]:
        imagens = [i["imageUrl"].split("?")[0] for i in item.get("images", [])]
        if imagens:
            yield {"site": "fuscaopreto", "url": f"{BASE}/{produto['linkText']}/p?skuId={item['itemId']}",
                   "nome": item.get("nameComplete") or produto["productName"], "marca": produto.get("brand"),
                   "codigo_fabricante": None, "ean": item.get("ean") or None, "imagens": imagens,
                   "carro": ", ".join(produto.get("Modelo") or produto.get("Modelos") or []) or None}


def main():
    marcas = [m for m in api_get(BASE, "brand/list") if m.get("isActive")]
    with ThreadPoolExecutor(max_workers=3) as pool:
        filtros = [fq for lista in pool.map(filtros_da_marca, marcas) for fq in lista]
        vistos = set()
        SAIDA.parent.mkdir(exist_ok=True)
        with SAIDA.open("w", encoding="utf-8") as f:
            for lote in pool.map(lambda fq: list(produtos(fq)), filtros):
                for p in lote:
                    if p["productId"] not in vistos:
                        vistos.add(p["productId"])
                        for r in registros(p):
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(vistos)} produtos -> {SAIDA}")


if __name__ == "__main__":
    main()
