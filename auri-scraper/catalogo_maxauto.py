#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Maxauto, fabricante de sensores (site próprio, em HTML).

Uso: python catalogo_maxauto.py   ->  catalogos/maxauto.jsonl (andamento em catalogos/maxauto.log)

A lista de /produtos (12 por página) dá o link de cada produto; a página do produto dá o código
("MAX 01.0014/ 5512": código novo / código antigo), a linha ("Sensores de Velocidade"), as fotos
(até 950x950) e a aplicação por montadora. O site não tem EAN.

Código: sai como a KarHub escreve ("010014 / 5512") e a Auri ("010014"): sem o "MAX " e sem o ponto do site,
com o zero à esquerda. O código antigo fica depois da barra, como na KarHub: o cliente às vezes só tem ele.
Fotos: o nome do arquivo traz o código; a de outro código (MAX 12.0152 com fotos do 12.0147) sai.
"""
import argparse
import html
import json
import logging
import re
import socket
import time
from pathlib import Path

import requests
import urllib3.util.connection

# alguns servidores destes fabricantes só respondem em IPv4 (igual ao helper/fotos.py)
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

BASE = "https://maxauto.com.br"
SITE, MARCA = "maxauto", "MAXAUTO"
SAIDA = Path("catalogos/maxauto.jsonl")
INTERVALO = 0.7  # segundos entre requisições: no máximo ~1,5 por segundo
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
ANOS_RE = re.compile(r"\s*-?\s*(\d{4}|\d{2})?\s*>\s*(\d{4}|\d{2})?\s*$")  # ' - 96>00', ' - 13>', ' - >05'

log = logging.getLogger("maxauto")
_ultima = 0.0


def baixar(sessao, url):
    """GET com intervalo mínimo entre requisições; recusa, timeout, 429 e 5xx são tentados de novo com espera."""
    global _ultima
    for espera in (5, 15, 30, 60, None):
        pausa = _ultima + INTERVALO - time.monotonic()
        if INTERVALO and pausa > 0:
            time.sleep(pausa)
        _ultima = time.monotonic()
        try:
            r = sessao.get(url, timeout=60)
            if r.status_code == 200:
                return r.text
            erro = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except (requests.ConnectionError, requests.Timeout) as e:
            erro = str(e)
        if espera is None:
            break
        log.warning(f"{erro} em {url}; nova tentativa em {espera}s")
        time.sleep(espera)
    raise RuntimeError(f"{erro} em {url}")


def limpar(trecho):
    texto = re.sub(r"<br\s*/?>", " ", trecho or "")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", texto)).split())


def links_da_lista(pagina):
    """Os cartões da lista apontam para '../produto/max-01-0014-5512/370/'."""
    return list(dict.fromkeys(f"{BASE}/produto/{slug}" for slug in re.findall(r'href="\.\./produto/([^"]+)"', pagina)))


def ultima_pagina(pagina):
    """Número (base 0) da última página: os links dizem 'Ir para 144' e a página atual vem num <span>."""
    numeros = re.findall(r'title="Ir para (\d+)"', pagina) + re.findall(r"<span[^>]*>(\d+)</span>", pagina)
    return max(map(int, numeros), default=1) - 1


def codigos_do_titulo(titulo):
    """'MAX 01.0014/ 5512' -> ['01.0014', '5512'] (o novo e o antigo, como o site imprime)."""
    sem_max = re.sub(r"^MAX\b", "", titulo.strip(), flags=re.I)
    return [re.sub(r"\s", "", p) for p in sem_max.split("/") if p.strip()]


def codigo_fabricante(titulo):
    """'MAX 01.0014/ 5512' -> '010014 / 5512'. Texto: o zero à esquerda fica."""
    return " / ".join(c.replace(".", "") for c in codigos_do_titulo(titulo))


def fotos(pagina, codigos):
    """Fotos em tamanho cheio, na ordem do site. O arquivo é '<id do upload>-<nome original>': '6743-01-01041.jpg' é a
    foto 1 do 01.0104 e '2886-8800.jpg' é do código antigo 8800. Sai a que traz outro código do mesmo tipo."""
    novos = {c for c in codigos if re.fullmatch(r"\d{2}\.\d{4}", c)}
    antigos = {c for c in codigos if re.fullmatch(r"\d{4}", c)}
    saida = []
    for url in re.findall(r'class="example-image-link" href="([^"]+)"', pagina):
        url = html.unescape(url).strip()
        nome = re.sub(r"^\d+-", "", url.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        novo = re.match(r"(\d{2})-(\d{4})", nome)
        antigo = re.match(r"(\d{4})(?!\d)", nome)
        if novo and novos and f"{novo[1]}.{novo[2]}" not in novos:
            log.info(f"foto de outro código descartada em {'/'.join(codigos)}: {url}")
            continue
        if not novo and antigo and antigos and antigo[1] not in antigos:
            log.info(f"foto de outro código descartada em {'/'.join(codigos)}: {url}")
            continue
        saida.append(url)
    return list(dict.fromkeys(saida))


def _ano(a):
    if not a:
        return None
    n = int(a)
    return n if n > 999 else n + (1900 if n >= 30 else 2000)


def veiculo(texto):
    """'4Runner 2.7/ 3.4 V6 - 96>00' -> '4Runner 2.7/ 3.4 V6 1996-2000'; '13>' -> 'após 2013'; '>05' -> 'até 2005'.
    O helper separa trechos por ' - ' e ',', então os de dentro do texto somem."""
    m = ANOS_RE.search(texto)
    base, de, ate = (texto[:m.start()], _ano(m[1]), _ano(m[2])) if m else (texto, None, None)
    base = re.sub(r"\s+-\s+", " ", base).replace(", ", "/ ").strip()
    anos = f"{de}-{ate}" if de and ate else f"após {de}" if de else f"até {ate}" if ate else ""
    return f"{base} {anos}".strip()


def aplicacao(pagina):
    """Bloco APLICAÇÃO: '<p><strong>TOYOTA</strong></p><ul><li>Camry ...</li></ul>'. Cada <p> é candidato a montadora dos
    <li> que vêm depois; as notas do fim ('02 Pinos', 'Equivalências') não têm <li> e ficam de fora."""
    partes = re.split(r"<h3[^>]*>\s*APLICA", pagina, maxsplit=1, flags=re.I)
    if len(partes) < 2:
        return None
    bloco = re.split(r"<iframe|<!-- inicio fechando", partes[1])[0]
    montadora, veiculos = "", []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>|<li[^>]*>(.*?)</li>", bloco, re.S):
        texto = limpar(m[1] if m[1] is not None else m[2])
        if not texto:
            continue
        if m[1] is not None:
            montadora = re.sub(r"\s*[/-]\s*", " ", texto).strip()  # 'CHRYSLER/ JEEP/ DODGE' -> 'CHRYSLER JEEP DODGE'
        else:
            veiculos.append(" ".join(filter(None, (montadora, veiculo(texto)))))
    return "; ".join(dict.fromkeys(veiculos)) or None


def registro(pagina, url):
    titulo = re.search(r"<h2[^>]*>\s*(MAX\b.*?)</h2>", pagina, re.S | re.I)
    if not titulo:
        raise ValueError(f"página sem o código MAX: {url}")
    linha = re.search(r"<h3[^>]*>(.*?)</h3>", pagina[titulo.end():], re.S)
    nome = re.split(r"\s+-(?:\s+|$)", limpar(linha[1]))[0].strip() if linha else ""  # 'Sensores ABS - ABS Wheel...'
    codigo = limpar(titulo[1])
    return {"site": SITE, "url": url, "nome": nome or codigo, "marca": MARCA,
            "codigo_fabricante": codigo_fabricante(codigo), "ean": None,
            "imagens": fotos(pagina, codigos_do_titulo(codigo)), "carro": aplicacao(pagina)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()
    SAIDA.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(SAIDA.with_suffix(".log"), "w", "utf-8")])
    sessao = requests.Session()
    sessao.headers["User-Agent"] = UA
    primeira = baixar(sessao, f"{BASE}/produtos?pagina=0")
    ultima, links, falhas = ultima_pagina(primeira), links_da_lista(primeira), []
    for n in range(1, ultima + 1):
        try:
            links += links_da_lista(baixar(sessao, f"{BASE}/produtos?pagina={n}"))
        except RuntimeError as e:
            log.error(f"página {n} da lista: {e}")
            falhas.append(f"lista {n}")
    links = list(dict.fromkeys(links))
    log.info(f"{len(links)} produtos em {ultima + 1} páginas da lista")
    regs = []
    for i, url in enumerate(links, 1):
        try:
            regs.append(registro(baixar(sessao, url), url))
        except (RuntimeError, ValueError) as e:
            log.error(str(e))
            falhas.append(url)
        if i % 100 == 0:
            log.info(f"{i} de {len(links)} produtos lidos")
    with SAIDA.open("w", encoding="utf-8") as f:
        for r in regs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    estranhos = [r["codigo_fabricante"] for r in regs if not re.fullmatch(r"(\d{6}|\d{4})( / \d{4})*", r["codigo_fabricante"])]
    if estranhos:
        log.warning(f"{len(estranhos)} códigos fora do padrão: {estranhos[:30]}")
    log.info(f"{len(regs)} produtos -> {SAIDA}: {sum(bool(r['imagens']) for r in regs)} com foto, "
             f"{sum(bool(r['carro']) for r in regs)} com aplicação; {len(falhas)} falhas {falhas[:20]}")


if __name__ == "__main__":
    main()
