"""Publica o helper.sqlite no Postgres `helper` do Wayap e as fotos na pasta do servidor (rsync). Fotos antes do banco."""
import io
import re
import subprocess
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

from helper.banco import VERSAO_ESQUEMA, ler_meta
from helper.montadoras import casar_wayap

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


def ddl_veiculos(tem_montadoras):
    """Spec de veículos, seções 6 e 9. tem_montadoras: a tabela montadoras do Wayap existe neste banco (só lida, nunca escrita)."""
    logo = "coalesce(w.logo, vm.logo)" if tem_montadoras else "vm.logo"
    junta = "LEFT JOIN montadoras w ON w.id_montadora = vm.id_montadora" if tem_montadoras else ""
    return [
        """CREATE TABLE IF NOT EXISTS veiculo_montadora (
             id_veiculo_montadora INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE, nome_exibicao TEXT NOT NULL, logo TEXT,
             id_montadora INTEGER, qtd_pecas INTEGER NOT NULL DEFAULT 0, ativo BOOLEAN NOT NULL DEFAULT TRUE)""",
        """CREATE TABLE IF NOT EXISTS veiculo_modelo (
             id_modelo INTEGER PRIMARY KEY, id_veiculo_montadora INTEGER NOT NULL REFERENCES veiculo_montadora(id_veiculo_montadora),
             nome TEXT NOT NULL, nome_exibicao TEXT NOT NULL, foto TEXT, foto_herdada BOOLEAN NOT NULL DEFAULT FALSE,
             ano_inicio INTEGER, ano_fim INTEGER, qtd_pecas INTEGER NOT NULL DEFAULT 0, ativo BOOLEAN NOT NULL DEFAULT TRUE,
             hash_conteudo TEXT, atualizado_em TIMESTAMP, UNIQUE (id_veiculo_montadora, nome))""",
        """CREATE TABLE IF NOT EXISTS veiculo_versao (
             id_versao INTEGER PRIMARY KEY, id_modelo INTEGER NOT NULL REFERENCES veiculo_modelo(id_modelo),
             nome TEXT NOT NULL, nome_exibicao TEXT NOT NULL, motor TEXT, ativo BOOLEAN NOT NULL DEFAULT TRUE)""",
        """CREATE INDEX IF NOT EXISTS veiculo_versao_modelo ON veiculo_versao (id_modelo)""",
        """CREATE TABLE IF NOT EXISTS veiculo_versao_ano (
             id_versao INTEGER NOT NULL REFERENCES veiculo_versao(id_versao), ano INTEGER NOT NULL, PRIMARY KEY (id_versao, ano))""",
        # sem chave estrangeira: carga de milhões de linhas; a ordem da publicação (peças antes) garante a integridade
        """CREATE TABLE IF NOT EXISTS peca_veiculo (
             id_peca INTEGER NOT NULL, id_modelo INTEGER NOT NULL, id_versao INTEGER,
             ano_inicio INTEGER, ano_fim INTEGER, nivel TEXT NOT NULL)""",
        """CREATE INDEX IF NOT EXISTS peca_veiculo_peca ON peca_veiculo (id_peca)""",
        """CREATE INDEX IF NOT EXISTS peca_veiculo_modelo ON peca_veiculo (id_modelo, ano_inicio, ano_fim)""",
        """CREATE TABLE IF NOT EXISTS peca_veiculo_estado (id_peca INTEGER PRIMARY KEY, hash TEXT NOT NULL)""",
        """ALTER TABLE carga ADD COLUMN IF NOT EXISTS modelos_publicados INTEGER""",
        """ALTER TABLE carga ADD COLUMN IF NOT EXISTS ligacoes_veiculo BIGINT""",
        f"""CREATE OR REPLACE VIEW v_veiculo_montadora AS
             SELECT vm.id_veiculo_montadora, vm.id_montadora, vm.nome, vm.nome_exibicao,
                    '/files/aGVscGVy/' || {logo} AS logo_url,
                    (SELECT count(*) FROM veiculo_modelo mo WHERE mo.id_veiculo_montadora = vm.id_veiculo_montadora AND mo.ativo) AS qtd_modelos,
                    vm.qtd_pecas
             FROM veiculo_montadora vm {junta}
             WHERE vm.ativo""",
        """CREATE OR REPLACE VIEW v_veiculo_modelo AS
             SELECT id_modelo, id_veiculo_montadora, nome, nome_exibicao, '/files/aGVscGVy/' || foto AS foto_url, foto_herdada,
                    ano_inicio, ano_fim, qtd_pecas
             FROM veiculo_modelo WHERE ativo""",
    ]


def funcoes_veiculos(com_trgm):
    """Consultas 7 a 9 da spec de veículos. Regra da confiança igual à de helper/consulta.py (ids_por_veiculo)."""
    if com_trgm:
        filtro = "p_texto IS NULL OR p.desc_curta ILIKE '%' || upper(unaccent(p_texto)) || '%' OR p.desc_curta % upper(unaccent(p_texto))"
        semelhanca = "CASE WHEN p_texto IS NULL THEN 0 ELSE similarity(p.desc_curta, upper(unaccent(p_texto))) END DESC,"
    else:
        filtro = "p_texto IS NULL OR p.desc_curta ILIKE '%' || p_texto || '%'"
        semelhanca = ""
    return [
        """CREATE OR REPLACE FUNCTION anos_do_modelo(p_modelo INTEGER) RETURNS TABLE (ano INTEGER) AS $$
             SELECT DISTINCT va.ano FROM veiculo_versao_ano va JOIN veiculo_versao v ON v.id_versao = va.id_versao
             WHERE v.id_modelo = p_modelo AND v.ativo ORDER BY va.ano DESC
           $$ LANGUAGE sql STABLE""",
        """CREATE OR REPLACE FUNCTION versoes_do_ano(p_modelo INTEGER, p_ano INTEGER)
             RETURNS TABLE (id_versao INTEGER, nome_exibicao TEXT, motor TEXT) AS $$
             SELECT v.id_versao, v.nome_exibicao, v.motor FROM veiculo_versao v JOIN veiculo_versao_ano va ON va.id_versao = v.id_versao
             WHERE v.id_modelo = p_modelo AND va.ano = p_ano AND v.ativo ORDER BY v.nome_exibicao
           $$ LANGUAGE sql STABLE""",
        """CREATE OR REPLACE FUNCTION ids_por_veiculo(p_modelo INTEGER, p_ano INTEGER, p_versao INTEGER DEFAULT NULL)
             RETURNS TABLE (id_peca INTEGER, confianca TEXT) AS $$
             WITH v AS (
               SELECT pv.id_peca, bool_or(pv.id_versao IS NULL) AS todas, coalesce(bool_or(pv.id_versao = p_versao), FALSE) AS esta
               FROM peca_veiculo pv JOIN peca pe ON pe.id_peca = pv.id_peca AND pe.status = 'ativa'
               WHERE pv.id_modelo = p_modelo AND pv.nivel = 'versao' AND p_ano BETWEEN pv.ano_inicio AND pv.ano_fim
                 -- linha de uma versão vale só nos anos da faixa em que a versão existe (spec 5.3): lacuna não conta
                 AND (pv.id_versao IS NULL OR EXISTS (SELECT 1 FROM veiculo_versao_ano va
                                                       WHERE va.id_versao = pv.id_versao AND va.ano = p_ano))
               GROUP BY pv.id_peca),
             m AS (
               SELECT DISTINCT pv.id_peca FROM peca_veiculo pv JOIN peca pe ON pe.id_peca = pv.id_peca AND pe.status = 'ativa'
               WHERE pv.id_modelo = p_modelo AND pv.nivel = 'modelo'
                 AND (pv.ano_inicio IS NULL OR pv.ano_inicio <= p_ano) AND (pv.ano_fim IS NULL OR pv.ano_fim >= p_ano))
             SELECT v.id_peca, CASE WHEN p_versao IS NOT NULL THEN 'versao' WHEN v.todas THEN 'todas_versoes' ELSE 'algumas_versoes' END
             FROM v WHERE p_versao IS NULL OR v.todas OR v.esta
             UNION ALL
             SELECT m.id_peca, 'modelo_ano' FROM m WHERE NOT EXISTS (SELECT 1 FROM v WHERE v.id_peca = m.id_peca)
           $$ LANGUAGE sql STABLE""",
        f"""CREATE OR REPLACE FUNCTION pecas_por_veiculo(p_modelo INTEGER, p_ano INTEGER, p_versao INTEGER DEFAULT NULL,
                                                        p_texto TEXT DEFAULT NULL, p_limite INTEGER DEFAULT 100)
             RETURNS TABLE (id_peca INTEGER, id_marca INTEGER, marca TEXT, codigo TEXT, ean TEXT, desc_curta TEXT, desc_completa TEXT,
                            tipo_peca TEXT, ncm_sugerido TEXT, unidade_sugerida TEXT, tem_foto BOOLEAN, qtd_fontes INTEGER,
                            confianca TEXT) AS $$
             SELECT p.id_peca, p.id_marca, p.marca, p.codigo, p.ean, p.desc_curta, p.desc_completa, p.tipo_peca, p.ncm_sugerido,
                    p.unidade_sugerida, p.tem_foto, p.qtd_fontes, i.confianca
             FROM ids_por_veiculo(p_modelo, p_ano, p_versao) i JOIN v_peca p ON p.id_peca = i.id_peca
             WHERE {filtro}
             ORDER BY CASE i.confianca WHEN 'algumas_versoes' THEN 2 WHEN 'modelo_ano' THEN 3 ELSE 1 END,
                      {semelhanca} p.tem_foto DESC, p.qtd_fontes DESC, p.id_peca
             LIMIT p_limite
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
        cur.execute("SELECT to_regclass('public.montadoras') IS NOT NULL")
        tem_montadoras = bool(cur.fetchone()[0])  # tabela do Wayap: só lida pela view v_veiculo_montadora
        for sql in DDL_POSTGRES + ddl_veiculos(tem_montadoras) + funcoes_sql(com_trgm) + funcoes_veiculos(com_trgm):
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


def comando_rsync(origem, destino_ssh, pasta_remota, excluir=()):
    # --partial-dir: transferência interrompida fica fora do nome final e é completada na próxima rodada.
    # Sem --delete: nunca apaga no destino. -a já pula arquivo idêntico, então não precisa de --ignore-existing.
    # --no-owner/--no-group: no servidor os arquivos ficam do usuário que recebe (root, como os da topcar), não do uid local.
    return (["rsync", "-a", "--no-owner", "--no-group", "--chmod=D755,F644", "--partial", "--partial-dir=.rsync-partial", "--info=stats1"]
            + [f"--exclude={e}" for e in excluir]
            + [f"{str(origem).rstrip('/')}/", f"{destino_ssh}:{str(pasta_remota).rstrip('/')}/"])


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


# ---------- veículos (spec de veículos, seção 8) ----------

def veiculos_preparados(db):
    """False quando o `helper.py veiculos` nunca rodou (publica só as peças, como antes)."""
    feito, preparado = ler_meta(db, "veiculos_em"), ler_meta(db, "preparado_em")
    if not feito:
        return False
    if preparado and feito < preparado:
        raise RuntimeError("o helper.py veiculos é mais antigo que o último preparar (uma fusão pode ter mudado ids de peça): "
                           "rode python helper.py veiculos antes de publicar")
    return True


def _tsv(linhas):
    buf = io.StringIO()
    for l in linhas:
        buf.write("\t".join("\\N" if v is None else str(v) for v in l) + "\n")
    buf.seek(0)
    return buf


def _lotes(ids, n):
    return (ids[i:i + n] for i in range(0, len(ids), n))


def publicar_veiculos(db, con, ensaio, executar_rsync, pasta_fotos, destino_ssh, pasta_remota, lote_pecas=5000):
    # 0) leituras do destino; a montadoras do Wayap só é lida, nunca escrita
    with con.cursor() as cur:
        cur.execute("SELECT to_regclass('public.montadoras') IS NOT NULL")
        wayap = []
        if cur.fetchone()[0]:
            cur.execute("SELECT id_montadora, descricao FROM montadoras")
            wayap = list(cur.fetchall())
        remoto_m, remoto_mod, remoto_pv = {}, {}, {}
        # o ensaio não instala o esquema: antes da primeira publicação as tabelas veiculo_* ainda não existem no destino
        cur.execute("SELECT to_regclass('public.veiculo_montadora') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("SELECT id_veiculo_montadora, nome, nome_exibicao, logo, id_montadora, qtd_pecas, ativo FROM veiculo_montadora")
            remoto_m = {l[0]: tuple(l) for l in cur.fetchall()}
            cur.execute("SELECT id_modelo, hash_conteudo FROM veiculo_modelo")
            remoto_mod = {i: h for i, h in cur.fetchall()}
            cur.execute("SELECT id_peca, hash FROM peca_veiculo_estado")
            remoto_pv = {i: h for i, h in cur.fetchall()}
    con.rollback()  # o rsync pode demorar: a sessão não fica "idle in transaction"
    montadoras = []
    for m in db.execute("SELECT * FROM veiculo_montadora ORDER BY id_veiculo_montadora").fetchall():
        id_wayap = casar_wayap(m["nome"], wayap)
        db.execute("UPDATE veiculo_montadora SET id_montadora = ? WHERE id_veiculo_montadora = ?", (id_wayap, m["id_veiculo_montadora"]))
        montadoras.append((m["id_veiculo_montadora"], m["nome"], m["nome_exibicao"], m["logo"], id_wayap, m["qtd_pecas"], bool(m["ativo"])))
    db.commit()
    montadoras = [t for t in montadoras if remoto_m.get(t[0]) != t]
    modelos = sorted(i for i, h in db.execute("SELECT id_modelo, hash_conteudo FROM veiculo_modelo") if remoto_mod.get(i) != h)
    local_pv = {i: h for i, h in db.execute("SELECT id_peca, hash FROM peca_veiculo_estado")}
    d = diferencas({i: (h, "ativa") for i, h in local_pv.items()}, {i: (h, "ativa") for i, h in remoto_pv.items()})
    gravar, apagar = d["novas"] + d["alteradas"], sorted(set(remoto_pv) - set(local_pv))
    arquivos = [l[0] for l in db.execute("SELECT caminho FROM veiculo_arquivo WHERE publicado = 0")]
    r = {"montadoras": len(montadoras), "modelos": len(modelos), "pecas_veiculo": len(gravar),
         "pecas_veiculo_apagar": len(apagar), "arquivos_veiculo": len(arquivos)}
    if ensaio:
        return r
    # 1) arquivos antes do banco: se o rsync falhar, nada é gravado
    if arquivos and destino_ssh:
        executar_rsync(comando_rsync(pasta_fotos, destino_ssh, pasta_remota, excluir=("proprias/", ".gitignore")))
    db.executemany("UPDATE veiculo_arquivo SET publicado = 1 WHERE caminho = ?", [(a,) for a in arquivos])
    db.commit()
    # 2) montadoras e árvore, numa transação
    try:
        with con.cursor() as cur:
            psycopg2.extras.execute_batch(cur, """INSERT INTO veiculo_montadora (id_veiculo_montadora, nome, nome_exibicao, logo, id_montadora, qtd_pecas, ativo)
                VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id_veiculo_montadora) DO UPDATE SET nome = EXCLUDED.nome,
                  nome_exibicao = EXCLUDED.nome_exibicao, logo = EXCLUDED.logo, id_montadora = EXCLUDED.id_montadora,
                  qtd_pecas = EXCLUDED.qtd_pecas, ativo = EXCLUDED.ativo""", montadoras)
            for lote in _lotes(modelos, 500):
                psycopg2.extras.execute_batch(cur, """INSERT INTO veiculo_modelo (id_modelo, id_veiculo_montadora, nome, nome_exibicao, foto, foto_herdada,
                      ano_inicio, ano_fim, qtd_pecas, ativo, hash_conteudo, atualizado_em)
                    VALUES (%(id_modelo)s, %(id_veiculo_montadora)s, %(nome)s, %(nome_exibicao)s, %(foto)s, %(foto_herdada)s::int::boolean,
                      %(ano_inicio)s, %(ano_fim)s, %(qtd_pecas)s, %(ativo)s::int::boolean, %(hash_conteudo)s, %(atualizado_em)s::timestamp)
                    ON CONFLICT (id_modelo) DO UPDATE SET id_veiculo_montadora = EXCLUDED.id_veiculo_montadora, nome = EXCLUDED.nome,
                      nome_exibicao = EXCLUDED.nome_exibicao, foto = EXCLUDED.foto, foto_herdada = EXCLUDED.foto_herdada,
                      ano_inicio = EXCLUDED.ano_inicio, ano_fim = EXCLUDED.ano_fim, qtd_pecas = EXCLUDED.qtd_pecas, ativo = EXCLUDED.ativo,
                      hash_conteudo = EXCLUDED.hash_conteudo, atualizado_em = EXCLUDED.atualizado_em""",
                    _linhas(db, "SELECT id_modelo, id_veiculo_montadora, nome, nome_exibicao, foto, foto_herdada, ano_inicio, ano_fim, "
                                "qtd_pecas, ativo, hash_conteudo, atualizado_em FROM veiculo_modelo WHERE id_modelo IN ({ids})", lote))
                psycopg2.extras.execute_batch(cur, """INSERT INTO veiculo_versao (id_versao, id_modelo, nome, nome_exibicao, motor, ativo)
                    VALUES (%(id_versao)s, %(id_modelo)s, %(nome)s, %(nome_exibicao)s, %(motor)s, %(ativo)s::int::boolean)
                    ON CONFLICT (id_versao) DO UPDATE SET id_modelo = EXCLUDED.id_modelo, nome = EXCLUDED.nome,
                      nome_exibicao = EXCLUDED.nome_exibicao, motor = EXCLUDED.motor, ativo = EXCLUDED.ativo""",
                    _linhas(db, "SELECT id_versao, id_modelo, nome, nome_exibicao, motor, ativo FROM veiculo_versao WHERE id_modelo IN ({ids})", lote))
                cur.execute("DELETE FROM veiculo_versao_ano WHERE id_versao IN (SELECT id_versao FROM veiculo_versao WHERE id_modelo = ANY(%s))", (lote,))
                psycopg2.extras.execute_batch(cur, "INSERT INTO veiculo_versao_ano (id_versao, ano) VALUES (%(id_versao)s, %(ano)s)",
                    _linhas(db, "SELECT va.id_versao, va.ano FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao) "
                                "WHERE v.id_modelo IN ({ids})", lote))
        con.commit()
    except Exception:
        con.rollback()
        raise
    # 3) peca_veiculo em lotes, com commit por lote: uma queda continua de onde parou na próxima rodada
    for lote in _lotes(apagar, lote_pecas):
        with con.cursor() as cur:
            cur.execute("DELETE FROM peca_veiculo WHERE id_peca = ANY(%s)", (lote,))
            cur.execute("DELETE FROM peca_veiculo_estado WHERE id_peca = ANY(%s)", (lote,))
        con.commit()
    ligacoes = 0
    for lote in _lotes(gravar, lote_pecas):
        try:
            with con.cursor() as cur:
                cur.execute("DELETE FROM peca_veiculo WHERE id_peca = ANY(%s)", (lote,))
                marc = ",".join("?" * len(lote))
                linhas = db.execute(f"SELECT id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo "
                                    f"WHERE id_peca IN ({marc}) ORDER BY id_peca", lote).fetchall()
                cur.copy_expert("COPY peca_veiculo (id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel) FROM STDIN", _tsv(linhas))
                psycopg2.extras.execute_batch(cur, "INSERT INTO peca_veiculo_estado (id_peca, hash) VALUES (%s, %s) "
                                                   "ON CONFLICT (id_peca) DO UPDATE SET hash = EXCLUDED.hash",
                                              [(i, local_pv[i]) for i in lote])
            con.commit()
            ligacoes += len(linhas)
        except Exception:
            con.rollback()
            raise
    with con.cursor() as cur:
        cur.execute("UPDATE carga SET modelos_publicados = %s, ligacoes_veiculo = %s WHERE id_carga = (SELECT max(id_carga) FROM carga)",
                    (len(modelos), ligacoes))
    con.commit()
    r["ligacoes_gravadas"] = ligacoes
    return r
