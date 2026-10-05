import copy
import json
from pathlib import Path

import pytest
import requests

import catalogo_tcchicotes
from catalogo_tcchicotes import cartoes, codigo, fotos_grandes, registro, total, veiculos
from helper.normalizar import normalizar_codigo

# páginas reais do site (recortadas: só a galeria, a identificação e as abas de aplicação)
DADOS = Path(__file__).parent / "dados"
LISTA = (DADOS / "tcchicotes_lista.html").read_text(encoding="utf-8")
PAGINAS = {c: (DADOS / f"tcchicotes_produto_{c}.html").read_text(encoding="utf-8")
           for c in ("102.1278", "103.1730", "411.035.10", "C0100-52-25")}
PERTINHO = json.loads((DADOS / "tcchicotes_pertinho.json").read_text(encoding="utf-8"))
SITE = "https://tcchicotes.com.br/produtos/"
FOTO = "https://buscanarede.com.br/cms/produtos_webp/tcchicotes/"


def test_lista_da_o_codigo_do_site_e_a_url_de_cada_cartao():
    assert cartoes(LISTA) == [("101.1032", SITE + "chicote-01-via-do-sensor-de-oleo/"),
                              ("101.1038", SITE + "chicote-01-via-do-sensor-de-temperatura/"),
                              ("101.1045", SITE + "chicote-01-via-injecao-eletronica-femea/")]
    assert total(LISTA) == 4264


def test_codigo_ganha_o_prefixo_tc_e_normaliza_igual_a_karhub_e_ao_cliente():
    assert codigo("102.1278") == "TC 102.1278"
    assert normalizar_codigo(codigo("102.1278")) == normalizar_codigo("TC 102.1278") == "TC1021278"
    assert normalizar_codigo(codigo("411.035.10")) == "TC41103510"  # cliente: "TC41103510"
    assert normalizar_codigo(codigo("C0100-64/25")) == "TCC010064/25"  # cliente: "TCC010064/25"
    assert codigo("500.0123") == "TC 500.0123"  # zero à esquerda fica


def test_sonda_tem_ean_foto_grande_e_aplicacao_por_modelo_com_anos():
    r = registro(PAGINAS["411.035.10"], SITE + "sonda-lambda-4-fios/", fotos_grandes(PERTINHO))
    assert r == {
        "site": "tcchicotes", "url": SITE + "sonda-lambda-4-fios/",
        "nome": "SONDA LAMBDA 4 FIOS COM 35CM DA ROSCA ATÉ O CONECTOR FIAT ELBA 1.5 SPI - 93/97 ELBA 1.6 8V SPI - "
                "95/96 FIORINO 1.5 8V SP",
        "marca": "TC CHICOTES", "codigo_fabricante": "TC 411.035.10", "ean": "7898400000040",
        "carro": "Fiat Elba 1.5 Spi 1993-1997; Fiat Elba 1.6 8V Spi 1995-1996; Fiat Fiorino 1.5 8V Spi 1994-1996; "
                 "Fiat Fiorino 1.6 8V Mpi 1995-1996; Fiat Prêmio 1.5 Spi 1993-1997; Fiat Tempra 2.0 8V 1994-1997; "
                 "Fiat Tempra 2.0 16V 1994-1997; Fiat Uno 1.5 8V Spi 1994-1996; Fiat Uno 1.6 8V Mpi 1995-1996",
        "imagens": ["https://images.pertinhodemim.com/789840000004_pt-BR.png",
                    FOTO + "2025/08/db0cc52e49823c4442cb27eb8a7e3d93.webp"]}


def test_ano_1940_e_sem_ano_e_buraco_na_sequencia_fica_separado():
    carro = veiculos(PAGINAS["103.1730"])
    assert carro.startswith("Mitsubishi Eclipse 1995; Mitsubishi Pajero Tr4 2010-2015, 2017-2018; "
                            "Mitsubishi L200 Triton 2.4 Flex 2007-2016; ")
    assert carro.endswith("Hyundai Santa Fé; Hyundai Sonata; Kia Picanto; Kawasaki Er-6N; Kawasaki Rx250F 2011-2012; "
                          "Kawasaki Kfx 450R 2011-2014")


def test_diversos_nao_e_aplicacao():
    r = registro(PAGINAS["102.1278"], SITE + "x/", fotos_grandes(PERTINHO))
    assert r["carro"] is None
    assert r["codigo_fabricante"] == "TC 102.1278" and r["ean"] == "7898484694937"
    assert r["imagens"] == ["https://images.pertinhodemim.com/789848469493_pt-BR.png",
                            FOTO + "2025/08/105fc773a0abef12c170a53239376bc7.webp"]


def test_cabo_sem_foto_grande_fica_so_com_a_do_site():
    r = registro(PAGINAS["C0100-52-25"], SITE + "cabo/", fotos_grandes(PERTINHO))
    assert r["codigo_fabricante"] == "TC C0100-52/25"
    assert r["ean"] == "7898705313135" and r["carro"] is None
    assert r["imagens"] == [FOTO + "2026/08/921014ac129df17a00faded3e75e2d17.webp"]


def test_foto_grande_com_outro_codigo_no_nome_nao_entra():
    itens = copy.deepcopy(PERTINHO)
    itens[0]["name"] = "102.9999 - Chicote 02 Vias"  # mesmo GTIN do 102.1278, código diferente
    r = registro(PAGINAS["102.1278"], SITE + "x/", fotos_grandes(itens))
    assert r["imagens"] == [FOTO + "2025/08/105fc773a0abef12c170a53239376bc7.webp"]


def test_foto_grande_sem_codigo_no_nome_entra_pelo_gtin():
    itens = copy.deepcopy(PERTINHO)
    itens[0]["name"] = "CHICOTE 02 VIAS BOMBA DE COMBUSTIVEL FLEX"
    r = registro(PAGINAS["102.1278"], SITE + "x/", fotos_grandes(itens))
    assert r["imagens"][0] == "https://images.pertinhodemim.com/789848469493_pt-BR.png"


def test_imagem_padrao_sem_foto_do_site_e_descartada():
    pagina = PAGINAS["C0100-52-25"].replace(FOTO + "2026/08/921014ac129df17a00faded3e75e2d17.webp",
                                            "https://buscanarede.com.br/cms/no-image.webp")
    assert registro(pagina, SITE + "cabo/", {})["imagens"] == []


@pytest.mark.parametrize("ean", ["0", "7898705313136", "0000000000000"])
def test_ean_que_nao_e_ean13_valido_fica_nulo(ean):
    pagina = PAGINAS["C0100-52-25"].replace("<dd>7898705313135</dd>", f"<dd>{ean}</dd>")
    assert registro(pagina, SITE + "cabo/", {})["ean"] is None


class _Resposta:
    def __init__(self, status, texto=""):
        self.status_code, self.text = status, texto


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
    esperas = []
    monkeypatch.setattr(catalogo_tcchicotes.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_tcchicotes, "ritmo", catalogo_tcchicotes.Ritmo(0))

    def usar(respostas):
        sessao = _Sessao(respostas)
        monkeypatch.setattr(catalogo_tcchicotes, "sessao", lambda: sessao)
        return sessao
    return usar, esperas


def test_erro_de_conexao_e_500_sao_tentados_de_novo(rede):
    usar, esperas = rede
    sessao = usar([requests.ConnectionError("recusada"), _Resposta(503), _Resposta(200, "ok")])
    assert catalogo_tcchicotes.pedir(SITE) == "ok"
    assert [e for e in esperas if e] == [5, 15] and len(sessao.urls) == 3


def test_404_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404)])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_tcchicotes.pedir(SITE)
    assert not any(esperas)


def test_desiste_depois_de_cinco_tentativas(rede):
    usar, esperas = rede
    usar([requests.Timeout("lento")] * 5)
    with pytest.raises(RuntimeError, match="lento"):
        catalogo_tcchicotes.pedir(SITE)
    assert [e for e in esperas if e] == [5, 15, 30, 60]


def test_ja_feitos_le_as_urls_gravadas_e_ignora_linha_cortada(tmp_path):
    arq = tmp_path / "tc.jsonl"
    assert catalogo_tcchicotes.ja_feitos(arq) == set()
    arq.write_text('{"url": "a"}\n{"url": "b"}\n{"url": "c', encoding="utf-8")
    assert catalogo_tcchicotes.ja_feitos(arq) == {"a", "b"}
