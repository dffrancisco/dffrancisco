import json

from helper.topcar import Estatisticas, carregar, vocabulario_carros


class WayapFalso:
    def produtos(self):
        return [{"cod_produto": 1, "desc_produto": "CABO VELA GOL", "marca": "GAUSS", "id_marca": 7, "ncm": "85443000",
                 "unidade": "JG", "id_fornecedor": 3, "num_fabricante": "GC5045", "num_fabricante2": None, "cod_barra": "7898252655139"},
                {"cod_produto": 2, "desc_produto": "CABO VELA PALIO", "marca": "GAUSS", "id_marca": 7, "ncm": "85443000",
                 "unidade": "JG", "id_fornecedor": 3, "num_fabricante": "GC4269", "num_fabricante2": "", "cod_barra": None},
                {"cod_produto": 3, "desc_produto": "LANTERNA TRASEIRA LOGAN", "marca": "ARTEB", "id_marca": 2, "ncm": "85122022",
                 "unidade": "PC", "id_fornecedor": 4, "num_fabricante": "0460447", "num_fabricante2": None, "cod_barra": None}]

    def chamar(self, rota, call, **k):
        return {"getMarca": [{"id_marca": 7, "descricao": "GAUSS"}, {"id_marca": 2, "descricao": "ARTEB"}],
                "getCarro": [{"id_carro": 1, "descricao": "GOL"}, {"id_carro": 2, "descricao": "Corsa Wagon"},
                             {"id_carro": 3, "descricao": "UNIVERSAL"}]}[call]


def test_carregar_grava_cache_e_reusa(tmp_path):
    cache = tmp_path / "topcar.json"
    dados = carregar(cache=cache, wayap=WayapFalso())
    assert len(dados["produtos"]) == 3 and cache.exists()
    cache.write_text(json.dumps({"marcas": [], "carros": [], "produtos": []}), encoding="utf-8")
    assert carregar(cache=cache, wayap=None)["produtos"] == []  # sem renovar, lê o cache e não chama o Wayap


def test_vocabulario_carros_normaliza():
    dados = carregar(cache=None, wayap=WayapFalso())
    assert vocabulario_carros(dados) == {"GOL": "GOL", "CORSA WAGON": "CORSA WAGON", "UNIVERSAL": "UNIVERSAL"}


def test_estatisticas_ncm_e_unidade():
    e = Estatisticas(WayapFalso().produtos())
    assert e.ncm("CABO VELA", "GAUSS") == "85443000"
    assert e.ncm("CABO VELA", "MARCA SEM HISTORICO") == "85443000"   # cai para o tipo sem marca
    assert e.ncm("LANTERNA TRASEIRA", "ARTEB") == "85122022"
    assert e.ncm("PARAFUSO", "ARTEB") == "85122022"                  # cai para a marca sem tipo
    assert e.ncm("PARAFUSO", "NINGUEM") is None
    assert e.unidade("GAUSS") == "JG" and e.unidade("NINGUEM") is None
