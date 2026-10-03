"""Consultas do contrato (spec, seção 7) sobre o SQLite local. O Postgres implementa as mesmas regras em SQL (publicar.py)."""
from helper.normalizar import normalizar_codigo, normalizar_ean


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
