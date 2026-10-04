"""Árvore de veículos no helper.sqlite (montadora, modelo, versão e anos), com ids estáveis por nome canônico.
Lê veiculos/karhub_arvore.jsonl, gravado por catalogo_karhub_veiculos.py. Spec de veículos, seções 6 e 7."""
import json
import re
from pathlib import Path

from helper.montadoras import nome_canonico
from helper.veiculo_tipo import ajuste_de

MOTOR_RE = re.compile(r"\b\d\.\d\b")


def ler_arvore(caminho):
    linhas = {}
    with Path(caminho).open(encoding="utf-8") as f:
        for texto in f:
            try:
                l = json.loads(texto)
                linhas[(l["montadora"]["handle"], l["modelo"]["handle"])] = l
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return list(linhas.values())


def motor(rotulo):
    m = MOTOR_RE.search(rotulo or "")
    return m[0] if m else None


def _montadora(db, nome, exibicao, logo_fonte):
    l = db.execute("SELECT id_veiculo_montadora FROM veiculo_montadora WHERE nome = ?", (nome,)).fetchone()
    if l:
        db.execute("UPDATE veiculo_montadora SET nome_exibicao = ?, logo_fonte = coalesce(?, logo_fonte), ativo = 1 "
                   "WHERE id_veiculo_montadora = ?", (exibicao, logo_fonte, l[0]))
        return l[0]
    return db.execute("INSERT INTO veiculo_montadora (nome, nome_exibicao, logo_fonte) VALUES (?, ?, ?)",
                      (nome, exibicao, logo_fonte)).lastrowid


def _modelo(db, id_vm, nome, exibicao, tipo, foto_fonte):
    l = db.execute("SELECT id_modelo FROM veiculo_modelo WHERE id_veiculo_montadora = ? AND nome = ?", (id_vm, nome)).fetchone()
    if l:
        db.execute("UPDATE veiculo_modelo SET nome_exibicao = ?, tipo = ?, foto_fonte = ?, ativo = 1 WHERE id_modelo = ?",
                   (exibicao, tipo, foto_fonte, l[0]))
        return l[0]
    return db.execute("INSERT INTO veiculo_modelo (id_veiculo_montadora, nome, nome_exibicao, tipo, foto_fonte) VALUES (?, ?, ?, ?, ?)",
                      (id_vm, nome, exibicao, tipo, foto_fonte)).lastrowid


def _versao(db, id_modelo, nome, exibicao):
    l = db.execute("SELECT id_versao FROM veiculo_versao WHERE id_modelo = ? AND nome = ?", (id_modelo, nome)).fetchone()
    if l:
        db.execute("UPDATE veiculo_versao SET nome_exibicao = ?, motor = ?, ativo = 1 WHERE id_versao = ?",
                   (exibicao, motor(exibicao), l[0]))
        return l[0]
    return db.execute("INSERT INTO veiculo_versao (id_modelo, nome, nome_exibicao, motor) VALUES (?, ?, ?, ?)",
                      (id_modelo, nome, exibicao, motor(exibicao))).lastrowid


def carregar_arvore(db, linhas, montadoras, ajustes=None):
    """Todos os tipos entram (carro, moto, pesado), com o tipo no modelo. ajustes: helper_veiculos_tipo.csv; o tipo que o
    dono deu vale já aqui, sem esperar uma nova coleta (a regra 1 da classificação vale sobre todas)."""
    # anos e ids do KarHub saem inteiros do arquivo; montadora, modelo e versão nunca são apagados (ids publicados)
    db.execute("DELETE FROM veiculo_versao_ano")
    db.execute("DELETE FROM veiculo_fonte")
    for tabela in ("veiculo_montadora", "veiculo_modelo", "veiculo_versao"):
        db.execute(f"UPDATE {tabela} SET ativo = 0")
    for l in linhas:
        tipo = (ajustes and ajuste_de(ajustes, montadoras.chaves(l["montadora"]["label"]), l["modelo"]["label"])) or l.get("tipo", "carro")
        id_vm = _montadora(db, montadoras.canonica(l["montadora"]["label"]), l["montadora"]["label"], l["montadora"].get("logo_url"))
        id_modelo = _modelo(db, id_vm, nome_canonico(l["modelo"]["label"]), l["modelo"]["label"], tipo, l["modelo"].get("foto_url"))
        for a in l["anos"]:
            for v in a["versoes"]:
                id_versao = _versao(db, id_modelo, nome_canonico(v["label"]), v["label"])
                db.execute("INSERT OR IGNORE INTO veiculo_versao_ano (id_versao, ano) VALUES (?, ?)", (id_versao, a["ano"]))
                for id_fonte in v["ids_fonte"]:
                    db.execute("INSERT OR REPLACE INTO veiculo_fonte (site, id_fonte, id_versao, ano) VALUES ('karhub', ?, ?, ?)",
                               (str(id_fonte), id_versao, a["ano"]))
    # anos do modelo saem dos anos das versões (dois handles do KarHub podem dar o mesmo nome canônico)
    db.execute("""UPDATE veiculo_modelo SET
                    ano_inicio = (SELECT min(va.ano) FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao)
                                  WHERE v.id_modelo = veiculo_modelo.id_modelo),
                    ano_fim = (SELECT max(va.ano) FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao)
                               WHERE v.id_modelo = veiculo_modelo.id_modelo)""")
    db.commit()
    um = lambda sql: db.execute(sql).fetchone()[0]
    return {"montadoras": um("SELECT count(*) FROM veiculo_montadora WHERE ativo = 1"),
            "modelos": um("SELECT count(*) FROM veiculo_modelo WHERE ativo = 1"),
            "versoes": um("SELECT count(*) FROM veiculo_versao WHERE ativo = 1"),
            "anos_versao": um("SELECT count(*) FROM veiculo_versao_ano")}
