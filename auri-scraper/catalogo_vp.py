#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da VP Virtual Plásticos (vp.ind.br), site do fabricante.

Uso: python catalogo_vp.py             ->  catalogos/vp.jsonl (log em catalogos/vp.log)
     python catalogo_vp.py --refazer   ->  apaga o .jsonl e lê tudo de novo
     python catalogo_vp.py --limite 20 ->  teste com poucos produtos

Os produtos saem do sitemap.xml (inclusive os acessórios em subpastas, como retrovisores e máquinas de vidro);
cada página tem "Código:", uma foto (900x600 a 1200x1200) e a tabela de aplicação. O site não mostra EAN.
As fotos dentro da descrição dos módulos são dos componentes (flange, sensor, copo) e ficam de fora.

A marca sai como "VP VIRTUAL PLASTIC", o nome que a CarBlue usa. O código sai como a CarBlue escreve, sem o "VP"
que o site põe nas flanges ("VP7057" -> "7057"); só os módulos (VP + 3 dígitos, "VP074") ficam com ele.
Retoma de onde parou: produtos cuja URL já está no .jsonl são pulados.
"""
import argparse
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests

from catalogo_ds import ESPERAS, UA, Ritmo, anos, ja_feitos, sem_tags, veiculo  # catalogo_ds também força o IPv4

BASE = "https://www.vp.ind.br"
SAIDA = Path("catalogos/vp.jsonl")
MARCA = "VP VIRTUAL PLASTIC"
CONEXOES = 2
INTERVALO = 0.6  # no máximo ~1,7 inícios de requisição por segundo, somando as conexões
NAO_PRODUTO = {"produtos", "representantes", "a-virtual-plasticos", "conteudo-tecnico"}  # 1ª pasta das outras páginas

log = logging.getLogger("vp")
_local = threading.local()
ritmo = Ritmo(INTERVALO)


def pedir(url):
    """Texto da página; None se ela não existe (404). Recusa, timeout, 429 e 5xx são tentados de novo."""
    if not hasattr(_local, "sessao"):
        _local.sessao = requests.Session()
        _local.sessao.headers["User-Agent"] = UA
    for espera in ESPERAS + (None,):
        ritmo.esperar()
        try:
            r = _local.sessao.get(url, timeout=60)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
            erro = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except (requests.ConnectionError, requests.Timeout) as e:
            erro = str(e)
        if espera is None:
            break
        log.warning("AVISO %s: %s; nova tentativa em %ss", url, erro, espera)
        time.sleep(espera)
    raise RuntimeError(f"{erro} em {url}")


def produtos_do_sitemap(xml):
    """Páginas de produto: as que ficam numa pasta ('/flanges/...', '/acessorios/retrovisores/...') que não é
    de categoria, representante ou institucional."""
    urls = []
    for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml):
        partes = loc.replace(BASE, "").strip("/").split("/")
        if len(partes) >= 2 and partes[0] not in NAO_PRODUTO:
            urls.append(loc)
    return list(dict.fromkeys(urls))


def codigo(texto):
    """Sem o 'VP' das flanges ('VP7057' -> '7057', 'VP7016-CH' -> '7016-CH'), como a CarBlue escreve. Nos módulos
    ('VP074') o VP fica: é como o site, a Altese, a Auri e o cliente escrevem, e '074' sozinho não diz nada."""
    c = texto.strip()
    m = re.fullmatch(r"VP\s*(\d{4}.*)", c, re.I)
    return m.group(1) if m else c


def especificacoes(pagina):
    """{'Código': '8822', 'Fabricante': 'VP', 'Combustível': 'Flex', ...}"""
    pares = re.findall(r"<span class='pe-tit'>([^<]*)</span><span class='pe-esp'>(.*?)</span>", pagina, re.S)
    return {sem_tags(t).rstrip(":").strip(): sem_tags(v) for t, v in pares if t.strip()}


def carro(pagina, combustivel):
    m = re.search(r"<table class='tabela-responsiva prodvariacoes'>(.*?)</table>", pagina, re.S)
    if not m:
        return None
    aplicacoes = []
    for tr in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S):
        c = {k: sem_tags(v) for k, v in re.findall(r"<td class='linha-(\d+)'>(.*?)</td>", tr, re.S)}
        if c.get("02"):
            aplicacoes.append(veiculo(c.get("01", ""), c["02"], anos(c.get("04")), c.get("03", ""),
                                      [combustivel, c.get("06", "")]))
    return "; ".join(dict.fromkeys(aplicacoes)) or None


def registros(pagina, url):
    espec = especificacoes(pagina)
    if not espec.get("Código"):
        return []
    if espec.get("Fabricante") not in (None, "", "VP"):
        log.warning("AVISO %s: fabricante %r", url, espec["Fabricante"])
    nome = sem_tags((re.search(r"<div id='pe-title'>\s*<h1>(.*?)</h1>", pagina, re.S) or [None, ""])[1])
    foto = re.search(r"<div id='ImagemProduto'>\s*<a href='([^']+)'", pagina)
    imagens = [urljoin(url, foto.group(1))] if foto else []  # algumas vêm como '../imagens/...'
    return [{"site": "vp", "url": url, "nome": nome or espec["Código"], "marca": MARCA,
             "codigo_fabricante": codigo(espec["Código"]), "ean": None,
             "carro": carro(pagina, espec.get("Combustível", "")), "imagens": imagens}]


def detalhar(url):
    pagina = pedir(url)
    return url, registros(pagina, url) if pagina is not None else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refazer", action="store_true", help="apaga o .jsonl e lê o catálogo inteiro de novo")
    ap.add_argument("--limite", type=int, help="lê só os N primeiros produtos pendentes")
    args = ap.parse_args()
    SAIDA.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(SAIDA.with_suffix(".log"), encoding="utf-8")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    if args.refazer and SAIDA.exists():
        SAIDA.unlink()
    inicio, feitos = time.time(), ja_feitos(SAIDA)
    urls = produtos_do_sitemap(pedir(BASE + "/sitemap.xml") or "")
    pendentes = [u for u in urls if u not in feitos][:args.limite]
    log.info("INICIO %s produtos no sitemap; %s já no arquivo, %s pendentes", len(urls), len(feitos & set(urls)), len(pendentes))
    gravados = sem_foto = vazios = erros = 0
    with ThreadPoolExecutor(max_workers=CONEXOES) as pool, SAIDA.open("a", encoding="utf-8") as f:
        futuros = [pool.submit(detalhar, u) for u in pendentes]
        for n, fut in enumerate(as_completed(futuros), 1):
            try:
                url, regs = fut.result()
            except Exception as e:  # segue com os outros; o produto fica pendente para a próxima execução
                erros += 1
                log.error("ERRO %s", e)
                continue
            if not regs:
                vazios += 1
                log.warning("AVISO %s: %s", url, "404" if regs is None else "página sem 'Código:'")
                continue
            for r in regs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                sem_foto += not r["imagens"]
            f.flush()
            gravados += len(regs)
            if n % 100 == 0:
                log.info("[%s/%s] %s gravados, %s sem foto, %s vazios, %s erros, %.0f min",
                         n, len(pendentes), gravados, sem_foto, vazios, erros, (time.time() - inicio) / 60)
    log.info("FIM %s produtos lidos, %s registros gravados (%s sem foto), %s páginas vazias, %s erros, %.1f min -> %s",
             len(pendentes), gravados, sem_foto, vazios, erros, (time.time() - inicio) / 60, SAIDA)


if __name__ == "__main__":
    main()
