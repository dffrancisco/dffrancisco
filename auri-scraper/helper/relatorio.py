"""Relatório de qualidade do helper.sqlite em markdown."""
from datetime import date
from pathlib import Path


def _um(db, sql, *p):
    return db.execute(sql, p).fetchone()[0]


def gerar(db, extras=None):
    extras = extras or {}
    linhas = [f"# Helper: relatório de {date.today().isoformat()}", ""]
    if "fontes" in extras:
        linhas += ["## Fontes lidas", "", "| site | arquivos | anúncios | linhas inválidas |", "|---|---|---|---|"]
        for site, f in sorted(extras["fontes"].items()):
            linhas.append(f"| {site} | {f['arquivos']} | {f['anuncios']} | {f['invalidas']} |")
        linhas.append("")
    if "gravacao" in extras:
        g = extras["gravacao"]
        linhas += ["## Esta preparação", "",
                   f"- Peças novas: {g['novas']}", f"- Peças alteradas: {g['alteradas']}", f"- Peças iguais: {g['iguais']}",
                   f"- Inativadas por fusão: {g['inativadas_por_fusao']}", f"- Inativadas por sumiço das fontes: {g['inativadas_por_sumico']}",
                   f"- Conflitos de EAN: {extras.get('conflitos_ean', 0)}", f"- Conflitos de código: {extras.get('conflitos_codigo', 0)}", ""]
    linhas += ["## Situação do banco", "",
               f"- Peças ativas: {_um(db, 'SELECT count(*) FROM peca WHERE status=\"ativa\"')}",
               f"- Peças inativas: {_um(db, 'SELECT count(*) FROM peca WHERE status=\"inativa\"')}",
               f"- Peças sem marca: {_um(db, 'SELECT count(*) FROM peca p JOIN marca m USING (id_marca) WHERE p.status=\"ativa\" AND m.nome=\"(SEM MARCA)\"')}",
               f"- Peças com marca desconhecida: {_um(db, 'SELECT count(*) FROM peca p JOIN marca m USING (id_marca) WHERE p.status=\"ativa\" AND m.tipo=\"desconhecida\" AND m.nome<>\"(SEM MARCA)\"')}",
               f"- Peças sem código: {_um(db, 'SELECT count(*) FROM peca WHERE status=\"ativa\" AND codigo IS NULL')}",
               f"- Peças sem EAN: {_um(db, 'SELECT count(*) FROM peca WHERE status=\"ativa\" AND ean IS NULL')}",
               f"- Peças sem aplicação: {_um(db, 'SELECT count(*) FROM peca p WHERE status=\"ativa\" AND NOT EXISTS (SELECT 1 FROM aplicacao a WHERE a.id_peca=p.id_peca)')}",
               f"- Peças sem foto baixada: {_um(db, 'SELECT count(*) FROM peca WHERE status=\"ativa\" AND tem_foto=0')}",
               f"- Fotos pendentes de download: {_um(db, 'SELECT count(*) FROM foto_pendente')}",
               f"- Fotos baixadas: {_um(db, 'SELECT count(*) FROM foto')} (publicáveis: {_um(db, 'SELECT count(*) FROM foto WHERE publicavel=1')})", ""]
    linhas += ["## Marcas desconhecidas mais frequentes", "", "| marca | peças |", "|---|---|"]
    for nome, n in db.execute("SELECT m.nome, count(*) FROM peca p JOIN marca m USING (id_marca) WHERE m.tipo='desconhecida' AND p.status='ativa' GROUP BY m.nome ORDER BY 2 DESC LIMIT 50"):
        linhas.append(f"| {nome} | {n} |")
    linhas += ["", "## Modelos de carro não reconhecidos mais frequentes", "", "| modelo | aplicações |", "|---|---|"]
    for modelo, n in db.execute("SELECT modelo, count(*) FROM aplicacao WHERE modelo_reconhecido=0 GROUP BY modelo ORDER BY 2 DESC LIMIT 50"):
        linhas.append(f"| {modelo} | {n} |")
    return "\n".join(linhas) + "\n"


def salvar(texto, pasta, nome):
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{date.today().isoformat()}-{nome}"
    caminho.write_text(texto, encoding="utf-8")
    return caminho
