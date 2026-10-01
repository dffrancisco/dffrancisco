"""Partes comuns aos scrapers de lojas VTEX (AutoNext, Hipervarejo...).

Os dados vêm da API pública de catálogo da VTEX. Cada loja só precisa de uma função
`registros(produto)` que transforma um produto da API em um registro por SKU, no
formato do produto.json do auri_scraper.py (com a chave extra "_pasta").
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from scrapling.fetchers import Fetcher

from auri_scraper import ALIAS_MONTADORA

POR_PAGINA = 50  # máximo aceito pela API de busca da VTEX
MOTOR_RE = re.compile(r"\s\d{1,2}\.\d[A-Za-z]?\b")  # cilindrada ("1.6", "1.8S") separa modelo e motor


def api_get(base, path):
    for espera in (5, 15, 30, None):
        page = Fetcher.get(f"{base}/api/catalog_system/pub/{path}", stealthy_headers=True)
        if page.status in (200, 206):  # a busca paginada responde 206
            return json.loads(page.body)
        if espera is None or page.status < 500:
            raise RuntimeError(f"HTTP {page.status} em {path}")
        time.sleep(espera)  # erro 5xx da loja costuma ser passageiro


def produtos_da_marca(base, marca):
    brand = next((b for b in api_get(base, "brand/list") if b["name"].lower() == marca.lower()), None)
    if not brand:
        raise SystemExit(f"marca {marca!r} não encontrada em {base}")
    produtos, inicio = [], 0
    while True:
        lote = api_get(base, f"products/search?fq=B:{brand['id']}&_from={inicio}&_to={inicio + POR_PAGINA - 1}")
        produtos += lote
        if len(lote) < POR_PAGINA:
            return produtos
        inicio += POR_PAGINA


def produto_da_url(base, url):
    """https://<loja>/<slug>/p  ->  dados do produto na API."""
    slug = urlparse(url).path.strip("/").removesuffix("/p")
    resultado = api_get(base, f"products/search/{slug}/p")
    if not resultado:
        raise RuntimeError(f"produto não encontrado: {url}")
    return resultado[0]


def normaliza_montadora(nome):
    """'CHEVROLET / GM', 'GM   CHEVROLET', 'VW-VOLKSWAGEN', 'Mercedes Benz' -> nome padronizado."""
    partes = re.findall(r"[A-ZÀ-Ý]+", nome.upper())
    if len(partes) > 1:
        partes = [p for p in partes if p not in ("GM", "VW")]
    nome = " ".join(partes)
    return {**ALIAS_MONTADORA, "MERCEDES BENZ": "MERCEDES-BENZ"}.get(nome, nome)


def separar_motor(texto):
    """'Astra Sedan Comfort 1.8 Álcool' -> ('Astra Sedan Comfort', '1.8 Álcool')"""
    m = MOTOR_RE.search(texto)
    if m and m.start():
        return texto[:m.start()].strip(), texto[m.start():].strip()
    return texto.strip(), None


def faixas(anos):
    """[1991, 1992, 1993, 2002, 2003] -> [(1991, 1993), (2002, 2003)]"""
    anos = sorted(set(anos))
    if not anos:
        return []
    grupos = [[anos[0]]]
    for ano in anos[1:]:
        if ano == grupos[-1][-1] + 1:
            grupos[-1].append(ano)
        else:
            grupos.append([ano])
    return [(g[0], g[-1]) for g in grupos]


def aplicacoes_por_faixa(montadora, texto, anos):
    """Uma aplicação por faixa contínua de anos (1991-1993 e 2002-2004 viram duas)."""
    veiculo, motor = separar_motor(texto)
    return [{"montadora": montadora, "veiculo": veiculo, "motor": motor, "ano_inicio": inicio, "ano_fim": fim}
            for inicio, fim in faixas(anos) or [(None, None)]]


def mesclar(destino, outro):
    """A mesma peça aparece em mais de um anúncio: junta as aplicações."""
    for campo in ("aplicacoes", "observacoes"):
        for valor in outro[campo]:
            if valor not in destino[campo]:
                destino[campo].append(valor)


def baixar_foto(url):
    # O CDN às vezes recusa conexões por alguns segundos depois de muitas requisições seguidas
    for espera in (5, 20, 60, None):
        try:
            return Fetcher.get(url, headers={"Accept": "image/jpeg,image/png;q=0.9,*/*;q=0.5"})
        except Exception:
            if espera is None:
                raise
            time.sleep(espera)


def baixar_fotos(urls, pasta):
    # Em paralelo: uma foto por vez leva ~1 s cada
    with ThreadPoolExecutor(max_workers=6) as pool:
        respostas = list(pool.map(baixar_foto, urls))
    imagens = []
    for i, (img_url, resp) in enumerate(zip(urls, respostas), 1):
        if resp.status == 200:
            tipo = (resp.headers.get("content-type") or "").split(";")[0].strip()
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
                tipo, Path(urlparse(img_url).path).suffix or ".jpg")
            arquivo = f"foto_{i}{ext}"
            (pasta / arquivo).write_bytes(resp.body)
            imagens.append({"arquivo": arquivo, "url": img_url.split("?")[0], "principal": i == 1})
    return imagens


def executar(doc, base, registros, chave, saida_padrao):
    """Linha de comando comum: URLs e/ou --marca -> uma pasta por SKU + produtos.json."""
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*")
    ap.add_argument("-m", "--marca", help="baixa todos os produtos da marca (ex.: Arteb)")
    ap.add_argument("-o", "--output", default=saida_padrao)
    args = ap.parse_args()
    out = Path(args.output)
    if not args.urls and not args.marca:
        ap.error("informe URLs ou --marca")

    produtos, erros = [], []
    for url in dict.fromkeys(args.urls):
        try:
            produtos.append(produto_da_url(base, url))
        except Exception as e:
            erros.append({"url": url, "erro": str(e)})
            print(f"ERRO {url}: {e}", file=sys.stderr)
    if args.marca:
        da_marca = produtos_da_marca(base, args.marca)
        print(f"{len(da_marca)} produtos encontrados para a marca {args.marca}")
        produtos += da_marca

    pecas, duplicadas = {}, 0
    for produto in {p["productId"]: p for p in produtos}.values():
        for reg in registros(produto):
            k = chave(reg)
            if k in pecas:
                mesclar(pecas[k], reg)
                duplicadas += 1
            else:
                pecas[k] = reg
    print(f"{len(pecas)} SKUs ({duplicadas} repetidos em outros anúncios foram mesclados)")

    indice = []
    for n, reg in enumerate(pecas.values(), 1):
        try:
            pasta = out / reg.pop("_pasta")
            pasta.mkdir(parents=True, exist_ok=True)
            reg["imagens"] = baixar_fotos(reg["imagens"], pasta)
            (pasta / "produto.json").write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
            indice.append({**{k: v for k, v in reg.items() if k != "descricao_html"}, "pasta": pasta.name})
            print(f"[{n}/{len(pecas)}] OK  {reg['nome']} -> {pasta} "
                  f"({len(reg['imagens'])} fotos, {len(reg['aplicacoes'])} aplicações)")
        except Exception as e:  # segue para o próximo SKU
            erros.append({"url": reg["url_origem"], "erro": str(e)})
            print(f"[{n}/{len(pecas)}] ERRO {reg['url_origem']}: {e}", file=sys.stderr)

    # Índice com todas as peças num único arquivo (útil para importação em lote)
    out.mkdir(parents=True, exist_ok=True)
    (out / "produtos.json").write_text(json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
    if erros:
        (out / "erros.json").write_text(json.dumps(erros, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(indice)} ok, {len(erros)} erros. Índice: {out / 'produtos.json'}")
    sys.exit(0 if not erros else 1)
