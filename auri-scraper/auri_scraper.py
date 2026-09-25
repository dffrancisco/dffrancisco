#!/usr/bin/env python3
"""Extrai dados e fotos de peças do site Auri Auto Peças usando Scrapling.

Uso:
    python auri_scraper.py URL [URL ...] [-o pasta_saida]

Para cada URL cria  <saida>/<modelo>/ contendo:
    produto.json   dados da peça (pronto para cadastro no Wayap)
    foto_1.jpg ... fotos em resolução original
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from scrapling.fetchers import Fetcher

APP_RE = re.compile(r"^(?P<veiculo>.+?),\s*(?P<motor>.+?),\s*\(DESDE\s+(?P<de>\d{4})\s+AT[ÉE]\s+(?P<ate>\d{4})\)", re.I)


def clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def meta(page, prop):
    el = page.css(f'#product-container meta[itemprop="{prop}"]')
    return clean(el[0].attrib.get("content")) if el else None


def data_layer(page):
    for script in page.css("script::text").getall():
        m = re.search(r"dataLayer\s*=\s*(\[.*?\]);?\s*$", script, re.S)
        if m:
            try:
                return json.loads(m.group(1))[0]
            except (json.JSONDecodeError, IndexError):
                pass
    return {}


def parse_descricao(page):
    """Separa a descrição em ficha técnica (chave: valor) e lista de aplicações."""
    ficha, aplicacoes, montadora, secao = {}, [], None, "ficha"
    for p in page.css("#descricao p"):
        line = clean(p.get_all_text(separator=" "))
        line = re.sub(r"\s+([,:])", r"\1", line).strip(" ,")
        if not line:
            continue
        if line.upper().startswith("APLICA"):
            secao = "aplicacao"
            continue
        if secao == "ficha":
            if "FICHA T" in line.upper():
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                ficha[clean(k)] = clean(v)
        else:
            m = APP_RE.match(line)
            if m:
                aplicacoes.append({
                    "montadora": montadora,
                    "veiculo": m["veiculo"].strip(),
                    "motor": m["motor"].strip(),
                    "ano_inicio": int(m["de"]),
                    "ano_fim": int(m["ate"]),
                })
            else:  # linha só com o nome da montadora (ex.: CHEVROLET)
                montadora = line
    return ficha, aplicacoes


def fotos(page):
    urls = page.css(".image-thumbs img::attr(src)").getall() or page.css("#mainImage::attr(src)").getall()
    # Remove o prefixo de miniatura (ex.: "180_") para obter a imagem original
    full = [re.sub(r"/(\d+)_([^/]+)$", r"/\2", u) for u in urls]
    return list(dict.fromkeys(full))


def scrape(url, out_root):
    page = Fetcher.get(url, stealthy_headers=True)
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status} em {url}")

    dl = data_layer(page)
    ficha, aplicacoes = parse_descricao(page)
    nome = clean(page.css("h4.name-product-large::text").get()) or dl.get("nameProduct")
    modelo = meta(page, "model") or dl.get("model")
    preco = dl.get("priceSell") or dl.get("price")

    pasta = out_root / (modelo or urlparse(url).path.strip("/").replace("/", "_"))
    pasta.mkdir(parents=True, exist_ok=True)

    imagens = []
    for i, img_url in enumerate(fotos(page), 1):
        # Sem este Accept o CDN devolve WebP; pedimos JPEG/PNG por compatibilidade
        resp = Fetcher.get(img_url, headers={"Accept": "image/jpeg,image/png;q=0.9,*/*;q=0.5"})
        if resp.status == 200:
            tipo = (resp.headers.get("content-type") or "").split(";")[0].strip()
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
                tipo, Path(urlparse(img_url).path).suffix or ".jpg")
            arquivo = f"foto_{i}{ext}"
            (pasta / arquivo).write_bytes(resp.body)
            imagens.append({"arquivo": arquivo, "url": img_url, "principal": i == 1})

    produto = {
        "nome": nome,
        "descricao_curta": meta(page, "description"),
        "marca": dl.get("brand") or ficha.get("MARCA"),
        "codigo_fabricante": modelo or ficha.get("CÓDIGO DO FABRICANTE"),
        "ean": meta(page, "gtin14") or dl.get("EAN"),
        "sku": meta(page, "sku") or dl.get("idProduct"),
        "referencia": dl.get("reference"),
        "categoria": dl.get("category"),
        "preco": float(preco) if preco else None,
        "moeda": "BRL",
        "disponivel": dl.get("availability") == "YES",
        "ficha_tecnica": {k: v for k, v in ficha.items()
                          if k not in ("MARCA", "CÓDIGO DO FABRICANTE", "CÓDIGO DE BARRAS")},
        "aplicacoes": aplicacoes,
        "descricao_html": page.css("#descricao").get() if page.css("#descricao") else None,
        "imagens": imagens,
        "url_origem": url,
    }
    (pasta / "produto.json").write_text(json.dumps(produto, ensure_ascii=False, indent=2), encoding="utf-8")
    return pasta, produto


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("-o", "--output", default="pecas")
    args = ap.parse_args()
    out = Path(args.output)
    ok = True
    for url in args.urls:
        try:
            pasta, prod = scrape(url, out)
            print(f"OK  {prod['nome']} -> {pasta} ({len(prod['imagens'])} fotos, {len(prod['aplicacoes'])} aplicações)")
        except Exception as e:  # segue para a próxima URL
            ok = False
            print(f"ERRO {url}: {e}", file=sys.stderr)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
