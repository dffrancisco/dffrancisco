"""Fotos do helper: download, curadoria (tamanho, duplicata, logo), miniatura e origem."""
import hashlib
import socket
import threading
import tomllib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import requests
import urllib3.util.connection
from PIL import Image

from helper.fusao import atualizar_hash
from wayap_fotos import DISTANCIA_DUPLICADA, LADO_ENVIO, MENOR_LADO, abrir_rgb, banner_de_aplicacao, dhash, distancia

# esta rede não tem rota IPv6 e alguns CDNs (cdn.shopify.com) resolvem primeiro para IPv6: igual ao painel_wayap.py
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

LADO_MINIATURA = 300
LOTE_DOWNLOAD = 200  # downloads em paralelo por lote; o processamento e o SQLite ficam na thread principal
SUFIXO_MINIATURA = "_p.jpg"


def dhash_para_banco(h):
    """dHash é 64 bits sem sinal; SQLite e Postgres guardam inteiro de 64 bits com sinal."""
    return h - (1 << 64) if h >= (1 << 63) else h


def dhash_do_banco(v):
    return v & 0xFFFFFFFFFFFFFFFF


def carregar_config(caminho):
    with Path(caminho).open("rb") as f:
        return tomllib.load(f)


def preparar_imagem(dados):
    """bytes -> {'jpeg','largura','altura','dhash'} ou None (motivo em preparar_imagem.motivo)."""
    preparar_imagem.motivo = None
    try:
        im = abrir_rgb(dados)
    except Exception:
        preparar_imagem.motivo = "nao e imagem"
        return None
    if min(im.size) < MENOR_LADO:
        preparar_imagem.motivo = "pequena"
        return None
    if banner_de_aplicacao(im):
        preparar_imagem.motivo = "banner"
        return None
    if max(im.size) > LADO_ENVIO:
        im.thumbnail((LADO_ENVIO, LADO_ENVIO), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=88, optimize=True)
    return {"jpeg": buf.getvalue(), "largura": im.width, "altura": im.height, "dhash": dhash(im)}


def miniatura(jpeg):
    im = Image.open(BytesIO(jpeg))
    im.thumbnail((LADO_MINIATURA, LADO_MINIATURA), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=82)
    return buf.getvalue()


def origem_tipo(site, url, config):
    fab = config.get("fabricante", {})
    host = urlsplit(url or "").hostname or ""
    return "fabricante" if site in fab.get("sites", []) or host in fab.get("hosts", []) else "loja"


def baixar(url, sessao=None):
    sessao = sessao or requests.Session()
    try:
        r = sessao.get(url, timeout=60)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not r.headers.get("Content-Type", "").startswith("image/"):
        return None
    return r.content


def e_prioritaria(tipo, config):
    """Peça "com cara" (helper_fotos.toml, [prioridade]): palavra em qualquer posição do tipo, ou tipo que começa
    com uma das expressões de comeca_com; nunca quando começa com uma das de `nunca`."""
    p = config.get("prioridade", {})
    t = " ".join((tipo or "").upper().split())
    comeca = lambda x: t == x or t.startswith(x + " ")
    if not t or any(comeca(x) for x in p.get("nunca", [])):
        return False
    return bool(set(t.split()) & set(p.get("palavras", []))) or any(comeca(x) for x in p.get("comeca_com", []))


def _pendentes(db, config, limite, marca, tipo, prioridade, so_prioridade=False):
    sql = """SELECT fp.id_peca, fp.url, fp.arquivo_local, fp.prioridade, fp.site, p.tipo_peca
             FROM foto_pendente fp JOIN peca p USING (id_peca) JOIN marca m USING (id_marca)
             WHERE p.status = 'ativa' AND fp.tentativas < ?"""
    params = [config.get("download", {}).get("tentativas_maximas", 3)]
    if marca:
        sql += " AND m.nome = ?"
        params.append(marca.upper())
    if tipo:
        sql += " AND p.tipo_peca LIKE ?"
        params.append(tipo.upper() + "%")
    linhas = db.execute(sql, params).fetchall()
    if so_prioridade:
        linhas = [l for l in linhas if e_prioritaria(l["tipo_peca"], config)]

    def peso(l):
        com_cara = e_prioritaria(l["tipo_peca"], config) if prioridade else False
        return (0 if l["arquivo_local"] else 1, 0 if com_cara else 1, l["prioridade"], l["id_peca"], l["url"])
    linhas.sort(key=peso)
    return linhas[:limite] if limite else linhas


def processar_pendentes(db, pasta, config, limite=None, marca=None, tipo=None, prioridade=False, so_prioridade=False,
                        baixar=baixar):
    pasta = Path(pasta)
    r = {"gravadas": 0, "duplicadas": 0, "descartadas": 0, "erros": 0}
    tocadas = set()
    max_tentativas = config.get("download", {}).get("tentativas_maximas", 3)
    paralelo = max(1, int(config.get("download", {}).get("paralelo", 1)))
    local = threading.local()  # uma sessão HTTP por thread

    def obter(l):
        if l["arquivo_local"] and Path(l["arquivo_local"]).exists():
            return Path(l["arquivo_local"]).read_bytes()
        if not hasattr(local, "sessao"):
            local.sessao = requests.Session()
        return baixar(l["url"], sessao=local.sessao)

    linhas = _pendentes(db, config, limite, marca, tipo, prioridade, so_prioridade)
    with ThreadPoolExecutor(paralelo) as executor:
        for inicio in range(0, len(linhas), LOTE_DOWNLOAD):
            lote = linhas[inicio:inicio + LOTE_DOWNLOAD]
            for l, dados in zip(lote, executor.map(obter, lote)):
                _processar_uma(db, pasta, config, l, dados, r, tocadas, max_tentativas)
            db.commit()
    marcar_logos(db, config.get("logo", {}).get("max_pecas", 20))
    for id_peca in tocadas:
        db.execute("UPDATE peca SET tem_foto = EXISTS (SELECT 1 FROM foto WHERE id_peca=? AND publicavel=1) WHERE id_peca=?", (id_peca, id_peca))
        atualizar_hash(db, id_peca)
    db.commit()
    return r


def _processar_uma(db, pasta, config, l, dados, r, tocadas, max_tentativas):
    """Cura uma foto já baixada (thread principal): descarta, marca duplicada ou grava arquivo, miniatura e linha."""
    id_peca, url = l["id_peca"], l["url"]
    img = preparar_imagem(dados) if dados else None
    if img is None:
        motivo = preparar_imagem.motivo if dados else "download falhou"
        if motivo in ("pequena", "banner"):  # recusa definitiva: fica registrada para o preparar não re-enfileirar
            db.execute("UPDATE foto_pendente SET tentativas = ?, erro = ? WHERE id_peca=? AND url=?", (max_tentativas, motivo, id_peca, url))
            r["descartadas"] += 1
        else:
            db.execute("UPDATE foto_pendente SET tentativas = tentativas + 1, erro = ? WHERE id_peca=? AND url=?", (motivo, id_peca, url))
            r["erros"] += 1
        return
    existentes = db.execute("SELECT dhash, largura, altura FROM foto WHERE id_peca=?", (id_peca,)).fetchall()
    if any(e["dhash"] is not None and distancia(dhash_do_banco(e["dhash"]), img["dhash"]) <= DISTANCIA_DUPLICADA for e in existentes):
        db.execute("UPDATE foto_pendente SET tentativas = ?, erro = 'duplicada' WHERE id_peca=? AND url=?", (max_tentativas, id_peca, url))
        r["duplicadas"] += 1
        return
    arquivo = hashlib.sha1(img["jpeg"]).hexdigest() + ".jpg"
    destino = pasta / str(id_peca)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / arquivo).write_bytes(img["jpeg"])
    (destino / arquivo.replace(".jpg", SUFIXO_MINIATURA)).write_bytes(miniatura(img["jpeg"]))
    ordem = db.execute("SELECT coalesce(max(ordem), 0) + 1 FROM foto WHERE id_peca=?", (id_peca,)).fetchone()[0]
    db.execute("""INSERT OR IGNORE INTO foto (id_peca, ordem, arquivo, largura, altura, bytes, dhash, origem_tipo, url_fonte)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
               (id_peca, ordem, arquivo, img["largura"], img["altura"], len(img["jpeg"]), dhash_para_banco(img["dhash"]),
                origem_tipo(l["site"], url, config), url))
    db.execute("DELETE FROM foto_pendente WHERE id_peca=? AND url=?", (id_peca, url))
    tocadas.add(id_peca)
    r["gravadas"] += 1


def marcar_logos(db, max_pecas):
    """A mesma imagem em mais de max_pecas peças diferentes é logo/'sem foto': não publicável."""
    logos = [l[0] for l in db.execute("SELECT dhash FROM foto WHERE dhash IS NOT NULL GROUP BY dhash HAVING count(DISTINCT id_peca) > ?", (max_pecas,))]
    n, afetadas = 0, set()
    for h in logos:
        afetadas.update(l[0] for l in db.execute("SELECT DISTINCT id_peca FROM foto WHERE dhash=? AND publicavel=1", (h,)))
        n += db.execute("UPDATE foto SET publicavel=0, motivo_nao_publicavel='logo' WHERE dhash=? AND publicavel=1", (h,)).rowcount
    for id_peca in afetadas:  # peças antigas também: tem_foto e hash mudam para o publicar reenviá-las
        db.execute("UPDATE peca SET tem_foto = EXISTS (SELECT 1 FROM foto WHERE id_peca=? AND publicavel=1) WHERE id_peca=?", (id_peca, id_peca))
        atualizar_hash(db, id_peca)
    return n
