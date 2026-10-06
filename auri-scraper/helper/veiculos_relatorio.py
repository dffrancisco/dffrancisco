"""Relatório do `helper.py veiculos` (markdown) e planilha com o tipo de todos os modelos coletados."""
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

from helper.veiculo_tipo import ajuste_de


def _jsonl(caminho):
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    saida = []
    for texto in caminho.read_text(encoding="utf-8").splitlines():
        try:
            saida.append(json.loads(texto))
        except json.JSONDecodeError:
            continue
    return saida


def _primeira_versao(linha):
    for a in linha.get("anos") or []:
        if a["versoes"]:
            return a["versoes"][0]["label"]
    return ""


def salvar_tipos_csv(pasta_veiculos, destino, ajustes=None, montadoras=None):
    """Uma linha por (montadora, modelo): a da árvore vale sobre a de excluídos, e o ajuste do dono sobre as duas."""
    pasta = Path(pasta_veiculos)
    por_modelo = {}
    for l in _jsonl(pasta / "karhub_excluidos.jsonl"):
        por_modelo[(l["montadora"]["label"], l["modelo"]["label"])] = (l.get("tipo", ""), l.get("motivo_tipo", ""),
                                                                       (l.get("versoes_exemplo") or [""])[0])
    for l in _jsonl(pasta / "karhub_arvore.jsonl"):
        por_modelo[(l["montadora"]["label"], l["modelo"]["label"])] = (l.get("tipo", "carro"), l.get("motivo_tipo", ""),
                                                                       _primeira_versao(l))
    linhas = []
    for (montadora, modelo), (tipo, motivo, versao) in por_modelo.items():
        ajuste = ajuste_de(ajustes, montadoras.chaves(montadora), modelo) if ajustes and montadoras else None
        if ajuste:
            tipo, motivo = ajuste, "ajuste"
        linhas.append((montadora, modelo, tipo, motivo, versao))
    with Path(destino).open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["montadora", "modelo", "tipo", "motivo", "versao_exemplo"])
        w.writerows(sorted(linhas))
    return Counter((t, m) for _, _, t, m, _ in linhas)


def gerar(db, estat, tipos, sem_modelo):
    def um(sql):
        return db.execute(sql).fetchone()[0]
    img, lig = estat.get("imagens", {}), estat.get("ligacao", {})
    por_nivel = dict(db.execute("SELECT nivel, count(*) FROM vei_peca GROUP BY nivel").fetchall())
    L = [f"# Helper: veículos em {date.today().isoformat()}", "", "## Árvore", "",
         f"- Montadoras ativas: {um('SELECT count(*) FROM vei_montadora WHERE ativo = 1')}",
         f"- Modelos ativos: {um('SELECT count(*) FROM vei_modelo WHERE ativo = 1')}",
         f"- Versões ativas: {um('SELECT count(*) FROM vei_versao WHERE ativo = 1')}",
         f"- Anos-versão: {um('SELECT count(*) FROM vei_versao_ano')}", "",
         "## Tipos dos modelos", "", "| tipo | motivo | modelos |", "|---|---|---|"]
    L += [f"| {t} | {m} | {n} |" for (t, m), n in sorted(tipos.items())]
    L += ["", "Planilha completa em `<data>-veiculos-tipos.csv`; correções vão em `helper_veiculos_tipo.csv`.", "",
          "## Montadoras", "",
          f"- Ligadas à `montadoras` do Wayap (na última publicação): "
          f"{um('SELECT count(*) FROM vei_montadora WHERE ativo = 1 AND id_montadora IS NOT NULL')}",
          "- Sem par no Wayap: " + (", ".join(r[0] for r in db.execute(
              "SELECT nome FROM vei_montadora WHERE ativo = 1 AND id_montadora IS NULL ORDER BY nome")) or "nenhuma"), "",
          "## Imagens", "",
          f"- Fotos de modelo: do KarHub {img.get('foto_karhub', 0)}, próprias {img.get('foto_propria', 0)}, "
          f"herdadas {img.get('foto_herdada', 0)}, sem foto {img.get('foto_sem', 0)}, inválidas {img.get('foto_invalida', 0)}",
          f"- Logos: do KarHub {img.get('logo_karhub', 0)}, próprios {img.get('logo_propria', 0)}, "
          f"sem logo {img.get('logo_sem', 0)}, inválidos {img.get('logo_invalida', 0)}", "",
          "### 100 modelos com mais peças sem foto (candidatos a foto própria)", "", "| montadora | modelo | peças |", "|---|---|---|"]
    L += [f"| {a} | {b} | {n} |" for a, b, n in db.execute(
        """SELECT vm.nome, mo.nome, mo.qtd_pecas FROM vei_modelo mo JOIN vei_montadora vm USING (id_veiculo_montadora)
           WHERE mo.ativo = 1 AND mo.foto IS NULL ORDER BY mo.qtd_pecas DESC, vm.nome, mo.nome LIMIT 100""")]
    L += ["", "## Ligação peça → veículo", "",
          f"- Peças com nível versão (KarHub): {lig.get('pecas_nivel_versao', 0)}",
          f"- Peças com nível modelo (texto de aplicação): {lig.get('pecas_nivel_modelo', 0)}",
          f"- Linhas de vei_peca: {sum(por_nivel.values())} "
          f"(versão {por_nivel.get('versao', 0)}, modelo {por_nivel.get('modelo', 0)})",
          f"- Ids de veículo fora da árvore (motos, pesados ou novos): {lig.get('ids_desconhecidos', 0)}",
          f"- Anúncios do KarHub sem linha de compatibilidade: {lig.get('handles_sem_compat', 0)}",
          f"- Aplicações que não casaram com modelo: {lig.get('aplicacoes_sem_modelo', 0)}", "",
          "### 50 aplicações mais comuns sem modelo", "", "| aplicação | ocorrências |", "|---|---|"]
    L += [f"| {texto} | {n} |" for texto, n in sem_modelo.most_common(50)]
    return "\n".join(L) + "\n"
