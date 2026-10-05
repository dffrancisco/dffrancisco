"""CLI do helper. Uso: python helper.py {preparar|fotos|relatorio|cobertura|lista|publicar} [opções]."""
import argparse
import csv
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from helper import banco, consulta, fontes, fusao, lista, relatorio, topcar
from helper import fotos as fotos_mod
from helper import publicar as pub
from helper.marcas import Marcas
from wayap_fotos import ENV_ADMIN, carregar_env


def _args_comuns(p):
    p.add_argument("--base", type=Path, default=Path("."), help="pasta com catalogos/ e pecas_* (padrão: atual)")
    p.add_argument("--banco", type=Path, default=None, help="helper.sqlite (padrão: <base>/helper.sqlite)")
    p.add_argument("--topcar-cache", type=Path, default=None, help="padrão: <base>/helper_cache/topcar.json")
    p.add_argument("--marcas", type=Path, default=Path(__file__).resolve().parents[1] / "helper_marcas.csv")


def _resolver(args):
    args.banco = args.banco or args.base / "helper.sqlite"
    args.topcar_cache = args.topcar_cache or args.base / "helper_cache/topcar.json"
    args.relatorios = args.base / "helper_relatorios"
    return args


def _dados_topcar(args):
    try:
        return topcar.carregar(cache=args.topcar_cache)
    except SystemExit as e:  # sem WAYAP_* no ambiente e sem cache
        print(f"aviso: sem dados da topcar ({e}); vocabulário de carros e NCM ficam vazios", file=sys.stderr)
        return {"marcas": [], "carros": [], "produtos": []}


def preparar(args):
    inicio = time.time()
    db = banco.abrir(args.banco)
    marcas = Marcas.carregar(args.marcas)
    dados = _dados_topcar(args)
    vocab, stats = topcar.vocabulario_carros(dados), topcar.Estatisticas(dados["produtos"])
    anuncios, por_site = [], defaultdict(lambda: {"arquivos": 0, "anuncios": 0, "invalidas": 0})
    for fonte in fontes.fontes_disponiveis(args.base):
        erros, n = [], 0
        for a in fontes.ler_fonte(fonte, erros):
            anuncios.append(a)
            n += 1
        por_site[fonte.site]["arquivos"] += 1
        por_site[fonte.site]["anuncios"] += n
        por_site[fonte.site]["invalidas"] += len(erros)
        db.execute("INSERT OR REPLACE INTO fonte_lida (caminho, site, mtime, anuncios) VALUES (?,?,?,?)", (str(fonte.caminho), fonte.site, fonte.mtime, n))
    print(f"{len(anuncios)} anúncios lidos de {sum(f['arquivos'] for f in por_site.values())} arquivos em {time.time() - inicio:.0f}s")
    pecas, conflitos = fusao.fundir(anuncios, marcas, vocab, stats)
    print(f"{len(pecas)} peças após a fusão; {len(conflitos)} conflitos")
    resultado = fusao.gravar(db, pecas, pasta_fotos=args.base / "helper_fotos")
    print("gravação:", ", ".join(f"{k} {v}" for k, v in resultado.items()))
    args.relatorios.mkdir(parents=True, exist_ok=True)
    marcas.salvar_desconhecidas(args.relatorios / f"{time.strftime('%Y-%m-%d')}-marcas-desconhecidas.csv")
    with (args.relatorios / f"{time.strftime('%Y-%m-%d')}-conflitos.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["tipo", "chave", "valores", "escolhido"])
        w.writerows([c["tipo"], c["chave"], "|".join(c["valores"]), c["escolhido"]] for c in conflitos)
    extras = {"fontes": dict(por_site), "gravacao": resultado,
              "conflitos_ean": sum(c["tipo"] == "ean" for c in conflitos), "conflitos_codigo": sum(c["tipo"] == "codigo" for c in conflitos)}
    caminho = relatorio.salvar(relatorio.gerar(db, extras), args.relatorios, "preparar.md")
    ativas = db.execute("SELECT count(*) FROM peca WHERE status='ativa'").fetchone()[0]
    print(f"peças ativas: {ativas}; relatório em {caminho}; {time.time() - inicio:.0f}s")
    return 0


def cmd_relatorio(args):
    db = banco.abrir(args.banco)
    caminho = relatorio.salvar(relatorio.gerar(db), args.relatorios, "relatorio.md")
    print(caminho.read_text(encoding="utf-8"))
    return 0


def cmd_fotos(args):
    db = banco.abrir(args.banco)
    config = fotos_mod.carregar_config(args.config_fotos)
    ids = {int(l) for l in args.lista.read_text(encoding="utf-8").split()} if args.lista else None
    r = fotos_mod.processar_pendentes(db, args.base / "helper_fotos", config, limite=args.limite, marca=args.marca,
                                      tipo=args.tipo, prioridade=args.prioridade, so_prioridade=args.so_prioridade, ids=ids)
    print("fotos:", ", ".join(f"{k} {v}" for k, v in r.items()))
    print("pendentes restantes:", db.execute("SELECT count(*) FROM foto_pendente WHERE tentativas < 3").fetchone()[0])
    return 0


def cmd_cobertura(args):
    db = banco.abrir(args.banco)
    dados = _dados_topcar(args)
    produtos = topcar.produtos_para_cobertura(dados)
    r = consulta.cobertura(db, produtos)
    linhas = ["| marca | produtos | por EAN | por código | não encontrados | cobertura |", "|---|---|---|---|---|---|"]
    tot = {"total": 0, "por_ean": 0, "por_codigo": 0, "nao_encontrados": 0}
    for marca, c in sorted(r.items(), key=lambda kv: -kv[1]["total"]):
        for k in tot:
            tot[k] += c[k]
        linhas.append(f"| {marca} | {c['total']} | {c['por_ean']} | {c['por_codigo']} | {c['nao_encontrados']} | {100 * (c['por_ean'] + c['por_codigo']) / c['total']:.0f}% |")
    if tot["total"]:
        linhas.append(f"| **TOTAL** | {tot['total']} | {tot['por_ean']} | {tot['por_codigo']} | {tot['nao_encontrados']} | {100 * (tot['por_ean'] + tot['por_codigo']) / tot['total']:.0f}% |")
    texto = "# Cobertura do helper sobre a topcar\n\n" + "\n".join(linhas) + "\n"
    caminho = relatorio.salvar(texto, args.relatorios, "cobertura.md")
    print(texto)
    print("gravado em", caminho)
    return 0


def cmd_lista(args):
    db = banco.abrir(args.banco)
    casador = lista.Casador(db, Marcas.carregar(args.marcas))
    pasta = args.base / "helper_listas" / (args.nome or args.planilha.stem.lower())
    pasta.mkdir(parents=True, exist_ok=True)
    contagem, ids_ativos = defaultdict(int), set()
    with (pasta / "itens.csv").open("w", encoding="utf-8", newline="") as f_itens, \
            (pasta / "pendentes.csv").open("w", encoding="utf-8", newline="") as f_pend:
        itens, pendentes = csv.writer(f_itens, delimiter=";"), csv.writer(f_pend, delimiter=";")
        itens.writerow(["cod", "via", "ids", "foto", "marca_divergente", "ativo", "ean", "catalogo", "marca", "nome", "grupo"])
        pendentes.writerow(["cod", "ean", "catalogo", "marca", "nome", "grupo"])
        for item in lista.ler_planilha(args.planilha):
            r = casador.casar(item)
            foto = lista.situacao_foto(db, r["ids"])
            via = r["via"] or "nao_achou"
            itens.writerow([item.cod, via, ",".join(map(str, r["ids"])), foto, "S" if r["marca_divergente"] else "",
                            "S" if item.ativo else "N", item.ean or "", item.catalogo, item.marca, item.nome, item.grupo])
            if not item.ativo:
                contagem[("inativo", "")] += 1
                continue
            contagem[(via, foto)] += 1
            ids_ativos.update(r["ids"])
            if not r["ids"]:
                pendentes.writerow([item.cod, item.ean or "", item.catalogo, item.marca, item.nome, item.grupo])
    (pasta / "ids.txt").write_text("".join(f"{i}\n" for i in sorted(ids_ativos)), encoding="utf-8")
    ativos = sum(n for (via, _), n in contagem.items() if via != "inativo")
    linhas = [f"# Lista {pasta.name}: {args.planilha.name}", "", f"{ativos} itens ativos ({contagem[('inativo', '')]} inativos fora)", "",
              "| casou por | foto | itens | % dos ativos |", "|---|---|---|---|"]
    for (via, foto), n in sorted(contagem.items(), key=lambda kv: -kv[1]):
        if via != "inativo":
            linhas.append(f"| {via} | {foto or '-'} | {n} | {100 * n / max(ativos, 1):.1f}% |")
    texto = "\n".join(linhas) + f"\n\nPeças do helper casadas: {len(ids_ativos)} (em ids.txt)\n"
    (pasta / "resumo.md").write_text(texto, encoding="utf-8")
    print(texto)
    print("gravado em", pasta)
    return 0


def cmd_publicar(args):
    carregar_env()
    db = banco.abrir(args.banco)
    destino_ssh, pasta_remota = os.environ.get("HELPER_SSH"), os.environ.get("HELPER_FOTOS_DIR", "/home/wayap/helper/store/foto_produto")
    if not args.ensaio and not destino_ssh:
        print("defina HELPER_SSH (ex.: wayap@servidor) no .env para publicar fotos", file=sys.stderr)
        return 2
    env = pub.ler_env_admin(ENV_ADMIN)
    pub.criar_banco(env)
    con = pub.conectar(env, pub.NOME_BANCO)
    com_trgm = pub.instalar_esquema(con)
    if not com_trgm:
        print("aviso: unaccent/pg_trgm indisponíveis; busca_texto ficou sem tolerância a erro de digitação", file=sys.stderr)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or None
    r = pub.publicar(db, con, ensaio=args.ensaio, executar_rsync=pub.executar_rsync_real, pasta_fotos=args.base / "helper_fotos",
                     destino_ssh=destino_ssh, pasta_remota=pasta_remota, commit_repo=commit)
    print(("ENSAIO: " if args.ensaio else "publicado: ") + ", ".join(f"{k} {v}" for k, v in r.items()))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="comando", required=True)
    for nome, fn in (("preparar", preparar), ("relatorio", cmd_relatorio)):
        sp = sub.add_parser(nome)
        _args_comuns(sp)
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("fotos")
    _args_comuns(sp)
    sp.add_argument("--limite", type=int, default=None)
    sp.add_argument("--marca", default=None)
    sp.add_argument("--tipo", default=None, help="começo do tipo de peça, ex.: LANTERNA")
    sp.add_argument("--prioridade", action="store_true", help="peças 'com cara' (helper_fotos.toml) primeiro")
    sp.add_argument("--so-prioridade", action="store_true", help="só as peças 'com cara' (onda prioritária)")
    sp.add_argument("--lista", type=Path, default=None, help="ids.txt de helper.py lista: só as peças da lista do cliente")
    sp.add_argument("--config-fotos", type=Path, default=Path(__file__).resolve().parents[1] / "helper_fotos.toml")
    sp.set_defaults(fn=cmd_fotos)
    sp = sub.add_parser("cobertura")
    _args_comuns(sp)
    sp.set_defaults(fn=cmd_cobertura)
    sp = sub.add_parser("lista", help="casa a planilha de peças de um cliente com o helper")
    _args_comuns(sp)
    sp.add_argument("planilha", type=Path)
    sp.add_argument("--nome", default=None, help="pasta em helper_listas/ (padrão: nome do arquivo)")
    sp.set_defaults(fn=cmd_lista)
    sp = sub.add_parser("publicar")
    _args_comuns(sp)
    sp.add_argument("--ensaio", action="store_true")
    sp.set_defaults(fn=cmd_publicar)
    args = _resolver(p.parse_args(argv))
    return args.fn(args)
