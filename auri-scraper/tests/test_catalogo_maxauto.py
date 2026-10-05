from pathlib import Path

import pytest
import requests

import catalogo_maxauto
from aplicacao_texto import ocorrencias_do_texto
from catalogo_maxauto import codigo_fabricante, links_da_lista, registro, ultima_pagina

# páginas reais do maxauto.com.br, recortadas no bloco do produto (ou nos cartões e na paginação da lista)
DADOS = Path(__file__).parent / "dados"
FOTO = "https://www.maxauto.com.br/public/produtos/"


def pagina(nome):
    return (DADOS / f"maxauto_{nome}.html").read_text(encoding="utf-8")


def produto(id_produto, slug):
    url = f"https://maxauto.com.br/produto/{slug}/{id_produto}/"
    return registro(pagina(f"produto_{id_produto}"), url)


def test_lista_da_os_links_dos_produtos_e_a_ultima_pagina():
    html = pagina("lista_0")
    links = links_da_lista(html)
    assert len(links) == 12
    assert links[0] == "https://maxauto.com.br/produto/max-01-0001-5100/1114/"
    assert links[-1] == "https://maxauto.com.br/produto/max-01-0013-5510/1061/"
    assert ultima_pagina(html) == 143


def test_ultima_pagina_da_lista_tem_os_codigos_antigos():
    html = pagina("lista_143")
    assert links_da_lista(html)[0] == "https://maxauto.com.br/produto/max-5184/104/"
    assert ultima_pagina(html) == 143


def test_codigo_sai_como_a_karhub_escreve_sem_max_e_sem_ponto_com_o_zero():
    assert codigo_fabricante("MAX 01.0104") == "010104"
    assert codigo_fabricante("MAX 01.0014/ 5512") == "010014 / 5512"
    assert codigo_fabricante("MAX 01.0001 / 5100") == "010001 / 5100"
    assert codigo_fabricante("MAX 5184") == "5184"
    assert codigo_fabricante("MAX 08.0101/ 8800") == "080101 / 8800"


def test_produto_simples():
    r = produto("818", "max-01-0104")
    assert r == {
        "site": "maxauto", "url": "https://maxauto.com.br/produto/max-01-0104/818/",
        "nome": "Sensores de Velocidade", "marca": "MAXAUTO", "codigo_fabricante": "010104", "ean": None,
        "imagens": [FOTO + "6743-01-01041.jpg", FOTO + "4557-01-0104-10.jpg", FOTO + "6742-01-01042.jpg",
                    FOTO + "6741-01-01043.jpg"],
        "carro": "TOYOTA 4Runner 2.7/ 3.4 V6 1996-2000; TOYOTA Avalon 3.0 V6 2000-2004; TOYOTA Camry 2.2/ 3.0 V6 após 1993; "
                 "TOYOTA Celica 1.8 2000-2001; TOYOTA Corolla 2.4 2009-2010; TOYOTA Highlander 2.4/ 3.0 V6 2001-2010; "
                 "TOYOTA Matrix 2.4 2010-2010; TOYOTA RAV4 2.0/ 2.4/ 3.5 V6 após 1996; TOYOTA Sienna 3.0 V6 2001-2010; "
                 "TOYOTA Solara 3.0 V6 1999-2008; SCION TC 2.4 2005-2010; SCION XB 2.4 2010-2010; "
                 "LEXUS TOYOTA ES300 3.0 V6 após 1996; LEXUS TOYOTA ES330 3.3 V6 após 1996; LEXUS TOYOTA RX300 3.0 V6 1999-2003; "
                 "LEXUS TOYOTA RX330 3.3 V6 2004-2006; LEXUS TOYOTA SC300 3.0 1995-1997"}


def test_fotos_de_outro_codigo_saem():
    # o MAX 12.0152 mostra 3 fotos do 12.0147; fica só a do próprio código
    r = produto("1586", "max-12-0152")
    assert r["codigo_fabricante"] == "120152"
    assert r["imagens"] == [FOTO + "10944-12-0152-folder.jpg"]


def test_foto_com_o_codigo_antigo_fica_e_montadoras_juntas_viram_uma_so():
    r = produto("404", "max-08-0101-8800")
    assert r["codigo_fabricante"] == "080101 / 8800"
    assert r["imagens"] == [FOTO + "9911-08-01011.jpg", FOTO + "2886-8800.jpg", FOTO + "9910-08-01012.jpg",
                            FOTO + "9909-08-01013.jpg"]
    assert r["carro"].startswith("CHRYSLER JEEP DODGE Aspen 4.7 V8 2007-2009; CHRYSLER JEEP DODGE Dakota 4.7 V8 2000-2010;")


def test_cada_montadora_vale_para_os_modelos_logo_abaixo_e_as_notas_ficam_de_fora():
    r = produto("370", "max-01-0014-5512")
    assert r["codigo_fabricante"] == "010014 / 5512"
    assert r["carro"] == ("SUZUKI Grand Vitara 2.5 V6 1999-2005; SUZUKI Vitara 1.6/ 2.0 1999-2004; SUZUKI XL-7 2.7 V6 2002-2003; "
                          "GM Tracker 2.0 2007-2009")


def test_produto_unificado_fica_sem_aplicacao():
    r = produto("2282", "max-12-0192")
    assert r["codigo_fabricante"] == "120192"
    assert r["carro"] is None
    assert len(r["imagens"]) == 4


def test_foto_png_e_nome_da_linha():
    r = produto("4251", "max-09-0045")
    assert r["nome"] == "Sensores de Fluxo de Ar"
    assert r["imagens"][0] == FOTO + "16360-09-0045-1.png"
    assert r["carro"] == "RENAULT Master 2.5 16V Diesel 2009-2015"


def test_aplicacao_e_lida_pelo_helper_com_os_anos():
    r = produto("1586", "max-12-0152")
    ocorrencias = ocorrencias_do_texto(r["carro"])
    assert ["FIAT STRADA TREKKING/ WORKING", "STRADA TREKKING/ WORKING", (2013, None), []] in ocorrencias
    assert ["FIAT BRAVO ESSENCE/ SPORTING", "BRAVO ESSENCE/ SPORTING", (2011, 2016), []] in ocorrencias


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
def esperas(monkeypatch):
    lista = []
    monkeypatch.setattr(catalogo_maxauto.time, "sleep", lista.append)
    monkeypatch.setattr(catalogo_maxauto, "INTERVALO", 0)
    return lista


def test_conexao_recusada_e_erro_500_sao_tentados_de_novo(esperas):
    sessao = _Sessao([requests.ConnectionError("recusada"), _Resposta(503), _Resposta(200, "ok")])
    assert catalogo_maxauto.baixar(sessao, "https://maxauto.com.br/produtos?pagina=0") == "ok"
    assert esperas == [5, 15]
    assert len(sessao.urls) == 3


def test_erro_4xx_nao_e_tentado_de_novo(esperas):
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_maxauto.baixar(_Sessao([_Resposta(404)]), "https://maxauto.com.br/produto/x/1/")
    assert esperas == []


def test_desiste_depois_de_cinco_tentativas(esperas):
    with pytest.raises(RuntimeError, match="recusada"):
        catalogo_maxauto.baixar(_Sessao([requests.ConnectionError("recusada")] * 5), "https://maxauto.com.br/")
    assert esperas == [5, 15, 30, 60]
