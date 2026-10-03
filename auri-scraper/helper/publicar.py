"""Publica o helper.sqlite no Postgres `helper` do Wayap e as fotos na pasta do servidor (rsync). Fotos antes do banco."""
import re
import subprocess
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

from helper.banco import VERSAO_ESQUEMA

NOME_BANCO = "helper"

DDL_POSTGRES = [
    """CREATE TABLE IF NOT EXISTS marca (id_marca INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE, tipo TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS peca (
         id_peca INTEGER PRIMARY KEY, id_marca INTEGER NOT NULL REFERENCES marca(id_marca), codigo TEXT, ean TEXT,
         desc_curta TEXT NOT NULL, desc_completa TEXT, tipo_peca TEXT, ncm_sugerido TEXT, unidade_sugerida TEXT,
         tem_foto BOOLEAN NOT NULL DEFAULT FALSE, qtd_fontes INTEGER NOT NULL DEFAULT 0,
         status TEXT NOT NULL DEFAULT 'ativa', fundida_em INTEGER, hash_conteudo TEXT, atualizado_em TIMESTAMP)""",
    """CREATE INDEX IF NOT EXISTS peca_codigo ON peca (codigo)""",
    """CREATE INDEX IF NOT EXISTS peca_codigo_sem_zero ON peca (ltrim(codigo, '0'))""",
    """CREATE INDEX IF NOT EXISTS peca_ean ON peca (ean)""",
    """CREATE INDEX IF NOT EXISTS peca_tipo ON peca (tipo_peca)""",
    """CREATE TABLE IF NOT EXISTS codigo_alternativo (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca), tipo TEXT NOT NULL, valor TEXT NOT NULL,
         qtd_fontes INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (id_peca, tipo, valor))""",
    """CREATE INDEX IF NOT EXISTS alt_valor ON codigo_alternativo (valor)""",
    """CREATE INDEX IF NOT EXISTS alt_valor_sem_zero ON codigo_alternativo (ltrim(valor, '0'))""",
    """CREATE TABLE IF NOT EXISTS aplicacao (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca), montadora TEXT, modelo TEXT NOT NULL,
         ano_inicio INTEGER, ano_fim INTEGER, motor TEXT, observacao TEXT, texto_original TEXT)""",
    """CREATE INDEX IF NOT EXISTS aplicacao_peca ON aplicacao (id_peca)""",
    """CREATE INDEX IF NOT EXISTS aplicacao_modelo ON aplicacao (montadora, modelo)""",
    """CREATE TABLE IF NOT EXISTS foto (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca), ordem INTEGER NOT NULL, arquivo TEXT NOT NULL,
         largura INTEGER, altura INTEGER, bytes INTEGER, dhash BIGINT, origem_tipo TEXT NOT NULL,
         publicavel BOOLEAN NOT NULL DEFAULT TRUE, assinatura_visual BYTEA, url_fonte TEXT, PRIMARY KEY (id_peca, arquivo))""",
    """CREATE TABLE IF NOT EXISTS origem (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca), site TEXT NOT NULL, url TEXT NOT NULL,
         nome_original TEXT, marca_original TEXT, codigo_original TEXT, ean_original TEXT, carro_original TEXT,
         coletado_em DATE, PRIMARY KEY (site, url))""",
    """CREATE INDEX IF NOT EXISTS origem_peca ON origem (id_peca)""",
    """CREATE TABLE IF NOT EXISTS carga (
         id_carga SERIAL PRIMARY KEY, iniciada_em TIMESTAMP, terminada_em TIMESTAMP, pecas_ativas INTEGER,
         pecas_inativadas INTEGER, fotos_publicadas INTEGER, bytes_fotos BIGINT, versao_esquema INTEGER, commit_repo TEXT)""",
    """CREATE OR REPLACE VIEW v_peca AS
         SELECT p.*, m.nome AS marca, m.tipo AS tipo_marca FROM peca p JOIN marca m USING (id_marca) WHERE p.status = 'ativa'""",
    """CREATE OR REPLACE VIEW v_foto_publicavel AS
         SELECT id_peca, ordem, arquivo, largura, altura, origem_tipo,
                '/files/aGVscGVy/store/foto_produto/' || id_peca || '/' || arquivo AS url,
                '/files/aGVscGVy/store/foto_produto/' || id_peca || '/' || replace(arquivo, '.jpg', '_p.jpg') AS url_miniatura
         FROM foto WHERE publicavel ORDER BY id_peca, ordem""",
]


def funcoes_sql(com_trgm):
    """Funções do contrato (spec, seção 7). 'aGVscGVy' é base64('helper'), igual à regra de URL das sociedades."""
    normaliza = "upper(regexp_replace(translate($1, 'áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ', 'aaaaeeioooucAAAAEEIOOOUC'), '[^A-Za-z0-9/+;]', '', 'g'))"
    busca_texto = (
        """CREATE OR REPLACE FUNCTION busca_texto(texto TEXT, limite INTEGER DEFAULT 40) RETURNS SETOF v_peca AS $$
             -- desc_curta já é maiúscula e sem acento: o predicado fica sobre a coluna pura e usa o índice gin (trgm)
             WITH t AS (SELECT upper(unaccent($1)) AS q)
             SELECT v.* FROM v_peca v, t
             WHERE v.desc_curta % t.q OR v.desc_curta ILIKE '%' || t.q || '%'
             ORDER BY similarity(v.desc_curta, t.q) DESC, v.qtd_fontes DESC LIMIT $2
           $$ LANGUAGE sql STABLE"""
        if com_trgm else
        """CREATE OR REPLACE FUNCTION busca_texto(texto TEXT, limite INTEGER DEFAULT 40) RETURNS SETOF v_peca AS $$
             SELECT v.* FROM v_peca v
             WHERE (v.desc_curta || ' ' || coalesce(v.desc_completa, '')) ILIKE '%' || $1 || '%'
             ORDER BY v.qtd_fontes DESC LIMIT $2
           $$ LANGUAGE sql STABLE""")
    return [
        f"""CREATE OR REPLACE FUNCTION normaliza_codigo(TEXT) RETURNS TEXT AS $$
              SELECT trim(both '/' from regexp_replace(replace(replace({normaliza}, '+', '/'), ';', '/'), '/+', '/', 'g'))
            $$ LANGUAGE sql IMMUTABLE""",
        """CREATE OR REPLACE FUNCTION busca_codigo(texto TEXT) RETURNS SETOF v_peca AS $$
             WITH t AS (SELECT normaliza_codigo($1) AS c),
             exato AS (
               SELECT v.* FROM v_peca v, t WHERE t.c <> '' AND v.codigo = t.c
               UNION
               SELECT v.* FROM v_peca v JOIN codigo_alternativo a USING (id_peca), t WHERE t.c <> '' AND a.valor = t.c),
             sem_zero AS (
               SELECT v.* FROM v_peca v, t WHERE ltrim(t.c, '0') <> '' AND ltrim(v.codigo, '0') = ltrim(t.c, '0')
               UNION
               SELECT v.* FROM v_peca v JOIN codigo_alternativo a USING (id_peca), t WHERE ltrim(t.c, '0') <> '' AND ltrim(a.valor, '0') = ltrim(t.c, '0'))
             SELECT * FROM exato
             UNION ALL
             SELECT * FROM sem_zero WHERE NOT EXISTS (SELECT 1 FROM exato)
           $$ LANGUAGE sql STABLE""",
        """CREATE OR REPLACE FUNCTION busca_ean(texto TEXT) RETURNS SETOF v_peca AS $$
             WITH t AS (SELECT right(regexp_replace($1, '\\D', '', 'g'), 13) AS e)
             SELECT v.* FROM v_peca v, t WHERE length(t.e) = 13 AND v.ean = t.e
             UNION
             SELECT v.* FROM v_peca v JOIN codigo_alternativo a ON a.id_peca = v.id_peca AND a.tipo = 'ean', t
             WHERE length(t.e) = 13 AND a.valor = t.e
           $$ LANGUAGE sql STABLE""",
        busca_texto,
        """CREATE OR REPLACE FUNCTION busca_tipo(tipo TEXT, montadora TEXT DEFAULT NULL, modelo TEXT DEFAULT NULL,
                                                so_com_foto BOOLEAN DEFAULT FALSE, limite INTEGER DEFAULT 100) RETURNS SETOF v_peca AS $$
             SELECT DISTINCT v.* FROM v_peca v LEFT JOIN aplicacao ap USING (id_peca)
             WHERE v.tipo_peca LIKE upper($1) || '%'
               AND ($2 IS NULL OR ap.montadora = upper($2))
               AND ($3 IS NULL OR ap.modelo LIKE upper($3) || '%')
               AND (NOT $4 OR v.tem_foto)
             ORDER BY v.tem_foto DESC, v.qtd_fontes DESC LIMIT $5
           $$ LANGUAGE sql STABLE""",
    ]


def ler_env_admin(caminho):
    texto = Path(caminho).read_text(encoding="utf-8")
    return dict(re.findall(r"^(POSTGRES_[A-Z]+)=(.*)$", texto, re.M))


def conectar(env, dbname):
    return psycopg2.connect(host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"], user=env["POSTGRES_USER"],
                            password=env["POSTGRES_PASSWORD"], dbname=dbname, connect_timeout=15)


def criar_banco(env, nome=NOME_BANCO):
    con = conectar(env, "postgres")
    con.autocommit = True
    with con.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nome,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{nome}"')
    con.close()


def instalar_esquema(con):
    com_trgm = True
    with con.cursor() as cur:
        for ext in ("unaccent", "pg_trgm"):
            try:
                cur.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")
                con.commit()
            except psycopg2.Error:
                con.rollback()
                com_trgm = False
        for sql in DDL_POSTGRES + funcoes_sql(com_trgm):
            cur.execute(sql)
        if com_trgm:
            cur.execute("CREATE INDEX IF NOT EXISTS peca_desc_trgm ON peca USING gin (desc_curta gin_trgm_ops)")
    con.commit()
    return com_trgm


def diferencas(local, remoto):
    """local/remoto: id -> (hash_conteudo, status). Devolve ids a inserir, atualizar, inativar e iguais."""
    r = {"novas": [], "alteradas": [], "iguais": [], "inativar": []}
    for i, (h, s) in sorted(local.items()):
        if i not in remoto:
            r["novas"].append(i)
        elif remoto[i] != (h, s):
            r["alteradas"].append(i)
        else:
            r["iguais"].append(i)
    r["inativar"] = sorted(i for i, (h, s) in remoto.items() if i not in local and s == "ativa")
    return r


def comando_rsync(origem, destino_ssh, pasta_remota):
    # --partial-dir: transferência interrompida fica fora do nome final e é completada na próxima rodada.
    # Sem --delete: nunca apaga no destino. -a já pula arquivo idêntico, então não precisa de --ignore-existing.
    return ["rsync", "-a", "--partial", "--partial-dir=.rsync-partial", "--info=stats1",
            f"{str(origem).rstrip('/')}/", f"{destino_ssh}:{str(pasta_remota).rstrip('/')}/"]


def executar_rsync_real(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"rsync falhou ({r.returncode}): {r.stderr.strip()[:500]}")
    return r.stdout


def _linhas(db, sql, ids):
    marc = ",".join("?" * len(ids))
    return [dict(r) for r in db.execute(sql.format(ids=marc), ids)] if ids else []


def publicar(db, con, ensaio, executar_rsync, pasta_fotos, destino_ssh, pasta_remota, commit_repo):
    inicio = datetime.now()
    local = {r["id_peca"]: (r["hash_conteudo"], r["status"]) for r in db.execute("SELECT id_peca, hash_conteudo, status FROM peca")}
    with con.cursor() as cur:
        cur.execute("SELECT id_peca, hash_conteudo, status FROM peca")
        remoto = {i: (h, s) for i, h, s in cur.fetchall()}
    con.rollback()  # fecha a transação de leitura: o rsync pode levar horas e a sessão não pode ficar "idle in transaction"
    d = diferencas(local, remoto)
    # lista congelada: foto que o `fotos` gravar durante o rsync não sobe agora nem é marcada como publicada
    fotos_novas = [dict(r) for r in db.execute("SELECT id_peca, arquivo, bytes FROM foto WHERE publicada = 0")]
    resultado = {"novas": len(d["novas"]), "alteradas": len(d["alteradas"]), "iguais": len(d["iguais"]), "inativar": len(d["inativar"]),
                 "fotos_a_publicar": len(fotos_novas), "bytes_fotos": sum(f["bytes"] or 0 for f in fotos_novas), "fotos_publicadas": 0}
    if ensaio:
        return resultado
    # 1) fotos antes do banco: se falhar, nada é gravado
    if fotos_novas and destino_ssh:
        executar_rsync(comando_rsync(pasta_fotos, destino_ssh, pasta_remota))
    db.executemany("UPDATE foto SET publicada = 1 WHERE id_peca = ? AND arquivo = ?", [(f["id_peca"], f["arquivo"]) for f in fotos_novas])
    # 2) banco, em uma transação; só fotos já sincronizadas (publicada = 1) entram
    ids = d["novas"] + d["alteradas"]
    try:
        with con.cursor() as cur:
            cur.execute("SELECT 1")
            marcas = [dict(r) for r in db.execute("SELECT id_marca, nome, tipo FROM marca")]
            psycopg2.extras.execute_batch(cur, "INSERT INTO marca (id_marca, nome, tipo) VALUES (%(id_marca)s, %(nome)s, %(tipo)s) ON CONFLICT (id_marca) DO UPDATE SET nome = EXCLUDED.nome, tipo = EXCLUDED.tipo", marcas)
            for lote in (ids[i:i + 500] for i in range(0, len(ids), 500)):
                pecas = _linhas(db, "SELECT id_peca, id_marca, codigo, ean, desc_curta, desc_completa, tipo_peca, ncm_sugerido, unidade_sugerida, tem_foto, qtd_fontes, status, fundida_em, hash_conteudo, atualizado_em FROM peca WHERE id_peca IN ({ids})", lote)
                psycopg2.extras.execute_batch(cur, """INSERT INTO peca (id_peca, id_marca, codigo, ean, desc_curta, desc_completa, tipo_peca, ncm_sugerido, unidade_sugerida, tem_foto, qtd_fontes, status, fundida_em, hash_conteudo, atualizado_em)
                    VALUES (%(id_peca)s, %(id_marca)s, %(codigo)s, %(ean)s, %(desc_curta)s, %(desc_completa)s, %(tipo_peca)s, %(ncm_sugerido)s, %(unidade_sugerida)s, %(tem_foto)s::int::boolean, %(qtd_fontes)s, %(status)s, %(fundida_em)s, %(hash_conteudo)s, %(atualizado_em)s::timestamp)
                    ON CONFLICT (id_peca) DO UPDATE SET id_marca = EXCLUDED.id_marca, codigo = EXCLUDED.codigo, ean = EXCLUDED.ean, desc_curta = EXCLUDED.desc_curta,
                      desc_completa = EXCLUDED.desc_completa, tipo_peca = EXCLUDED.tipo_peca, ncm_sugerido = EXCLUDED.ncm_sugerido, unidade_sugerida = EXCLUDED.unidade_sugerida,
                      tem_foto = EXCLUDED.tem_foto, qtd_fontes = EXCLUDED.qtd_fontes, status = EXCLUDED.status, fundida_em = EXCLUDED.fundida_em,
                      hash_conteudo = EXCLUDED.hash_conteudo, atualizado_em = EXCLUDED.atualizado_em""", pecas)
                for tabela in ("codigo_alternativo", "aplicacao", "foto", "origem"):
                    cur.execute(f"DELETE FROM {tabela} WHERE id_peca = ANY(%s)", (lote,))
                psycopg2.extras.execute_batch(cur, "INSERT INTO codigo_alternativo (id_peca, tipo, valor, qtd_fontes) VALUES (%(id_peca)s, %(tipo)s, %(valor)s, %(qtd_fontes)s)",
                                              _linhas(db, "SELECT id_peca, tipo, valor, qtd_fontes FROM codigo_alternativo WHERE id_peca IN ({ids})", lote))
                psycopg2.extras.execute_batch(cur, "INSERT INTO aplicacao (id_peca, montadora, modelo, ano_inicio, ano_fim, motor, observacao, texto_original) VALUES (%(id_peca)s, %(montadora)s, %(modelo)s, %(ano_inicio)s, %(ano_fim)s, %(motor)s, %(observacao)s, %(texto_original)s)",
                                              _linhas(db, "SELECT id_peca, montadora, modelo, ano_inicio, ano_fim, motor, observacao, texto_original FROM aplicacao WHERE id_peca IN ({ids})", lote))
                psycopg2.extras.execute_batch(cur, "INSERT INTO foto (id_peca, ordem, arquivo, largura, altura, bytes, dhash, origem_tipo, publicavel, url_fonte) VALUES (%(id_peca)s, %(ordem)s, %(arquivo)s, %(largura)s, %(altura)s, %(bytes)s, %(dhash)s, %(origem_tipo)s, %(publicavel)s::int::boolean, %(url_fonte)s)",
                                              _linhas(db, "SELECT id_peca, ordem, arquivo, largura, altura, bytes, dhash, origem_tipo, publicavel, url_fonte FROM foto WHERE publicada = 1 AND id_peca IN ({ids})", lote))
                psycopg2.extras.execute_batch(cur, "INSERT INTO origem (id_peca, site, url, nome_original, marca_original, codigo_original, ean_original, carro_original, coletado_em) VALUES (%(id_peca)s, %(site)s, %(url)s, %(nome_original)s, %(marca_original)s, %(codigo_original)s, %(ean_original)s, %(carro_original)s, %(coletado_em)s::date) ON CONFLICT (site, url) DO UPDATE SET id_peca = EXCLUDED.id_peca",
                                              _linhas(db, "SELECT id_peca, site, url, nome_original, marca_original, codigo_original, ean_original, carro_original, coletado_em FROM origem WHERE id_peca IN ({ids})", lote))
            if d["inativar"]:
                cur.execute("UPDATE peca SET status = 'inativa', atualizado_em = now() WHERE id_peca = ANY(%s)", (d["inativar"],))
            cur.execute("SELECT count(*) FROM peca WHERE status = 'ativa'")
            ativas = cur.fetchone()[0]
            cur.execute("INSERT INTO carga (iniciada_em, terminada_em, pecas_ativas, pecas_inativadas, fotos_publicadas, bytes_fotos, versao_esquema, commit_repo) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (inicio, datetime.now(), ativas, len(d["inativar"]), len(fotos_novas), resultado["bytes_fotos"], VERSAO_ESQUEMA, commit_repo))
        con.commit()
    except Exception:
        con.rollback()
        db.rollback()
        raise
    db.execute("INSERT INTO carga (iniciada_em, terminada_em, pecas_ativas, pecas_inativadas, fotos_publicadas, bytes_fotos, versao_esquema, commit_repo, ensaio) VALUES (?,?,?,?,?,?,?,?,0)",
               (inicio.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), len(local), len(d["inativar"]), len(fotos_novas), resultado["bytes_fotos"], VERSAO_ESQUEMA, commit_repo))
    db.commit()
    resultado["fotos_publicadas"] = len(fotos_novas)
    return resultado
