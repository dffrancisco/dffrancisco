"""Veículos do helper (helper.sqlite, só leitura) para a aba Cadastrar do painel: listas do seletor, anúncios que
servem num veículo e veículos compatíveis de uma peça (lista, árvore, carros de venda e complemento).
Spec: docs/superpowers/specs/2026-10-06-painel-veiculos-design.md."""
import json
import sqlite3
import traceback
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from helper.consulta import ORDEM_CONFIANCA, ids_por_veiculo  # noqa: F401 (ORDEM_CONFIANCA é usada pelo painel)

HELPER_DB = Path("helper.sqlite")
FOTOS_VEICULOS = Path("helper_fotos_veiculos")
PASTAS_IMAGEM = ("montadoras", "modelos")


class Indisponivel(Exception):
    """helper.sqlite ausente ou sem veículos: o painel funciona como antes."""


class Ocupado(Exception):
    """helper.sqlite travado por outro processo."""


@contextmanager
def helper(caminho=None):
    caminho = Path(caminho or HELPER_DB)
    if not caminho.exists():
        raise Indisponivel(f"{caminho} não encontrado")
    db = None
    try:
        db = sqlite3.connect(f"{caminho.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            tem_modelos = db.execute("SELECT 1 FROM vei_modelo WHERE ativo = 1 LIMIT 1").fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            tem_modelos = None
        if not tem_modelos:
            raise Indisponivel(f"{caminho} sem veículos")
        yield db
    except sqlite3.DatabaseError as e:
        if "locked" in str(e) or "busy" in str(e):
            raise Ocupado("Base de veículos ocupada, tente de novo") from e
        traceback.print_exc()  # arquivo corrompido, sem permissão ou consulta errada: o painel segue sem a base
        raise Indisponivel(f"{caminho} ilegível: {e}") from e
    finally:
        if db is not None:
            db.close()


def url_imagem(caminho):
    """'veiculos/modelos/2_c25631ef.webp' (caminho no servidor) -> '/veiculos/img/modelos/2_c25631ef.webp'."""
    return "/veiculos/img/" + caminho.removeprefix("veiculos/") if caminho else None


def montadoras(db):
    return [{"id": r["id_veiculo_montadora"], "nome": r["nome_exibicao"], "logo_url": url_imagem(r["logo"]),
             "qtd_pecas": r["qtd_pecas"]}
            for r in db.execute("""SELECT vm.id_veiculo_montadora, vm.nome_exibicao, vm.logo, vm.qtd_pecas
                                   FROM vei_montadora vm
                                   WHERE vm.ativo = 1 AND EXISTS (SELECT 1 FROM vei_modelo mo WHERE mo.ativo = 1
                                                                    AND mo.id_veiculo_montadora = vm.id_veiculo_montadora)
                                   ORDER BY vm.qtd_pecas DESC, vm.nome""")]


def modelos(db, id_montadora):
    return [{"id": r["id_modelo"], "nome": r["nome_exibicao"], "tipo": r["tipo"], "foto_url": url_imagem(r["foto"]),
             "ano_inicio": r["ano_inicio"], "ano_fim": r["ano_fim"]}
            for r in db.execute("""SELECT id_modelo, nome_exibicao, tipo, foto, ano_inicio, ano_fim FROM vei_modelo
                                   WHERE id_veiculo_montadora = ? AND ativo = 1 ORDER BY nome""", (id_montadora,))]


def anos(db, id_modelo):
    return [r[0] for r in db.execute("""SELECT DISTINCT va.ano FROM vei_versao_ano va JOIN vei_versao v USING (id_versao)
                                        WHERE v.id_modelo = ? AND v.ativo = 1 ORDER BY va.ano DESC""", (id_modelo,))]


def versoes(db, id_modelo, ano):
    return [{"id": r[0], "nome": r[1]}
            for r in db.execute("""SELECT v.id_versao, v.nome FROM vei_versao v JOIN vei_versao_ano va USING (id_versao)
                                   WHERE v.id_modelo = ? AND va.ano = ? AND v.ativo = 1 ORDER BY v.nome""",
                                (id_modelo, ano))]


def veiculo_escolhido(db, id_modelo, ano, id_versao=None):
    """Nome canônico do modelo (para achar o carro da sociedade) e o texto 'Chevrolet Onix 2018 LT 1.4 8V FLEX'."""
    r = db.execute("""SELECT vm.nome_exibicao AS montadora, mo.nome AS modelo, mo.nome_exibicao AS modelo_exibicao
                      FROM vei_modelo mo JOIN vei_montadora vm USING (id_veiculo_montadora)
                      WHERE mo.id_modelo = ? AND mo.ativo = 1""", (id_modelo,)).fetchone()
    if not r:
        return None
    versao = db.execute("SELECT nome FROM vei_versao WHERE id_versao = ? AND id_modelo = ?",
                        (id_versao, id_modelo)).fetchone() if id_versao else None
    texto = " ".join(filter(None, [r["montadora"], r["modelo_exibicao"], str(ano), versao and versao[0]]))
    return {"modelo": r["modelo"], "texto": texto}


def serve_no_veiculo(db, id_modelo, ano, id_versao=None):
    """{(site, url): (confiança, id_peca)} dos anúncios cujas peças servem no veículo (regras de ids_por_veiculo)."""
    ids = ids_por_veiculo(db, id_modelo, ano, id_versao)
    if not ids:
        return {}
    linhas = db.execute("SELECT o.id_peca, o.site, o.url FROM json_each(?) j JOIN origem o ON o.id_peca = j.value",
                        (json.dumps(list(ids)),))
    return {(site, url): (ids[id_peca], id_peca) for id_peca, site, url in linhas}


SELO_TODAS, SELO_CONFIRA = "todas as versões", "confira a versão"
VEREDITOS = {"versao": "Serve", "todas_versoes": "Serve", "algumas_versoes": "Serve em algumas versões: escolha a versão",
             "modelo_ano": "Confira a versão"}


def peca_do_item(db, site, url):
    r = db.execute("""SELECT o.id_peca FROM origem o JOIN peca p USING (id_peca)
                      WHERE o.site = ? AND o.url = ? AND p.status = 'ativa'""", (site, url)).fetchone()
    return r[0] if r else None


def motores_do_modelo(db, id_modelo, ano_inicio, ano_fim):
    return [m for (m,) in db.execute("""SELECT DISTINCT v.motor FROM vei_versao v JOIN vei_versao_ano va USING (id_versao)
                                        WHERE v.id_modelo = ? AND v.ativo = 1 AND v.motor IS NOT NULL
                                          AND va.ano BETWEEN ? AND ? ORDER BY CAST(v.motor AS REAL)""",
                                     (id_modelo, ano_inicio, ano_fim))]


def veiculos_da_peca(db, id_peca):
    """Linhas de vei_peca da peça com nomes e motores, na ordem montadora, modelo, ano e versão (nulos primeiro)."""
    linhas = []
    for r in db.execute("""SELECT vm.nome AS montadora, vm.nome_exibicao AS montadora_exibicao, vm.logo,
                                  mo.id_modelo, mo.nome AS modelo, mo.nome_exibicao AS modelo_exibicao, mo.tipo, mo.foto,
                                  pv.id_versao, v.nome AS versao, v.motor, pv.ano_inicio, pv.ano_fim, pv.nivel
                           FROM vei_peca pv JOIN vei_modelo mo USING (id_modelo)
                                JOIN vei_montadora vm USING (id_veiculo_montadora)
                                LEFT JOIN vei_versao v ON v.id_versao = pv.id_versao
                           WHERE pv.id_peca = ? AND mo.ativo = 1 AND vm.ativo = 1 AND (pv.id_versao IS NULL OR v.ativo = 1)
                           ORDER BY vm.nome, mo.nome, pv.ano_inicio, v.nome""", (id_peca,)):
        linha = dict(r)
        if r["id_versao"]:
            linha["motores"] = [r["motor"]] if r["motor"] else []
        elif r["nivel"] == "versao":  # todas as versões: os motores das versões que existem na faixa
            linha["motores"] = motores_do_modelo(db, r["id_modelo"], r["ano_inicio"], r["ano_fim"])
        else:
            linha["motores"] = []
        linhas.append(linha)
    return linhas


def faixa(inicio, fim):
    """(2013, 2019) -> '2013-2019'; (2019, 2019) -> '2019'; (2010, None) -> '2010-'; (None, None) -> ''."""
    if inicio is None and fim is None:
        return ""
    if inicio == fim:
        return str(inicio)
    return f"{inicio or ''}-{fim or ''}"


def texto_linha(l):
    """'CHEVROLET ONIX 2013-2019 LT 1.4 8V FLEX': nomes canônicos, como a lista da KarHub."""
    return " ".join(p for p in (l["montadora"], l["modelo"], faixa(l["ano_inicio"], l["ano_fim"]), l["versao"]) if p)


def lista(linhas):
    return [{"texto": texto_linha(l), "tipo": l["tipo"],
             "selo": SELO_CONFIRA if l["nivel"] == "modelo" else None if l["id_versao"] else SELO_TODAS}
            for l in linhas]


def linhas_complemento(linhas):
    return "\n".join(dict.fromkeys(texto_linha(l) for l in linhas))


def ocorrencias(linhas):
    """Entrada do agrupar_veiculos do painel: [rótulo, modelo, (início, fim) ou None, motores]."""
    return [[f"{l['montadora']} {l['modelo']}", l["modelo"],
             None if l["ano_inicio"] is None and l["ano_fim"] is None else (l["ano_inicio"], l["ano_fim"]), l["motores"]]
            for l in linhas]


def arvore(db, linhas):
    """Montadora -> modelos -> anos (decrescente) -> versões do ano, como a vista em árvore da KarHub."""
    montadoras, versoes_do_modelo = {}, {}
    for l in linhas:
        if l["id_modelo"] not in versoes_do_modelo:
            por_ano = defaultdict(dict)
            for ano, id_versao, nome in db.execute("""SELECT va.ano, v.id_versao, v.nome FROM vei_versao v
                                                      JOIN vei_versao_ano va USING (id_versao)
                                                      WHERE v.id_modelo = ? AND v.ativo = 1""", (l["id_modelo"],)):
                por_ano[ano][id_versao] = nome
            versoes_do_modelo[l["id_modelo"]] = por_ano
        m = montadoras.setdefault(l["montadora"], {"nome": l["montadora_exibicao"], "logo_url": url_imagem(l["logo"]),
                                                   "modelos": {}})
        mo = m["modelos"].setdefault(l["id_modelo"], {"nome": l["modelo_exibicao"], "tipo": l["tipo"],
                                                      "foto_url": url_imagem(l["foto"]), "anos": {}})
        inicio, fim = l["ano_inicio"] or 0, l["ano_fim"] or 9999
        for ano, versoes_ano in versoes_do_modelo[l["id_modelo"]].items():
            if not inicio <= ano <= fim or (l["id_versao"] and l["id_versao"] not in versoes_ano):
                continue
            a = mo["anos"].setdefault(ano, {"ano": ano, "versoes": set(), "todas": False, "confira": False})
            if l["nivel"] == "modelo":
                a["confira"] = True
            elif l["id_versao"]:
                a["versoes"].add(versoes_ano[l["id_versao"]])
            else:
                a["todas"] = True
                a["versoes"].update(versoes_ano.values())
    return [{"nome": m["nome"], "logo_url": m["logo_url"],
             "modelos": [{"nome": mo["nome"], "tipo": mo["tipo"], "foto_url": mo["foto_url"],
                          "faixa": faixa(min(mo["anos"], default=None), max(mo["anos"], default=None)),
                          "anos": [dict(a, versoes=sorted(a["versoes"]))
                                   for _, a in sorted(mo["anos"].items(), reverse=True)]}
                         for mo in m["modelos"].values()]}
            for m in montadoras.values()]


def seu_veiculo(db, id_peca, id_modelo, ano, id_versao=None):
    """Veredito da peça para o veículo escolhido na busca (o 'Confirmar compatibilidade' da KarHub)."""
    escolhido = veiculo_escolhido(db, id_modelo, ano, id_versao)
    if not escolhido:
        return None
    confianca = ids_por_veiculo(db, id_modelo, ano, id_versao).get(id_peca)
    if confianca:
        veredito = VEREDITOS[confianca]
    elif id_versao is not None and id_peca in ids_por_veiculo(db, id_modelo, ano):
        veredito = "Não serve nesta versão"
    elif db.execute("SELECT 1 FROM vei_peca WHERE id_peca = ? AND id_modelo = ? AND nivel = 'modelo' "
                    "AND ano_inicio IS NULL AND ano_fim IS NULL", (id_peca, id_modelo)).fetchone():
        veredito = "Confira o ano: o anúncio cita o modelo, sem o ano"
    else:
        veredito = "Não consta para este veículo"
    return {"veiculo": escolhido["texto"], "confianca": confianca, "veredito": veredito}
