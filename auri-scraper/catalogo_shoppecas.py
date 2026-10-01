#!/usr/bin/env python3
"""Catálogo da ShopPeças (loja Wake Commerce) -> catalogos/shoppecas.jsonl, só metadados.

Uso:
    python catalogo_shoppecas.py                  # catálogo inteiro (retoma se interrompido)
    python catalogo_shoppecas.py --limite 50 -o /tmp/amostra.jsonl

Os dados vêm da API GraphQL da vitrine Wake (storefront-api.fbits.net), com o token
público que a própria loja coloca em todas as páginas para o navegador usar. Ela devolve
50 produtos por requisição com EAN, SKU, marca, fotos e descrição -> ~830 requisições
para o catálogo inteiro (~41 mil variações), uma de cada vez.

Quase tudo na loja é do grupo Universal Automotive (Universal, Uniflex, Amortex, Micro,
Unick). O EAN e o SKU da API muitas vezes são da própria loja (prefixos 7906400, 779179x,
780514x...); o EAN e o código do fabricante verdadeiros ficam na descrição
("Código Universal do Produto (EAN): ...", "SKU Universal: 97073"), por isso têm prioridade.

Uma linha por variação com foto:
    {"site", "url", "nome", "marca", "codigo_fabricante", "ean", "imagens", "carro"}
Progresso (cursor da última página gravada) fica no .log ao lado do .jsonl.
"""
import argparse
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

LOJA = "https://www.shoppecas.com.br"
API = "https://storefront-api.fbits.net/graphql"
TOKEN_PADRAO = "tcs_shopp_c9745c1eb9af4416b1a28018cda0e134"
POR_PAGINA = 50  # máximo aceito pela API
PAUSA = 0.5  # entre requisições (a paginação por cursor já obriga a ir uma de cada vez)
ESPERAS = (5, 15, 30, 60)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

QUERY = """query($after: String) {
  products(first: %d, after: $after, filters: {}, sortKey: NAME) {
    totalCount
    pageInfo { hasNextPage endCursor }
    nodes {
      mainVariant aliasComplete productName variantName sku ean
      productBrand { name }
      images { url order }
      informations { value }
    }
  }
}""" % POR_PAGINA

VEICULOS_RE = re.compile(r"VE[IÍ]CULOS APLIC[AÁ]VEIS|APLICA[CÇ][AÃ]O NOS SEGUINTES VE[IÍ]CULOS", re.I)
FIM_VEICULOS_RE = re.compile(r"^(IDENTIFICA|ESPECIFICA|MEDIDAS|ADAPTADORES|OBSERVA|N[ºo°] ORIGINAL|GARANTIA|"
                             r"INSTALA|CONTE[UÚ]DO|PERGUNTAS|DADOS T)|:$|^[^:]{2,45}:\s*\S", re.I)
TRACOS_RE = re.compile(r"^[-_=\s]+$")
MARCAS_LIXO = {"Excluir"}  # "marca" usada pela loja para esconder produtos


class Bloqueio(Exception):
    pass


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def gtin(valor):
    """Normaliza para EAN-13 (ou EAN-8) e confere o dígito verificador; senão None."""
    m = re.search(r"\d{8,14}", valor or "")
    d = m.group(0) if m else ""
    if len(d) == 14 and d.startswith("0"):
        d = d[1:]
    elif len(d) == 12:
        d = "0" + d
    if not d.isdigit() or len(d) not in (8, 13):
        return None
    soma = sum(int(c) * (1 if i % 2 else 3) for i, c in enumerate(reversed(d[:-1])))
    return d if (10 - soma % 10) % 10 == int(d[-1]) else None


def linhas(valor):
    raw = re.sub(r"<(br|hr)\b[^>]*>|</?(p|div|li|h\d)\b[^>]*>", "\n", valor or "", flags=re.I)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace("\xa0", " ")
    return [re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")]


def campo(ls, rotulo):
    """Valor de 'Rótulo: valor' na ficha 'IDENTIFICAÇÃO DO PRODUTO' da descrição."""
    r = re.compile(rf"^{rotulo}\s*:\s*(.+)$", re.I)
    for l in ls:
        m = r.match(l)
        if m:
            return m.group(1).strip()
    return None


def codigo_fabricante(ls, sku, ean):
    # "97073"; "97991x2" / "53112 x2" = kit com N unidades da mesma peça.
    # Kits de peças diferentes ("38095 / 38096") e códigos da loja ("SPP1262 (...)") ficam de fora.
    valor = campo(ls, r"SKU Universal(?: Automotive)?")
    m = re.fullmatch(r"(\d{4,6})(?:\s*x\s*\d+)?", valor or "", re.I)
    if m:
        return m.group(1)
    # Sem ficha na descrição: o SKU da loja é código Universal + 3 dígitos ("97073001"), mas só
    # vale quando o EAN do grupo Universal (789527 2 CCCCC D) traz o mesmo código.
    sku = (sku or "").strip()
    if re.fullmatch(r"\d{8}", sku) and (ean or "").startswith("7895272") and ean[7:12] == sku[:5]:
        return sku[:5]
    return None


def veiculos(ls):
    """Bloco 'VEÍCULOS APLICÁVEIS' -> 'Fiat: Uno G1 85 a 06; Ford: Escort 93 a 96'."""
    inicio = next((i for i, l in enumerate(ls) if VEICULOS_RE.search(l)), None)
    if inicio is None:
        return None
    resto = [l for l in ls[inicio + 1:] if l]
    grupos, montadora = {}, None
    for i, l in enumerate(resto):
        if TRACOS_RE.match(l):
            continue
        proxima = resto[i + 1] if i + 1 < len(resto) else ""
        if FIM_VEICULOS_RE.search(l) or TRACOS_RE.match(proxima):  # próxima seção
            break
        m = re.match(r"^(.*?[^-\s])\s*-{3,}$", l)  # "Ford-----------"
        if m or (not l.startswith("-") and proxima.startswith("-") and l.upper() == l):  # "FORD" + "- Cargo"
            montadora = (m.group(1) if m else l).strip()
            continue
        grupos.setdefault(montadora, []).append(l.lstrip("- ").strip())
    partes = [(f"{m}: " if m else "") + ", ".join(dict.fromkeys(vs)) for m, vs in grupos.items() if vs]
    return "; ".join(partes) or None


def registro(p):
    imagens = [i["url"].split("?")[0] for i in sorted(p.get("images") or [], key=lambda i: i["order"]) if i.get("url")]
    if not imagens:
        return None
    blocos = [linhas(i.get("value")) for i in p.get("informations") or []]
    ls = [l for b in blocos for l in b]
    marca_api = (p.get("productBrand") or {}).get("name")
    # variações escondidas (mesma peça anunciada para outro carro) só se distinguem pelo variantName
    nome = p.get("productName") if p.get("mainVariant") else (p.get("variantName") or p.get("productName"))
    ean = gtin(campo(ls, r"(?:.{0,40}\()?EAN\)?")) or gtin(p.get("ean"))
    return {
        "site": "shoppecas",
        "url": f"{LOJA}/{p['aliasComplete']}",
        "nome": (nome or "").strip() or None,
        "marca": campo(ls, "Marca") or (marca_api if marca_api not in MARCAS_LIXO else None),
        "codigo_fabricante": codigo_fabricante(ls, p.get("sku"), ean),
        "ean": ean,
        "imagens": list(dict.fromkeys(imagens)),
        # as categorias de veículo da loja não servem: produtos sem aplicação caem todos em "BMW 320"
        "carro": next(filter(None, map(veiculos, blocos)), None),
    }


def token_da_loja(sessao):
    try:
        r = sessao.get(LOJA + "/", timeout=60)
        m = re.search(r'storefrontAccessToken\s*:\s*"([^"]+)"', r.text)
        if m:
            return m.group(1)
    except requests.RequestException:
        pass
    return TOKEN_PADRAO


class Api:
    def __init__(self, log):
        self.log = log
        self.pausa = PAUSA
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Origin": LOJA, "Referer": LOJA + "/"})
        self.s.headers.update({"Content-Type": "application/json", "TCS-Access-Token": token_da_loja(self.s)})

    def pagina(self, cursor):
        for tentativa, espera in enumerate((*ESPERAS, None)):
            time.sleep(self.pausa)
            try:
                r = self.s.post(API, json={"query": QUERY, "variables": {"after": cursor}}, timeout=90)
                json_ok = "json" in r.headers.get("content-type", "")
                if r.status_code == 403 or (not json_ok and "captcha" in r.text[:5000].lower()):
                    # bloqueio: diminui o ritmo daqui em diante e avisa no log
                    self.pausa = min(self.pausa * 4, 30)
                    raise Bloqueio(f"HTTP {r.status_code} (bloqueio/captcha) - pausa agora {self.pausa}s")
                if r.status_code == 429:
                    self.pausa = min(self.pausa * 2, 10)  # a API da Wake limita por minuto: diminui o ritmo
                    raise requests.HTTPError(f"HTTP 429 - pausa agora {self.pausa}s")
                if r.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                d = r.json()
                if not d.get("data") or not d["data"].get("products"):
                    raise requests.HTTPError(f"resposta sem dados: {str(d.get('errors'))[:300]}")
                return d["data"]["products"]
            except (requests.RequestException, ValueError, Bloqueio) as e:
                if espera is None:
                    raise
                self.log(f"AVISO tentativa {tentativa + 1}: {e}; aguardando {espera}s")
                time.sleep(espera)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="catalogos/shoppecas.jsonl")
    ap.add_argument("--limite", type=int, help="para depois de N variações lidas (teste)")
    args = ap.parse_args()
    saida = Path(args.output)
    saida.parent.mkdir(parents=True, exist_ok=True)
    arq_log = saida.with_suffix(".log")

    def log(msg):
        linha = f"{agora()} {msg}"
        print(linha, flush=True)
        with arq_log.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")

    # Retomada: continua do cursor da última página gravada, se a execução anterior não terminou.
    # Registros já presentes no arquivo não são gravados de novo.
    cursor = None
    if arq_log.exists():
        for l in arq_log.read_text(encoding="utf-8").splitlines():
            if " cursor=" in l:
                cursor = l.split(" cursor=", 1)[1].strip() or None
            elif " CONCLUIDO" in l:
                cursor = None
    vistos = set()
    if saida.exists():
        for l in saida.read_text(encoding="utf-8").splitlines():
            if l.strip():
                vistos.add(json.dumps(json.loads(l), sort_keys=True, ensure_ascii=False))

    api = Api(log)
    log(f"INICIO {'retomando do cursor ' + cursor if cursor else 'do começo'}; {len(vistos)} registros já no arquivo")
    lidos = gravados = sem_foto = repetidos = 0
    n = 0
    inicio = time.time()
    while True:
        pg = api.pagina(cursor)
        n += 1
        novos = []
        for p in pg["nodes"]:
            lidos += 1
            reg = registro(p)
            if reg is None:
                sem_foto += 1
                continue
            chave = json.dumps(reg, sort_keys=True, ensure_ascii=False)
            if chave in vistos:
                repetidos += 1
                continue
            vistos.add(chave)
            novos.append(json.dumps(reg, ensure_ascii=False))
        if novos:
            with saida.open("a", encoding="utf-8") as f:
                f.write("\n".join(novos) + "\n")
        gravados += len(novos)
        cursor = pg["pageInfo"]["endCursor"]
        fim = not pg["pageInfo"]["hasNextPage"] or (args.limite and lidos >= args.limite)
        log(f"pagina {n} ({lidos}/{pg['totalCount']} lidos, {gravados} gravados, {sem_foto} sem foto, "
            f"{repetidos} repetidos, {time.time() - inicio:.0f}s) cursor={'' if fim and not args.limite else cursor}")
        if fim:
            break
    if not args.limite:
        log(f"CONCLUIDO {lidos} variações lidas, {gravados} gravadas, {sem_foto} sem foto, {repetidos} repetidos/já no arquivo")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
