import copy
import json
import threading
from pathlib import Path

import pytest
import requests

import catalogo_altese
from catalogo_altese import registros

# produtos reais da API da Altese (descrição encurtada)
PRODUTOS = {p["productId"]: p for p in json.loads((Path(__file__).parent / "dados/altese_produtos.json").read_text(encoding="utf-8"))}
FOTO = "https://altese.vteximg.com.br/arquivos/ids/"


def test_arteb_mantem_o_codigo_com_zero_e_aplicacao_sem_ano():
    assert list(registros(PRODUTOS["2015410"])) == [{
        "site": "altese", "url": "https://www.altese.com.br/0160708-farol-lado-direito-uno/p",
        "nome": "Farol Lado Direito Uno 2004 até 2013 e Fiorino 2004 até 2013", "marca": "Arteb",
        "codigo_fabricante": "0160708", "ean": None,
        "imagens": [FOTO + "158596/0160708_Fiat_01_logo.jpg", FOTO + "158597/0160708_Fiat_02_logo.jpg"],
        "carro": "Fiat Uno"}]


def test_prefixo_da_loja_sai_do_codigo_da_fitam_e_cada_modelo_vira_um_veiculo():
    [r] = registros(PRODUTOS["2014035"])
    assert r["codigo_fabricante"] == "36034D"
    assert r["ean"] == "7798035618668"
    assert r["carro"] == "Chevrolet Novo Prisma; Chevrolet Prisma"


def test_codigo_da_fitam_sem_prefixo_fica_como_esta():
    produto = copy.deepcopy(PRODUTOS["2014035"])
    produto["items"][0]["referenceId"] = [{"Key": "RefId", "Value": "FIT"}]
    assert next(registros(produto))["codigo_fabricante"] == "FIT"
    produto["items"][0]["referenceId"] = [{"Key": "RefId", "Value": "36034D"}]
    assert next(registros(produto))["codigo_fabricante"] == "36034D"


def test_letras_de_marca_fora_da_tabela_fazem_parte_do_codigo():
    [r] = registros(PRODUTOS["2020848"])
    assert r["codigo_fabricante"] == "RC309"
    assert r["carro"] == "Chevrolet Omega 1992-1998"


def test_dois_lados_viram_dois_registros_com_o_lado_no_nome():
    assert [(r["url"], r["nome"], r["codigo_fabricante"], r["carro"]) for r in registros(PRODUTOS["2002059"])] == [
        ("https://www.altese.com.br/zn14141469-zn14141468-altese-farol/p?skuId=2002236",
         "Farol Principal Cromado Ranger 2009 até 2011 Lado Esquerdo", "ZN14141469", "Ford Ranger 2009-2011"),
        ("https://www.altese.com.br/zn14141469-zn14141468-altese-farol/p?skuId=2002237",
         "Farol Principal Cromado Ranger 2009 até 2011 Lado Direito", "ZN14141468", "Ford Ranger 2009-2011"),
    ]


def test_lado_que_ja_esta_no_nome_do_sku_nao_se_repete():
    assert [(r["nome"], r["codigo_fabricante"]) for r in registros(PRODUTOS["2006868"])] == [
        ("Farol Corsa 1994 até 2010 Esq", "0160179"), ("Farol Corsa 1994 até 2010 Dir", "0160180")]


def test_produto_de_um_sku_usa_o_nome_do_produto_sem_repetir_o_do_sku():
    [r] = registros(PRODUTOS["2015508"])
    assert r["nome"] == "Farol Principal Duplo Máscara Negra: Gol G3 - Parati G3 - Saveiro G3- Lado  Direito"


def test_produto_sem_montadora_fica_sem_carro():
    [r] = registros(PRODUTOS["2017180"])
    assert r["carro"] is None and r["ean"] == "760687145103"


def test_prefixo_da_hella_sai_do_codigo():
    [r] = registros(PRODUTOS["2017180"])
    assert r["codigo_fabricante"] == "7951"


def test_kit_montado_pela_loja_e_ignorado():
    assert list(registros(PRODUTOS["2015933"])) == []


def test_sku_sem_foto_e_ignorado():
    produto = copy.deepcopy(PRODUTOS["2002059"])
    produto["items"][1]["images"] = []
    assert [r["codigo_fabricante"] for r in registros(produto)] == ["ZN14141469"]


class _Resposta:
    def __init__(self, status, corpo, headers=None):
        self.status_code, self._corpo, self.headers = status, corpo, headers or {}

    def json(self):
        return json.loads(self._corpo)


class _Sessao:
    """Responde em ordem; uma exceção na lista é levantada no lugar da resposta."""
    def __init__(self, respostas):
        self.respostas, self.urls, self.headers = respostas, [], {}

    def get(self, url, timeout=None):
        self.urls.append(url)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def rede(monkeypatch):
    esperas = []
    monkeypatch.setattr(catalogo_altese.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_altese, "_local", threading.local())

    def usar(respostas):
        sessoes = []

        def nova():
            sessoes.append(_Sessao(respostas))
            return sessoes[-1]
        monkeypatch.setattr(catalogo_altese.requests, "Session", nova)
        return sessoes
    return usar, esperas


def test_conexao_recusada_e_erro_500_sao_tentados_de_novo_na_mesma_sessao(rede):
    usar, esperas = rede
    sessoes = usar([requests.ConnectionError("curl: (7) Could not connect to server"),
                    _Resposta(500, "The operation was canceled."),
                    _Resposta(206, "[]", {"resources": "0-0/191"})])
    assert catalogo_altese.total("fq=B:2000046") == 191
    assert esperas == [5, 15]
    assert len(sessoes) == 1 and len(sessoes[0].urls) == 3
    assert sessoes[0].urls[0] == f"{catalogo_altese.BASE}/api/catalog_system/pub/products/search?fq=B:2000046&_from=0&_to=0"


def test_erro_4xx_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404, "")])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_altese.api("brand/list")
    assert esperas == []


def test_desiste_depois_de_quatro_tentativas(rede):
    usar, esperas = rede
    usar([requests.ConnectionError("recusada")] * 4)
    with pytest.raises(RuntimeError, match="recusada"):
        catalogo_altese.api("brand/list")
    assert esperas == [5, 15, 30]


def test_marcas_para_ler_tira_id_repetido_inativas_e_ignoradas():
    lista = [{"id": 2000010, "name": "Bosch", "isActive": True}, {"id": 2000010, "name": "Bosch", "isActive": True},
             {"id": 2000046, "name": "Arteb", "isActive": True}, {"id": 2000099, "name": "Mahle", "isActive": True},
             {"id": 2000100, "name": "Mahle", "isActive": True}, {"id": 2000500, "name": "Velha", "isActive": False},
             {"id": 2000317, "name": "Altese Combos e Kit", "isActive": True}]
    assert [m["id"] for m in catalogo_altese.marcas_para_ler(lista)] == [2000010, 2000046, 2000099, 2000100]
    assert [m["id"] for m in catalogo_altese.marcas_para_ler(lista, "arteb")] == [2000046]
    with pytest.raises(SystemExit):
        catalogo_altese.marcas_para_ler(lista, "Altese Combos e Kit")


def test_ean_repetido_em_codigos_diferentes_da_loja_e_descartado():
    regs = [{"marca": "Cofap", "codigo_fabricante": "BTC33107", "ean": "7891579343048"},
            {"marca": "Cofap", "codigo_fabricante": "BTC33108", "ean": "7891579343048"},  # direita com o EAN da esquerda
            {"marca": "Cofap", "codigo_fabricante": "GP30365", "ean": "7891579992017"},
            {"marca": "Cofap", "codigo_fabricante": "GP30365", "ean": "7891579992017"},  # mesmo SKU em dois anúncios
            {"marca": "Nakata", "codigo_fabricante": "HG41062", "ean": None}]
    assert [r["ean"] for r in catalogo_altese.sem_ean_repetido(regs)] == [None, None, "7891579992017", "7891579992017", None]


def test_ano_do_produto_so_vai_para_o_modelo_quando_ha_um_modelo_so():
    """O 'Ano do Veículo' da Altese é do produto inteiro (1969 a 2022 numa peça de Fox e Gol G5 a G7): repetido em cada
    modelo, virava 'Gol G7 1969-2022'. Com um modelo só, a faixa é dele."""
    from catalogo_altese import veiculos
    varios = {"Todas as Montadoras": ["Volkswagen"], "Volkswagen": ["Fox", "Gol G7"], "Ano do Veículo :": ["1969", "2022"]}
    um = {"Todas as Montadoras": ["Chevrolet"], "Chevrolet": ["Omega"], "Ano do Veículo :": ["1992", "1995", "1998"]}
    assert veiculos(varios) == "Volkswagen Fox; Volkswagen Gol G7"
    assert veiculos(um) == "Chevrolet Omega 1992-1998"


def test_coringa_1969_2022_da_loja_nao_vira_ano():
    from catalogo_altese import veiculos
    p = {"Todas as Montadoras": ["Volkswagen"], "Volkswagen": ["Polo"], "Ano do Veículo :": [str(a) for a in range(1969, 2023)]}
    assert veiculos(p) == "Volkswagen Polo"
