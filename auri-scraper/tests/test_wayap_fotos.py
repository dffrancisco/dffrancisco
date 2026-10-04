import json

import catalogo_para_pecas
from wayap_fotos import casar, n_codigo, n_ean, n_marca


def produto(marca, codigo, desc, cod_barra=""):
    return {"cod_produto": 1, "marca": marca, "num_fabricante": codigo, "num_fabricante2": "",
            "desc_produto": desc, "cod_barra": cod_barra}


def registro(marca, codigo, nome, ean=None):
    return {"fonte": "altese", "pasta": "x", "nome": nome, "marca": n_marca(marca), "codigo": n_codigo(codigo),
            "ean": n_ean(ean), "imagens": ["a.jpg"], "url": "u"}


def test_casar_por_codigo_usa_apelido_da_marca():
    # helper_marcas.csv: FIAT tem o apelido ORIGINAL FIAT
    casados, _ = casar([produto("FIAT", "46744566", "CORREIA ALTERNADOR 1.3")],
                       [registro("Original Fiat", "46744566", "Correia do Alternador Fire 1.3")])
    assert [aceitos for _, aceitos in casados] == [{0: "codigo+marca"}]


def test_casar_por_codigo_continua_exigindo_mesma_marca():
    casados, _ = casar([produto("FIAT", "46744566", "CORREIA ALTERNADOR")],
                       [registro("Original Ford", "46744566", "Correia do Alternador")])
    assert casados == []


def test_gravar_peca_completa_fotos_que_falharam(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    falhar = {"https://x/2.jpg"}

    class Resposta:
        headers = {"content-type": "image/jpeg"}
        content = b"jpg"

    monkeypatch.setattr(catalogo_para_pecas, "baixar", lambda url: None if url in falhar else Resposta())
    peca = {"url": "https://loja/p", "nome": "Farol", "marca": "Arteb", "codigo_fabricante": "0160818",
            "imagens": ["https://x/1.jpg", "https://x/2.jpg"]}
    pasta = catalogo_para_pecas.gravar_peca("altese", peca, "farol")
    assert [i["arquivo"] for i in json.loads((pasta / "produto.json").read_text())["imagens"]] == ["foto_1.jpg"]

    falhar.clear()
    catalogo_para_pecas.gravar_peca("altese", peca, "farol")
    produto_json = json.loads((pasta / "produto.json").read_text())
    assert [i["arquivo"] for i in produto_json["imagens"]] == ["foto_1.jpg", "foto_2.jpg"]
    assert [i["principal"] for i in produto_json["imagens"]] == [True, False]
    assert produto_json["codigo_fabricante"] == "0160818"


def test_banner_de_aplicacao_da_karhub():
    from PIL import Image, ImageDraw
    from wayap_fotos import banner_de_aplicacao

    banner = Image.new("RGB", (1000, 1000), "white")
    d = ImageDraw.Draw(banner)
    d.rectangle([20, 20, 980, 160], fill=(16, 30, 72))
    d.polygon([(880, 20), (980, 20), (980, 60)], fill=(240, 90, 30))
    for y in range(200, 400, 20):
        d.line([(40, y), (600, y)], fill=(120, 120, 140), width=2)
    assert banner_de_aplicacao(banner)

    peca = Image.new("RGB", (1000, 1000), "white")
    ImageDraw.Draw(peca).ellipse([200, 200, 800, 800], fill=(30, 30, 40))
    assert not banner_de_aplicacao(peca)
    assert not banner_de_aplicacao(Image.new("RGB", (1000, 1000), (16, 30, 72)))
