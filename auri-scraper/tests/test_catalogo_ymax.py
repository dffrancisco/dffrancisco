from pathlib import Path

import pytest
import requests

import catalogo_ymax
from catalogo_ymax import foto_original, ids_da_lista, registro, total, veiculos

# páginas reais da YM Distribuidora (recortadas: do breadcrumb até a aba "Detalhes")
DADOS = Path(__file__).parent / "dados"
LISTA = (DADOS / "ymax_lista.html").read_text(encoding="utf-8")
PAGINAS = {c: (DADOS / f"ymax_produto_{c}.html").read_text(encoding="utf-8")
           for c in ("05065", "16080", "164501", "50825", "61120", "7219")}
BASE = "https://www.ymdistribuidora.com.br/"
FOTO = BASE + "image/data/Produtos/"


def test_lista_da_os_ids_dos_produtos_e_o_total():
    assert ids_da_lista(LISTA) == ["5440", "5373", "5441"]
    assert total(LISTA) == 4303


def test_foto_do_cache_vira_a_original():
    assert foto_original(BASE + "image/cache/data/Produtos/CO/CORPO-DE-BORBOLETA-Unica-E101162F-1-1000x1000.jpg.webp") \
        == FOTO + "CO/CORPO-DE-BORBOLETA-Unica-E101162F-1.jpg"
    assert foto_original(BASE + "image/cache/data/Produtos/X/A-1-1000x1000.png") == FOTO + "X/A-1.png"
    assert foto_original(BASE + "image/data/Produtos/X/A-1.jpg") == FOTO + "X/A-1.jpg"


def test_produto_com_tres_fotos_ean_e_aplicacao():
    assert registro(PAGINAS["164501"]) == {
        "site": "ymax", "url": BASE + "corpo-de-borboleta-5443", "nome": "CORPO DE BORBOLETA", "marca": "YMAX",
        "codigo_fabricante": "164501", "ean": "7908295250519",
        "carro": "Honda CITY 1.5 6V G4 2015-2020; Honda FIT 1.5 16V G3 2015-2021; Honda WRV 1.5 16V 2018-2021",
        "imagens": [FOTO + "CO/CORPO-DE-BORBOLETA-Unica-E101162F-1.jpg", FOTO + "CO/CORPO-DE-BORBOLETA-Unica-C5096C36-2.jpg",
                    FOTO + "CO/CORPO-DE-BORBOLETA-Unica-80DA6FE7-3.jpg"]}


def test_codigo_com_zero_a_esquerda_fica_e_texto_depois_do_ano_tambem():
    r = registro(PAGINAS["05065"])
    assert r["codigo_fabricante"] == "05065"
    assert r["ean"] == "7908295215037"
    assert r["carro"] == "Fiat PALIO G1 2000-2003 EX FIRE; Fiat PALIO WEEKEND G1 2000-2003"
    assert r["imagens"] == [FOTO + "CH/CHAVE-DE-SETA-Unica-C3687642-1.jpg"]


def test_varias_montadoras_e_ano_em_aberto():
    assert veiculos(PAGINAS["61120"]) == (
        "Mercedes-Benz SPRINTER 311 2.2 16V TURBO G1 2002-2004; Mercedes-Benz SPRINTER 311 2.2 16V TURBO G2 2012-2016; "
        "Mercedes-Benz SPRINTER 313 2.2 16V TURBO G1 2004-2012; Mercedes-Benz SPRINTER 313 2.2 16V TURBO G2 2017-2019; "
        "Mercedes-Benz SPRINTER 415 2.2 16V TURBO G2 2013-2019; Mercedes-Benz SPRINTER 314 2.2 16V TURBO G2 Após 2020; "
        "Mercedes-Benz SPRINTER 416 2.2 16V TURBO G2 Após 2020; Mercedes-Benz SPRINTER 516 2.2 16V TURBO G2 Após 2021; "
        "Jeep GRAND CHEROKEE 2.7 20V 5CIL TURBO G2/WJ 2002-2004")


def test_linha_de_motor_e_codigos_equivalentes_nao_viram_aplicacao():
    assert veiculos(PAGINAS["16080"]) == ("Citroen AIRCROSS 1.5 8V 2010-2018; Citroen C3 1.5 8V 2012-2017; "
                                          "Citroen C3 PICASSO 1.5 8V 2012-2015; Peugeot 208 1.5 8V 2012-2018")
    assert veiculos(PAGINAS["7219"]) == "Peugeot 206 1.0 16V 2001-2006; Renault CLIO 1.0 16V 2001-2005"


def test_montadora_com_sigla_e_nome_vira_o_nome():
    assert veiculos(PAGINAS["50825"]) == (
        "Chevrolet IPANEMA 2.0 8V 1989-1994 MULTIPONTO; Chevrolet KADETT 2.0 8V 1989-1994 MULTIPONTO; "
        "Chevrolet MONZA 2.0 8V 1990-1994 MULTIPONTO; Volkswagen GOL GTI 2.0 8V 1989-1997; "
        "Volkswagen QUANTUM 2.0 8V 1989-1993; Volkswagen SANTANA 2.0 8V 1989-1993")


def test_lista_inteira_numa_pagina_so():
    assert "limit=" in catalogo_ymax.LISTA and int(catalogo_ymax.LISTA.split("limit=")[1].split("&")[0]) >= 5000


def test_produto_sem_aplicacao_fica_sem_carro():
    pagina = PAGINAS["7219"].replace("206 1.0 16V 2001 > 2006", "").replace("CLIO 1.0 16V 2001 > 2005", "")
    assert veiculos(pagina) is None


def test_imagem_padrao_sem_foto_e_descartada():
    pagina = PAGINAS["7219"].replace("data/Produtos/CO/CORPO-DE-BORBOLETA-Unica-793D6241-1-1000x1000.jpg.webp",
                                     "no_image-1000x1000.png")
    assert registro(pagina)["imagens"] == []


@pytest.mark.parametrize("ean", ["", "7908295207439", "0000000000000"])
def test_ean_invalido_fica_nulo(ean):
    pagina = PAGINAS["7219"].replace("</strong> 7908295207438<", f"</strong> {ean}<")
    assert registro(pagina)["ean"] is None


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
    monkeypatch.setattr(catalogo_ymax.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_ymax, "ritmo", catalogo_ymax.Ritmo(0))

    def usar(respostas):
        sessao = _Sessao(respostas)
        monkeypatch.setattr(catalogo_ymax, "sessao", lambda: sessao)
        return sessao
    return usar, esperas


def test_erro_de_conexao_e_500_sao_tentados_de_novo(rede):
    usar, esperas = rede
    sessao = usar([requests.ConnectionError("recusada"), _Resposta(502), _Resposta(200, "ok")])
    assert catalogo_ymax.pedir(BASE) == "ok"
    assert [e for e in esperas if e] == [5, 15] and len(sessao.urls) == 3


def test_404_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404)])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_ymax.pedir(BASE)
    assert not any(esperas)


def test_ja_feitos_le_os_ids_gravados_e_ignora_linha_cortada(tmp_path):
    arq = tmp_path / "ymax.jsonl"
    assert catalogo_ymax.ja_feitos(arq) == set()
    arq.write_text('{"url": "https://www.ymdistribuidora.com.br/corpo-de-borboleta-5443"}\n{"url": "https://x/', encoding="utf-8")
    assert catalogo_ymax.ja_feitos(arq) == {"5443"}
