import sqlite3

from helper.banco import VERSAO_ESQUEMA, abrir, id_marca


def test_abrir_cria_tabelas(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    nomes = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"peca", "codigo_alternativo", "aplicacao", "foto", "origem", "marca", "marca_apelido", "carga",
            "fonte_lida", "meta"} <= nomes
    assert db.execute("SELECT valor FROM meta WHERE chave='versao_esquema'").fetchone()[0] == str(VERSAO_ESQUEMA)


def test_abrir_duas_vezes_nao_quebra(tmp_path):
    abrir(tmp_path / "h.sqlite").close()
    db = abrir(tmp_path / "h.sqlite")
    assert db.execute("SELECT count(*) FROM peca").fetchone()[0] == 0


def test_id_marca_cria_e_reaproveita(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    a = id_marca(db, "ARTEB", "reposicao")
    assert id_marca(db, "ARTEB", "reposicao") == a
    assert id_marca(db, "COFRAN", "reposicao") == a + 1
    assert db.execute("SELECT tipo FROM marca WHERE id_marca=?", (a,)).fetchone()[0] == "reposicao"


def test_peca_exige_chave_unica(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    m = id_marca(db, "ARTEB", "reposicao")
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (1, ?, 'ARTEB|0160818', '0160818', 'FAROL', 'ativa')", (m,))
    try:
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (2, ?, 'ARTEB|0160818', '0160818', 'FAROL', 'ativa')", (m,))
        assert False, "deveria violar a chave única"
    except sqlite3.IntegrityError:
        pass


def test_indices_para_busca_tolerante_a_zero_a_esquerda(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    indices = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"peca_codigo_sem_zero", "alt_valor_sem_zero"} <= indices


def test_abrir_espera_quando_outro_processo_escreve(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    assert db.execute("PRAGMA busy_timeout").fetchone()[0] >= 60000
