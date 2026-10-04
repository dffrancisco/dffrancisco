#!/usr/bin/env python3
"""Árvore de veículos da KarHub (montadora → modelo → ano → versão), fotos de modelo, logos e compatibilidade
produto → veículo, para o helper. Só carros e utilitários descem até as versões; motos e pesados ficam registrados
em karhub_excluidos.jsonl. Spec: docs/superpowers/specs/2026-10-03-helper-veiculos-design.md

Uso:
    python catalogo_karhub_veiculos.py fipe       # listas da FIPE para classificar o tipo (veiculos/fipe.json)
    python catalogo_karhub_veiculos.py arvore     # retoma pelos modelos já gravados; --montadora chevrolet; --do-inicio
    python catalogo_karhub_veiculos.py compat     # ids de veículo de cada produto de catalogos/karhub.jsonl; --do-inicio

Saída em veiculos/: karhub_arvore.jsonl, karhub_excluidos.jsonl, karhub_compat.jsonl, fipe.json, imagens/ e <comando>.log.
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import requests
from curl_cffi.requests.exceptions import RequestException as ErroCurl

from helper.montadoras import Montadoras
from helper.veiculo_tipo import carregar_ajustes, classificar, indexar_fipe

SITE = "https://www.karhub.com.br"
FIPE = "https://parallelum.com.br/fipe/api/v1"
LISTAS_FIPE = ("carros", "motos", "caminhoes")
ESPERAS = (5, 15, 30, 60)
PAUSA = 0.3
LOTE_COMPAT = 50  # com 100 handles a API devolve {} sem erro
ERROS_REDE = (requests.RequestException, ErroCurl, OSError)


class Bloqueado(Exception):
    pass


def buscar_scrapling(url):
    from scrapling.fetchers import Fetcher  # o site e as imagens ficam atrás do Cloudflare: requests puro leva 403
    r = Fetcher.get(url, stealthy_headers=True, timeout=60, headers={"Accept": "application/json, image/avif, image/*"})
    return r.status, r.body, (r.headers.get("content-type") or "")


def buscar_requests(url):
    r = requests.get(url, timeout=60)
    return r.status_code, r.content, r.headers.get("content-type", "")


class Cliente:
    """GET com novas tentativas. buscar(url) -> (status, corpo, content_type); trocado por um falso nos testes."""

    def __init__(self, buscar=None, esperas=ESPERAS, pausa=PAUSA, log=print):
        self.buscar = buscar or buscar_scrapling
        self.esperas, self.pausa, self.log = esperas, pausa, log

    def get(self, url, aceitar_404=False):
        bloqueios = 0
        for espera in (*self.esperas, None):
            try:
                status, corpo, tipo = self.buscar(url)
                erro = None
            except ERROS_REDE as e:  # conexão recusada ou timeout: houve minutos assim nos testes de 2026-10-03
                status, corpo, tipo, erro = None, b"", "", f"conexão: {e}"
            if status == 200:
                if self.pausa:
                    time.sleep(self.pausa)
                return corpo, tipo
            if status == 404 and aceitar_404:
                return None, tipo
            if status in (403, 430) or (status and b"captcha" in corpo[:3000].lower()):
                bloqueios += 1
                erro = f"BLOQUEIO HTTP {status}"
                espera = espera and espera * 4
            elif erro is None:
                erro = f"HTTP {status}"
            if espera is None:
                raise (Bloqueado if bloqueios else RuntimeError)(f"{erro} em {url}")
            self.log(f"{erro}; nova tentativa em {espera}s")
            time.sleep(espera)

    def json(self, url):
        return json.loads(self.get(url)[0])


def ler_jsonl(caminho):
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    texto = caminho.read_text(encoding="utf-8")
    if texto and not texto.endswith("\n"):  # última linha cortada por uma interrupção
        texto = texto[:texto.rfind("\n") + 1]
        caminho.write_text(texto, encoding="utf-8")
    return [json.loads(l) for l in texto.splitlines() if l.strip()]


# ---------- FIPE ----------

def coletar_fipe(cliente, saida):
    dados = {}
    for lista in LISTAS_FIPE:
        dados[lista] = {}
        for marca in cliente.json(f"{FIPE}/{lista}/marcas"):
            modelos = cliente.json(f"{FIPE}/{lista}/marcas/{marca['codigo']}/modelos")["modelos"]
            dados[lista][marca["nome"]] = [m["nome"] for m in modelos]
    Path(saida).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return {lista: len(v) for lista, v in dados.items()}


# ---------- árvore ----------

def api_veiculos(cliente, **params):
    return cliente.json(f"{SITE}/api/get-vehicles" + (f"?{urlencode(params)}" if params else ""))


def conteudo(cliente, handle):
    """get-automaker-content: {'brand': {...}, 'model': {...}} ou {} quando o KarHub não tem conteúdo."""
    d = cliente.json(f"{SITE}/api/get-automaker-content?handle={quote(handle)}")
    return (d.get("data") or {}).get("data") or {}


def baixar_imagem(cliente, url, pasta):
    """Guarda em pasta/<caminho da URL>. Devolve a URL se a imagem existe; None se não há URL ou deu 404."""
    if not url:
        return None
    destino = Path(pasta) / urlsplit(url).path.lstrip("/")
    if destino.exists():
        return url
    corpo, tipo = cliente.get(url, aceitar_404=True)
    if corpo is None or not tipo.startswith("image/"):
        return None
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(corpo)
    return url


def _versoes(itens):
    return [{"label": v["label"], "handle": v["handle"], "ids_fonte": [str(i) for i in v["compatible_ids"]]}
            for v in itens if v.get("compatible_ids")]


def _feitos(arq_arvore, arq_excl, indice_fipe, ajustes, montadoras):
    feitos = {(l["montadora"]["handle"], l["modelo"]["handle"]) for l in ler_jsonl(arq_arvore)}
    for l in ler_jsonl(arq_excl):
        if l.get("tipo") == "sem_anos":
            feitos.add((l["montadora"]["handle"], l["modelo"]["handle"]))
            continue
        # um ajuste novo em helper_veiculos_tipo.csv pode ter transformado o excluído em carro: aí ele é coletado
        tipo, _ = classificar(montadoras.chaves(l["montadora"]["label"]), l["modelo"]["label"], l.get("versoes_exemplo") or [],
                              indice_fipe, ajustes)
        if tipo != "carro":
            feitos.add((l["montadora"]["handle"], l["modelo"]["handle"]))
    return feitos


def coletar_arvore(cliente, pasta, indice_fipe, ajustes, montadoras, so_montadora=None, do_inicio=False, log=print):
    pasta = Path(pasta)
    arq_arvore, arq_excl = pasta / "karhub_arvore.jsonl", pasta / "karhub_excluidos.jsonl"
    alvo_arvore = Path(f"{arq_arvore}.novo") if do_inicio else arq_arvore
    alvo_excl = Path(f"{arq_excl}.novo") if do_inicio else arq_excl
    feitos = _feitos(alvo_arvore, alvo_excl, indice_fipe, ajustes, montadoras)
    hoje, r, logos = date.today().isoformat(), Counter(), {}
    with alvo_arvore.open("a", encoding="utf-8") as f_arv, alvo_excl.open("a", encoding="utf-8") as f_exc:
        def gravar(arquivo, registro):
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
            arquivo.flush()

        for marca in api_veiculos(cliente)["brands"]:
            if so_montadora and marca["handle"] != so_montadora:
                continue
            chaves = montadoras.chaves(marca["label"])
            for modelo in api_veiculos(cliente, brand=marca["handle"])["models"]:
                if (marca["handle"], modelo["handle"]) in feitos:
                    r["ja_feitos"] += 1
                    continue
                base = {"montadora": {"label": marca["label"], "handle": marca["handle"]},
                        "modelo": {"label": modelo["label"], "handle": modelo["handle"]}}
                anos = api_veiculos(cliente, brand=marca["handle"], model=modelo["handle"])["years"]
                if not anos:
                    gravar(f_exc, {**base, "tipo": "sem_anos", "motivo_tipo": "sem_anos", "versoes_exemplo": [], "coletado_em": hoje})
                    r["sem_anos"] += 1
                    continue
                recentes = api_veiculos(cliente, brand=marca["handle"], model=modelo["handle"], year=anos[0]["value"])["versions"]
                rotulos = [v["label"] for v in recentes]
                tipo, motivo = classificar(chaves, modelo["label"], rotulos, indice_fipe, ajustes)
                if tipo != "carro":
                    gravar(f_exc, {**base, "tipo": tipo, "motivo_tipo": motivo, "versoes_exemplo": rotulos[:5], "coletado_em": hoje})
                    r[f"excluido_{tipo}"] += 1
                    log(f"{marca['label']} {modelo['label']}: {tipo} ({motivo}), fora da árvore")
                    continue
                lista_anos = [{"ano": int(anos[0]["value"]), "versoes": _versoes(recentes)}]
                for ano in anos[1:]:
                    itens = api_veiculos(cliente, brand=marca["handle"], model=modelo["handle"], year=ano["value"])["versions"]
                    lista_anos.append({"ano": int(ano["value"]), "versoes": _versoes(itens)})
                if marca["handle"] not in logos:
                    url_logo = (conteudo(cliente, marca["handle"]).get("brand") or {}).get("image_url")
                    logos[marca["handle"]] = baixar_imagem(cliente, url_logo, pasta / "imagens")
                url_foto = (conteudo(cliente, f"{marca['handle']}/{modelo['handle']}").get("model") or {}).get("image_url")
                gravar(f_arv, {"montadora": {**base["montadora"], "logo_url": logos[marca["handle"]]},
                               "modelo": {**base["modelo"], "foto_url": baixar_imagem(cliente, url_foto, pasta / "imagens")},
                               "tipo": tipo, "motivo_tipo": motivo, "anos": lista_anos, "coletado_em": hoje})
                r["carros"] += 1
                log(f"{marca['label']} {modelo['label']}: carro ({motivo}), {len(lista_anos)} anos")
    if do_inicio:
        alvo_arvore.replace(arq_arvore)
        alvo_excl.replace(arq_excl)
    return r


# ---------- compatibilidade produto -> veículo ----------

def handles_do_catalogo(caminho):
    vistos = {}
    with Path(caminho).open(encoding="utf-8") as f:
        for linha in f:
            try:
                url = json.loads(linha)["url"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            vistos.setdefault(urlsplit(url).path.rsplit("/", 1)[-1], None)
    return list(vistos)


def _compat(cliente, handles):
    resposta = cliente.json(f"{SITE}/api/product-compatible-ids?handles={','.join(quote(h) for h in handles)}")
    return resposta if isinstance(resposta, dict) else {}


def coletar_compat(cliente, catalogo, saida, do_inicio=False, log=print):
    saida = Path(saida)
    alvo = Path(f"{saida}.novo") if do_inicio else saida
    feitos = {l["handle"] for l in ler_jsonl(alvo)}
    pendentes = [h for h in handles_do_catalogo(catalogo) if h not in feitos]
    hoje, r = date.today().isoformat(), Counter()
    log(f"compat: {len(feitos)} handles já gravados, {len(pendentes)} a consultar")
    with alvo.open("a", encoding="utf-8") as f:
        for i in range(0, len(pendentes), LOTE_COMPAT):
            lote = pendentes[i:i + LOTE_COMPAT]
            resposta = _compat(cliente, lote)
            if not resposta and len(lote) > 10:
                # lote inteiro vazio: recusado ou ninguém com compatibilidade? em lotes de 10 dá para saber
                resposta = {}
                for j in range(0, len(lote), 10):
                    resposta.update(_compat(cliente, lote[j:j + 10]))
            for h in lote:
                ids = [str(x) for x in resposta.get(h) or []]
                f.write(json.dumps({"handle": h, "ids": ids, "coletado_em": hoje}) + "\n")
                r["com_ids" if ids else "sem_ids"] += 1
            f.flush()
            if (i // LOTE_COMPAT) % 20 == 0:
                log(f"compat: {i + len(lote)} de {len(pendentes)}")
    if do_inicio:
        alvo.replace(saida)
    return r


# ---------- linha de comando ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["fipe", "arvore", "compat"])
    ap.add_argument("--pasta", type=Path, default=Path("veiculos"))
    ap.add_argument("--catalogo", type=Path, default=Path("catalogos/karhub.jsonl"), help="compat: de onde vêm os handles")
    ap.add_argument("--montadora", help="arvore: só esta montadora (handle do KarHub, ex.: chevrolet)")
    ap.add_argument("--do-inicio", action="store_true", help="coleta tudo de novo em arquivos .novo e troca no fim")
    args = ap.parse_args(argv)
    if args.montadora and args.do_inicio:
        ap.error("--montadora não combina com --do-inicio (a troca no fim apagaria as outras montadoras)")
    args.pasta.mkdir(parents=True, exist_ok=True)
    with open(args.pasta / f"{args.comando}.log", "a", encoding="utf-8") as f_log:
        def log(msg):
            linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
            print(linha, flush=True)
            f_log.write(linha + "\n")
            f_log.flush()

        try:
            if args.comando == "fipe":
                r = coletar_fipe(Cliente(buscar=buscar_requests, pausa=1.0, log=log), args.pasta / "fipe.json")
            elif args.comando == "arvore":
                arq_fipe = args.pasta / "fipe.json"
                if not arq_fipe.exists():
                    log(f"sem {arq_fipe}: rode antes python catalogo_karhub_veiculos.py fipe")
                    return 2
                r = coletar_arvore(Cliente(log=log), args.pasta, indexar_fipe(json.loads(arq_fipe.read_text(encoding="utf-8"))),
                                   carregar_ajustes(), Montadoras.carregar(), so_montadora=args.montadora,
                                   do_inicio=args.do_inicio, log=log)
            else:
                r = coletar_compat(Cliente(log=log), args.catalogo, args.pasta / "karhub_compat.jsonl", do_inicio=args.do_inicio, log=log)
        except Bloqueado as e:
            log(f"PARADO por bloqueio ({e}). Rode de novo mais tarde; retoma de onde parou.")
            return 2
        log("fim: " + ", ".join(f"{k} {v}" for k, v in sorted(dict(r).items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
