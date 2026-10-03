"""Lê catalogos/*.jsonl e pecas_*/**/produto.json e entrega anúncios num formato único."""
import json
import re
from collections import namedtuple
from datetime import date
from pathlib import Path

Fonte = namedtuple("Fonte", "caminho site tipo mtime")

# ordem de confiança das fontes para escolher descrição e ordem de fotos (menor = melhor)
PRIORIDADE_SITE = {"universal": 1, "karhub": 2, "shoppecas": 3, "carblue": 4}
PRIORIDADE_PADRAO = 5


def prioridade(site, de_produto_json):
    return 0 if de_produto_json else PRIORIDADE_SITE.get(site, PRIORIDADE_PADRAO)


def fontes_disponiveis(base):
    base = Path(base)
    fontes = [Fonte(a, a.stem, "jsonl", a.stat().st_mtime) for a in sorted((base / "catalogos").glob("*.jsonl"))]
    for pasta in sorted(base.glob("pecas_*")):
        site = pasta.name[len("pecas_"):]
        for a in sorted(pasta.rglob("produto.json")):
            fontes.append(Fonte(a, site, "produto_json", a.stat().st_mtime))
    return fontes


def _data(mtime):
    return date.fromtimestamp(mtime).isoformat()


def _anuncio_base(site, fonte):
    return {"site": site, "url": None, "nome": None, "marca": None, "codigo": None, "ean": None, "carro": None,
            "aplicacoes": [], "equivalentes": [], "imagens": [], "observacoes": [],
            "coletado_em": _data(fonte.mtime), "prioridade": prioridade(site, fonte.tipo == "produto_json")}


def _de_jsonl(r, fonte):
    a = _anuncio_base(r.get("site") or fonte.site, fonte)
    a.update(url=r.get("url"), nome=r.get("nome"), marca=r.get("marca"), codigo=r.get("codigo_fabricante"),
             ean=r.get("ean"), carro=r.get("carro"))
    if r.get("codigo_original"):
        a["equivalentes"] = [c.strip() for c in re.split(r"[/;,]", str(r["codigo_original"])) if c.strip()]
    a["imagens"] = [{"url": u, "arquivo_local": None, "principal": i == 0} for i, u in enumerate(r.get("imagens") or [])]
    return a


def _de_produto_json(p, fonte):
    a = _anuncio_base(fonte.site, fonte)
    a.update(url=p.get("url_origem") or p.get("url"), nome=p.get("nome"), marca=p.get("marca"),
             codigo=p.get("codigo_fabricante"), ean=p.get("ean"), carro=p.get("carro"),
             aplicacoes=list(p.get("aplicacoes") or []), equivalentes=list(p.get("codigos_equivalentes") or []),
             observacoes=list(p.get("observacoes") or []))
    pasta = fonte.caminho.parent
    for i, im in enumerate(p.get("imagens") or []):
        if isinstance(im, str):
            im = {"url": im, "arquivo": None, "principal": i == 0}
        local = pasta / im["arquivo"] if im.get("arquivo") else None
        a["imagens"].append({"url": im.get("url"), "arquivo_local": str(local) if local and local.exists() else None,
                             "principal": bool(im.get("principal", i == 0))})
    return a


def ler_fonte(fonte, erros):
    """Gera anúncios da fonte; problemas vão para `erros` (lista de str), nunca interrompem."""
    if fonte.tipo == "jsonl":
        with fonte.caminho.open(encoding="utf-8") as f:
            for n, linha in enumerate(f, 1):
                if not linha.strip():
                    continue
                try:
                    r = json.loads(linha)
                except json.JSONDecodeError:
                    erros.append(f"linha {n} inválida")  # vazia ou cortada: catálogo ainda sendo gravado
                    continue
                if r.get("url"):
                    yield _de_jsonl(r, fonte)
        return
    try:
        p = json.loads(fonte.caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        erros.append(f"{fonte.caminho}: produto.json inválido ({e})")
        return
    a = _de_produto_json(p, fonte)
    if a["url"]:
        yield a
    else:
        erros.append(f"{fonte.caminho}: produto.json sem url_origem")
