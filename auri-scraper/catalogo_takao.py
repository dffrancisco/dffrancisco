#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Takao, pelo portal do próprio fabricante.

Uso: python catalogo_takao.py   ->  catalogos/takao.jsonl (progresso em catalogos/takao.log)

A API do portal (portal.takao.com.br, aberta, sem login) lista os ~8 mil modelos em páginas. O site separa
o modelo ("P VW 14") da medida ("STD", "0,50", "1,00"), mas no mercado cada medida é um SKU com código
próprio, escrito junto: "PVW14STD", "BBFI10050" (Altese, Auri e a lista do cliente; a KarHub escreve
"BB FI 10 0,50", que o helper normaliza para o mesmo). Então cada medida vira uma linha, com a URL do modelo;
a variação "-" é o modelo sem medida ("RTRE18"). O site não tem EAN. As fotos vêm em 750x750 e são listadas
na ordem do portal; a "imagem-coringa" (foto genérica da família) fica de fora.
"""
import json
import logging
import socket
import time
from pathlib import Path

import requests
import urllib3.util.connection

# o portal é atrás da Cloudflare e esta rede não tem rota IPv6: igual ao helper/fotos.py
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

API = "https://backend-portal.takao.com.br/ProdutoService/BuscarPorSKUSemPrecoSAPSemLogin"
DETALHE = "https://portal.takao.com.br/detalhe/"
SAIDA = Path("catalogos/takao.jsonl")
POR_PAGINA = 100       # 100 modelos levam ~20 s para a API montar
INTERVALO = 1.0        # no máximo uma requisição por segundo
ESPERAS = (5, 15, 30, 60, 120)  # backoff em timeout, erro de conexão, 5xx e "Success": false
CORINGA = "imagem-coringa"
CABECALHOS = {"Content-Type": "application/json", "Origin": "https://portal.takao.com.br",
              "Referer": "https://portal.takao.com.br/",
              "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}

log = logging.getLogger("catalogo_takao")
_sessao = None
_ultimo = 0.0


def _esperar_vez():
    global _ultimo
    falta = _ultimo + INTERVALO - time.monotonic()
    if falta > 0:
        time.sleep(falta)
    _ultimo = time.monotonic()


def pagina(skip, take):
    """Uma página da listagem (SKU vazio = todos os modelos). Timeout, recusa, 5xx e "Success": false são
    passageiros; 4xx não."""
    global _sessao
    if _sessao is None:
        _sessao = requests.Session()
        _sessao.headers.update(CABECALHOS)
    corpo = {"ClienteId": "", "SKU": "", "Take": take, "Skip": skip}
    for espera in ESPERAS + (None,):
        _esperar_vez()
        try:
            r = _sessao.post(API, json=corpo, timeout=180)
            if r.status_code == 200:
                dados = r.json()
                if dados.get("Success"):
                    return dados.get("Result") or []
                erro = f"Success false em Skip={skip}"
            else:
                erro = f"HTTP {r.status_code} em Skip={skip}"
                if r.status_code < 500:
                    break
        except (requests.ConnectionError, requests.Timeout, ValueError) as e:
            erro = f"{e} em Skip={skip}"
        if espera is None:
            break
        log.info("AVISO %s; nova tentativa em %ss", erro, espera)
        time.sleep(espera)
    raise RuntimeError(erro)


def modelos(buscar=pagina):
    """Todos os modelos, sem repetir. Pede um a mais que a página: a API leva ~2 min e devolve vazio quando o
    Skip passa do fim, então a próxima página só é pedida quando o item extra prova que ela existe."""
    vistos, skip = set(), 0
    while True:
        lote = buscar(skip, POR_PAGINA + 1)
        for m in lote:
            if m["Id"] not in vistos:
                vistos.add(m["Id"])
                yield m
        if len(lote) <= POR_PAGINA:
            return
        skip += POR_PAGINA


def codigo(modelo, medida):
    """'P VW 14' + '0,50' -> 'PVW14050'; sem medida ('-') -> 'PVW14'. O resto (zeros, traço) fica."""
    sufixo = "" if medida in (None, "-") else medida.replace(",", "")
    return "".join(modelo.split()) + "".join(sufixo.split())


def imagens(produto):
    return [u for u in dict.fromkeys(produto.get("Imagem") or []) if u and CORINGA not in u]


def registros(produto):
    medidas = [v["Key"] for v in produto.get("Variacoes") or [] if v.get("Key")] or ["-"]
    aplicacao = " ".join((produto.get("Aplicacao") or "").split())
    fotos = imagens(produto)
    for medida in dict.fromkeys(medidas):
        nome = produto["Descricao"].strip() + ("" if medida == "-" else f" {medida}")
        yield {"site": "takao", "url": DETALHE + produto["Id"], "nome": f"{nome} - Takao {produto['Modelo']}",
               "marca": "TAKAO", "codigo_fabricante": codigo(produto["Modelo"], medida), "ean": None,
               "carro": aplicacao or None, "imagens": fotos}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(SAIDA.with_suffix(".log"), encoding="utf-8")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    inicio, regs, n = time.time(), [], 0
    for n, produto in enumerate(modelos(), 1):
        regs += registros(produto)
        if n % POR_PAGINA == 0:
            log.info("%s modelos, %s linhas, %.0f min", n, len(regs), (time.time() - inicio) / 60)
    SAIDA.parent.mkdir(exist_ok=True)
    with SAIDA.open("w", encoding="utf-8") as f:
        for r in regs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    repetidos = len(regs) - len({r["codigo_fabricante"] for r in regs})
    log.info("fim: %s modelos, %s linhas (%s com foto, %s códigos repetidos) em %.0f min -> %s", n, len(regs),
             sum(bool(r["imagens"]) for r in regs), repetidos, (time.time() - inicio) / 60, SAIDA)


if __name__ == "__main__":
    main()
