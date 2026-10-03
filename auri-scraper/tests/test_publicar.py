import os

import pytest

from helper.banco import abrir
from helper.publicar import DDL_POSTGRES, comando_rsync, diferencas, funcoes_sql, ler_env_admin, publicar


def test_ler_env_admin(tmp_path):
    arq = tmp_path / ".env_admin"
    arq.write_text("# x\nPOSTGRES_HOST=10.0.0.1\n#POSTGRES_HOST=antigo\nPOSTGRES_PORT=5432\nPOSTGRES_USER=u\nPOSTGRES_PASSWORD=p=1\n", encoding="utf-8")
    assert ler_env_admin(arq) == {"POSTGRES_HOST": "10.0.0.1", "POSTGRES_PORT": "5432", "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p=1"}


def test_diferencas():
    local = {1: ("h1", "ativa"), 2: ("h2novo", "ativa"), 3: ("h3", "ativa"), 5: ("h5", "inativa")}
    remoto = {2: ("h2", "ativa"), 3: ("h3", "ativa"), 4: ("h4", "ativa"), 5: ("h5x", "ativa")}
    assert diferencas(local, remoto) == {"novas": [1], "alteradas": [2, 5], "iguais": [3], "inativar": [4]}


def test_comando_rsync():
    cmd = comando_rsync("/x/helper_fotos", "wayap@srv", "/home/wayap/helper/store/foto_produto")
    assert cmd[0] == "rsync" and "--delete" not in cmd and "-a" in cmd and "--partial-dir=.rsync-partial" in cmd
    assert "--ignore-existing" not in cmd  # arquivo truncado de uma queda tem de ser completado na próxima rodada
    # o dono local (uid 1000) não pode ir para o servidor: lá os arquivos são do usuário que recebe (root, como na topcar)
    assert "--no-owner" in cmd and "--no-group" in cmd and "--chmod=D755,F644" in cmd
    assert cmd[-2:] == ["/x/helper_fotos/", "wayap@srv:/home/wayap/helper/store/foto_produto/"]


def test_ddl_tem_tabelas_funcoes_e_nao_expoe_origem_nas_funcoes():
    ddl = "\n".join(DDL_POSTGRES)
    for t in ("peca", "codigo_alternativo", "aplicacao", "foto", "origem", "marca", "carga"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in ddl
    fs = "\n".join(funcoes_sql(True))
    for f in ("busca_codigo", "busca_ean", "busca_texto", "busca_tipo"):
        assert f"FUNCTION {f}" in fs
    assert "FROM origem" not in fs and "CREATE OR REPLACE VIEW v_peca" in ddl
    assert "similarity" in fs and "similarity" not in "\n".join(funcoes_sql(False))
    # I5 da revisão: o predicado trigram tem de ser sobre desc_curta pura (coluna indexada), não sobre concatenação com unaccent
    bt = next(f for f in funcoes_sql(True) if "FUNCTION busca_texto" in f)
    assert "v.desc_curta %" in bt and "|| ' ' ||" not in bt.split("WHERE", 1)[1].split("ORDER BY")[0]


class ConFalsa:
    """Registra SQL executado; serve para garantir ordem (rsync antes do banco) e ensaio."""
    def __init__(self, remoto):
        self.remoto, self.sql, self.commits, self.eventos = remoto, [], 0, []
    def cursor(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def execute(self, sql, params=None):
        sql = sql.decode() if isinstance(sql, bytes) else sql
        self.sql.append(sql.split()[0].upper() + " " + " ".join(sql.split()[1:3]))
        self._ultimo = sql
    def mogrify(self, sql, params=None):  # psycopg2.extras.execute_batch chama mogrify e depois execute(bytes)
        return sql.encode()
    def executemany(self, sql, seq):
        for _ in seq:
            self.execute(sql)
    def fetchall(self):
        if "hash_conteudo" in self._ultimo:
            return [(i, h, s) for i, (h, s) in self.remoto.items()]
        return []
    def fetchone(self):
        return (1,)
    def commit(self):
        self.commits += 1
        self.eventos.append("commit")
    def rollback(self):
        self.eventos.append("rollback")


def _db_local(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'ARTEB', 'reposicao')")
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status, hash_conteudo) VALUES (1, 1, 'ARTEB|1', '1', 'FAROL', 'ativa', 'h1')")
    db.execute("INSERT INTO foto (id_peca, ordem, arquivo, origem_tipo) VALUES (1, 1, 'a.jpg', 'loja')")
    db.commit()
    (tmp_path / "helper_fotos/1").mkdir(parents=True)
    (tmp_path / "helper_fotos/1/a.jpg").write_bytes(b"x")
    return db


def test_rsync_falhando_nao_grava_no_banco(tmp_path):
    db = _db_local(tmp_path)
    con = ConFalsa(remoto={})
    def rsync_quebrado(cmd):
        raise RuntimeError("rsync: connection refused")
    with pytest.raises(RuntimeError):
        publicar(db, con, ensaio=False, executar_rsync=rsync_quebrado, pasta_fotos=tmp_path / "helper_fotos",
                 destino_ssh="wayap@srv", pasta_remota="/home/wayap/helper/store/foto_produto", commit_repo="abc")
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in con.sql) and con.commits == 0


def test_ensaio_nao_roda_rsync_nem_grava(tmp_path):
    db = _db_local(tmp_path)
    con = ConFalsa(remoto={})
    chamadas = []
    r = publicar(db, con, ensaio=True, executar_rsync=lambda cmd: chamadas.append(cmd), pasta_fotos=tmp_path / "helper_fotos",
                 destino_ssh="wayap@srv", pasta_remota="/x", commit_repo="abc")
    assert r["novas"] == 1 and r["fotos_a_publicar"] == 1 and chamadas == []
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s in con.sql)


def test_publicacao_grava_na_ordem_e_marca_fotos(tmp_path):
    db = _db_local(tmp_path)
    con = ConFalsa(remoto={})
    ordem = []
    r = publicar(db, con, ensaio=False, executar_rsync=lambda cmd: ordem.append("rsync"), pasta_fotos=tmp_path / "helper_fotos",
                 destino_ssh="wayap@srv", pasta_remota="/x", commit_repo="abc")
    assert ordem == ["rsync"] and r["novas"] == 1 and r["fotos_publicadas"] == 1 and con.commits >= 1
    assert any(s.startswith("INSERT INTO peca") for s in con.sql) and any(s.startswith("INSERT INTO carga") for s in con.sql)
    assert db.execute("SELECT publicada FROM foto").fetchone()[0] == 1
    # segunda vez: nada muda
    con2 = ConFalsa(remoto={1: ("h1", "ativa")})
    r2 = publicar(db, con2, ensaio=False, executar_rsync=lambda cmd: ordem.append("rsync2"), pasta_fotos=tmp_path / "helper_fotos",
                  destino_ssh="wayap@srv", pasta_remota="/x", commit_repo="abc")
    assert r2["novas"] == 0 and r2["alteradas"] == 0 and r2["fotos_publicadas"] == 0 and "rsync2" not in ordem
    assert not any(s.startswith("INSERT INTO peca") for s in con2.sql)


@pytest.mark.skipif(not os.environ.get("HELPER_TESTE_PG"), reason="defina HELPER_TESTE_PG=1 com um Postgres de teste em .env_admin")
def test_integracao_postgres(tmp_path):
    from helper.publicar import conectar, criar_banco, instalar_esquema, ler_env_admin
    from wayap_fotos import ENV_ADMIN
    env = ler_env_admin(ENV_ADMIN)
    criar_banco(env, "helper_teste")
    con = conectar(env, "helper_teste")
    instalar_esquema(con)
    db = _db_local(tmp_path)
    r = publicar(db, con, ensaio=False, executar_rsync=lambda cmd: None, pasta_fotos=tmp_path / "helper_fotos",
                 destino_ssh=None, pasta_remota=None, commit_repo="teste")
    assert r["novas"] == 1
    with con.cursor() as cur:
        cur.execute("SELECT id_peca FROM busca_codigo('1')")
        assert cur.fetchall() == [(1,)]


def test_transacao_fechada_antes_do_rsync_e_lista_de_fotos_congelada(tmp_path):
    """I4 da revisão: (b) rollback antes do rsync, para não ficar 'idle in transaction' por horas;
    (c) foto que entra durante o rsync não é marcada como publicada."""
    db = _db_local(tmp_path)
    con = ConFalsa(remoto={})
    def rsync(cmd):
        con.eventos.append("rsync")
        db.execute("INSERT INTO foto (id_peca, ordem, arquivo, origem_tipo) VALUES (1, 2, 'nova.jpg', 'loja')")
        db.commit()
    r = publicar(db, con, ensaio=False, executar_rsync=rsync, pasta_fotos=tmp_path / "helper_fotos",
                 destino_ssh="wayap@srv", pasta_remota="/x", commit_repo="abc")
    assert con.eventos.index("rollback") < con.eventos.index("rsync") < con.eventos.index("commit")
    assert r["fotos_publicadas"] == 1
    assert dict(db.execute("SELECT arquivo, publicada FROM foto")) == {"a.jpg": 1, "nova.jpg": 0}
