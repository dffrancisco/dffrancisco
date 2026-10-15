"""Fotos dos produtos de um tenant do Wayap (topcar) para as peças do helper que ainda não têm foto, casando pelo EAN.

As fotos da topcar são de loja (subidas pelo painel ou pelo wayap_fotos.py); entram como origem_tipo 'loja' com
url_fonte 'wayap://<sociedade>/<cod_produto>/<arquivo>' e publicada = 0: o `publicar` normal sobe arquivos e linhas.
Fonte dos arquivos: a pasta do tenant (<PATH_NF>/<sociedade>/store/foto_produto), não a API — roda na máquina que
tem a pasta (ou uma cópia dela).
"""
import hashlib
import re
from pathlib import Path

from helper.fotos import SUFIXO_MINIATURA, dhash_do_banco, dhash_para_banco, marcar_logos, miniatura, preparar_imagem
from helper.fusao import atualizar_hash
from wayap_fotos import DISTANCIA_DUPLICADA, distancia

PASTA_ORIGEM_PADRAO = "/home/wayap/{sociedade}/store/foto_produto"


def ean_valido(e):
    t = (e or "").strip()
    return t if re.fullmatch(r"\d{8,14}", t) else None


def _unicos(pares):
    """{chave: valor} só das chaves que aparecem uma vez; devolve também quantas chaves se repetiram."""
    contagem = {}
    for chave, _ in pares:
        contagem[chave] = contagem.get(chave, 0) + 1
    return {c: v for c, v in pares if contagem[c] == 1}, sum(1 for n in contagem.values() if n > 1)


def planejar(db, produtos, fotos):
    """produtos: [(cod_produto, cod_barra)] ativos da topcar; fotos: [(cod_produto, nome_imagem, ordem)] ativas.
    Devolve ([{id_peca, cod_produto, arquivos}], motivos): só peça ativa sem foto publicável, EAN único nos dois lados."""
    motivos = {}

    def motivo(m, n=1):
        motivos[m] = motivos.get(m, 0) + n

    por_produto = {}
    for cod, nome, ordem in sorted(fotos, key=lambda f: (f[0], f[2])):
        por_produto.setdefault(cod, []).append(nome)
    topcar, rep = _unicos([(ean_valido(b), c) for c, b in produtos if ean_valido(b)])
    if rep:
        motivo("ean_repetido_topcar", rep)

    pecas = db.execute("SELECT id_peca, ean, tem_foto FROM peca WHERE status = 'ativa'").fetchall()
    eans = [(ean_valido(p["ean"]), p["id_peca"]) for p in pecas if ean_valido(p["ean"])]
    unicos, _ = _unicos(eans)
    plano = []
    for p in pecas:
        ean = ean_valido(p["ean"])
        if not ean:
            motivo("sem_ean")
            continue
        if ean not in unicos:
            motivo("ean_repetido_helper")
            continue
        if ean not in topcar:
            continue  # peça que a topcar não tem: nem conta, é a maioria do helper
        if db.execute("SELECT 1 FROM foto WHERE id_peca=? AND publicavel=1 LIMIT 1", (p["id_peca"],)).fetchone():
            motivo("peca_ja_tem_foto")
            continue
        arquivos = por_produto.get(topcar[ean])
        if not arquivos:
            motivo("topcar_sem_foto")
            continue
        plano.append({"id_peca": p["id_peca"], "cod_produto": topcar[ean], "arquivos": arquivos})
    return plano, motivos


def importar(db, pasta, sociedade, produtos, fotos, pasta_origem, limite=None, max_pecas_logo=20):
    """Grava as fotos do plano em <pasta>/<id_peca>/ e na tabela foto (publicada = 0). Idempotente pela url_fonte."""
    pasta, pasta_origem = Path(pasta), Path(pasta_origem)
    r = {"pecas": 0, "gravadas": 0, "duplicadas": 0, "descartadas": 0, "ausentes": 0}
    plano, _ = planejar(db, produtos, fotos)
    tocadas = set()
    for p in plano[:limite] if limite else plano:
        id_peca, cod = p["id_peca"], p["cod_produto"]
        gravou = False
        for nome in p["arquivos"]:
            url = f"wayap://{sociedade}/{cod}/{nome}"
            if db.execute("SELECT 1 FROM foto WHERE url_fonte=?", (url,)).fetchone():
                continue
            caminho = pasta_origem / str(cod) / nome
            if not caminho.exists():
                r["ausentes"] += 1
                continue
            img = preparar_imagem(caminho.read_bytes())
            if img is None:
                r["descartadas"] += 1
                continue
            existentes = db.execute("SELECT dhash FROM foto WHERE id_peca=?", (id_peca,)).fetchall()
            if any(e["dhash"] is not None and distancia(dhash_do_banco(e["dhash"]), img["dhash"]) <= DISTANCIA_DUPLICADA for e in existentes):
                r["duplicadas"] += 1
                continue
            arquivo = hashlib.sha1(img["jpeg"]).hexdigest() + ".jpg"
            destino = pasta / str(id_peca)
            destino.mkdir(parents=True, exist_ok=True)
            (destino / arquivo).write_bytes(img["jpeg"])
            (destino / arquivo.replace(".jpg", SUFIXO_MINIATURA)).write_bytes(miniatura(img["jpeg"]))
            ordem = db.execute("SELECT coalesce(max(ordem), 0) + 1 FROM foto WHERE id_peca=?", (id_peca,)).fetchone()[0]
            db.execute("""INSERT OR IGNORE INTO foto (id_peca, ordem, arquivo, largura, altura, bytes, dhash, origem_tipo, url_fonte)
                          VALUES (?,?,?,?,?,?,?,'loja',?)""",
                       (id_peca, ordem, arquivo, img["largura"], img["altura"], len(img["jpeg"]), dhash_para_banco(img["dhash"]), url))
            r["gravadas"] += 1
            gravou = True
            tocadas.add(id_peca)
        if gravou:
            r["pecas"] += 1
        db.commit()
    if tocadas:
        marcar_logos(db, max_pecas_logo)
    for id_peca in tocadas:
        db.execute("UPDATE peca SET tem_foto = EXISTS (SELECT 1 FROM foto WHERE id_peca=? AND publicavel=1) WHERE id_peca=?", (id_peca, id_peca))
        atualizar_hash(db, id_peca)
    db.commit()
    return r


def carregar_tenant(con):
    """Produtos ativos e fotos ativas do tenant (conexão psycopg2 somente leitura)."""
    with con.cursor() as cur:
        cur.execute("SELECT cod_produto, cod_barra FROM produto WHERE deletado = 'N'")
        produtos = cur.fetchall()
        cur.execute("""SELECT cod_produto, nome_imagem, ordem_imagem FROM produto_foto
                       WHERE deletado_em IS NULL AND nome_imagem <> ''""")
        fotos = cur.fetchall()
    return produtos, fotos
