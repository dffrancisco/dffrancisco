import copy
import json
import threading
from pathlib import Path

import pytest
import requests

import catalogo_autonext
from catalogo_autonext import codigo, registros

# produtos reais da API da AutoNext (sem os campos que o catálogo não usa)
PRODUTOS = {p["productId"]: p for p in json.loads((Path(__file__).parent / "dados/autonext_produtos.json").read_text(encoding="utf-8"))}
FOTO = "https://autonext.vteximg.com.br/arquivos/ids/"


def test_kostal_mantem_os_pontos_e_o_zero_e_aplicacao_vem_dos_modelos():
    [r] = registros(PRODUTOS["3985"])
    assert r == {
        "site": "autonext",
        "url": "https://www.autonext.com.br/interruptor-vidro-eletrico-simples-escort-verona-apollo-88-92-com-moldura-3900101/p",
        "nome": "Interruptor Vidro Elétrico Simples Escort Verona Apollo 88/92 Com Moldura - 3900101 Kostal",
        "marca": "Kostal", "codigo_fabricante": "03.9001.01", "ean": "7894708003950",
        "imagens": [FOTO + "452518/03_9001_01_1.jpg", FOTO + "452519/03_9001_01_2.jpg",
                    FOTO + "452520/03_9001_01_3.jpg", FOTO + "452521/03_9001_01_4.jpg"],
        "carro": r["carro"]}
    assert r["carro"].startswith("Apollo Gl; Apollo Gls; Apollo Vip; Escort Ghia")


def test_arteb_perde_o_prefixo_da_loja_e_ganha_o_zero_de_volta_em_cada_lado():
    regs = list(registros(PRODUTOS["286"]))
    assert [(r["url"], r["nome"], r["codigo_fabricante"], r["ean"]) for r in regs] == [
        ("https://www.autonext.com.br/farol-astra-2003-ate-2011-foco-duplo-com-motor-regulagem/p?skuId=16792",
         "Farol Astra 2003 até 2011 Foco Duplo com Motor Regulagem Direito Arteb", "0160818", "7896482549105"),
        ("https://www.autonext.com.br/farol-astra-2003-ate-2011-foco-duplo-com-motor-regulagem/p?skuId=16793",
         "Farol Astra 2003 até 2011 Foco Duplo com Motor Regulagem Esquerdo Arteb", "0160817", "7896482549099")]
    assert regs[0]["carro"].startswith("CHEVROLET Astra 2003-2004 2.0 Gasolina; CHEVROLET Astra Advantage 2004-2009 2.0 Flex")


def test_arteb_antigo_com_dois_zeros():
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["224"])] == ["0060052", "0060051"]


def test_prefixo_da_loja_sai_do_codigo():
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["576"])] == ["97416", "97417"]  # Blawer BL-
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["6644"])] == ["12783"]  # Zen ZEN-


def test_cofran_volta_a_uma_casa_decimal():
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["11750"])] == ["3086.5", "3087.5"]


def test_sufixo_de_versao_da_delphi_sai():
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["12365"])] == ["HNX700"]


def test_codigo_interno_da_loja_vira_null_mas_o_do_fabricante_atras_dele_fica():
    [aromatizante] = registros(PRODUTOS["5518"])
    assert aromatizante["codigo_fabricante"] is None and aromatizante["ean"] == "7896360120587"
    assert aromatizante["carro"] is None  # 'APLICACAO-UNIVERSAL'
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["5393"])] == ["AX002N"]  # Gauss S18.AX002N


def test_ean_com_digito_errado_fica_de_fora():
    assert [r["ean"] for r in registros(PRODUTOS["12540"])] == [None, "7897563503542"]


def test_sku_inativo_e_ignorado():
    assert list(registros(PRODUTOS["12603"])) == []


def test_sku_sem_foto_e_ignorado():
    produto = copy.deepcopy(PRODUTOS["576"])
    produto["items"][0]["images"] = []
    assert [r["codigo_fabricante"] for r in registros(produto)] == ["97417"]


def test_sem_colchete_usa_o_codigo_do_fabricante_da_ficha_se_for_um_so():
    produto = copy.deepcopy(PRODUTOS["12365"])
    produto["items"][0]["referenceId"] = [{"Key": "RefId", "Value": "HNX700"}]
    assert next(registros(produto))["codigo_fabricante"] == "HNX700"
    produto["Código do fabricante"] = ["HNX700, HNX701"]
    assert next(registros(produto))["codigo_fabricante"] is None


@pytest.mark.parametrize("marca, bruto, esperado", [
    ("ZM", "ZM-370.116.40", "370.116.40"), ("ZM", "ZM170.110.64", "170.110.64"), ("NAT", "NAT100520", "100520"),
    ("Hella", "HE-H3WL", "H3WL"), ("Hella", "HBI0110", "HBI0110"), ("Bosch", "F000TE188E", "F000TE188E"),
    ("Autonext Parts", "S20.1426LD", None), ("Permak", "S03.HI320", "HI320"), ("Cofran Retrovisores", "C-1455.00", "1455.0"),
    ("Arteb", "A-161.006", "0161006"), ("Arteb", "A-160.818X", "160.818X"), ("Delphi", "CS20053-13B1", "CS20053"),
    ("Osram", "64211CW.NBC", "64211CW.NBC"), ("Radnaq", "RQ1011", "RQ1011"), ("Vonixx", "V-2026005", "2026005"),
])
def test_codigo(marca, bruto, esperado):
    assert codigo(marca, bruto) == esperado


class _Resposta:
    def __init__(self, status, corpo, headers=None):
        self.status_code, self._corpo, self.headers = status, corpo, headers or {}

    def json(self):
        return json.loads(self._corpo)


class _Sessao:
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
    esperas, relogio = [], [100.0]
    monkeypatch.setattr(catalogo_autonext.time, "sleep", lambda s: (esperas.append(s), relogio.__setitem__(0, relogio[0] + s)))
    monkeypatch.setattr(catalogo_autonext.time, "monotonic", lambda: relogio[0])
    monkeypatch.setattr(catalogo_autonext, "_local", threading.local())
    monkeypatch.setattr(catalogo_autonext, "_proxima", 0.0)

    def usar(respostas):
        sessoes = []

        def nova():
            sessoes.append(_Sessao(respostas))
            return sessoes[-1]
        monkeypatch.setattr(catalogo_autonext.requests, "Session", nova)
        return sessoes
    return usar, esperas


def test_erro_500_e_conexao_caida_sao_tentados_de_novo_e_respeitam_duas_por_segundo(rede):
    usar, esperas = rede
    sessoes = usar([requests.ConnectionError("recusada"), _Resposta(500, '"The operation was canceled."'),
                    _Resposta(206, "[]", {"resources": "0-0/191"}), _Resposta(206, "[]", {"resources": "0-0/7"})])
    assert catalogo_autonext.total("fq=B:2000046") == 191
    assert catalogo_autonext.total("fq=B:2000047") == 7
    assert esperas == [5, 15, 0.5]
    assert len(sessoes) == 1
    assert sessoes[0].urls[0] == f"{catalogo_autonext.BASE}/api/catalog_system/pub/products/search?fq=B:2000046&_from=0&_to=0"


def test_erro_4xx_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404, "")])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_autonext.api("brand/list")
    assert esperas == []
