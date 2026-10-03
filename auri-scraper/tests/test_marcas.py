from pathlib import Path

from helper.marcas import Marcas

CSV = Path(__file__).resolve().parents[1] / "helper_marcas.csv"


def test_canonica_por_nome_e_apelido():
    m = Marcas.carregar(CSV)
    assert m.canonica("Universal") == ("UNIVERSAL", "reposicao")
    assert m.canonica("Univel") == ("UNIVERSAL", "reposicao")
    assert m.canonica("universal automotive") == ("UNIVERSAL", "reposicao")
    assert m.canonica("VW") == ("VOLKSWAGEN", "montadora")


def test_desconhecida_e_registrada_e_normalizada():
    m = Marcas.carregar(CSV)
    assert m.canonica("Clic Peças") == ("CLIC PECAS", "desconhecida")
    assert m.canonica("clic pecas") == ("CLIC PECAS", "desconhecida")
    assert m.desconhecidas["CLIC PECAS"] == 2


def test_sem_marca():
    m = Marcas.carregar(CSV)
    assert m.canonica(None) == ("", "desconhecida")
    assert m.canonica("  ") == ("", "desconhecida")
    assert m.desconhecidas.get("") is None


def test_compativeis_usa_regra_do_wayap_fotos():
    m = Marcas.carregar(CSV)
    assert m.compativeis("UNIVERSAL", "UNIVEL")  # apelido -> mesma canônica
    assert m.compativeis("COFAP", "COFAP")
    assert not m.compativeis("COFAP", "COFRAN")
    assert m.compativeis("MONROE AXIOS", "MONROE")  # regra de substring do wayap_fotos


def test_salvar_desconhecidas(tmp_path):
    m = Marcas.carregar(CSV)
    m.canonica("Marca Nova")
    m.salvar_desconhecidas(tmp_path / "desc.csv")
    assert (tmp_path / "desc.csv").read_text(encoding="utf-8").splitlines() == ["marca;ocorrencias", "MARCA NOVA;1"]


def test_csv_de_marcas_usa_quebra_de_linha_lf():
    assert b"\r" not in CSV.read_bytes()
