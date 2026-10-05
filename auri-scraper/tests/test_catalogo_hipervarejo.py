import copy
import json
import threading
from pathlib import Path

import pytest
from curl_cffi import CurlError

import catalogo_hipervarejo
from catalogo_hipervarejo import registros

# produtos reais da API da Hipervarejo (sem a descrição e os campos que o catálogo não usa)
PRODUTOS = {p["productId"]: p for p in json.loads((Path(__file__).parent / "dados/hipervarejo_produtos.json").read_text(encoding="utf-8"))}
FOTO = "https://fortbras.vteximg.com.br/arquivos/ids/"


def test_arteb_sem_o_sufixo_da_loja_um_registro_por_lado_com_o_lado_da_variacao():
    regs = list(registros(PRODUTOS["63882"]))
    assert [(r["url"], r["nome"], r["codigo_fabricante"], r["ean"]) for r in regs] == [
        ("https://hipervarejo.com.br/lanterna-traseira-chevrolet-s10-2012-a-2018-cristal-vermelho-sem-luz-de-neblina-arteb/p?skuId=2054",
         "Lanterna Traseira Chevrolet S10 2012 a 2018 Cristal Vermelho Sem Luz de Neblina Arteb - Lado Esquerdo Motorista",
         "0460447", "7896482546753"),
        ("https://hipervarejo.com.br/lanterna-traseira-chevrolet-s10-2012-a-2018-cristal-vermelho-sem-luz-de-neblina-arteb/p?skuId=341211",
         "Lanterna Traseira Chevrolet S10 2012 a 2018 Cristal Vermelho Sem Luz de Neblina Arteb - Lado Direito Passageiro",
         "0460448", None)]
    assert regs[0]["site"] == "hipervarejo" and regs[0]["marca"] == "Arteb"
    assert regs[0]["carro"] == "CHEVROLET S10 2012-2018"
    assert regs[0]["imagens"][0] == FOTO + "330028/lanterna-traseira-chevrolet-s10-2012-a-2018-motorista-cristal-vermelho-sem-luz-de-neblina-arteb-hipervarejo-1.jpg"
    assert len(regs[0]["imagens"]) == 5


def test_refid_interno_da_loja_da_lugar_ao_codigo_da_ficha():
    [r] = registros(PRODUTOS["58819"])  # RefId 0636397; o nome fala em 0160275, mas a ficha, a foto e o EAN são do 0160594
    assert r == {"site": "hipervarejo", "url": "https://hipervarejo.com.br/farol-de-milha-chevrolet-zafira-2004-a-2010-passageiro-arteb-0160275/p",
                 "nome": "Farol de Milha Chevrolet Zafira 2004 a 2010 Passageiro Arteb 0160275", "marca": "Arteb",
                 "codigo_fabricante": "0160594", "ean": "7896482538413",
                 "imagens": [FOTO + f"{n}/farol-de-milha-chevrolet-zafira-2004-a-2010-passageiro-arteb-0160594-hipervarejo-{i}.jpg.jpg"
                             for i, n in enumerate(range(503488, 503492), 1)],
                 "carro": "CHEVROLET ZAFIRA 2004-2010"}


def test_refid_interno_sem_ficha_usa_o_codigo_depois_da_marca_no_nome():
    [r] = registros(PRODUTOS["58783"])  # 'Farol de Milha Corsa Meriva Montana Motorista Arteb 0160275'
    assert r["codigo_fabricante"] == "0160275"
    assert r["carro"] == "CHEVROLET CORSA; CHEVROLET MERIVA; CHEVROLET MONTANA"


def test_takao_codigo_da_ficha_e_ean_da_loja_fora():
    [valvula] = registros(PRODUTOS["9542055"])
    assert valvula["codigo_fabricante"] == "VADVW18A"
    assert valvula["ean"] is None  # 7910052144740: o prefixo 791 não é de ninguém no GS1, é numeração da loja
    [pistao] = registros(PRODUTOS["9532392"])
    assert pistao["codigo_fabricante"] == "PGM18 0.50"  # a medida faz parte do código


def test_codigo_igual_ao_refid():
    [r] = registros(PRODUTOS["227517"])
    assert (r["codigo_fabricante"], r["ean"]) == ("SE31142", "7890903022659")
    assert r["carro"].startswith("FIAT UNO MILLE CELEB. WAY ECON. 2009-2013 1.0 F.FLEX 2P; ")


def test_variacao_da_loja_perde_o_var_e_o_indice():
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["236597"])] == ["SE30829"]  # VARSE30829_1


def test_variacao_com_indice_colado_volta_o_zero_que_a_ficha_perdeu():
    assert [r["codigo_fabricante"] for r in registros(PRODUTOS["266374"])] == ["0280157133"]  # VAR02801571331 / 280157133


def test_codigo_do_fabricante_da_ficha_vale_mais_que_a_lista_de_equivalentes():
    [r] = registros(PRODUTOS["325339"])  # RefId interno 0672180; Número de peça traz equivalentes de outras marcas
    assert r["codigo_fabricante"] == "0092S58048"


def test_kit_montado_pela_loja_e_ignorado():
    assert list(registros(PRODUTOS["317928"])) == []  # SKHG33036_C1: 4 amortecedores
    assert list(registros(PRODUTOS["195649"])) == []  # HG33036_D: 2 amortecedores dianteiros


def test_sku_sem_foto_e_ignorado():
    produto = copy.deepcopy(PRODUTOS["63882"])
    produto["items"][0]["images"] = []
    assert [r["codigo_fabricante"] for r in registros(produto)] == ["0460448"]


def test_ean_do_item_diferente_do_da_ficha_fica_de_fora():
    produto = copy.deepcopy(PRODUTOS["227517"])
    produto["Código de barras (EAN)"] = ["7890903022666"]
    assert next(registros(produto))["ean"] is None
    produto["items"][0]["ean"] = ""
    assert next(registros(produto))["ean"] == "7890903022666"


@pytest.mark.parametrize("marca, ref, ficha, esperado", [
    ("Ampri", "27043_AMP", [], "27043"),
    ("Cobreq", "N2005COB", ["N2005COB"], "N2005"),  # a ficha repete o RefId
    ("Cobreq", "N1804C_COB", ["N-1804C"], "N-1804C"),  # grafia da ficha
    ("3RHO", "VAR88093RHO20", ["8809"], "8809"),
    ("Aliperti", "VARAL8404_ALI_1", ["AL8404 ALI"], "AL8404"),
    ("Axios", "531X2712_AXI", ["AXIOS 531.2712", "COFAP BTC08126"], "531.2712"),  # '.' virou X no RefId
    ("Axios", "312X679_AXI", ["031.2679"], "031.2679"),
    ("MANN-FILTER", "VARCU4251W11", ["CU4251/1"], "CU4251/1"),  # '/' virou W
    ("Denso", "BC261470Z1220RC", ["BC261470-1220RC"], "BC261470-1220RC"),  # '-' virou Z
    ("Bosch", "VARF000KE0P111", ["F000KE0P11"], "F000KE0P11"),
    ("Bosch", "VARF000KE0P111", [], None),  # sem ficha não dá para separar o índice
    ("Takao", "ASD18_STD", [], "ASD18 STD"),  # STD é a medida, faz parte do código
    ("Axios", "BR10504401649", ["BR10504401649"], None),  # código interno da loja
    ("Cofap", "KTC03203_COF", ["KTC03203"], "KTC03203"),  # KTC é da Cofap, não kit da loja
])
def test_codigo_fabricante(marca, ref, ficha, esperado):
    produto = {"brand": marca, "productName": "Peça", "Código do fabricante": ficha,
               "items": [{"itemId": "1", "referenceId": [{"Key": "RefId", "Value": ref}]}]}
    assert catalogo_hipervarejo.codigo_fabricante(produto, produto["items"][0]) == esperado


class _Pagina:
    def __init__(self, status, corpo, headers=None):
        self.status, self.headers = status, headers or {}
        self.body = corpo.encode() if isinstance(corpo, str) else corpo


class _Sessao:
    """Responde em ordem; uma exceção na lista é levantada no lugar da resposta."""
    def __init__(self, respostas):
        self.respostas, self.urls = respostas, []

    def get(self, url, **_):
        self.urls.append(url)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def rede(monkeypatch):
    esperas, relogio = [], [100.0]
    monkeypatch.setattr(catalogo_hipervarejo.time, "sleep", lambda s: (esperas.append(s), relogio.__setitem__(0, relogio[0] + s)))
    monkeypatch.setattr(catalogo_hipervarejo.time, "monotonic", lambda: relogio[0])
    monkeypatch.setattr(catalogo_hipervarejo, "_local", threading.local())
    monkeypatch.setattr(catalogo_hipervarejo, "_proxima", 0.0)

    def usar(respostas):
        sessoes = []

        class _Fabrica:
            def __init__(self, **opcoes):
                self.opcoes = opcoes

            def __enter__(self):
                sessoes.append(_Sessao(respostas))
                return sessoes[-1]
        monkeypatch.setattr(catalogo_hipervarejo, "FetcherSession", _Fabrica)
        return sessoes
    return usar, esperas


def _busca(produtos, total):
    return _Pagina(206, json.dumps(produtos), {"resources": f"0-{len(produtos)}/{total}"})


def test_erro_de_conexao_500_e_desafio_429_sao_tentados_de_novo_na_mesma_sessao(rede):
    usar, esperas = rede
    sessoes = usar([CurlError("Connection reset"), _Pagina(500, '"The operation was canceled."'),
                    _Pagina(429, "challenge"), _busca([], 191)])
    assert catalogo_hipervarejo.total("fq=B:2000046") == 191
    assert [e for e in esperas if e >= 5] == [5, 15, 30]
    assert len(sessoes) == 1 and len(sessoes[0].urls) == 4
    assert sessoes[0].urls[0] == f"{catalogo_hipervarejo.BASE}/api/catalog_system/pub/products/search?fq=B:2000046&_from=0&_to=0"


def test_erro_4xx_nao_e_tentado_de_novo(rede):
    usar, esperas = rede
    usar([_Pagina(404, "")])
    with pytest.raises(RuntimeError, match="HTTP 404"):
        catalogo_hipervarejo.api("brand/list")
    assert esperas == []


def test_desiste_depois_de_cinco_tentativas(rede):
    usar, esperas = rede
    usar([CurlError("recusada")] * 5)
    with pytest.raises(RuntimeError, match="recusada"):
        catalogo_hipervarejo.api("brand/list")
    assert [e for e in esperas if e >= 5] == [5, 15, 30, 60]


def test_no_maximo_duas_requisicoes_por_segundo(rede):
    usar, esperas = rede
    usar([_Pagina(200, "[]")] * 3)
    for _ in range(3):
        catalogo_hipervarejo.api("brand/list")
    assert esperas == [0.5, 0.5]


def test_marca_pequena_e_lida_sem_pedir_o_total_a_parte(rede):
    usar, _ = rede
    primeira = [{"productId": str(i)} for i in range(50)]
    sessoes = usar([_busca(primeira, 70), _busca([{"productId": str(i)} for i in range(50, 70)], 70)])
    produtos, total = catalogo_hipervarejo.da_marca(2000046)
    assert total == 70 and len(produtos) == 70
    assert [u.split("?")[1] for u in sessoes[0].urls] == ["fq=B:2000046&_from=0&_to=49", "fq=B:2000046&_from=50&_to=99"]


def test_marca_grande_e_dividida_em_faixas_de_preco_sem_repetir_produto(rede, monkeypatch):
    usar, _ = rede
    monkeypatch.setattr(catalogo_hipervarejo, "LIMITE_BUSCA", 100)
    monkeypatch.setattr(catalogo_hipervarejo, "PRECO_MAXIMO", 100)
    p = [{"productId": str(i)} for i in range(160)]
    usar([_busca(p[:50], 160),  # primeira página: passa do limite
          _busca([], 160),  # faixa 0-100
          _busca([], 90), _busca([], 71),  # faixas 0-50 e 50-100 (o preço 50 sai nas duas)
          _busca(p[:50], 90), _busca(p[50:90], 90),
          _busca(p[89:139], 71), _busca(p[139:160], 71)])
    produtos, total = catalogo_hipervarejo.da_marca(7)
    assert total == 160 and [x["productId"] for x in produtos] == [str(i) for i in range(160)]


def test_marcas_para_ler_sem_repetir_id_e_filtrando_pelo_nome():
    from catalogo_hipervarejo import marcas_para_ler
    lista = [{"id": 1, "name": "Arteb"}, {"id": 1, "name": "Arteb"}, {"id": 2, "name": "Takao"}]
    assert [m["id"] for m in marcas_para_ler(lista)] == [1, 2]
    assert [m["id"] for m in marcas_para_ler(lista, "takao")] == [2]
    with pytest.raises(SystemExit):
        marcas_para_ler(lista, "Nenhuma")


def test_marca_lida_vira_registros_na_thread_e_nao_guarda_o_produto_bruto(rede):
    usar, _ = rede
    usar([_busca([PRODUTOS["63882"]], 1)])
    n, lidos = catalogo_hipervarejo.registros_da_marca(2000046)
    assert n == 1 and [pid for pid, _ in lidos] == ["63882"]
    assert lidos[0][1] == list(registros(PRODUTOS["63882"]))


def test_parcial_guarda_cada_marca_e_ignora_a_ultima_linha_cortada(tmp_path):
    parcial = tmp_path / "hipervarejo.parcial.jsonl"
    catalogo_hipervarejo.gravar_parcial(parcial, 7, 2, [("1", [{"codigo_fabricante": "A"}]), ("2", [])])
    catalogo_hipervarejo.gravar_parcial(parcial, 9, 1, [("3", [{"codigo_fabricante": "B"}])])
    with parcial.open("a", encoding="utf-8") as f:
        f.write('{"marca": 11, "n": 5, "lid')  # interrompido no meio da escrita
    assert catalogo_hipervarejo.ler_parcial(parcial) == {
        7: (2, [("1", [{"codigo_fabricante": "A"}]), ("2", [])]), 9: (1, [("3", [{"codigo_fabricante": "B"}])])}
    assert catalogo_hipervarejo.ler_parcial(tmp_path / "nao_existe.jsonl") == {}
