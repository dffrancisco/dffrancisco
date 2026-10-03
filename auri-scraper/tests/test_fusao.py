from pathlib import Path

from helper.banco import abrir
from helper.fusao import atualizar_hash, fundir, gravar
from helper.marcas import Marcas
from helper.topcar import Estatisticas

CSV = Path(__file__).resolve().parents[1] / "helper_marcas.csv"
VOCAB = {"GOL": "GOL", "PALIO": "PALIO", "LOGAN": "LOGAN"}


def _m():
    return Marcas.carregar(CSV)


def _a(site, url, nome, marca, codigo, ean=None, carro=None, prioridade=5, imagens=(), equivalentes=(), aplicacoes=()):
    return {"site": site, "url": url, "nome": nome, "marca": marca, "codigo": codigo, "ean": ean, "carro": carro,
            "aplicacoes": list(aplicacoes), "equivalentes": list(equivalentes), "observacoes": [],
            "imagens": [{"url": u, "arquivo_local": None, "principal": i == 0} for i, u in enumerate(imagens)],
            "coletado_em": "2026-10-01", "prioridade": prioridade}


def _fundir(anuncios):
    return fundir(anuncios, _m(), VOCAB, Estatisticas([]))


def test_zero_a_esquerda_funde_so_com_ean_e_fica_com_zero():
    pecas, conflitos = _fundir([
        _a("auri", "https://auri/1", "FAROL GOL 0160818 ARTEB", "ARTEB", "0160818", ean="7898252655139", prioridade=0),
        _a("autonext", "https://an/1", "Farol Gol Arteb 160818", "Arteb", "160818", ean="7898252655139", prioridade=0)])
    assert len(pecas) == 1
    p = pecas[0]
    assert p["codigo"] == "0160818" and p["chave"] == "ARTEB|0160818"
    assert all(v != "160818" for _, v, _ in p["alternativos"])
    assert {o["url"] for o in p["origens"]} == {"https://auri/1", "https://an/1"}
    assert conflitos == []


def test_zero_a_esquerda_sem_ean_nao_funde():
    pecas, _ = _fundir([_a("auri", "https://auri/1", "FAROL", "ARTEB", "0160818"),
                        _a("autonext", "https://an/1", "FAROL", "ARTEB", "160818")])
    assert sorted(p["codigo"] for p in pecas) == ["0160818", "160818"]


def test_kit_desmembrado_em_alternativos():
    pecas, _ = _fundir([_a("hipervarejo", "https://h/1", "KIT LANTERNA", "ARTEB", "0460361 + 0460362")])
    assert pecas[0]["codigo"] == "0460361/0460362"
    assert {("kit", "0460361", 1), ("kit", "0460362", 1)} <= set(pecas[0]["alternativos"])
    assert pecas[0]["ean"] is None


def test_ean_divergente_mesmo_codigo_vira_alternativo_e_conflito():
    pecas, conflitos = _fundir([
        _a("karhub", "https://k/1", "Cabo Vela", "Gauss", "GC5045", ean="7898252655139"),
        _a("carblue", "https://c/1", "Cabo Vela", "GAUSS", "GC5045", ean="7898252655139"),
        _a("shoppecas", "https://s/1", "Cabo Vela", "Gauss", "GC5045", ean="7898252655979")])
    p = pecas[0]
    assert p["ean"] == "7898252655139" and ("ean", "7898252655979", 1) in p["alternativos"]
    assert conflitos == [{"tipo": "ean", "chave": "GAUSS|GC5045", "valores": ["7898252655139", "7898252655979"],
                          "escolhido": "7898252655139"}]


def test_karhub_e_carblue_mesma_peca_descricao_da_fonte_prioritaria_e_fotos_em_ordem():
    pecas, _ = _fundir([
        _a("carblue", "https://c/1", "CABO VELA GOL 1.0 8V GC5045", "GAUSS", "GC5045", prioridade=4, imagens=["https://c/a.jpg"]),
        _a("karhub", "https://k/1", "Jogo Cabo De Vela - Gauss - Gc5045", "Gauss", "GC5045", prioridade=2,
           imagens=["https://k/a.jpg", "https://c/a.jpg"])])
    p = pecas[0]
    assert p["desc_curta"] == "JOGO CABO VELA" and p["qtd_fontes"] == 2
    assert [f["url"] for f in p["fotos"]] == ["https://k/a.jpg", "https://c/a.jpg"]  # karhub primeiro, sem repetir
    assert p["unidade_sugerida"] == "JG" and p["tipo_peca"] == "CABO VELA"


def test_equivalentes_viram_ean_ou_original():
    pecas, _ = _fundir([_a("auri", "https://auri/1", "AMORTECEDOR", "COFAP", "BTC01104",
                           equivalentes=["7891579301901", "8200 123 456"])])
    assert {("ean", "7891579301901", 1), ("original", "8200123456", 1)} <= set(pecas[0]["alternativos"])


def test_sem_marca_sem_ean_e_peca_isolada_por_url():
    pecas, _ = _fundir([_a("fuscaopreto", "https://f/1", "LANTERNA", None, "123"),
                        _a("fuscaopreto", "https://f/2", "LANTERNA", "", "123")])
    assert len(pecas) == 2 and {p["chave"] for p in pecas} == {"URL:https://f/1", "URL:https://f/2"}
    assert all(p["tipo_marca"] == "desconhecida" for p in pecas)


def test_sem_codigo_com_ean_funde_com_peca_de_marca_pelo_ean():
    pecas, _ = _fundir([_a("karhub", "https://k/1", "Lanterna Logan - Arteb - 0460447", "Arteb", "0460447", ean="7898252655139"),
                        _a("fuscaopreto", "https://f/1", "Lanterna Logan", None, None, ean="7898252655139")])
    assert len(pecas) == 1 and pecas[0]["codigo"] == "0460447" and pecas[0]["qtd_fontes"] == 2


def test_sem_codigo_com_ean_e_marca_incompativel_nao_funde():
    pecas, _ = _fundir([_a("karhub", "https://k/1", "Lanterna", "Arteb", "0460447", ean="7898252655139"),
                        _a("clicpecas", "https://cl/1", "Lanterna", "Clic Peças", None, ean="7898252655139")])
    assert len(pecas) == 2 and "CLIC PECAS|EAN:7898252655139" in {p["chave"] for p in pecas}


def test_aplicacoes_unidas_das_fontes():
    pecas, _ = _fundir([_a("carblue", "https://c/1", "X", "GAUSS", "1", carro="GOL 96 97 98"),
                        _a("karhub", "https://k/1", "X", "GAUSS", "1", carro="Volkswagen Gol 1999-2001")])
    assert [(l["modelo"], l["ano_inicio"], l["ano_fim"]) for l in pecas[0]["aplicacoes"]] == [("GOL", 1996, 2001)]


def test_gravar_ids_estaveis_e_fusao_posterior_inativa_o_maior_id(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    a1 = _a("auri", "https://auri/1", "FAROL", "ARTEB", "0160818")
    a2 = _a("autonext", "https://an/1", "FAROL", "ARTEB", "160818")
    pecas, _ = _fundir([a1, a2])
    r = gravar(db, pecas)
    assert r["novas"] == 2
    ids = dict(db.execute("SELECT codigo, id_peca FROM peca"))
    # rodar de novo sem mudança: nada altera
    assert gravar(db, _fundir([a1, a2])[0]) == {"novas": 0, "alteradas": 0, "iguais": 2, "inativadas_por_fusao": 0, "inativadas_por_sumico": 0}
    assert dict(db.execute("SELECT codigo, id_peca FROM peca")) == ids
    # agora as fontes trazem o EAN: as duas viram uma; o menor id sobrevive
    a1["ean"] = a2["ean"] = "7898252655139"
    r = gravar(db, _fundir([a1, a2])[0])
    assert r["inativadas_por_fusao"] == 1
    menor, maior = sorted(ids.values())
    viva = db.execute("SELECT id_peca, codigo, status FROM peca WHERE status='ativa'").fetchall()
    assert [tuple(v) for v in viva] == [(menor, "0160818", "ativa")]
    morta = db.execute("SELECT status, fundida_em FROM peca WHERE id_peca=?", (maior,)).fetchone()
    assert tuple(morta) == ("inativa", menor)
    assert {r[0] for r in db.execute("SELECT id_peca FROM origem")} == {menor}


def test_gravar_inativa_peca_que_sumiu_das_fontes(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    gravar(db, _fundir([_a("auri", "https://auri/1", "FAROL", "ARTEB", "1"), _a("auri", "https://auri/2", "FAROL", "ARTEB", "2")])[0])
    r = gravar(db, _fundir([_a("auri", "https://auri/1", "FAROL", "ARTEB", "1")])[0])
    assert r["inativadas_por_sumico"] == 1
    assert db.execute("SELECT status FROM peca WHERE codigo='2'").fetchone()[0] == "inativa"


def test_hash_muda_quando_conteudo_muda(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    gravar(db, _fundir([_a("auri", "https://auri/1", "FAROL", "ARTEB", "1")])[0])
    id_peca, h = db.execute("SELECT id_peca, hash_conteudo FROM peca").fetchone()
    assert len(h) == 40 and atualizar_hash(db, id_peca) is False
    db.execute("UPDATE peca SET desc_curta='FAROL DIANTEIRO' WHERE id_peca=?", (id_peca,))
    assert atualizar_hash(db, id_peca) is True
