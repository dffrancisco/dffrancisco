import json
from pathlib import Path

import pytest
import requests

import catalogo_raven
from catalogo_raven import ean_valido, registro, sem_ean_repetido, veiculos

# respostas reais do ravenferramentas.com.br: a API do WordPress (só os campos pedidos) e a página do produto
# recortada na seção do produto (galeria, nome, peso e o link "Encontrar revendedor" com o EAN)
DADOS = Path(__file__).parent / "dados"
PRODUTOS = {p["link"].rstrip("/").rsplit("/", 1)[-1]: p
            for p in json.loads((DADOS / "raven_produtos.json").read_text(encoding="utf-8"))}
TERMOS = {t["id"]: t for t in json.loads((DADOS / "raven_veiculos.json").read_text(encoding="utf-8"))}
FOTO = "https://www.ravenferramentas.com.br/wp-content/uploads/"


def produto(slug, arquivo=None):
    pagina = (DADOS / f"raven_produto_{arquivo or slug}.html").read_text(encoding="utf-8")
    return registro(PRODUTOS[slug], pagina, TERMOS)


def test_produto_com_seis_fotos_e_ean_do_link_de_revendedor():
    nome_foto = "PAR-FERRAMENTAS-SINCRONISMO-CORRENTE-1_8-16V-ETORQ-EVO-FIAT-ARGO-TORO-JEEP-RENEGADE.jpg"
    assert produto("141022") == {
        "site": "raven", "url": "https://www.ravenferramentas.com.br/produtos/ferramenta/141022/",
        "nome": "Ferramenta para Sincronismo Fiat E-Torq Evo 1.8", "marca": "RAVEN", "codigo_fabricante": "141022",
        "ean": "7899942502085", "imagens": [f"{FOTO}2025/08/141022-RAVEN-0{i}-{nome_foto}" for i in range(6)],
        "carro": None}


def test_veiculos_da_taxonomia_viram_montadora_e_modelo():
    r = produto("151501")
    assert r["carro"] == ("Renault Clio 1.0 16V; Renault Mégane 2.0 16V; Renault Mégane 2.0 8V; Renault Scénic 2.0; "
                          "Renault Scénic 2.0 16V")
    assert r["nome"] == "Conjunto Ferramentas Troca Correia Renault 2.0 16V"
    assert r["ean"] == "7898540994711"
    assert len(r["imagens"]) == 3


def test_ferramenta_universal_fica_sem_carro():
    r = produto("100100")
    assert r["carro"] is None
    assert r["nome"] == "Torquimetro de Estalo de 0,3 a 1,2 Kgfm - 3/8"


def test_codigo_com_traco_fica_como_o_fabricante_imprime():
    r = produto("109652-06")
    assert r["codigo_fabricante"] == "109652-06"
    assert r["ean"] == "7898540991871"
    assert r["imagens"][0] == f"{FOTO}2026/05/109652-06-RAVEN-00-ADAPTADOR-TESTE-ARREFECIMENTO-CAMINHAO-ONIBUS-SCANIA-SISTEMA-SELADO.jpg"


def test_general_motors_vira_chevrolet_e_montadora_nao_se_repete_no_modelo():
    assert veiculos(PRODUTOS["811008"]["veiculo"], TERMOS) == (
        "Chevrolet Blazer Maxion 2.5 Diesel; Cross Lander CL224; Land Rover Defender 110; Land Rover Defender 90; "
        "Ford F-1000; Eletra Ônibus Hibrido; Ford Ranger; Matra Rural Matra; Chevrolet S 10 Maxion 2.5 Diesel; "
        "Mercedes Benz Sprinter 310D; Mercedes Benz Sprinter 312")


def test_foto_de_outro_codigo_sai():
    pagina = (DADOS / "raven_produto_151501.html").read_text(encoding="utf-8").replace("151501-RAVEN-03", "151003-RAVEN-03")
    r = registro(PRODUTOS["151501"], pagina, TERMOS)
    assert [u.rsplit("/", 1)[-1][:16] for u in r["imagens"]] == ["151501-RAVEN-00-", "151501-RAVEN-04-"]


def test_ean_invalido_fica_de_fora():
    assert ean_valido("7899942502085") == "7899942502085"
    assert ean_valido("7899942502086") is None  # dígito verificador errado
    assert ean_valido("141022") is None
    assert ean_valido(None) is None


def test_ean_repetido_em_codigos_diferentes_e_descartado():
    regs = [{"codigo_fabricante": "109652-06", "ean": "7898540991871"},
            {"codigo_fabricante": "109652-06", "ean": "7898540991871"},  # mesmo código em dois posts
            {"codigo_fabricante": "141022", "ean": "7899942502085"},
            {"codigo_fabricante": "141023", "ean": "7899942502085"}]
    assert [r["ean"] for r in sem_ean_repetido(regs)] == ["7898540991871", "7898540991871", None, None]


class _Resposta:
    def __init__(self, status, texto="", headers=None):
        self.status_code, self.text, self.headers = status, texto, headers or {}

    def json(self):
        return json.loads(self.text)


class _Sessao:
    """Responde em ordem; uma exceção na lista é levantada no lugar da resposta."""
    def __init__(self, respostas):
        self.respostas, self.urls, self.headers = respostas, [], {}

    def get(self, url, params=None, timeout=None):
        self.urls.append((url, params))
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def esperas(monkeypatch):
    lista = []
    monkeypatch.setattr(catalogo_raven.time, "sleep", lista.append)
    monkeypatch.setattr(catalogo_raven, "INTERVALO", 0)
    return lista


def test_timeout_e_erro_500_sao_tentados_de_novo(esperas):
    sessao = _Sessao([requests.Timeout("lento"), _Resposta(500), _Resposta(200, "[]")])
    assert catalogo_raven.baixar(sessao, "https://www.ravenferramentas.com.br/").text == "[]"
    assert esperas == [5, 15]


def test_erro_4xx_nao_e_tentado_de_novo(esperas):
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_raven.baixar(_Sessao([_Resposta(404)]), "https://www.ravenferramentas.com.br/x/")
    assert esperas == []


def test_lista_da_api_le_todas_as_paginas(esperas):
    sessao = _Sessao([_Resposta(200, '[{"id": 1}, {"id": 2}]', {"X-WP-TotalPages": "2"}),
                      _Resposta(200, '[{"id": 3}]', {"X-WP-TotalPages": "2"})])
    assert [p["id"] for p in catalogo_raven.da_api(sessao, "produto", "id,link")] == [1, 2, 3]
    assert [params["page"] for _, params in sessao.urls] == [1, 2]
