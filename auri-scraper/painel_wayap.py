#!/usr/bin/env python3
"""Painel local do Wayap: curadoria das fotos enviadas e cadastro de produtos pelos catálogos dos sites.

Uso (mesmas variáveis WAYAP_* do wayap_fotos.py):
    python painel_wayap.py [--porta 8765]
e abra http://localhost:8765

- Curadoria de fotos: cada foto enviada (lotes em fotos_wayap_<sociedade>*/plano.json). "Foto certa" só
  tira da lista; "Foto errada" tira da lista e apaga a foto no Wayap.
- Cadastrar dos sites: busca nos catálogos (catalogos/*.jsonl: KarHub, ShopPeças, CarBlue, Universal...) e
  cadastra no Wayap o produto escolhido, com custo e venda zerados, marca/carro/fornecedor/NCM/unidade sugeridos
  pelo que o cadastro já usa, e sobe as fotos (que entram na curadoria, lote fotos_wayap_<sociedade>_cadastro).
"""
import argparse
import hashlib
import html as html_texto
import json
import os
import re
import socket
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
import requests
import urllib3.util.connection
from flask import Flask, Response, abort, jsonify, redirect, request, send_file

from scrapling.fetchers import Fetcher

from aplicacao_texto import MONTADORAS_TITULO, juntar_anos, ocorrencias_do_texto

from wayap_fotos import (DISTANCIA_DUPLICADA, ENV_ADMIN, LADO_ENVIO, MAX_FOTOS, MENOR_LADO, Wayap, abrir_rgb, dhash,
                         distancia, gravar_plano, marcas_compativeis, n_codigo, n_ean, n_marca, sem_acento)

# esta rede não tem rota IPv6 e o cdn.shopify.com às vezes resolve primeiro para IPv6 ("Network is unreachable")
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

app = Flask(__name__)
trava = threading.Lock()
estado = {}

CATALOGOS = Path("catalogos")
DB_CATALOGOS = CATALOGOS / "catalogos.sqlite"
CACHE_IMAGENS = CATALOGOS / "cache_imagens"
NOMES_SITES = {"karhub": "KarHub", "shoppecas": "ShopPeças", "carblue": "CarBlue", "clicpecas": "ClicPeças",
               "fuscaopreto": "Fuscão Preto", "universal": "Universal", "azacessorios": "AZ Acessórios"}
# modelos da KarHub que o cadastro agrupa em outro carro (o nome original vai para o complemento)
ALIAS_MODELOS = {"CLASSIC": "CORSA", "CORSA CLASSIC": "CORSA"}
# montadoras que os sites escrevem antes do modelo na aplicação ('Mercedes-Benz Actros 2012', 'ALFA ROMEO: 145 94 a 01')
UNIDADE_PELA_PALAVRA = {"JOGO": "JG", "KIT": "KT", "PAR": "PA"}
PALAVRAS_GENERICAS = {"JOGO", "KIT", "PAR", "PARA", "COM", "SEM", "PECA", "PECAS"}
CONECTIVOS = {"PARA", "DA", "DE", "DO", "DAS", "DOS", "E", "COM"}
TAMANHO_DESCRICAO = 45  # maior descrição hoje no cadastro; o padrão da casa é curto
LIMITES = {"desc_produto": 100, "desc_produto_completa": 400, "num_fabricante": 15, "cod_barra": 13, "ncm": 8,
           "unidade": 2}


# ---------- catálogos dos sites (um SQLite com busca textual) ----------

def codigos_do_item(codigo):
    """Kits trazem vários códigos: 'GS2116 / GS2118' -> '|GS2116|GS2118|'."""
    partes = [n_codigo(c) for c in re.split(r"[/;,]", codigo or "")]
    return "|" + "|".join(p for p in partes if p) + "|"


def nome_site(site):
    return NOMES_SITES.get(site, site.title())


def linhas_do_catalogo(site, arquivo, hosts):
    with arquivo.open(encoding="utf-8") as f:
        for linha in f:
            try:
                r = json.loads(linha)
            except json.JSONDecodeError:
                continue  # linha vazia, ou cortada porque o catálogo ainda está sendo gravado
            imagens = r.get("imagens") or []
            hosts.update(urlsplit(u).hostname for u in imagens)
            yield (site, r.get("url"), r.get("nome"), r.get("marca"), r.get("codigo_fabricante"),
                   codigos_do_item(r.get("codigo_fabricante")), n_ean(r.get("ean")), r.get("carro"), json.dumps(imagens))


def indexar_catalogos():
    """Indexa catalogos/<site>.jsonl; só refaz o site cujo arquivo mudou (ou sumiu) desde a última vez."""
    db = sqlite3.connect(DB_CATALOGOS)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS item (id INTEGER PRIMARY KEY AUTOINCREMENT, site, url, nome, marca, codigo, codigos,
                                         ean, carro, imagens);
        CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5(nome, marca, codigo, carro, content='item',
                                                            content_rowid='id', tokenize='unicode61 remove_diacritics 2');
        CREATE INDEX IF NOT EXISTS item_ean ON item (ean);
        CREATE INDEX IF NOT EXISTS item_site ON item (site);
        CREATE TABLE IF NOT EXISTS fonte (site PRIMARY KEY, mtime, itens, hosts);
    """)
    feitos = dict(db.execute("SELECT site, mtime FROM fonte"))
    arquivos = {a.stem: a for a in CATALOGOS.glob("*.jsonl")}
    for site in sorted(set(feitos) | set(arquivos)):
        mtime = arquivos[site].stat().st_mtime if site in arquivos else None
        if feitos.get(site) == mtime:
            continue
        print(f"indexando catálogo {site} (só na primeira vez ou quando o arquivo muda)...")
        # o índice textual é externo (content='item'): as linhas saem dele antes de saírem de item
        db.execute("INSERT INTO busca (busca, rowid, nome, marca, codigo, carro) "
                   "SELECT 'delete', id, nome, marca, codigo, carro FROM item WHERE site = ?", (site,))
        db.execute("DELETE FROM item WHERE site = ?", (site,))
        db.execute("DELETE FROM fonte WHERE site = ?", (site,))
        if mtime is not None:
            hosts = set()
            db.executemany("INSERT INTO item (site, url, nome, marca, codigo, codigos, ean, carro, imagens) "
                           "VALUES (?,?,?,?,?,?,?,?,?)", linhas_do_catalogo(site, arquivos[site], hosts))
            db.execute("INSERT INTO busca (rowid, nome, marca, codigo, carro) "
                       "SELECT id, nome, marca, codigo, carro FROM item WHERE site = ?", (site,))
            itens = db.execute("SELECT count(*) FROM item WHERE site = ?", (site,)).fetchone()[0]
            db.execute("INSERT INTO fonte VALUES (?, ?, ?, ?)", (site, mtime, itens, json.dumps(sorted(filter(None, hosts)))))
        db.commit()
    db.close()


def db_catalogos():
    db = sqlite3.connect(DB_CATALOGOS)
    db.row_factory = sqlite3.Row
    return db


def sites_indexados():
    with db_catalogos() as db:
        return [dict(r) for r in db.execute("SELECT site, itens, hosts FROM fonte WHERE itens > 0 ORDER BY itens DESC")]


def item_do_catalogo(id_item):
    with db_catalogos() as db:
        item = db.execute("SELECT * FROM item WHERE id = ?", (id_item,)).fetchone()
    if not item:
        abort(404)
    return dict(item)


def buscar_catalogos(q, site="", limite=40, offset=0):
    """Uma página de resultados: EAN e código exatos vêm na primeira; a busca textual é paginada."""
    q = q.strip()
    filtro, args = ("AND item.site = ?", [site]) if site else ("", [])
    achados, textuais = [], []
    with db_catalogos() as db:
        if offset == 0 and n_ean(q):
            achados += db.execute(f"SELECT * FROM item WHERE ean = ? {filtro}", [n_ean(q)] + args).fetchall()
        if offset == 0 and " " not in q and len(n_codigo(q)) >= 3:
            achados += db.execute(f"SELECT * FROM item WHERE codigos LIKE ? {filtro} LIMIT 200",
                                  [f"%|{n_codigo(q)}|%"] + args).fetchall()
        termos = re.findall(r"\w+", sem_acento(q))
        if termos:
            consulta = " ".join(f'"{t}"*' for t in termos)
            textuais = db.execute(f"SELECT item.* FROM busca JOIN item ON item.id = busca.rowid WHERE busca MATCH ? "
                                  f"{filtro} ORDER BY rank LIMIT ? OFFSET ?", [consulta] + args + [limite, offset]).fetchall()
    vistos, lista = set(), []
    for r in achados + textuais:
        if r["id"] not in vistos:
            vistos.add(r["id"])
            lista.append(dict(r))
    return lista, len(textuais) == limite


# ---------- cadastro do Wayap (cache para sugestões e para saber o que já existe) ----------

def palavras_chave(desc):
    """Tipo da peça pelas duas primeiras palavras relevantes: 'JOGO CABO DE VELA' -> ('CABO VELA', 'CABO')."""
    ps = [p for p in re.findall(r"[A-Z]{3,}", sem_acento(desc).upper()) if p not in PALAVRAS_GENERICAS | CONECTIVOS]
    return " ".join(ps[:2]), (ps[0] if ps else "")


def carregar_wayap():
    w = estado["wayap"]
    produtos = list({p["cod_produto"]: p for p in w.produtos()}.values())
    marcas = w.chamar("/produto", "getMarca")
    carros = w.chamar("/produto", "getCarro")
    stats = defaultdict(Counter)
    fornecedores = Counter()
    for p in produtos:
        marca, (duas, uma) = p["id_marca"], palavras_chave(p["desc_produto"])
        if (p.get("ncm") or "").strip():
            for chave in (("ncm", marca, duas), ("ncm", None, duas), ("ncm", marca, uma), ("ncm", None, uma),
                          ("ncm", marca, None)):
                stats[chave][p["ncm"].strip()] += 1
        stats[("unidade", marca)][p["unidade"]] += 1
        stats[("fornecedor", marca)][p["id_fornecedor"]] += 1
        fornecedores[(p["id_fornecedor"], p.get("razao_social") or str(p["id_fornecedor"]))] += 1
    estado.update(produtos=produtos, marcas=marcas, carros=carros, stats=stats,
                  fornecedores=[{"id": i, "nome": n} for (i, n), _ in fornecedores.most_common(60)])
    indexar_produtos()


def indexar_produtos():
    por_ean, por_codigo, por_num = {}, defaultdict(list), {}
    for p in estado["produtos"]:
        if n_ean(p["cod_barra"]):
            por_ean[n_ean(p["cod_barra"])] = p
        for c in (p["num_fabricante"], p.get("num_fabricante2")):
            if len(n_codigo(c)) >= 3:
                por_codigo[n_codigo(c)].append(p)
        por_num[(p["num_fabricante"] or "").strip().upper()] = p
    estado.update(por_ean=por_ean, por_codigo=por_codigo, por_num=por_num)


def ja_cadastrado(item):
    """Produto do Wayap que já é esta peça: mesmo EAN, ou mesmo código com a marca compatível."""
    if item["ean"] and item["ean"] in estado["por_ean"]:
        return estado["por_ean"][item["ean"]]
    for c in filter(None, item["codigos"].split("|")):
        for p in estado["por_codigo"].get(c, []):
            if marcas_compativeis(n_marca(p["marca"]), n_marca(item["marca"])):
                return p
    return None


def moda(chave):
    c = estado["stats"].get(chave)
    return c.most_common(1)[0][0] if c else None


def achar_marca(nome):
    alvo = n_marca(nome)
    exata = [m for m in estado["marcas"] if n_marca(m["descricao"]) == alvo]
    parecidas = exata or [m for m in estado["marcas"] if marcas_compativeis(n_marca(m["descricao"]), alvo)]
    return parecidas[0] if parecidas else None


def achar_carro(texto):
    """Primeiro veículo da aplicação ('Ford Escort 1981-2003 1.8 ...') -> carro do cadastro ('ESCORT')."""
    carros = {sem_acento(c["descricao"]).upper(): c for c in estado["carros"]}
    primeiro = (texto or "").split(";")[0]
    palavras = [p for p in re.findall(r"[A-Za-z0-9]+", sem_acento(primeiro).upper())][1:]  # sem a montadora
    for n in range(min(3, len(palavras)), 0, -1):
        if " ".join(palavras[:n]) in carros:
            return carros[" ".join(palavras[:n])]
    return carros.get("UNIVERSAL")


def html_produto_karhub(url):
    cache = estado.setdefault("paginas", {})
    if url not in cache:
        cache[url] = ""
        for espera in (3, 10, None):
            try:
                pagina = Fetcher.get(url, stealthy_headers=True, timeout=60)
                if pagina.status == 200:
                    cache[url] = pagina.body.decode("utf-8", "ignore") if isinstance(pagina.body, bytes) else str(pagina.body)
                    break
            except Exception:
                pass
            if espera is None:
                break
            time.sleep(espera)
    return cache[url]


def compatibilidade_karhub(url):
    """Lista 'Veículos Compatíveis' da página (ex.: 'CHEVROLET CELTA 2013 LS 2P 1.0 8V FLEX (77-78 CV)') e as
    montadoras citadas no JSON-LD, para separar montadora de modelo ('LAND ROVER', 'MERCEDES BENZ')."""
    texto = html_produto_karhub(url)
    if 'id="compatible-vehicles"' not in texto:
        return [], []
    bloco = texto[texto.index('id="compatible-vehicles"'):]
    bloco = bloco[:bloco.find("</ul>")]
    linhas = [html_texto.unescape(re.sub(r"<[^>]+>", "", li)).strip() for li in re.findall(r"<li[^>]*>(.*?)</li>", bloco, re.S)]
    montadoras = {sem_acento(m).upper() for m in re.findall(r'"@type":"Brand","name":"([^"]+)"', texto)}
    return [l for l in linhas if l], sorted(montadoras, key=len, reverse=True)


def carro_do_modelo(modelo):
    """'CORSA WAGON' -> carro 'CORSA WAGON' se existir, senão 'CORSA'."""
    carros = {sem_acento(c["descricao"]).upper(): c for c in estado["carros"]}
    palavras = modelo.split()
    for n in range(len(palavras), 0, -1):
        if " ".join(palavras[:n]) in carros:
            return carros[" ".join(palavras[:n])]
    return carros.get(ALIAS_MODELOS.get(modelo, ""))


def ocorrencias_karhub(item):
    """Uma ocorrência por linha de 'Veículos Compatíveis' da página da KarHub (ver agrupar_veiculos)."""
    linhas, montadoras = compatibilidade_karhub(item["url"])
    ocorrencias = []
    for linha in linhas:
        texto = sem_acento(linha).upper()
        montadora = next((m for m in montadoras if texto.startswith(m + " ")), texto.split(" ")[0])
        m = re.match(r"(?P<modelo>.+?)\s+(?P<ano>(?:19|20)\d{2})\b(?P<versao>.*)", texto[len(montadora):].strip())
        if m:
            motor = re.search(r"\b\d\.\d\b", m["versao"])
            ocorrencias.append([f"{montadora} {m['modelo']}", m["modelo"], (int(m["ano"]),) * 2,
                                [motor[0]] if motor else []])
    return ocorrencias, linhas


def agrupar_veiculos(ocorrencias):
    """Um carro do cadastro por modelo compatível, com o complemento no padrão da casa: '1.0 / 1.4 00/12 WAGON'.
    Cada ocorrência é [rótulo no site, modelo sem a montadora, (ano início, ano fim) ou None, motores]."""
    grupos = {}
    for rotulo, modelo, anos, motores in ocorrencias:
        carro = carro_do_modelo(modelo)
        g = grupos.setdefault(carro["id_carro"] if carro else "?" + modelo,
                              {"id_carro": carro["id_carro"] if carro else None, "carro": carro["descricao"] if carro else "",
                               "modelo_origem": rotulo, "anos": None, "motores": set(), "extras": [], "versoes": 0})
        if anos:
            g["anos"] = juntar_anos(g["anos"], anos)
        g["versoes"] += 1
        g["motores"].update(motores)
        nome_carro = sem_acento(carro["descricao"]).upper() if carro else ""
        extra = modelo[len(nome_carro):].strip() if modelo.startswith(nome_carro) else modelo
        if extra and extra not in g["extras"]:
            g["extras"].append(extra)
    veiculos = []
    for g in grupos.values():
        anos = ""
        if g["anos"]:
            inicio, fim = g["anos"]
            anos = (f"{inicio % 100:02d}" if inicio else "") + "/" + (f"{fim % 100:02d}" if fim else "")
        complemento = " ".join(filter(None, [" / ".join(sorted(g["motores"], key=float)), anos, "/".join(g["extras"])]))
        veiculos.append({"id_carro": g["id_carro"], "carro": g["carro"], "modelo_origem": g["modelo_origem"],
                         "complemento": complemento[:1000], "versoes": g["versoes"]})
    return veiculos


def veiculos_sugeridos(item):
    """Veículos da página da KarHub; nos outros sites (ou sem essa lista) os da aplicação escrita no catálogo."""
    ocorrencias, linhas = ocorrencias_karhub(item) if item["site"] == "karhub" else ([], [])
    if not ocorrencias:
        ocorrencias = ocorrencias_do_texto(item["carro"])
        linhas = linhas or [l.strip() for l in (item["carro"] or "").split(";") if l.strip()]
    return agrupar_veiculos(ocorrencias), linhas


def carro_do_titulo(nome):
    """'Bieleta Dianteira Para Chevrolet Captiva E Tracker - Monroe ...' -> carro 'CAPTIVA'."""
    texto = sem_acento(nome.split(" - ")[0]).upper()
    if " PARA " not in texto:
        return None
    palavras = [p for p in texto.split(" PARA ", 1)[1].split() if p not in MONTADORAS_TITULO]
    for i in range(len(palavras)):
        carro = carro_do_modelo(" ".join(palavras[i:i + 3]))
        if carro:
            return carro
    return None


def gravar_complemento_produto(cod_produto, texto):
    """produto.complemento é coluna nova e a API do Wayap ainda não a grava: grava direto no banco."""
    if not texto:
        return None
    if not ENV_ADMIN.exists():
        return f"complemento do produto não gravado: {ENV_ADMIN} não encontrado"
    env = dict(re.findall(r"^(POSTGRES_[A-Z]+)=(.*)$", ENV_ADMIN.read_text(), re.M))
    con = psycopg2.connect(host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"], user=env["POSTGRES_USER"],
                           password=env["POSTGRES_PASSWORD"], dbname=estado["wayap"].sociedade, connect_timeout=15)
    try:
        with con, con.cursor() as cur:
            cur.execute("UPDATE produto SET complemento = %s WHERE cod_produto = %s", (texto, cod_produto))
    finally:
        con.close()
    return None


def sugestao(item):
    site = nome_site(item["site"])
    nome = item["nome"] or ""
    base = nome.split(" - ")[0]  # "Jogo Cabo De Vela - Gauss - Gc5045": tira marca e código do fim
    desc = " ".join(p for p in sem_acento(base).upper().split() if p not in CONECTIVOS)
    if len(desc) > TAMANHO_DESCRICAO:
        desc = desc[:TAMANHO_DESCRICAO].rsplit(" ", 1)[0]
    marca = achar_marca(item["marca"])
    id_marca = marca["id_marca"] if marca else None
    duas, uma = palavras_chave(desc)
    veiculos, linhas = veiculos_sugeridos(item)
    ids = [v["id_carro"] for v in veiculos if v["id_carro"]]
    titulo = carro_do_titulo(item["nome"] or "")
    # carro principal: o citado no título; senão o primeiro dos veículos compatíveis; senão o da aplicação
    if titulo and (titulo["id_carro"] in ids or not ids):
        carro = titulo
    elif ids:
        carro = next(c for c in estado["carros"] if c["id_carro"] == ids[0])
    else:
        carro = achar_carro(item["carro"])
    num = (item["codigo"] or "").replace(" / ", "/").strip()
    avisos = []
    if not num:
        avisos.append(f"{site} não informa o código do fabricante desta peça: preencha o Nº fabricante.")
    if len(num) > LIMITES["num_fabricante"]:
        avisos.append(f"O código '{num}' passa de 15 caracteres: ajuste antes de cadastrar.")
    existente = estado["por_num"].get(num.upper())
    if existente:
        avisos.append(f"O Nº fabricante '{num}' já existe no produto {existente['cod_produto']} "
                      f"({existente['desc_produto']} - {existente['marca']}); o Wayap não aceita repetido.")
    if not item["marca"]:
        avisos.append(f"{site} não informa a marca desta peça: escolha a marca.")
    elif not marca:
        avisos.append(f"A marca '{item['marca']}' não existe no cadastro: será criada.")
    if not linhas:
        avisos.append(f"{site} não informa veículos compatíveis para esta peça: confira o carro principal.")
    elif any(v["id_carro"] is None for v in veiculos):
        avisos.append(f"Alguns modelos citados em {site} não existem no cadastro de carros: escolha o carro ou desmarque.")
    return {
        "desc_produto": desc,
        "desc_produto_completa": nome[:400],
        "num_fabricante": num,
        "cod_barra": item["ean"] or "",
        "id_marca": id_marca if id_marca is not None else "nova",
        "marca_nova": "" if marca else sem_acento(item["marca"] or "").upper(),
        "id_carro": carro["id_carro"] if carro else None,
        "id_fornecedor": moda(("fornecedor", id_marca)) or 1,
        "ncm": next((n for n in map(moda, [("ncm", id_marca, duas), ("ncm", None, duas), ("ncm", id_marca, uma),
                                           ("ncm", None, uma), ("ncm", id_marca, None)]) if n), ""),
        "unidade": UNIDADE_PELA_PALAVRA.get(desc.split(" ")[0] if desc else "") or moda(("unidade", id_marca)) or "PC",
        "avisos": avisos,
        "veiculos": veiculos,
        "complemento_produto": "\n".join(linhas),
    }


# ---------- lotes de fotos (curadoria) ----------

def lotes():
    return sorted(str(p.parent) for p in Path(".").glob(f"fotos_wayap_{estado['wayap'].sociedade}*/plano.json"))


def arquivo_lote(nome):
    if nome not in lotes():
        abort(404)
    return Path(nome) / "plano.json"


def ler_lote(nome):
    return json.loads(arquivo_lote(nome).read_text(encoding="utf-8"))


def localizar_no_wayap(cod_produto, foto):
    """Nome atual da foto no Wayap, achado pelo conteúdo: apagar uma foto renumera as seguintes."""
    alvo = dhash(abrir_rgb(foto["preparada"]))
    w = estado["wayap"]
    for nome in w.fotos(cod_produto):
        for espera in (3, 10, None):
            try:
                r = requests.get(w.url_fotos + nome, timeout=60)
                if r.status_code == 200:
                    if distancia(dhash(abrir_rgb(r.content)), alvo) <= DISTANCIA_DUPLICADA:
                        return nome
                    break
            except requests.RequestException:
                pass
            if espera is None:
                raise RuntimeError(f"não consegui baixar {nome} do Wayap para conferir")
            time.sleep(espera)
    return None


def enviar_fotos_catalogo(item, cod_produto, campos, urls):
    """Baixa, filtra (tamanho mínimo e duplicadas) e sobe até 5 fotos; registra no lote da curadoria."""
    saida = Path(f"fotos_wayap_{estado['wayap'].sociedade}_cadastro")
    casamento = f"cadastro {item['site']}"
    escolhidas, hashes = [], []
    for url in urls:
        try:
            r = requests.get(url, timeout=60)
            im = abrir_rgb(r.content) if r.status_code == 200 else None
        except Exception:
            im = None
        if im is None or min(im.size) < MENOR_LADO:
            continue
        h = dhash(im)
        if any(distancia(h, x) <= DISTANCIA_DUPLICADA for x in hashes):
            continue
        hashes.append(h)
        destino = saida / "enviar" / str(cod_produto) / f"{len(escolhidas) + 1}.jpg"
        destino.parent.mkdir(parents=True, exist_ok=True)
        largura, altura = im.size
        im.thumbnail((LADO_ENVIO, LADO_ENVIO))
        im.save(destino, "JPEG", quality=92)
        escolhidas.append({"origem": url, "fonte": item["site"], "pasta": "", "url_origem": item["url"],
                           "principal": not escolhidas, "w": largura, "h": altura, "casamento": casamento,
                           "status": "pendente", "nome_wayap": None, "preparada": str(destino)})
        if len(escolhidas) == MAX_FOTOS:
            break
    for f in escolhidas:
        r = estado["wayap"].enviar_foto(cod_produto, f["preparada"])
        if isinstance(r, dict) and r.get("img"):
            f.update(status="enviado", nome_wayap=r["img"], enviado_em=time.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            f["status"] = "erro"
    plano = json.loads((saida / "plano.json").read_text(encoding="utf-8")) if (saida / "plano.json").exists() else []
    marca = next((m["descricao"] for m in estado["marcas"] if m["id_marca"] == campos["id_marca"]), item["marca"])
    carro = next((c["descricao"] for c in estado["carros"] if c["id_carro"] == campos["id_carro"]), "")
    plano.append({"cod_produto": cod_produto, "desc_produto": campos["desc_produto"], "marca": marca, "carro": carro,
                  "num_fabricante": campos["num_fabricante"], "cod_barra": campos["cod_barra"],
                  "fotos_existentes": 0, "casamento": [casamento], "fotos": escolhidas})
    gravar_plano(plano, saida)
    return sum(f["status"] == "enviado" for f in escolhidas)


# ---------- rotas ----------

@app.get("/")
def pagina_curadoria():
    return (CABECALHO + CURADORIA).replace("__SOCIEDADE__", estado["wayap"].sociedade).replace("__ABA1__", "ativa") \
        .replace("__ABA2__", "")


@app.get("/cadastro")
def pagina_cadastro():
    return (CABECALHO + CADASTRO).replace("__SOCIEDADE__", estado["wayap"].sociedade).replace("__ABA1__", "") \
        .replace("__ABA2__", "ativa")


@app.get("/karhub")
def pagina_karhub():  # endereço antigo da aba, de quando só havia a KarHub
    return redirect("/cadastro")


@app.get("/api/lotes")
def api_lotes():
    return jsonify(lotes())


@app.get("/api/itens")
def api_itens():
    lote = request.args["lote"]
    with trava:
        plano = ler_lote(lote)
    lista = []
    for p in plano:
        for n, f in enumerate(p["fotos"]):
            if f["status"] == "enviado" and not f.get("curadoria"):
                lista.append({"id": f"{p['cod_produto']}:{n}", "cod_produto": p["cod_produto"],
                              "desc_produto": p["desc_produto"], "carro": p.get("carro") or "",
                              "marca": p["marca"], "num_fabricante": p["num_fabricante"],
                              "cod_barra": p["cod_barra"] or "", "fonte": f["fonte"],
                              "url_origem": f.get("url_origem") or "", "casamento": f.get("casamento", ""),
                              "resolucao": f"{f['w']}x{f['h']}"})
    return jsonify(lista)


@app.get("/foto/<path:lote>/<int:cod>/<int:n>")
def foto(lote, cod, n):
    with trava:
        plano = ler_lote(lote)
    for p in plano:
        if p["cod_produto"] == cod and n < len(p["fotos"]):
            return send_file(Path(p["fotos"][n]["preparada"]).resolve(), mimetype="image/jpeg")
    abort(404)


@app.post("/api/decidir")
def api_decidir():
    lote, decisao = request.json["lote"], request.json["decisao"]
    cod, n = (int(x) for x in request.json["id"].split(":"))
    if decisao not in ("certa", "errada"):
        abort(400)
    with trava:
        plano = ler_lote(lote)
        p = next((p for p in plano if p["cod_produto"] == cod), None)
        if not p or n >= len(p["fotos"]) or p["fotos"][n]["status"] != "enviado":
            return jsonify({"erro": "foto não encontrada no lote"}), 404
        f = p["fotos"][n]
        if decisao == "errada":
            try:
                nome = localizar_no_wayap(cod, f)
            except RuntimeError as e:
                return jsonify({"erro": f"{e}; tente de novo"}), 502
            if not nome:
                return jsonify({"erro": "não achei esta foto no produto do Wayap (já foi apagada ou trocada?)"}), 404
            r = estado["wayap"].apagar_foto(cod, nome)
            if not (isinstance(r, dict) and r.get("retorno") in ("ok", "semFoto")):
                return jsonify({"erro": f"o Wayap não apagou: {r}"}), 502
            f["status"], f["nome_wayap"] = "apagado_curadoria", None
            for outra in p["fotos"]:  # as seguintes foram renumeradas pelo Wayap
                if outra["status"] == "enviado" and outra["nome_wayap"]:
                    try:
                        outra["nome_wayap"] = localizar_no_wayap(cod, outra) or outra["nome_wayap"]
                    except RuntimeError:
                        pass  # o nome é só referência; a curadoria sempre localiza pelo conteúdo
        f["curadoria"] = decisao
        gravar_plano(plano, arquivo_lote(lote).parent)
    return jsonify({"ok": True})


@app.get("/img")
def imagem_catalogo():
    """Miniaturas dos sites servidas por aqui (cache em disco): o navegador não depende do CDN deles."""
    url, largura = request.args.get("u", ""), request.args.get("w", "300")
    host = urlsplit(url).hostname
    if not url.startswith("https://") or host not in estado["hosts"] or not largura.isdigit() \
            or not 0 < int(largura) <= 2000:
        abort(400)
    arq = CACHE_IMAGENS / (hashlib.md5(f"{url}|{largura}".encode()).hexdigest() + ".img")
    if not arq.exists():
        shopify = host == "cdn.shopify.com"  # a Shopify (KarHub) já entrega reduzida; os outros CDNs, o original
        r = requests.get(url + ("&" if "?" in url else "?") + f"width={largura}" if shopify else url, timeout=30)
        if r.status_code != 200:
            abort(502)
        conteudo = r.content
        if not shopify:
            try:
                im = abrir_rgb(conteudo)
            except Exception:
                abort(502)
            im.thumbnail((int(largura), int(largura)))
            saida = BytesIO()
            im.save(saida, "JPEG", quality=88)
            conteudo = saida.getvalue()
        CACHE_IMAGENS.mkdir(parents=True, exist_ok=True)
        arq.write_bytes(conteudo)
    return Response(arq.read_bytes(), mimetype="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/catalogo/sites")
def api_sites():
    return jsonify([{"site": s["site"], "nome": nome_site(s["site"]), "itens": s["itens"]} for s in sites_indexados()])


@app.get("/api/catalogo/busca")
def api_busca():
    lista = []
    achados, tem_mais = buscar_catalogos(request.args.get("q", ""), request.args.get("site", ""),
                                         offset=int(request.args.get("offset", 0)))
    for r in achados:
        existente = ja_cadastrado(r)
        imagens = json.loads(r["imagens"])
        lista.append({"id": r["id"], "site": r["site"], "site_nome": nome_site(r["site"]), "nome": r["nome"],
                      "marca": r["marca"], "codigo": r["codigo"], "ean": r["ean"], "carro": r["carro"], "url": r["url"],
                      "imagens": imagens,
                      "existente": {"cod_produto": existente["cod_produto"], "desc_produto": existente["desc_produto"]}
                      if existente else None})
    return jsonify({"itens": lista, "tem_mais": tem_mais})


@app.get("/api/catalogo/sugestao/<int:id_item>")
def api_sugestao(id_item):
    item = item_do_catalogo(id_item)
    return jsonify({"campos": sugestao(item), "marcas": estado["marcas"], "carros": estado["carros"],
                    "fornecedores": estado["fornecedores"], "imagens": json.loads(item["imagens"])})


@app.post("/api/catalogo/cadastrar")
def api_cadastrar():
    dados = request.json
    item = item_do_catalogo(int(dados["id"]))
    c = {k: (str(v).strip() if isinstance(v, str) else v) for k, v in dados["campos"].items()}
    c["desc_produto"] = c["desc_produto"].upper()
    for campo, limite in LIMITES.items():
        if len(str(c.get(campo) or "")) > limite:
            return jsonify({"erro": f"{campo} passa de {limite} caracteres"}), 400
    for campo in ("desc_produto", "num_fabricante", "unidade", "id_carro", "id_fornecedor"):
        if not c.get(campo):
            return jsonify({"erro": f"{campo} é obrigatório"}), 400
    with trava:
        w = estado["wayap"]
        if c["id_marca"] == "nova":
            descricao = (c.get("marca_nova") or "").upper()
            if not descricao:
                return jsonify({"erro": "informe o nome da marca nova"}), 400
            r = w.chamar("/marcas", "insert", param={"descricao": descricao}, idMarcaGrupo=1)
            if not (isinstance(r, list) and r and r[0].get("id_marca")):
                return jsonify({"erro": f"o Wayap não criou a marca: {r}"}), 502
            c["id_marca"] = r[0]["id_marca"]
            estado["marcas"].append({"id_marca": c["id_marca"], "descricao": descricao})
        param = {"num_fabricante": c["num_fabricante"], "desc_produto": c["desc_produto"],
                 "desc_produto_completa": c.get("desc_produto_completa") or None, "cod_barra": c.get("cod_barra") or None,
                 "unidade": c["unidade"].upper(), "ncm": c.get("ncm") or None, "id_marca": int(c["id_marca"]),
                 "id_carro": int(c["id_carro"]), "id_fornecedor": int(c["id_fornecedor"]), "custo": 0, "venda": 0,
                 "cadastrante": item["site"].upper()}
        r = w.chamar("/produto", "insertProduto", param=param)
        if not (isinstance(r, dict) and r.get("cod_produto")):
            return jsonify({"erro": (r or {}).get("msg") if isinstance(r, dict) else str(r)}), 400
        cod = r["cod_produto"]
        c["id_marca"], c["id_carro"] = int(c["id_marca"]), int(c["id_carro"])
        avisos = []
        nomes_carros = {x["id_carro"]: x["descricao"] for x in estado["carros"]}
        vistos = set()
        for v in dados.get("veiculos") or []:
            if not v.get("incluir") or not v.get("id_carro") or int(v["id_carro"]) in vistos:
                continue
            id_carro, complemento = int(v["id_carro"]), (v.get("complemento") or "").strip()[:1000]
            vistos.add(id_carro)
            if id_carro == c["id_carro"]:  # o insertProduto já criou o carro principal, sem complemento
                r = w.chamar("/produto", "updateCarroVenda", param={
                    "cod_produto": cod, "id_carroOld": id_carro, "id_carroNew": id_carro, "complemento": complemento,
                    "informativo": "", "nomeCarro": nomes_carros.get(id_carro), "campoOld": "", "campoNew": complemento})
            else:
                r = w.chamar("/produto", "insertCarroVenda", param={
                    "cod_produto": cod, "id_carro": id_carro, "complemento": complemento, "informativo": "",
                    "nomeCarro": nomes_carros.get(id_carro)})
            if not (isinstance(r, dict) and r.get("ok")):
                avisos.append(f"carro {nomes_carros.get(id_carro)}: {r}")
        try:
            erro = gravar_complemento_produto(cod, (c.get("complemento_produto") or "").strip())
        except Exception as e:
            erro = f"complemento do produto não gravado: {e}"
        if erro:
            avisos.append(erro)
        enviadas = enviar_fotos_catalogo(item, cod, c, dados.get("fotos") or [])
        marca = next((m["descricao"] for m in estado["marcas"] if m["id_marca"] == c["id_marca"]), "")
        estado["produtos"].append({"cod_produto": cod, "desc_produto": c["desc_produto"], "marca": marca,
                                   "num_fabricante": c["num_fabricante"], "num_fabricante2": "",
                                   "cod_barra": c.get("cod_barra") or ""})
        indexar_produtos()
    return jsonify({"cod_produto": cod, "fotos": enviadas, "carros": len(vistos), "avisos": avisos})


# ---------- páginas ----------

CABECALHO = r"""<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel Wayap</title>
<style>
:root {
  --bg: #f4f5f7; --card: #ffffff; --text: #1d2330; --muted: #5d6677; --line: #e1e4ea;
  --ok: #1f8a4c; --ok-bg: #e6f4ec; --bad: #c0392b; --bad-bg: #fbeae8; --accent: #2b59c3; --accent-bg: #e8eefb;
  --warn: #9a6700; --warn-bg: #fff4d6;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #14171c; --card: #1d2128; --text: #e7e9ee; --muted: #9aa3b2; --line: #2c323c;
          --ok: #4cc27f; --ok-bg: #173325; --bad: #ff7b6b; --bad-bg: #3a1c19; --accent: #7fa4ff; --accent-bg: #1c2740;
          --warn: #f2c14e; --warn-bg: #3a2f12; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { position: sticky; top: 0; z-index: 5; background: var(--card); border-bottom: 1px solid var(--line);
         padding: 10px 20px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }
header h1 { font-size: 17px; margin: 0; }
nav a { text-decoration: none; color: var(--muted); padding: 6px 12px; border-radius: 6px; font-weight: 600; }
nav a.ativa { background: var(--accent-bg); color: var(--accent); }
header select, header input, .form input, .form select, .form textarea {
  font: inherit; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--text); }
.contador { color: var(--muted); } .contador b { color: var(--text); }
.dica { color: var(--muted); font-size: 13px; margin-left: auto; }
main { max-width: 1100px; margin: 16px auto; padding: 0 16px; }
.linha { display: grid; grid-template-columns: 170px 1fr auto; gap: 18px; align-items: center; background: var(--card);
         border: 1px solid var(--line); border-radius: 10px; padding: 12px; margin-bottom: 10px; transition: opacity .25s, transform .25s; }
.linha.ativa { outline: 2px solid var(--accent); }
.linha.saindo { opacity: 0; transform: translateX(30px); }
.linha img, .foto { width: 170px; height: 170px; object-fit: contain; background: #fff; border-radius: 8px; cursor: zoom-in;
                    border: 1px solid var(--line); }
.desc { font-weight: 600; font-size: 16px; margin-bottom: 6px; }
.campos { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 3px 18px; font-size: 14px; }
.campos span { color: var(--muted); }
.origem { margin-top: 6px; font-size: 13px; color: var(--muted); }
.origem a { color: var(--accent); }
.botoes { display: flex; flex-direction: column; gap: 8px; min-width: 150px; }
button { font: inherit; font-weight: 600; padding: 10px 14px; border-radius: 8px; border: 1px solid; cursor: pointer; }
button:disabled { opacity: .5; cursor: wait; }
.certa { color: var(--ok); background: var(--ok-bg); border-color: var(--ok); }
.errada { color: var(--bad); background: var(--bad-bg); border-color: var(--bad); }
.primario { color: #fff; background: var(--accent); border-color: var(--accent); }
.secundario { color: var(--text); background: transparent; border-color: var(--line); }
.selo { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 99px; }
.selo.existe { background: var(--ok-bg); color: var(--ok); }
.selo.site { background: var(--accent-bg); color: var(--accent); vertical-align: 2px; }
.vazio { text-align: center; color: var(--muted); padding: 60px 0; }
#zoom { position: fixed; inset: 0; background: rgba(0,0,0,.8); display: none; align-items: center; justify-content: center; z-index: 20; cursor: zoom-out; }
#zoom img { max-width: 92vw; max-height: 92vh; background: #fff; border-radius: 8px; }
#aviso { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); color: #fff; padding: 10px 16px;
         border-radius: 8px; display: none; z-index: 21; max-width: 90vw; }
.modal { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: none; align-items: flex-start; justify-content: center;
         z-index: 15; overflow-y: auto; padding: 30px 12px; }
.form { background: var(--card); border-radius: 12px; padding: 20px; width: min(860px, 100%); }
.form h2 { margin: 0 0 4px; font-size: 18px; }
.grade { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px; margin: 14px 0; }
.grade label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
.grade .largo { grid-column: 1 / -1; }
.avisos { background: var(--warn-bg); color: var(--warn); border-radius: 8px; padding: 10px 12px; font-size: 14px; }
.fotos { display: flex; gap: 10px; flex-wrap: wrap; margin: 8px 0 16px; }
.fotos label { position: relative; } .fotos input { position: absolute; top: 6px; left: 6px; width: 18px; height: 18px; }
.fotos img { width: 120px; height: 120px; object-fit: contain; background: #fff; border-radius: 8px; border: 2px solid var(--line); }
.fotos input:checked + img { border-color: var(--accent); }
.acoes { display: flex; gap: 10px; justify-content: flex-end; }
.veiculo { display: grid; grid-template-columns: 22px 190px 1fr auto; gap: 8px; align-items: center; margin-bottom: 6px; }
.veiculo select, .veiculo input[type=text] { font: inherit; padding: 5px 8px; border: 1px solid var(--line); border-radius: 6px;
                                             background: var(--bg); color: var(--text); min-width: 0; }
.veiculo .origem { margin: 0; white-space: nowrap; }
@media (max-width: 700px) {
  .linha { grid-template-columns: 1fr; } .linha img, .foto { width: 100%; height: 260px; }
  .botoes { flex-direction: row; } .botoes button { flex: 1; }
  .dica { display: none; } .grade { grid-template-columns: 1fr; }
  .veiculo { grid-template-columns: 22px 1fr; } .veiculo input[type=text], .veiculo .origem { grid-column: 2; }
}
</style>
</head>
<body>
<header>
  <h1>Wayap · __SOCIEDADE__</h1>
  <nav><a href="/" class="__ABA1__">Curadoria de fotos</a><a href="/cadastro" class="__ABA2__">Cadastrar dos sites</a></nav>
"""

CURADORIA = r"""
  <select id="lote" title="Lote de fotos"></select>
  <div class="contador"><b id="pendentes">…</b> para revisar · <span id="feitas">0</span> revisadas agora</div>
  <select id="filtroFonte"><option value="">Todos os sites</option></select>
  <input id="busca" placeholder="Buscar descrição, marca, código…" size="24">
  <div class="dica">Atalhos: <b>C</b> certa · <b>E</b> errada · <b>↑↓</b> navegar</div>
</header>
<main id="lista"></main>
<div id="zoom"><img alt=""></div>
<div id="aviso"></div>
<script>
const POR_PAGINA = 40;
let itens = [], filtrados = [], mostrados = 0, ativa = 0, feitas = 0;
const processando = new Set();
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const loteAtual = () => document.getElementById("lote").value;
const lista = document.getElementById("lista");
const linhas = () => [...lista.querySelectorAll(".linha")];

function avisar(texto) {
  const a = document.getElementById("aviso"); a.style.background = "var(--bad)"; a.textContent = texto;
  a.style.display = "block"; setTimeout(() => a.style.display = "none", 5000);
}

async function iniciar() {
  const lotes = await (await fetch("/api/lotes")).json();
  const sel = document.getElementById("lote");
  sel.innerHTML = lotes.map(l => `<option>${esc(l)}</option>`).join("");
  let salvo = null;
  try { salvo = localStorage.getItem("lote"); } catch (e) {}
  if (lotes.includes(salvo)) sel.value = salvo;
  else if (lotes.length) sel.value = lotes[lotes.length - 1];
  carregar();
}

async function carregar() {
  try { localStorage.setItem("lote", loteAtual()); } catch (e) {}
  lista.innerHTML = '<div class="vazio">Carregando…</div>';
  itens = loteAtual() ? await (await fetch("/api/itens?lote=" + encodeURIComponent(loteAtual()))).json() : [];
  const fontes = [...new Set(itens.map(i => i.fonte))].sort();
  document.getElementById("filtroFonte").innerHTML = '<option value="">Todos os sites</option>' +
    fontes.map(f => `<option>${esc(f)}</option>`).join("");
  desenhar();
}

function filtrar() {
  const fonte = document.getElementById("filtroFonte").value;
  const termo = document.getElementById("busca").value.trim().toUpperCase();
  return itens.filter(i => (!fonte || i.fonte === fonte) &&
    (!termo || `${i.desc_produto} ${i.marca} ${i.num_fabricante} ${i.cod_barra} ${i.carro} ${i.cod_produto}`.toUpperCase().includes(termo)));
}

function linhaHtml(i) {
  return `
    <div class="linha" data-id="${esc(i.id)}">
      <img loading="lazy" src="/foto/${encodeURIComponent(loteAtual())}/${i.id.replace(":", "/")}" alt="Foto enviada para ${esc(i.desc_produto)}">
      <div>
        <div class="desc">${esc(i.desc_produto)}</div>
        <div class="campos">
          <div><span>Carro:</span> ${esc(i.carro) || "—"}</div>
          <div><span>Marca:</span> ${esc(i.marca)}</div>
          <div><span>Nº fabricante:</span> ${esc(i.num_fabricante)}</div>
          <div><span>Cód. barras:</span> ${esc(i.cod_barra) || "—"}</div>
        </div>
        <div class="origem">Produto ${i.cod_produto} · foto de <b>${esc(i.fonte)}</b> (${esc(i.casamento)}, ${esc(i.resolucao)})
          ${i.url_origem ? `· <a href="${esc(i.url_origem)}" target="_blank" rel="noopener">ver no site</a>` : ""}</div>
      </div>
      <div class="botoes">
        <button class="certa" data-decisao="certa">✓ Foto certa</button>
        <button class="errada" data-decisao="errada">✗ Foto errada</button>
      </div>
    </div>`;
}

function atualizarContador() {
  document.getElementById("pendentes").textContent = filtrados.length;
}

function marcarAtiva() {
  linhas().forEach((l, k) => l.classList.toggle("ativa", k === ativa));
}

// recomeça a lista: troca de lote, de filtro ou de busca
function desenhar() {
  filtrados = filtrar(); mostrados = 0; ativa = 0;
  atualizarContador();
  if (!filtrados.length) { lista.innerHTML = '<div class="vazio">Nada para revisar aqui.</div>'; return; }
  lista.innerHTML = '<div id="fim" class="vazio">Carregando mais…</div>';
  mostrarMais();
}

// acrescenta o próximo bloco no fim da lista, sem mexer no que já está na tela
function mostrarMais() {
  const fim = document.getElementById("fim");
  if (!fim) return;
  const bloco = filtrados.slice(mostrados, mostrados + POR_PAGINA);
  fim.insertAdjacentHTML("beforebegin", bloco.map(linhaHtml).join(""));
  mostrados += bloco.length;
  fim.style.display = mostrados < filtrados.length ? "" : "none";
  marcarAtiva();
  // observar de novo: se o fim ainda estiver visível (tela alta), o observador dispara outra vez
  observador.unobserve(fim); observador.observe(fim);
}

const observador = new IntersectionObserver(entradas => {
  if (entradas[0].isIntersecting && mostrados < filtrados.length) mostrarMais();
}, {rootMargin: "800px"});

async function decidir(id, decisao) {
  if (processando.has(id)) return;
  const linha = lista.querySelector(`.linha[data-id="${id}"]`);
  if (!linha) return;
  processando.add(id);
  linha.querySelectorAll("button").forEach(b => b.disabled = true);
  try {
    const r = await fetch("/api/decidir", {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify({lote: loteAtual(), id, decisao})});
    if (!r.ok) {
      avisar((await r.json()).erro || "Erro ao salvar");
      linha.querySelectorAll("button").forEach(b => b.disabled = false);
      return;
    }
  } finally {
    processando.delete(id);
  }
  feitas++; document.getElementById("feitas").textContent = feitas;
  itens = itens.filter(i => i.id !== id);
  filtrados = filtrados.filter(i => i.id !== id);
  mostrados--;
  atualizarContador();
  linha.classList.add("saindo");
  setTimeout(() => {
    linha.remove();
    if (!filtrados.length) { lista.innerHTML = '<div class="vazio">Nada para revisar aqui.</div>'; return; }
    ativa = Math.max(0, Math.min(ativa, linhas().length - 1));
    marcarAtiva();
    const fim = document.getElementById("fim");
    if (fim) { observador.unobserve(fim); observador.observe(fim); }
  }, 250);
}

lista.addEventListener("click", e => {
  const botao = e.target.closest("button[data-decisao]");
  const linha = e.target.closest(".linha");
  if (!linha) return;
  if (botao) { decidir(linha.dataset.id, botao.dataset.decisao); return; }
  if (e.target.tagName === "IMG") {
    const z = document.getElementById("zoom"); z.querySelector("img").src = e.target.src; z.style.display = "flex";
  }
  if (e.target.tagName !== "A") { ativa = linhas().indexOf(linha); marcarAtiva(); }
});
document.getElementById("zoom").onclick = e => e.currentTarget.style.display = "none";
document.getElementById("lote").onchange = carregar;
document.getElementById("filtroFonte").onchange = desenhar;
document.getElementById("busca").oninput = desenhar;
document.addEventListener("keydown", e => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (e.key === "Escape") { document.getElementById("zoom").style.display = "none"; return; }
  const atual = linhas()[ativa];
  if (!atual) return;
  const k = e.key.toLowerCase();
  if (k === "c") decidir(atual.dataset.id, "certa");
  else if (k === "e") decidir(atual.dataset.id, "errada");
  else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    if (e.key === "ArrowDown" && ativa >= linhas().length - 1 && mostrados < filtrados.length) mostrarMais();
    ativa = Math.max(0, Math.min(linhas().length - 1, ativa + (e.key === "ArrowDown" ? 1 : -1)));
    marcarAtiva();
    linhas()[ativa].scrollIntoView({block: "center"});
  }
});
iniciar();
</script>
</body>
</html>
"""

CADASTRO = r"""
  <form id="formBusca" style="display:flex; gap:8px; flex:1; min-width:260px; flex-wrap:wrap">
    <select id="site" title="Site do catálogo"><option value="">Todos os sites</option></select>
    <input id="q" placeholder="Código do fabricante, EAN ou descrição (ex.: GC5045, bieleta captiva)" style="flex:1; min-width:180px" autofocus>
    <button class="primario" type="submit">Buscar</button>
  </form>
</header>
<main id="resultados"><div class="vazio">Busque uma peça nos catálogos dos sites para cadastrar no Wayap.</div></main>
<div class="modal" id="modal">
  <form class="form" id="formCadastro">
    <h2 id="tituloForm"></h2>
    <div class="origem" id="origemForm"></div>
    <div class="grade">
      <label class="largo">Descrição (até 100)<input name="desc_produto" maxlength="100" required></label>
      <label class="largo">Descrição completa (até 400)<textarea name="desc_produto_completa" maxlength="400" rows="3"></textarea></label>
      <label>Nº fabricante (até 15)<input name="num_fabricante" maxlength="15" required></label>
      <label>Cód. barras (EAN)<input name="cod_barra" maxlength="13"></label>
      <label>Marca<select name="id_marca" required></select></label>
      <label>Nome da marca nova<input name="marca_nova" maxlength="60"></label>
      <label>Carro principal<select name="id_carro" required></select></label>
      <label>Fornecedor<select name="id_fornecedor" required></select></label>
      <label>NCM<input name="ncm" maxlength="8" pattern="\d{8}" title="8 dígitos"></label>
      <label>Unidade<select name="unidade"><option>PC</option><option>UN</option><option>JG</option><option>KT</option><option>PA</option><option>CX</option><option>LT</option><option>MT</option></select></label>
      <label>Custo<input value="0,00" disabled></label>
      <label>Venda<input value="0,00" disabled></label>
    </div>
    <p style="margin:6px 0 6px;font-weight:600">Veículos compatíveis (<span id="siteVeiculos"></span>) →
      carros de venda com complemento <span class="origem" id="resumoVeiculos"></span></p>
    <div id="veiculosForm"></div>
    <div class="grade" style="margin-top:8px">
      <label class="largo">Complemento do produto (lista completa de veículos compatíveis)
        <textarea name="complemento_produto" rows="4"></textarea></label>
    </div>
    <div class="avisos" id="avisos" hidden></div>
    <p style="margin:14px 0 4px;font-weight:600">Fotos para subir (até 5)</p>
    <div class="fotos" id="fotosForm"></div>
    <div class="acoes">
      <button type="button" class="secundario" onclick="fechar()">Cancelar</button>
      <button type="submit" class="primario" id="btnCadastrar">Cadastrar no Wayap</button>
    </div>
  </form>
</div>
<div id="zoom"><img alt=""></div>
<div id="aviso"></div>
<script>
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const miniatura = (url, w = 300) => "/img?w=" + w + "&u=" + encodeURIComponent(url);
const POR_PAGINA = 40;
let resultados = [], itemAtual = null, consulta = "", siteBusca = "", offset = 0;
const main = document.getElementById("resultados");
const seletorSite = document.getElementById("site");

function avisar(texto, ok) {
  const a = document.getElementById("aviso"); a.style.background = ok ? "var(--ok)" : "var(--bad)"; a.textContent = texto;
  a.style.display = "block"; setTimeout(() => a.style.display = "none", 6000);
}

async function carregarSites() {
  const sites = await (await fetch("/api/catalogo/sites")).json();
  seletorSite.innerHTML = '<option value="">Todos os sites</option>' + sites.map(s =>
    `<option value="${esc(s.site)}">${esc(s.nome)} (${s.itens.toLocaleString("pt-BR")})</option>`).join("");
  let salvo = null;
  try { salvo = localStorage.getItem("site"); } catch (e) {}
  if (sites.some(s => s.site === salvo)) seletorSite.value = salvo;
}
seletorSite.onchange = () => {
  try { localStorage.setItem("site", seletorSite.value); } catch (e) {}
  if (document.getElementById("q").value.trim()) document.getElementById("formBusca").requestSubmit();
};

document.getElementById("formBusca").onsubmit = async e => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim(); if (!q) return;
  consulta = q; siteBusca = seletorSite.value; offset = 0; resultados = [];
  main.innerHTML = '<div class="vazio">Buscando…</div>';
  await buscarMais();
};

async function buscarMais() {
  const botao = document.getElementById("maisProdutos");
  if (botao) { botao.disabled = true; botao.textContent = "Carregando…"; }
  const d = await (await fetch(`/api/catalogo/busca?q=${encodeURIComponent(consulta)}&site=${encodeURIComponent(siteBusca)}&offset=${offset}`)).json();
  offset += POR_PAGINA;
  const ids = new Set(resultados.map(r => r.id));
  const novos = d.itens.filter(r => !ids.has(r.id));
  resultados.push(...novos);
  if (!resultados.length) {
    const onde = siteBusca ? "no catálogo " + (seletorSite.selectedOptions[0]?.text.replace(/ \(.*/, "") || siteBusca) : "nos catálogos";
    main.innerHTML = `<div class="vazio">Nada encontrado ${esc(onde)}.</div>`; return;
  }
  if (!document.getElementById("rodape"))
    main.innerHTML = '<div id="rodape" style="text-align:center;margin:18px 0 40px"></div>';
  document.getElementById("rodape").insertAdjacentHTML("beforebegin", novos.map(linhaHtml).join(""));
  document.getElementById("rodape").innerHTML = d.tem_mais
    ? `<button class="secundario" id="maisProdutos" onclick="buscarMais()">Mais produtos</button>
       <div class="origem" style="margin-top:6px">${resultados.length} mostrados</div>`
    : `<div class="origem">${resultados.length} resultado(s) · fim da lista</div>`;
}

function linhaHtml(r) {
  return `
    <div class="linha" data-id="${r.id}">
      ${r.imagens.length ? `<img class="foto" loading="lazy" src="${esc(miniatura(r.imagens[0]))}" data-grande="${esc(miniatura(r.imagens[0], 1000))}" alt="${esc(r.nome)}">` : '<div class="foto"></div>'}
      <div>
        <div class="desc"><span class="selo site">${esc(r.site_nome)}</span> ${esc(r.nome)}</div>
        <div class="campos">
          <div><span>Marca:</span> ${esc(r.marca) || "—"}</div>
          <div><span>Código:</span> ${esc(r.codigo) || "—"}</div>
          <div><span>EAN:</span> ${esc(r.ean) || "—"}</div>
          <div><span>Fotos:</span> ${r.imagens.length}</div>
        </div>
        <div class="origem">${esc((r.carro || "").slice(0, 220))}${(r.carro || "").length > 220 ? "…" : ""}
          · <a href="${esc(r.url)}" target="_blank" rel="noopener">ver no site</a></div>
      </div>
      <div class="botoes">
        ${r.existente ? `<span class="selo existe">Já cadastrado: ${r.existente.cod_produto}</span>
                         <div class="origem">${esc(r.existente.desc_produto)}</div>`
                      : `<button class="primario" onclick="abrir(${r.id})">Cadastrar</button>`}
      </div>
    </div>`;
}

main.addEventListener("click", e => {
  if (e.target.matches("img.foto")) {
    const z = document.getElementById("zoom"); z.querySelector("img").src = e.target.dataset.grande; z.style.display = "flex";
  }
});

function opcoes(lista, id, nome, valor) {
  return lista.map(o => `<option value="${esc(o[id])}"${String(o[id]) === String(valor) ? " selected" : ""}>${esc(o[nome])}</option>`).join("");
}

async function abrir(id) {
  itemAtual = resultados.find(r => r.id === id);
  const d = await (await fetch("/api/catalogo/sugestao/" + id)).json();
  const f = document.getElementById("formCadastro"), c = d.campos;
  document.getElementById("tituloForm").textContent = itemAtual.nome;
  document.getElementById("origemForm").innerHTML = `${esc(itemAtual.site_nome)} · ${esc(itemAtual.marca)} ${esc(itemAtual.codigo)} · <a href="${esc(itemAtual.url)}" target="_blank" rel="noopener">ver no site</a>`;
  document.getElementById("siteVeiculos").textContent = itemAtual.site_nome;
  for (const campo of ["desc_produto", "desc_produto_completa", "num_fabricante", "cod_barra", "ncm", "marca_nova"])
    f.elements[campo].value = c[campo] ?? "";
  f.elements.id_marca.innerHTML = '<option value="nova">— criar marca nova —</option>' + opcoes(d.marcas, "id_marca", "descricao", c.id_marca);
  f.elements.id_marca.value = String(c.id_marca);
  f.elements.id_carro.innerHTML = opcoes(d.carros, "id_carro", "descricao", c.id_carro);
  const fornecedores = d.fornecedores.some(o => String(o.id) === String(c.id_fornecedor)) ? d.fornecedores
                       : [{id: c.id_fornecedor, nome: "Fornecedor " + c.id_fornecedor}, ...d.fornecedores];
  f.elements.id_fornecedor.innerHTML = opcoes(fornecedores, "id", "nome", c.id_fornecedor);
  f.elements.unidade.value = c.unidade;
  marcaNova();
  const av = document.getElementById("avisos");
  av.hidden = !c.avisos.length; av.innerHTML = c.avisos.map(a => "⚠ " + esc(a)).join("<br>");
  f.elements.complemento_produto.value = c.complemento_produto || "";
  document.getElementById("resumoVeiculos").textContent = c.veiculos.length
    ? `(${c.veiculos.length} modelo(s), ${c.veiculos.reduce((t, v) => t + v.versoes, 0)} versões)` : "";
  document.getElementById("veiculosForm").innerHTML = c.veiculos.map(v => `
    <div class="veiculo">
      <input type="checkbox" class="vIncluir"${v.id_carro ? " checked" : ""} title="Incluir este carro no produto">
      <select class="vCarro"><option value="">— escolher carro —</option>${opcoes(d.carros, "id_carro", "descricao", v.id_carro)}</select>
      <input type="text" class="vCompl" maxlength="1000" value="${esc(v.complemento)}" title="Complemento do carro">
      <span class="origem">${esc(v.modelo_origem)} · ${v.versoes} versões</span>
    </div>`).join("") || `<span class="origem">${esc(itemAtual.site_nome)} não informa veículos compatíveis para esta peça.</span>`;
  document.getElementById("fotosForm").innerHTML = d.imagens.map((u, k) =>
    `<label><input type="checkbox" value="${esc(u)}"${k < 5 ? " checked" : ""}><img src="${esc(miniatura(u))}" alt="Foto ${k + 1}"></label>`).join("")
    || '<span class="origem">Este item não tem fotos.</span>';
  document.getElementById("modal").style.display = "flex";
  f.elements.desc_produto.focus();
}

function marcaNova() {
  const f = document.getElementById("formCadastro");
  f.elements.marca_nova.disabled = f.elements.id_marca.value !== "nova";
}
document.getElementById("formCadastro").elements.id_marca.onchange = marcaNova;
function fechar() { document.getElementById("modal").style.display = "none"; }

document.getElementById("formCadastro").onsubmit = async e => {
  e.preventDefault();
  const f = e.target, campos = {};
  for (const el of f.elements) if (el.name && !el.disabled) campos[el.name] = el.value;
  const fotos = [...document.querySelectorAll("#fotosForm input:checked")].map(i => i.value).slice(0, 5);
  const veiculos = [...document.querySelectorAll("#veiculosForm .veiculo")].map(l => ({
    incluir: l.querySelector(".vIncluir").checked, id_carro: l.querySelector(".vCarro").value,
    complemento: l.querySelector(".vCompl").value}));
  const btn = document.getElementById("btnCadastrar"); btn.disabled = true; btn.textContent = "Cadastrando…";
  try {
    const r = await fetch("/api/catalogo/cadastrar", {method: "POST", headers: {"Content-Type": "application/json"},
                                                    body: JSON.stringify({id: itemAtual.id, campos, fotos, veiculos})});
    const d = await r.json();
    if (!r.ok) { avisar(d.erro || "Erro ao cadastrar"); return; }
    itemAtual.existente = {cod_produto: d.cod_produto, desc_produto: campos.desc_produto.toUpperCase()};
    fechar();
    main.querySelector(`.linha[data-id="${itemAtual.id}"]`).outerHTML = linhaHtml(itemAtual);
    const texto = `Produto ${d.cod_produto} cadastrado com ${d.fotos} foto(s) e ${d.carros} carro(s) de venda.`;
    if (d.avisos && d.avisos.length) avisar(texto + " Atenção: " + d.avisos.join("; "));
    else avisar(texto + " As fotos estão na curadoria.", true);
  } finally { btn.disabled = false; btn.textContent = "Cadastrar no Wayap"; }
};
document.getElementById("zoom").onclick = e => e.currentTarget.style.display = "none";
document.addEventListener("keydown", e => { if (e.key === "Escape") { fechar(); document.getElementById("zoom").style.display = "none"; } });
carregarSites();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8765)
    args = ap.parse_args()
    estado["wayap"] = Wayap()
    indexar_catalogos()
    estado["hosts"] = {h for s in sites_indexados() for h in json.loads(s["hosts"])}
    print("lendo o cadastro do Wayap...")
    carregar_wayap()
    print(f"Painel em http://localhost:{args.porta}")
    app.run(host="127.0.0.1", port=args.porta, threaded=True)


if __name__ == "__main__":
    main()
