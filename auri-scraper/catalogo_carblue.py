#!/usr/bin/env python3
"""Catálogo da CarBlue (https://www.carblue.com.br) para casar fotos por EAN / código do fabricante.

A loja roda na Wake Commerce (antiga Fbits). Em vez de abrir as ~110 mil páginas de produto, lê a
API GraphQL da vitrine (a mesma que o JavaScript do site chama, com o token público que vem no
HTML), 50 produtos por requisição.

Uso:
    python catalogo_carblue.py                  # catálogo inteiro -> catalogos/carblue.jsonl
    python catalogo_carblue.py --limite 50      # teste rápido

Uma linha por produto/variação com foto:
    {"site", "url", "nome", "marca", "codigo_fabricante", "ean", "imagens", "carro"}
Variações (lado direito/esquerdo...) têm a mesma URL; cada uma leva só as próprias fotos, na
resolução original. EAN só com dígito verificador válido; campo sem valor fica null.
Retomável: o progresso de cada parte do catálogo fica no .log ao lado da saída; ao rodar de novo,
continua de onde parou e não repete linhas que já estão no .jsonl.
"""
import argparse
import html
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import requests

SITE = "https://www.carblue.com.br"
API = "https://storefront-api.fbits.net/graphql"
TOKEN_RE = re.compile(r'storefrontAccessToken:\s*"(tcs_\w+)"')
TOKEN_CONHECIDO = "tcs_carbl_ba29618382db40fbbaf5cd8b4d66c1fd"  # visto no HTML em 2026-09
POR_PAGINA = 50  # máximo aceito pela API
PARALELO = 3
ESPERAS = (5, 15, 30, 60)
NULOS = {"", "N/A", "NA", "-", "0", "."}

# A paginação da API é por cursor (sequencial); estes filtros dividem o catálogo inteiro sem
# sobreposição para ler em paralelo. A lista de marcas da API não serve: omite marcas com produtos.
PARTES = {
    "principal-disponivel": {"mainVariant": True, "available": True},
    "principal-indisponivel": {"mainVariant": True, "available": False},
    "variacao-disponivel": {"mainVariant": False, "available": True},
    "variacao-indisponivel": {"mainVariant": False, "available": False},
}
PRODUTOS = """query($filtros: ProductExplicitFiltersInput!, $depois: String, $n: Int) {
  products(first: $n, after: $depois, filters: $filtros, sortKey: NAME, sortDirection: ASC) {
    totalCount pageInfo { hasNextPage endCursor }
    nodes { productVariantId productName aliasComplete ean productBrand { name } images { url fileName order }
            attributes { name value } informations { title value } } } }"""


class Retentavel(Exception):
    pass


class Catalogo:
    def __init__(self, saida, limite):
        self.saida, self.log_path, self.limite = saida, saida.with_suffix(".log"), limite
        self.trava = threading.Lock()
        self.local = threading.local()
        # Espaçamento mínimo entre requisições (somando as threads): ~75/min fica abaixo do limite da API
        self.intervalo, self.ultimo, self.ultimo_429 = 0.8, 0.0, 0.0
        self.bloqueios = self.limitados = self.erros = self.gravados = 0
        self.linhas = self._linhas_existentes()
        self.progresso = self._progresso()
        self.token = None

    def _linhas_existentes(self):
        if not self.saida.exists():
            return set()
        texto = self.saida.read_text(encoding="utf-8")
        linhas = texto.splitlines()
        # Última linha cortada por uma interrupção no meio da escrita: descarta
        if linhas and not texto.endswith("\n"):
            linhas.pop()
            self.saida.write_text("".join(l + "\n" for l in linhas), encoding="utf-8")
        return set(linhas)

    def _progresso(self):
        """{parte: último cursor lido} a partir do log; None = parte concluída."""
        progresso = {}
        if self.log_path.exists():
            for m in re.finditer(r"^\S+ \S+ (PAGINA|CONCLUIDA) parte=(\S+)(?:.* depois=(\S+))?",
                                 self.log_path.read_text(encoding="utf-8"), re.M):
                progresso[m[2]] = m[3] if m[1] == "PAGINA" else None
        return progresso

    def log(self, msg):
        linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
        print(linha, flush=True)
        with self.trava, self.log_path.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")

    def sessao(self):
        if not hasattr(self.local, "s"):
            self.local.s = requests.Session()
            self.local.s.headers["User-Agent"] = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
        return self.local.s

    def aguardar_vez(self):
        with self.trava:
            espera = self.ultimo + self.intervalo - time.monotonic()
            self.ultimo = time.monotonic() + max(espera, 0)
        if espera > 0:
            time.sleep(espera)

    def pedir(self, metodo, url, **kw):
        for espera in (*ESPERAS, None):
            self.aguardar_vez()
            try:
                r = self.sessao().request(metodo, url, timeout=60, **kw)
                if r.status_code == 429:  # a API aceita uma rajada e depois limita por minuto
                    with self.trava:
                        self.limitados += 1
                        if time.monotonic() - self.ultimo_429 > 10:  # as 3 threads recebem 429 juntas
                            self.intervalo = min(self.intervalo * 1.5, 10)
                        self.ultimo_429 = time.monotonic()
                    raise Retentavel(f"HTTP 429 - desacelerando para 1 requisição a cada {self.intervalo:.1f}s")
                if r.status_code >= 500:
                    raise Retentavel(f"HTTP {r.status_code}")
                # A API sempre responde JSON; HTML no lugar dela é página de bloqueio/captcha
                if r.status_code == 403 or (url == API and "json" not in r.headers.get("content-type", "")):
                    with self.trava:
                        self.bloqueios += 1
                        self.intervalo = min(max(self.intervalo * 2, 1), 10)
                    raise Retentavel(f"HTTP {r.status_code} {r.headers.get('content-type')} (bloqueio?) - "
                                     f"desacelerando para 1 requisição a cada {self.intervalo:.0f}s")
                r.raise_for_status()
                return r
            except (requests.ConnectionError, requests.Timeout, Retentavel) as e:
                if espera is None:
                    raise
                self.log(f"AVISO {url}: {e}; nova tentativa em {espera}s")
                time.sleep(espera)

    def graphql(self, consulta, variaveis):
        r = self.pedir("POST", API, json={"query": consulta, "variables": variaveis},
                       headers={"TCS-Access-Token": self.token})
        dados = r.json()
        if dados.get("errors"):
            raise RuntimeError(f"GraphQL: {dados['errors']}")
        return dados["data"]

    def total(self, filtros):
        return self.graphql(PRODUTOS, {"filtros": filtros, "n": 1})["products"]["totalCount"]

    def gravar(self, registros):
        with self.trava:
            novos = []
            for reg in registros:
                linha = json.dumps(reg, ensure_ascii=False)
                if linha not in self.linhas and not self.completo():
                    self.linhas.add(linha)
                    novos.append(linha)
                    self.gravados += 1
            if novos:
                with self.saida.open("a", encoding="utf-8") as f:
                    f.write("".join(l + "\n" for l in novos))
        return len(novos)

    def completo(self):
        return self.limite is not None and self.gravados >= self.limite

    def baixar_parte(self, nome):
        depois, lidos, novos, total = self.progresso.get(nome), 0, 0, None
        try:
            while not self.completo():
                try:
                    pagina = self.graphql(PRODUTOS, {"filtros": PARTES[nome], "depois": depois, "n": POR_PAGINA})["products"]
                except RuntimeError:
                    if not depois or lidos:
                        raise
                    self.log(f"AVISO parte={nome}: cursor salvo não aceito, recomeçando a parte do início")
                    depois = None
                    continue
                total = pagina["totalCount"]
                lidos += len(pagina["nodes"])
                novos += self.gravar([r for r in map(registro, pagina["nodes"]) if r])
                if self.completo():  # o limite pode ter cortado esta página: não registra como lida
                    break
                if not pagina["pageInfo"]["hasNextPage"]:
                    self.log(f"CONCLUIDA parte={nome} lidos={lidos} total={total} novas={novos}")
                    return
                depois = pagina["pageInfo"]["endCursor"]
                self.log(f"PAGINA parte={nome} lidos={lidos} total={total} novas={novos} depois={depois}")
        except Exception as e:  # segue com as outras partes; esta continua na próxima execução
            self.erros += 1
            self.log(f"ERRO parte={nome} após {lidos} produtos lidos: {e}")

    def obter_token(self):
        # Às vezes o CDN devolve a página comprimida sem avisar no cabeçalho: tenta de novo
        for _ in range(3):
            m = TOKEN_RE.search(self.pedir("GET", SITE + "/").text)
            if m:
                return m.group(1)
        self.log(f"AVISO token não encontrado na página inicial; usando {TOKEN_CONHECIDO}")
        return TOKEN_CONHECIDO

    def executar(self):
        self.token = self.obter_token()

        totais = {nome: self.total(filtros) for nome, filtros in PARTES.items()}
        geral = self.total({})
        if sum(totais.values()) != geral:
            self.log(f"AVISO as partes somam {sum(totais.values())} produtos, mas o catálogo tem {geral}")
        pendentes = [nome for nome in PARTES if self.progresso.get(nome, "") is not None]
        self.log(f"INICIO catálogo com {geral} produtos {totais}; partes pendentes: {pendentes}; "
                 f"{len(self.linhas)} linhas já em {self.saida}")
        inicio = time.time()
        with ThreadPoolExecutor(max_workers=PARALELO) as pool:
            list(pool.map(self.baixar_parte, pendentes))
        self.log(f"FIM {self.gravados} linhas novas, {len(self.linhas)} no total, {self.erros} partes com erro "
                 f"(rode de novo para continuar), {self.limitados} respostas 429, {self.bloqueios} 403/captcha, "
                 f"intervalo final {self.intervalo:.1f}s, {time.time() - inicio:.0f}s")


def limpo(texto):
    texto = re.sub(r"\s+", " ", html.unescape(texto or "")).strip()
    # "[CODIGOFORNECEDOR]": campo do modelo de cadastro que ficou sem preencher
    return None if texto.upper() in NULOS or re.fullmatch(r"\[\w+\]", texto) else texto


def texto_html(valor):
    """'ELBA 85 86<br>UNO 85 86<br>' ou '<ul><li>UNIVERSAL</li></ul>' -> 'ELBA 85 86; UNO 85 86'"""
    valor = re.sub(r"<br\s*/?>|</(li|p|div)>", "\n", valor or "", flags=re.I)
    linhas = [limpo(re.sub(r"<[^>]+>", " ", l)) for l in valor.split("\n")]
    return "; ".join(l for l in linhas if l) or None


def gtin(codigo):
    """Só GTIN com dígito verificador válido; o site às vezes põe o código interno no campo EAN."""
    codigo = (codigo or "").strip()
    if not re.fullmatch(r"\d{8}|\d{12,14}", codigo) or not codigo.strip("0"):
        return None
    soma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(codigo[:-1])))
    return codigo if (10 - soma % 10) % 10 == int(codigo[-1]) else None


def fotos(p):
    """A API repete em cada variação as fotos de todas as variações do produto (lado direito e
    esquerdo...); o nome do arquivo começa pelo id da variação dona: '397746-1.jpg'."""
    proprias = []
    for img in p["images"] or []:
        dono, _, n = (img.get("fileName") or "").partition("-")
        if dono == str(p["productVariantId"]) and img.get("url"):
            proprias.append(((img["order"], int(n) if n.isdigit() else 0), img["url"]))
    # Sem parâmetros de tamanho o CDN devolve a imagem original (a API manda ?w=420&h=420).
    # O host vem ora "Carblue.fbitsstatic.net", ora "carblue...": padroniza para não duplicar linhas
    return list(dict.fromkeys(re.sub(r"^https?://[^/]+", lambda m: m[0].lower(), url.split("?")[0])
                              for _, url in sorted(proprias)))


def registro(p):
    imagens = fotos(p)
    if not imagens:
        return None
    atributos = {a["name"]: a["value"] for a in p["attributes"] or []}
    infos = {i["title"]: i["value"] for i in p["informations"] or []}
    codigo = limpo(atributos.get("PART_NUMBER"))
    if not codigo:
        m = re.search(r"C[óo]digo do Fornecedor:\s*([^<]+)", infos.get("Descrição") or "")
        codigo = limpo(m.group(1)) if m else None
    return {
        "site": "carblue",
        "url": f"{SITE}/{p['aliasComplete']}",
        "nome": limpo(p["productName"]),
        "marca": limpo((p["productBrand"] or {}).get("name") or atributos.get("Fabricante")),
        "codigo_fabricante": codigo,
        "ean": gtin(p["ean"]),
        "imagens": imagens,
        "carro": texto_html(infos.get("Veículos compatíveis")),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--saida", default=Path(__file__).parent / "catalogos" / "carblue.jsonl", type=Path)
    ap.add_argument("--limite", type=int, help="para depois de gravar N linhas novas (teste)")
    args = ap.parse_args()
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    Catalogo(args.saida, args.limite).executar()


if __name__ == "__main__":
    sys.exit(main())
