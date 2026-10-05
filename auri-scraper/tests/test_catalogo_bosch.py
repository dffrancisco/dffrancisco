import copy
import json
from pathlib import Path

import pytest
import requests

import catalogo_bosch
from catalogo_bosch import carro, confere, fotos, montadoras_para_ler, numeros_no_nome, registro, termos

# respostas reais da API da Bosch (ps.am.dxtservice.com), com descrição e números OE encurtados
PRODUTOS = json.loads((Path(__file__).parent / "dados/bosch_produtos.json").read_text(encoding="utf-8"))
FOTO = "https://emea.resource.bosch.com/AA/internet/enfinity/img/products/"


def _veiculos(numero, ident, montadora):
    return [(montadora, PRODUTOS[numero]["veiculos"][ident])]


def test_registro_com_numero_sem_espaco_fotos_na_ordem_do_site_e_aplicacao():
    p = PRODUTOS["0280156439"]
    assert registro(p["detalhe"], _veiculos("0280156439", "FIA", "Fiat")) == {
        "site": "bosch",
        "url": "https://am.boschaftermarket.com/br/pt/pe%C3%A7as/product-search.html?prodKey=0280156439",
        "nome": "Válvula de injeção, gasolina", "marca": "BOSCH", "codigo_fabricante": "0280156439", "ean": None,
        "imagens": [FOTO + f"0280156439{f}WHCO0000LA.jpg" for f in ("PH17", "PH01", "PH07", "PH13", "PH19")],
        "carro": "Fiat Palio 1.0 MPI 8V Flex 2010-2011; Fiat Palio Fire 1.0 MPI 8V Flex 2010-2014; "
                 "Fiat Siena 1.0 Flex 2012-2015; Fiat Siena 1.0 MPI 8V Flex 2010-2012; Fiat Siena Fire 1.0 MPI 8V Flex 2010-2012"}


def test_codigo_com_letras_e_zero_a_esquerda_fica_como_a_bosch_escreve():
    assert registro(PRODUTOS["F000KE0P11"]["detalhe"], [])["codigo_fabricante"] == "F000KE0P11"
    assert registro(PRODUTOS["0986B01016"]["detalhe"], [])["codigo_fabricante"] == "0986B01016"


def test_sem_aplicacao_fica_sem_carro():
    assert registro(PRODUTOS["F000KE0P11"]["detalhe"], [])["carro"] is None


def test_fotos_sem_desenho_tecnico_nem_repetidas():
    assert fotos(PRODUTOS["0280130039"]["detalhe"]) == [
        FOTO + f"0280130039{f}WHCO0000.jpg" for f in ("PH04", "PHAN", "PH01", "PH07", "PH13", "PH19", "PHA0")]


def test_fotos_seguem_a_sequencia_e_nao_a_ordem_da_resposta():
    detalhe = copy.deepcopy(PRODUTOS["F000KE0P11"]["detalhe"])
    detalhe["images"].reverse()
    assert [u.rsplit("/", 1)[1][10:14] for u in fotos(detalhe)] == ["PH23", "PH01", "PH07", "PH13", "PH19", "PH25"]


def test_mesmo_modelo_em_varias_carrocerias_junta_os_anos():
    assert carro(_veiculos("0280130039", "VWW", "Volkswagen")) == (
        "Volkswagen Caravelle T4 2.8 1996-2000; Volkswagen Corrado 2.8 1991-1993; Volkswagen Golf III 1.6 1994-1997; "
        "Volkswagen Kombi 1.6 Mi 1997-2005")


def test_ano_final_em_aberto_vira_apos():
    veiculos = copy.deepcopy(PRODUTOS["0986B01016"]["veiculos"]["AGL"])
    veiculos[6]["productionPeriod"]["to"] = None  # Marrua 2.8 D, 2005-2011
    assert "Agrale Marrua 2.8 D após 2005" in carro([("Agrale", veiculos)]).split("; ")


def test_onibus_e_caminhao_da_montadora_entram_na_aplicacao():
    texto = carro(_veiculos("0986B01016", "AGL", "Agrale"))
    assert texto.startswith("Agrale 6000 2000-2005; Agrale A5 2.8 D 2002-2005; ")
    assert "Agrale Furgovan 6000 E-tronic 2005-2011" in texto


def test_montadoras_do_brasil_com_nome_do_mercado_e_as_de_fora_ignoradas():
    lidas, ignoradas = montadoras_para_ler(PRODUTOS["0280130039"]["montadoras"])
    assert lidas == [("ALF", "Alfa Romeo", ["0280130039"], None), ("VWW", "Volkswagen", ["0280130039"], None)]
    assert ignoradas == ["GAZ", "MMZ (MINSK MOTOREN WERK)", "OPEL"]
    lidas, _ = montadoras_para_ler(PRODUTOS["0986B01016"]["montadoras"])
    assert [(i, nome) for i, nome, _, _ in lidas] == [("AGL", "Agrale"), ("CHE", "Chevrolet"), ("MAP", "Marcopolo"),
                                                      ("NIS", "Nissan"), ("TRL", "Troller"), ("VWW", "Volkswagen")]


def test_montadora_com_numero_oe_relevante_passa_o_numero_do_produto():
    resposta = copy.deepcopy(PRODUTOS["0280156439"]["montadoras"])
    resposta["oeNumbersRelevant"] = True
    assert montadoras_para_ler(resposta)[0] == [("FIA", "Fiat", ["0280156439"], "0280156439")]


@pytest.mark.parametrize("catalogo, esperado", [
    ("0986450235", ["0986450235"]),
    ("SP08 / 0242235661", ["SP08", "0242235661"]),
    ("SP22 { }", ["SP22"]),
    ("SP06*", ["SP06"]),
    ("0280157104 /0280157151", ["0280157104", "0280157151"]),
    ("1465ZS0033/0928400826", ["1465ZS0033", "0928400826"]),
    ("3397016732 (AF28M)", ["3397016732", "AF28M"]),
    ("0986221066 /EBI7022 { ]", ["0986221066", "EBI7022"]),
    ("0280150504 LARANJA", ["0280150504"]),
    ("0445116034/035", ["0445116034"]),  # '035' é o fim abreviado do outro número
    ("DOT4 0204032339", ["DOT4", "0204032339"]),
    ("LUA MARWAL", []),
    ("USAR CADASTRO", []),
    ("", []),
])
def test_termos_do_campo_catalogo(catalogo, esperado):
    assert termos(catalogo) == esperado


@pytest.mark.parametrize("nome, esperado", [
    ("VELA IGN F000KE0P06 (BKUR6ET-10)", ["F000KE0P06"]),
    ("PEDAL ACELERADOR 0280755067(508) { }", ["0280755067"]),
    ("MED FLUXO AR 0280218209 / 0280218423 { }", ["0280218209", "0280218423"]),
    ("ELETROVENTILADOR RADIADOR F006B10095", ["F006B10095"]),
    ("KIT BICOS INJETORES ORIGINAL GOLF JETTA TIGUAN 1.4 TSI", []),
    ("FILTRO COMB FLEXIVELXX", []),
])
def test_numeros_bosch_escritos_no_nome(nome, esperado):
    assert numeros_no_nome(nome) == esperado


def test_confere_pelo_numero_e_pelos_codigos_curtos_da_ficha():
    assert confere("F000KE0P11", PRODUTOS["F000KE0P11"]["detalhe"])
    assert confere("SP11", PRODUTOS["F000KE0P11"]["detalhe"])  # "Número de busca (KSN)": "Sp 11"
    assert confere("W9B", PRODUTOS["F000KE0P11"]["detalhe"])  # "Designação": "W 9 B+", só letras e dígitos contam
    assert confere("FR78", PRODUTOS["0242232801"]["detalhe"])  # "Designação": "FR 78"
    assert confere("OB1016", PRODUTOS["0986B01016"]["detalhe"])  # "Abreviação comercial (HKB)": "OB 1016"
    assert not confere("SP12", PRODUTOS["F000KE0P11"]["detalhe"])
    assert not confere("0280", PRODUTOS["0280156439"]["detalhe"])


class _Api:
    """Responde caminhos da API a partir de um dicionário e guarda o que foi pedido."""
    def __init__(self, respostas):
        self.respostas, self.pedidos = respostas, []

    def __call__(self, caminho):
        self.pedidos.append(caminho)
        return copy.deepcopy(self.respostas.get(caminho.split("?")[0]))


def _busca(*numeros):
    return {"foundResults": len(numeros), "hasMoreData": False, "products": [{"productNumber": n} for n in numeros]}


def test_achar_pelo_numero_nao_abre_ficha_de_outros_resultados(monkeypatch):
    api = _Api({"/search/0580314419": _busca("0580314419", "F000TE102Z")})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    assert catalogo_bosch.achar("0580314419", {}) == [("0580314419", "número")]
    assert len(api.pedidos) == 1


def test_achar_codigo_curto_confere_a_ficha_dos_resultados(monkeypatch):
    api = _Api({"/search/FR78": _busca("0241Z10401", "0242232801"),
                "/search-details/0241Z10401": {"productNumber": "0241Z10401", "specificationTabData": []},
                "/search-details/0242232801": PRODUTOS["0242232801"]["detalhe"]})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    fichas = {}
    assert catalogo_bosch.achar("FR78", fichas) == [("0242232801", "código curto")]
    assert set(fichas) == {"0241Z10401", "0242232801"}  # a ficha lida fica guardada para o registro


def test_codigo_curto_com_zero_tambem_e_buscado_sem_o_zero(monkeypatch):
    # a busca não acha "SP06"; a ficha do F000KE0P06 traz "Número de busca (KSN)": "Sp 6"
    detalhe = copy.deepcopy(PRODUTOS["F000KE0P11"]["detalhe"])
    detalhe["productNumber"] = "F000KE0P06"
    for linha in detalhe["specificationTabData"]:
        if linha["columnData"][0] == "Número de busca (KSN)":
            linha["columnData"][1] = "Sp 6"
    api = _Api({"/search/SP06": _busca(), "/search/SP6": _busca("F000KE0P06"), "/search-details/F000KE0P06": detalhe})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    assert catalogo_bosch.achar("SP06", {}) == [("F000KE0P06", "código curto")]


def test_codigo_curto_achado_de_primeira_nao_tenta_sem_o_zero(monkeypatch):
    api = _Api({"/search/SP11": _busca("F000KE0P11"), "/search-details/F000KE0P11": PRODUTOS["F000KE0P11"]["detalhe"]})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    assert catalogo_bosch.achar("SP11", {}) == [("F000KE0P11", "código curto")]
    assert len(api.pedidos) == 2


def test_achar_numero_que_a_busca_nao_devolve_nao_abre_fichas(monkeypatch):
    api = _Api({"/search/0280": _busca("0258986502")})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    assert catalogo_bosch.achar("0280", {}) == []
    assert len(api.pedidos) == 1


def test_item_da_lista_cai_para_o_numero_do_nome_quando_o_catalogo_nao_acha(monkeypatch):
    api = _Api({"/search/D9BC": _busca(), "/search/9240081510": _busca("9240081510")})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    item = {"cod": "925", "catalogo": "D9BC", "nome": "VELA IGN 9240081510 { }"}
    assert catalogo_bosch.achar_item(item, {}) == [("9240081510", "nome")]


def test_numero_do_nome_diferente_do_catalogo_tambem_e_buscado(monkeypatch):
    api = _Api({"/search/0280218002": _busca("0280218002"), "/search/F00099G002": _busca("F00099G002")})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    item = {"cod": "1421", "catalogo": "0280218002", "nome": "MED FLUXO AR 0280218002 / F00099G002"}
    assert catalogo_bosch.achar_item(item, {}) == [("0280218002", "número"), ("F00099G002", "nome")]
    assert len(api.pedidos) == 2  # o número que já estava no catálogo não é buscado de novo


def test_item_da_lista_busca_todos_os_codigos_do_catalogo(monkeypatch):
    api = _Api({"/search/SP11": _busca("F000KE0P11"), "/search/0242235661": _busca("0242235661"),
                "/search-details/F000KE0P11": PRODUTOS["F000KE0P11"]["detalhe"]})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    item = {"cod": "1", "catalogo": "SP11 / 0242235661", "nome": "VELA IGN F000KE0P11"}
    assert catalogo_bosch.achar_item(item, {}) == [("F000KE0P11", "código curto"), ("0242235661", "número")]


def test_ler_produto_monta_o_registro_com_a_aplicacao_das_montadoras_do_brasil(monkeypatch):
    p = PRODUTOS["0280130039"]
    api = _Api({"/search-details/0280130039": p["detalhe"], "/usage-in-vehicles/0280130039/makers": p["montadoras"],
                "/usage-in-vehicles/0280130039/vehicles/VWW": {"vehicles": p["veiculos"]["VWW"]}})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    ignoradas = set()
    r = catalogo_bosch.ler_produto("0280130039", {}, ignoradas)
    assert r["carro"].startswith("Volkswagen Caravelle T4 2.8 1996-2000; ")
    assert ignoradas == {"GAZ", "MMZ (MINSK MOTOREN WERK)", "OPEL"}
    assert "/usage-in-vehicles/0280130039/vehicles/ALF" in api.pedidos  # sem resposta: Alfa Romeo fica sem veículos


def test_produto_sem_foto_nao_vira_registro_nem_consulta_a_aplicacao(monkeypatch):
    detalhe = dict(PRODUTOS["F000KE0P11"]["detalhe"], images=[])  # F000KE0P22 vem assim no catálogo mundial
    api = _Api({"/search-details/F000KE0P11": detalhe})
    monkeypatch.setattr(catalogo_bosch, "api", api)
    assert catalogo_bosch.ler_produto("F000KE0P11", {}, set()) is None
    assert api.pedidos == ["/search-details/F000KE0P11?queryPIM=false"]


def test_produto_sem_ficha_nao_vira_registro(monkeypatch):
    monkeypatch.setattr(catalogo_bosch, "api", _Api({}))
    assert catalogo_bosch.ler_produto("0000000000", {}, set()) is None


class _Resposta:
    def __init__(self, status, corpo, tipo="application/json"):
        self.status_code, self.text, self.headers = status, corpo, {"content-type": tipo}

    def json(self):
        return json.loads(self.text)


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
    monkeypatch.setattr(catalogo_bosch.time, "sleep", esperas.append)
    monkeypatch.setattr(catalogo_bosch, "INTERVALO", 0)
    monkeypatch.setattr(catalogo_bosch, "_sessao", None)

    def usar(respostas):
        sessoes = []

        def nova():
            sessoes.append(_Sessao(respostas))
            return sessoes[-1]
        monkeypatch.setattr(catalogo_bosch.requests, "Session", nova)
        return sessoes
    return usar, esperas


def test_conexao_recusada_429_e_500_sao_tentados_de_novo_com_espera_crescente(rede):
    usar, esperas = rede
    sessoes = usar([requests.ConnectionError("recusada"), _Resposta(429, ""), _Resposta(500, ""),
                    _Resposta(200, '{"foundResults": 0, "products": []}')])
    assert catalogo_bosch.api("/search/SP11?pageNumber=1") == {"foundResults": 0, "products": []}
    assert esperas == [5, 15, 30]
    assert len(sessoes) == 1
    assert sessoes[0].urls[0] == "https://ps.am.dxtservice.com/ps/api/pt/br/search/SP11?pageNumber=1"


def test_pagina_de_erro_em_html_vira_none_sem_insistir(rede):
    usar, esperas = rede
    usar([_Resposta(200, '<div class="A-Callout A-Callout--error">An unexpected server error</div>', "text/html")])
    assert catalogo_bosch.api("/usage-in-vehicles/X/vehicles/Y") is None
    assert esperas == []


def test_erro_4xx_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Resposta(404, "")])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_bosch.api("/search-details/X")
    assert esperas == []


def test_desiste_depois_de_cinco_tentativas(rede):
    usar, esperas = rede
    usar([requests.Timeout("lento")] * 5)
    with pytest.raises(RuntimeError, match="lento"):
        catalogo_bosch.api("/search/X")
    assert esperas == [5, 15, 30, 60]


def test_itens_bosch_da_lista_de_pendentes(tmp_path):
    lista = tmp_path / "pendentes.csv"
    lista.write_text("cod;ean;catalogo;marca;nome;grupo\n"
                     "9;;0986450235;BOSCH;FILTRO COMB 0986450235;FILTROS\n"
                     "19;0000000000628;1250978A;ORIGINAL SI;BOMB COMB COMPLETA 1250978A;INJECAO\n"
                     "76;4047024656642;SP22 { };Bosch;VELA IGN F000KE0P22(BPR6EFS) { };IGNICAO\n", encoding="utf-8")
    assert [i["cod"] for i in catalogo_bosch.itens_da_lista(lista)] == ["9", "76"]


def test_retoma_pulando_numeros_ja_gravados(tmp_path):
    saida = tmp_path / "bosch.jsonl"
    saida.write_text(json.dumps({"codigo_fabricante": "0280156439"}) + "\n" + '{"codigo_fab', encoding="utf-8")
    assert catalogo_bosch.ja_gravados(saida) == {"0280156439"}
    assert catalogo_bosch.ja_gravados(tmp_path / "nao_existe.jsonl") == set()
