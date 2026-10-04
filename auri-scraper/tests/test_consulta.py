from helper.banco import abrir
from helper.consulta import cobertura, ids_por_veiculo, normalizar_busca, peca_completa, pecas_por_veiculo, por_codigo, por_ean


def _db(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'ARTEB', 'reposicao')")
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, ean, desc_curta, status) VALUES (1, 1, 'ARTEB|0160818', '0160818', '7898252655139', 'FAROL', 'ativa')")
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, ean, desc_curta, status) VALUES (2, 1, 'ARTEB|160818X', '160818X', NULL, 'FAROL', 'ativa')")
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, ean, desc_curta, status) VALUES (3, 1, 'ARTEB|9', '9', NULL, 'VELHA', 'inativa')")
    db.execute("INSERT INTO codigo_alternativo (id_peca, tipo, valor) VALUES (1, 'original', '265552690R')")
    db.execute("INSERT INTO codigo_alternativo (id_peca, tipo, valor) VALUES (1, 'ean', '7898252655979')")
    db.execute("INSERT INTO aplicacao (id_peca, montadora, modelo, ano_inicio, ano_fim) VALUES (1, 'RENAULT', 'LOGAN', 2010, 2013)")
    db.execute("INSERT INTO foto (id_peca, ordem, arquivo, origem_tipo, publicavel) VALUES (1, 1, 'a.jpg', 'loja', 1)")
    db.execute("INSERT INTO foto (id_peca, ordem, arquivo, origem_tipo, publicavel) VALUES (1, 2, 'b.jpg', 'loja', 0)")
    db.commit()
    return db


def test_normalizar_busca():
    assert normalizar_busca(" 0160-818 ") == "0160818" and normalizar_busca("dni 0610") == "DNI0610"
    assert normalizar_busca("gs2116 / gs2118") == "GS2116/GS2118"


def test_por_codigo_exato_alternativo_e_zero_a_esquerda(tmp_path):
    db = _db(tmp_path)
    assert por_codigo(db, "0160818") == [1]
    assert por_codigo(db, "265552690r") == [1]          # código original, minúsculas
    assert por_codigo(db, "160818") == [1]              # sem o zero: tolerância só na busca
    assert db.execute("SELECT codigo FROM peca WHERE id_peca=1").fetchone()[0] == "0160818"  # dado intocado
    assert por_codigo(db, "9") == []                    # inativa não aparece
    assert por_codigo(db, "") == []


def test_por_ean(tmp_path):
    db = _db(tmp_path)
    assert por_ean(db, "7898252655139") == [1] and por_ean(db, "07898252655979") == [1] and por_ean(db, "123") == []


def test_peca_completa_sem_origem_e_so_fotos_publicaveis(tmp_path):
    p = peca_completa(_db(tmp_path), 1)
    assert p["marca"] == "ARTEB" and p["codigo"] == "0160818"
    assert p["aplicacoes"] == [{"montadora": "RENAULT", "modelo": "LOGAN", "ano_inicio": 2010, "ano_fim": 2013, "motor": None, "observacao": None}]
    assert [f["arquivo"] for f in p["fotos"]] == ["a.jpg"]
    assert p["alternativos"] == [{"tipo": "ean", "valor": "7898252655979"}, {"tipo": "original", "valor": "265552690R"}]
    assert "origem" not in p and "origens" not in p


def test_cobertura(tmp_path):
    db = _db(tmp_path)
    produtos = [{"marca": "ARTEB", "num_fabricante": "0160818", "num_fabricante2": None, "cod_barra": None},
                {"marca": "ARTEB", "num_fabricante": "ZZZ", "num_fabricante2": None, "cod_barra": "7898252655139"},
                {"marca": "ARTEB", "num_fabricante": "NAO", "num_fabricante2": None, "cod_barra": None},
                {"marca": "COFRAN", "num_fabricante": "160818X", "num_fabricante2": None, "cod_barra": None}]
    assert cobertura(db, produtos) == {"ARTEB": {"total": 3, "por_ean": 1, "por_codigo": 1, "nao_encontrados": 1},
                                       "COFRAN": {"total": 1, "por_ean": 0, "por_codigo": 1, "nao_encontrados": 0}}


def _db_veiculo(tmp_path):
    db = abrir(tmp_path / "v.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'FREMAX', 'reposicao')")
    for id_peca, desc, foto, fontes in [(1, "TAMBOR FREIO", 1, 5), (2, "TAMBOR FREIO", 0, 9), (3, "PASTILHA FREIO", 0, 1),
                                        (4, "TAMBOR FREIO", 0, 2), (5, "TAMBOR FREIO", 1, 1), (6, "TAMBOR FREIO", 1, 3)]:
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, tem_foto, qtd_fontes, status) "
                   "VALUES (?, 1, ?, ?, ?, ?, ?, 'ativa')", (id_peca, f"F|{id_peca}", str(id_peca), desc, foto, fontes))
    db.execute("UPDATE peca SET status = 'inativa' WHERE id_peca = 6")
    db.executemany("INSERT INTO peca_veiculo VALUES (?, ?, ?, ?, ?, ?)", [
        (1, 10, None, 2020, 2022, "versao"),   # todas as versões
        (2, 10, 100, 2021, 2021, "versao"),    # só a versão 100
        (3, 10, None, None, None, "modelo"),   # texto, qualquer ano
        (4, 10, None, 2015, 2019, "modelo"),   # texto, outros anos
        (5, 10, 200, 2021, 2021, "versao"), (5, 10, None, 2010, 2012, "versao"),
        (6, 10, None, 2020, 2022, "versao")])  # peça inativa
    db.commit()
    return db


def test_confianca_sem_versao(tmp_path):
    assert ids_por_veiculo(_db_veiculo(tmp_path), 10, 2021) == {1: "todas_versoes", 2: "algumas_versoes", 3: "modelo_ano",
                                                                 5: "algumas_versoes"}


def test_confianca_com_versao_tira_quem_o_karhub_diz_que_nao_serve(tmp_path):
    db = _db_veiculo(tmp_path)
    assert ids_por_veiculo(db, 10, 2021, 100) == {1: "versao", 2: "versao", 3: "modelo_ano"}
    assert ids_por_veiculo(db, 10, 2021, 200) == {1: "versao", 3: "modelo_ano", 5: "versao"}
    assert ids_por_veiculo(db, 10, 2016) == {3: "modelo_ano", 4: "modelo_ano"}
    assert ids_por_veiculo(db, 99, 2021) == {}


def test_pecas_por_veiculo_texto_ordem_e_limite(tmp_path):
    db = _db_veiculo(tmp_path)
    r = pecas_por_veiculo(db, 10, 2021, texto="tambor")
    assert [p["id_peca"] for p in r] == [1, 5, 2]  # todas_versoes; depois algumas_versoes com foto antes
    assert r[0]["marca"] == "FREMAX" and r[0]["confianca"] == "todas_versoes" and "origem" not in r[0]
    assert [p["id_peca"] for p in pecas_por_veiculo(db, 10, 2021, texto="pastilha")] == [3]
    assert len(pecas_por_veiculo(db, 10, 2021, limite=1)) == 1
    assert pecas_por_veiculo(db, 99, 2021) == []
