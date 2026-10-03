import json
from pathlib import Path

from helper.banco import abrir
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
