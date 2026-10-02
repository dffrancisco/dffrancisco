#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da AZ Acessórios (loja Wake Commerce), por marca.

Uso:
    python catalogo_azacessorios.py                          # Loma Plast -> catalogos/azacessorios.jsonl
    python catalogo_azacessorios.py --marca "Loma Plast" --marca Loma

Lê a API GraphQL da vitrine Wake (storefront-api.fbits.net) com o token público que vem no HTML,
filtrando pelo id da marca. A loja tem duas marcas para o mesmo fabricante: "Loma Plast" e "Loma".

O SKU da loja só traz o código do fabricante nas peças "LPLHT-01008013" (-> LHT01008013, mesmo
formato do Auri); os outros ("206513", "LP932") são códigos internos e ficam null. EANs começados
em 99 também são da loja (9900000...), não do fabricante. Fotos vêm em 1200x1200 sem os
parâmetros de tamanho. A aplicação sai do bloco "Compatível com: Montadora" da descrição.

Uma linha por variação (lado direito/esquerdo...) com foto:
    {"site", "url", "nome", "marca", "codigo_fabricante", "ean", "imagens", "carro"}
"""
import argparse
import html
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import requests

LOJA = "https://www.azacessorios.com.br"
API = "https://storefront-api.fbits.net/graphql"
TOKEN_CONHECIDO = "tcs_lojaa_7efca79d97c742188dbde0c69ddaa15d"  # visto no HTML em 2026-10
SAIDA = Path("catalogos/azacessorios.jsonl")
POR_PAGINA = 50  # máximo aceito pela API
ESPERAS = (5, 15, 30, 60)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
MONTADORAS = {"VOLSKWAGEN": "Volkswagen", "CHEVEOLET": "Chevrolet", "RENAUT": "Renault", "CITROËN": "Citroen",
              "MERCEDES BENZ": "Mercedes-Benz"}

PRODUTOS = """query($filtros: ProductExplicitFiltersInput!, $depois: String) {
  products(first: %d, after: $depois, filters: $filtros, sortKey: NAME) {
    totalCount pageInfo { hasNextPage endCursor }
    nodes { productVariantId productName variantName aliasComplete sku ean
            productBrand { name } images { url order } informations { value } } } }""" % POR_PAGINA


class Api:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Origin": LOJA, "Referer": LOJA + "/"})
        try:
            m = re.search(r'storefrontAccessToken\s*:\s*"(tcs_\w+)"', self.s.get(LOJA + "/", timeout=60).text)
            token = m.group(1) if m else TOKEN_CONHECIDO
        except requests.RequestException:
            token = TOKEN_CONHECIDO
        self.s.headers.update({"Content-Type": "application/json", "TCS-Access-Token": token})

    def __call__(self, query, **variaveis):
        for espera in (*ESPERAS, None):
            try:
                r = self.s.post(API, json={"query": query, "variables": variaveis}, timeout=90)
                if r.status_code == 200 and "errors" not in r.json():
                    return r.json()["data"]
                erro = f"HTTP {r.status_code} {r.text[:200]}"
            except (requests.RequestException, ValueError) as e:
                erro = str(e)
            if espera is None:
                raise RuntimeError(f"API da Wake falhou: {erro}")
            print(f"  {erro} -> nova tentativa em {espera}s")
            time.sleep(espera)

    def id_da_marca(self, nome):
        # A lista de marcas da API omite algumas ("Loma" não aparece); a busca acha pelos produtos.
        achadas = self('query($n: [String]) { brands(first: 5, brandInput: {names: $n}) { nodes { brandId name } } }',
                       n=[nome])["brands"]["nodes"]
        achadas += [p["productBrand"] for p in self('query($q: String!) { search(query: $q) { products(first: 50) '
                                                    '{ nodes { productBrand { brandId: id name } } } } }',
                                                    q=nome)["search"]["products"]["nodes"]]
        return next((m["brandId"] for m in achadas if m["name"].casefold() == nome.casefold()), None)

    def produtos(self, marca_id):
        depois = None
        while True:
            pg = self(PRODUTOS, filtros={"brandId": [marca_id]}, depois=depois)["products"]
            yield from pg["nodes"]
            if not pg["pageInfo"]["hasNextPage"]:
                return
            depois = pg["pageInfo"]["endCursor"]
            time.sleep(0.5)


def linhas(valor):
    raw = re.sub(r"<(br|hr)\b[^>]*>|</?(p|div|li|h\d)\b[^>]*>", "\n", valor or "", flags=re.I)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " ")
    return [l for l in (re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")) if l]


def ean(valor):
    d = re.sub(r"\D", "", valor or "")
    if len(d) != 13 or d.startswith("99"):  # 99...: numeração interna da loja
        return None
    return d if sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d)) % 10 == 0 else None


def codigo_fabricante(sku):
    m = re.fullmatch(r"LP(LHT)-?([0-9A-Z][0-9A-Z-]*)", (sku or "").strip(), re.I)
    return f"LHT{m.group(2).upper()}" if m else None


def veiculos(ls):
    """'Compatível com: Chevrolet' + '- Corsa 2004', '- Corsa 2005'... -> 'Chevrolet Corsa 2004-2012'."""
    anos, montadora = defaultdict(set), None
    for l in ls:
        m = re.match(r"(?:Compat[ií]vel com|Modelos Compat[ií]veis)\s*:\s*(.+)", l, re.I)
        if m:
            nome = m.group(1).strip()
            montadora = MONTADORAS.get(nome.upper(), nome if not nome.isupper() else nome.title())
            continue
        if montadora is None:
            continue
        m = re.match(r"-\s*(.+?)\s+((?:19|20)\d\d)$", l)
        if not m:
            if anos:
                break  # fim da lista de modelos
            continue
        anos[f"{montadora} {m.group(1)}"].add(int(m.group(2)))
    return "; ".join(f"{v} {min(a)}-{max(a)}" if len(a) > 1 else f"{v} {min(a)}" for v, a in anos.items()) or None


def registro(p):
    imagens = [i["url"].split("?")[0] for i in sorted(p.get("images") or [], key=lambda i: i["order"]) if i.get("url")]
    if not imagens:
        return None
    ls = [l for i in p.get("informations") or [] for l in linhas(i.get("value"))]
    return {"site": "azacessorios", "url": f"{LOJA}/{p['aliasComplete']}",
            "nome": (p.get("variantName") or p["productName"]).strip(), "marca": p["productBrand"]["name"],
            "codigo_fabricante": codigo_fabricante(p.get("sku")), "ean": ean(p.get("ean")),
            "imagens": list(dict.fromkeys(imagens)), "carro": veiculos(ls)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--marca", action="append", help='nome da marca na loja (repetível; padrão "Loma Plast")')
    ap.add_argument("-o", "--saida", type=Path, default=SAIDA)
    args = ap.parse_args()
    api = Api()
    vistos, gravados, sem_foto = set(), 0, 0
    args.saida.parent.mkdir(exist_ok=True)
    with args.saida.open("w", encoding="utf-8") as f:
        for nome in args.marca or ["Loma Plast"]:
            marca_id = api.id_da_marca(nome)
            if marca_id is None:
                print(f"marca {nome!r} não encontrada na loja")
                continue
            n = 0
            for p in api.produtos(marca_id):
                if p["productVariantId"] in vistos:
                    continue
                vistos.add(p["productVariantId"])
                n += 1
                reg = registro(p)
                if reg is None:
                    sem_foto += 1
                    continue
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
                gravados += 1
            print(f"{nome} (id {marca_id}): {n} variações")
    print(f"{gravados} gravadas, {sem_foto} sem foto -> {args.saida}")


if __name__ == "__main__":
    main()
