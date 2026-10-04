"""CLI do helper. Uso: python helper.py {preparar|fotos|relatorio|cobertura|publicar} [opções]."""
import argparse
import csv
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from helper import banco, consulta, fontes, fusao, relatorio, topcar, veiculos, veiculos_fotos, veiculos_ligar, veiculos_relatorio
from helper import fotos as fotos_mod
from helper import publicar as pub
from helper.marcas import Marcas
from helper.montadoras import ARQUIVO_PADRAO as MONTADORAS_PADRAO, Montadoras, nome_canonico
from helper.veiculo_tipo import carregar_ajustes
from wayap_fotos import ENV_ADMIN, carregar_env


def _args_comuns(p):
    p.add_argument("--base", type=Path, default=Path("."), help="pasta com catalogos/ e pecas_* (padrão: atual)")
    p.add_argument("--banco", type=Path, default=None, help="helper.sqlite (padrão: <base>/helper.sqlite)")
    p.add_argument("--topcar-cache", type=Path, default=None, help="padrão: <base>/helper_cache/topcar.json")
    p.add_argument("--marcas", type=Path, default=Path(__file__).resolve().parents[1] / "helper_marcas.csv")
    p.add_argument("--montadoras", type=Path, default=MONTADORAS_PADRAO, help="apelidos de montadora (helper_montadoras.csv)")


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
    banco.gravar_meta(db, "preparado_em", banco.agora())  # o publicar recusa veículos ligados antes desta fusão
    db.commit()
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
    r = fotos_mod.processar_pendentes(db, args.base / "helper_fotos", config, limite=args.limite, marca=args.marca,
                                      tipo=args.tipo, prioridade=args.prioridade, so_prioridade=args.so_prioridade)
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


def cmd_publicar(args):
    carregar_env()
    db = banco.abrir(args.banco)
    try:
        com_veiculos = pub.veiculos_preparados(db)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    destino_ssh, pasta_remota = os.environ.get("HELPER_SSH"), os.environ.get("HELPER_FOTOS_DIR", "/home/wayap/helper/store/foto_produto")
    if not args.ensaio and not destino_ssh:
        print("defina HELPER_SSH (ex.: wayap@servidor) no .env para publicar fotos", file=sys.stderr)
        return 2
    env = pub.ler_env_admin(ENV_ADMIN)
    if not args.ensaio:  # o ensaio não grava nada, nem esquema: só lê o que já está no destino
        pub.criar_banco(env)
    con = pub.conectar(env, pub.NOME_BANCO)
    if not args.ensaio and not pub.instalar_esquema(con):
        print("aviso: unaccent/pg_trgm indisponíveis; busca_texto ficou sem tolerância a erro de digitação", file=sys.stderr)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or None
    r = pub.publicar(db, con, ensaio=args.ensaio, executar_rsync=pub.executar_rsync_real, pasta_fotos=args.base / "helper_fotos",
                     destino_ssh=destino_ssh, pasta_remota=pasta_remota, commit_repo=commit)
    print(("ENSAIO: " if args.ensaio else "publicado: ") + ", ".join(f"{k} {v}" for k, v in r.items()))
    if com_veiculos:
        rv = pub.publicar_veiculos(db, con, ensaio=args.ensaio, executar_rsync=pub.executar_rsync_real,
                                   pasta_fotos=args.base / "helper_fotos_veiculos", destino_ssh=destino_ssh,
                                   pasta_remota=os.environ.get("HELPER_VEICULOS_DIR", "/home/wayap/helper/veiculos"))
        print(("ENSAIO veículos: " if args.ensaio else "veículos publicados: ") + ", ".join(f"{k} {v}" for k, v in rv.items()))
    return 0


def cmd_veiculos(args):
    inicio = time.time()
    pasta = args.base / "veiculos"
    arq_arvore = pasta / "karhub_arvore.jsonl"
    if not arq_arvore.exists():
        print(f"sem {arq_arvore}: rode python catalogo_karhub_veiculos.py fipe e depois arvore", file=sys.stderr)
        return 2
    db = banco.abrir(args.banco)
    montadoras = Montadoras.carregar(args.montadoras)
    ajustes = carregar_ajustes()  # helper_veiculos_tipo.csv: correção de tipo vale já, sem recoletar
    estat = {"arvore": veiculos.carregar_arvore(db, veiculos.ler_arvore(arq_arvore), montadoras, ajustes)}
    print("árvore:", ", ".join(f"{k} {v}" for k, v in estat["arvore"].items()))
    estat["imagens"] = veiculos_fotos.processar_imagens(db, pasta / "imagens", args.base / "helper_fotos_veiculos")
    print("imagens:", ", ".join(f"{k} {v}" for k, v in sorted(estat["imagens"].items())))
    estat["ligacao"], sem_modelo = veiculos_ligar.ligar(db, pasta / "karhub_compat.jsonl", montadoras)
    print("ligação:", ", ".join(f"{k} {v}" for k, v in sorted(estat["ligacao"].items())))
    args.relatorios.mkdir(parents=True, exist_ok=True)
    tipos = veiculos_relatorio.salvar_tipos_csv(pasta, args.relatorios / f"{time.strftime('%Y-%m-%d')}-veiculos-tipos.csv",
                                                ajustes, montadoras)
    caminho = relatorio.salvar(veiculos_relatorio.gerar(db, estat, tipos, sem_modelo), args.relatorios, "veiculos.md")
    print(f"relatório em {caminho}; {time.time() - inicio:.0f}s")
    return 0


def cmd_pecas_do_veiculo(args):
    db = banco.abrir(args.banco)
    montadora = Montadoras.carregar(args.montadoras).canonica(args.montadora)
    modelo = db.execute("""SELECT mo.id_modelo FROM vei_modelo mo JOIN vei_montadora vm USING (id_veiculo_montadora)
                           WHERE vm.nome = ? AND mo.nome = ? AND mo.ativo = 1""", (montadora, nome_canonico(args.modelo))).fetchone()
    if not modelo:
        print(f"modelo não encontrado: {montadora} {nome_canonico(args.modelo)}", file=sys.stderr)
        return 1
    id_versao = None
    if args.versao:
        versao = db.execute("SELECT id_versao FROM vei_versao WHERE id_modelo = ? AND nome = ? AND ativo = 1",
                            (modelo[0], nome_canonico(args.versao))).fetchone()
        if not versao:
            print(f"versão não encontrada: {args.versao}. Versões de {args.ano}:")
            for (nome,) in db.execute("""SELECT v.nome_exibicao FROM vei_versao v JOIN vei_versao_ano va USING (id_versao)
                                         WHERE v.id_modelo = ? AND va.ano = ? AND v.ativo = 1 ORDER BY 1""", (modelo[0], args.ano)):
                print(f"  {nome}")
            return 1
        id_versao = versao[0]
    pecas = consulta.pecas_por_veiculo(db, modelo[0], args.ano, id_versao, args.texto, args.limite)
    for p in pecas:
        print(f"{p['confianca']:<16} {p['marca'][:20]:<20} {(p['codigo'] or ''):<18} {p['desc_curta']}")
    print(f"{len(pecas)} peças")
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
    sp.add_argument("--config-fotos", type=Path, default=Path(__file__).resolve().parents[1] / "helper_fotos.toml")
    sp.set_defaults(fn=cmd_fotos)
    sp = sub.add_parser("cobertura")
    _args_comuns(sp)
    sp.set_defaults(fn=cmd_cobertura)
    sp = sub.add_parser("veiculos", help="árvore de veículos, imagens e ligação peça -> veículo (depois do preparar)")
    _args_comuns(sp)
    sp.set_defaults(fn=cmd_veiculos)
    sp = sub.add_parser("pecas-do-veiculo", help="conferência: peças de um veículo, com a confiança")
    _args_comuns(sp)
    sp.add_argument("montadora")
    sp.add_argument("modelo")
    sp.add_argument("ano", type=int)
    sp.add_argument("--versao", default=None)
    sp.add_argument("--texto", default=None)
    sp.add_argument("--limite", type=int, default=100)
    sp.set_defaults(fn=cmd_pecas_do_veiculo)
    sp = sub.add_parser("publicar")
    _args_comuns(sp)
    sp.add_argument("--ensaio", action="store_true")
    sp.set_defaults(fn=cmd_publicar)
    args = _resolver(p.parse_args(argv))
    return args.fn(args)
