import json

from helper.banco import abrir, ler_meta
from helper.montadoras import Montadoras
from helper.veiculos import carregar_arvore
from helper.veiculos_ligar import Arvore, agrupar, atualizar_hashes_modelos, faixas, juntar_faixas, ligar, ligar_versao
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
    return [tuple(l) for l in db.execute("SELECT id_versao, ano_inicio, ano_fim, nivel FROM vei_peca WHERE id_peca = ? "
                                         "ORDER BY id_versao IS NOT NULL, id_versao, ano_inicio", (id_peca,))]


def test_ligar_nivel_versao(tmp_path):
    db, compat = _base(tmp_path)
    r = ligar_versao(db, Arvore(db), compat)
    v4x2 = db.execute("SELECT id_versao FROM vei_versao WHERE nome LIKE '4X2%'").fetchone()[0]
    assert _linhas(db, 1) == [(None, 2020, 2021, "versao")]
    assert _linhas(db, 2) == [(None, 2020, 2020, "versao"), (v4x2, 2021, 2021, "versao")]
    assert _linhas(db, 3) == []  # peça inativa
    assert r["ids_desconhecidos"] == 1 and r["pecas_nivel_versao"] == 2
    assert {i[1] for i in db.execute("PRAGMA index_list(vei_peca)")} >= {"vei_peca_id_peca", "vei_peca_modelo"}


def test_sem_arquivo_de_compatibilidade(tmp_path):
    db, _ = _base(tmp_path)
    r = ligar_versao(db, Arvore(db), tmp_path / "nao_existe.jsonl")
    assert r["pecas_nivel_versao"] == 0 and r["handles_sem_compat"] == 3  # p3 é de peça inativa: nem entra


def test_tipo_entra_no_hash_do_modelo(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, [_linha()], Montadoras({}))
    atualizar_hashes_modelos(db)
    db.execute("UPDATE vei_modelo SET tipo = 'pesado'")
    assert atualizar_hashes_modelos(db) == 1  # o ajuste de tipo chega ao Wayap na próxima publicação


def test_juntar_faixas():
    assert juntar_faixas([(1996, 1998), (1999, 2001), (2005, 2006)]) == [(1996, 2001), (2005, 2006)]
    assert juntar_faixas([(1996, 1998), (None, None)]) == [(1996, 1998)]  # sem ano não engole a faixa datada
    assert juntar_faixas([(None, None), (None, None)]) == [(None, None)]
    assert juntar_faixas([(2005, None), (2000, 2004)]) == [(2000, None)]
    assert juntar_faixas([(None, 1999), (1998, 2003)]) == [(None, 2003)]


def test_ligar_completo_nivel_modelo_e_fechamento(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    m = Montadoras({"VW": "VOLKSWAGEN"})
    carregar_arvore(db, [_linha(), _linha(montadora="Volkswagen", mh="volkswagen", modelo="Gol"),
                         _linha(montadora="Ford", mh="ford", modelo="Ka"), _linha(montadora="Kia", mh="kia", modelo="Ka")], m)
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'X', 'reposicao')")
    for i in range(1, 7):
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?, 1, ?, ?, 'PECA', 'ativa')",
                   (i, f"X|{i}", str(i)))
    db.execute("UPDATE peca SET status = 'inativa' WHERE id_peca = 6")
    db.executemany("INSERT INTO aplicacao (id_peca, montadora, modelo, ano_inicio, ano_fim) VALUES (?, ?, ?, ?, ?)", [
        (1, "VW", "GOL G4", 2006, 2008), (1, "VOLKSWAGEN", "GOL", 2009, 2010),  # junta em 2006-2010
        (2, None, "GOL", 2001, 2000),                                           # sem montadora, nome único; anos invertidos
        (3, None, "KA", 2010, 2012),                                            # sem montadora, KA em Ford e Kia: ambíguo
        (4, "CHEVROLET", "TRACKER", 2021, 2021),                                # já confirmado pelo KarHub
        (5, "FORD", "FIESTA", 2010, 2012),                                      # montadora na árvore, modelo não
        (6, "VW", "GOL", 2000, 2001)])                                          # peça inativa
    db.execute("INSERT INTO origem (id_peca, site, url) VALUES (4, 'karhub', 'https://www.karhub.com.br/p/p4')")
    db.commit()
    compat = tmp_path / "compat.jsonl"
    compat.write_text(json.dumps({"handle": "p4", "ids": ["5"]}) + "\n", encoding="utf-8")
    r, sem_modelo = ligar(db, compat, m)
    gol = db.execute("SELECT id_modelo FROM vei_modelo WHERE nome = 'GOL'").fetchone()[0]

    def linhas_de(p):
        return [tuple(l) for l in db.execute("SELECT id_modelo, id_versao, ano_inicio, ano_fim, nivel FROM vei_peca WHERE id_peca = ?", (p,))]
    assert linhas_de(1) == [(gol, None, 2006, 2010, "modelo")]
    assert linhas_de(2) == [(gol, None, 2000, 2001, "modelo")]
    assert linhas_de(3) == [] and linhas_de(5) == [] and linhas_de(6) == []
    assert [l[4] for l in linhas_de(4)] == ["versao"]  # o texto não repete o que o KarHub confirmou
    assert sem_modelo["KA"] == 1 and sem_modelo["FORD FIESTA"] == 1
    assert r["pecas_nivel_versao"] == 1 and r["pecas_nivel_modelo"] == 2 and r["pecas_ligadas"] == 3
    assert db.execute("SELECT qtd_pecas FROM vei_modelo WHERE id_modelo = ?", (gol,)).fetchone()[0] == 2
    assert db.execute("SELECT qtd_pecas FROM vei_montadora WHERE nome = 'VOLKSWAGEN'").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM vei_peca_estado").fetchone()[0] == 3
    assert ler_meta(db, "veiculos_em")
    assert db.execute("SELECT count(*) FROM vei_modelo WHERE hash_conteudo IS NULL").fetchone()[0] == 0
    hashes_pecas = dict(db.execute("SELECT id_peca, hash FROM vei_peca_estado"))
    hashes_modelos = dict(db.execute("SELECT id_modelo, hash_conteudo FROM vei_modelo"))
    r2, _ = ligar(db, compat, m)  # mesma entrada: mesmos hashes, nenhum modelo alterado
    assert dict(db.execute("SELECT id_peca, hash FROM vei_peca_estado")) == hashes_pecas
    assert dict(db.execute("SELECT id_modelo, hash_conteudo FROM vei_modelo")) == hashes_modelos
    assert r2["modelos_alterados"] == 0


def test_karhub_contestado_pelo_texto_dos_outros_sites_vira_nivel_modelo(tmp_path):
    """A KarHub diz que a peça serve em Chevrolet e Volkswagen; os outros sites, listando veículos, só citam Chevrolet:
    o que é só da KarHub (Gol) cai para 'confira a versão'. Texto que veio do próprio KarHub não conta como conferência."""
    db = abrir(tmp_path / "h.sqlite")
    m = Montadoras({"VW": "VOLKSWAGEN"})
    carregar_arvore(db, [_linha(), _linha(montadora="Volkswagen", mh="volkswagen", modelo="Gol")], m)
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'X', 'reposicao')")
    for i in (7, 8, 9):
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?, 1, ?, ?, 'PECA', 'ativa')",
                   (i, f"X|{i}", str(i)))
        db.execute("INSERT INTO origem (id_peca, site, url) VALUES (?, 'karhub', ?)", (i, f"https://www.karhub.com.br/p/p{i}"))
    db.executemany("INSERT INTO aplicacao (id_peca, montadora, modelo, ano_inicio, ano_fim, de_karhub) VALUES (?, ?, ?, ?, ?, ?)", [
        (7, "CHEVROLET", "TRACKER", 2021, 2021, 0),   # outro site cita só Chevrolet
        (8, "VOLKSWAGEN", "GOL", 2020, 2021, 1),      # só o texto do próprio KarHub: não confere nada
        (9, None, "GOL", 2020, 2020, 0)])             # outro site cita o Gol: confirma
    db.commit()
    compat = tmp_path / "compat.jsonl"
    todos = ["62329", "62330", "5", "volkswagen-Gol-62329", "volkswagen-Gol-62330", "volkswagen-Gol-5"]
    compat.write_text("".join(json.dumps({"handle": f"p{i}", "ids": todos}) + "\n" for i in (7, 8, 9)), encoding="utf-8")
    r, _ = ligar(db, compat, m)
    gol = db.execute("SELECT id_modelo FROM vei_modelo WHERE nome = 'GOL'").fetchone()[0]
    tracker = db.execute("SELECT id_modelo FROM vei_modelo WHERE nome = 'TRACKER'").fetchone()[0]

    def linhas_de(p):
        return sorted(tuple(l) for l in db.execute("SELECT id_modelo, id_versao, ano_inicio, ano_fim, nivel FROM vei_peca "
                                                   "WHERE id_peca = ?", (p,)))
    assert linhas_de(7) == sorted([(tracker, None, 2020, 2021, "versao"), (gol, None, 2020, 2021, "modelo")])
    assert linhas_de(8) == sorted([(tracker, None, 2020, 2021, "versao"), (gol, None, 2020, 2021, "versao")])
    assert linhas_de(9) == sorted([(gol, None, 2020, 2021, "versao"), (tracker, None, 2020, 2021, "modelo")])
    assert r["pares_contestados"] == 2  # peça 7 (Gol) e peça 9 (Tracker)
