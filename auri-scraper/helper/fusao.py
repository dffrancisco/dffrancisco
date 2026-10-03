"""Funde anúncios de várias fontes em uma linha por peça do mercado e grava no SQLite com ids estáveis."""
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime

from helper.aplicacoes import aplicacoes_do_anuncio, juntar_aplicacoes
from helper.banco import id_marca
from helper.normalizar import (codigos_kit, desc_completa, desc_curta, normalizar_codigo, normalizar_ean,
                               so_zeros_diferem, tipo_peca, unidade_sugerida)


# ---------- agrupamento ----------

def _chave(marca, codigo, ean, url):
    if marca and codigo:
        return f"{marca}|{codigo}"
    if marca and ean:
        return f"{marca}|EAN:{ean}"
    if not marca and ean:
        return f"|EAN:{ean}"
    return f"URL:{url}"


class _UniaoBusca:
    def __init__(self):
        self.pai = {}

    def achar(self, x):
        self.pai.setdefault(x, x)
        while self.pai[x] != x:
            self.pai[x] = self.pai[self.pai[x]]
            x = self.pai[x]
        return x

    def unir(self, a, b):
        self.pai[self.achar(a)] = self.achar(b)


def _sem_repetidos(anuncios):
    """A mesma URL pode vir do .jsonl e do produto.json do mesmo site (pecas_karhub nasce do karhub.jsonl):
    fica o anúncio de maior prioridade (menor número), que é o mais rico."""
    por_url = {}
    for a in anuncios:
        chave = (a["site"], a["url"])
        if chave not in por_url or a["prioridade"] < por_url[chave]["prioridade"]:
            por_url[chave] = a
    return list(por_url.values())


def _preparar(anuncios, marcas):
    for a in _sem_repetidos(anuncios):
        marca, tipo_marca = marcas.canonica(a.get("marca"))
        codigo = normalizar_codigo(a.get("codigo"))
        ean = normalizar_ean(a.get("ean"))
        yield dict(a, _marca=marca, _tipo_marca=tipo_marca, _codigo=codigo, _ean=ean,
                   _chave=_chave(marca, codigo, ean, a.get("url")))


def _agrupar(preparados, marcas):
    uniao = _UniaoBusca()
    por_ean = defaultdict(list)
    for a in preparados:
        uniao.achar(a["_chave"])
        if a["_ean"] and not a["_chave"].startswith("URL:"):
            por_ean[a["_ean"]].append(a)
    for ean, lista in por_ean.items():
        base = lista[0]
        for outro in lista[1:]:
            if not base["_marca"] or not outro["_marca"] or marcas.compativeis(base["_marca"], outro["_marca"]):
                uniao.unir(outro["_chave"], base["_chave"])
    grupos = defaultdict(list)
    for a in preparados:
        grupos[uniao.achar(a["_chave"])].append(a)
    return list(grupos.values())


# ---------- montagem da peça ----------

def _escolher_codigo(grupo, conflitos, marca):
    contagem = Counter(a["_codigo"] for a in grupo if a["_codigo"])
    if not contagem:
        return None
    codigos = list(contagem)
    if len(codigos) == 1:
        return codigos[0]
    if all(so_zeros_diferem(x, y) for i, x in enumerate(codigos) for y in codigos[i + 1:]):
        return max(codigos, key=len)  # o que tem o zero à esquerda é o oficial; a outra grafia fica só na origem
    melhor = max(codigos, key=lambda c: (contagem[c], -min(a["prioridade"] for a in grupo if a["_codigo"] == c), len(c)))
    conflitos.append({"tipo": "codigo", "chave": f"{marca}|{melhor}", "valores": sorted(codigos), "escolhido": melhor})
    return melhor


def _montar(grupo, marcas, vocab, stats, conflitos):
    grupo.sort(key=lambda a: (a["prioridade"], a["site"], a["url"]))
    marcas_validas = Counter(a["_marca"] for a in grupo if a["_marca"])
    marca = marcas_validas.most_common(1)[0][0] if marcas_validas else ""
    tipo_marca = next((a["_tipo_marca"] for a in grupo if a["_marca"] == marca), "desconhecida")
    codigo = _escolher_codigo(grupo, conflitos, marca)
    eans = Counter(a["_ean"] for a in grupo if a["_ean"])
    ean = eans.most_common(1)[0][0] if eans else None
    chave = _chave(marca, codigo, ean, grupo[0]["url"])
    if len(eans) > 1:
        conflitos.append({"tipo": "ean", "chave": chave, "valores": sorted(eans), "escolhido": ean})
    alternativos = Counter()
    for e in eans:
        if e != ean:
            alternativos[("ean", e)] += eans[e]
    for a in grupo:
        if a["_codigo"] and a["_codigo"] != codigo and not (codigo and so_zeros_diferem(a["_codigo"], codigo)):
            alternativos[("fabricante", a["_codigo"])] += 1
        for eq in a.get("equivalentes") or []:
            e = normalizar_ean(eq)
            if e and e != ean:
                alternativos[("ean", e)] += 1
            elif not e:
                c = normalizar_codigo(eq)
                if c and c != codigo:
                    alternativos[("original", c)] += 1
    for parte in codigos_kit(codigo or ""):
        alternativos[("kit", parte)] += 1
    principal = grupo[0]
    dc = desc_curta(principal["nome"], marca=principal.get("marca"), codigo=principal.get("codigo")) or \
        desc_curta(principal["nome"]) or (codigo or "PECA")
    nome_longo = max((a["nome"] or "" for a in grupo), key=len)
    tipo = tipo_peca(dc)
    aplicacoes = juntar_aplicacoes([l for a in grupo for l in aplicacoes_do_anuncio(a, vocab)])
    fotos, vistas = [], set()
    for a in grupo:
        for im in a.get("imagens") or []:
            if im.get("url") and im["url"] not in vistas:
                vistas.add(im["url"])
                fotos.append({"url": im["url"], "arquivo_local": im.get("arquivo_local"), "prioridade": a["prioridade"], "site": a["site"]})
    origens = [{"site": a["site"], "url": a["url"], "nome_original": a.get("nome"), "marca_original": a.get("marca"),
                "codigo_original": a.get("codigo"), "ean_original": a.get("ean"), "carro_original": a.get("carro"),
                "coletado_em": a.get("coletado_em")} for a in grupo]
    return {"marca": marca, "tipo_marca": tipo_marca, "codigo": codigo, "ean": ean, "chave": chave,
            "desc_curta": dc, "desc_completa": desc_completa(nome_longo), "tipo_peca": tipo,
            "ncm_sugerido": stats.ncm(tipo, marca), "unidade_sugerida": unidade_sugerida(dc, stats.unidade(marca)),
            "qtd_fontes": len(grupo), "alternativos": sorted((t, v, n) for (t, v), n in alternativos.items()),
            "aplicacoes": aplicacoes, "fotos": fotos, "origens": origens}


def fundir(anuncios, marcas, vocab, stats):
    conflitos = []
    preparados = list(_preparar(anuncios, marcas))
    pecas = [_montar(g, marcas, vocab, stats, conflitos) for g in _agrupar(preparados, marcas)]
    pecas.sort(key=lambda p: p["chave"])
    return pecas, conflitos


# ---------- gravação com ids estáveis ----------

CAMPOS_HASH = ("id_marca", "codigo", "ean", "desc_curta", "desc_completa", "tipo_peca", "ncm_sugerido",
               "unidade_sugerida", "tem_foto", "qtd_fontes", "status", "fundida_em")


def hash_peca(db, id_peca):
    p = db.execute("SELECT * FROM peca WHERE id_peca = ?", (id_peca,)).fetchone()
    partes = [{k: p[k] for k in CAMPOS_HASH},
              [tuple(r) for r in db.execute("SELECT tipo, valor, qtd_fontes FROM codigo_alternativo WHERE id_peca=? ORDER BY tipo, valor", (id_peca,))],
              [tuple(r) for r in db.execute("SELECT montadora, modelo, ano_inicio, ano_fim, motor, observacao FROM aplicacao WHERE id_peca=? ORDER BY 1,2,3,4,5", (id_peca,))],
              [tuple(r) for r in db.execute("SELECT ordem, arquivo, origem_tipo FROM foto WHERE id_peca=? AND publicavel=1 ORDER BY ordem", (id_peca,))]]
    return hashlib.sha1(json.dumps(partes, ensure_ascii=False, default=str).encode()).hexdigest()


def atualizar_hash(db, id_peca):
    novo = hash_peca(db, id_peca)
    atual = db.execute("SELECT hash_conteudo FROM peca WHERE id_peca=?", (id_peca,)).fetchone()[0]
    if novo == atual:
        return False
    db.execute("UPDATE peca SET hash_conteudo=?, atualizado_em=? WHERE id_peca=?", (novo, datetime.now().isoformat(timespec="seconds"), id_peca))
    return True


def _ids_existentes(db, peca):
    ids = set()
    linha = db.execute("SELECT id_peca FROM peca WHERE chave = ?", (peca["chave"],)).fetchone()
    if linha:
        ids.add(linha[0])
    for o in peca["origens"]:
        linha = db.execute("SELECT id_peca FROM origem WHERE site=? AND url=?", (o["site"], o["url"])).fetchone()
        if linha:
            ids.add(linha[0])
    vivos = set()
    for i in ids:  # segue a cadeia de fundida_em até a peça viva
        atual = i
        while True:
            l = db.execute("SELECT status, fundida_em FROM peca WHERE id_peca=?", (atual,)).fetchone()
            if l is None or l["status"] == "ativa" or not l["fundida_em"]:
                break
            atual = l["fundida_em"]
        vivos.add(atual)
    return vivos


def _apagar_filhos(db, id_peca, com_fotos=False):
    db.execute("DELETE FROM codigo_alternativo WHERE id_peca=?", (id_peca,))
    db.execute("DELETE FROM aplicacao WHERE id_peca=?", (id_peca,))
    db.execute("DELETE FROM origem WHERE id_peca=?", (id_peca,))
    if com_fotos:
        db.execute("DELETE FROM foto_pendente WHERE id_peca=?", (id_peca,))


def gravar(db, pecas_fundidas):
    r = Counter(novas=0, alteradas=0, iguais=0, inativadas_por_fusao=0, inativadas_por_sumico=0)
    vistos = set()
    proximo = (db.execute("SELECT coalesce(max(id_peca), 0) FROM peca").fetchone()[0]) + 1
    for p in pecas_fundidas:
        ids = _ids_existentes(db, p)
        if ids:
            id_peca = min(ids)
            for outro in ids - {id_peca}:
                db.execute("UPDATE peca SET status='inativa', fundida_em=? WHERE id_peca=?", (id_peca, outro))
                db.execute("UPDATE foto SET id_peca=? WHERE id_peca=? AND arquivo NOT IN (SELECT arquivo FROM foto WHERE id_peca=?)", (id_peca, outro, id_peca))
                _apagar_filhos(db, outro, com_fotos=True)
                atualizar_hash(db, outro)
                r["inativadas_por_fusao"] += 1
            nova = False
        else:
            id_peca, proximo, nova = proximo, proximo + 1, True
        vistos.add(id_peca)
        idm = id_marca(db, p["marca"] or "(SEM MARCA)", p["tipo_marca"] if p["marca"] else "desconhecida")
        # outra peça pode estar com esta chave (ex.: fusão trocou chaves); libera antes de gravar
        db.execute("UPDATE peca SET chave = 'ANTIGA:' || id_peca || ':' || chave WHERE chave=? AND id_peca<>?", (p["chave"], id_peca))
        db.execute("""INSERT INTO peca (id_peca, id_marca, chave, codigo, ean, desc_curta, desc_completa, tipo_peca, ncm_sugerido,
                                        unidade_sugerida, qtd_fontes, status, fundida_em)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,'ativa',NULL)
                      ON CONFLICT(id_peca) DO UPDATE SET id_marca=excluded.id_marca, chave=excluded.chave, codigo=excluded.codigo,
                        ean=excluded.ean, desc_curta=excluded.desc_curta, desc_completa=excluded.desc_completa,
                        tipo_peca=excluded.tipo_peca, ncm_sugerido=excluded.ncm_sugerido, unidade_sugerida=excluded.unidade_sugerida,
                        qtd_fontes=excluded.qtd_fontes, status='ativa', fundida_em=NULL""",
                   (id_peca, idm, p["chave"], p["codigo"], p["ean"], p["desc_curta"], p["desc_completa"], p["tipo_peca"],
                    p["ncm_sugerido"], p["unidade_sugerida"], p["qtd_fontes"]))
        _apagar_filhos(db, id_peca)
        db.executemany("INSERT INTO codigo_alternativo (id_peca, tipo, valor, qtd_fontes) VALUES (?,?,?,?)",
                       [(id_peca, t, v, n) for t, v, n in p["alternativos"]])
        db.executemany("""INSERT OR IGNORE INTO aplicacao (id_peca, montadora, modelo, ano_inicio, ano_fim, motor, observacao, texto_original, modelo_reconhecido)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                       [(id_peca, l["montadora"], l["modelo"], l["ano_inicio"], l["ano_fim"], l["motor"], l["observacao"],
                         l["texto_original"], int(l["modelo_reconhecido"])) for l in p["aplicacoes"]])
        db.executemany("INSERT OR REPLACE INTO origem (id_peca, site, url, nome_original, marca_original, codigo_original, ean_original, carro_original, coletado_em) VALUES (?,?,?,?,?,?,?,?,?)",
                       [(id_peca, o["site"], o["url"], o["nome_original"], o["marca_original"], o["codigo_original"], o["ean_original"], o["carro_original"], o["coletado_em"]) for o in p["origens"]])
        ja_tem = {r0[0] for r0 in db.execute("SELECT url_fonte FROM foto WHERE id_peca=?", (id_peca,))}
        db.executemany("INSERT OR IGNORE INTO foto_pendente (id_peca, url, arquivo_local, prioridade, site) VALUES (?,?,?,?,?)",
                       [(id_peca, f["url"], f["arquivo_local"], f["prioridade"], f["site"]) for f in p["fotos"] if f["url"] not in ja_tem])
        if nova:
            atualizar_hash(db, id_peca)
            r["novas"] += 1
        elif atualizar_hash(db, id_peca):
            r["alteradas"] += 1
        else:
            r["iguais"] += 1
    marcadores = ",".join("?" * len(vistos)) or "NULL"
    sumidas = [l[0] for l in db.execute(f"SELECT id_peca FROM peca WHERE status='ativa' AND id_peca NOT IN ({marcadores})", tuple(vistos))]
    for id_peca in sumidas:
        db.execute("UPDATE peca SET status='inativa' WHERE id_peca=?", (id_peca,))
        atualizar_hash(db, id_peca)
        r["inativadas_por_sumico"] += 1
    db.commit()
    return dict(r)
