import openpyxl
import pytest

from helper.banco import abrir
from helper.cli import main
from helper.lista import Casador, Item, codigos_do_campo, ean_do_cliente, ler_planilha
from helper.marcas import Marcas
from tests.test_marcas import CSV

PECAS = [  # id, marca, código, ean
    (1, "KYB", "3440007", "7891234567895"),
    (2, "TC CHICOTES", "TC1071079", None),
    (3, "DS", "1116", None),
    (4, "FRASLE", "PD/1494", None),
    (5, "TECFIL", "PSL62", None),
    (6, "VETOR", "VT8017", "7898195951053"),
    (7, "GAUSS", "GS2197", None),
    (8, "RAINHA DAS SETE", "7090B", None),
    (9, "VP VIRTUAL PLASTIC", "7119", None),
]


def _db(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    for id_peca, marca, codigo, ean in PECAS:
        db.execute("INSERT OR IGNORE INTO marca (nome, tipo) VALUES (?, 'reposicao')", (marca,))
        idm = db.execute("SELECT id_marca FROM marca WHERE nome=?", (marca,)).fetchone()[0]
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, ean, desc_curta, status) VALUES (?,?,?,?,?,'PECA','ativa')",
                   (id_peca, idm, f"{marca}|{codigo}", codigo, ean))
    db.execute("UPDATE peca SET tem_foto=1 WHERE id_peca=1")
    db.execute("INSERT INTO foto_pendente (id_peca, url) VALUES (2, 'https://k/tc.jpg')")
    db.commit()
    return db


@pytest.fixture
def casar(tmp_path):
    casador = Casador(_db(tmp_path), Marcas.carregar(CSV))
    return lambda marca, codigos=(), ean=None: casador.casar(Item(cod="1", ean=ean, codigos=list(codigos), marca=marca))


def test_ean_do_cliente_descarta_os_internos():
    assert ean_do_cliente("7898195951053") == "7898195951053"
    assert ean_do_cliente("087295118771") == "0087295118771"  # UPC de 12 dígitos
    assert ean_do_cliente("0000000112628") is None  # número interno com zeros na frente
    assert ean_do_cliente("2000000012346") is None  # prefixo 2: uso interno da loja
    assert ean_do_cliente("7000000121869") is None  # 7000000 + código do produto
    assert ean_do_cliente("123456789") is None and ean_do_cliente("") is None


def test_codigos_do_campo_separa_por_barra_com_espaco_e_tira_lixo():
    assert codigos_do_campo("SP08 / 0242235661 / SP22 { }") == ["SP08", "0242235661", "SP22"]
    assert codigos_do_campo("066.782 / 13B-12M") == ["066782", "13B12M"]
    assert codigos_do_campo("PD/1494") == ["PD/1494"]  # barra sem espaço faz parte do código
    assert codigos_do_campo("ETE7637 | TC5000723") == ["ETE7637", "TC5000723"]
    assert codigos_do_campo("") == []


def test_ean_vale_mesmo_com_a_marca_escrita_de_outro_jeito(casar):
    r = casar("VTO", ["VTO8017"], ean="7898195951053")
    assert (r["via"], r["ids"], r["marca_divergente"]) == ("ean", [6], True)


def test_codigo_com_apelido_de_marca(casar):
    assert casar("KAYABA", ["3440007"])["ids"] == [1]
    assert casar("TC", ["TC1071079"])["ids"] == [2]


def test_prefixo_que_o_cliente_poe_no_codigo(casar):
    assert casar("D S", ["DS1116"])["ids"] == [3]
    assert casar("RAINHA DA SETE", ["ETE7090B"])["ids"] == [8]
    assert casar("VP", ["VP7119"])["ids"] == [9]  # VP é a primeira palavra de VP VIRTUAL PLASTIC


def test_barra_e_sufixo_da_marca(casar):
    assert casar("FRASLE", ["PD1494"])["ids"] == [4]
    assert casar("TECFIL", ["PSL62B"])["ids"] == [5]


def test_adicional_da_mesma_marca_conta(casar):
    """Vela BOSCH SP11: o número Bosch F000KE0P11 vem nos adicionais e é o que as lojas usam."""
    assert casar("KAYABA", ["GB48302", "3440007"])["ids"] == [1]


def test_codigo_de_outra_marca_nao_conta(casar):
    """Os códigos adicionais da planilha são equivalências de outras marcas: foto de outra marca não serve."""
    assert casar("D S", ["GS2197"]) == {"via": None, "ids": [], "marca_divergente": False}
    assert casar("IMPORTADO", ["GS2197"])["ids"] == []  # marca genérica só casa por EAN


def _planilha(caminho, linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Código", "Catálogo", "Cód Barra", "Códigos Adicionais", "Nome", "Grupo", "Marca", "Ativo"])
    for l in linhas:
        ws.append(l)
    wb.save(caminho)


def test_ler_planilha_e_ativo(tmp_path):
    _planilha(tmp_path / "p.xlsx", [
        [1.0, "SP08 / 0242235661", "7898195951053", "SP08 | GS2197", "VELA", "IGNICAO", "BOSCH", "S"],
        [2.0, "X1", None, None, "FILTRO", "INATIVOS", "BOSCH", "S"],
        [3.0, "X2", None, None, "FILTRO", "FILTROS", "DESATIVADO", "S"],
        [4.0, "X3", None, None, "FILTRO", "FILTROS", "BOSCH", "N"]])
    itens = ler_planilha(tmp_path / "p.xlsx")
    # os adicionais vêm depois do catálogo; os de outra marca são barrados no casamento pela marca
    assert (itens[0].cod, itens[0].ean, itens[0].codigos, itens[0].marca) == ("1", "7898195951053", ["SP08", "0242235661", "GS2197"], "BOSCH")
    assert [i.ativo for i in itens] == [True, False, False, False]


def test_comando_lista_grava_itens_ids_e_pendentes(tmp_path):
    _db(tmp_path).close()
    _planilha(tmp_path / "p.xlsx", [
        [10.0, "3440007", None, None, "AMORTECEDOR", "SUSPENSAO", "KAYABA", "S"],
        [11.0, "TC1071079", None, None, "CHICOTE", "ELETRICA", "TC", "S"],
        [12.0, "NAOEXISTE", None, None, "SENSOR", "INJECAO", "BOSCH", "S"]])
    assert main(["lista", str(tmp_path / "p.xlsx"), "--nome", "teste", "--base", str(tmp_path), "--banco", str(tmp_path / "h.sqlite")]) == 0
    pasta = tmp_path / "helper_listas/teste"
    assert (pasta / "ids.txt").read_text().split() == ["1", "2"]
    itens = (pasta / "itens.csv").read_text(encoding="utf-8").splitlines()
    assert itens[1].split(";")[:4] == ["10", "codigo", "1", "tem_foto"] and itens[2].split(";")[3] == "pendente"
    pendentes = (pasta / "pendentes.csv").read_text(encoding="utf-8").splitlines()
    assert len(pendentes) == 2 and pendentes[1].startswith("12;")
