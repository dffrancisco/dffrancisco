"""Banco local de preparação do helper (SQLite). Mesmo modelo da spec, seção 4."""
import sqlite3
from datetime import datetime

VERSAO_ESQUEMA = 3

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
    # ---- veículos (spec de veículos, seção 6); prefixo vei_ porque o banco helper do Postgres é dividido com o Wayap
    """CREATE TABLE IF NOT EXISTS vei_montadora (
         id_veiculo_montadora INTEGER PRIMARY KEY AUTOINCREMENT,
         nome TEXT NOT NULL UNIQUE, nome_exibicao TEXT NOT NULL,
         logo TEXT, logo_fonte TEXT, id_montadora INTEGER,
         qtd_pecas INTEGER NOT NULL DEFAULT 0, ativo INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS vei_modelo (
         id_modelo INTEGER PRIMARY KEY AUTOINCREMENT,
         id_veiculo_montadora INTEGER NOT NULL REFERENCES vei_montadora(id_veiculo_montadora),
         nome TEXT NOT NULL, nome_exibicao TEXT NOT NULL,
         tipo TEXT NOT NULL DEFAULT 'carro' CHECK (tipo IN ('carro','moto','pesado')),
         foto TEXT, foto_herdada INTEGER NOT NULL DEFAULT 0, foto_fonte TEXT,
         ano_inicio INTEGER, ano_fim INTEGER, qtd_pecas INTEGER NOT NULL DEFAULT 0,
         ativo INTEGER NOT NULL DEFAULT 1, hash_conteudo TEXT, atualizado_em TEXT,
         UNIQUE (id_veiculo_montadora, nome))""",
    """CREATE TABLE IF NOT EXISTS vei_versao (
         id_versao INTEGER PRIMARY KEY AUTOINCREMENT,
         id_modelo INTEGER NOT NULL REFERENCES vei_modelo(id_modelo),
         nome TEXT NOT NULL, nome_exibicao TEXT NOT NULL, motor TEXT, ativo INTEGER NOT NULL DEFAULT 1,
         UNIQUE (id_modelo, nome))""",
    """CREATE TABLE IF NOT EXISTS vei_versao_ano (
         id_versao INTEGER NOT NULL REFERENCES vei_versao(id_versao), ano INTEGER NOT NULL,
         PRIMARY KEY (id_versao, ano))""",
    """CREATE TABLE IF NOT EXISTS vei_fonte (
         site TEXT NOT NULL, id_fonte TEXT NOT NULL, id_versao INTEGER NOT NULL, ano INTEGER NOT NULL,
         PRIMARY KEY (site, id_fonte))""",
    """CREATE TABLE IF NOT EXISTS vei_peca (
         id_peca INTEGER NOT NULL, id_modelo INTEGER NOT NULL, id_versao INTEGER,
         ano_inicio INTEGER, ano_fim INTEGER, nivel TEXT NOT NULL CHECK (nivel IN ('versao','modelo')))""",
    """CREATE TABLE IF NOT EXISTS vei_peca_estado (id_peca INTEGER PRIMARY KEY, hash TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS vei_arquivo (caminho TEXT PRIMARY KEY, publicado INTEGER NOT NULL DEFAULT 0)""",
]

# a carga de vei_peca (milhões de linhas) apaga os índices e recria no fim: veiculos_ligar.py usa esta lista
INDICES_PECA_VEICULO = [
    "CREATE INDEX IF NOT EXISTS vei_peca_id_peca ON vei_peca (id_peca)",
    "CREATE INDEX IF NOT EXISTS vei_peca_modelo ON vei_peca (id_modelo, ano_inicio, ano_fim)",
]


def abrir(caminho):
    db = sqlite3.connect(str(caminho))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 60000")  # outro comando do helper pode estar gravando (fotos comita a cada 200)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    for comando in DDL + INDICES_PECA_VEICULO:
        db.execute(comando)
    db.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES ('versao_esquema', ?)", (str(VERSAO_ESQUEMA),))
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


def gravar_meta(db, chave, valor):
    db.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES (?, ?)", (chave, valor))


def ler_meta(db, chave):
    linha = db.execute("SELECT valor FROM meta WHERE chave = ?", (chave,)).fetchone()
    return linha[0] if linha else None


def agora():
    return datetime.now().isoformat(timespec="seconds")
