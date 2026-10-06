import sqlite3

import pytest

import painel_veiculos
from helper.banco import abrir


def _helper(tmp_path):
    """helper.sqlite pequeno: Chevrolet (Onix com foto e versões, Celta), Fiat (Uno), Honda (Biz, moto) e Gurgel (só
    modelo inativo). Peça 1: todas as versões do Onix 2013-2016, só a LT em 2017-2019 e texto 'Uno a partir de 2010';
    peça 2: texto 'Celta' sem ano; peça 3 inativa; peça 4 sem veículos."""
    caminho = tmp_path / "helper.sqlite"
    db = abrir(caminho)
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'FREMAX', 'reposicao')")
    for id_peca, desc, status in [(1, "PASTILHA FREIO", "ativa"), (2, "TAMBOR FREIO", "ativa"),
                                  (3, "PASTILHA VELHA", "inativa"), (4, "DISCO FREIO", "ativa")]:
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?, 1, ?, ?, ?, ?)",
                   (id_peca, f"F|{id_peca}", str(id_peca), desc, status))
    db.executemany("INSERT INTO origem (id_peca, site, url) VALUES (?, ?, ?)", [
        (1, "karhub", "https://k/p1"), (1, "universal", "https://u/p1"), (2, "carblue", "https://c/p2"),
        (3, "karhub", "https://k/p3"), (4, "karhub", "https://k/p4")])
    db.executemany("INSERT INTO vei_montadora (id_veiculo_montadora, nome, nome_exibicao, logo, qtd_pecas) "
                   "VALUES (?, ?, ?, ?, ?)", [
                       (1, "CHEVROLET", "Chevrolet", "veiculos/montadoras/1_aaa.png", 50), (2, "FIAT", "Fiat", None, 80),
                       (3, "HONDA", "Honda", None, 5), (4, "GURGEL", "Gurgel", None, 90)])
    db.executemany("INSERT INTO vei_modelo (id_modelo, id_veiculo_montadora, nome, nome_exibicao, tipo, foto, ano_inicio, "
                   "ano_fim, ativo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                       (10, 1, "ONIX", "Onix", "carro", "veiculos/modelos/10_bbb.webp", 2013, 2019, 1),
                       (11, 1, "CELTA", "Celta", "carro", None, 2005, 2010, 1),
                       (20, 2, "UNO", "Uno", "carro", None, 2008, 2012, 1),
                       (30, 3, "BIZ", "Biz", "moto", None, 2010, 2020, 1),
                       (40, 4, "BR 800", "BR 800", "carro", None, 1988, 1991, 0)])
    db.executemany("INSERT INTO vei_versao (id_versao, id_modelo, nome, nome_exibicao, motor, ativo) "
                   "VALUES (?, ?, ?, ?, ?, ?)", [
                       (100, 10, "LT 1.4 8V FLEX", "Lt 1.4 8v Flex", "1.4", 1),
                       (101, 10, "LS 1.0 8V FLEX", "Ls 1.0 8v Flex", "1.0", 1),
                       (102, 10, "LTZ 1.4 8V FLEX", "Ltz 1.4 8v Flex", "1.4", 0),
                       (110, 11, "LIFE 1.0", "Life 1.0", "1.0", 1), (200, 20, "MILLE 1.0", "Mille 1.0", "1.0", 1),
                       (300, 30, "KS 100CC", "Ks 100cc", None, 1), (400, 40, "SL 0.8", "Sl 0.8", "0.8", 1)])
    db.executemany("INSERT INTO vei_versao_ano VALUES (?, ?)",
                   [(100, a) for a in range(2013, 2020)] + [(101, a) for a in range(2013, 2017)]
                   + [(102, a) for a in range(2015, 2020)] + [(110, a) for a in range(2005, 2011)]
                   + [(200, a) for a in range(2008, 2013)] + [(300, a) for a in range(2010, 2021)]
                   + [(400, a) for a in range(1988, 1992)])
    db.executemany("INSERT INTO vei_peca VALUES (?, ?, ?, ?, ?, ?)", [
        (1, 10, None, 2013, 2016, "versao"),   # todas as versões do Onix 2013-2016
        (1, 10, 100, 2017, 2019, "versao"),    # só a LT em 2017-2019
        (1, 20, None, 2010, None, "modelo"),   # texto de aplicação: Uno a partir de 2010
        (2, 11, None, None, None, "modelo"),   # texto sem ano: Celta
        (3, 10, None, 2013, 2019, "versao")])  # peça inativa
    db.commit()
    db.close()
    return caminho


def test_helper_ausente_ou_sem_veiculos(tmp_path):
    vazio, sem_modelos = tmp_path / "vazio.sqlite", tmp_path / "sem_modelos.sqlite"
    sqlite3.connect(vazio).close()
    abrir(sem_modelos).close()
    for caminho in (tmp_path / "nao_existe.sqlite", vazio, sem_modelos):
        with pytest.raises(painel_veiculos.Indisponivel):
            with painel_veiculos.helper(caminho):
                pass


def test_helper_so_leitura_e_trava_vira_ocupado(tmp_path):
    caminho = _helper(tmp_path)
    with painel_veiculos.helper(caminho) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM vei_modelo")
    with pytest.raises(painel_veiculos.Ocupado):
        with painel_veiculos.helper(caminho):
            raise sqlite3.OperationalError("database is locked")


def test_url_imagem():
    assert painel_veiculos.url_imagem("veiculos/modelos/10_bbb.webp") == "/veiculos/img/modelos/10_bbb.webp"
    assert painel_veiculos.url_imagem(None) is None


def test_listas_do_seletor(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        montadoras = painel_veiculos.montadoras(db)
        assert [m["nome"] for m in montadoras] == ["Fiat", "Chevrolet", "Honda"]  # Gurgel só tem modelo inativo
        assert montadoras[1] == {"id": 1, "nome": "Chevrolet", "logo_url": "/veiculos/img/montadoras/1_aaa.png",
                                 "qtd_pecas": 50}
        assert painel_veiculos.modelos(db, 1) == [
            {"id": 11, "nome": "Celta", "tipo": "carro", "foto_url": None, "ano_inicio": 2005, "ano_fim": 2010},
            {"id": 10, "nome": "Onix", "tipo": "carro", "foto_url": "/veiculos/img/modelos/10_bbb.webp",
             "ano_inicio": 2013, "ano_fim": 2019}]
        assert painel_veiculos.modelos(db, 3)[0]["tipo"] == "moto"
        assert painel_veiculos.modelos(db, 4) == []
        assert painel_veiculos.anos(db, 10) == list(range(2019, 2012, -1))  # a LTZ (inativa) não conta
        assert painel_veiculos.versoes(db, 10, 2014) == [{"id": 101, "nome": "LS 1.0 8V FLEX"},
                                                        {"id": 100, "nome": "LT 1.4 8V FLEX"}]
        assert painel_veiculos.versoes(db, 10, 2018) == [{"id": 100, "nome": "LT 1.4 8V FLEX"}]


def test_veiculo_escolhido(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        assert painel_veiculos.veiculo_escolhido(db, 10, 2018, 100) == {"modelo": "ONIX",
                                                                       "texto": "Chevrolet Onix 2018 LT 1.4 8V FLEX"}
        assert painel_veiculos.veiculo_escolhido(db, 10, 2018) == {"modelo": "ONIX", "texto": "Chevrolet Onix 2018"}
        assert painel_veiculos.veiculo_escolhido(db, 40, 1990) is None  # modelo inativo
        assert painel_veiculos.veiculo_escolhido(db, 999, 2018) is None
