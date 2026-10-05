from pathlib import Path

import pytest
import requests

import catalogo_iguacu
from catalogo_iguacu import anos, campos, linhas, registros

# resposta real da busca do site (linhas de 7 códigos e a linha vazia que o site às vezes põe; viewstate encurtado)
HTML = (Path(__file__).parent / "dados/iguacu_busca.html").read_text(encoding="utf-8")
POR_CODIGO = {r["codigo_fabricante"]: r for r in registros(linhas(HTML))}
FOTO = "https://www.iguacu.ind.br/images/produtos/"


def test_codigo_sai_sem_ponto_traco_e_barra_como_o_cliente_escreve():
    assert POR_CODIGO["30104259297"] == {
        "site": "iguacu", "url": "https://www.iguacu.ind.br/busca#301.0425-92/97",
        "nome": "Termo-Interruptor do Radiador - Iguaçu 301.0425-92/97", "marca": "IGUACU",
        "codigo_fabricante": "30104259297", "ean": None,
        "carro": "ALFA ROMEO 155 Após 1993 2.5; CITROEN JUMPER Após 1994 2.0; FIAT PALIO 1996-2002 1.0 8V; "
                 "FIAT PALIO WEEKEND 1998-2000 1.0 8V; FIAT SIENA 1999-2000 1.0 8V",
        "imagens": [FOTO + "30104259297.jpg"]}


def test_um_registro_por_codigo_na_ordem_do_site_sem_a_linha_vazia():
    assert list(POR_CODIGO) == ["401156880", "401156887", "401124782", "401160982", "2032014", "601300680", "30104259297"]


def test_anos_separados_por_espaco_e_foto_pelo_codigo():
    assert POR_CODIGO["601300680"]["carro"] == "AUDI A4 2001-2002; AUDI A3 Após 2002 1.6 8V"
    assert POR_CODIGO["2032014"]["imagens"] == [FOTO + "2032014.jpg"]


def test_nome_vem_da_familia_do_codigo():
    assert POR_CODIGO["401156880"]["nome"] == "Válvula Termostática - Iguaçu 401.1568-80"
    assert POR_CODIGO["2032014"]["nome"] == "Sensor de Temperatura do Painel - Iguaçu 203.2014"
    assert POR_CODIGO["601300680"]["nome"] == "Combinado de Válvula Termostática - Iguaçu 601.3006-80"


@pytest.mark.parametrize("texto, esperado", [
    ("07-15", (2007, 2015)), ("99-02", (1999, 2002)), ("86-86", (1986, 1986)), ("01 02", (2001, 2002)),
    ("08->", (2008, None)), ("02 >", (2002, None)), (">-86", (None, 1986)),
    ("---", None), (">->", None), ("", None)])
def test_anos_do_site(texto, esperado):
    assert anos(texto) == esperado


def test_carro_junta_os_anos_do_mesmo_veiculo_e_motor():
    # Golf 1.4 16V TSI 16-17 (flex) e 14-16 (gasolina); Jetta 18-> e 15-18
    assert POR_CODIGO["401156887"]["carro"] == (
        "VOLKSWAGEN GOLF 2014-2017 1.4 16V TSI; VOLKSWAGEN JETTA Após 2015 1.4 16V TSI; "
        "VOLKSWAGEN TIGUAN Após 2016 1.4 16V TSI; VOLKSWAGEN GOLF Após 2016 1.6 16V TSI")


def test_ate_ano_e_motor_em_branco():
    assert POR_CODIGO["401124782"]["carro"] == (
        "FORD BELINA Até 1986; FORD CORCEL Até 1986; FORD ESCORT Até 1986 1.3; FORD DEL REY Até 1986 1.6; "
        "FORD ESCORT Até 1986 1.6; RENAULT TRAFIC Após 1978; RENAULT R12 Após 1978 1.4; RENAULT R18 Após 1978 1.4")


def test_sem_ano_fica_so_veiculo_e_motor():
    assert POR_CODIGO["2032014"]["carro"].startswith("AUDI COUPÉ; AUDI 80 1.9; AUDI 80 2.0; AUDI 100 2.2; AUDI 200 2.2;")
    assert POR_CODIGO["401160982"]["carro"].startswith("CATERPILLAR 216 CRAWLER TRACTORS; CATERPILLAR 226 B CRAWLER")


def test_campos_escondidos_do_formulario():
    f = campos(HTML)
    assert f["__VIEWSTATEGENERATOR"] == "6A88D377"
    assert f["__VIEWSTATE"].startswith("/wEPDwUIMjQ1Mzk1MTc")
    assert f["__EVENTTARGET"] == ""


def test_descoberta_junta_digitos_familias_e_familia_com_o_primeiro_digito_do_numero():
    # cada termo traz só uma parte dos códigos: 201.0826 só aparece em "2010", 504.6801 (fora do menu) num dígito
    respostas = {"1": ["201.0831", "504.6801", ""], "2": ["201.0831", "203.2014"], "201.": ["201.0802"],
                 "2010": ["201.0826", "201.0831"], "5049": ["504.9001"]}
    pedidos = []

    def buscar(termo):
        pedidos.append(termo)
        return [{"codigo": c} for c in respostas.get(termo, [])]
    assert catalogo_iguacu.descobrir(buscar) == {"201.0802", "201.0826", "201.0831", "203.2014", "504.6801"}
    assert pedidos[:10] == list("0123456789")
    assert {"201.", "203.", "401.", "504.", "701."} <= set(pedidos)  # famílias do menu e as achadas
    assert {"2010", "2032", "5046"} <= set(pedidos) and "5049" not in pedidos


class _Resposta:
    def __init__(self, status, texto="", tipo="text/html"):
        self.status_code, self.text, self.headers = status, texto, {"Content-Type": tipo}


class _Sessao:
    """Responde em ordem; uma exceção na lista é levantada no lugar da resposta."""
    def __init__(self, respostas):
        self.respostas, self.pedidos, self.headers = respostas, [], {}

    def request(self, metodo, url, data=None, timeout=None, allow_redirects=True):
        self.pedidos.append((metodo, url, data))
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def rede(monkeypatch):
    esperas = []
    monkeypatch.setattr(catalogo_iguacu.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_iguacu, "INTERVALO", 0)
    monkeypatch.setattr(catalogo_iguacu, "_sessao", None)
    monkeypatch.setattr(catalogo_iguacu, "_form", None)

    def usar(respostas):
        sessao = _Sessao(respostas)
        monkeypatch.setattr(catalogo_iguacu.requests, "Session", lambda: sessao)
        return sessao
    return usar, esperas


def test_busca_reaproveita_o_formulario_que_volta_no_post(rede):
    usar, esperas = rede
    sessao = usar([_Resposta(200, HTML), requests.Timeout("lenta"), _Resposta(200, HTML), _Resposta(200, HTML)])
    assert {l["codigo"] for l in catalogo_iguacu.buscar("401.1568-87")} >= {"401.1568-87", "401.1247-82"}
    catalogo_iguacu.buscar("2010831")
    assert esperas == [5]
    assert [m for m, _, _ in sessao.pedidos] == ["GET", "POST", "POST", "POST"]
    _, url, dados = sessao.pedidos[3]
    assert url == catalogo_iguacu.BUSCA
    assert dados["TxtPesquisaCatalogo"] == "2010831" and dados["chks"] == "RB_Iguacu"
    assert dados["__VIEWSTATEGENERATOR"] == "6A88D377"


def test_post_recusado_refaz_a_busca_com_formulario_novo(rede, monkeypatch):
    usar, esperas = rede
    monkeypatch.setattr(catalogo_iguacu, "ESPERAS", ())
    sessao = usar([_Resposta(200, HTML), _Resposta(500), _Resposta(200, HTML), _Resposta(200, HTML)])
    assert catalogo_iguacu.buscar("401.1568-87")
    assert [m for m, _, _ in sessao.pedidos] == ["GET", "POST", "GET", "POST"]


def test_aplicacoes_do_codigo_so_ficam_as_linhas_dele(rede):
    usar, esperas = rede
    usar([_Resposta(200, HTML), _Resposta(200, HTML)])
    assert [l["veiculo"] for l in catalogo_iguacu.aplicacoes_do_codigo("601.3006-80")] == ["A4", "A3"]


def test_erro_4xx_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404)])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_iguacu.buscar("401.")
    assert esperas == []


def test_foto_existe_so_com_200_e_tipo_de_imagem(rede):
    usar, esperas = rede
    sessao = usar([_Resposta(200, tipo="image/jpeg"), _Resposta(404), _Resposta(200, tipo="text/html"),
                   requests.ConnectionError("recusada"), _Resposta(200, tipo="image/jpeg")])
    assert catalogo_iguacu.foto_existe(FOTO + "2010831.jpg")
    assert not catalogo_iguacu.foto_existe(FOTO + "9999999.jpg")
    assert not catalogo_iguacu.foto_existe(FOTO + "2010832.jpg")
    assert catalogo_iguacu.foto_existe(FOTO + "2010833.jpg")
    assert esperas == [5]
    assert sessao.pedidos[0][:2] == ("HEAD", FOTO + "2010831.jpg")
