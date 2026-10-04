import json

from helper.banco import abrir
from helper.montadoras import Montadoras
from helper.veiculos import carregar_arvore, ler_arvore, motor

FOTO_TRACKER = "https://images.karhub.com.br/veiculos/chevrolet-tracker.avif"


def _linha(montadora="Chevrolet", mh="chevrolet", modelo="Tracker", anos=None, foto=FOTO_TRACKER, tipo="carro"):
    """Linha de karhub_arvore.jsonl. Tracker padrão: 2021 {4x2 (62329), Lt (62330)}, 2020 {Lt (5)}.
    Outros modelos recebem os mesmos anos com ids prefixados (<handle>-<modelo>-62329...), para não colidirem."""
    if anos is None:
        p = "" if (mh, modelo) == ("chevrolet", "Tracker") else f"{mh}-{modelo}-"
        anos = [{"ano": 2021, "versoes": [{"label": "4x2 Aut. 1.2 12v L3 Turbo", "handle": "a", "ids_fonte": [f"{p}62329"]},
                                          {"label": "Lt 1.0", "handle": "b", "ids_fonte": [f"{p}62330"]}]},
                {"ano": 2020, "versoes": [{"label": "Lt 1.0", "handle": "b", "ids_fonte": [f"{p}5"]}]}]
    return {"montadora": {"label": montadora, "handle": mh, "logo_url": f"https://images.karhub.com.br/assets/montadoras/{mh}.avif"},
            "modelo": {"label": modelo, "handle": modelo, "foto_url": foto}, "tipo": tipo, "motivo_tipo": "fipe",
            "anos": anos, "coletado_em": "2026-10-03"}


M = Montadoras({"MERCEDESBENZ": "MERCEDES-BENZ"})


def test_motor():
    assert motor("Lt 1.0") == "1.0" and motor("4p Mec. (g7) 1.0 12v L3 (75 82 Cv)") == "1.0"
    assert motor("Ks 100cc (6,4 Cv)") is None


def test_ler_arvore_ultima_linha_vale_e_invalida_e_ignorada(tmp_path):
    arq = tmp_path / "a.jsonl"
    arq.write_text(json.dumps(_linha(foto=None)) + "\n" + json.dumps(_linha()) + "\n{cortada", encoding="utf-8")
    linhas = ler_arvore(arq)
    assert len(linhas) == 1 and linhas[0]["modelo"]["foto_url"] == FOTO_TRACKER


def test_carrega_montadora_modelo_versoes_e_anos(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    assert carregar_arvore(db, [_linha()], M) == {"montadoras": 1, "modelos": 1, "versoes": 2, "anos_versao": 3}
    mo = db.execute("SELECT * FROM vei_modelo").fetchone()
    assert (mo["nome"], mo["nome_exibicao"], mo["ano_inicio"], mo["ano_fim"], mo["ativo"]) == ("TRACKER", "Tracker", 2020, 2021, 1)
    assert mo["foto_fonte"] == FOTO_TRACKER and mo["tipo"] == "carro"
    assert db.execute("SELECT logo_fonte FROM vei_montadora").fetchone()[0].endswith("chevrolet.avif")
    vs = {r["nome"]: r for r in db.execute("SELECT * FROM vei_versao")}
    assert set(vs) == {"4X2 AUT. 1.2 12V L3 TURBO", "LT 1.0"} and vs["LT 1.0"]["motor"] == "1.0"
    assert vs["LT 1.0"]["nome_exibicao"] == "Lt 1.0"
    assert db.execute("SELECT ano FROM vei_fonte WHERE id_fonte = '5'").fetchone()[0] == 2020
    anos_lt = [r[0] for r in db.execute("SELECT va.ano FROM vei_versao_ano va JOIN vei_versao v USING (id_versao) "
                                        "WHERE v.nome = 'LT 1.0' ORDER BY va.ano")]
    assert anos_lt == [2020, 2021]


def test_ids_estaveis_ao_recarregar_e_ausente_vira_inativo(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, [_linha(), _linha(modelo="Onix")], M)
    ids = dict(db.execute("SELECT nome, id_modelo FROM vei_modelo"))
    sql_lt = ("SELECT v.id_versao FROM vei_versao v JOIN vei_modelo m USING (id_modelo) "
              "WHERE m.nome = 'TRACKER' AND v.nome = 'LT 1.0'")
    lt = db.execute(sql_lt).fetchone()[0]
    carregar_arvore(db, [_linha(modelo="Onix"), _linha()], M)  # outra ordem
    assert dict(db.execute("SELECT nome, id_modelo FROM vei_modelo")) == ids
    assert db.execute(sql_lt).fetchone()[0] == lt
    r = carregar_arvore(db, [_linha(modelo="Onix")], M)
    assert db.execute("SELECT ativo FROM vei_modelo WHERE nome = 'TRACKER'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM vei_versao v JOIN vei_modelo m USING (id_modelo) "
                      "WHERE m.nome = 'TRACKER' AND v.ativo = 1").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM vei_fonte WHERE id_fonte = '62329'").fetchone()[0] == 0
    assert r["modelos"] == 1


def test_montadora_canonica_e_moto_e_pesado_entram_com_o_tipo(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, [_linha(montadora="Mercedes Benz", mh="mercedes-benz", modelo="A 200"),
                         _linha(montadora="Mercedes Benz", mh="mercedes-benz", modelo="1214 K", tipo="pesado"),
                         _linha(montadora="Honda", mh="honda", modelo="Biz", tipo="moto")], M)
    assert [tuple(r) for r in db.execute("SELECT nome, nome_exibicao FROM vei_montadora ORDER BY nome")] == [
        ("HONDA", "Honda"), ("MERCEDES-BENZ", "Mercedes Benz")]
    assert dict(db.execute("SELECT nome, tipo FROM vei_modelo")) == {"A 200": "carro", "1214 K": "pesado", "BIZ": "moto"}


def test_ajuste_do_dono_muda_o_tipo_sem_recoletar(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    linhas = [_linha(), _linha(modelo="A 40")]
    carregar_arvore(db, linhas, M)
    r = carregar_arvore(db, linhas, M, ajustes={("CHEVROLET", "A 40"): "pesado"})
    assert tuple(db.execute("SELECT tipo, ativo FROM vei_modelo WHERE nome = 'A 40'").fetchone()) == ("pesado", 1)
    assert r["modelos"] == 2


def test_ano_sem_versao_nao_conta(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    anos = [{"ano": 2022, "versoes": []}, {"ano": 2021, "versoes": [{"label": "Lt", "handle": "x", "ids_fonte": ["1"]}]}]
    carregar_arvore(db, [_linha(anos=anos)], M)
    assert tuple(db.execute("SELECT ano_inicio, ano_fim FROM vei_modelo").fetchone()) == (2021, 2021)
