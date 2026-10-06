"""Veículos do helper (helper.sqlite, só leitura) para a aba Cadastrar do painel: listas do seletor, anúncios que
servem num veículo e veículos compatíveis de uma peça (lista, árvore, carros de venda e complemento).
Spec: docs/superpowers/specs/2026-10-06-painel-veiculos-design.md."""
import sqlite3
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
    db = sqlite3.connect(f"{caminho.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        try:
            tem_modelos = db.execute("SELECT 1 FROM vei_modelo WHERE ativo = 1 LIMIT 1").fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            tem_modelos = None
        if not tem_modelos:
            raise Indisponivel(f"{caminho} sem veículos")
        yield db
    except sqlite3.OperationalError as e:
        if "locked" in str(e) or "busy" in str(e):
            raise Ocupado("Base de veículos ocupada, tente de novo") from e
        raise
    finally:
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
