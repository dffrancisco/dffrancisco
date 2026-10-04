#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Altese Auto Peças (VTEX).

Uso: python catalogo_altese.py                ->  catalogos/altese.jsonl
     python catalogo_altese.py --marca Arteb  ->  o mesmo arquivo, só com essa marca

O RefId do SKU é o código do fabricante como ele imprime (Arteb "0160708", Nakata "N93035"), menos nas
marcas em que a loja põe um prefixo dela (PREFIXOS). A aplicação vem dos campos montadora -> modelos e
"Ano do Veículo"; o ano vale para o produto inteiro. Todos os SKUs têm foto, em até 1200x1200.
"""
import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests

from vtex import POR_PAGINA

BASE = "https://www.altese.com.br"
SAIDA = Path("catalogos/altese.jsonl")
LIMITE_BUSCA = 2500  # a busca da VTEX não pagina além disso
PRECO_MAXIMO = 100000  # nenhum produto custa mais que isso
IGNORADAS = {"Altese Combos e Kit", "Alternativo"}  # kits montados pela loja e peça sem fabricante
# prefixo que a loja põe no código do fabricante ("FIT36034D" é o 36034D da Fitam). Só entra marca em que, no
# helper, nenhum código bate como a loja mostra e pelo menos 3 batem sem o prefixo (conferido em 2026-10-03).
# Ficam de fora as marcas em que o prefixo é do código em algum site (Frasle PD, Contitech CT, DS, Valclei),
# a Tirreno (oficial é FLU/DS/...), a Paraflu (formato diferente) e as marcas sem códigos no helper para conferir.
PREFIXOS = {"Fitam": "FIT", "TG POLI": "TG", "SKF": "SKF", "LUXCAR": "LUX", "Dyna": "DYN", "Elper": "ELP",
            "Schadek": "SCH", "Dayco": "DAY", "KYB": "KYB", "Blawer": "BLA", "Gates": "GAT", "Orbi Química": "ORB",
            "NAT": "NAT", "Universal": "UNI", "Florio": "F", "AMPRI": "AMP", "IKS": "IKS", "AJE": "AJE", "Sampel": "SAM",
            "Proauto": "PRO", "Euro": "EUR", "SYL": "SYL", "Hella": "HEL", "AMS": "AMS", "NYTRON": "NY", "ATE": "ATE",
            "GRID Calotas": "GRI"}
LADO_RE = re.compile(r"\b(esq|dir|esquerd[oa]|direit[oa]|motorista|passageiro)\b", re.I)


_local = threading.local()


def _get(caminho):
    """Uma sessão (conexão reaproveitada) por thread: a loja recusa conexões novas em rajada ("curl: (7) Could not
    connect"), e o Fetcher do Scrapling abre uma por chamada. Recusa, timeout e 500 ("The operation was canceled",
    com várias buscas juntas) são passageiros."""
    if not hasattr(_local, "sessao"):
        _local.sessao = requests.Session()
        _local.sessao.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    for espera in (5, 15, 30, None):
        try:
            r = _local.sessao.get(f"{BASE}/api/catalog_system/pub/{caminho}", timeout=60)
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
    # um erro aqui faria a faixa inteira ser pulada sem aviso, então _get insiste antes de desistir
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
            print(f"AVISO {fq} R$ {de}-{ate}: {n} produtos, só os {LIMITE_BUSCA} primeiros serão lidos")
        return [faixa] if n else []
    meio = round((de + ate) / 2, 2)  # as faixas incluem as pontas: o preço do meio sai nas duas
    return filtros(fq, de, meio) + filtros(fq, meio, ate)


def codigo(marca, ref):
    prefixo = PREFIXOS.get(marca)
    return ref[len(prefixo):] if prefixo and ref.startswith(prefixo) and len(ref) > len(prefixo) else ref


def veiculos(produto):
    """'Todas as Montadoras': ['Chevrolet'], 'Chevrolet': ['Omega'], 'Ano do Veículo :': ['1992', ..., '1998']
    -> 'Chevrolet Omega 1992-1998'."""
    anos = sorted(int(a) for a in produto.get("Ano do Veículo :") or [] if a.isdigit())
    faixa = "-".join(dict.fromkeys(str(a) for a in (anos[0], anos[-1]))) if anos else ""
    partes = [" ".join(filter(None, (montadora, modelo, faixa)))
              for montadora in produto.get("Todas as Montadoras") or [] for modelo in produto.get(montadora) or []]
    return "; ".join(dict.fromkeys(partes)) or None


def registros(produto):
    if produto.get("brand") in IGNORADAS:
        return
    varios = len(produto["items"]) > 1
    for item in produto["items"]:
        imagens = [i["imageUrl"].split("?")[0] for i in item.get("images", [])]
        if not imagens:
            continue
        ref = next((r["Value"] for r in item.get("referenceId") or [] if r.get("Key") == "RefId"), None)
        ref = ref or produto.get("productReference")
        # o nameComplete junta o nome do produto com o do SKU; só o do SKU diz o lado ("Farol Corsa ... Esq")
        nome = item.get("name") if varios else produto["productName"]
        lado = (item.get("Selecione o Lado Desejado") or [""])[0].split(" - ")[0]  # "Esquerdo - Motorista"
        if varios and lado and not LADO_RE.search(nome):
            nome += f" Lado {lado}"
        yield {"site": "altese", "url": f"{BASE}/{produto['linkText']}/p" + (f"?skuId={item['itemId']}" if varios else ""),
               "nome": nome, "marca": produto.get("brand"),
               "codigo_fabricante": codigo(produto.get("brand"), ref) if ref else None,
               "ean": item.get("ean") or None, "imagens": list(dict.fromkeys(imagens)), "carro": veiculos(produto)}


def sem_ean_repetido(regs):
    """A loja repete EAN em códigos diferentes (lado direito com o EAN do esquerdo, kit com o da unidade): não dá
    para saber qual é o certo, e o EAN errado funde peças diferentes no helper. O código continua casando."""
    codigos = {}
    for r in regs:
        if r["ean"]:
            codigos.setdefault(r["ean"], set()).add((r["marca"], r["codigo_fabricante"]))
    for r in regs:
        if r["ean"] and len(codigos[r["ean"]]) > 1:
            r["ean"] = None
    return regs


def marcas_para_ler(lista, marca=None):
    # a lista da loja repete marca com o mesmo id (Bosch), o que contaria os produtos dela duas vezes
    marcas = [m for m in {m["id"]: m for m in lista}.values() if m.get("isActive") and m["name"] not in IGNORADAS]
    if marca:
        marcas = [m for m in marcas if m["name"].lower() == marca.lower()]
        if not marcas:
            raise SystemExit(f"marca {marca!r} não encontrada em {BASE}")
    return marcas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-m", "--marca", help="só os produtos desta marca (ex.: Arteb)")
    args = ap.parse_args()
    marcas = marcas_para_ler(api("brand/list"), args.marca)
    with ThreadPoolExecutor(max_workers=3) as pool:
        partes = [fq for lista in pool.map(lambda m: filtros(f"fq=B:{m['id']}"), marcas) for fq in lista]
        esperado = sum(pool.map(total, [f"fq=B:{m['id']}" for m in marcas]))
        vistos, regs = set(), []
        for lote in pool.map(lambda fq: list(produtos(fq)), partes):
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
    print(f"{len(vistos)} de {esperado} produtos lidos em {len(partes)} buscas; {len(regs)} SKUs -> {SAIDA} "
          f"({descartados} EANs descartados por estarem em mais de um código)")


if __name__ == "__main__":
    main()
