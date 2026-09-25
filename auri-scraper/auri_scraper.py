#!/usr/bin/env python3
"""Extrai dados e fotos de peças do site Auri Auto Peças usando Scrapling.

Uso:
    python auri_scraper.py URL [URL ...] [-o pasta_saida]
    python auri_scraper.py --marca Arteb

Para cada URL cria  <saida>/<slug-da-url>/ contendo:
    produto.json   dados da peça (pronto para cadastro no Wayap)
    foto_1.jpg ... fotos em resolução original
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from scrapling.fetchers import Fetcher


# "(DESDE 2006 ATÉ 2014)", "(DESDE 2012 EM DIANTE)", "(2014 - 2016)", "(2011...)", "(2012)"
ANOS_RE = re.compile(r"\(?\s*(?:DESDE\s+)?(?P<de>(?:19|20)\d{2})\s*(?:(?:AT[ÉE]|À|A|-|–|/)\s*"
                     r"(?P<ate>(?:19|20)\d{2})|(?P<diante>EM\s+DIANTE|\.{2,}|\+))?\s*\)", re.I)
# "FORD KA 2005" (uma linha por ano) ou "KIA PICANTO 2011..." (de 2011 em diante)
ANO_FINAL_RE = re.compile(r"^(?P<veiculo>.+?)\s+(?P<ano>(19|20)\d{2})(?P<mais>\s*(\.{2,}|…|\+|EM DIANTE))?$", re.I)
# Cabeçalho que abre a lista de aplicações ("APLICAÇÃO:", "APLICAÇAÕ", "APLICAÇÕES")
APLICACAO_RE = re.compile(r"^APLICA\w*\s*:?\s*$", re.I)
RODAPE_RE = re.compile(r"para mais informa|combine o envio|whatsapp|^sobre a marca", re.I)
# Títulos de seção que aparecem como "chave:" mas não são dados da ficha
TITULOS = {"DESCRIÇÃO", "DESCRICAO", "ESPECIFICAÇÕES TÉCNICAS", "ESPECIFICACOES TECNICAS", "INFORMAÇÕES TÉCNICAS"}
MONTADORAS = {"CHEVROLET", "GM", "VOLKSWAGEN", "VW", "FIAT", "FORD", "HYUNDAI", "RENAULT", "TOYOTA",
              "HONDA", "NISSAN", "PEUGEOT", "CITROEN", "CITROËN", "KIA", "MITSUBISHI", "JEEP",
              "MERCEDES", "MERCEDES-BENZ", "MB", "BMW", "AUDI", "CHERY", "JAC", "SUZUKI", "DODGE",
              "CHRYSLER", "IVECO", "SCANIA", "VOLVO", "AGRALE", "TROLLER", "SUBARU", "MAZDA", "SEAT",
              "LIFAN", "EFFA", "CAOA", "BYD", "RAM", "YAMAHA"}
# Cabeçalhos da ficha nos diferentes formatos usados pelo site -> chave padronizada
CHAVES = {"CÓDIGO DO FABRICANTE": "codigo_fabricante", "CODIGO DO FABRICANTE": "codigo_fabricante",
          "CÓDIGO DE FÁBRICA": "codigo_fabricante", "CODIGO DE FABRICA": "codigo_fabricante",
          "CÓDIGO DE BARRAS": "ean", "CODIGO DE BARRAS": "ean", "MARCA": "marca"}


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


def linhas_descricao(page):
    """Texto da descrição quebrado por elementos de bloco (p, br, div, hr, li)."""
    el = page.css("#descricao")
    if not el:
        return []
    raw = re.sub(r"<(style|script)\b.*?</\1>", "", el[0].get(), flags=re.S | re.I)
    raw = re.sub(r"<(br|hr)\b[^>]*>|</?(p|div|li|h\d)\b[^>]*>", "\n", raw, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return [re.sub(r"\s+([,:])", r"\1", clean(l)).strip(" ,") for l in text.split("\n") if clean(l).strip(" ,")]


ALIAS_MONTADORA = {"GM": "CHEVROLET", "VW": "VOLKSWAGEN", "CITROËN": "CITROEN",
                   "MB": "MERCEDES-BENZ", "MERCEDES": "MERCEDES-BENZ"}


def separar_montadora(texto, montadora):
    partes = texto.split(" ", 1)
    if len(partes) == 2 and partes[0].upper() in MONTADORAS:
        return ALIAS_MONTADORA.get(partes[0].upper(), partes[0].upper()), partes[1].strip()
    return montadora, texto


def parse_aplicacoes(linhas):
    aplicacoes, observacoes, montadora, buffer = [], [], None, []
    por_ano = {}  # formato "HYUNDAI HB20 HATCH 2012" (uma linha por ano)
    for linha in linhas:
        if RODAPE_RE.search(linha):  # texto de atendimento da loja, não é dado da peça
            break
        if linha.upper() in MONTADORAS:
            montadora, buffer = ALIAS_MONTADORA.get(linha.upper(), linha.upper()), []
            continue
        if linha[0] in "({" and linha[-1] in ")}" and not ANOS_RE.search(linha):
            observacoes.append(linha.strip("(){}").replace("} {", "; "))
            continue
        m = ANO_FINAL_RE.match(linha)
        if m:
            observacoes += buffer
            buffer = []
            mont, veiculo = separar_montadora(m["veiculo"], montadora)
            anos = por_ano.setdefault((mont, veiculo), [])
            anos.append(int(m["ano"]))
            if m["mais"]:
                anos.append(None)  # sem ano final: "em diante"
            continue
        buffer.append(linha)
        anos = ANOS_RE.search(linha)
        if not anos:
            continue
        texto = ANOS_RE.sub("", " ".join(buffer)).strip(" ,")
        buffer = []
        partes = [clean(x) for x in texto.split(",") if clean(x)]
        mont, veiculo = separar_montadora(partes[0] if partes else "", montadora)
        aplicacoes.append({"montadora": mont, "veiculo": veiculo,
                           "motor": ", ".join(partes[1:]) or None,
                           "ano_inicio": int(anos["de"]),
                           "ano_fim": None if anos["diante"] else int(anos["ate"] or anos["de"])})
    for (mont, veiculo), anos in por_ano.items():
        validos = [a for a in anos if a]
        aplicacoes.append({"montadora": mont, "veiculo": veiculo, "motor": None, "ano_inicio": min(validos),
                           "ano_fim": None if None in anos else max(validos)})
    # Sobras curtas são notas ("FUMÊ", "MÁSCARA NEGRA"); parágrafos longos ficam só em descricao_texto
    observacoes += [b for b in buffer if len(b) <= 80]
    return aplicacoes, observacoes


def parse_descricao(page):
    """Separa a descrição em dados básicos, ficha técnica (chave: valor) e aplicações."""
    linhas = linhas_descricao(page)
    idx = next((i for i, l in enumerate(linhas) if APLICACAO_RE.match(l)), None)
    if idx is None:  # "APLICAÇÃO: conteúdo" na mesma linha
        idx = next((i for i, l in enumerate(linhas) if l.upper().startswith("APLICAÇÃO:")), len(linhas))
    basicos, ficha, i = {}, {}, 0
    ficha_linhas = linhas[:idx]
    while i < len(ficha_linhas):
        linha = ficha_linhas[i]
        if ":" in linha:
            chave, valor = (clean(x) for x in linha.split(":", 1))
            chave_up = chave.upper()
            if chave_up in TITULOS or "FICHA T" in chave_up:
                i += 1
                continue
            # valor na linha seguinte ("Marca:" / "Arteb")
            if not valor and i + 1 < len(ficha_linhas) and ":" not in ficha_linhas[i + 1]:
                i += 1
                valor = ficha_linhas[i]
            if chave and valor:
                if chave_up in ("CÓDIGO", "CODIGO", "CÓDIGO SIMILAR", "CÓDIGO EQUIVALENTE"):
                    # códigos de outras marcas para a mesma peça (ex.: "23111 AMPRI")
                    basicos.setdefault("codigos_equivalentes", []).append(valor)
                elif chave_up in CHAVES:
                    basicos[CHAVES[chave_up]] = valor
                else:
                    ficha[chave_up] = valor.upper()
        i += 1
    resto = linhas[idx:]
    if resto:  # a própria linha "APLICAÇÃO:" pode já trazer conteúdo depois dos dois pontos
        resto = ([resto[0].split(":", 1)[1].strip()] if ":" in resto[0] else []) + resto[1:]
    aplicacoes, observacoes = parse_aplicacoes([l for l in resto if l])
    if not aplicacoes:
        # Algumas peças listam as aplicações sob outro título (ex.: "DESCRIÇÃO:")
        aplicacoes, _ = parse_aplicacoes(linhas)
    return basicos, ficha, aplicacoes, observacoes


def texto_descricao(page):
    """Descrição em texto puro, sem o rodapé de atendimento da loja."""
    linhas = []
    for linha in linhas_descricao(page):
        if RODAPE_RE.search(linha):
            break
        linhas.append(linha)
    return "\n".join(linhas)


def fotos(page):
    urls = page.css(".image-thumbs img::attr(src)").getall() or page.css("#mainImage::attr(src)").getall()
    # Remove o prefixo de miniatura (ex.: "180_") para obter a imagem original
    full = [re.sub(r"/(\d+)_([^/]+)$", r"/\2", u) for u in urls]
    return list(dict.fromkeys(full))


BASE = "https://www.auriautopecas.com.br"


def urls_da_marca(marca):
    """Percorre todas as páginas da listagem da marca e devolve as URLs dos produtos."""
    urls, pg = [], 1
    while True:
        # Após a última página o site redireciona (302) para "sem resultados"
        page = Fetcher.get(f"{BASE}/{marca.lower()}?pg={pg}", stealthy_headers=True, follow_redirects=False)
        novos = [u for u in page.css(".product-custom > meta[itemprop='url']::attr(href)").getall()
                 if u not in urls]
        if page.status != 200 or not novos:
            return urls
        urls += novos
        pg += 1


class NaoEProduto(Exception):
    """A URL é uma categoria/página institucional, não um produto."""


def slug(texto):
    import unicodedata
    texto = unicodedata.normalize("NFKD", texto or "sem-marca").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-") or "sem-marca"


def scrape(url, out_root, por_marca=False):
    page = Fetcher.get(url, stealthy_headers=True)
    if page.status != 200:
        raise RuntimeError(f"HTTP {page.status} em {url}")
    if not page.css("#product-container"):
        raise NaoEProduto(url)

    dl = data_layer(page)
    basicos, ficha, aplicacoes, observacoes = parse_descricao(page)
    nome = clean(page.css("h4.name-product-large::text").get()) or dl.get("nameProduct")
    marca = dl.get("brand") or basicos.get("marca")
    # Em muitas peças o campo "modelo" do site vem com a marca; o código real está na descrição
    modelo = basicos.get("codigo_fabricante") or meta(page, "model") or dl.get("model")
    if modelo and marca and modelo.upper() == marca.upper():
        modelo = None
    preco = dl.get("priceSell") or dl.get("price")

    pasta = out_root / (slug(marca) if por_marca else "") / urlparse(url).path.strip("/").split("/")[-1]
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
        "marca": marca,
        "codigo_fabricante": modelo,
        "ean": meta(page, "gtin14") or dl.get("EAN") or basicos.get("ean"),
        "sku": meta(page, "sku") or dl.get("idProduct"),
        "referencia": dl.get("reference"),
        "categoria": dl.get("category"),
        "preco": float(preco) if preco else None,
        "moeda": "BRL",
        "disponivel": dl.get("availability") == "YES",
        "codigos_equivalentes": basicos.get("codigos_equivalentes", []),
        "ficha_tecnica": ficha,
        "aplicacoes": aplicacoes,
        "observacoes": observacoes,
        "descricao_texto": texto_descricao(page),
        "descricao_html": page.css("#descricao").get() if page.css("#descricao") else None,
        "imagens": imagens,
        "url_origem": url,
    }
    (pasta / "produto.json").write_text(json.dumps(produto, ensure_ascii=False, indent=2), encoding="utf-8")
    return pasta, produto


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*")
    ap.add_argument("-m", "--marca", help="baixa todos os produtos da marca (ex.: Arteb)")
    ap.add_argument("-o", "--output", default="pecas")
    args = ap.parse_args()
    out = Path(args.output)
    urls = list(args.urls)
    if args.marca:
        urls += urls_da_marca(args.marca)
        print(f"{len(urls)} produtos encontrados para a marca {args.marca}")
    if not urls:
        ap.error("informe URLs ou --marca")

    produtos, erros = [], []
    for n, url in enumerate(dict.fromkeys(urls), 1):
        try:
            pasta, prod = scrape(url, out)
            produtos.append({**{k: v for k, v in prod.items() if k != "descricao_html"}, "pasta": pasta.name})
            print(f"[{n}/{len(urls)}] OK  {prod['nome']} -> {pasta} "
                  f"({len(prod['imagens'])} fotos, {len(prod['aplicacoes'])} aplicações)")
        except Exception as e:  # segue para a próxima URL
            erros.append({"url": url, "erro": str(e)})
            print(f"[{n}/{len(urls)}] ERRO {url}: {e}", file=sys.stderr)

    # Índice com todas as peças num único arquivo (útil para importação em lote)
    out.mkdir(parents=True, exist_ok=True)
    (out / "produtos.json").write_text(json.dumps(produtos, ensure_ascii=False, indent=2), encoding="utf-8")
    if erros:
        (out / "erros.json").write_text(json.dumps(erros, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(produtos)} ok, {len(erros)} erros. Índice: {out / 'produtos.json'}")
    sys.exit(0 if not erros else 1)


if __name__ == "__main__":
    main()
