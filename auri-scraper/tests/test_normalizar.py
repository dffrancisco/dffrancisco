from helper.normalizar import (codigos_kit, desc_completa, desc_curta, normalizar_codigo, normalizar_ean,
                               so_zeros_diferem, tipo_peca, unidade_sugerida)


def test_codigo_mantem_zero_a_esquerda():
    assert normalizar_codigo("0160818") == "0160818"
    assert normalizar_codigo(" 0460447 ") == "0460447"


def test_codigo_tira_separadores_e_acentos_mas_nao_zeros():
    assert normalizar_codigo("DNI 0610") == "DNI0610"
    assert normalizar_codigo("2779-sampel") == "2779SAMPEL"
    assert normalizar_codigo("GS.2116") == "GS2116"
    assert normalizar_codigo("0001") == "0001"


def test_codigo_kit_preserva_barra_e_desmembra():
    assert normalizar_codigo("GS2116 / GS2118") == "GS2116/GS2118"
    assert codigos_kit("GS2116/GS2118") == ["GS2116", "GS2118"]
    assert codigos_kit("GS2116") == []
    assert normalizar_codigo("0460361 + 0460362") == "0460361/0460362"


def test_codigo_vazio():
    assert normalizar_codigo(None) == ""
    assert normalizar_codigo(" - ") == ""


def test_so_zeros_diferem():
    assert so_zeros_diferem("0160818", "160818")
    assert not so_zeros_diferem("0160818", "0160819")
    assert not so_zeros_diferem("160818", "160818")  # iguais não é "diferem"


def test_ean():
    assert normalizar_ean("7898252655139") == "7898252655139"
    assert normalizar_ean("07898252655139") == "7898252655139"
    assert normalizar_ean("1234567890123") is None
    assert normalizar_ean(None) is None


def test_desc_curta_tira_marca_codigo_e_conectivos():
    nome = "KIT PROTETOR CORREIA DENTADA 0106006 2M PLASTIC - FIAT PALIO"
    assert desc_curta(nome, marca="2M PLASTIC", codigo="0106006") == "KIT PROTETOR CORREIA DENTADA"
    assert desc_curta("Jogo Cabo De Vela - Gauss - Gc5045", marca="Gauss", codigo="GC5045") == "JOGO CABO VELA"


def test_desc_curta_corta_em_45_na_fronteira_da_palavra():
    nome = "Tomada Polarizada 12v Com Potência Máxima De 120w Para Toyota Corolla E Etios - Dni - Dni 0610"
    d = desc_curta(nome, marca="DNI", codigo="DNI 0610")
    assert len(d) <= 45 and not d.endswith(" ") and d == "TOMADA POLARIZADA 12V POTENCIA MAXIMA 120W"


def test_desc_completa_limita_400():
    assert len(desc_completa("x" * 500)) == 400
    assert desc_completa("  Lanterna  ") == "Lanterna"


def test_tipo_peca():
    assert tipo_peca("JOGO CABO VELA") == "CABO VELA"
    assert tipo_peca("LANTERNA TRASEIRA LOGAN 10/13 LE") == "LANTERNA TRASEIRA"
    assert tipo_peca("KIT") == ""


def test_unidade():
    assert unidade_sugerida("JOGO CABO VELA") == "JG"
    assert unidade_sugerida("KIT PROTETOR") == "KT"
    assert unidade_sugerida("PAR LANTERNA") == "PA"
    assert unidade_sugerida("LANTERNA TRASEIRA", moda_marca="JG") == "JG"
    assert unidade_sugerida("LANTERNA TRASEIRA") == "PC"
