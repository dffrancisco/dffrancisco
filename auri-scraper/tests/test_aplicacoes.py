from helper.aplicacoes import aplicacoes_do_anuncio, casar_modelo, juntar_aplicacoes

VOCAB = {"GOL": "GOL", "PARATI": "PARATI", "PALIO": "PALIO", "CORSA": "CORSA", "CORSA WAGON": "CORSA WAGON",
         "LOGAN": "LOGAN", "UNIVERSAL": "UNIVERSAL"}


def _anuncio(**k):
    base = {"carro": None, "aplicacoes": [], "nome": "", "observacoes": []}
    base.update(k)
    return base


def test_casar_modelo_prefixo_mais_longo():
    assert casar_modelo("CORSA WAGON", VOCAB) == ("CORSA WAGON", True)
    assert casar_modelo("CORSA SEDAN GL", VOCAB) == ("CORSA", True)
    assert casar_modelo("HILUX SRV", VOCAB) == ("HILUX SRV", False)


def test_texto_carblue():
    linhas = aplicacoes_do_anuncio(_anuncio(carro="GOL G2 96 97 98; PARATI G2 95"), VOCAB)
    assert {(l["modelo"], l["ano_inicio"], l["ano_fim"], l["montadora"]) for l in linhas} == {
        ("GOL", 1996, 1998, None), ("PARATI", 1995, 1995, None)}
    assert all(l["modelo_reconhecido"] for l in linhas)
    assert linhas[0]["texto_original"].startswith("GOL G2")


def test_texto_shoppecas_com_montadora_e_aberto():
    linhas = aplicacoes_do_anuncio(_anuncio(carro="Fiat: Palio 01 a 12, Siena Após 08"), VOCAB)
    por_modelo = {l["modelo"]: l for l in linhas}
    assert por_modelo["PALIO"]["montadora"] == "FIAT" and por_modelo["PALIO"]["ano_fim"] == 2012
    assert por_modelo["SIENA"]["ano_inicio"] == 2008 and por_modelo["SIENA"]["ano_fim"] is None
    assert por_modelo["SIENA"]["modelo_reconhecido"] is False


def test_estruturada_do_produto_json_tem_prioridade_sobre_o_texto():
    a = _anuncio(carro="GOL 2000", aplicacoes=[{"montadora": "FIAT", "veiculo": "PALIO ELX", "motor": "FIRE 1.0 L 8V",
                                                 "ano_inicio": 2007, "ano_fim": 2009}])
    linhas = aplicacoes_do_anuncio(a, VOCAB)
    assert linhas == [{"montadora": "FIAT", "modelo": "PALIO", "ano_inicio": 2007, "ano_fim": 2009, "motor": "1.0",
                       "observacao": None, "texto_original": "FIAT PALIO ELX FIRE 1.0 L 8V 2007-2009",
                       "modelo_reconhecido": True}]


def test_observacao_vem_das_observacoes_do_anuncio():
    linhas = aplicacoes_do_anuncio(_anuncio(carro="LOGAN 2010", observacoes=["LADO ESQUERDO"]), VOCAB)
    assert linhas[0]["observacao"] == "LADO ESQUERDO"


def test_juntar_aplicacoes_ignora_montadora_ausente():
    a = {"montadora": None, "modelo": "GOL", "ano_inicio": 1996, "ano_fim": 1998, "motor": None}
    b = {"montadora": "VOLKSWAGEN", "modelo": "GOL", "ano_inicio": 1999, "ano_fim": 2001, "motor": None}
    out = juntar_aplicacoes([dict(x, observacao=None, texto_original="", modelo_reconhecido=True) for x in (a, b)])
    assert [(o["montadora"], o["ano_inicio"], o["ano_fim"]) for o in out] == [("VOLKSWAGEN", 1996, 2001)]


def test_juntar_aplicacoes_une_faixas_adjacentes_e_sobrepostas():
    a = {"montadora": "VW", "modelo": "GOL", "ano_inicio": 1996, "ano_fim": 1998, "motor": None}
    b = {"montadora": "VW", "modelo": "GOL", "ano_inicio": 1999, "ano_fim": 2001, "motor": None}
    c = {"montadora": "VW", "modelo": "GOL", "ano_inicio": 2005, "ano_fim": 2008, "motor": None}
    d = {"montadora": "VW", "modelo": "GOL", "ano_inicio": 1997, "ano_fim": 2000, "motor": "1.6"}
    out = juntar_aplicacoes([dict(x, observacao=None, texto_original="", modelo_reconhecido=True) for x in (a, b, c, d)])
    faixas = sorted(((o["motor"], o["ano_inicio"], o["ano_fim"]) for o in out), key=lambda f: (f[0] or "", f[1]))
    assert faixas == [(None, 1996, 2001), (None, 2005, 2008), ("1.6", 1997, 2000)]


def test_sem_aplicacao():
    assert aplicacoes_do_anuncio(_anuncio(), VOCAB) == []
