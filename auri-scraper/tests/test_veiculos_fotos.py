from io import BytesIO

from PIL import Image

from helper.banco import abrir
from helper.montadoras import Montadoras
from helper.veiculos import carregar_arvore
from helper.veiculos_fotos import modelo_pai, para_png, para_webp, processar_imagens
from tests.test_veiculos import _linha


def _img(cor=(200, 0, 0, 255), tam=(600, 450)):
    im = Image.new("RGBA", tam, (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (100, 100), cor), (10, 10))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _base(tmp_path, linhas):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, linhas, Montadoras({}))
    return db


def _imagens_karhub(tmp_path, foto=None, logo=None):
    imgs = tmp_path / "veiculos/imagens"
    (imgs / "veiculos").mkdir(parents=True)
    (imgs / "assets/montadoras").mkdir(parents=True)
    if foto is not None:
        (imgs / "veiculos/chevrolet-tracker.avif").write_bytes(foto)
    if logo is not None:
        (imgs / "assets/montadoras/chevrolet.avif").write_bytes(logo)
    return imgs


def test_conversoes_mantem_transparencia():
    w = Image.open(BytesIO(para_webp(_img())))
    assert w.format == "WEBP" and w.mode == "RGBA" and w.size == (600, 450) and w.getpixel((500, 400))[3] == 0
    p = Image.open(BytesIO(para_png(_img(tam=(400, 400)))))
    assert p.format == "PNG" and p.size == (200, 200) and p.mode == "RGBA"


def test_foto_do_karhub_logo_e_heranca(tmp_path):
    db = _base(tmp_path, [_linha(), _linha(modelo="Tracker Premier", foto=None), _linha(modelo="Onix", foto=None)])
    imgs = _imagens_karhub(tmp_path, foto=_img(), logo=_img(tam=(200, 200)))
    r = processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    fotos = {x["nome"]: (x["foto"], x["foto_herdada"]) for x in db.execute("SELECT nome, foto, foto_herdada FROM veiculo_modelo")}
    foto_tracker = fotos["TRACKER"][0]
    assert foto_tracker.startswith("veiculos/modelos/") and foto_tracker.endswith(".webp") and fotos["TRACKER"][1] == 0
    assert fotos["TRACKER PREMIER"] == (foto_tracker, 1)
    assert fotos["ONIX"] == (None, 0)
    logo = db.execute("SELECT logo FROM veiculo_montadora").fetchone()[0]
    assert logo.startswith("veiculos/montadoras/") and logo.endswith(".png")
    assert (tmp_path / "helper_fotos_veiculos" / foto_tracker.removeprefix("veiculos/")).exists()
    assert {a[0] for a in db.execute("SELECT caminho FROM veiculo_arquivo WHERE publicado = 0")} == {foto_tracker, logo}
    assert (r["foto_karhub"], r["foto_herdada"], r["foto_sem"], r["logo_karhub"]) == (1, 1, 1, 1)


def test_imagem_propria_tem_prioridade(tmp_path):
    db = _base(tmp_path, [_linha()])
    imgs = _imagens_karhub(tmp_path, foto=_img((200, 0, 0, 255)))
    proprias = tmp_path / "helper_fotos_veiculos/proprias"
    (proprias / "modelos").mkdir(parents=True)
    (proprias / "modelos/Chevrolet-Tracker.png").write_bytes(_img((0, 0, 200, 255)))
    (proprias / "montadoras").mkdir(parents=True)
    (proprias / "montadoras/chevrolet.png").write_bytes(_img(tam=(200, 200)))
    r = processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    foto = db.execute("SELECT foto FROM veiculo_modelo").fetchone()[0]
    px = Image.open(tmp_path / "helper_fotos_veiculos" / foto.removeprefix("veiculos/")).convert("RGBA").getpixel((50, 50))
    assert px[2] > 150 and px[0] < 50  # azul da própria, não o vermelho do KarHub
    assert r["foto_propria"] == 1 and r["logo_propria"] == 1


def test_imagem_corrompida_nao_derruba(tmp_path):
    db = _base(tmp_path, [_linha()])
    imgs = _imagens_karhub(tmp_path, foto=b"<html>erro do cloudflare</html>", logo=b"\x89PNG truncado")
    r = processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    assert db.execute("SELECT foto FROM veiculo_modelo").fetchone()[0] is None
    assert db.execute("SELECT logo FROM veiculo_montadora").fetchone()[0] is None
    assert r["foto_invalida"] == 1 and r["logo_invalida"] == 1


def test_rodar_de_novo_nao_duplica_arquivo(tmp_path):
    db = _base(tmp_path, [_linha()])
    imgs = _imagens_karhub(tmp_path, foto=_img())
    processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    assert len(list((tmp_path / "helper_fotos_veiculos/modelos").iterdir())) == 1
    assert db.execute("SELECT count(*) FROM veiculo_arquivo").fetchone()[0] == 1


def test_modelo_pai():
    nomes = {"ASTRA": 1, "ASTRA HATCH": 2, "ASTRA HATCH GSI": 3}
    assert modelo_pai("ASTRA HATCH GSI", nomes, {1: "a.webp", 2: None}) == 1
    assert modelo_pai("ASTRA HATCH GSI", nomes, {1: "a.webp", 2: "b.webp"}) == 2
    assert modelo_pai("ASTRA", nomes, {1: "a.webp"}) is None
