import json

import pytest

import catalogo_karhub_veiculos as cv
from helper.montadoras import Montadoras
from helper.veiculo_tipo import indexar_fipe

GV = f"{cv.SITE}/api/get-vehicles"
CT = f"{cv.SITE}/api/get-automaker-content?handle="
LOGO = "https://images.karhub.com.br/assets/montadoras/chevrolet.avif"
FOTO = "https://images.karhub.com.br/veiculos/chevrolet-tracker.avif"


def _json(obj):
    return (200, json.dumps(obj).encode(), "application/json")


def _item(label, ids=(), handle=None):
    return {"id": 0, "label": label, "value": label, "handle": handle or label, "compatible_ids": list(ids)}


class Web:
    """Servidor falso: url -> (status, corpo, tipo) | Exception. Rota ausente = 404 em HTML, como o Cloudflare."""
    def __init__(self, rotas):
        self.rotas, self.pedidos = rotas, []

    def __call__(self, url):
        self.pedidos.append(url)
        r = self.rotas.get(url)
        if r is None:
            return (404, b"<html>404</html>", "text/html")
        if isinstance(r, Exception):
            raise r
        return r


def _rotas():
    return {
        GV: _json({"brands": [_item("Chevrolet", handle="chevrolet"), _item("Honda", handle="honda")]}),
        f"{GV}?brand=chevrolet": _json({"models": [_item("Tracker")]}),
        f"{GV}?brand=honda": _json({"models": [_item("Biz 100")]}),
        f"{GV}?brand=chevrolet&model=Tracker": _json({"years": [_item("2021", ["62329", "62330"]), _item("2020", ["5"])]}),
        f"{GV}?brand=chevrolet&model=Tracker&year=2021": _json({"versions": [_item("4x2 Aut. 1.2 12v L3 Turbo", ["62329"], "a"),
                                                                             _item("Lt 1.0", ["62330"], "b")]}),
        f"{GV}?brand=chevrolet&model=Tracker&year=2020": _json({"versions": [_item("Lt 1.0", ["5"], "b")]}),
        f"{GV}?brand=honda&model=Biz+100": _json({"years": [_item("2015", ["9"])]}),
        f"{GV}?brand=honda&model=Biz+100&year=2015": _json({"versions": [_item("Ks 100cc (6,4 Cv)", ["9"])]}),
        f"{CT}chevrolet": _json({"data": {"data": {"brand": {"image_url": LOGO}}}}),
        f"{CT}chevrolet/Tracker": _json({"data": {"data": {"model": {"image_url": FOTO}}}}),
        LOGO: (200, b"LOGO", "image/avif"),
        FOTO: (200, b"FOTO", "image/avif"),
    }


def _cliente(web):
    return cv.Cliente(buscar=web, esperas=(), pausa=0, log=lambda m: None)


def _coletar(tmp_path, web, ajustes=None, **kw):
    return cv.coletar_arvore(_cliente(web), tmp_path, indexar_fipe({}), ajustes or {}, Montadoras({}), log=lambda m: None, **kw)


def _ler(arq):
    return [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines()]


def test_cliente_repete_erro_de_conexao_e_5xx(monkeypatch):
    respostas = [ConnectionError("recusada"), (500, b"", "text/html"), (200, b'{"ok": 1}', "application/json")]

    def buscar(url):
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    esperas = []
    monkeypatch.setattr(cv.time, "sleep", esperas.append)
    c = cv.Cliente(buscar=buscar, esperas=(5, 15, 30), pausa=0, log=lambda m: None)
    assert c.json("u") == {"ok": 1} and esperas == [5, 15]


def test_cliente_bloqueado_espera_quatro_vezes_e_desiste(monkeypatch):
    esperas = []
    monkeypatch.setattr(cv.time, "sleep", esperas.append)
    c = cv.Cliente(buscar=lambda url: (403, b"<html>captcha</html>", "text/html"), esperas=(5, 15), pausa=0, log=lambda m: None)
    with pytest.raises(cv.Bloqueado):
        c.json("u")
    assert esperas == [20, 60]


def test_imagem_404_volta_none_sem_novas_tentativas():
    web = Web({})
    assert _cliente(web).get("https://x/y.avif", aceitar_404=True) == (None, "text/html")
    assert len(web.pedidos) == 1


def test_fipe_grava_marcas_e_modelos_das_tres_listas(tmp_path):
    rotas = {}
    for lista in cv.LISTAS_FIPE:
        rotas[f"{cv.FIPE}/{lista}/marcas"] = _json([{"codigo": "1", "nome": f"Marca {lista}"}])
        rotas[f"{cv.FIPE}/{lista}/marcas/1/modelos"] = _json({"modelos": [{"codigo": 1, "nome": f"Modelo {lista}"}], "anos": []})
    r = cv.coletar_fipe(_cliente(Web(rotas)), tmp_path / "fipe.json")
    assert json.loads((tmp_path / "fipe.json").read_text()) == {l: {f"Marca {l}": [f"Modelo {l}"]} for l in cv.LISTAS_FIPE}
    assert r == {"carros": 1, "motos": 1, "caminhoes": 1}


def test_arvore_grava_carro_completo_e_separa_moto(tmp_path):
    web = Web(_rotas())
    r = _coletar(tmp_path, web)
    (t,) = _ler(tmp_path / "karhub_arvore.jsonl")
    assert t["montadora"] == {"label": "Chevrolet", "handle": "chevrolet", "logo_url": LOGO}
    assert t["modelo"] == {"label": "Tracker", "handle": "Tracker", "foto_url": FOTO}
    assert (t["tipo"], t["motivo_tipo"]) == ("carro", "padrao")
    assert t["anos"] == [{"ano": 2021, "versoes": [{"label": "4x2 Aut. 1.2 12v L3 Turbo", "handle": "a", "ids_fonte": ["62329"]},
                                                  {"label": "Lt 1.0", "handle": "b", "ids_fonte": ["62330"]}]},
                         {"ano": 2020, "versoes": [{"label": "Lt 1.0", "handle": "b", "ids_fonte": ["5"]}]}]
    (e,) = _ler(tmp_path / "karhub_excluidos.jsonl")
    assert (e["modelo"]["label"], e["tipo"], e["motivo_tipo"], e["versoes_exemplo"]) == ("Biz 100", "moto", "versao", ["Ks 100cc (6,4 Cv)"])
    assert (tmp_path / "imagens/veiculos/chevrolet-tracker.avif").read_bytes() == b"FOTO"
    assert (tmp_path / "imagens/assets/montadoras/chevrolet.avif").read_bytes() == b"LOGO"
    assert r["carros"] == 1 and r["excluido_moto"] == 1
    assert not any(u.startswith(f"{CT}honda") for u in web.pedidos)  # moto não pede conteúdo nem logo


def test_foto_404_fica_ausente(tmp_path):
    rotas = _rotas()
    del rotas[FOTO]
    _coletar(tmp_path, Web(rotas))
    assert _ler(tmp_path / "karhub_arvore.jsonl")[0]["modelo"]["foto_url"] is None


def test_retoma_pulando_modelos_gravados_e_corta_linha_incompleta(tmp_path):
    _coletar(tmp_path, Web(_rotas()))
    with (tmp_path / "karhub_arvore.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"montadora": {"lab')  # queda no meio da gravação
    web2 = Web(_rotas())
    r = _coletar(tmp_path, web2)
    assert r["ja_feitos"] == 2 and r.get("carros", 0) == 0
    assert len(_ler(tmp_path / "karhub_arvore.jsonl")) == 1
    assert not any("year=" in u for u in web2.pedidos)


def test_excluido_que_virou_carro_por_ajuste_e_coletado(tmp_path):
    _coletar(tmp_path, Web(_rotas()))
    rotas = _rotas()
    rotas[f"{CT}honda"] = _json({"data": None})
    rotas[f"{CT}honda/Biz%20100"] = _json({"data": None})
    r = _coletar(tmp_path, Web(rotas), ajustes={("HONDA", "BIZ 100"): "carro"})
    assert r["carros"] == 1
    biz = [t for t in _ler(tmp_path / "karhub_arvore.jsonl") if t["modelo"]["label"] == "Biz 100"][0]
    assert biz["motivo_tipo"] == "ajuste" and biz["montadora"]["logo_url"] is None


def test_modelo_sem_anos_e_registrado_e_nao_volta(tmp_path):
    rotas = _rotas()
    rotas[f"{GV}?brand=chevrolet&model=Tracker"] = _json({"years": []})
    _coletar(tmp_path, Web(rotas))
    assert [e["tipo"] for e in _ler(tmp_path / "karhub_excluidos.jsonl")] == ["sem_anos", "moto"]
    assert _coletar(tmp_path, Web(rotas))["ja_feitos"] == 2


def test_do_inicio_grava_em_arquivo_novo_e_troca_no_fim(tmp_path):
    _coletar(tmp_path, Web(_rotas()))
    antigo = (tmp_path / "karhub_arvore.jsonl").read_text(encoding="utf-8")
    r = _coletar(tmp_path, Web(_rotas()), do_inicio=True)
    assert r["carros"] == 1 and not (tmp_path / "karhub_arvore.jsonl.novo").exists()
    assert json.loads((tmp_path / "karhub_arvore.jsonl").read_text(encoding="utf-8"))["anos"] == json.loads(antigo)["anos"]


def test_so_uma_montadora(tmp_path):
    r = _coletar(tmp_path, Web(_rotas()), so_montadora="honda")
    assert r.get("carros", 0) == 0 and r["excluido_moto"] == 1


def test_main_recusa_montadora_com_do_inicio(tmp_path):
    with pytest.raises(SystemExit):
        cv.main(["arvore", "--pasta", str(tmp_path), "--montadora", "chevrolet", "--do-inicio"])


def test_main_arvore_sem_fipe_avisa(tmp_path):
    assert cv.main(["arvore", "--pasta", str(tmp_path)]) == 2


def test_excluido_nao_volta_so_porque_as_versoes_de_exemplo_parecem_de_carro(tmp_path):
    # pesado decidido por uma versão além da 5ª: as de exemplo, sozinhas, cairiam no "padrão" (carro)
    (tmp_path / "karhub_excluidos.jsonl").write_text(json.dumps({
        "montadora": {"label": "Honda", "handle": "honda"}, "modelo": {"label": "Biz 100", "handle": "Biz 100"},
        "tipo": "pesado", "motivo_tipo": "versao", "versoes_exemplo": ["Lt 1.0"], "coletado_em": "2026-10-04"}) + "\n",
        encoding="utf-8")
    web = Web(_rotas())
    r = _coletar(tmp_path, web)
    assert r["ja_feitos"] == 1 and not any("Biz" in u for u in web.pedidos)
    assert len(_ler(tmp_path / "karhub_excluidos.jsonl")) == 1  # sem linha duplicada


def test_modelo_com_erro_permanente_nao_trava_a_coleta(tmp_path):
    rotas = _rotas()
    del rotas[f"{GV}?brand=chevrolet&model=Tracker&year=2020"]  # 404 em rota JSON: erro que não passa
    r = _coletar(tmp_path, Web(rotas))
    assert r["erro"] == 1 and r["excluido_moto"] == 1  # a Honda, que vem depois, foi coletada
    assert (tmp_path / "karhub_arvore.jsonl").read_text(encoding="utf-8") == ""  # nada gravado pela metade
    assert _coletar(tmp_path, Web(_rotas()))["carros"] == 1  # na rodada seguinte o Tracker é tentado de novo


def test_200_com_captcha_conta_como_bloqueio(monkeypatch):
    monkeypatch.setattr(cv.time, "sleep", lambda s: None)
    c = cv.Cliente(buscar=lambda url: (200, b"<html>captcha</html>", "text/html"), esperas=(5,), pausa=0, log=lambda m: None)
    with pytest.raises(cv.Bloqueado):
        c.json("u")


def test_main_sai_com_2_quando_a_rede_nao_volta(tmp_path, monkeypatch):
    (tmp_path / "fipe.json").write_text("{}", encoding="utf-8")

    def falha(*a, **k):
        raise RuntimeError("conexão: recusada em https://www.karhub.com.br/api/get-vehicles")
    monkeypatch.setattr(cv, "coletar_arvore", falha)
    assert cv.main(["arvore", "--pasta", str(tmp_path)]) == 2


def _catalogo(tmp_path, n):
    arq = tmp_path / "karhub.jsonl"
    linhas = [json.dumps({"url": f"https://www.karhub.com.br/p/peca-{i}"}) for i in range(n)]
    linhas.append(json.dumps({"url": "https://www.karhub.com.br/p/peca-0?Lado=Direito"}))  # variante: mesmo handle
    arq.write_text("\n".join(linhas) + "\n{cortada", encoding="utf-8")
    return arq


def _rota_compat(handles):
    return f"{cv.SITE}/api/product-compatible-ids?handles={','.join(handles)}"


def test_handles_do_catalogo(tmp_path):
    assert cv.handles_do_catalogo(_catalogo(tmp_path, 3)) == ["peca-0", "peca-1", "peca-2"]


def test_compat_em_lotes_de_50(tmp_path):
    handles = [f"peca-{i}" for i in range(60)]
    rotas = {_rota_compat(handles[:50]): _json({h: [1, 2] for h in handles[:50]}),
             _rota_compat(handles[50:]): _json({"peca-55": ["7"]})}
    r = cv.coletar_compat(_cliente(Web(rotas)), _catalogo(tmp_path, 60), tmp_path / "compat.jsonl", log=lambda m: None)
    por_handle = {l["handle"]: l["ids"] for l in _ler(tmp_path / "compat.jsonl")}
    assert len(por_handle) == 60 and por_handle["peca-0"] == ["1", "2"]
    assert por_handle["peca-55"] == ["7"] and por_handle["peca-56"] == []
    assert r["com_ids"] == 51 and r["sem_ids"] == 9


def test_lote_inteiro_vazio_repete_em_lotes_de_10(tmp_path):
    handles = [f"peca-{i}" for i in range(50)]
    rotas = {_rota_compat(handles): _json({})}
    for j in range(0, 50, 10):
        rotas[_rota_compat(handles[j:j + 10])] = _json({h: ["3"] for h in handles[j:j + 10]})
    cv.coletar_compat(_cliente(Web(rotas)), _catalogo(tmp_path, 50), tmp_path / "compat.jsonl", log=lambda m: None)
    assert all(l["ids"] == ["3"] for l in _ler(tmp_path / "compat.jsonl"))


def test_compat_retoma_pelos_handles_gravados(tmp_path):
    (tmp_path / "compat.jsonl").write_text(json.dumps({"handle": "peca-0", "ids": ["1"], "coletado_em": "2026-10-01"}) + "\n", encoding="utf-8")
    web = Web({_rota_compat(["peca-1", "peca-2"]): _json({"peca-1": ["9"]})})
    cv.coletar_compat(_cliente(web), _catalogo(tmp_path, 3), tmp_path / "compat.jsonl", log=lambda m: None)
    assert [l["handle"] for l in _ler(tmp_path / "compat.jsonl")] == ["peca-0", "peca-1", "peca-2"]
    assert len(web.pedidos) == 1
