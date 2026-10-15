from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from helper.banco import abrir
from helper.topcar_fotos import ean_valido, importar, planejar


def _jpeg(w, h, cor=(200, 30, 30)):
    im = Image.new("RGB", (w, h), cor)
    faixa = w * (sum(cor) % 7 + 1) // 9
    ImageDraw.Draw(im).rectangle([0, 0, faixa, h], fill=(255, 255, 255))
    buf = BytesIO()
    im.save(buf, format="JPEG")
    return buf.getvalue()


def _banco(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'ARTEB', 'reposicao')")
    for id_peca, ean, tem_foto in [(1, "7891000000001", 0), (2, "7891000000002", 0), (3, "7891000000003", 1),
                                   (4, "7891000000004", 0), (5, "7891000000004", 0), (6, None, 0), (7, "7891000000007", 0)]:
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, ean, desc_curta, status, tem_foto) VALUES (?,1,?,?,?,'P','ativa',?)",
                   (id_peca, f"X|{id_peca}", str(id_peca), ean, tem_foto))
    db.execute("INSERT INTO foto (id_peca, ordem, arquivo, origem_tipo) VALUES (3, 1, 'x.jpg', 'loja')")
    db.commit()
    return db


def test_ean_valido():
    assert ean_valido(" 7891000000001 ") == "7891000000001"
    assert ean_valido("ABC") is None and ean_valido(None) is None and ean_valido("1234567") is None


def test_planejar_casa_pelo_ean_so_pecas_sem_foto_e_eans_unicos(tmp_path):
    db = _banco(tmp_path)
    produtos = [(101, "7891000000001"), (102, "7891000000002"), (103, "7891000000003"), (104, "7891000000004"),
                (107, "7891000000007"), (117, "7891000000007")]
    fotos = [(101, "a.jpg", 1), (101, "b.jpg", 2), (103, "c.jpg", 1), (104, "d.jpg", 1), (107, "e.jpg", 1), (117, "f.jpg", 1)]
    plano, motivos = planejar(db, produtos, fotos)
    assert [(p["id_peca"], p["cod_produto"], [f for f in p["arquivos"]]) for p in plano] == [(1, 101, ["a.jpg", "b.jpg"])]
    assert motivos == {"peca_ja_tem_foto": 1, "ean_repetido_helper": 2, "ean_repetido_topcar": 1, "sem_ean": 1, "topcar_sem_foto": 1}


def test_importar_grava_dedup_descarta_e_e_idempotente(tmp_path):
    db = _banco(tmp_path)
    origem = tmp_path / "topcar"
    (origem / "101").mkdir(parents=True)
    (origem / "101" / "a.jpg").write_bytes(_jpeg(800, 800))
    (origem / "101" / "b.jpg").write_bytes(_jpeg(800, 800))                  # igual à primeira: duplicada
    (origem / "101" / "c.jpg").write_bytes(_jpeg(600, 600, cor=(0, 0, 0)))   # diferente: entra
    (origem / "101" / "d.jpg").write_bytes(_jpeg(100, 100))                  # pequena: descartada
    (origem / "102").mkdir()                                                  # e.jpg não existe: ausente
    produtos = [(101, "7891000000001"), (102, "7891000000002")]
    fotos = [(101, "a.jpg", 1), (101, "b.jpg", 2), (101, "c.jpg", 3), (101, "d.jpg", 4), (102, "e.jpg", 1)]
    pasta = tmp_path / "helper_fotos"
    r = importar(db, pasta, "topcar", produtos, fotos, origem)
    assert r == {"pecas": 1, "gravadas": 2, "duplicadas": 1, "descartadas": 1, "ausentes": 1}
    linhas = db.execute("SELECT id_peca, ordem, arquivo, origem_tipo, url_fonte, publicada, largura FROM foto WHERE id_peca=1 ORDER BY ordem").fetchall()
    assert [(l["ordem"], l["origem_tipo"], l["url_fonte"], l["publicada"], l["largura"]) for l in linhas] == \
        [(1, "loja", "wayap://topcar/101/a.jpg", 0, 800), (2, "loja", "wayap://topcar/101/c.jpg", 0, 600)]
    arq = linhas[0]["arquivo"]
    assert len(arq) == 44 and (pasta / "1" / arq).exists() and (pasta / "1" / arq.replace(".jpg", "_p.jpg")).exists()
    assert db.execute("SELECT tem_foto, hash_conteudo FROM peca WHERE id_peca=1").fetchone()[0] == 1
    assert db.execute("SELECT hash_conteudo FROM peca WHERE id_peca=1").fetchone()[0] is not None
    # segunda rodada: a peça 1 já tem foto e sai do plano; o arquivo ausente da peça 2 é tentado de novo (e continua ausente)
    assert importar(db, pasta, "topcar", produtos, fotos, origem) == {"pecas": 0, "gravadas": 0, "duplicadas": 0, "descartadas": 0, "ausentes": 1}
