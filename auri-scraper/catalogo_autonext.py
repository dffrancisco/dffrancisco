#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da AutoNext (VTEX).

Uso: python catalogo_autonext.py                ->  catalogos/autonext.jsonl
     python catalogo_autonext.py --marca Arteb  ->  o mesmo arquivo, só com essa marca

O código do fabricante vem entre colchetes no fim do RefId do SKU ("03.9001.01-Kostal-[03.9001.01]") e fica como o
fabricante imprime, com pontos e zeros: "03.9001.01" é da Kostal, que os outros sites mostram como 3900101. Algumas
marcas levam um prefixo da loja (PREFIXOS) e "S16.01600" é um código interno da loja, que vira null (a peça ainda
casa pelo EAN). A aplicação vem do bloco "compatível com os seguintes automóveis" da descrição.
"""
import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

from autonext_scraper import parse_aplicacoes
from catalogo_altese import sem_ean_repetido
from vtex import POR_PAGINA, normaliza_montadora
from wayap_fotos import n_ean

BASE = "https://www.autonext.com.br"
SAIDA = Path("catalogos/autonext.jsonl")
LIMITE_BUSCA = 2500  # a busca da VTEX não pagina além disso
PRECO_MAXIMO = 100000  # nenhum produto custa mais que isso
INTERVALO = 0.5  # no máximo 2 requisições por segundo, somando as threads
# prefixo que a loja põe no código ("BL-97416" é o 97416 da Blawer). Conferido em 2026-10-04 com os outros catálogos:
# com o prefixo quase nenhum código bate pelo EAN, sem ele quase todos. A Radnaq fica de fora: o cliente escreve "RQ1011".
PREFIXOS = {"ZM": "ZM-?", "Vonixx": "V-", "Blawer": "BL-", "Dyna": "DY-", "NAT": "NAT", "Unifap": "UF-", "TG Poli": "TG-",
            "Hella": "HE-", "Granero": "GRA-", "Autotravi": "AB-", "Orbi": "ORBI-", "Euro": "EP-", "Autoshine": "AS-",
            "Renov": "RN-", "MTE": "MTE-", "Flório": "FL-", "Marília": "IM-", "Olimpic": "OL-", "Zen": "ZEN-",
            "Cofran Lanternas": "C-", "Cofran Retrovisores": "C-", "Arteb": "A-"}
COLCHETE_RE = re.compile(r"\[([^\]]+)\]$")
INTERNO_RE = re.compile(r"S\d\d\.(.+)")  # código da loja por grupo ("S16.01600"); às vezes com o do fabricante atrás

_local = threading.local()
_vez = threading.Lock()
_proxima = 0.0


def _esperar_vez():
    global _proxima
    with _vez:
        agora = time.monotonic()
        espera = _proxima - agora
        _proxima = max(agora, _proxima) + INTERVALO
    if espera > 0:
        time.sleep(espera)


def _get(caminho):
    """Uma sessão (conexão reaproveitada) por thread. 500 ("The operation was canceled.", com várias buscas
    pesadas juntas), timeout e conexão recusada são passageiros."""
    if not hasattr(_local, "sessao"):
        _local.sessao = requests.Session()
        _local.sessao.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    for espera in (5, 15, 30, 60, None):
        _esperar_vez()
        try:
            r = _local.sessao.get(f"{BASE}/api/catalog_system/pub/{caminho}", timeout=90)
            if r.status_code in (200, 206):  # a busca paginada responde 206
                return r
            erro = f"HTTP {r.status_code}"
            if r.status_code < 500:
                break
        except (requests.ConnectionError, requests.Timeout) as e:
            erro = str(e)
        if espera is None:
            break
        time.sleep(espera)
    raise RuntimeError(f"{erro} em {caminho}")


def api(caminho):
    return _get(caminho).json()


def total(fq):
    r = _get(f"products/search?{fq}&_from=0&_to=0")
    return int((r.headers.get("resources") or "0-0/0").split("/")[-1])


def produtos(fq):
    for inicio in range(0, LIMITE_BUSCA, POR_PAGINA):
        lote = api(f"products/search?{fq}&_from={inicio}&_to={inicio + POR_PAGINA - 1}")
        yield from lote
        if len(lote) < POR_PAGINA:
            return


def filtros(fq, de=0, ate=PRECO_MAXIMO):
    """Divide a busca em faixas de preço até cada parte caber no limite."""
    faixa = f"{fq}&fq={quote(f'P:[{de} TO {ate}]')}"
    n = total(faixa)
    if n <= LIMITE_BUSCA or ate - de < 0.02:
        if n > LIMITE_BUSCA:
            print(f"AVISO {fq} R$ {de}-{ate}: {n} produtos, só os {LIMITE_BUSCA} primeiros serão lidos", file=sys.stderr)
        return [faixa] if n else []
    meio = round((de + ate) / 2, 2)  # as faixas incluem as pontas: o preço do meio sai nas duas
    return filtros(fq, de, meio) + filtros(fq, meio, ate)


def codigo(marca, bruto):
    """Código entre colchetes no RefId -> como o fabricante imprime; None se for código interno da loja."""
    interno = INTERNO_RE.fullmatch(bruto)
    if interno:  # "S18.AX002N" é o AX002N da Gauss; "S16.01600" e "S20.1426LD" são só da loja
        bruto = interno[1] if interno[1][0].isalpha() else None
        if not bruto:
            return None
    prefixo = PREFIXOS.get(marca)
    if prefixo and re.match(prefixo, bruto) and re.sub(f"^{prefixo}", "", bruto):
        bruto = re.sub(f"^{prefixo}", "", bruto)
    if marca == "Arteb" and re.fullmatch(r"\d{3}\.\d{3}", bruto):
        return bruto.replace(".", "").zfill(7)  # "A-160.818" é o 0160818, "A-060.051" o 0060051
    if marca.startswith("Cofran"):
        return re.sub(r"^(\d+\.\d)0$", r"\1", bruto)  # a Cofran usa uma casa: "3086.50" é o 3086.5
    if marca == "Delphi":
        return re.sub(r"-1\dB\d$", "", bruto)  # "HNX700-13B2": a ficha e os outros sites mostram HNX700
    return bruto


def texto_carro(aplicacoes):
    """[{'montadora': 'CHEVROLET', 'veiculo': 'Astra', 'motor': '2.0 Gasolina', 'ano_inicio': 2003, 'ano_fim': 2004}]
    -> 'CHEVROLET Astra 2003-2004 2.0 Gasolina'."""
    partes = []
    for a in aplicacoes:
        anos = "-".join(dict.fromkeys(str(x) for x in (a["ano_inicio"], a["ano_fim"]) if x))
        partes.append(" ".join(filter(None, (a["montadora"], a["veiculo"], anos, a["motor"]))))
    return "; ".join(dict.fromkeys(partes)) or None


def carro(produto):
    montadoras = produto.get("Montadora Veículo Compatível") or []
    aplicacoes, _ = parse_aplicacoes(produto.get("description"),
                                     normaliza_montadora(montadoras[0]) if len(montadoras) == 1 else None)
    if aplicacoes:
        return texto_carro(aplicacoes)
    # sem a lista na descrição, ficam os modelos da ficha, sem ano
    modelos = [m for m in produto.get("Modelo Veículo Compatível") or [] if m != "APLICACAO-UNIVERSAL"]
    return "; ".join(dict.fromkeys(modelos)) or None


def registros(produto):
    varios = len(produto["items"]) > 1
    texto = None
    for item in produto["items"]:
        imagens = [i["imageUrl"].split("?")[0] for i in item.get("images", [])]
        if not imagens or item["name"].upper().startswith("INATIVO"):  # SKU desativado pela loja
            continue
        ref = next((r["Value"] for r in item.get("referenceId") or [] if r.get("Key") == "RefId"), "")
        m = COLCHETE_RE.search(ref)
        if m:
            cod = codigo(produto["brand"], m[1].strip())
        else:  # sem colchete: só a ficha, se ela tiver um código só
            ficha = [c.strip() for v in produto.get("Código do fabricante") or [] for c in re.split(r",| ou ", v)]
            cod = codigo(produto["brand"], ficha[0]) if len(ficha) == 1 and ficha[0] else None
        texto = texto or carro(produto)
        # o nome do SKU já traz o lado e a marca ("Farol Astra ... Direito Arteb")
        yield {"site": "autonext", "url": f"{BASE}/{produto['linkText']}/p" + (f"?skuId={item['itemId']}" if varios else ""),
               "nome": item.get("nameComplete") or item.get("name") or produto["productName"], "marca": produto["brand"],
               "codigo_fabricante": cod, "ean": n_ean(item.get("ean")), "imagens": list(dict.fromkeys(imagens)),
               "carro": texto}


def da_marca(id_marca):
    """(produtos sem repetir, total que a loja informa); acima do limite da busca, lê em faixas de preço."""
    fq = f"fq=B:{id_marca}"
    n = total(fq)
    lidos = produtos(fq) if n <= LIMITE_BUSCA else (p for f in filtros(fq) for p in produtos(f))
    return list({p["productId"]: p for p in lidos}.values()), n


def marcas_para_ler(lista, marca=None):
    marcas = list({m["id"]: m for m in lista}.values())
    if marca:
        marcas = [m for m in marcas if m["name"].lower() == marca.lower()]
        if not marcas:
            raise SystemExit(f"marca {marca!r} não encontrada em {BASE}")
    return marcas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-m", "--marca", help="só os produtos desta marca (ex.: Arteb)")
    args = ap.parse_args()
    inicio = time.monotonic()
    marcas = marcas_para_ler(api("brand/list"), args.marca)
    vistos, regs, esperado, falhas = set(), [], 0, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for marca, futuro in [(m, pool.submit(da_marca, m["id"])) for m in marcas]:
            try:
                lote, n = futuro.result()
            except RuntimeError as e:  # segue com as outras marcas; a contagem final mostra o que faltou
                falhas.append(marca["name"])
                print(f"ERRO marca {marca['name']}: {e}", file=sys.stderr)
                continue
            esperado += n
            for p in lote:
                if p["productId"] not in vistos:
                    vistos.add(p["productId"])
                    regs += registros(p)
    com_ean = sum(bool(r["ean"]) for r in regs)
    descartados = com_ean - sum(bool(r["ean"]) for r in sem_ean_repetido(regs))
    SAIDA.parent.mkdir(exist_ok=True)
    with SAIDA.open("w", encoding="utf-8") as f:
        for r in regs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(vistos)} de {esperado} produtos lidos ({len(marcas)} marcas, {len(falhas)} com erro); {len(regs)} SKUs -> "
          f"{SAIDA} ({descartados} EANs descartados por estarem em mais de um código) em {time.monotonic() - inicio:.0f}s")


if __name__ == "__main__":
    main()
