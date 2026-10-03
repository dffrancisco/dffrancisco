import json
from pathlib import Path

from helper.fontes import fontes_disponiveis, ler_fonte, prioridade


def _escrever(caminho, texto):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")


def test_fontes_disponiveis_acha_jsonl_e_produto_json(tmp_path):
    _escrever(tmp_path / "catalogos/karhub.jsonl", "")
    _escrever(tmp_path / "pecas_auri/arteb/farol-0160818/produto.json", "{}")
    _escrever(tmp_path / "pecas_carblue/x-123/produto.json", "{}")
    _escrever(tmp_path / "pecas_carblue/x-123/foto_1.jpg", "")
    fontes = fontes_disponiveis(tmp_path)
    assert [(f.site, f.tipo, f.caminho.relative_to(tmp_path).as_posix()) for f in sorted(fontes, key=lambda f: str(f.caminho))] == [
        ("karhub", "jsonl", "catalogos/karhub.jsonl"),
        ("auri", "produto_json", "pecas_auri/arteb/farol-0160818/produto.json"),
        ("carblue", "produto_json", "pecas_carblue/x-123/produto.json"),
    ]


def test_ler_jsonl_ignora_linha_cortada_e_conta(tmp_path):
    arq = tmp_path / "catalogos/karhub.jsonl"
    linha = {"site": "karhub", "url": "https://k/p/1", "nome": "Jogo Cabo De Vela - Gauss - Gc5045", "marca": "Gauss",
             "codigo_fabricante": "GC5045", "ean": "7898252655139", "carro": "Renault Megane 1997-2003 2.0",
             "imagens": ["https://cdn/a.jpg", "https://cdn/b.jpg"]}
    _escrever(arq, json.dumps(linha) + "\n" + '{"site": "karhub", "url": "https://k/p/2", "nome": "cort')
    fonte = next(f for f in fontes_disponiveis(tmp_path))
    erros = []
    anuncios = list(ler_fonte(fonte, erros))
    assert len(anuncios) == 1 and erros == ["linha 2 inválida"]
    a = anuncios[0]
    assert a["site"] == "karhub" and a["codigo"] == "GC5045" and a["ean"] == "7898252655139"
    assert a["imagens"] == [{"url": "https://cdn/a.jpg", "arquivo_local": None, "principal": True},
                            {"url": "https://cdn/b.jpg", "arquivo_local": None, "principal": False}]
    assert a["aplicacoes"] == [] and a["carro"] == "Renault Megane 1997-2003 2.0"
    assert a["prioridade"] == prioridade("karhub", False) == 2
    assert len(a["coletado_em"]) == 10


def test_ler_produto_json_auri_com_aplicacoes_e_fotos_locais(tmp_path):
    pasta = tmp_path / "pecas_auri/2m-plastic/kit-0106006"
    _escrever(pasta / "produto.json", json.dumps({
        "nome": "KIT PROTETOR CORREIA DENTADA 0106006 2M PLASTIC - FIAT PALIO", "marca": "2M PLASTIC",
        "codigo_fabricante": "0106006", "ean": "7898590390532", "codigos_equivalentes": ["7891579301901", "ABC1"],
        "aplicacoes": [{"montadora": "FIAT", "veiculo": "PALIO", "motor": "1.0", "ano_inicio": 2007, "ano_fim": 2009}],
        "observacoes": ["COM AVARIA"],
        "imagens": [{"arquivo": "foto_1.png", "url": "https://img/1.png", "principal": True},
                    {"arquivo": "foto_2.jpg", "url": "https://img/2.jpg", "principal": False}],
        "url_origem": "https://www.auriautopecas.com.br/kit-0106006"}))
    _escrever(pasta / "foto_1.png", "")  # foto_2.jpg não existe no disco
    fonte = next(f for f in fontes_disponiveis(tmp_path))
    a = next(ler_fonte(fonte, []))
    assert a["site"] == "auri" and a["url"] == "https://www.auriautopecas.com.br/kit-0106006"
    assert a["codigo"] == "0106006" and a["equivalentes"] == ["7891579301901", "ABC1"]
    assert a["aplicacoes"][0]["veiculo"] == "PALIO" and a["observacoes"] == ["COM AVARIA"]
    assert a["imagens"][0]["arquivo_local"] == str(pasta / "foto_1.png") and a["imagens"][0]["principal"] is True
    assert a["imagens"][1]["arquivo_local"] is None
    assert a["prioridade"] == 0


def test_produto_json_invalido_vira_erro(tmp_path):
    _escrever(tmp_path / "pecas_carblue/x/produto.json", "{nao e json")
    fonte = next(f for f in fontes_disponiveis(tmp_path))
    erros = []
    assert list(ler_fonte(fonte, erros)) == [] and erros and "produto.json" in erros[0]
