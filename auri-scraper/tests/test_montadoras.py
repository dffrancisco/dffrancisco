from helper.montadoras import Montadoras, casar_wayap, nome_canonico


def _montadoras(tmp_path):
    arq = tmp_path / "m.csv"
    arq.write_text("apelido;nome\nKIA;KIA MOTORS\nMERCEDES BENZ;MERCEDES-BENZ\nGM;CHEVROLET\nBMW BMW;BMW\n", encoding="utf-8")
    return Montadoras.carregar(arq)


def test_nome_canonico():
    assert nome_canonico("  Citroën  C4 ") == "CITROEN C4"
    assert nome_canonico(None) == ""


def test_canonica_usa_apelidos_e_normaliza(tmp_path):
    m = _montadoras(tmp_path)
    assert m.canonica("Kia") == "KIA MOTORS"
    assert m.canonica("Mercedes Benz") == "MERCEDES-BENZ" and m.canonica("MERCEDES-BENZ") == "MERCEDES-BENZ"
    assert m.canonica("gm") == "CHEVROLET" and m.canonica("BMW BMW") == "BMW"
    assert m.canonica("Caoa Chery") == "CAOA CHERY"  # sem apelido: maiúsculas sem acento
    assert m.canonica("") is None and m.canonica(None) is None


def test_chaves_do_nome_como_veio_e_canonico(tmp_path):
    assert _montadoras(tmp_path).chaves("Kia") == {"KIA", "KIAMOTORS"}
    assert _montadoras(tmp_path).chaves("") == set()


def test_casar_wayap_por_letras_e_numeros():
    wayap = [(43, "MERCEDES-BENZ"), (34, "KIA MOTORS"), (11, "CHEVROLET")]
    assert casar_wayap("MERCEDES BENZ", wayap) == 43
    assert casar_wayap("KIA MOTORS", wayap) == 34
    assert casar_wayap("CAOA CHERY", wayap) is None
    assert casar_wayap("", wayap) is None


def test_arquivo_do_repositorio_tem_os_apelidos_da_spec():
    m = Montadoras.carregar()
    for apelido, nome in [("KIA", "KIA MOTORS"), ("JAC", "JAC MOTORS"), ("ASIA", "ASIA MOTORS"),
                          ("MERCEDES BENZ", "MERCEDES-BENZ"), ("GM", "CHEVROLET"), ("VW", "VOLKSWAGEN"), ("BMW BMW", "BMW")]:
        assert m.canonica(apelido) == nome
