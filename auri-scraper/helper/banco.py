"""Banco local de preparação do helper (SQLite). Mesmo modelo da spec, seção 4."""
import sqlite3

VERSAO_ESQUEMA = 1

DDL = [
    """CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT)""",
    """CREATE TABLE IF NOT EXISTS marca (
         id_marca INTEGER PRIMARY KEY AUTOINCREMENT,
         nome TEXT NOT NULL UNIQUE,
         tipo TEXT NOT NULL CHECK (tipo IN ('reposicao','montadora','desconhecida')))""",
    """CREATE TABLE IF NOT EXISTS marca_apelido (
         id_marca INTEGER NOT NULL REFERENCES marca(id_marca),
         apelido TEXT NOT NULL,
         PRIMARY KEY (id_marca, apelido))""",
    """CREATE TABLE IF NOT EXISTS peca (
         id_peca INTEGER PRIMARY KEY,
         id_marca INTEGER NOT NULL REFERENCES marca(id_marca),
         chave TEXT NOT NULL UNIQUE,            -- 'MARCA|CODIGO', 'MARCA|EAN:789...' ou 'URL:https://...'
         codigo TEXT,                           -- texto, com zeros à esquerda; NULL quando a fonte não informa
         ean TEXT,
         desc_curta TEXT NOT NULL,
         desc_completa TEXT,
         tipo_peca TEXT,
         ncm_sugerido TEXT,
         unidade_sugerida TEXT,
         tem_foto INTEGER NOT NULL DEFAULT 0,
         qtd_fontes INTEGER NOT NULL DEFAULT 0,
         status TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa','inativa')),
         fundida_em INTEGER REFERENCES peca(id_peca),
         hash_conteudo TEXT,
         atualizado_em TEXT)""",
    """CREATE INDEX IF NOT EXISTS peca_codigo ON peca (codigo)""",
    """CREATE INDEX IF NOT EXISTS peca_codigo_sem_zero ON peca (ltrim(codigo, '0'))""",
    """CREATE INDEX IF NOT EXISTS peca_ean ON peca (ean)""",
    """CREATE INDEX IF NOT EXISTS peca_tipo ON peca (tipo_peca)""",
    """CREATE TABLE IF NOT EXISTS codigo_alternativo (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca),
         tipo TEXT NOT NULL CHECK (tipo IN ('ean','original','kit','fabricante')),
         valor TEXT NOT NULL,
         qtd_fontes INTEGER NOT NULL DEFAULT 1,
         PRIMARY KEY (id_peca, tipo, valor))""",
    """CREATE INDEX IF NOT EXISTS alt_valor ON codigo_alternativo (valor)""",
    """CREATE INDEX IF NOT EXISTS alt_valor_sem_zero ON codigo_alternativo (ltrim(valor, '0'))""",
    """CREATE TABLE IF NOT EXISTS aplicacao (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca),
         montadora TEXT, modelo TEXT NOT NULL, ano_inicio INTEGER, ano_fim INTEGER, motor TEXT,
         observacao TEXT, texto_original TEXT, modelo_reconhecido INTEGER NOT NULL DEFAULT 1,
         UNIQUE (id_peca, montadora, modelo, ano_inicio, ano_fim, motor))""",
    """CREATE TABLE IF NOT EXISTS foto (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca),
         ordem INTEGER NOT NULL,
         arquivo TEXT NOT NULL,
         largura INTEGER, altura INTEGER, bytes INTEGER, dhash INTEGER,
         origem_tipo TEXT NOT NULL CHECK (origem_tipo IN ('fabricante','loja')),
         publicavel INTEGER NOT NULL DEFAULT 1,
         motivo_nao_publicavel TEXT,
         publicada INTEGER NOT NULL DEFAULT 0,
         assinatura_visual BLOB,
         url_fonte TEXT,
         PRIMARY KEY (id_peca, arquivo))""",
    """CREATE INDEX IF NOT EXISTS foto_dhash ON foto (dhash)""",
    """CREATE TABLE IF NOT EXISTS origem (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca),
         site TEXT NOT NULL, url TEXT NOT NULL,
         nome_original TEXT, marca_original TEXT, codigo_original TEXT, ean_original TEXT, carro_original TEXT,
         coletado_em TEXT,
         PRIMARY KEY (site, url))""",
    """CREATE INDEX IF NOT EXISTS origem_peca ON origem (id_peca)""",
    """CREATE TABLE IF NOT EXISTS foto_pendente (
         id_peca INTEGER NOT NULL REFERENCES peca(id_peca),
         url TEXT NOT NULL, arquivo_local TEXT, prioridade INTEGER NOT NULL DEFAULT 5, site TEXT,
         tentativas INTEGER NOT NULL DEFAULT 0, erro TEXT,
         PRIMARY KEY (id_peca, url))""",
    """CREATE TABLE IF NOT EXISTS fonte_lida (caminho TEXT PRIMARY KEY, site TEXT, mtime REAL, anuncios INTEGER)""",
    """CREATE TABLE IF NOT EXISTS carga (
         id_carga INTEGER PRIMARY KEY AUTOINCREMENT, iniciada_em TEXT, terminada_em TEXT,
         pecas_ativas INTEGER, pecas_inativadas INTEGER, fotos_publicadas INTEGER, bytes_fotos INTEGER,
         versao_esquema INTEGER, commit_repo TEXT, ensaio INTEGER NOT NULL DEFAULT 0)""",
]


def abrir(caminho):
    db = sqlite3.connect(str(caminho))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 60000")  # outro comando do helper pode estar gravando (fotos comita a cada 200)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    for comando in DDL:
        db.execute(comando)
    db.execute("INSERT OR IGNORE INTO meta (chave, valor) VALUES ('versao_esquema', ?)", (str(VERSAO_ESQUEMA),))
    colunas = {r[1] for r in db.execute("PRAGMA table_info(foto)")}
    if "publicada" not in colunas:  # bancos criados antes da coluna
        db.execute("ALTER TABLE foto ADD COLUMN publicada INTEGER NOT NULL DEFAULT 0")
    db.commit()
    return db


def id_marca(db, nome, tipo):
    linha = db.execute("SELECT id_marca, tipo FROM marca WHERE nome = ?", (nome,)).fetchone()
    if linha:
        if tipo != "desconhecida" and tipo != linha[1]:  # o dono classificou no helper_marcas.csv
            db.execute("UPDATE marca SET tipo = ? WHERE id_marca = ?", (tipo, linha[0]))
        return linha[0]
    return db.execute("INSERT INTO marca (nome, tipo) VALUES (?, ?)", (nome, tipo)).lastrowid
