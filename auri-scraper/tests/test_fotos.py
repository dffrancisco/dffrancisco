from io import BytesIO
from pathlib import Path

from PIL import Image

from helper.banco import abrir
from helper.fotos import (baixar, carregar_config, marcar_logos, miniatura, origem_tipo, preparar_imagem,
                          processar_pendentes)

TOML = Path(__file__).resolve().parents[1] / "helper_fotos.toml"


def _png(w, h, cor=(200, 30, 30), modo="RGB"):
    """Imagem com uma faixa branca à esquerda cuja largura depende da cor: imagens lisas teriam dHash 0 e pareceriam iguais."""
    from PIL import ImageDraw
    im = Image.new(modo, (w, h), cor if modo == "RGB" else cor + (0,))
    faixa = w * (sum(cor) % 7 + 1) // 9
    ImageDraw.Draw(im).rectangle([0, 0, faixa, h], fill=(255, 255, 255) if modo == "RGB" else (0, 0, 255, 255))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_preparar_imagem_reduz_e_converte():
    r = preparar_imagem(_png(3000, 1500))
    assert r["largura"] == 1024 and r["altura"] == 512 and r["jpeg"][:2] == b"\xff\xd8" and isinstance(r["dhash"], int)


def test_preparar_imagem_descarta_pequena_e_lixo():
    assert preparar_imagem(_png(200, 600)) is None and preparar_imagem.motivo == "pequena"
    assert preparar_imagem(b"<html>nao sou imagem</html>") is None and preparar_imagem.motivo == "nao e imagem"
    assert preparar_imagem(b"") is None


def test_transparente_ganha_fundo_branco():
    r = preparar_imagem(_png(400, 400, modo="RGBA"))
    im = Image.open(BytesIO(r["jpeg"]))
    assert im.getpixel((399, 399))[0] > 240  # canto transparente ficou branco


def test_miniatura_300():
    r = preparar_imagem(_png(3000, 1500))
    im = Image.open(BytesIO(miniatura(r["jpeg"])))
    assert max(im.size) == 300


def test_origem_tipo():
    cfg = carregar_config(TOML)
    assert origem_tipo("universal", "https://x/y.jpg", cfg) == "fabricante"
    assert origem_tipo("karhub", "https://universalautomotive.vteximg.com.br/a.jpg", cfg) == "fabricante"
    assert origem_tipo("karhub", "https://cdn.shopify.com/a.jpg", cfg) == "loja"


def test_baixar_recusa_conteudo_que_nao_e_imagem():
    class Resp:
        status_code, headers, content = 200, {"Content-Type": "text/html"}, b"<html>"
    class Sessao:
        def get(self, url, timeout): return Resp()
    assert baixar("https://x/a.jpg", sessao=Sessao()) is None


def _banco_com_pendentes(tmp_path, fotos):
    db = abrir(tmp_path / "h.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'ARTEB', 'reposicao')")
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, tipo_peca, status) VALUES (1, 1, 'ARTEB|1', '1', 'LANTERNA TRASEIRA', 'LANTERNA TRASEIRA', 'ativa')")
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, tipo_peca, status) VALUES (2, 1, 'ARTEB|2', '2', 'PARAFUSO', 'PARAFUSO', 'ativa')")
    db.executemany("INSERT INTO foto_pendente (id_peca, url, arquivo_local, prioridade, site) VALUES (?,?,?,?,?)", fotos)
    db.commit()
    return db


def test_processar_pendentes_grava_dedup_e_erros(tmp_path):
    local = tmp_path / "foto_1.png"
    local.write_bytes(_png(800, 800))
    db = _banco_com_pendentes(tmp_path, [
        (1, "https://img/local.png", str(local), 0, "auri"),
        (1, "https://img/igual.png", None, 2, "karhub"),      # mesma imagem: duplicada
        (1, "https://img/outra.png", None, 2, "karhub"),      # imagem diferente: entra
        (1, "https://img/pequena.png", None, 4, "carblue"),   # descartada
        (1, "https://img/html", None, 4, "carblue"),          # erro
        (2, "https://img/parafuso.png", None, 5, "clicpecas")])
    conteudo = {"https://img/igual.png": _png(800, 800), "https://img/outra.png": _png(800, 800, cor=(0, 0, 0)),
                "https://img/pequena.png": _png(100, 100), "https://img/html": b"<html>", "https://img/parafuso.png": _png(500, 500, cor=(0, 255, 0))}
    pasta = tmp_path / "helper_fotos"
    r = processar_pendentes(db, pasta, carregar_config(TOML), baixar=lambda url, sessao=None: conteudo.get(url))
    assert r == {"gravadas": 3, "duplicadas": 1, "descartadas": 1, "erros": 1}
    fotos = db.execute("SELECT id_peca, ordem, arquivo, origem_tipo, publicavel FROM foto ORDER BY id_peca, ordem").fetchall()
    assert [(f["id_peca"], f["ordem"], f["origem_tipo"], f["publicavel"]) for f in fotos] == [(1, 1, "loja", 1), (1, 2, "loja", 1), (2, 1, "loja", 1)]
    arq = fotos[0]["arquivo"]
    assert len(arq) == 44 and arq.endswith(".jpg") and (pasta / "1" / arq).exists() and (pasta / "1" / arq.replace(".jpg", "_p.jpg")).exists()
    assert db.execute("SELECT tem_foto FROM peca WHERE id_peca=1").fetchone()[0] == 1
    assert db.execute("SELECT hash_conteudo FROM peca WHERE id_peca=1").fetchone()[0] is not None
    pendentes = {r["url"]: r["erro"] for r in db.execute("SELECT url, erro FROM foto_pendente")}
    assert pendentes == {"https://img/html": "nao e imagem", "https://img/igual.png": "duplicada", "https://img/pequena.png": "pequena"}
    assert db.execute("SELECT tentativas FROM foto_pendente WHERE url='https://img/html'").fetchone()[0] == 1


def test_processar_pendentes_prioridade_e_limite(tmp_path):
    db = _banco_com_pendentes(tmp_path, [(2, "https://img/parafuso.png", None, 5, "clicpecas"),
                                         (1, "https://img/lanterna.png", None, 5, "clicpecas")])
    conteudo = {"https://img/parafuso.png": _png(500, 500), "https://img/lanterna.png": _png(500, 500)}
    r = processar_pendentes(db, tmp_path / "f", carregar_config(TOML), limite=1, prioridade=True, baixar=lambda u, sessao=None: conteudo[u])
    assert r["gravadas"] == 1 and db.execute("SELECT id_peca FROM foto").fetchone()[0] == 1  # LANTERNA primeiro


def test_marcar_logos(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'X', 'reposicao')")
    for i in range(1, 25):
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?,1,?,?,'P','ativa')", (i, f"X|{i}", str(i)))
        db.execute("INSERT INTO foto (id_peca, ordem, arquivo, dhash, origem_tipo) VALUES (?,1,'a.jpg',12345,'loja')", (i,))
    db.execute("INSERT INTO foto (id_peca, ordem, arquivo, dhash, origem_tipo) VALUES (1,2,'b.jpg',999,'loja')")
    assert marcar_logos(db, max_pecas=20) == 24
    assert db.execute("SELECT count(*) FROM foto WHERE publicavel=0 AND motivo_nao_publicavel='logo'").fetchone()[0] == 24
    assert db.execute("SELECT publicavel FROM foto WHERE arquivo='b.jpg'").fetchone()[0] == 1


def _png_gradiente(w, h):
    """Escurece da esquerda para a direita: todos os 64 bits do dHash ficam ligados (valor >= 2**63)."""
    im = Image.new("L", (w, h))
    im.putdata([255 - (x * 255 // (w - 1)) for y in range(h) for x in range(w)])
    buf = BytesIO()
    im.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def test_dhash_com_bit_alto_cabe_no_sqlite_e_continua_detectando_duplicata(tmp_path):
    r = preparar_imagem(_png_gradiente(600, 400))
    assert r["dhash"] >= 2 ** 63  # é o caso que estourava o INTEGER do SQLite
    db = _banco_com_pendentes(tmp_path, [(1, "https://img/g1.png", None, 2, "karhub"),
                                         (1, "https://img/g2.png", None, 2, "karhub")])
    conteudo = {"https://img/g1.png": _png_gradiente(600, 400), "https://img/g2.png": _png_gradiente(900, 600)}
    res = processar_pendentes(db, tmp_path / "f", carregar_config(TOML), baixar=lambda u, sessao=None: conteudo[u])
    assert res["gravadas"] == 1 and res["duplicadas"] == 1


def test_logo_detectado_depois_atualiza_as_pecas_antigas(tmp_path):
    """I1 da revisão: a 21ª peça com a mesma imagem torna as 20 anteriores não publicáveis; elas precisam
    ganhar tem_foto=0 e hash novo para o publicar reenviar."""
    from helper.fusao import atualizar_hash
    db = abrir(tmp_path / "h.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'X', 'reposicao')")
    img = preparar_imagem(_png(500, 500))
    from helper.fotos import dhash_para_banco
    for i in range(1, 21):
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status, tem_foto) VALUES (?,1,?,?,'P','ativa',1)", (i, f"X|{i}", str(i)))
        db.execute("INSERT INTO foto (id_peca, ordem, arquivo, dhash, origem_tipo) VALUES (?,1,'a.jpg',?,'loja')", (i, dhash_para_banco(img["dhash"])))
        atualizar_hash(db, i)
    hashes_antes = dict(db.execute("SELECT id_peca, hash_conteudo FROM peca"))
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (21,1,'X|21','21','P','ativa')")
    db.execute("INSERT INTO foto_pendente (id_peca, url, prioridade, site) VALUES (21, 'https://img/logo.png', 5, 'karhub')")
    db.commit()
    processar_pendentes(db, tmp_path / "f", carregar_config(TOML), baixar=lambda u, sessao=None: _png(500, 500))
    assert db.execute("SELECT count(*) FROM peca WHERE tem_foto=1").fetchone()[0] == 0
    hashes_depois = dict(db.execute("SELECT id_peca, hash_conteudo FROM peca"))
    assert all(hashes_depois[i] != hashes_antes[i] for i in range(1, 21))


def test_foto_descartada_nao_volta_para_a_fila(tmp_path):
    """I7 da revisão: pequena e duplicada ficam registradas em foto_pendente (sem novas tentativas) para o
    preparar seguinte não as re-enfileirar e o fotos não as baixar de novo."""
    db = _banco_com_pendentes(tmp_path, [(1, "https://img/a.png", None, 2, "karhub"),
                                         (1, "https://img/dup.png", None, 2, "karhub"),
                                         (1, "https://img/pequena.png", None, 2, "karhub")])
    conteudo = {"https://img/a.png": _png(500, 500), "https://img/dup.png": _png(500, 500), "https://img/pequena.png": _png(100, 100)}
    cfg = carregar_config(TOML)
    r = processar_pendentes(db, tmp_path / "f", cfg, baixar=lambda u, sessao=None: conteudo[u])
    assert r["gravadas"] == 1 and r["duplicadas"] == 1 and r["descartadas"] == 1
    restantes = {row["url"]: row["erro"] for row in db.execute("SELECT url, erro FROM foto_pendente")}
    assert restantes == {"https://img/dup.png": "duplicada", "https://img/pequena.png": "pequena"}
    assert processar_pendentes(db, tmp_path / "f", cfg, baixar=lambda u, sessao=None: conteudo[u]) == {"gravadas": 0, "duplicadas": 0, "descartadas": 0, "erros": 0}
