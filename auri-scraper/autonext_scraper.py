#!/usr/bin/env python3
"""Extrai dados e fotos de peças do site AutoNext (VTEX) usando Scrapling.

Uso:
    python autonext_scraper.py URL [URL ...] [-o pasta_saida]
    python autonext_scraper.py --marca Arteb

Os dados vêm da API pública de catálogo da VTEX. Cada produto do site tem uma ou
mais variações (SKU), ex.: lado direito/esquerdo, cada uma com EAN, código e fotos
próprios. Por isso é gerada uma pasta por SKU, no mesmo formato do auri_scraper.py:
    <saida>/<slug-do-produto>-<codigo>/produto.json
    <saida>/<slug-do-produto>-<codigo>/foto_1.jpg ...
"""
import html
import re

from auri_scraper import clean
from vtex import aplicacoes_por_faixa, executar, normaliza_montadora

BASE = "https://www.autonext.com.br"

# Especificações que já viram campos próprios do JSON ou que são internas do ERP da loja
IGNORAR_SPECS = {"Fabricante", "EAN / GTIN", "Código do fabricante", "Modelo Veículo Compatível",
                 "Montadora Veículo Compatível", "Veículo Compatível", "Detalhes da Garantia",
                 "Códigos Alternativos Automáticos - ERP", "Apelidos Automáticos - ERP"}
# "Astra 2.0 Gasolina 2003, 2004."  /  "Onix Hatch LT 2012 2013 2014"  /  "Voyage 1.8 1989, 199." (cortado)
APLICACAO_RE = re.compile(r"^(?P<veiculo>.+?)[\s,]+(?P<anos>(?:(?:19|20)\d{2}[\s,.]*)+)(?:\d{1,3}\.?)?$")
FIM_APLICACOES_RE = re.compile(r"^(Fundada em|Fuja dos|Procurando|A AutoNext)", re.I)


def parse_aplicacoes(descricao, montadora):
    """Lê o bloco 'Este produto é compatível com os seguintes automóveis:' da descrição."""
    m = re.search(r"seguintes autom[óo]veis:?(.*)", descricao or "", re.S | re.I)
    if not m:
        return [], []
    raw = re.sub(r"<(br|hr)\b[^>]*>|</?(p|div|li|h\d)\b[^>]*>", "\n", m.group(1), flags=re.I)
    linhas = [clean(l) for l in html.unescape(re.sub(r"<[^>]+>", " ", raw)).split("\n")]
    aplicacoes, observacoes = [], []
    for linha in filter(None, linhas):
        if FIM_APLICACOES_RE.match(linha):  # texto institucional depois da lista
            break
        m = APLICACAO_RE.match(linha)
        if m:
            anos = [int(a) for a in re.findall(r"(?:19|20)\d{2}", m["anos"])]
            aplicacoes += aplicacoes_por_faixa(montadora, m["veiculo"].strip(" ,"), anos)
        elif "OBS" in linha.upper():
            observacoes.append(linha.strip("* "))
        elif len(linha.split()) <= 3 and ":" not in linha and not re.search(r"\d", linha):
            montadora = normaliza_montadora(linha)  # cabeçalho "CHEVROLET", "Volkswagen"...
    return aplicacoes, observacoes


def codigo_fabricante(produto, item):
    # RefId do SKU termina com o código do fabricante: "...-Direito-[A-160.818]"
    m = re.search(r"\[A-([\d.]+)\]$", item["referenceId"][0]["Value"] if item.get("referenceId") else "")
    if m:
        return m[1].replace(".", "")
    codigos = produto.get("Código do fabricante") or []
    if len(produto["items"]) == 1 and len(codigos) == 1 and "," not in codigos[0]:
        return codigos[0].strip()
    return None


def ficha_tecnica(produto, item):
    ficha = {nome.upper(): ", ".join(produto[nome]).upper()
             for nome in produto.get("allSpecifications", []) if nome not in IGNORAR_SPECS and produto.get(nome)}
    for var in item.get("variations", []):  # ex.: LADO: DIREITO (PASSAGEIRO)
        ficha[var.upper()] = ", ".join(item[var]).upper()
    return ficha


def registros(produto):
    """Um registro (sem fotos baixadas ainda) por SKU do produto."""
    montadoras = produto.get("Montadora Veículo Compatível") or []
    aplicacoes, observacoes = parse_aplicacoes(
        produto.get("description"), normaliza_montadora(montadoras[0]) if len(montadoras) == 1 else None)
    categoria = produto["categories"][0].strip("/") if produto.get("categories") else None
    for item in produto["items"]:
        if item["name"].upper().startswith("INATIVO"):  # SKU desativado pela loja (sem nome/preço)
            continue
        oferta = item["sellers"][0]["commertialOffer"] if item.get("sellers") else {}
        codigo = codigo_fabricante(produto, item)
        yield {
            "nome": item.get("nameComplete") or produto["productName"],
            "descricao_curta": produto.get("metaTagDescription"),
            "marca": produto.get("brand"),
            "codigo_fabricante": codigo,
            "ean": item.get("ean") or None,
            "sku": item["itemId"],
            "referencia": item["referenceId"][0]["Value"] if item.get("referenceId") else None,
            "categoria": categoria,
            "preco": oferta.get("Price") or None,
            "moeda": "BRL",
            "disponivel": bool(oferta.get("IsAvailable") and oferta.get("AvailableQuantity")),
            "ficha_tecnica": ficha_tecnica(produto, item),
            "aplicacoes": list(aplicacoes),
            "observacoes": list(observacoes),
            "descricao_html": produto.get("description"),
            "imagens": [img["imageUrl"] for img in item.get("images", [])],
            "url_origem": f"{produto['link']}?skuId={item['itemId']}",
            "_pasta": f"{produto['linkText']}-{codigo or item['itemId']}",
        }


if __name__ == "__main__":
    # a mesma peça (mesmo EAN) aparece em mais de um anúncio
    executar(__doc__, BASE, registros, lambda r: r["ean"] or r["sku"], "pecas_autonext")
