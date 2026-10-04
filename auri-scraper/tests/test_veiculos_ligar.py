import json

from helper.banco import abrir
from helper.montadoras import Montadoras
from helper.veiculos import carregar_arvore
from helper.veiculos_ligar import Arvore, agrupar, faixas, ligar_versao
from tests.test_veiculos import _linha


def test_faixas_contam_so_os_anos_do_universo():
    assert faixas({2010, 2011, 2013}, [2010, 2011, 2013]) == [(2010, 2013)]  # 2012 não existe: não quebra
    assert faixas({2010, 2013}, [2010, 2011, 2013]) == [(2010, 2010), (2013, 2013)]
    assert faixas(set(), [2010]) == []


def test_ano_completo_vira_todas_as_versoes():
    versoes_por_ano = {2020: {1, 2}, 2021: {1, 2}, 2022: {1, 3}}
    anos_por_versao = {1: [2020, 2021, 2022], 2: [2020, 2021], 3: [2022]}
    assert agrupar(versoes_por_ano, anos_por_versao, {2020: {1, 2}, 2021: {1, 2}, 2022: {1}}) == [(None, 2020, 2021), (1, 2022, 2022)]


def test_versao_em_anos_nao_seguidos():
    versoes_por_ano = {2018: {1, 2}, 2019: {1, 2}, 2021: {1, 2}}
    anos_por_versao = {1: [2018, 2019, 2021], 2: [2018, 2019, 2021]}
    assert agrupar(versoes_por_ano, anos_por_versao, {a: {1, 2} for a in (2018, 2019, 2021)}) == [(None, 2018, 2021)]
    assert agrupar(versoes_por_ano, anos_por_versao, {2018: {2}, 2021: {2}}) == [(2, 2018, 2018), (2, 2021, 2021)]


def _base(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, [_linha()], Montadoras({}))  # Tracker: 2021 {62329 4x2, 62330 Lt}, 2020 {5 Lt}
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'X', 'reposicao')")
    for i in (1, 2, 3):
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?, 1, ?, ?, 'PECA', 'ativa')",
                   (i, f"X|{i}", str(i)))
    db.execute("UPDATE peca SET status = 'inativa' WHERE id_peca = 3")
    for id_peca, url in [(1, "https://www.karhub.com.br/p/p1"), (2, "https://www.karhub.com.br/p/p2a"),
                         (2, "https://www.karhub.com.br/p/p2b?Lado=Direito"), (3, "https://www.karhub.com.br/p/p3")]:
        db.execute("INSERT INTO origem (id_peca, site, url) VALUES (?, 'karhub', ?)", (id_peca, url))
    db.commit()
    compat = tmp_path / "compat.jsonl"
    compat.write_text("\n".join(json.dumps(l) for l in [
        {"handle": "p1", "ids": ["62329", "62330", "5", "999999"]},  # tudo do Tracker + um id fora da árvore
        {"handle": "p2a", "ids": ["62329"]}, {"handle": "p2b", "ids": ["5"]},  # mesma peça, dois anúncios
        {"handle": "p1", "ids": ["1"]},  # repetida: vale a primeira
        {"handle": "p3", "ids": ["5"]}]) + "\n{cortada", encoding="utf-8")
    return db, compat


def _linhas(db, id_peca):
    return [tuple(l) for l in db.execute("SELECT id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo WHERE id_peca = ? "
                                         "ORDER BY id_versao IS NOT NULL, id_versao, ano_inicio", (id_peca,))]


def test_ligar_nivel_versao(tmp_path):
    db, compat = _base(tmp_path)
    r = ligar_versao(db, Arvore(db), compat)
    v4x2 = db.execute("SELECT id_versao FROM veiculo_versao WHERE nome LIKE '4X2%'").fetchone()[0]
    assert _linhas(db, 1) == [(None, 2020, 2021, "versao")]
    assert _linhas(db, 2) == [(None, 2020, 2020, "versao"), (v4x2, 2021, 2021, "versao")]
    assert _linhas(db, 3) == []  # peça inativa
    assert r["ids_desconhecidos"] == 1 and r["pecas_nivel_versao"] == 2
    assert {i[1] for i in db.execute("PRAGMA index_list(peca_veiculo)")} >= {"peca_veiculo_peca", "peca_veiculo_modelo"}


def test_sem_arquivo_de_compatibilidade(tmp_path):
    db, _ = _base(tmp_path)
    r = ligar_versao(db, Arvore(db), tmp_path / "nao_existe.jsonl")
    assert r["pecas_nivel_versao"] == 0 and r["handles_sem_compat"] == 3  # p3 é de peça inativa: nem entra
