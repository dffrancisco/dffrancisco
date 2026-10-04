import pytest

from helper.veiculo_tipo import carregar_ajustes, chaves_marca_fipe, classificar, indexar_fipe, normalizar

# nomes no formato da API da FIPE (parallelum)
FIPE = {
    "carros": {"GM - Chevrolet": ["Tracker LT 1.0 Turbo 12V Flex Aut.", "ONIX HATCH LT 1.0 12V Flex 5p Mec."],
               "Honda": ["Civic Sedan EXL 2.0 Flex 16V Aut.4p"], "Agrale": ["MARRUÁ AM 200 2.8 CS TDI Diesel"],
               "Mercedes-Benz": ["A 200 Style 1.6 Turbo 16V"]},
    "motos": {"HONDA": ["CG 160 FAN"]},
    "caminhoes": {"Mercedes-Benz": ["L-1620 6x2 2p (diesel)"], "Agrale": ["MARRUÁ AM 200 CD 4x4 TDI Diesel"]},
}
IDX = indexar_fipe(FIPE)


def test_normalizar_e_chaves_da_marca_fipe():
    assert normalizar("Cr-v  EXL") == "CR V EXL"
    assert chaves_marca_fipe("GM - Chevrolet") == {"GMCHEVROLET", "GM", "CHEVROLET"}
    assert chaves_marca_fipe("Caoa Chery/Chery") == {"CAOACHERYCHERY", "CAOACHERY", "CHERY"}
    assert chaves_marca_fipe("Mercedes-Benz") == {"MERCEDESBENZ"}


def test_fipe_decide_quando_conhece_o_modelo():
    assert classificar({"CHEVROLET"}, "Tracker", [], IDX, {}) == ("carro", "fipe")
    assert classificar({"HONDA"}, "Civic", [], IDX, {}) == ("carro", "fipe")
    assert classificar({"HONDA"}, "CG 160", [], IDX, {}) == ("moto", "fipe")
    assert classificar({"MERCEDESBENZ"}, "L 1620", [], IDX, {}) == ("pesado", "fipe")
    # em "carros" e em "caminhoes": na dúvida, carro
    assert classificar({"AGRALE"}, "Marrua", [], IDX, {}) == ("carro", "fipe")
    # prefixo só em fronteira de palavra: "ONI" não casa "ONIX HATCH..."
    assert classificar({"CHEVROLET"}, "Oni", [], IDX, {}) == ("carro", "padrao")


def test_versoes_decidem_quando_a_fipe_nao_conhece():
    assert classificar({"HONDA"}, "Biz 100", ["Ks 100cc (6,4 Cv)"], IDX, {}) == ("moto", "versao")
    assert classificar({"MERCEDESBENZ"}, "1214 K", ["4x2 6.0 12v L6 E 1 P 3"], IDX, {}) == ("pesado", "versao")
    assert classificar({"VOLVO"}, "B 12", ["R 6x2 12.0 24v L6 Turbo E 3 P 5 (420 Cv)"], IDX, {}) == ("pesado", "versao")
    assert classificar({"CHEVROLET"}, "D 6000", ["4x2 4.0 8v E 0 P 2"], IDX, {}) == ("pesado", "versao")
    # utilitário diesel leve: fase P com motor pequeno continua carro
    assert classificar({"IVECO"}, "Daily 30 130", ["Furgão 4x2 2.3 16v Turbo E 5 P 6"], IDX, {}) == ("carro", "padrao")
    assert classificar({"HYUNDAI"}, "Hr Hd", ["Cabine Simples 2.5 8v Turbo"], IDX, {}) == ("carro", "padrao")
    # portas ("4p") não são fase de emissão
    assert classificar({"CHEVROLET"}, "Astra Hatch", ["Advantage 4p Aut. 2.0 8v Flex (133 140 Cv)"], IDX, {}) == ("carro", "padrao")


def test_nome_de_onibus():
    assert classificar({"IVECO"}, "Bus 170 S28", [], IDX, {}) == ("pesado", "nome")


def test_ajuste_do_dono_vence_tudo(tmp_path):
    arq = tmp_path / "t.csv"
    arq.write_text("montadora;modelo;tipo\nIveco;Daily 30 130;pesado\nHonda;Civic;moto\n", encoding="utf-8")
    aj = carregar_ajustes(arq)
    assert classificar({"IVECO"}, "Daily 30-130", ["Furgão 4x2 2.3"], IDX, aj) == ("pesado", "ajuste")
    assert classificar({"HONDA"}, "Civic", [], IDX, aj) == ("moto", "ajuste")
    assert carregar_ajustes(tmp_path / "nao_existe.csv") == {}


def test_ajuste_com_tipo_invalido_avisa(tmp_path):
    arq = tmp_path / "t.csv"
    arq.write_text("montadora;modelo;tipo\nIveco;Daily;caminhao\n", encoding="utf-8")
    with pytest.raises(ValueError, match="caminhao"):
        carregar_ajustes(arq)


def test_arquivo_de_ajustes_do_repositorio_carrega():
    assert isinstance(carregar_ajustes(), dict)
