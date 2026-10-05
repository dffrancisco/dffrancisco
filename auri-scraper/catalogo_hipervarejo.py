#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Hipervarejo (VTEX).

Uso: python catalogo_hipervarejo.py                ->  catalogos/hipervarejo.jsonl
     python catalogo_hipervarejo.py --marca Arteb  ->  o mesmo arquivo, só com essa marca
"""
import argparse
import html
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

from curl_cffi import CurlError
from scrapling.fetchers import FetcherSession

from catalogo_altese import sem_ean_repetido
from catalogo_autonext import texto_carro
from hipervarejo_scraper import aplicacoes
from vtex import POR_PAGINA
from wayap_fotos import marcas_compativeis, n_ean, n_marca, sem_acento

BASE = "https://hipervarejo.com.br"
SAIDA = Path("catalogos/hipervarejo.jsonl")
LIMITE_BUSCA = 2500  # a busca da VTEX não pagina além disso
PRECO_MAXIMO = 100000  # nenhum produto custa mais que isso
INTERVALO = 0.5  # no máximo 2 requisições por segundo, somando as threads
EAN_DA_LOJA = "791"  # o GS1 não deu o prefixo 791 a ninguém (o Brasil é 789-790): é numeração da própria loja
# código da loja (Fortbras) no lugar do RefId: 'BR10504401649' sempre; '0636397' quando a ficha não diz que é ele
# mesmo (a Kostal tem 1510520, a Arteb 0160594)
INTERNO_RE = re.compile(r"BR\d{11}")
NUMERO_DA_LOJA_RE = re.compile(r"[01]\d{6}")
# kit que a loja monta: 'SKHG33036_C1' (4 amortecedores), 'HG33036_D' (2 dianteiros), 'KT0460361ART' (par de lanternas),
# 'KIT155722400002' (2 pneus), 'PALHETASTRADA' (par de palhetas)
KIT_RE = re.compile(r"^(KIT|KT|SK|PAR|PALHETA)|_[CDTP]\d?(_\d+)?$")
LIXO_FICHA = {"DUP", "DUP1", "DUP2", "DUP3", "PART", "DIV"}  # marcas de duplicado no fim do 'Número de peça'
ABREVIACOES = {}  # marca -> abreviações que não são as 3 primeiras letras do nome

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
    """A loja fica atrás de um desafio da Vercel: requests leva 429, o Fetcher do Scrapling (TLS de navegador)
    passa. Uma sessão por thread reaproveita a conexão. 500 ("The operation was canceled.", com várias buscas
    pesadas juntas), 429 e conexão caída são passageiros."""
    if not hasattr(_local, "sessao"):
        _local.sessao = FetcherSession(stealthy_headers=True, timeout=90, retries=1).__enter__()
    for espera in (5, 15, 30, 60, None):
        _esperar_vez()
        try:
            r = _local.sessao.get(f"{BASE}/api/catalog_system/pub/{caminho}")
            if r.status in (200, 206):  # a busca paginada responde 206
                return r
            erro = f"HTTP {r.status}"
            if r.status < 500 and r.status != 429:
                break
        except CurlError as e:
            erro = str(e)
        if espera is None:
            break
        time.sleep(espera)
    raise RuntimeError(f"{erro} em {caminho}")


def api(caminho):
    return json.loads(_get(caminho).body)


def pagina(fq, inicio, n=POR_PAGINA):
    """(produtos, total da busca): o total vem no cabeçalho de qualquer página."""
    r = _get(f"products/search?{fq}&_from={inicio}&_to={inicio + n - 1}")
    return json.loads(r.body), int((r.headers.get("resources") or "0-0/0").split("/")[-1])


def total(fq):
    return pagina(fq, 0, 1)[1]


def produtos(fq, primeira=None):
    lote, inicio = primeira if primeira is not None else pagina(fq, 0)[0], 0
    while True:
        yield from lote
        inicio += POR_PAGINA
        if len(lote) < POR_PAGINA or inicio >= LIMITE_BUSCA:
            return
        lote = pagina(fq, inicio)[0]


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


def da_marca(id_marca):
    """(produtos sem repetir, total que a loja informa). A primeira página já traz o total; acima do limite da
    busca a marca é relida em faixas de preço."""
    fq = f"fq=B:{id_marca}"
    lote, n = pagina(fq, 0)
    lidos = produtos(fq, lote) if n <= LIMITE_BUSCA else (p for f in filtros(fq) for p in produtos(f))
    return list({p["productId"]: p for p in lidos}.values()), n


# ---------------------------------------------------------------- código do fabricante

def _limpo(codigo):
    return re.sub(r"[^A-Z0-9]", "", sem_acento(codigo or "").upper())


def abreviacoes(marca):
    """Abreviação que a loja cola no código: as 3 primeiras letras da marca ('0460447_ART', 'N2005COB')."""
    nome = n_marca(marca)
    return ({nome, nome[:3]} | ABREVIACOES.get(marca, set())) - {""}


def _refid(item):
    return next((r["Value"] for r in item.get("referenceId") or [] if r.get("Key") == "RefId"), None) or ""


def sem_loja(codigo, marca):
    """Tira o que a loja põe em volta do código: VAR e o índice da variação, a abreviação da marca
    ('VAR23115_AMP3' -> '23115'). None se for código interno ou se o índice estiver colado ('VARF000KE0P111')."""
    c = " ".join(codigo.split()).upper()
    var = c.startswith("VAR")
    c = c[3:] if var else c
    abv = "|".join(sorted(map(re.escape, abreviacoes(marca)), key=len, reverse=True))
    m = re.fullmatch(rf"(.+?)[_ ]?(?:{abv})([_ ]?\d{{1,2}})?", c) if abv else None
    if m and re.search(r"\d", m[1]) and (var or not m[2]):
        c = m[1]
    elif var:
        m = re.fullmatch(r"(.+?)_\d{1,2}", c)
        if not m:
            return None
        c = m[1]
    c = c.strip("_ ").replace("_", " ")
    return c if c and re.search(r"\d", c) and not INTERNO_RE.fullmatch(c) else None


def _partes(valores):
    texto = re.sub(r"<br\s*/?>|</?p\b[^>]*>", ";", " ; ".join(valores or []), flags=re.I)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    return [" ".join(p.split()) for p in re.split(r"[;,\n|]| / | ou ", texto) if p.strip()]


def _da_marca(parte, marca, so_da_marca):
    """'AXIOS 531.2708' -> '531.2708', '0160593 ART' -> '0160593'; 'MONROE SP289' (outra marca) -> None."""
    palavras = parte.split()
    while len(palavras) > 1 and (palavras[-1].upper() in LIXO_FICHA or _limpo(palavras[-1]) in abreviacoes(marca)):
        palavras.pop()
    n = next((i for i, p in enumerate(palavras) if re.search(r"\d", p)), len(palavras))
    prefixo = n_marca(" ".join(palavras[:n]))
    if len(prefixo) > 2:  # 'F 000 99C 609' é da Bosch mesmo
        if marcas_compativeis(prefixo, n_marca(marca)):
            palavras = palavras[n:]
        elif so_da_marca:
            return None
    return " ".join(palavras)


def da_ficha(produto, campo):
    """Códigos da ficha, sem o que a loja põe em volta. 'Número de peça' mistura os equivalentes de outras marcas:
    dele só ficam os sem marca e os da marca do produto."""
    marca = produto.get("brand") or ""
    codigos = {}
    for parte in _partes(produto.get(campo)):
        c = _da_marca(parte, marca, campo == "Número de peça")
        c = c and sem_loja(c, marca)  # a ficha às vezes repete o RefId ('22120_AMP')
        if c and len(_limpo(c)) >= 3:
            codigos.setdefault(_limpo(c), c)
    return list(codigos.values())


def _variantes(ref, marca):
    """Formas do RefId para comparar com a ficha, sem zeros à esquerda: sem o índice colado da variação e com a
    pontuação que a loja trocou por letra ('.' por X, '-' por Z, '/' por W)."""
    bases = {sem_loja(ref, marca) or ""}
    r = ref.upper()
    if r.startswith("VAR"):
        bases |= {_limpo(r[3:])[:-1], _limpo(r[3:])[:-2]}
    formas = set()
    for b in filter(None, map(_limpo, bases)):
        for letras in ("", "X", "Z", "W", "XZ", "XW", "ZW", "XZW"):
            formas.add(re.sub(f"[{letras}]", "", b).lstrip("0") if letras else b.lstrip("0"))
    return formas - {""}


def _com_zero(codigo, ref):
    """A ficha às vezes perde o zero à esquerda que o RefId tem ('280157133' / 'VAR02801571331')."""
    zeros = re.search(f"(0*){_limpo(codigo).lstrip('0')}", _limpo(ref))
    falta = len(zeros[1]) - (len(_limpo(codigo)) - len(_limpo(codigo).lstrip("0"))) if zeros else 0
    return "0" * falta + codigo if falta > 0 else codigo


def do_nome(produto):
    """'Farol de Milha Corsa Meriva Montana Motorista Arteb 0160275' -> '0160275': o código costuma vir logo depois
    da marca no nome."""
    marca, palavras = n_marca(produto.get("brand")), produto.get("productName", "").split()
    for i in range(len(palavras) - 1):
        if n_marca(palavras[i]) == marca and re.search(r"\d", palavras[i + 1]) and len(_limpo(palavras[i + 1])) >= 4 \
                and not re.fullmatch(r"(19|20)\d\d", palavras[i + 1]):
            return sem_loja(palavras[i + 1], produto.get("brand") or "")
    return None


def kit_da_loja(produto, item):
    """Kit que a loja monta (2 amortecedores, par de faróis, 4 pneus...): o código e o EAN são de uma peça só."""
    ref = _refid(item).upper()
    if not KIT_RE.search(ref):
        return False
    proprio = _limpo(sem_loja(ref, produto.get("brand") or "") or ref)  # 'KTC03203_COF' é código da Cofap
    return not any(_limpo(c) == proprio for c in da_ficha(produto, "Código do fabricante"))


def codigo_fabricante(produto, item):
    marca, ref = produto.get("brand") or "", _refid(item).strip()
    ficha = da_ficha(produto, "Código do fabricante")
    pecas = da_ficha(produto, "Número de peça")
    if NUMERO_DA_LOJA_RE.fullmatch(ref):  # a loja às vezes copia o próprio número na ficha
        outros = [c for c in ficha + pecas if _limpo(c) != ref]
        if len(outros) < len(ficha + pecas) and not outros:
            return ref  # só ele na ficha: é da marca
        ficha, pecas, ref = [c for c in ficha if c in outros], [c for c in pecas if c in outros], ""
    formas = _variantes(ref, marca) if ref else set()
    for c in ficha + pecas:  # a ficha confirma o RefId: fica a grafia dela ('531.2712', 'N-1804C')
        if _limpo(c).lstrip("0") in formas:
            return _com_zero(c, ref)
    base = sem_loja(ref, marca) if ref else None
    if base or len(produto["items"]) > 1:  # com vários SKUs, a ficha é de um só
        return base
    for lista in (ficha, pecas):  # RefId interno da loja ('0636397')
        if lista:
            return lista[0] if len(lista) == 1 else None
    return do_nome(produto)


# ---------------------------------------------------------------- registros

def ean(produto, item):
    """Com um SKU só, o EAN do item e o da ficha têm de bater: quando divergem, ora um ora outro é o certo. Com
    vários, a ficha é de um SKU só e fica o do item, se nenhum outro SKU tiver o mesmo."""
    def valido(e):
        e = n_ean(e)
        return e if e and not e.startswith(EAN_DA_LOJA) else None
    do_item = valido(item.get("ean"))
    if len(produto["items"]) > 1:
        return None if sum(valido(i.get("ean")) == do_item for i in produto["items"]) > 1 else do_item
    da_ficha = {valido(e) for e in re.findall(r"\d{8,14}", " ".join(produto.get("Código de barras (EAN)") or []))} - {None}
    if do_item and da_ficha and do_item not in da_ficha:
        return None
    return do_item or (da_ficha.pop() if len(da_ficha) == 1 else None)


def nome(produto, item):
    """Com vários SKUs, o nome do SKU às vezes está trocado (esquerdo chamado de direito); o da variação é confiável."""
    if len(produto["items"]) == 1:
        return produto["productName"]
    variacao = ", ".join(v for var in item.get("variations") or [] for v in item.get(var) or [])
    return f"{produto['productName']} - {variacao}" if variacao else item.get("nameComplete") or produto["productName"]


def registros(produto):
    varios = len(produto["items"]) > 1
    carro = None
    for item in produto["items"]:
        imagens = [i["imageUrl"].split("?")[0] for i in item.get("images", [])]
        if not imagens or kit_da_loja(produto, item):
            continue
        carro = carro or texto_carro(aplicacoes(produto)[0])
        yield {"site": "hipervarejo", "url": f"{BASE}/{produto['linkText']}/p" + (f"?skuId={item['itemId']}" if varios else ""),
               "nome": nome(produto, item), "marca": produto.get("brand"),
               "codigo_fabricante": codigo_fabricante(produto, item), "ean": ean(produto, item),
               "imagens": list(dict.fromkeys(imagens)), "carro": carro}


PARCIAL = SAIDA.with_suffix(".parcial.jsonl")


def registros_da_marca(id_marca):
    """(total da loja, [(productId, registros)]): o produto bruto (com a descrição em HTML) não sai da thread; com
    todas as marcas na fila, guardar o bruto das já lidas passava de 7 GB."""
    produtos, n = da_marca(id_marca)
    return n, [(p["productId"], list(registros(p))) for p in produtos]


def gravar_parcial(caminho, id_marca, n, lidos):
    with Path(caminho).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"marca": id_marca, "n": n, "lidos": lidos}, ensure_ascii=False) + "\n")


def ler_parcial(caminho):
    """{id da marca: (total, [(productId, registros)])} das marcas já lidas; a última linha pode estar cortada."""
    lidas = {}
    if Path(caminho).exists():
        for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(linha)
            except json.JSONDecodeError:
                continue
            lidas[d["marca"]] = (d["n"], [(pid, regs) for pid, regs in d["lidos"]])
    return lidas


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
    lidas = ler_parcial(PARCIAL)  # retoma: marca já lida numa execução interrompida não é lida de novo
    faltam = [m for m in marcas if m["id"] not in lidas]
    print(f"{len(marcas)} marcas, {len(marcas) - len(faltam)} já lidas antes", flush=True)
    falhas = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futuros = {pool.submit(registros_da_marca, m["id"]): m for m in faltam}
        for feitas, futuro in enumerate(as_completed(futuros), 1):
            marca = futuros[futuro]
            try:
                n, lidos = futuro.result()
            except RuntimeError as e:  # segue com as outras marcas; a contagem final mostra o que faltou
                falhas.append(marca["name"])
                print(f"ERRO marca {marca['name']}: {e}", file=sys.stderr)
                continue
            gravar_parcial(PARCIAL, marca["id"], n, lidos)
            lidas[marca["id"]] = (n, lidos)
            if feitas % 100 == 0:
                print(f"{feitas}/{len(faltam)} marcas, {time.monotonic() - inicio:.0f}s", flush=True)
    vistos, regs = set(), []
    for _, (_, lidos) in sorted(lidas.items()):
        for pid, rs in lidos:
            if pid not in vistos:
                vistos.add(pid)
                regs += rs
    esperado = sum(n for n, _ in lidas.values())
    com_ean = sum(bool(r["ean"]) for r in regs)
    descartados = com_ean - sum(bool(r["ean"]) for r in sem_ean_repetido(regs))
    SAIDA.parent.mkdir(exist_ok=True)
    with SAIDA.open("w", encoding="utf-8") as f:
        for r in regs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if not falhas and not args.marca:
        PARCIAL.unlink(missing_ok=True)
    print(f"{len(vistos)} de {esperado} produtos lidos ({len(marcas)} marcas, {len(falhas)} com erro: {falhas[:20]}); "
          f"{len(regs)} SKUs -> {SAIDA} ({descartados} EANs descartados por estarem em mais de um código) "
          f"em {time.monotonic() - inicio:.0f}s")

if __name__ == "__main__":
    main()
