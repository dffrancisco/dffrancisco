#!/usr/bin/env python3
"""Baixa as fotos só das peças dos catálogos que casam com produtos SEM foto do Wayap.

Uso (mesmas variáveis WAYAP_* do wayap_fotos.py):
    python catalogo_para_pecas.py karhub carblue shoppecas clicpecas fuscaopreto

Lê catalogos/<site>.jsonl (metadados gerados pelos catalogo_<site>.py), casa com as mesmas
regras do wayap_fotos.py e grava pecas_<site>/<slug>/produto.json + foto_N, no formato das
outras pastas de peças. Depois é só rodar `wayap_fotos.py planejar --fontes ...`.
"""
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from scrapling.fetchers import Fetcher

from wayap_fotos import Wayap, casar, n_codigo, n_ean, n_marca


def slug(url):
    ultimo = re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.lower()).strip("-")[-80:] or "produto"
    return f"{ultimo}-{hashlib.md5(url.encode()).hexdigest()[:6]}"


def identidade(c):
    """Mesma peça: variantes da ShopPeças repetem URL, EAN e fotos; as da CarBlue (lado D/E) só a URL."""
    return f"{c['url']}|{c.get('ean')}|{c.get('codigo_fabricante')}|{c['imagens'][0]}"


def pastas_por_peca(catalogo, indices):
    """Nome da pasta de cada peça: o slug da URL, com sufixo só quando a URL tem mais de uma peça."""
    por_url = defaultdict(dict)
    for i in indices:
        por_url[catalogo[i]["url"]].setdefault(identidade(catalogo[i]), i)
    pastas = {}
    for url, pecas in por_url.items():
        for ident, i in pecas.items():
            sufixo = f"-{hashlib.md5(ident.encode()).hexdigest()[:4]}" if len(pecas) > 1 else ""
            pastas[i] = slug(url) + sufixo
    return pastas


def baixar(url):
    for espera in (5, 15, 30, None):
        try:
            r = Fetcher.get(url, headers={"Accept": "image/jpeg,image/png;q=0.9,*/*;q=0.5"}, timeout=60)
            if r.status == 200:
                return r
        except Exception:
            pass
        if espera is None:
            return None
        time.sleep(espera)


def gravar_peca(site, c, nome_pasta):
    pasta = Path(f"pecas_{site}") / nome_pasta
    if (pasta / "produto.json").exists():
        return pasta
    pasta.mkdir(parents=True, exist_ok=True)
    imagens = []
    for i, url in enumerate(c["imagens"], 1):
        r = baixar(url)
        if not r:
            continue
        tipo = (r.headers.get("content-type") or "").split(";")[0].strip()
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(tipo, ".jpg")
        (pasta / f"foto_{i}{ext}").write_bytes(r.body)
        imagens.append({"arquivo": f"foto_{i}{ext}", "url": url, "principal": i == 1})
    produto = {"nome": c.get("nome"), "marca": c.get("marca"), "codigo_fabricante": c.get("codigo_fabricante"),
               "ean": c.get("ean"), "carro": c.get("carro"), "imagens": imagens, "url_origem": c["url"]}
    (pasta / "produto.json").write_text(json.dumps(produto, ensure_ascii=False, indent=2), encoding="utf-8")
    return pasta


def main():
    sites = sys.argv[1:]
    if not sites:
        raise SystemExit(__doc__)
    wayap = Wayap()
    produtos = [p for p in {p["cod_produto"]: p for p in wayap.produtos()}.values() if not (p["foto"] or "").strip()]
    print(f"{len(produtos)} produtos sem foto no Wayap")
    for site in sites:
        arq = Path(f"catalogos/{site}.jsonl")
        if not arq.exists():
            print(f"{site}: {arq} não existe, pulando")
            continue
        catalogo = [json.loads(l) for l in arq.open(encoding="utf-8") if l.strip()]
        catalogo = [c for c in catalogo if c.get("imagens") and c.get("url")]
        registros = [{"fonte": site, "pasta": c["url"], "nome": c.get("nome") or "", "marca": n_marca(c.get("marca")),
                      "codigo": n_codigo(c.get("codigo_fabricante")), "ean": n_ean(c.get("ean")),
                      "imagens": c["imagens"], "url": c["url"]} for c in catalogo]
        casados, revisar = casar(produtos, registros)
        # uma pasta por peça (não por linha do catálogo): senão duas threads gravam no mesmo produto.json
        pastas = pastas_por_peca(catalogo, sorted({i for _, aceitos in casados for i in aceitos}))
        usados = list(pastas)
        print(f"{site}: {len(catalogo)} peças no catálogo, {len(casados)} produtos casados "
              f"({len(usados)} peças para baixar), {len(revisar)} para revisar")
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda i: gravar_peca(site, catalogo[i], pastas[i]), usados))


if __name__ == "__main__":
    main()
