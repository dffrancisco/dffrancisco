import json
from pathlib import Path

import pytest
import requests

import catalogo_takao
from catalogo_takao import codigo, registros

# modelos reais da API do portal Takao (só os campos usados)
PRODUTOS = {p["Modelo"]: p for p in json.loads((Path(__file__).parent / "dados/takao_produtos.json").read_text(encoding="utf-8"))}
FOTO = "https://takao.blob.core.windows.net/images-mult-prod/750/"


def test_cada_medida_vira_uma_linha_com_o_codigo_junto_e_a_mesma_url():
    assert list(registros(PRODUTOS["P VW 14"])) == [
        {"site": "takao", "url": "https://portal.takao.com.br/detalhe/2856e9ab-23c0-49ed-a119-f690a7d330e5",
         "nome": f"Pistão (JG) {medida} - Takao P VW 14", "marca": "TAKAO", "codigo_fabricante": cod, "ean": None,
         "carro": "VOLKSWAGEN FLEX 1.4L 8V L4 SOHC MI KOMBI APÓS 06", "imagens": [FOTO + "P%20VW%2014/0.jpg"]}
        for medida, cod in (("STD", "PVW14STD"), ("0,50", "PVW14050"), ("1,00", "PVW14100"))]


def test_medida_com_zero_a_esquerda_fica_como_texto():
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["AS LA 16"])] == ["ASLA16040", "ASLA16060"]


def test_modelo_sem_medida_fica_so_com_o_codigo_do_modelo():
    [r] = registros(PRODUTOS["RT RE 18"])
    assert r["codigo_fabricante"] == "RTRE18"
    assert r["nome"] == "Retentor Traseiro - Takao RT RE 18"
    # "/0" e "/0.jpg" são fotos diferentes (na biela B D 18, a "/0.jpg" é o desenho com as medidas)
    assert r["imagens"] == [FOTO + "RT%20RE%2018/0", FOTO + "RT%20RE%2018/0.jpg"]
    assert r["carro"] == "GASOLINA RENAULT/VOLVO 1.4/1.6/1.8/2.0L AUDI/GM/PEUGEOT"


def test_traco_ao_lado_de_medida_e_a_variacao_sem_medida_e_as_fotos_ficam_na_ordem_da_api():
    regs = list(registros(PRODUTOS["B D 18"]))
    assert [(r["codigo_fabricante"], r["nome"]) for r in regs] == [
        ("BD18STD", "Biela (cada) STD - Takao B D 18"), ("BD18", "Biela (cada) - Takao B D 18")]
    assert regs[0]["imagens"] == [FOTO + f"B%20D%2018/{f}" for f in ("0", "0.jpg", "1.jpg", "2.jpg")]


def test_imagem_coringa_nao_e_foto_do_produto():
    regs = list(registros(PRODUTOS["AS GM 31"]))
    assert [r["codigo_fabricante"] for r in regs] == ["ASGM31STD", "ASGM31050", "ASGM31075"]
    assert all(r["imagens"] == [] for r in regs)


def test_codigo_tira_so_espaco_e_virgula():
    assert codigo("JCB TO 25D-4", None) == "JCBTO25D-4"
    assert codigo("BB FI 10", "0,25") == "BBFI10025"
    assert codigo("PC VW 16", "-") == "PCVW16"


def test_aplicacao_vazia_fica_sem_carro():
    produto = dict(PRODUTOS["RT RE 18"], Aplicacao="  ")
    assert next(registros(produto))["carro"] is None


def _lote(*ids):
    return [{"Id": i} for i in ids]


def test_paginas_pedem_um_a_mais_para_nunca_passar_do_fim_e_juntam_sem_repetir(monkeypatch):
    # a API demora minutos e não responde quando o Skip passa do fim: só se pede a próxima página quando a
    # atual trouxe o item extra, que prova que ela existe
    monkeypatch.setattr(catalogo_takao, "POR_PAGINA", 3)
    paginas = {0: _lote("a", "b", "c", "d"), 3: _lote("d", "e", "f", "g"), 6: _lote("g", "h")}
    pedidos = []

    def buscar(skip, take):
        pedidos.append((skip, take))
        return paginas[skip]
    assert [m["Id"] for m in catalogo_takao.modelos(buscar)] == list("abcdefgh")
    assert pedidos == [(0, 4), (3, 4), (6, 4)]


def test_pagina_exata_para_sem_pedir_alem_do_fim(monkeypatch):
    monkeypatch.setattr(catalogo_takao, "POR_PAGINA", 3)
    pedidos = []

    def buscar(skip, take):
        pedidos.append(skip)
        return _lote("a", "b", "c") if skip == 0 else pytest.fail("pediu além do fim")
    assert [m["Id"] for m in catalogo_takao.modelos(buscar)] == ["a", "b", "c"]
    assert pedidos == [0]


class _Resposta:
    def __init__(self, status, corpo):
        self.status_code, self._corpo = status, corpo

    def json(self):
        return json.loads(self._corpo)


class _Sessao:
    """Responde em ordem; uma exceção na lista é levantada no lugar da resposta."""
    def __init__(self, respostas):
        self.respostas, self.pedidos, self.headers = respostas, [], {}

    def post(self, url, json=None, timeout=None):
        self.pedidos.append((url, json))
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def rede(monkeypatch):
    esperas = []
    monkeypatch.setattr(catalogo_takao.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_takao, "INTERVALO", 0)
    monkeypatch.setattr(catalogo_takao, "_sessao", None)

    def usar(respostas):
        sessao = _Sessao(respostas)
        monkeypatch.setattr(catalogo_takao.requests, "Session", lambda: sessao)
        return sessao
    return usar, esperas


def test_timeout_e_erro_500_sao_tentados_de_novo(rede):
    usar, esperas = rede
    sessao = usar([requests.Timeout("lenta"), _Resposta(500, ""), _Resposta(200, '{"Success": true, "Result": [{"Id": "x"}]}')])
    assert catalogo_takao.pagina(200, 101) == [{"Id": "x"}]
    assert esperas == [5, 15]
    assert sessao.pedidos[0] == (catalogo_takao.API, {"ClienteId": "", "SKU": "", "Take": 101, "Skip": 200})


def test_resposta_sem_sucesso_tambem_e_tentada_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(200, '{"Success": false, "Result": null}'), _Resposta(200, '{"Success": true, "Result": []}')])
    assert catalogo_takao.pagina(0, 101) == []
    assert esperas == [5]


def test_erro_4xx_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404, "")])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_takao.pagina(0, 101)
    assert esperas == []


def test_desiste_depois_de_todas_as_esperas(rede):
    usar, esperas = rede
    usar([requests.ConnectionError("recusada")] * (len(catalogo_takao.ESPERAS) + 1))
    with pytest.raises(RuntimeError, match="recusada"):
        catalogo_takao.pagina(0, 101)
    assert esperas == list(catalogo_takao.ESPERAS)
