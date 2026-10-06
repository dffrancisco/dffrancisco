"""Consultas do contrato (spec, seção 7) sobre o SQLite local. O Postgres implementa as mesmas regras em SQL (publicar.py)."""
from collections import defaultdict

from helper.normalizar import normalizar_codigo, normalizar_ean
from wayap_fotos import sem_acento


def normalizar_busca(texto):
    return normalizar_codigo(texto)


def por_codigo(db, texto):
    """Exatos primeiro; sem resultado, tolera zero à esquerda no texto e no banco (só na comparação).
    Duas buscas unidas em vez de OR entre tabelas, para cada uma usar o próprio índice."""
    t = normalizar_busca(texto)
    if not t:
        return []
    sql = """SELECT id_peca FROM peca WHERE status='ativa' AND codigo = ?
             UNION
             SELECT p.id_peca FROM codigo_alternativo a JOIN peca p USING (id_peca) WHERE a.valor = ? AND p.status='ativa'
             ORDER BY 1"""
    ids = [l[0] for l in db.execute(sql, (t, t))]
    if ids:
        return ids
    sem_zero = t.lstrip("0")
    if not sem_zero:
        return []
    sql = """SELECT id_peca FROM peca WHERE status='ativa' AND ltrim(codigo, '0') = ?
             UNION
             SELECT p.id_peca FROM codigo_alternativo a JOIN peca p USING (id_peca) WHERE ltrim(a.valor, '0') = ? AND p.status='ativa'
             ORDER BY 1"""
    return [l[0] for l in db.execute(sql, (sem_zero, sem_zero))]


def por_ean(db, texto):
    e = normalizar_ean(texto)
    if not e:
        return []
    sql = """SELECT id_peca FROM peca WHERE status='ativa' AND ean = ?
             UNION
             SELECT p.id_peca FROM codigo_alternativo a JOIN peca p USING (id_peca) WHERE a.tipo = 'ean' AND a.valor = ? AND p.status='ativa'
             ORDER BY 1"""
    return [l[0] for l in db.execute(sql, (e, e))]


def peca_completa(db, id_peca):
    p = db.execute("SELECT p.*, m.nome AS marca FROM peca p JOIN marca m USING (id_marca) WHERE id_peca=?", (id_peca,)).fetchone()
    if not p:
        return None
    d = {k: p[k] for k in ("id_peca", "marca", "codigo", "ean", "desc_curta", "desc_completa", "tipo_peca", "ncm_sugerido",
                           "unidade_sugerida", "tem_foto", "qtd_fontes", "status")}
    d["alternativos"] = [{"tipo": r["tipo"], "valor": r["valor"]} for r in db.execute(
        "SELECT tipo, valor FROM codigo_alternativo WHERE id_peca=? ORDER BY tipo, valor", (id_peca,))]
    d["aplicacoes"] = [dict(r) for r in db.execute(
        "SELECT montadora, modelo, ano_inicio, ano_fim, motor, observacao FROM aplicacao WHERE id_peca=? ORDER BY montadora, modelo, ano_inicio", (id_peca,))]
    d["fotos"] = [dict(r) for r in db.execute(
        "SELECT ordem, arquivo, largura, altura, origem_tipo FROM foto WHERE id_peca=? AND publicavel=1 ORDER BY ordem", (id_peca,))]
    return d


def cobertura(db, produtos_topcar):
    resultado = {}
    for p in produtos_topcar:
        marca = (p.get("marca") or "(SEM MARCA)").upper()
        r = resultado.setdefault(marca, {"total": 0, "por_ean": 0, "por_codigo": 0, "nao_encontrados": 0})
        r["total"] += 1
        if p.get("cod_barra") and por_ean(db, p["cod_barra"]):
            r["por_ean"] += 1
        elif any(por_codigo(db, c) for c in (p.get("num_fabricante"), p.get("num_fabricante2")) if c):
            r["por_codigo"] += 1
        else:
            r["nao_encontrados"] += 1
    return resultado


# ---------- consultas 8 e 9 da spec de veículos (o Postgres implementa as mesmas regras em publicar.py) ----------

ORDEM_CONFIANCA = {"versao": 1, "todas_versoes": 1, "algumas_versoes": 2, "modelo_ano": 3}


def ids_por_veiculo(db, id_modelo, ano, id_versao=None):
    versao = defaultdict(lambda: {"todas": False, "esta": False})
    # linha de uma versão vale só nos anos da faixa em que a versão existe (spec 5.3): uma lacuna não conta
    for id_peca, v in db.execute(
            """SELECT pv.id_peca, pv.id_versao FROM vei_peca pv JOIN peca p USING (id_peca)
               WHERE pv.id_modelo = ? AND pv.nivel = 'versao' AND ? BETWEEN pv.ano_inicio AND pv.ano_fim AND p.status = 'ativa'
                 AND (pv.id_versao IS NULL OR EXISTS (SELECT 1 FROM vei_versao_ano va
                                                       WHERE va.id_versao = pv.id_versao AND va.ano = ?))""",
            (id_modelo, ano, ano)):
        e = versao[id_peca]
        e["todas"] = e["todas"] or v is None
        e["esta"] = e["esta"] or (id_versao is not None and v == id_versao)
    r = {}
    for id_peca, e in versao.items():
        if id_versao is None:
            r[id_peca] = "todas_versoes" if e["todas"] else "algumas_versoes"
        elif e["todas"] or e["esta"]:
            r[id_peca] = "versao"
        # versão escolhida e a peça só serve em outras: o KarHub diz que não serve, fica de fora
    for (id_peca,) in db.execute(
            """SELECT DISTINCT pv.id_peca FROM vei_peca pv JOIN peca p USING (id_peca)
               WHERE pv.id_modelo = ? AND pv.nivel = 'modelo' AND p.status = 'ativa'
                 -- texto sem ano nenhum ('Gol G3') não vale para um ano escolhido; faixa aberta escrita ('após 08') vale
                 AND (pv.ano_inicio IS NOT NULL OR pv.ano_fim IS NOT NULL)
                 AND (pv.ano_inicio IS NULL OR pv.ano_inicio <= ?) AND (pv.ano_fim IS NULL OR pv.ano_fim >= ?)""",
            (id_modelo, ano, ano)):
        if id_peca not in versao:
            r[id_peca] = "modelo_ano"
    return r


def pecas_por_veiculo(db, id_modelo, ano, id_versao=None, texto=None, limite=100):
    ids = ids_por_veiculo(db, id_modelo, ano, id_versao)
    if not ids:
        return []
    # um modelo popular tem dezenas de milhares de peças: tabela temporária em vez de IN (?, ?, ...)
    db.execute("CREATE TEMP TABLE IF NOT EXISTS ids_veiculo (id_peca INTEGER PRIMARY KEY, confianca TEXT)")
    db.execute("DELETE FROM ids_veiculo")
    db.executemany("INSERT INTO ids_veiculo VALUES (?, ?)", ids.items())
    filtro = " ".join(sem_acento(texto).upper().split()) if texto else None
    linhas = db.execute(
        """SELECT p.id_peca, p.id_marca, m.nome AS marca, p.codigo, p.ean, p.desc_curta, p.desc_completa, p.tipo_peca,
                  p.ncm_sugerido, p.unidade_sugerida, p.tem_foto, p.qtd_fontes, i.confianca
           FROM ids_veiculo i JOIN peca p USING (id_peca) JOIN marca m USING (id_marca)
           WHERE ? IS NULL OR p.desc_curta LIKE '%' || ? || '%'""", (filtro, filtro)).fetchall()
    pecas = sorted((dict(l) for l in linhas),
                   key=lambda d: (ORDEM_CONFIANCA[d["confianca"]], -d["tem_foto"], -d["qtd_fontes"], d["id_peca"]))
    return pecas[:limite]
