"""Fotos do helper: download, curadoria (tamanho, duplicata, logo), miniatura e origem."""
import hashlib
import tomllib
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image

from helper.fusao import atualizar_hash
from wayap_fotos import DISTANCIA_DUPLICADA, LADO_ENVIO, MENOR_LADO, abrir_rgb, dhash, distancia

LADO_MINIATURA = 300
SUFIXO_MINIATURA = "_p.jpg"


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


def _pendentes(db, config, limite, marca, tipo, prioridade):
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
    tipos = config.get("prioridade", {}).get("tipos", [])

    def peso(l):
        com_cara = any((l["tipo_peca"] or "").startswith(t) for t in tipos) if prioridade else False
        return (0 if l["arquivo_local"] else 1, 0 if com_cara else 1, l["prioridade"], l["id_peca"], l["url"])
    linhas.sort(key=peso)
    return linhas[:limite] if limite else linhas


def processar_pendentes(db, pasta, config, limite=None, marca=None, tipo=None, prioridade=False, baixar=baixar):
    pasta = Path(pasta)
    r = {"gravadas": 0, "duplicadas": 0, "descartadas": 0, "erros": 0}
    sessao = requests.Session()
    tocadas = set()
    for l in _pendentes(db, config, limite, marca, tipo, prioridade):
        id_peca, url = l["id_peca"], l["url"]
        dados = None
        if l["arquivo_local"] and Path(l["arquivo_local"]).exists():
            dados = Path(l["arquivo_local"]).read_bytes()
        if dados is None:
            dados = baixar(url, sessao=sessao)
        img = preparar_imagem(dados) if dados else None
        if img is None:
            motivo = preparar_imagem.motivo if dados else "download falhou"
            if motivo == "pequena":
                db.execute("DELETE FROM foto_pendente WHERE id_peca=? AND url=?", (id_peca, url))
                r["descartadas"] += 1
            else:
                db.execute("UPDATE foto_pendente SET tentativas = tentativas + 1, erro = ? WHERE id_peca=? AND url=?", (motivo, id_peca, url))
                r["erros"] += 1
            continue
        existentes = db.execute("SELECT dhash, largura, altura FROM foto WHERE id_peca=?", (id_peca,)).fetchall()
        if any(e["dhash"] is not None and distancia(e["dhash"], img["dhash"]) <= DISTANCIA_DUPLICADA for e in existentes):
            db.execute("DELETE FROM foto_pendente WHERE id_peca=? AND url=?", (id_peca, url))
            r["duplicadas"] += 1
            continue
        arquivo = hashlib.sha1(img["jpeg"]).hexdigest() + ".jpg"
        destino = pasta / str(id_peca)
        destino.mkdir(parents=True, exist_ok=True)
        (destino / arquivo).write_bytes(img["jpeg"])
        (destino / arquivo.replace(".jpg", SUFIXO_MINIATURA)).write_bytes(miniatura(img["jpeg"]))
        ordem = db.execute("SELECT coalesce(max(ordem), 0) + 1 FROM foto WHERE id_peca=?", (id_peca,)).fetchone()[0]
        db.execute("""INSERT OR IGNORE INTO foto (id_peca, ordem, arquivo, largura, altura, bytes, dhash, origem_tipo, url_fonte)
                      VALUES (?,?,?,?,?,?,?,?,?)""",
                   (id_peca, ordem, arquivo, img["largura"], img["altura"], len(img["jpeg"]), img["dhash"],
                    origem_tipo(l["site"], url, config), url))
        db.execute("DELETE FROM foto_pendente WHERE id_peca=? AND url=?", (id_peca, url))
        tocadas.add(id_peca)
        r["gravadas"] += 1
        if r["gravadas"] % 200 == 0:
            db.commit()
    marcar_logos(db, config.get("logo", {}).get("max_pecas", 20))
    for id_peca in tocadas:
        db.execute("UPDATE peca SET tem_foto = EXISTS (SELECT 1 FROM foto WHERE id_peca=? AND publicavel=1) WHERE id_peca=?", (id_peca, id_peca))
        atualizar_hash(db, id_peca)
    db.commit()
    return r


def marcar_logos(db, max_pecas):
    """A mesma imagem em mais de max_pecas peças diferentes é logo/'sem foto': não publicável."""
    logos = [l[0] for l in db.execute("SELECT dhash FROM foto WHERE dhash IS NOT NULL GROUP BY dhash HAVING count(DISTINCT id_peca) > ?", (max_pecas,))]
    n = 0
    for h in logos:
        n += db.execute("UPDATE foto SET publicavel=0, motivo_nao_publicavel='logo' WHERE dhash=? AND publicavel=1", (h,)).rowcount
    if logos:
        db.execute("UPDATE peca SET tem_foto = EXISTS (SELECT 1 FROM foto f WHERE f.id_peca=peca.id_peca AND publicavel=1)")
    return n
