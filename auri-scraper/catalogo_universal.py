#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Universal Automotive (VTEX).

Uso: python catalogo_universal.py   ->  catalogos/universal.jsonl

É a loja B2B do próprio fabricante (grupo Universal: Universal/Univel, Micro, Uniflex,
Carto, Amortex, Unick, Uni1000), então os dados são os originais: todo produto tem EAN,
o RefId do SKU é o código do fabricante ("41595") e as fotos vêm em 1200x1200.
A aplicação sai da tabela "VEÍCULOS COMPATÍVEIS" da ficha técnica.
"""
import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

from scrapling.fetchers import Fetcher

from vtex import POR_PAGINA, api_get

BASE = "https://www.universalautomotive.com.br"
SAIDA = Path("catalogos/universal.jsonl")
LIMITE_BUSCA = 2500  # a busca da VTEX não pagina além disso
PRECO_MAXIMO = 100000  # nenhum produto custa mais que isso
MONTADORAS = {"General Motors": "Chevrolet"}  # mesmo nome que a KarHub usa no campo "carro"


def total(fq):
    # um erro aqui faria a faixa inteira ser pulada sem aviso, então insiste como o api_get
    for espera in (5, 15, 30, None):
        page = Fetcher.get(f"{BASE}/api/catalog_system/pub/products/search?{fq}&_from=0&_to=0", stealthy_headers=True)
        if page.status in (200, 206):
            return int((page.headers.get("resources") or "0-0/0").split("/")[-1])
        if espera is None:
            raise RuntimeError(f"HTTP {page.status} contando {fq}")
        time.sleep(espera)


def produtos(fq):
    for inicio in range(0, LIMITE_BUSCA, POR_PAGINA):
        lote = api_get(BASE, f"products/search?{fq}&_from={inicio}&_to={inicio + POR_PAGINA - 1}")
        yield from lote
        if len(lote) < POR_PAGINA:
            return


def filtros(fq, de=0, ate=PRECO_MAXIMO):
    """Divide a busca em faixas de preço até cada parte caber no limite. Por categoria não dá:
    a maior parte dos produtos só está em "Promoções", que sozinha passa de 2500."""
    faixa = f"{fq}&fq={quote(f'P:[{de} TO {ate}]')}"
    n = total(faixa)
    if n <= LIMITE_BUSCA or ate - de < 0.02:
        if n > LIMITE_BUSCA:
            print(f"AVISO {fq} R$ {de}-{ate}: {n} produtos, só os {LIMITE_BUSCA} primeiros serão lidos")
        return [faixa] if n else []
    meio = round((de + ate) / 2, 2)  # as faixas incluem as pontas: o preço do meio sai nas duas
    return filtros(fq, de, meio) + filtros(fq, meio, ate)


def veiculos(produto):
    """Tabela 'VEÍCULOS COMPATÍVEIS' -> 'Volkswagen Gol 1988-1994; Chevrolet Chevette 1973-1982'."""
    ficha = "".join(produto.get("Características Técnicas") or [])
    m = re.search(r"VE[IÍ]CULOS COMPAT[IÍ]VEIS(.*?)</table>", ficha, re.S | re.I)
    if not m:
        return ", ".join(produto.get("Modelo") or []) or None
    partes = []
    for tr in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S)[1:]:  # a primeira linha é o cabeçalho
        celulas = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(celulas) != 6:
            continue
        montadora, _, modelo, _, de, ate = celulas
        anos = "-".join(dict.fromkeys(a for a in (de, ate) if a.isdigit()))
        partes.append(" ".join(filter(None, (MONTADORAS.get(montadora, montadora), modelo, anos))))
    return "; ".join(dict.fromkeys(partes)) or None


def registros(produto):
    for item in produto["items"]:
        imagens = [i["imageUrl"].split("?")[0] for i in item.get("images", [])]
        ref = next((r["Value"] for r in item.get("referenceId") or [] if r.get("Key") == "RefId"), None)
        sku = f"?skuId={item['itemId']}" if len(produto["items"]) > 1 else ""
        if imagens:
            yield {"site": "universal", "url": f"{BASE}/{produto['linkText']}/p{sku}",
                   "nome": produto["productName"], "marca": produto.get("brand"),
                   "codigo_fabricante": ref or produto.get("productReference") or None,
                   "ean": item.get("ean") or None, "imagens": list(dict.fromkeys(imagens)),
                   "carro": veiculos(produto)}


def main():
    marcas = [m for m in api_get(BASE, "brand/list") if m.get("isActive")]
    with ThreadPoolExecutor(max_workers=3) as pool:
        partes = [fq for lista in pool.map(lambda m: filtros(f"fq=B:{m['id']}"), marcas) for fq in lista]
        esperado = sum(pool.map(total, [f"fq=B:{m['id']}" for m in marcas]))
        vistos, sem_foto, gravados = set(), 0, 0
        SAIDA.parent.mkdir(exist_ok=True)
        with SAIDA.open("w", encoding="utf-8") as f:
            for lote in pool.map(lambda fq: list(produtos(fq)), partes):
                for p in lote:
                    if p["productId"] in vistos:
                        continue
                    vistos.add(p["productId"])
                    regs = list(registros(p))
                    sem_foto += not regs
                    gravados += len(regs)
                    for r in regs:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(vistos)} de {esperado} produtos lidos em {len(partes)} buscas; "
          f"{gravados} SKUs com foto, {sem_foto} produtos sem foto -> {SAIDA}")


if __name__ == "__main__":
    main()
