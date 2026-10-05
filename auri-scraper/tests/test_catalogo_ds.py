import json
import threading
from pathlib import Path

import pytest
import requests

import catalogo_ds
from catalogo_ds import anos, links, registros, ultima_pagina

# trechos <main> reais de ds.ind.br (só os espaços encurtados; o aviso "Comprar online" do 2328 fora)
DADOS = Path(__file__).parent / "dados"
PRODUTOS = catalogo_ds.BASE + "/pt/produtos/"
GALERIA = catalogo_ds.BASE + "/cache/media/gallery/"


def html(nome):
    return (DADOS / nome).read_text(encoding="utf-8")


def test_lista_traz_os_produtos_da_pagina_e_o_numero_da_ultima():
    pagina = html("ds_lista.html")
    assert links(pagina) == [PRODUTOS + f"valvula-de-agulha/{c}" for c in ("1012", "1017", "1018", "1019", "1025")]
    assert ultima_pagina(pagina) == 456


def test_pagina_da_lista_com_itens_escondidos_nao_traz_produto():
    assert links(html("ds_lista_vazia.html")) == []


def test_produto_vira_um_registro_com_codigo_sem_prefixo_fotos_da_galeria_e_aplicacao():
    url = PRODUTOS + "sensor-de-nivel-de-combustivel/2328"
    assert registros(html("ds_2328.html"), url) == [{
        "site": "ds", "url": url, "nome": "Sensor de Nível de Combustível - 2328", "marca": "DS",
        "codigo_fabricante": "2328", "ean": None,
        "carro": "Chevrolet Meriva 2003-2012 1.8 4Cil 8v (Flex); Chevrolet Montana 2003-2009 1.8 4Cil 8v (Flex)",
        "imagens": [GALERIA + f"2f/37/d1/{n}-sensor-de-nivel-de-combustivel-2328-943-image-800x800.jpg" for n in (1, 2, 3)]}]


def test_codigo_mantem_as_letras_do_site_e_ano_aberto_vira_apos():
    [r] = registros(html("ds_30074de.html"), PRODUTOS + "sensor-abs/30074de")
    assert r["codigo_fabricante"] == "30074DE"
    assert r["nome"] == "Sensor ABS - 30074DE"
    assert len(r["imagens"]) == 3
    assert r["carro"] == ("Hyundai Elantra 2006-2010 1.8 4Cil 16v (Gasolina); Hyundai i30 2009-2012 2.0 4Cil 16v (Gasolina); "
                          "Kia Cerato após 2008 1.6 4Cil 16v (Gasolina); Kia Picanto 2008-2011 1.0 3Cil 12v (Gasolina); "
                          "Kia Soul após 2008 1.6 4Cil 16v (Gasolina)")


def test_fotos_dos_outros_produtos_da_linha_nao_entram():
    [r] = registros(html("ds_1147a.html"), PRODUTOS + "regulador-de-pressao-ajustavel/1147a")
    assert r["codigo_fabricante"] == "1147A"
    assert r["imagens"] == [GALERIA + "b7/06/83/1-regulador-de-pressao-ajustavel-1147A-70-image-800x800.jpg"]
    assert r["carro"].startswith("Eagle Summit após 1992 1.8 4Cil 16v (Gasolina); ")


def test_pagina_sem_produto_nao_vira_registro():
    # código inexistente: o site responde 200 com a página vazia
    assert registros("<main>\n</main>", PRODUTOS + "x/119005") == []


def test_produto_sem_galeria_fica_sem_foto():
    pagina = html("ds_2328.html").replace('<ul class="pgwSlider">', '<ul class="outra">')
    [r] = registros(pagina, PRODUTOS + "sensor-de-nivel-de-combustivel/2328")
    assert r["imagens"] == []


@pytest.mark.parametrize("texto, esperado", [
    ("03 &gt; 12", (2003, 2012)), ("92 &gt;", (1992, None)), ("&gt; 12", (None, 2012)), ("15", (2015, 2015)),
    ("", (None, None)), ("1995 &gt; 1998", (1995, 1998)), ("06/ 2008&gt;2014", (2008, 2014))])
def test_anos(texto, esperado):
    assert anos(texto) == esperado


def test_ponto_e_virgula_e_parenteses_da_observacao_nao_quebram_a_aplicacao():
    pagina = html("ds_2328.html").replace('<td class="observacoes"></td>', '<td class="observacoes">Com A/C; (exceto 1.0)</td>', 1)
    [r] = registros(pagina, PRODUTOS + "sensor-de-nivel-de-combustivel/2328")
    assert r["carro"].split("; ")[0] == "Chevrolet Meriva 2003-2012 1.8 4Cil 8v (Flex, Com A/C, exceto 1.0)"


class _Resposta:
    def __init__(self, status, texto=""):
        self.status_code, self.text = status, texto


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
    monkeypatch.setattr(catalogo_ds.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_ds, "_local", threading.local())
    monkeypatch.setattr(catalogo_ds, "ritmo", catalogo_ds.Ritmo(0))

    def usar(respostas):
        sessoes = []

        def nova():
            sessoes.append(_Sessao(respostas))
            return sessoes[-1]
        monkeypatch.setattr(catalogo_ds.requests, "Session", nova)
        return sessoes
    return usar, esperas


def test_conexao_recusada_e_erro_500_sao_tentados_de_novo(rede):
    usar, esperas = rede
    sessoes = usar([requests.ConnectionError("recusada"), _Resposta(500), _Resposta(200, "ok")])
    assert catalogo_ds.pedir(catalogo_ds.BASE + "/pt/x") == "ok"
    assert esperas == [5, 15]
    assert len(sessoes) == 1 and len(sessoes[0].urls) == 3


def test_pagina_404_nao_e_tentada_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404)])
    assert catalogo_ds.pedir(catalogo_ds.BASE + "/pt/x") is None
    assert esperas == []


def test_desiste_depois_de_cinco_tentativas(rede):
    usar, esperas = rede
    usar([requests.Timeout("lento")] * 5)
    with pytest.raises(RuntimeError, match="lento"):
        catalogo_ds.pedir(catalogo_ds.BASE + "/pt/x")
    assert esperas == [5, 15, 30, 60]


def test_ritmo_espaca_os_inicios_das_requisicoes(monkeypatch):
    agora, esperas = [100.0], []
    monkeypatch.setattr(catalogo_ds.time, "monotonic", lambda: agora[0])

    def dormir(s):
        esperas.append(round(s, 2))
        agora[0] += s
    monkeypatch.setattr(catalogo_ds.time, "sleep", dormir)
    ritmo = catalogo_ds.Ritmo(0.6)
    for _ in range(3):
        ritmo.esperar()
    agora[0] += 1.0  # já passou do intervalo: não espera
    ritmo.esperar()
    assert esperas == [0.6, 0.6]


def test_urls_ja_gravadas_sao_puladas_ao_retomar(tmp_path):
    saida = tmp_path / "ds.jsonl"
    saida.write_text(json.dumps({"url": "a"}) + "\n" + json.dumps({"url": "a"}) + "\n" + '{"url": "b"' + "\n",
                     encoding="utf-8")
    assert catalogo_ds.ja_feitos(saida) == {"a"}
    assert catalogo_ds.ja_feitos(tmp_path / "nao_existe.jsonl") == set()
