import threading
from pathlib import Path

import pytest
import requests

import catalogo_vp
from catalogo_vp import codigo, produtos_do_sitemap, registros

# trechos <main> reais de vp.ind.br (só os espaços encurtados) e um pedaço do sitemap
DADOS = Path(__file__).parent / "dados"
BASE = catalogo_vp.BASE


def html(nome):
    return (DADOS / nome).read_text(encoding="utf-8")


def test_sitemap_traz_so_as_paginas_de_produto():
    assert produtos_do_sitemap(html("vp_sitemap.xml")) == [
        BASE + "/acessorios/acoplamento-3146",
        BASE + "/acessorios/kits-de-vidros-eletricos/kit-maquina-de-vidro-agile-dianteira-ld-5127",
        BASE + "/flanges/flange-de-combustivel-vp7057",
        BASE + "/lancamentos/modulo-de-combustivel-vp101",
        BASE + "/modulos-de-combustivel/modulo-de-combustivel-vp074",
        BASE + "/sensores-de-nivel/sensor-de-nivel-de-combustivel-8822"]


def test_sensor_vira_um_registro_com_a_foto_do_produto_e_aplicacao():
    url = BASE + "/sensores-de-nivel/sensor-de-nivel-de-combustivel-8822"
    assert registros(html("vp_8822.html"), url) == [{
        "site": "vp", "url": url, "nome": "Sensor de Nível de Combustível 8822", "marca": "VP VIRTUAL PLASTIC",
        "codigo_fabricante": "8822", "ean": None,
        "carro": "Volkswagen Bora 2008-2011 2.0 4cil 8v (Flex); Volkswagen Golf 2007-2008 1.6 4cil 8v (Flex); "
                 "Volkswagen Golf 2008-2014 2.0 4cil 8v (Flex)",
        "imagens": [BASE + "/imagens/produtos/sensores-de-nivel/8822.jpg"]}]


def test_flange_perde_o_vp_como_na_carblue():
    [r] = registros(html("vp_vp7057.html"), BASE + "/flanges/flange-de-combustivel-vp7057")
    assert r["codigo_fabricante"] == "7057"
    assert r["imagens"] == [BASE + "/imagens/produtos/flanges/7057.1.jpg"]
    assert r["carro"] == "Fiat Marea 1999-2001 2.4 4cil 16v (Gasolina); Fiat Marea Weekend 1999-2001 2.4 4cil 16v (Gasolina)"


def test_modulo_fica_com_o_vp_e_sem_as_fotos_dos_componentes_da_descricao():
    [r] = registros(html("vp_vp074.html"), BASE + "/modulos-de-combustivel/modulo-de-combustivel-vp074")
    assert r["codigo_fabricante"] == "VP074"
    assert r["nome"] == "Módulo de Combustível VP074"
    assert r["imagens"] == [BASE + "/imagens/produtos/modulos-de-combustivel/vp074.jpg"]
    assert r["carro"].startswith("Fiat Fiorino 1997-2001 1.0 4cil 8v MPI (Gasolina); ")


def test_observacao_da_linha_entra_e_combustivel_traco_nao():
    [r] = registros(html("vp_5127.html"), BASE + "/acessorios/kits-de-vidros-eletricos/kit-maquina-de-vidro-agile-dianteira-ld-5127")
    assert (r["codigo_fabricante"], r["carro"]) == ("5127", "Chevrolet Agile 2010-2014 (Dianteira LD)")
    assert r["imagens"] == [BASE + "/imagens/produtos/acessorios/kits-de-vidros-eletricos/capturadetela2026-05-13145323.png"]
    [r] = registros(html("vp_3146.html"), BASE + "/acessorios/acoplamento-3146")
    assert r["carro"] == ("Fiat Idea (DIANTEIRO/TRASEIRO LD/LE); Fiat Punto (DIANTEIRO/TRASEIRO LD/LE); "
                          "Fiat Stilo (DIANTEIRO/TRASEIRO LD/LE)")


@pytest.mark.parametrize("site, esperado", [
    ("8822", "8822"), ("VP7057", "7057"), ("VP7016-CH", "7016-CH"), ("VP074", "VP074"), ("VP101", "VP101"),
    ("0115", "0115"), ("vp7242", "7242"), ("VPX", "VPX"), (" 10118 ", "10118")])
def test_codigo(site, esperado):
    assert codigo(site) == esperado


def test_pagina_sem_produto_nao_vira_registro():
    assert registros("<main><div id='main'></div></main>", BASE + "/produtos/flanges") == []


def test_foto_com_caminho_relativo_vira_url_completa():
    # a 5009 (kit de máquina de vidro) aponta a foto como '../imagens/produtos/linha-5000/5009.jpg'
    pagina = html("vp_5127.html").replace(
        "<a href='https://www.vp.ind.br/imagens/produtos/acessorios/kits-de-vidros-eletricos/capturadetela2026-05-13145323.png'",
        "<a href='../imagens/produtos/linha-5000/5009.jpg'")
    [r] = registros(pagina, BASE + "/acessorios/kit-maquina-de-vidro-gol-giii-dianteira-ld-le-5009")
    assert r["imagens"] == [BASE + "/imagens/produtos/linha-5000/5009.jpg"]


def test_produto_sem_foto_fica_sem_imagem():
    pagina = html("vp_8822.html").replace("<div id='ImagemProduto'>", "<div id='OutraCoisa'>")
    [r] = registros(pagina, BASE + "/sensores-de-nivel/sensor-de-nivel-de-combustivel-8822")
    assert r["imagens"] == []


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
    monkeypatch.setattr(catalogo_vp.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_vp, "_local", threading.local())
    monkeypatch.setattr(catalogo_vp, "ritmo", catalogo_vp.Ritmo(0))

    def usar(respostas):
        monkeypatch.setattr(catalogo_vp.requests, "Session", lambda: _Sessao(respostas))
    return usar, esperas


def test_erro_passageiro_e_tentado_de_novo_e_404_nao(rede):
    usar, esperas = rede
    usar([requests.ConnectionError("recusada"), _Resposta(503), _Resposta(200, "ok"), _Resposta(404)])
    assert catalogo_vp.pedir(BASE + "/x") == "ok"
    assert catalogo_vp.pedir(BASE + "/y") is None
    assert esperas == [5, 15]


def test_desiste_depois_de_cinco_tentativas(rede):
    usar, esperas = rede
    usar([requests.Timeout("lento")] * 5)
    with pytest.raises(RuntimeError, match="lento"):
        catalogo_vp.pedir(BASE + "/x")
    assert esperas == [5, 15, 30, 60]
