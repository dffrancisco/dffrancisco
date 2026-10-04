import os

import pytest

from helper.banco import abrir, gravar_meta
from helper.publicar import (DDL_POSTGRES, comando_rsync, ddl_veiculos, diferencas, funcoes_sql, funcoes_veiculos, ler_env_admin,
                             publicar, publicar_veiculos, veiculos_preparados)


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


def test_ddl_de_veiculos_e_funcoes_do_contrato():
    ddl = "\n".join(ddl_veiculos(tem_montadoras=True))
    for t in ("vei_montadora", "vei_modelo", "vei_versao", "vei_versao_ano", "vei_peca", "vei_peca_estado"):
        assert f"CREATE TABLE IF NOT EXISTS {t} (" in ddl
    assert "coalesce(w.logo, vm.logo)" in ddl and "LEFT JOIN montadoras w" in ddl
    modelo = next(c for c in ddl_veiculos(True) if "TABLE IF NOT EXISTS vei_modelo" in c)
    assert "tipo TEXT NOT NULL" in modelo
    v_modelo = next(c for c in ddl_veiculos(True) if "VIEW vei_v_modelo" in c)
    v_montadora = next(c for c in ddl_veiculos(True) if "VIEW vei_v_montadora" in c)
    assert "tipo" in v_modelo.split("FROM")[0] and "AS tipos" in v_montadora  # o Wayap filtra carro, moto ou pesado
    assert "montadoras w" not in "\n".join(ddl_veiculos(tem_montadoras=False))
    fs = "\n".join(funcoes_veiculos(True))
    tudo = ddl + fs
    for comando in ("INSERT INTO montadoras", "UPDATE montadoras", "DELETE FROM montadoras", "ALTER TABLE montadoras",
                    "CREATE TABLE IF NOT EXISTS montadoras"):
        assert comando not in tudo  # o helper nunca escreve na tabela do Wayap
    for f in ("vei_anos_do_modelo", "vei_versoes_do_ano", "vei_ids_por_veiculo", "vei_pecas_por_veiculo"):
        assert f"FUNCTION {f}" in fs
    assert "vei_fonte" not in tudo and "origem" not in fs
    assert "similarity" in fs and "similarity" not in "\n".join(funcoes_veiculos(False))


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


class ConVeiculos(ConFalsa):
    """Responde às leituras da publicação de veículos com o estado 'remoto' dado e guarda o que vai por COPY."""
    def __init__(self, montadoras_wayap=(), remoto_montadoras=(), remoto_modelos=(), remoto_estado=(), sem_tabelas_veiculo=False):
        super().__init__(remoto={})
        self.respostas = {"FROM montadoras": list(montadoras_wayap), "FROM vei_montadora": list(remoto_montadoras),
                          "FROM vei_modelo": list(remoto_modelos), "FROM vei_peca_estado": list(remoto_estado)}
        self.copias, self.sem_tabelas_veiculo, self.completo = [], sem_tabelas_veiculo, []

    def execute(self, sql, params=None):
        super().execute(sql, params)
        self.completo.append(self._ultimo)  # self.sql guarda só as 3 primeiras palavras

    def fetchall(self):
        for trecho, linhas in self.respostas.items():
            if trecho in self._ultimo:
                return linhas
        return super().fetchall()

    def fetchone(self):
        # to_regclass: a montadoras do Wayap existe; as tabelas veiculo_* só não existem antes da primeira publicação
        return (not (self.sem_tabelas_veiculo and "vei_montadora" in self._ultimo),)

    def copy_expert(self, sql, arquivo):
        self.sql.append("COPY " + sql.split()[1])
        self.copias.append(arquivo.getvalue())


def _db_veiculos(tmp_path):
    from helper.montadoras import Montadoras
    from helper.veiculos import carregar_arvore
    from helper.veiculos_ligar import fechar
    from tests.test_veiculos import _linha
    db = _db_local(tmp_path)  # peça 1
    carregar_arvore(db, [_linha()], Montadoras({}))
    id_modelo = db.execute("SELECT id_modelo FROM vei_modelo").fetchone()[0]
    db.execute("INSERT INTO vei_peca VALUES (1, ?, NULL, 2020, 2021, 'versao')", (id_modelo,))
    db.execute("UPDATE vei_modelo SET foto = 'veiculos/modelos/1_abc.webp'")
    db.execute("INSERT INTO vei_arquivo (caminho) VALUES ('veiculos/modelos/1_abc.webp')")
    (tmp_path / "helper_fotos_veiculos/modelos").mkdir(parents=True)
    (tmp_path / "helper_fotos_veiculos/modelos/1_abc.webp").write_bytes(b"x")
    fechar(db)
    return db


def _pub_v(db, con, tmp_path, ensaio=False, rsync=None, destino="wayap@srv"):
    return publicar_veiculos(db, con, ensaio=ensaio, executar_rsync=rsync or (lambda cmd: None),
                             pasta_fotos=tmp_path / "helper_fotos_veiculos", destino_ssh=destino, pasta_remota="/home/wayap/helper/veiculos")


def test_comando_rsync_com_exclusoes():
    cmd = comando_rsync("/x/helper_fotos_veiculos", "wayap@srv", "/home/wayap/helper/veiculos", excluir=("proprias/", ".gitignore"))
    assert "--exclude=proprias/" in cmd and "--exclude=.gitignore" in cmd
    assert cmd[-2:] == ["/x/helper_fotos_veiculos/", "wayap@srv:/home/wayap/helper/veiculos/"]


def test_publicar_veiculos_arquivos_antes_copy_e_sem_escrever_na_montadoras(tmp_path):
    db = _db_veiculos(tmp_path)
    con = ConVeiculos(montadoras_wayap=[(11, "CHEVROLET")])
    comandos = []

    def rsync(cmd):
        comandos.append(cmd)
        con.sql.append("RSYNC")
    r = _pub_v(db, con, tmp_path, rsync=rsync)
    assert "--exclude=proprias/" in comandos[0] and comandos[0][-1] == "wayap@srv:/home/wayap/helper/veiculos/"
    escritas = [i for i, s in enumerate(con.sql) if s.startswith(("INSERT", "UPDATE", "DELETE", "COPY"))]
    assert con.sql.index("RSYNC") < escritas[0]
    assert db.execute("SELECT id_montadora FROM vei_montadora").fetchone()[0] == 11
    assert any(s.startswith("INSERT INTO vei_modelo") for s in con.sql) and any(s.startswith("COPY vei_peca") for s in con.sql)
    assert any("INSERT INTO vei_modelo" in s and "%(tipo)s" in s for s in con.completo)
    assert con.copias[0].startswith("1\t") and "\\N" in con.copias[0]
    assert not any(s.startswith(("INSERT INTO montadoras", "UPDATE montadoras", "DELETE FROM montadoras")) for s in con.sql)
    assert (r["modelos"], r["pecas_veiculo"], r["arquivos_veiculo"], r["ligacoes_gravadas"]) == (1, 1, 1, 1)
    assert db.execute("SELECT publicado FROM vei_arquivo").fetchone()[0] == 1


def test_segunda_publicacao_de_veiculos_nao_grava_nada(tmp_path):
    db = _db_veiculos(tmp_path)
    _pub_v(db, ConVeiculos(montadoras_wayap=[(11, "CHEVROLET")]), tmp_path)
    m = db.execute("SELECT id_veiculo_montadora, nome, nome_exibicao, logo, id_montadora, qtd_pecas, ativo FROM vei_montadora").fetchone()
    con2 = ConVeiculos(montadoras_wayap=[(11, "CHEVROLET")], remoto_montadoras=[(m[0], m[1], m[2], m[3], m[4], m[5], bool(m[6]))],
                       remoto_modelos=[tuple(l) for l in db.execute("SELECT id_modelo, hash_conteudo FROM vei_modelo")],
                       remoto_estado=[tuple(l) for l in db.execute("SELECT id_peca, hash FROM vei_peca_estado")])
    rsyncs = []
    r = _pub_v(db, con2, tmp_path, rsync=rsyncs.append)
    assert rsyncs == [] and (r["montadoras"], r["modelos"], r["pecas_veiculo"], r["pecas_veiculo_apagar"], r["arquivos_veiculo"]) == (0, 0, 0, 0, 0)
    assert not any(s.startswith(("INSERT", "DELETE", "COPY")) for s in con2.sql)


def test_ensaio_de_veiculos_nao_grava(tmp_path):
    db = _db_veiculos(tmp_path)
    con = ConVeiculos()
    r = _pub_v(db, con, tmp_path, ensaio=True, rsync=lambda cmd: pytest.fail("rsync no ensaio"))
    assert r["modelos"] == 1 and r["arquivos_veiculo"] == 1 and "ligacoes_gravadas" not in r
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE", "COPY")) for s in con.sql)
    assert db.execute("SELECT publicado FROM vei_arquivo").fetchone()[0] == 0


def test_ensaio_antes_da_primeira_publicacao_nao_precisa_das_tabelas_no_destino(tmp_path):
    db = _db_veiculos(tmp_path)
    con = ConVeiculos(sem_tabelas_veiculo=True)
    r = _pub_v(db, con, tmp_path, ensaio=True)
    assert (r["montadoras"], r["modelos"], r["pecas_veiculo"]) == (1, 1, 1)
    assert any("FROM montadoras" in s for s in con.completo)  # a do Wayap continua sendo lida
    assert not any("FROM veiculo_" in s or "FROM vei_peca" in s for s in con.completo)


def test_peca_que_saiu_perde_as_linhas_no_destino(tmp_path):
    db = _db_veiculos(tmp_path)
    con = ConVeiculos(remoto_estado=[(99, "h")])
    r = _pub_v(db, con, tmp_path)
    assert r["pecas_veiculo_apagar"] == 1
    assert any(s.startswith("DELETE FROM vei_peca") for s in con.sql) and any(s.startswith("DELETE FROM vei_peca_estado") for s in con.sql)


def test_queda_no_meio_da_peca_veiculo_mantem_lotes_ja_gravados(tmp_path):
    from helper.veiculos_ligar import fechar
    db = _db_veiculos(tmp_path)
    id_modelo = db.execute("SELECT id_modelo FROM vei_modelo").fetchone()[0]
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (2, 1, 'ARTEB|2', '2', 'X', 'ativa')")
    db.execute("INSERT INTO vei_peca VALUES (2, ?, NULL, 2020, 2020, 'versao')", (id_modelo,))
    fechar(db)

    class Quebra(ConVeiculos):
        def copy_expert(self, sql, arquivo):
            if self.copias:
                raise RuntimeError("conexão caiu")
            super().copy_expert(sql, arquivo)
    con = Quebra()
    with pytest.raises(RuntimeError):
        publicar_veiculos(db, con, ensaio=False, executar_rsync=lambda c: None, pasta_fotos=tmp_path / "helper_fotos_veiculos",
                          destino_ssh=None, pasta_remota="/x", lote_pecas=1)
    assert len(con.copias) == 1 and con.eventos[-1] == "rollback"
    assert con.eventos.count("commit") >= 2  # árvore + primeiro lote de vei_peca ficaram


def test_veiculos_preparados(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    assert veiculos_preparados(db) is False
    gravar_meta(db, "preparado_em", "2026-10-03T10:00:00")
    gravar_meta(db, "veiculos_em", "2026-10-03T11:00:00")
    assert veiculos_preparados(db) is True
    gravar_meta(db, "preparado_em", "2026-10-03T12:00:00")
    with pytest.raises(RuntimeError, match="helper.py veiculos"):
        veiculos_preparados(db)


@pytest.mark.skipif(not os.environ.get("HELPER_TESTE_PG"), reason="defina HELPER_TESTE_PG=1 com um Postgres de teste em .env_admin")
def test_integracao_postgres_veiculos(tmp_path):
    from helper.publicar import conectar, criar_banco, instalar_esquema
    from wayap_fotos import ENV_ADMIN
    env = ler_env_admin(ENV_ADMIN)
    criar_banco(env, "helper_teste")
    con = conectar(env, "helper_teste")
    instalar_esquema(con)
    db = _db_veiculos(tmp_path)
    publicar(db, con, ensaio=False, executar_rsync=lambda cmd: None, pasta_fotos=tmp_path / "helper_fotos",
             destino_ssh=None, pasta_remota=None, commit_repo="teste")
    publicar_veiculos(db, con, ensaio=False, executar_rsync=lambda cmd: None, pasta_fotos=tmp_path / "helper_fotos_veiculos",
                      destino_ssh=None, pasta_remota=None)
    id_modelo = db.execute("SELECT id_modelo FROM vei_modelo").fetchone()[0]
    with con.cursor() as cur:
        cur.execute("SELECT ano FROM vei_anos_do_modelo(%s)", (id_modelo,))
        assert [a for (a,) in cur.fetchall()] == [2021, 2020]
        cur.execute("SELECT id_peca, confianca FROM vei_ids_por_veiculo(%s, 2021)", (id_modelo,))
        assert cur.fetchall() == [(1, "todas_versoes")]
        cur.execute("SELECT id_peca, confianca FROM vei_pecas_por_veiculo(%s, 2021, NULL, 'farol')", (id_modelo,))
        assert cur.fetchall() == [(1, "todas_versoes")]
        cur.execute("SELECT foto_url, tipo FROM vei_v_modelo WHERE id_modelo = %s", (id_modelo,))
        assert cur.fetchone() == ("/files/aGVscGVy/veiculos/modelos/1_abc.webp", "carro")
        cur.execute("SELECT tipos FROM vei_v_montadora")
        assert cur.fetchall() == [(["carro"],)]


@pytest.mark.skipif(not os.environ.get("HELPER_TESTE_PG"), reason="defina HELPER_TESTE_PG=1 com um Postgres de teste em .env_admin")
def test_integracao_postgres_versao_fora_do_ano(tmp_path):
    """Linha de versão vale só nos anos em que a versão existe: o 4x2 do Tracker só existe em 2021."""
    from helper.publicar import conectar, criar_banco, instalar_esquema
    from helper.veiculos_ligar import fechar
    from wayap_fotos import ENV_ADMIN
    env = ler_env_admin(ENV_ADMIN)
    criar_banco(env, "helper_teste_lacuna")
    con = conectar(env, "helper_teste_lacuna")
    instalar_esquema(con)
    db = _db_veiculos(tmp_path)
    id_modelo = db.execute("SELECT id_modelo FROM vei_modelo").fetchone()[0]
    v4x2 = db.execute("SELECT id_versao FROM vei_versao WHERE nome LIKE '4X2%'").fetchone()[0]
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (2, 1, 'ARTEB|2', '2', 'TAMBOR', 'ativa')")
    db.execute("INSERT INTO vei_peca VALUES (2, ?, ?, 2020, 2021, 'versao')", (id_modelo, v4x2))
    fechar(db)
    publicar(db, con, ensaio=False, executar_rsync=lambda cmd: None, pasta_fotos=tmp_path / "helper_fotos",
             destino_ssh=None, pasta_remota=None, commit_repo="teste")
    publicar_veiculos(db, con, ensaio=False, executar_rsync=lambda cmd: None, pasta_fotos=tmp_path / "helper_fotos_veiculos",
                      destino_ssh=None, pasta_remota=None)
    with con.cursor() as cur:
        cur.execute("SELECT id_peca, confianca FROM vei_ids_por_veiculo(%s, 2020) ORDER BY 1", (id_modelo,))
        assert cur.fetchall() == [(1, "todas_versoes")]  # a peça 2 não serve em 2020: o 4x2 não existe nesse ano
        cur.execute("SELECT id_peca, confianca FROM vei_ids_por_veiculo(%s, 2021) ORDER BY 1", (id_modelo,))
        assert cur.fetchall() == [(1, "todas_versoes"), (2, "algumas_versoes")]
