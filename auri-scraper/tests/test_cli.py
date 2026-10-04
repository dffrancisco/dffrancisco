import json
from pathlib import Path

from helper.banco import abrir, ler_meta
from helper.cli import main


def _escrever(caminho, texto):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


def _montar_base(tmp_path):
    k1 = {"site": "karhub", "url": "https://k/p/1", "nome": "Jogo Cabo De Vela - Gauss - Gc5045", "marca": "Gauss",
          "codigo_fabricante": "GC5045", "ean": "7898252655139", "carro": "Volkswagen Gol 1999-2001", "imagens": ["https://cdn/a.jpg"]}
    c1 = {"site": "carblue", "url": "https://c/p/1", "nome": "CABO VELA GOL GC5045", "marca": "GAUSS",
          "codigo_fabricante": "GC5045", "ean": "7898252655139", "carro": "GOL 96 97 98", "imagens": ["https://cdn/b.jpg"]}
    _escrever(tmp_path / "catalogos/karhub.jsonl", json.dumps(k1) + "\n")
    _escrever(tmp_path / "catalogos/carblue.jsonl", json.dumps(c1) + "\n{cortada")
    _escrever(tmp_path / "pecas_auri/arteb/farol/produto.json", json.dumps({
        "nome": "FAROL GOL 0160818 ARTEB", "marca": "ARTEB", "codigo_fabricante": "0160818", "ean": None,
        "aplicacoes": [{"montadora": "VOLKSWAGEN", "veiculo": "GOL", "motor": None, "ano_inicio": 1995, "ano_fim": 1999}],
        "imagens": [{"arquivo": "foto_1.jpg", "url": "https://img/1.jpg", "principal": True}], "url_origem": "https://auri/farol"}))
    _escrever(tmp_path / "pecas_auri/arteb/farol/foto_1.jpg", "")
    _escrever(tmp_path / "helper_cache/topcar.json", json.dumps({
        "marcas": [{"id_marca": 1, "descricao": "GAUSS"}], "carros": [{"id_carro": 1, "descricao": "GOL"}],
        "produtos": [{"cod_produto": 1, "desc_produto": "CABO VELA", "marca": "GAUSS", "ncm": "85443000", "unidade": "JG",
                      "num_fabricante": "GC5045", "num_fabricante2": None, "cod_barra": None}]}))


def test_preparar_ponta_a_ponta(tmp_path, capsys):
    _montar_base(tmp_path)
    assert main(["preparar", "--base", str(tmp_path)]) == 0
    db = abrir(tmp_path / "helper.sqlite")
    pecas = {r["codigo"]: r for r in db.execute("SELECT * FROM peca")}
    assert set(pecas) == {"GC5045", "0160818"}
    assert pecas["GC5045"]["qtd_fontes"] == 2 and pecas["GC5045"]["ncm_sugerido"] == "85443000"
    assert pecas["GC5045"]["unidade_sugerida"] == "JG" and pecas["GC5045"]["desc_curta"] == "JOGO CABO VELA"
    assert [tuple(r) for r in db.execute("SELECT modelo, ano_inicio, ano_fim FROM aplicacao WHERE id_peca=?", (pecas["GC5045"]["id_peca"],))] == [("GOL", 1996, 2001)]
    assert db.execute("SELECT count(*) FROM foto_pendente").fetchone()[0] == 3
    assert db.execute("SELECT arquivo_local FROM foto_pendente WHERE id_peca=?", (pecas["0160818"]["id_peca"],)).fetchone()[0].endswith("foto_1.jpg")
    relatorios = list((tmp_path / "helper_relatorios").glob("*-preparar.md"))
    assert len(relatorios) == 1
    texto = relatorios[0].read_text(encoding="utf-8")
    assert "| carblue | 1 | 1 |" in texto and "Peças ativas: 2" in texto
    assert "sem foto baixada: 2" in texto
    assert list((tmp_path / "helper_relatorios").glob("*-marcas-desconhecidas.csv"))
    saida = capsys.readouterr().out
    assert "peças ativas: 2" in saida


def test_relatorio_sozinho_depois_de_preparar(tmp_path):
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    assert main(["relatorio", "--base", str(tmp_path)]) == 0
    assert len(list((tmp_path / "helper_relatorios").glob("*-relatorio.md"))) == 1


def test_preparar_grava_a_hora_em_meta(tmp_path):
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    assert ler_meta(abrir(tmp_path / "helper.sqlite"), "preparado_em")


def _arvore_gol(tmp_path):
    arvore = {"montadora": {"label": "Volkswagen", "handle": "volkswagen", "logo_url": None},
              "modelo": {"label": "Gol", "handle": "Gol", "foto_url": None}, "tipo": "carro", "motivo_tipo": "fipe",
              "anos": [{"ano": a, "versoes": [{"label": "1.0 8v", "handle": "x", "ids_fonte": [str(a)]}]} for a in (1999, 2000, 2001)],
              "coletado_em": "2026-10-03"}
    _escrever(tmp_path / "veiculos/karhub_arvore.jsonl", json.dumps(arvore) + "\n")
    _escrever(tmp_path / "veiculos/karhub_excluidos.jsonl", json.dumps({
        "montadora": {"label": "Honda", "handle": "honda"}, "modelo": {"label": "Biz", "handle": "Biz"},
        "tipo": "moto", "motivo_tipo": "versao", "versoes_exemplo": ["Ks 100cc"], "coletado_em": "2026-10-03"}) + "\n")
    # o anúncio da KarHub em _montar_base tem url https://k/p/1: handle "1"
    _escrever(tmp_path / "veiculos/karhub_compat.jsonl", json.dumps({"handle": "1", "ids": ["1999", "2000"]}) + "\n")


def test_veiculos_ponta_a_ponta(tmp_path, capsys):
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    _arvore_gol(tmp_path)
    assert main(["veiculos", "--base", str(tmp_path)]) == 0
    db = abrir(tmp_path / "helper.sqlite")
    gc = db.execute("SELECT id_peca FROM peca WHERE codigo = 'GC5045'").fetchone()[0]
    assert [tuple(l) for l in db.execute("SELECT id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo WHERE id_peca = ?", (gc,))] == \
        [(None, 1999, 2000, "versao")]
    farol = db.execute("SELECT id_peca FROM peca WHERE codigo = '0160818'").fetchone()[0]
    assert [tuple(l) for l in db.execute("SELECT ano_inicio, ano_fim, nivel FROM peca_veiculo WHERE id_peca = ?", (farol,))] == \
        [(1995, 1999, "modelo")]
    rel = list((tmp_path / "helper_relatorios").glob("*-veiculos.md"))[0].read_text(encoding="utf-8")
    assert "Modelos ativos: 1" in rel and "| moto | versao | 1 |" in rel
    tipos = list((tmp_path / "helper_relatorios").glob("*-veiculos-tipos.csv"))[0].read_text(encoding="utf-8")
    assert "Honda;Biz;moto;versao;Ks 100cc" in tipos and "Volkswagen;Gol;carro;fipe;1.0 8v" in tipos


def test_veiculos_sem_arvore_avisa(tmp_path):
    _montar_base(tmp_path)
    assert main(["veiculos", "--base", str(tmp_path)]) == 2


def test_pecas_do_veiculo_aceita_o_jeito_do_usuario(tmp_path, capsys):
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    _arvore_gol(tmp_path)
    main(["veiculos", "--base", str(tmp_path)])
    capsys.readouterr()
    assert main(["pecas-do-veiculo", "volkswagen", "gol", "2000", "--base", str(tmp_path)]) == 0
    saida = capsys.readouterr().out
    assert "todas_versoes" in saida and "GC5045" in saida
    assert main(["pecas-do-veiculo", "vw", "Gol", "1997", "--base", str(tmp_path)]) == 0  # 1997: só o texto da Arteb
    assert "modelo_ano" in capsys.readouterr().out
    assert main(["pecas-do-veiculo", "VW", "GOL", "2000", "--versao", "1.0 8V", "--texto", "cabo", "--base", str(tmp_path)]) == 0
    saida = capsys.readouterr().out
    assert "versao" in saida and "GC5045" in saida and "0160818" not in saida
    assert main(["pecas-do-veiculo", "VW", "FUSCA", "2000", "--base", str(tmp_path)]) == 1
    assert main(["pecas-do-veiculo", "VW", "GOL", "2000", "--versao", "2.0 turbo", "--base", str(tmp_path)]) == 1
    assert "1.0 8v" in capsys.readouterr().out  # lista as versões do ano


def test_publicar_ensaio_nao_instala_esquema_e_recusa_veiculos_desatualizado(tmp_path, monkeypatch):
    from helper import publicar as pub
    from helper.banco import gravar_meta
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    _arvore_gol(tmp_path)
    main(["veiculos", "--base", str(tmp_path)])
    chamadas = []
    monkeypatch.setattr(pub, "ler_env_admin", lambda caminho: chamadas.append("env") or {})
    monkeypatch.setattr(pub, "conectar", lambda env, nome: object())
    monkeypatch.setattr(pub, "criar_banco", lambda *a, **k: chamadas.append("criar_banco"))
    monkeypatch.setattr(pub, "instalar_esquema", lambda con: chamadas.append("instalar_esquema") or True)
    monkeypatch.setattr(pub, "publicar", lambda db, con, **k: chamadas.append(("publicar", k["ensaio"])) or {"novas": 0})
    monkeypatch.setattr(pub, "publicar_veiculos", lambda db, con, **k: chamadas.append(("veiculos", k["ensaio"])) or {"modelos": 1})
    assert main(["publicar", "--ensaio", "--base", str(tmp_path)]) == 0
    assert chamadas == ["env", ("publicar", True), ("veiculos", True)]  # ensaio não cria banco nem tabelas
    db = abrir(tmp_path / "helper.sqlite")
    gravar_meta(db, "preparado_em", "9999-12-31T00:00:00")  # um preparar depois do veiculos
    db.commit()
    chamadas.clear()
    assert main(["publicar", "--ensaio", "--base", str(tmp_path)]) == 2
    assert chamadas == []  # recusa antes de conectar
