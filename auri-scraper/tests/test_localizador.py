from helper.localizador import linhas_localizador

PECA = {"id_peca": 7, "desc_curta": "FAROL DIANTEIRO", "desc_completa": "Farol  dianteiro lado esquerdo", "marca": "Arteb",
        "codigo": "0160-818", "ean": "7891234567895", "tipo_peca": "FAROL"}


def test_uma_linha_por_aplicacao_com_os_anos_dela():
    aplicacoes = [
        {"montadora": "VOLKSWAGEN", "modelo": "GOL", "ano_inicio": 2008, "ano_fim": 2013, "motor": "1.0", "observacao": None},
        {"montadora": "VOLKSWAGEN", "modelo": "FOX", "ano_inicio": 2010, "ano_fim": None, "motor": None, "observacao": "lado esquerdo"},
    ]
    linhas = linhas_localizador(PECA, ["16818", "AB-1"], aplicacoes)
    assert [(i, a, b) for i, a, b, _ in linhas] == [(7, 2008, 2013), (7, 2010, None)]
    assert linhas[0][3] == ("FAROL DIANTEIRO FAROL DIANTEIRO LADO ESQUERDO ARTEB 0160-818 16818 AB-1 7891234567895 FAROL "
                            "VOLKSWAGEN GOL 1.0")
    assert linhas[1][3].endswith("FAROL VOLKSWAGEN FOX LADO ESQUERDO")


def test_peca_sem_aplicacao_tem_uma_linha_sem_anos():
    assert linhas_localizador(PECA, [], []) == [
        (7, None, None, "FAROL DIANTEIRO FAROL DIANTEIRO LADO ESQUERDO ARTEB 0160-818 7891234567895 FAROL")]


def test_nulos_acentos_e_espacos():
    peca = {"id_peca": 1, "desc_curta": "PÁRA-CHOQUE", "desc_completa": None, "marca": "Fiat", "codigo": None, "ean": None,
            "tipo_peca": None}
    aplicacao = {"montadora": None, "modelo": "uno  mille", "ano_inicio": None, "ano_fim": None, "motor": None, "observacao": "  traseiro "}
    assert linhas_localizador(peca, [], [aplicacao]) == [(1, None, None, "PARA-CHOQUE FIAT UNO MILLE TRASEIRO")]
