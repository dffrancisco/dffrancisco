#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da DS Indústria de Peças Automotivas (ds.ind.br), site do fabricante.

Uso: python catalogo_ds.py             ->  catalogos/ds.jsonl (log em catalogos/ds.log)
     python catalogo_ds.py --refazer   ->  apaga o .jsonl e lê tudo de novo
     python catalogo_ds.py --limite 20 ->  teste com poucos produtos

A busca sem filtro (/pt/busca?page=N) lista o catálogo inteiro, 5 produtos por página; cada produto tem
uma página com "Código DS:", galeria de 1 a 4 fotos e a tabela "aplicação por veículo". O site não mostra EAN.

O código sai como o site e a KarHub escrevem, sem o "DS" na frente ("2328", "30074DE"): é a grafia da maioria
dos anúncios da marca no helper. O cliente escreve "DS2328" e o helper/lista.py tira o prefixo ao casar.
Retoma de onde parou: produtos cuja URL já está no .jsonl são pulados.
"""
import argparse
import html as htmllib
import json
import logging
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3.util.connection

BASE = "https://www.ds.ind.br"
LISTA = BASE + "/pt/busca?montadora=&modelo=&linha=&page={}"
SAIDA = Path("catalogos/ds.jsonl")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
CONEXOES = 2
INTERVALO = 0.6  # no máximo ~1,7 inícios de requisição por segundo, somando as conexões
ESPERAS = (5, 15, 30, 60)  # backoff em erro de conexão, 429 e 5xx
MONTADORAS = {"GM": "Chevrolet", "VW": "Volkswagen", "MB": "Mercedes-Benz"}  # mesmo nome que as lojas usam no "carro"

# o site só responde em IPv4 nesta rede (como em helper/fotos.py)
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

log = logging.getLogger("ds")
_local = threading.local()


class Ritmo:
    """Espaça os inícios de requisição entre as threads."""

    def __init__(self, intervalo):
        self.intervalo, self.proxima, self.trava = intervalo, 0.0, threading.Lock()

    def esperar(self):
        with self.trava:
            agora = time.monotonic()
            espera = self.proxima - agora
            self.proxima = max(agora, self.proxima) + self.intervalo
        if espera > 0:
            time.sleep(espera)


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


def sem_tags(trecho):
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", trecho or "")).split())


def links(pagina):
    """Produtos de uma página da busca (os itens que o site esconde vêm sem link)."""
    m = re.search(r'<ul class="resultado-itens">(.*?)</ul>', pagina, re.S)
    achados = re.findall(r'<a href="(https://www\.ds\.ind\.br/pt/produtos/[^"]+)" class="thumb', m.group(1)) if m else []
    return list(dict.fromkeys(achados))


def ultima_pagina(pagina):
    return max((int(n) for n in re.findall(r"[?&;]page=(\d+)", pagina)), default=1)


def _ano(texto):
    m = re.search(r"(\d{4}|\d{2})\D*$", texto)  # o último número: '04/2007' -> 2007, '03' -> 2003
    if not m:
        return None
    a = int(m.group(1))
    return a if a > 99 else a + (1900 if a >= 30 else 2000)  # mesma virada de aplicacao_texto.ler_anos


def anos(texto):
    """'03 &gt; 12' -> (2003, 2012); '92 &gt;' -> (1992, None); '15' -> (2015, 2015); '' -> (None, None)."""
    texto = htmllib.unescape(texto or "")
    if ">" not in texto:
        a = _ano(texto)
        return a, a
    de, ate = texto.split(">", 1)
    return _ano(de), _ano(ate)


def faixa(de, ate):
    """No formato que o helper lê (aplicacao_texto): '2003-2012', 'após 2008', 'até 2012'."""
    if de and ate:
        return str(de) if de == ate else f"{de}-{ate}"
    return f"após {de}" if de else f"até {ate}" if ate else ""


def montadora(nome):
    nome = " ".join(nome.split())
    if nome.upper() in MONTADORAS:
        return MONTADORAS[nome.upper()]
    return nome.title() if nome.isupper() and len(nome) > 3 else nome


def veiculo(fabricante, modelo, anos_, motor, extras):
    """Uma aplicação: 'Chevrolet Meriva 2003-2012 1.8 4Cil 8v (Flex)'. O helper separa as aplicações por ';' e
    ignora o que está entre parênteses, então ';' e parênteses do texto do site viram vírgula/somem."""
    extras = [" ".join(re.sub(r"[()]", " ", e).replace(";", ",").split()) for e in extras]
    extras = ", ".join(e for e in extras if e and e != "-")
    partes = [montadora(fabricante), " ".join(modelo.split()), faixa(*anos_), " ".join(motor.replace(" - ", " ").split())]
    return " ".join(p for p in partes if p) + (f" ({extras})" if extras else "")


def carro(pagina):
    m = re.search(r'<div class="table jq-apps">(.*?)</table>', pagina, re.S)
    if not m:
        return None
    aplicacoes = []
    for tr in re.findall(r"<tr>(.*?)</tr>", m.group(1), re.S):
        c = {k: sem_tags(v) for k, v in re.findall(r'<td class="(\w+)">(.*?)</td>', tr, re.S)}
        if c.get("modelo"):
            aplicacoes.append(veiculo(c.get("montadora", ""), c["modelo"], anos(c.get("ano")), c.get("motor", ""),
                                      [c.get("complemento", ""), c.get("observacoes", "")]))
    return "; ".join(dict.fromkeys(aplicacoes)) or None


def registros(pagina, url):
    m = re.search(r"Código DS:\s*([^<]*?)\s*<", pagina)
    if not m or not m.group(1):
        return []  # código inexistente: o site responde 200 com a página vazia
    codigo = m.group(1)
    nome = sem_tags((re.search(r'<h1[^>]*itemprop="name">(.*?)</h1>', pagina, re.S) or [None, ""])[1])
    galeria = re.search(r'<ul class="pgwSlider">(.*?)</ul>', pagina, re.S)
    imagens = [urljoin(url, src) for src in re.findall(r'src="([^"]+)"', galeria.group(1))] if galeria else []
    return [{"site": "ds", "url": url, "nome": f"{nome} - {codigo}" if nome else codigo, "marca": "DS",
             "codigo_fabricante": codigo, "ean": None, "carro": carro(pagina), "imagens": list(dict.fromkeys(imagens))}]


def ja_feitos(saida):
    feitos = set()
    if saida.exists():
        for linha in saida.open(encoding="utf-8"):
            try:
                feitos.add(json.loads(linha)["url"])
            except (ValueError, KeyError):
                pass  # linha truncada por interrupção
    return feitos


def listar(pool):
    primeira = pedir(LISTA.format(1)) or ""
    total = ultima_pagina(primeira)
    urls = links(primeira)
    for n, pagina in enumerate(pool.map(lambda p: pedir(LISTA.format(p)) or "", range(2, total + 1)), 2):
        urls += links(pagina)
        if n % 50 == 0:
            log.info("lista: página %s de %s, %s produtos", n, total, len(urls))
    return total, list(dict.fromkeys(urls))


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
    with ThreadPoolExecutor(max_workers=CONEXOES) as pool:
        paginas, urls = listar(pool)
        pendentes = [u for u in urls if u not in feitos][:args.limite]
        log.info("INICIO %s produtos em %s páginas da lista; %s já no arquivo, %s pendentes",
                 len(urls), paginas, len(feitos & set(urls)), len(pendentes))
        gravados = sem_foto = vazios = erros = 0
        with SAIDA.open("a", encoding="utf-8") as f:
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
                    log.warning("AVISO %s: %s", url, "404" if regs is None else "página sem 'Código DS'")
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
