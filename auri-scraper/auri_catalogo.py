#!/usr/bin/env python3
"""Baixa o catálogo inteiro da Auri Auto Peças (todas as marcas).

Uso:
    python auri_catalogo.py [-o pasta_saida] [-j processos]

Lê as URLs do sitemap do site, ignora páginas que não são produto e grava
<saida>/<marca>/<slug-da-peça>/produto.json + fotos. Pode ser interrompido e
executado de novo: as peças já baixadas (registradas em _estado.jsonl) são puladas.
No final gera <saida>/<marca>/produtos.json, <saida>/produtos.json e <saida>/resumo.json.
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

from scrapling.fetchers import Fetcher

from auri_scraper import BASE, NaoEProduto, scrape

SITEMAP = f"{BASE}/sitemap.xml"


def urls_sitemap():
    idx = Fetcher.get(SITEMAP)
    urls = []
    for sm in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", idx.body.decode("latin-1")):
        page = Fetcher.get(sm)
        urls += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", page.body.decode("latin-1"))
    return list(dict.fromkeys(u for u in urls if u.rstrip("/") != BASE))


def carregar_estado(arquivo):
    estado = {}
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            try:
                reg = json.loads(linha)
                estado[reg["url"]] = reg
            except (json.JSONDecodeError, KeyError):
                pass
    return estado


def trabalhar(args):
    url, out = args
    for tentativa in range(3):
        try:
            pasta, prod = scrape(url, Path(out), por_marca=True)
            return {"url": url, "status": "ok", "pasta": str(pasta.relative_to(out)),
                    "marca": prod["marca"], "fotos": len(prod["imagens"]), "aplicacoes": len(prod["aplicacoes"])}
        except NaoEProduto:
            return {"url": url, "status": "nao_produto"}
        except Exception as e:  # rede instável: tenta de novo com espera crescente
            erro = str(e)[:300]
            time.sleep(2 ** tentativa)
    return {"url": url, "status": "erro", "erro": erro}


def gerar_indices(out, estado):
    por_marca = {}
    for reg in estado.values():
        if reg["status"] != "ok":
            continue
        arq = out / reg["pasta"] / "produto.json"
        if not arq.exists():
            continue
        prod = json.loads(arq.read_text(encoding="utf-8"))
        prod.pop("descricao_html", None)
        prod["pasta"] = reg["pasta"]
        por_marca.setdefault(Path(reg["pasta"]).parts[0], []).append(prod)

    todos = []
    for marca, prods in sorted(por_marca.items()):
        prods.sort(key=lambda p: p["nome"] or "")
        (out / marca / "produtos.json").write_text(json.dumps(prods, ensure_ascii=False, indent=2), encoding="utf-8")
        todos += prods
    (out / "produtos.json").write_text(json.dumps(todos, ensure_ascii=False), encoding="utf-8")

    status = Counter(r["status"] for r in estado.values())
    resumo = {
        "produtos": len(todos),
        "marcas": len(por_marca),
        "fotos": sum(len(p["imagens"]) for p in todos),
        "aplicacoes": sum(len(p["aplicacoes"]) for p in todos),
        "disponiveis": sum(1 for p in todos if p["disponivel"]),
        "sem_aplicacao": sum(1 for p in todos if not p["aplicacoes"]),
        "sem_foto": sum(1 for p in todos if not p["imagens"]),
        "erros": status["erro"],
        "produtos_por_marca": {m: len(p) for m, p in sorted(por_marca.items(), key=lambda x: -len(x[1]))},
    }
    (out / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    erros = [r for r in estado.values() if r["status"] == "erro"]
    (out / "erros.json").write_text(json.dumps(erros, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="catalogo")
    ap.add_argument("-j", "--jobs", type=int, default=6, help="downloads em paralelo (padrão 6)")
    ap.add_argument("--limite", type=int, help="processa só N URLs (para teste)")
    ap.add_argument("--so-indices", action="store_true", help="só regenera os produtos.json/resumo.json")
    args = ap.parse_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    arq_estado = out / "_estado.jsonl"
    estado = carregar_estado(arq_estado)

    if not args.so_indices:
        urls = urls_sitemap()
        pendentes = [u for u in urls if estado.get(u, {}).get("status") not in ("ok", "nao_produto")]
        if args.limite:
            pendentes = pendentes[:args.limite]
        print(f"{len(urls)} URLs no sitemap, {len(pendentes)} pendentes", flush=True)
        inicio = time.time()
        with Pool(args.jobs) as pool, arq_estado.open("a", encoding="utf-8") as f:
            for n, reg in enumerate(pool.imap_unordered(trabalhar, [(u, str(out)) for u in pendentes]), 1):
                estado[reg["url"]] = reg
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
                f.flush()
                if reg["status"] == "erro":
                    print(f"ERRO {reg['url']}: {reg['erro']}", file=sys.stderr, flush=True)
                if n % 100 == 0 or n == len(pendentes):
                    ok = sum(1 for r in estado.values() if r["status"] == "ok")
                    ritmo = n / (time.time() - inicio)
                    print(f"[{n}/{len(pendentes)}] {ok} peças salvas | {ritmo:.1f} URLs/s | "
                          f"faltam ~{(len(pendentes) - n) / ritmo / 60:.0f} min", flush=True)

    resumo = gerar_indices(out, estado)
    print(json.dumps({k: v for k, v in resumo.items() if k != "produtos_por_marca"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
