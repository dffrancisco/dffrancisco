# Painel: veículos do helper na aba Cadastrar — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A aba "Cadastrar dos sites" do `painel_wayap.py` ganha a busca por veículo (montadora → modelo → ano →
versão, como na KarHub) e os veículos compatíveis da peça (lista e árvore) lidos do `helper.sqlite`, de onde saem os
carros de venda e o complemento do produto.

**Architecture:** Um módulo novo, `painel_veiculos.py`, lê o `helper.sqlite` só para leitura e concentra as regras
(listas do seletor, anúncios que servem num veículo, linhas/lista/árvore/veredito de uma peça). O `painel_wayap.py`
ganha rotas finas, a busca do catálogo aceita o filtro de veículo (tabela temporária cruzada por `site, url`) e o
HTML/JS da aba ganha o quadro de veículo e o bloco de veículos compatíveis. Item sem peça no helper continua como hoje.

**Tech Stack:** Python 3, Flask 3.1, SQLite 3.45 (FTS5, JSON1), pytest, JS e CSS puros dentro de `painel_wayap.py`.

**Spec:** `docs/superpowers/specs/2026-10-06-painel-veiculos-design.md`

## Global Constraints

- O painel nunca grava no `helper.sqlite`: conexão `file:...helper.sqlite?mode=ro` (URI), `timeout=5`.
- Sem veículo escolhido, a busca é exatamente a de hoje; `/api/catalogo/cadastrar` não muda.
- Lista e complemento do produto com nomes canônicos em maiúsculas: `CHEVROLET ONIX 2013-2019 LT 1.4 8V FLEX`.
- Selos da busca: `versao` → "Serve nesta versão", `todas_versoes` → "Serve em todas as versões",
  `algumas_versoes` → "Serve em algumas versões", `modelo_ano` → "Confira a versão".
- Selos da lista: "todas as versões" e "confira a versão".
- Vereditos do "Seu veículo": "Serve", "Serve em algumas versões: escolha a versão", "Confira a versão",
  "Não serve nesta versão", "Não consta para este veículo".
- Erros das rotas: helper ausente → 404 `{"erro": "Base de veículos não encontrada"}`; helper travado → 503
  `{"erro": "Base de veículos ocupada, tente de novo"}`.
- Aviso de modelos sem carro com fonte `base`: "Alguns modelos da base não existem no cadastro de carros: escolha o
  carro ou desmarque."
- Tipos de veículo: todos (carro, moto, pesado), misturados; selinho com o tipo quando não é carro.
- Imagens servidas só de `helper_fotos_veiculos/montadoras/` e `helper_fotos_veiculos/modelos/`.
- Testes: `cd /mnt/nvme/PROJETOS/dffrancisco/auri-scraper && .venv/bin/python -m pytest -q`. A raiz do git é
  `/mnt/nvme/PROJETOS/dffrancisco`; os caminhos deste plano são relativos a `auri-scraper/`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Estilo da casa: nomes e comentários em português, docstrings curtas, linhas até ~120 colunas.

## Review Focus

- Caminho de imagem com `..` (`/veiculos/img/modelos/../../segredo.txt`) → 404, nunca um arquivo fora de
  `helper_fotos_veiculos/`. Teste na Tarefa 4.
- Veículo popular com dezenas de milhares de peças (Gol, Onix) → a busca por veículo responde e pagina. Teste com
  60 mil anúncios na Tarefa 4.
- Linha de texto de aplicação com faixa aberta ("Uno a partir de 2010") ou sem ano → texto `FIAT UNO 2010-` /
  `CHEVROLET CELTA` e árvore só com os anos que o modelo tem. Testes na Tarefa 5.
- Base travada ou sumindo no meio (outro `helper.py` gravando) → busca por veículo 503 e formulário cai para o site,
  nunca 500. Testes nas Tarefas 4 e 6.
- Veículo guardado no navegador que não existe mais na base → quadro limpo, sem erro. Conferência manual na Tarefa 7.

---

### Task 1: Merge do `helper-veiculos` na `main`

**Files:**
- Modify (conflito): `helper/cli.py`
- Modify (local, ignorado pelo git): `veiculos/coleta_completa.sh`

**Interfaces:**
- Produces: na `main`, `helper/consulta.py` com `ORDEM_CONFIANCA` e `ids_por_veiculo(db, id_modelo, ano, id_versao=None)
  -> dict[int, str]`; `helper/banco.py` com `abrir(caminho)` criando as tabelas `vei_*`; comandos `helper.py veiculos`
  e `helper.py pecas-do-veiculo`.

- [ ] **Step 1: Conferir que a árvore está limpa e fazer o merge**

```bash
cd /mnt/nvme/PROJETOS/dffrancisco
git status --short          # esperado: nada
git checkout main
git merge --no-ff helper-veiculos -m "Merge do helper-veiculos na main: veículos no helper"
```
Esperado: `CONFLITO (conteúdo): conflito de mesclagem em auri-scraper/helper/cli.py` (e só ele).

- [ ] **Step 2: Resolver os dois trechos de `auri-scraper/helper/cli.py` ficando com os dois lados**

Primeiro trecho (imports) vira:

```python
from helper import (banco, consulta, fontes, fusao, lista, relatorio, topcar, veiculos, veiculos_fotos, veiculos_ligar,
                    veiculos_relatorio)
```

Segundo trecho (subcomandos, antes de `sp = sub.add_parser("publicar")`) vira os dois blocos em sequência:

```python
    sp = sub.add_parser("lista", help="casa a planilha de peças de um cliente com o helper")
    _args_comuns(sp)
    sp.add_argument("planilha", type=Path)
    sp.add_argument("--nome", default=None, help="pasta em helper_listas/ (padrão: nome do arquivo)")
    sp.set_defaults(fn=cmd_lista)
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
```

Também troque a docstring da primeira linha por:

```python
"""CLI do helper. Uso: python helper.py {preparar|fotos|relatorio|cobertura|lista|veiculos|pecas-do-veiculo|publicar} [opções]."""
```

Confira que não sobrou marcador: `grep -n "^<<<<<<<\|^=======\|^>>>>>>>" auri-scraper/helper/cli.py` → nada.

- [ ] **Step 3: Rodar todos os testes**

Run: `cd /mnt/nvme/PROJETOS/dffrancisco/auri-scraper && .venv/bin/python -m pytest -q`
Expected: todos passam (os do helper, dos catálogos novos da `main` e os de veículos do branch).

- [ ] **Step 4: Concluir o merge**

```bash
cd /mnt/nvme/PROJETOS/dffrancisco
git add auri-scraper/helper/cli.py
git commit --no-edit
```

- [ ] **Step 5: Apontar o script de coleta para a `main` (arquivo local, ignorado pelo git)**

Em `auri-scraper/veiculos/coleta_completa.sh`, troque a linha `COLETOR=...` por:

```bash
COLETOR=/mnt/nvme/PROJETOS/dffrancisco/auri-scraper/catalogo_karhub_veiculos.py
```

Confira: `ls /mnt/nvme/PROJETOS/dffrancisco/auri-scraper/catalogo_karhub_veiculos.py` existe. O worktree
`.worktrees/helper-veiculos` fica onde está; apagar é decisão do dono.

---

### Task 2: Reprocessar os veículos com a coleta completa

**Files:** nenhum versionado (grava `helper.sqlite`, `helper_fotos_veiculos/` e `helper_relatorios/`).

**Interfaces:**
- Produces: `helper.sqlite` com ~3.498 modelos ativos (carro, moto, pesado) e linhas `vei_peca` de nível `versao`.

- [ ] **Step 1: Conferir que ninguém está gravando no helper**

Run: `pgrep -af "helper.py" || echo livre`
Expected: `livre`. Se houver processo, esperar terminar (um escritor por vez no `helper.sqlite`).

- [ ] **Step 2: Rodar o `veiculos` como serviço do usuário (não morre com o terminal)**

```bash
cd /mnt/nvme/PROJETOS/dffrancisco/auri-scraper
systemd-run --user --unit=helper-veiculos --collect --working-directory="$PWD" \
  bash -c '.venv/bin/python helper.py veiculos > helper_relatorios/veiculos-rodada.log 2>&1'
systemctl --user status helper-veiculos --no-pager
```
Acompanhe com `tail -f helper_relatorios/veiculos-rodada.log` até aparecer `relatório em ...`.

- [ ] **Step 3: Conferir os números**

```bash
.venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("file:helper.sqlite?mode=ro", uri=True)
print("modelos ativos por tipo:", c.execute("SELECT tipo, count(*) FROM vei_modelo WHERE ativo = 1 GROUP BY tipo").fetchall())
print("ligações:", c.execute("SELECT nivel, count(*), count(DISTINCT id_peca) FROM vei_peca GROUP BY nivel").fetchall())
print("modelos com foto:", c.execute("SELECT count(*) FROM vei_modelo WHERE ativo = 1 AND foto IS NOT NULL").fetchone()[0])
EOF
.venv/bin/python helper.py pecas-do-veiculo CHEVROLET TRACKER 2021 --versao "4x2 Aut. 1.2 12v L3 Turbo" --texto PASTILHA --limite 10
```
Expected: soma dos tipos perto de 3.498; uma linha `('versao', ...)` com dezenas de milhares de peças; a consulta do
Tracker lista pastilhas com confiança `versao` ou `todas_versoes`. Anote os números para o relatório final. Se a
ligação `versao` vier zerada, PARE e investigue (o `karhub_compat.jsonl` não foi lido).

---

### Task 3: `painel_veiculos.py` — conexão com o helper e listas do seletor

Trabalho das Tarefas 3 a 9 num branch: `cd /mnt/nvme/PROJETOS/dffrancisco && git checkout -b painel-veiculos`.

**Files:**
- Create: `painel_veiculos.py`
- Test: `tests/test_painel_veiculos.py`

**Interfaces:**
- Consumes: `helper.consulta.ORDEM_CONFIANCA`, `helper.consulta.ids_por_veiculo`, `helper.banco.abrir` (testes).
- Produces:
  - `HELPER_DB: Path`, `FOTOS_VEICULOS: Path`, `PASTAS_IMAGEM = ("montadoras", "modelos")`
  - `class Indisponivel(Exception)`, `class Ocupado(Exception)`
  - `helper(caminho=None)` — context manager que entrega `sqlite3.Connection` (row_factory `sqlite3.Row`)
  - `url_imagem(caminho: str | None) -> str | None`
  - `montadoras(db) -> list[{"id", "nome", "logo_url", "qtd_pecas"}]`
  - `modelos(db, id_montadora) -> list[{"id", "nome", "tipo", "foto_url", "ano_inicio", "ano_fim"}]`
  - `anos(db, id_modelo) -> list[int]` (decrescente)
  - `versoes(db, id_modelo, ano) -> list[{"id", "nome"}]`
  - `veiculo_escolhido(db, id_modelo, ano, id_versao=None) -> {"modelo": str, "texto": str} | None`
  - teste: `_helper(tmp_path) -> Path` (banco pequeno usado por todas as tarefas seguintes)

- [ ] **Step 1: Escrever o banco de teste e os testes que falham**

Crie `tests/test_painel_veiculos.py`:

```python
import sqlite3

import pytest

import painel_veiculos
from helper.banco import abrir


def _helper(tmp_path):
    """helper.sqlite pequeno: Chevrolet (Onix com foto e versões, Celta), Fiat (Uno), Honda (Biz, moto) e Gurgel (só
    modelo inativo). Peça 1: todas as versões do Onix 2013-2016, só a LT em 2017-2019 e texto 'Uno a partir de 2010';
    peça 2: texto 'Celta' sem ano; peça 3 inativa; peça 4 sem veículos."""
    caminho = tmp_path / "helper.sqlite"
    db = abrir(caminho)
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'FREMAX', 'reposicao')")
    for id_peca, desc, status in [(1, "PASTILHA FREIO", "ativa"), (2, "TAMBOR FREIO", "ativa"),
                                  (3, "PASTILHA VELHA", "inativa"), (4, "DISCO FREIO", "ativa")]:
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?, 1, ?, ?, ?, ?)",
                   (id_peca, f"F|{id_peca}", str(id_peca), desc, status))
    db.executemany("INSERT INTO origem (id_peca, site, url) VALUES (?, ?, ?)", [
        (1, "karhub", "https://k/p1"), (1, "universal", "https://u/p1"), (2, "carblue", "https://c/p2"),
        (3, "karhub", "https://k/p3"), (4, "karhub", "https://k/p4")])
    db.executemany("INSERT INTO vei_montadora (id_veiculo_montadora, nome, nome_exibicao, logo, qtd_pecas) "
                   "VALUES (?, ?, ?, ?, ?)", [
                       (1, "CHEVROLET", "Chevrolet", "veiculos/montadoras/1_aaa.png", 50), (2, "FIAT", "Fiat", None, 80),
                       (3, "HONDA", "Honda", None, 5), (4, "GURGEL", "Gurgel", None, 90)])
    db.executemany("INSERT INTO vei_modelo (id_modelo, id_veiculo_montadora, nome, nome_exibicao, tipo, foto, ano_inicio, "
                   "ano_fim, ativo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [
                       (10, 1, "ONIX", "Onix", "carro", "veiculos/modelos/10_bbb.webp", 2013, 2019, 1),
                       (11, 1, "CELTA", "Celta", "carro", None, 2005, 2010, 1),
                       (20, 2, "UNO", "Uno", "carro", None, 2008, 2012, 1),
                       (30, 3, "BIZ", "Biz", "moto", None, 2010, 2020, 1),
                       (40, 4, "BR 800", "BR 800", "carro", None, 1988, 1991, 0)])
    db.executemany("INSERT INTO vei_versao (id_versao, id_modelo, nome, nome_exibicao, motor, ativo) "
                   "VALUES (?, ?, ?, ?, ?, ?)", [
                       (100, 10, "LT 1.4 8V FLEX", "Lt 1.4 8v Flex", "1.4", 1),
                       (101, 10, "LS 1.0 8V FLEX", "Ls 1.0 8v Flex", "1.0", 1),
                       (102, 10, "LTZ 1.4 8V FLEX", "Ltz 1.4 8v Flex", "1.4", 0),
                       (110, 11, "LIFE 1.0", "Life 1.0", "1.0", 1), (200, 20, "MILLE 1.0", "Mille 1.0", "1.0", 1),
                       (300, 30, "KS 100CC", "Ks 100cc", None, 1), (400, 40, "SL 0.8", "Sl 0.8", "0.8", 1)])
    db.executemany("INSERT INTO vei_versao_ano VALUES (?, ?)",
                   [(100, a) for a in range(2013, 2020)] + [(101, a) for a in range(2013, 2017)]
                   + [(102, a) for a in range(2015, 2020)] + [(110, a) for a in range(2005, 2011)]
                   + [(200, a) for a in range(2008, 2013)] + [(300, a) for a in range(2010, 2021)]
                   + [(400, a) for a in range(1988, 1992)])
    db.executemany("INSERT INTO vei_peca VALUES (?, ?, ?, ?, ?, ?)", [
        (1, 10, None, 2013, 2016, "versao"),   # todas as versões do Onix 2013-2016
        (1, 10, 100, 2017, 2019, "versao"),    # só a LT em 2017-2019
        (1, 20, None, 2010, None, "modelo"),   # texto de aplicação: Uno a partir de 2010
        (2, 11, None, None, None, "modelo"),   # texto sem ano: Celta
        (3, 10, None, 2013, 2019, "versao")])  # peça inativa
    db.commit()
    db.close()
    return caminho


def test_helper_ausente_ou_sem_veiculos(tmp_path):
    vazio, sem_modelos = tmp_path / "vazio.sqlite", tmp_path / "sem_modelos.sqlite"
    sqlite3.connect(vazio).close()
    abrir(sem_modelos).close()
    for caminho in (tmp_path / "nao_existe.sqlite", vazio, sem_modelos):
        with pytest.raises(painel_veiculos.Indisponivel):
            with painel_veiculos.helper(caminho):
                pass


def test_helper_so_leitura_e_trava_vira_ocupado(tmp_path):
    caminho = _helper(tmp_path)
    with painel_veiculos.helper(caminho) as db:
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM vei_modelo")
    with pytest.raises(painel_veiculos.Ocupado):
        with painel_veiculos.helper(caminho):
            raise sqlite3.OperationalError("database is locked")


def test_url_imagem():
    assert painel_veiculos.url_imagem("veiculos/modelos/10_bbb.webp") == "/veiculos/img/modelos/10_bbb.webp"
    assert painel_veiculos.url_imagem(None) is None


def test_listas_do_seletor(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        montadoras = painel_veiculos.montadoras(db)
        assert [m["nome"] for m in montadoras] == ["Fiat", "Chevrolet", "Honda"]  # Gurgel só tem modelo inativo
        assert montadoras[1] == {"id": 1, "nome": "Chevrolet", "logo_url": "/veiculos/img/montadoras/1_aaa.png",
                                 "qtd_pecas": 50}
        assert painel_veiculos.modelos(db, 1) == [
            {"id": 11, "nome": "Celta", "tipo": "carro", "foto_url": None, "ano_inicio": 2005, "ano_fim": 2010},
            {"id": 10, "nome": "Onix", "tipo": "carro", "foto_url": "/veiculos/img/modelos/10_bbb.webp",
             "ano_inicio": 2013, "ano_fim": 2019}]
        assert painel_veiculos.modelos(db, 3)[0]["tipo"] == "moto"
        assert painel_veiculos.modelos(db, 4) == []
        assert painel_veiculos.anos(db, 10) == list(range(2019, 2012, -1))  # a LTZ (inativa) não conta
        assert painel_veiculos.versoes(db, 10, 2014) == [{"id": 101, "nome": "LS 1.0 8V FLEX"},
                                                        {"id": 100, "nome": "LT 1.4 8V FLEX"}]
        assert painel_veiculos.versoes(db, 10, 2018) == [{"id": 100, "nome": "LT 1.4 8V FLEX"}]


def test_veiculo_escolhido(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        assert painel_veiculos.veiculo_escolhido(db, 10, 2018, 100) == {"modelo": "ONIX",
                                                                       "texto": "Chevrolet Onix 2018 LT 1.4 8V FLEX"}
        assert painel_veiculos.veiculo_escolhido(db, 10, 2018) == {"modelo": "ONIX", "texto": "Chevrolet Onix 2018"}
        assert painel_veiculos.veiculo_escolhido(db, 40, 1990) is None  # modelo inativo
        assert painel_veiculos.veiculo_escolhido(db, 999, 2018) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'painel_veiculos'`.

- [ ] **Step 3: Implementar `painel_veiculos.py`**

```python
"""Veículos do helper (helper.sqlite, só leitura) para a aba Cadastrar do painel: listas do seletor, anúncios que
servem num veículo e veículos compatíveis de uma peça (lista, árvore, carros de venda e complemento).
Spec: docs/superpowers/specs/2026-10-06-painel-veiculos-design.md."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from helper.consulta import ORDEM_CONFIANCA, ids_por_veiculo  # noqa: F401 (ORDEM_CONFIANCA é usada pelo painel)

HELPER_DB = Path("helper.sqlite")
FOTOS_VEICULOS = Path("helper_fotos_veiculos")
PASTAS_IMAGEM = ("montadoras", "modelos")


class Indisponivel(Exception):
    """helper.sqlite ausente ou sem veículos: o painel funciona como antes."""


class Ocupado(Exception):
    """helper.sqlite travado por outro processo."""


@contextmanager
def helper(caminho=None):
    caminho = Path(caminho or HELPER_DB)
    if not caminho.exists():
        raise Indisponivel(f"{caminho} não encontrado")
    db = sqlite3.connect(f"{caminho.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        try:
            tem_modelos = db.execute("SELECT 1 FROM vei_modelo WHERE ativo = 1 LIMIT 1").fetchone()
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            tem_modelos = None
        if not tem_modelos:
            raise Indisponivel(f"{caminho} sem veículos")
        yield db
    except sqlite3.OperationalError as e:
        if "locked" in str(e) or "busy" in str(e):
            raise Ocupado("Base de veículos ocupada, tente de novo") from e
        raise
    finally:
        db.close()


def url_imagem(caminho):
    """'veiculos/modelos/2_c25631ef.webp' (caminho no servidor) -> '/veiculos/img/modelos/2_c25631ef.webp'."""
    return "/veiculos/img/" + caminho.removeprefix("veiculos/") if caminho else None


def montadoras(db):
    return [{"id": r["id_veiculo_montadora"], "nome": r["nome_exibicao"], "logo_url": url_imagem(r["logo"]),
             "qtd_pecas": r["qtd_pecas"]}
            for r in db.execute("""SELECT vm.id_veiculo_montadora, vm.nome_exibicao, vm.logo, vm.qtd_pecas
                                   FROM vei_montadora vm
                                   WHERE vm.ativo = 1 AND EXISTS (SELECT 1 FROM vei_modelo mo WHERE mo.ativo = 1
                                                                    AND mo.id_veiculo_montadora = vm.id_veiculo_montadora)
                                   ORDER BY vm.qtd_pecas DESC, vm.nome""")]


def modelos(db, id_montadora):
    return [{"id": r["id_modelo"], "nome": r["nome_exibicao"], "tipo": r["tipo"], "foto_url": url_imagem(r["foto"]),
             "ano_inicio": r["ano_inicio"], "ano_fim": r["ano_fim"]}
            for r in db.execute("""SELECT id_modelo, nome_exibicao, tipo, foto, ano_inicio, ano_fim FROM vei_modelo
                                   WHERE id_veiculo_montadora = ? AND ativo = 1 ORDER BY nome""", (id_montadora,))]


def anos(db, id_modelo):
    return [r[0] for r in db.execute("""SELECT DISTINCT va.ano FROM vei_versao_ano va JOIN vei_versao v USING (id_versao)
                                        WHERE v.id_modelo = ? AND v.ativo = 1 ORDER BY va.ano DESC""", (id_modelo,))]


def versoes(db, id_modelo, ano):
    return [{"id": r[0], "nome": r[1]}
            for r in db.execute("""SELECT v.id_versao, v.nome FROM vei_versao v JOIN vei_versao_ano va USING (id_versao)
                                   WHERE v.id_modelo = ? AND va.ano = ? AND v.ativo = 1 ORDER BY v.nome""",
                                (id_modelo, ano))]


def veiculo_escolhido(db, id_modelo, ano, id_versao=None):
    """Nome canônico do modelo (para achar o carro da sociedade) e o texto 'Chevrolet Onix 2018 LT 1.4 8V FLEX'."""
    r = db.execute("""SELECT vm.nome_exibicao AS montadora, mo.nome AS modelo, mo.nome_exibicao AS modelo_exibicao
                      FROM vei_modelo mo JOIN vei_montadora vm USING (id_veiculo_montadora)
                      WHERE mo.id_modelo = ? AND mo.ativo = 1""", (id_modelo,)).fetchone()
    if not r:
        return None
    versao = db.execute("SELECT nome FROM vei_versao WHERE id_versao = ? AND id_modelo = ?",
                        (id_versao, id_modelo)).fetchone() if id_versao else None
    texto = " ".join(filter(None, [r["montadora"], r["modelo_exibicao"], str(ano), versao and versao[0]]))
    return {"modelo": r["modelo"], "texto": texto}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add painel_veiculos.py tests/test_painel_veiculos.py
git commit -m "$(printf 'painel_veiculos: helper.sqlite só leitura e listas do seletor de veículo\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 4: Busca por veículo no servidor e rotas do seletor

**Files:**
- Modify: `painel_veiculos.py` (acrescenta `serve_no_veiculo`)
- Modify: `painel_wayap.py` — imports (linhas 30-38), `indexar_catalogos` (linha 89), `buscar_catalogos` (linha 144),
  `api_busca` (linha 622) e rotas novas na seção `# ---------- rotas ----------`
- Test: `tests/test_painel_veiculos.py`

**Interfaces:**
- Consumes: `painel_veiculos.helper`, `Indisponivel`, `Ocupado`, `montadoras`, `modelos`, `anos`, `versoes`,
  `FOTOS_VEICULOS`, `PASTAS_IMAGEM`, `ORDEM_CONFIANCA`, `ids_por_veiculo`; `_helper(tmp_path)` do teste.
- Produces:
  - `painel_veiculos.serve_no_veiculo(db, id_modelo, ano, id_versao=None) -> dict[(site, url), confianca]`
  - `painel_wayap.veiculo_da_requisicao(args) -> (id_modelo, ano, id_versao | None) | None`
  - `painel_wayap.buscar_catalogos(q, site="", limite=40, offset=0, serve=None)`; com `serve`, cada item traz
    `confianca`
  - rotas `GET /api/veiculos/{montadoras,modelos,anos,versoes}`, `GET /veiculos/img/<caminho>`; `api_busca` aceita
    `modelo`, `ano`, `versao` e devolve `confianca` em cada item
  - teste: fixture `painel` (cliente Flask com helper, catálogo e `estado` de mentira), `_catalogo(pasta)`,
    `_urls(itens)`, `SERVE`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao topo de `tests/test_painel_veiculos.py` (junto dos outros imports):

```python
import json
from contextlib import contextmanager

import painel_wayap
```

E ao fim do arquivo:

```python
def _catalogo(pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    itens = {
        "karhub": [
            {"url": "https://k/p1", "nome": "Pastilha Freio Onix", "marca": "Fremax", "codigo_fabricante": "PD1",
             "imagens": ["https://img/p1.jpg"], "carro": "Chevrolet Onix 2013-2019"},
            {"url": "https://k/p4", "nome": "Disco Freio Onix", "marca": "Fremax", "codigo_fabricante": "DF4",
             "ean": "7890000000004", "imagens": []},
            {"url": "https://k/p5", "nome": "Pastilha Freio Gol", "marca": "Fremax", "codigo_fabricante": "PD5",
             "imagens": ["https://img/p5.jpg"]}],
        "universal": [{"url": "https://u/p1", "nome": "Pastilha Freio Dianteira", "marca": "Fremax",
                       "codigo_fabricante": "PD1", "imagens": []}],
        "carblue": [{"url": "https://c/sem", "nome": "Lanterna Onix", "marca": "Fitam", "codigo_fabricante": "L9",
                     "imagens": [], "carro": "ONIX 2015 2016"}]}
    for site, linhas in itens.items():
        (pasta / f"{site}.jsonl").write_text("".join(json.dumps(l) + "\n" for l in linhas), encoding="utf-8")


@pytest.fixture
def painel(tmp_path, monkeypatch):
    monkeypatch.setattr(painel_veiculos, "HELPER_DB", _helper(tmp_path))
    monkeypatch.setattr(painel_wayap, "CATALOGOS", tmp_path / "catalogos")
    monkeypatch.setattr(painel_wayap, "DB_CATALOGOS", tmp_path / "catalogos" / "catalogos.sqlite")
    _catalogo(tmp_path / "catalogos")
    painel_wayap.indexar_catalogos()
    monkeypatch.setattr(painel_wayap, "estado", {
        "marcas": [{"id_marca": 7, "descricao": "FREMAX"}],
        "carros": [{"id_carro": 1, "descricao": "ONIX"}, {"id_carro": 2, "descricao": "CELTA"},
                   {"id_carro": 3, "descricao": "UNIVERSAL"}],
        "stats": {}, "fornecedores": [], "por_num": {}, "por_ean": {}, "por_codigo": {}})
    return painel_wayap.app.test_client()


def _urls(itens):
    return [(i["site"], i["url"]) for i in itens]


SERVE = {("karhub", "https://k/p1"): "todas_versoes", ("universal", "https://u/p1"): "todas_versoes",
         ("karhub", "https://k/p5"): "modelo_ano"}


def test_serve_no_veiculo(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        assert painel_veiculos.serve_no_veiculo(db, 10, 2014) == {("karhub", "https://k/p1"): "todas_versoes",
                                                                  ("universal", "https://u/p1"): "todas_versoes"}
        assert painel_veiculos.serve_no_veiculo(db, 10, 2018, 100) == {("karhub", "https://k/p1"): "versao",
                                                                       ("universal", "https://u/p1"): "versao"}
        assert painel_veiculos.serve_no_veiculo(db, 11, 2006) == {("carblue", "https://c/p2"): "modelo_ano"}
        assert painel_veiculos.serve_no_veiculo(db, 10, 2018, 101) == {}


def test_busca_por_veiculo_sem_texto_ordem_site_e_pagina(painel):
    itens, tem_mais = painel_wayap.buscar_catalogos("", serve=SERVE)
    assert _urls(itens) == [("karhub", "https://k/p1"), ("universal", "https://u/p1"), ("karhub", "https://k/p5")]
    assert [i["confianca"] for i in itens] == ["todas_versoes", "todas_versoes", "modelo_ano"]
    assert not tem_mais
    assert _urls(painel_wayap.buscar_catalogos("", site="universal", serve=SERVE)[0]) == [("universal", "https://u/p1")]
    pagina, tem_mais = painel_wayap.buscar_catalogos("", limite=1, offset=1, serve=SERVE)
    assert _urls(pagina) == [("universal", "https://u/p1")] and tem_mais
    assert painel_wayap.buscar_catalogos("", serve={}) == ([], False)


def test_busca_por_veiculo_com_texto_codigo_e_ean(painel):
    itens, _ = painel_wayap.buscar_catalogos("pastilha", serve=SERVE)
    assert set(_urls(itens)[:2]) == {("karhub", "https://k/p1"), ("universal", "https://u/p1")}
    assert _urls(itens)[2:] == [("karhub", "https://k/p5")]
    assert set(_urls(painel_wayap.buscar_catalogos("PD1", serve=SERVE)[0])) == {("karhub", "https://k/p1"),
                                                                               ("universal", "https://u/p1")}
    assert painel_wayap.buscar_catalogos("disco", serve=SERVE)[0] == []
    assert painel_wayap.buscar_catalogos("7890000000004", serve=SERVE)[0] == []  # EAN exato de peça que não serve
    assert _urls(painel_wayap.buscar_catalogos("7890000000004")[0]) == [("karhub", "https://k/p4")]  # sem veículo
    assert "confianca" not in painel_wayap.buscar_catalogos("pastilha")[0][0]


def test_busca_por_veiculo_com_muitas_pecas(painel):
    serve = {("karhub", f"https://k/x{i}"): "modelo_ano" for i in range(60000)} | SERVE
    itens, tem_mais = painel_wayap.buscar_catalogos("", serve=serve)
    assert _urls(itens)[0] == ("karhub", "https://k/p1") and len(itens) == 3 and not tem_mais


def test_rotas_do_seletor(painel):
    assert [m["nome"] for m in painel.get("/api/veiculos/montadoras").get_json()] == ["Fiat", "Chevrolet", "Honda"]
    assert [m["id"] for m in painel.get("/api/veiculos/modelos?montadora=1").get_json()] == [11, 10]
    assert painel.get("/api/veiculos/anos?modelo=10").get_json()[0] == 2019
    assert painel.get("/api/veiculos/versoes?modelo=10&ano=2018").get_json() == [{"id": 100, "nome": "LT 1.4 8V FLEX"}]


def test_api_busca_com_veiculo(painel):
    d = painel.get("/api/catalogo/busca?q=&modelo=10&ano=2014").get_json()
    assert {(i["site"], i["url"]): i["confianca"] for i in d["itens"]} == {("karhub", "https://k/p1"): "todas_versoes",
                                                                          ("universal", "https://u/p1"): "todas_versoes"}
    assert painel.get("/api/catalogo/busca?q=pastilha&modelo=10&ano=2018&versao=101").get_json()["itens"] == []
    assert painel.get("/api/catalogo/busca?q=pastilha").get_json()["itens"][0]["confianca"] is None


def test_base_ausente_ou_ocupada(painel, monkeypatch, tmp_path):
    monkeypatch.setattr(painel_veiculos, "HELPER_DB", tmp_path / "nao_existe.sqlite")
    r = painel.get("/api/veiculos/montadoras")
    assert r.status_code == 404 and r.get_json() == {"erro": "Base de veículos não encontrada"}
    assert painel.get("/api/catalogo/busca?q=pastilha&modelo=10&ano=2014").status_code == 404
    assert painel.get("/api/catalogo/busca?q=pastilha").status_code == 200  # sem veículo não depende do helper

    @contextmanager
    def ocupado(caminho=None):
        raise painel_veiculos.Ocupado("Base de veículos ocupada, tente de novo")
        yield

    monkeypatch.setattr(painel_veiculos, "helper", ocupado)
    r = painel.get("/api/catalogo/busca?q=pastilha&modelo=10&ano=2014")
    assert r.status_code == 503 and r.get_json() == {"erro": "Base de veículos ocupada, tente de novo"}


def test_imagem_de_veiculo_so_das_pastas_do_helper(painel, monkeypatch, tmp_path):
    fotos = tmp_path / "fotos"
    (fotos / "modelos").mkdir(parents=True)
    (fotos / "outra").mkdir()
    (fotos / "modelos" / "10_bbb.webp").write_bytes(b"RIFF-WEBP")
    (fotos / "outra" / "x.png").write_bytes(b"x")
    (tmp_path / "segredo.txt").write_text("não", encoding="utf-8")
    monkeypatch.setattr(painel_veiculos, "FOTOS_VEICULOS", fotos)
    r = painel.get("/veiculos/img/modelos/10_bbb.webp")
    assert r.status_code == 200 and r.data == b"RIFF-WEBP"
    r.close()
    assert painel.get("/veiculos/img/modelos/../../segredo.txt").status_code == 404
    assert painel.get("/veiculos/img/outra/x.png").status_code == 404
    assert painel.get("/veiculos/img/modelos/nao_tem.webp").status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: FAIL — `AttributeError: module 'painel_veiculos' has no attribute 'serve_no_veiculo'` e
`TypeError: buscar_catalogos() got an unexpected keyword argument 'serve'`, além de 404 nas rotas novas.

- [ ] **Step 3: Implementar `serve_no_veiculo` em `painel_veiculos.py`**

Acrescente `import json` no topo (antes de `import sqlite3`) e, ao fim do arquivo:

```python
def serve_no_veiculo(db, id_modelo, ano, id_versao=None):
    """{(site, url): confiança} dos anúncios cujas peças servem no veículo, pelas regras de ids_por_veiculo do helper."""
    ids = ids_por_veiculo(db, id_modelo, ano, id_versao)
    if not ids:
        return {}
    linhas = db.execute("SELECT o.id_peca, o.site, o.url FROM json_each(?) j JOIN origem o ON o.id_peca = j.value",
                        (json.dumps(list(ids)),))
    return {(site, url): ids[id_peca] for id_peca, site, url in linhas}
```

- [ ] **Step 4: Ligar o painel ao módulo (imports e índice do catálogo)**

Em `painel_wayap.py`, na linha do Flask:

```python
from flask import Flask, Response, abort, jsonify, redirect, request, send_file, send_from_directory
```

E entre `from aplicacao_texto import ...` e `from wayap_fotos import (...`:

```python
import painel_veiculos
```

Em `indexar_catalogos`, no `executescript`, logo depois de `CREATE INDEX IF NOT EXISTS item_site ON item (site);`:

```python
        CREATE INDEX IF NOT EXISTS item_site_url ON item (site, url);
```

- [ ] **Step 5: Trocar `buscar_catalogos` inteira por:**

```python
def buscar_catalogos(q, site="", limite=40, offset=0, serve=None):
    """Uma página de resultados: EAN e código exatos vêm na primeira; a busca textual é paginada. Com `serve`
    ({(site, url): confiança}, da busca por veículo) só entram os anúncios que servem, os mais confiáveis primeiro."""
    q = q.strip()
    filtro, args = ("AND item.site = ?", [site]) if site else ("", [])
    achados, textuais = [], []
    with db_catalogos() as db:
        colunas, junta, ordem = "item.*", "", "rank"
        if serve is not None:
            db.execute("CREATE TEMP TABLE serve (site TEXT, url TEXT, confianca TEXT, ordem INTEGER, PRIMARY KEY (site, url))")
            db.executemany("INSERT INTO serve VALUES (?, ?, ?, ?)",
                           [(s, u, c, painel_veiculos.ORDEM_CONFIANCA[c]) for (s, u), c in serve.items()])
            colunas, ordem = "item.*, serve.confianca", "serve.ordem, rank"
            junta = "JOIN serve ON serve.site = item.site AND serve.url = item.url"
        if offset == 0 and n_ean(q):
            achados += db.execute(f"SELECT {colunas} FROM item {junta} WHERE ean = ? {filtro}", [n_ean(q)] + args).fetchall()
        if offset == 0 and " " not in q and len(n_codigo(q)) >= 3:
            achados += db.execute(f"SELECT {colunas} FROM item {junta} WHERE codigos LIKE ? {filtro} LIMIT 200",
                                  [f"%|{n_codigo(q)}|%"] + args).fetchall()
        termos = re.findall(r"\w+", sem_acento(q))
        if termos:
            consulta = " ".join(f'"{t}"*' for t in termos)
            textuais = db.execute(f"SELECT {colunas} FROM busca JOIN item ON item.id = busca.rowid {junta} "
                                  f"WHERE busca MATCH ? {filtro} ORDER BY {ordem} LIMIT ? OFFSET ?",
                                  [consulta] + args + [limite, offset]).fetchall()
        elif serve is not None:  # só o veículo: todas as peças dele, as com foto antes
            textuais = db.execute(f"SELECT {colunas} FROM serve JOIN item ON item.site = serve.site AND item.url = serve.url "
                                  f"WHERE 1 {filtro} ORDER BY serve.ordem, item.imagens = '[]', item.id LIMIT ? OFFSET ?",
                                  args + [limite, offset]).fetchall()
    vistos, lista = set(), []
    for r in achados + textuais:
        if r["id"] not in vistos:
            vistos.add(r["id"])
            lista.append(dict(r))
    return lista, len(textuais) == limite
```

- [ ] **Step 6: Trocar `api_busca` e acrescentar as rotas novas**

Troque a função `api_busca` inteira por:

```python
def veiculo_da_requisicao(args):
    """(modelo, ano, versão ou None) dos parâmetros, ou None sem veículo completo (modelo e ano)."""
    try:
        modelo, ano = int(args.get("modelo", "")), int(args.get("ano", ""))
    except ValueError:
        return None
    versao = args.get("versao", "")
    return modelo, ano, int(versao) if versao.isdigit() else None


@app.errorhandler(painel_veiculos.Indisponivel)
def base_de_veiculos_ausente(e):
    return jsonify({"erro": "Base de veículos não encontrada"}), 404


@app.errorhandler(painel_veiculos.Ocupado)
def base_de_veiculos_ocupada(e):
    return jsonify({"erro": str(e)}), 503


@app.get("/api/catalogo/busca")
def api_busca():
    serve, veiculo = None, veiculo_da_requisicao(request.args)
    if veiculo:
        with painel_veiculos.helper() as h:
            serve = painel_veiculos.serve_no_veiculo(h, *veiculo)
    lista = []
    achados, tem_mais = buscar_catalogos(request.args.get("q", ""), request.args.get("site", ""),
                                         offset=int(request.args.get("offset", 0)), serve=serve)
    for r in achados:
        existente = ja_cadastrado(r)
        imagens = json.loads(r["imagens"])
        lista.append({"id": r["id"], "site": r["site"], "site_nome": nome_site(r["site"]), "nome": r["nome"],
                      "marca": r["marca"], "codigo": r["codigo"], "ean": r["ean"], "carro": r["carro"], "url": r["url"],
                      "imagens": imagens, "confianca": r.get("confianca"),
                      "existente": {"cod_produto": existente["cod_produto"], "desc_produto": existente["desc_produto"]}
                      if existente else None})
    return jsonify({"itens": lista, "tem_mais": tem_mais})


@app.get("/api/veiculos/montadoras")
def api_montadoras():
    with painel_veiculos.helper() as db:
        return jsonify(painel_veiculos.montadoras(db))


@app.get("/api/veiculos/modelos")
def api_modelos():
    with painel_veiculos.helper() as db:
        return jsonify(painel_veiculos.modelos(db, request.args.get("montadora", type=int)))


@app.get("/api/veiculos/anos")
def api_anos():
    with painel_veiculos.helper() as db:
        return jsonify(painel_veiculos.anos(db, request.args.get("modelo", type=int)))


@app.get("/api/veiculos/versoes")
def api_versoes():
    with painel_veiculos.helper() as db:
        return jsonify(painel_veiculos.versoes(db, request.args.get("modelo", type=int),
                                               request.args.get("ano", type=int)))


@app.get("/veiculos/img/<path:caminho>")
def imagem_veiculo(caminho):
    """Logo de montadora e foto de modelo do helper; send_from_directory recusa caminho que sai da pasta."""
    if caminho.split("/")[0] not in painel_veiculos.PASTAS_IMAGEM:
        abort(404)
    return send_from_directory(painel_veiculos.FOTOS_VEICULOS.resolve(), caminho, max_age=86400)
```

- [ ] **Step 7: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: 13 passed.

- [ ] **Step 8: Rodar a suíte inteira**

Run: `.venv/bin/python -m pytest -q`
Expected: tudo passa.

- [ ] **Step 9: Commit**

```bash
git add painel_veiculos.py painel_wayap.py tests/test_painel_veiculos.py
git commit -m "$(printf 'painel: busca por veículo (anúncios que servem, por confiança) e rotas do seletor de veículo\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 5: `painel_veiculos.py` — veículos de uma peça

**Files:**
- Modify: `painel_veiculos.py`
- Test: `tests/test_painel_veiculos.py`

**Interfaces:**
- Consumes: `helper`, `url_imagem`, `veiculo_escolhido`, `ids_por_veiculo`; `_helper(tmp_path)`.
- Produces:
  - `peca_do_item(db, site, url) -> int | None` (só peça ativa)
  - `veiculos_da_peca(db, id_peca) -> list[dict]` — chaves: `montadora`, `montadora_exibicao`, `logo`, `id_modelo`,
    `modelo`, `modelo_exibicao`, `tipo`, `foto`, `id_versao`, `versao`, `motor`, `ano_inicio`, `ano_fim`, `nivel`,
    `motores` (lista de str)
  - `faixa(inicio, fim) -> str`, `texto_linha(linha) -> str`
  - `lista(linhas) -> list[{"texto", "selo", "tipo"}]`, `linhas_complemento(linhas) -> str`
  - `ocorrencias(linhas) -> list[[rotulo, modelo, (inicio, fim) | None, motores]]` (entrada de `agrupar_veiculos`)
  - `arvore(db, linhas) -> list[{"nome", "logo_url", "modelos": [{"nome", "tipo", "foto_url", "faixa",
    "anos": [{"ano", "versoes", "todas", "confira"}]}]}]`
  - `seu_veiculo(db, id_peca, id_modelo, ano, id_versao=None) -> {"veiculo", "confianca", "veredito"} | None`

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_painel_veiculos.py`:

```python
def test_peca_do_item(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        assert painel_veiculos.peca_do_item(db, "universal", "https://u/p1") == 1
        assert painel_veiculos.peca_do_item(db, "karhub", "https://k/p3") is None  # peça inativa
        assert painel_veiculos.peca_do_item(db, "carblue", "https://c/sem") is None


def test_linhas_lista_e_complemento(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        linhas = painel_veiculos.veiculos_da_peca(db, 1)
        assert [(l["modelo"], l["versao"], l["ano_inicio"], l["ano_fim"], l["nivel"], l["motores"]) for l in linhas] == [
            ("ONIX", None, 2013, 2016, "versao", ["1.0", "1.4"]),   # todas as versões: motores das versões ativas
            ("ONIX", "LT 1.4 8V FLEX", 2017, 2019, "versao", ["1.4"]),
            ("UNO", None, 2010, None, "modelo", [])]
        assert painel_veiculos.lista(linhas) == [
            {"texto": "CHEVROLET ONIX 2013-2016", "selo": "todas as versões", "tipo": "carro"},
            {"texto": "CHEVROLET ONIX 2017-2019 LT 1.4 8V FLEX", "selo": None, "tipo": "carro"},
            {"texto": "FIAT UNO 2010-", "selo": "confira a versão", "tipo": "carro"}]
        assert painel_veiculos.linhas_complemento(linhas) == (
            "CHEVROLET ONIX 2013-2016\nCHEVROLET ONIX 2017-2019 LT 1.4 8V FLEX\nFIAT UNO 2010-")
        assert painel_veiculos.lista(painel_veiculos.veiculos_da_peca(db, 2)) == [
            {"texto": "CHEVROLET CELTA", "selo": "confira a versão", "tipo": "carro"}]
        assert painel_veiculos.veiculos_da_peca(db, 4) == []


def test_faixa():
    assert painel_veiculos.faixa(2013, 2019) == "2013-2019"
    assert painel_veiculos.faixa(2019, 2019) == "2019"
    assert painel_veiculos.faixa(2010, None) == "2010-"
    assert painel_veiculos.faixa(None, 1992) == "-1992"
    assert painel_veiculos.faixa(None, None) == ""


def test_ocorrencias_para_os_carros_de_venda(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        assert painel_veiculos.ocorrencias(painel_veiculos.veiculos_da_peca(db, 1)) == [
            ["CHEVROLET ONIX", "ONIX", (2013, 2016), ["1.0", "1.4"]],
            ["CHEVROLET ONIX", "ONIX", (2017, 2019), ["1.4"]],
            ["FIAT UNO", "UNO", (2010, None), []]]
        assert painel_veiculos.ocorrencias(painel_veiculos.veiculos_da_peca(db, 2)) == [
            ["CHEVROLET CELTA", "CELTA", None, []]]


def test_arvore(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        arvore = painel_veiculos.arvore(db, painel_veiculos.veiculos_da_peca(db, 1))
        assert [(m["nome"], m["logo_url"]) for m in arvore] == [("Chevrolet", "/veiculos/img/montadoras/1_aaa.png"),
                                                                 ("Fiat", None)]
        onix = arvore[0]["modelos"][0]
        assert (onix["nome"], onix["tipo"], onix["foto_url"], onix["faixa"]) == (
            "Onix", "carro", "/veiculos/img/modelos/10_bbb.webp", "2013-2019")
        assert [a["ano"] for a in onix["anos"]] == list(range(2019, 2012, -1))
        assert onix["anos"][0] == {"ano": 2019, "versoes": ["LT 1.4 8V FLEX"], "todas": False, "confira": False}
        assert onix["anos"][-1] == {"ano": 2013, "versoes": ["LS 1.0 8V FLEX", "LT 1.4 8V FLEX"], "todas": True,
                                    "confira": False}  # a LTZ é inativa
        uno = arvore[1]["modelos"][0]
        assert uno["faixa"] == "2010-2012"  # texto 'a partir de 2010': só os anos que o Uno tem
        assert uno["anos"] == [{"ano": a, "versoes": [], "todas": False, "confira": True} for a in (2012, 2011, 2010)]
        celta = painel_veiculos.arvore(db, painel_veiculos.veiculos_da_peca(db, 2))[0]["modelos"][0]
        assert [a["ano"] for a in celta["anos"]] == list(range(2010, 2004, -1))  # sem ano: todos os anos do modelo


def test_seu_veiculo(tmp_path):
    with painel_veiculos.helper(_helper(tmp_path)) as db:
        sv = painel_veiculos.seu_veiculo
        assert sv(db, 1, 10, 2014) == {"veiculo": "Chevrolet Onix 2014", "confianca": "todas_versoes", "veredito": "Serve"}
        assert sv(db, 1, 10, 2018)["veredito"] == "Serve em algumas versões: escolha a versão"
        assert sv(db, 1, 10, 2018, 100) == {"veiculo": "Chevrolet Onix 2018 LT 1.4 8V FLEX", "confianca": "versao",
                                            "veredito": "Serve"}
        assert sv(db, 1, 10, 2018, 101)["veredito"] == "Não serve nesta versão"
        assert sv(db, 1, 20, 2015)["veredito"] == "Confira a versão"
        assert sv(db, 2, 10, 2014) == {"veiculo": "Chevrolet Onix 2014", "confianca": None,
                                       "veredito": "Não consta para este veículo"}
        assert sv(db, 1, 999, 2014) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: FAIL — `AttributeError: module 'painel_veiculos' has no attribute 'peca_do_item'` (e as demais funções).

- [ ] **Step 3: Implementar em `painel_veiculos.py`**

Acrescente `from collections import defaultdict` aos imports e, ao fim do arquivo:

```python
SELO_TODAS, SELO_CONFIRA = "todas as versões", "confira a versão"
VEREDITOS = {"versao": "Serve", "todas_versoes": "Serve", "algumas_versoes": "Serve em algumas versões: escolha a versão",
             "modelo_ano": "Confira a versão"}


def peca_do_item(db, site, url):
    r = db.execute("""SELECT o.id_peca FROM origem o JOIN peca p USING (id_peca)
                      WHERE o.site = ? AND o.url = ? AND p.status = 'ativa'""", (site, url)).fetchone()
    return r[0] if r else None


def motores_do_modelo(db, id_modelo, ano_inicio, ano_fim):
    return [m for (m,) in db.execute("""SELECT DISTINCT v.motor FROM vei_versao v JOIN vei_versao_ano va USING (id_versao)
                                        WHERE v.id_modelo = ? AND v.ativo = 1 AND v.motor IS NOT NULL
                                          AND va.ano BETWEEN ? AND ? ORDER BY CAST(v.motor AS REAL)""",
                                     (id_modelo, ano_inicio, ano_fim))]


def veiculos_da_peca(db, id_peca):
    """Linhas de vei_peca da peça com nomes e motores, na ordem montadora, modelo, ano e versão (nulos primeiro)."""
    linhas = []
    for r in db.execute("""SELECT vm.nome AS montadora, vm.nome_exibicao AS montadora_exibicao, vm.logo,
                                  mo.id_modelo, mo.nome AS modelo, mo.nome_exibicao AS modelo_exibicao, mo.tipo, mo.foto,
                                  pv.id_versao, v.nome AS versao, v.motor, pv.ano_inicio, pv.ano_fim, pv.nivel
                           FROM vei_peca pv JOIN vei_modelo mo USING (id_modelo)
                                JOIN vei_montadora vm USING (id_veiculo_montadora)
                                LEFT JOIN vei_versao v ON v.id_versao = pv.id_versao
                           WHERE pv.id_peca = ? AND mo.ativo = 1 AND vm.ativo = 1 AND (pv.id_versao IS NULL OR v.ativo = 1)
                           ORDER BY vm.nome, mo.nome, pv.ano_inicio, v.nome""", (id_peca,)):
        linha = dict(r)
        if r["id_versao"]:
            linha["motores"] = [r["motor"]] if r["motor"] else []
        elif r["nivel"] == "versao":  # todas as versões: os motores das versões que existem na faixa
            linha["motores"] = motores_do_modelo(db, r["id_modelo"], r["ano_inicio"], r["ano_fim"])
        else:
            linha["motores"] = []
        linhas.append(linha)
    return linhas


def faixa(inicio, fim):
    """(2013, 2019) -> '2013-2019'; (2019, 2019) -> '2019'; (2010, None) -> '2010-'; (None, None) -> ''."""
    if inicio is None and fim is None:
        return ""
    if inicio == fim:
        return str(inicio)
    return f"{inicio or ''}-{fim or ''}"


def texto_linha(l):
    """'CHEVROLET ONIX 2013-2019 LT 1.4 8V FLEX': nomes canônicos, como a lista da KarHub."""
    return " ".join(p for p in (l["montadora"], l["modelo"], faixa(l["ano_inicio"], l["ano_fim"]), l["versao"]) if p)


def lista(linhas):
    return [{"texto": texto_linha(l), "tipo": l["tipo"],
             "selo": SELO_CONFIRA if l["nivel"] == "modelo" else None if l["id_versao"] else SELO_TODAS}
            for l in linhas]


def linhas_complemento(linhas):
    return "\n".join(dict.fromkeys(texto_linha(l) for l in linhas))


def ocorrencias(linhas):
    """Entrada do agrupar_veiculos do painel: [rótulo, modelo, (início, fim) ou None, motores]."""
    return [[f"{l['montadora']} {l['modelo']}", l["modelo"],
             None if l["ano_inicio"] is None and l["ano_fim"] is None else (l["ano_inicio"], l["ano_fim"]), l["motores"]]
            for l in linhas]


def arvore(db, linhas):
    """Montadora -> modelos -> anos (decrescente) -> versões do ano, como a vista em árvore da KarHub."""
    montadoras, versoes_do_modelo = {}, {}
    for l in linhas:
        if l["id_modelo"] not in versoes_do_modelo:
            por_ano = defaultdict(dict)
            for ano, id_versao, nome in db.execute("""SELECT va.ano, v.id_versao, v.nome FROM vei_versao v
                                                      JOIN vei_versao_ano va USING (id_versao)
                                                      WHERE v.id_modelo = ? AND v.ativo = 1""", (l["id_modelo"],)):
                por_ano[ano][id_versao] = nome
            versoes_do_modelo[l["id_modelo"]] = por_ano
        m = montadoras.setdefault(l["montadora"], {"nome": l["montadora_exibicao"], "logo_url": url_imagem(l["logo"]),
                                                   "modelos": {}})
        mo = m["modelos"].setdefault(l["id_modelo"], {"nome": l["modelo_exibicao"], "tipo": l["tipo"],
                                                      "foto_url": url_imagem(l["foto"]), "anos": {}})
        inicio, fim = l["ano_inicio"] or 0, l["ano_fim"] or 9999
        for ano, versoes_ano in versoes_do_modelo[l["id_modelo"]].items():
            if not inicio <= ano <= fim or (l["id_versao"] and l["id_versao"] not in versoes_ano):
                continue
            a = mo["anos"].setdefault(ano, {"ano": ano, "versoes": set(), "todas": False, "confira": False})
            if l["nivel"] == "modelo":
                a["confira"] = True
            elif l["id_versao"]:
                a["versoes"].add(versoes_ano[l["id_versao"]])
            else:
                a["todas"] = True
                a["versoes"].update(versoes_ano.values())
    return [{"nome": m["nome"], "logo_url": m["logo_url"],
             "modelos": [{"nome": mo["nome"], "tipo": mo["tipo"], "foto_url": mo["foto_url"],
                          "faixa": faixa(min(mo["anos"], default=None), max(mo["anos"], default=None)),
                          "anos": [dict(a, versoes=sorted(a["versoes"]))
                                   for _, a in sorted(mo["anos"].items(), reverse=True)]}
                         for mo in m["modelos"].values()]}
            for m in montadoras.values()]


def seu_veiculo(db, id_peca, id_modelo, ano, id_versao=None):
    """Veredito da peça para o veículo escolhido na busca (o 'Confirmar compatibilidade' da KarHub)."""
    escolhido = veiculo_escolhido(db, id_modelo, ano, id_versao)
    if not escolhido:
        return None
    confianca = ids_por_veiculo(db, id_modelo, ano, id_versao).get(id_peca)
    if confianca:
        veredito = VEREDITOS[confianca]
    elif id_versao is not None and id_peca in ids_por_veiculo(db, id_modelo, ano):
        veredito = "Não serve nesta versão"
    else:
        veredito = "Não consta para este veículo"
    return {"veiculo": escolhido["texto"], "confianca": confianca, "veredito": veredito}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: 19 passed.

- [ ] **Step 5: Commit**

```bash
git add painel_veiculos.py tests/test_painel_veiculos.py
git commit -m "$(printf 'painel_veiculos: veículos de uma peça (lista, árvore, ocorrências, complemento e seu veículo)\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 6: Formulário no servidor — veículos da base, carro principal e plano B

**Files:**
- Modify: `painel_wayap.py` — `sugestao` (linha 367), `api_sugestao` (linha 638); função nova `veiculos_do_item`
  logo depois de `veiculos_sugeridos`
- Test: `tests/test_painel_veiculos.py`

**Interfaces:**
- Consumes: `painel_veiculos.helper`, `veiculo_escolhido`, `peca_do_item`, `veiculos_da_peca`, `ocorrencias`,
  `lista`, `arvore`, `linhas_complemento`, `seu_veiculo`, `Indisponivel`, `Ocupado`;
  `painel_wayap.agrupar_veiculos`, `veiculos_sugeridos`, `carro_do_modelo`, `veiculo_da_requisicao`; fixture `painel`.
- Produces:
  - `painel_wayap.veiculos_do_item(item, veiculo=None) -> {"fonte": "base"|"site", "veiculos", "lista", "arvore",
    "complemento", "seu_veiculo", "modelo_escolhido"}`
  - `painel_wayap.sugestao(item, vei)` (o segundo parâmetro é o retorno acima)
  - `GET /api/catalogo/sugestao/<id>?modelo=&ano=&versao=` com `veiculos_fonte`, `veiculos_lista`,
    `veiculos_arvore`, `seu_veiculo` no topo da resposta

- [ ] **Step 1: Escrever os testes que falham**

Acrescente ao fim de `tests/test_painel_veiculos.py`:

```python
def _id_item(site, url):
    with painel_wayap.db_catalogos() as db:
        return db.execute("SELECT id FROM item WHERE site = ? AND url = ?", (site, url)).fetchone()[0]


def _sem_karhub_ao_vivo(monkeypatch):
    monkeypatch.setattr(painel_wayap, "html_produto_karhub", lambda url: "")


def test_sugestao_com_veiculos_da_base(painel, monkeypatch):
    _sem_karhub_ao_vivo(monkeypatch)
    d = painel.get(f"/api/catalogo/sugestao/{_id_item('karhub', 'https://k/p1')}?modelo=10&ano=2014").get_json()
    assert d["veiculos_fonte"] == "base"
    assert [l["texto"] for l in d["veiculos_lista"]] == ["CHEVROLET ONIX 2013-2016",
                                                         "CHEVROLET ONIX 2017-2019 LT 1.4 8V FLEX", "FIAT UNO 2010-"]
    assert d["veiculos_arvore"][0]["modelos"][0]["anos"][0]["ano"] == 2019
    assert d["seu_veiculo"] == {"veiculo": "Chevrolet Onix 2014", "confianca": "todas_versoes", "veredito": "Serve"}
    c = d["campos"]
    assert c["id_carro"] == 1
    assert c["complemento_produto"] == "CHEVROLET ONIX 2013-2016\nCHEVROLET ONIX 2017-2019 LT 1.4 8V FLEX\nFIAT UNO 2010-"
    assert c["veiculos"] == [
        {"id_carro": 1, "carro": "ONIX", "modelo_origem": "CHEVROLET ONIX", "complemento": "1.0 / 1.4 13/19", "versoes": 2},
        {"id_carro": None, "carro": "", "modelo_origem": "FIAT UNO", "complemento": "10/ UNO", "versoes": 1}]
    assert "Alguns modelos da base não existem no cadastro de carros: escolha o carro ou desmarque." in c["avisos"]


def test_veiculo_escolhido_manda_no_carro_principal(painel, monkeypatch):
    _sem_karhub_ao_vivo(monkeypatch)
    d = painel.get(f"/api/catalogo/sugestao/{_id_item('karhub', 'https://k/p1')}?modelo=11&ano=2006").get_json()
    assert d["campos"]["id_carro"] == 2  # o Celta escolhido na busca, mesmo a peça não constando para ele
    assert d["seu_veiculo"]["veredito"] == "Não consta para este veículo"
    d = painel.get(f"/api/catalogo/sugestao/{_id_item('karhub', 'https://k/p1')}?modelo=20&ano=2011").get_json()
    assert d["campos"]["id_carro"] == 1  # o Uno não existe na sociedade: regras de hoje (primeiro compatível)
    assert d["seu_veiculo"]["veredito"] == "Confira a versão"


def test_sugestao_sem_peca_ou_sem_veiculos_usa_o_site(painel, monkeypatch):
    _sem_karhub_ao_vivo(monkeypatch)
    d = painel.get(f"/api/catalogo/sugestao/{_id_item('carblue', 'https://c/sem')}?modelo=10&ano=2015").get_json()
    assert (d["veiculos_fonte"], d["veiculos_lista"], d["seu_veiculo"]) == ("site", [], None)
    assert [v["id_carro"] for v in d["campos"]["veiculos"]] == [1]
    assert d["campos"]["complemento_produto"] == "ONIX 2015 2016"
    d = painel.get(f"/api/catalogo/sugestao/{_id_item('karhub', 'https://k/p4')}").get_json()
    assert d["veiculos_fonte"] == "site" and d["campos"]["veiculos"] == []
    assert "KarHub não informa veículos compatíveis para esta peça: confira o carro principal." in d["campos"]["avisos"]


def test_sugestao_com_base_ocupada_usa_o_site(painel, monkeypatch):
    _sem_karhub_ao_vivo(monkeypatch)

    @contextmanager
    def ocupado(caminho=None):
        raise painel_veiculos.Ocupado("Base de veículos ocupada, tente de novo")
        yield

    monkeypatch.setattr(painel_veiculos, "helper", ocupado)
    r = painel.get(f"/api/catalogo/sugestao/{_id_item('karhub', 'https://k/p1')}?modelo=10&ano=2014")
    assert r.status_code == 200 and r.get_json()["veiculos_fonte"] == "site"
    assert [v["id_carro"] for v in r.get_json()["campos"]["veiculos"]] == [1]  # pelo texto 'Chevrolet Onix 2013-2019'
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: FAIL — `KeyError: 'veiculos_fonte'` nos testes novos.

- [ ] **Step 3: Acrescentar `veiculos_do_item` logo depois de `veiculos_sugeridos`**

```python
def veiculos_do_item(item, veiculo=None):
    """Veículos do anúncio: da base de peças (helper) quando ele chega a uma peça com veículos; senão os do site, como
    antes. `veiculo` é o (modelo, ano, versão) escolhido na busca, para o carro principal e o 'Seu veículo'."""
    vei = {"fonte": "site", "lista": [], "arvore": [], "seu_veiculo": None, "modelo_escolhido": None}
    try:
        with painel_veiculos.helper() as h:
            if veiculo:
                escolhido = painel_veiculos.veiculo_escolhido(h, *veiculo)
                vei["modelo_escolhido"] = escolhido["modelo"] if escolhido else None
            id_peca = painel_veiculos.peca_do_item(h, item["site"], item["url"])
            linhas = painel_veiculos.veiculos_da_peca(h, id_peca) if id_peca else []
            if linhas:
                vei.update(fonte="base", veiculos=agrupar_veiculos(painel_veiculos.ocorrencias(linhas)),
                           lista=painel_veiculos.lista(linhas), arvore=painel_veiculos.arvore(h, linhas),
                           complemento=painel_veiculos.linhas_complemento(linhas),
                           seu_veiculo=painel_veiculos.seu_veiculo(h, id_peca, *veiculo) if veiculo else None)
                return vei
    except (painel_veiculos.Indisponivel, painel_veiculos.Ocupado):
        pass
    veiculos, linhas = veiculos_sugeridos(item)
    vei.update(veiculos=veiculos, complemento="\n".join(linhas))
    return vei
```

- [ ] **Step 4: Ajustar `sugestao`**

Troque a assinatura e a docstring:

```python
def sugestao(item, vei):
    """Campos do formulário. `vei` é o resultado de veiculos_do_item (carros de venda, complemento e o modelo
    escolhido na busca)."""
```

Troque o trecho que vai de `veiculos, linhas = veiculos_sugeridos(item)` até o `else: carro = achar_carro(item["carro"])` por:

```python
    veiculos = vei["veiculos"]
    ids = [v["id_carro"] for v in veiculos if v["id_carro"]]
    titulo = carro_do_titulo(item["nome"] or "")
    escolhido = carro_do_modelo(vei["modelo_escolhido"]) if vei["modelo_escolhido"] else None
    # carro principal: o do veículo escolhido na busca; senão o citado no título; senão o primeiro dos veículos
    # compatíveis; senão o da aplicação
    if escolhido:
        carro = escolhido
    elif titulo and (titulo["id_carro"] in ids or not ids):
        carro = titulo
    elif ids:
        carro = next(c for c in estado["carros"] if c["id_carro"] == ids[0])
    else:
        carro = achar_carro(item["carro"])
```

Troque os dois avisos de veículos:

```python
    if not vei["complemento"]:
        avisos.append(f"{site} não informa veículos compatíveis para esta peça: confira o carro principal.")
    elif any(v["id_carro"] is None for v in veiculos):
        avisos.append("Alguns modelos da base não existem no cadastro de carros: escolha o carro ou desmarque."
                      if vei["fonte"] == "base" else
                      f"Alguns modelos citados em {site} não existem no cadastro de carros: escolha o carro ou desmarque.")
```

E no `return`, a última linha `"complemento_produto": "\n".join(linhas),` vira:

```python
        "complemento_produto": vei["complemento"],
```

- [ ] **Step 5: Trocar `api_sugestao`**

```python
@app.get("/api/catalogo/sugestao/<int:id_item>")
def api_sugestao(id_item):
    item = item_do_catalogo(id_item)
    vei = veiculos_do_item(item, veiculo_da_requisicao(request.args))
    return jsonify({"campos": sugestao(item, vei), "marcas": estado["marcas"], "carros": estado["carros"],
                    "fornecedores": estado["fornecedores"], "imagens": json.loads(item["imagens"]),
                    "veiculos_fonte": vei["fonte"], "veiculos_lista": vei["lista"], "veiculos_arvore": vei["arvore"],
                    "seu_veiculo": vei["seu_veiculo"]})
```

Confira que não sobrou chamada antiga: `grep -n "sugestao(item)" painel_wayap.py` → nada.

- [ ] **Step 6: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_painel_veiculos.py -q`
Expected: 23 passed. Depois `.venv/bin/python -m pytest -q` → tudo passa.

- [ ] **Step 7: Commit**

```bash
git add painel_wayap.py tests/test_painel_veiculos.py
git commit -m "$(printf 'painel: formulário com veículos da base de peças, carro principal pelo veículo escolhido e plano B pelo site\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 7: Tela — quadro "Confira se serve no seu veículo" e busca com veículo

**Files:**
- Modify: `painel_wayap.py` — CSS em `CABECALHO` (antes de `@media (max-width: 700px)`), HTML e JS em `CADASTRO`

**Interfaces:**
- Consumes: rotas `/api/veiculos/*`, `/veiculos/img/*`, `/api/catalogo/busca` com `modelo`/`ano`/`versao` e
  `confianca`, `/api/catalogo/sugestao/<id>` com os mesmos parâmetros.
- Produces (JS, usados na Tarefa 8): `esc`, `normalizar(s)`, `imgOuVazio(url)`, `faixaAnos(i, f)`, `paramsVeiculo()`.

- [ ] **Step 1: CSS — acrescentar em `CABECALHO`, antes de `@media (max-width: 700px) {`**

```css
.quadro-veiculo { flex-basis: 100%; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 14px; }
.quadro-veiculo[hidden], .veiculo-escolhido[hidden], .alterna[hidden] { display: none; }
.seletor { position: relative; flex: 1; min-width: 140px; }
.seletor input { width: 100%; font: inherit; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px;
                 background: var(--bg); color: var(--text); }
.opcoes { position: absolute; z-index: 10; left: 0; right: 0; top: 100%; margin: 2px 0 0; padding: 4px 0; list-style: none;
          max-height: 320px; overflow-y: auto; background: var(--card); border: 1px solid var(--line); border-radius: 8px;
          box-shadow: 0 6px 20px rgba(0,0,0,.15); }
.opcoes li { display: flex; gap: 8px; align-items: center; padding: 5px 10px; cursor: pointer; }
.opcoes li.ativa, .opcoes li[data-i]:hover { background: var(--accent-bg); }
.opcoes .origem { margin: 0 0 0 auto; }
.opcoes img, .arvore img, .vazio-img { width: 40px; height: 30px; object-fit: contain; flex: none; }
.veiculo-escolhido { display: flex; gap: 8px; align-items: center; font-weight: 600; }
.veiculo-escolhido img { width: 64px; height: 48px; object-fit: contain; }
.veiculo-escolhido button { padding: 5px 10px; }
.selo.conf-versao, .selo.conf-todas_versoes { background: var(--ok-bg); color: var(--ok); }
.selo.conf-algumas_versoes, .selo.conf-modelo_ano, .selo.confira { background: var(--warn-bg); color: var(--warn); }
.selo.tipo { background: var(--line); color: var(--muted); }
```

- [ ] **Step 2: HTML — em `CADASTRO`, entre o `</form>` do `formBusca` e o `</header>`**

```html
  <div id="quadroVeiculo" class="quadro-veiculo" hidden>
    <strong>Confira se serve no seu veículo</strong>
    <div class="seletor" id="selMontadora"></div>
    <div class="seletor" id="selModelo"></div>
    <div class="seletor" id="selAno"></div>
    <div class="seletor" id="selVersao"></div>
    <div id="veiculoEscolhido" class="veiculo-escolhido" hidden>
      <img alt=""><span></span>
      <button type="button" class="secundario" id="limparVeiculo">Limpar</button>
    </div>
  </div>
```

- [ ] **Step 3: JS — utilitários e seletor, logo depois de `const seletorSite = document.getElementById("site");`**

```js
const normalizar = s => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
const SELOS = {versao: "Serve nesta versão", todas_versoes: "Serve em todas as versões",
               algumas_versoes: "Serve em algumas versões", modelo_ano: "Confira a versão"};
const imgOuVazio = url => url ? `<img src="${esc(url)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">`
                               : '<span class="vazio-img"></span>';  // imagem que falha vira quadro vazio
const faixaAnos = (i, f) => i == null && f == null ? "" : i === f ? String(i) : `${i ?? ""}-${f ?? ""}`;
let filtroVeiculo = "";

async function pedirJson(url) {
  const r = await fetch(url), d = await r.json();
  if (!r.ok) throw new Error(d.erro || "Erro " + r.status);
  return d;
}

class Seletor {  // lista com imagem e filtro por digitação; opções: {id, texto, html}
  constructor(id, placeholder, aoEscolher) {
    this.el = document.getElementById(id); this.aoEscolher = aoEscolher;
    this.opcoes = []; this.visiveis = []; this.ativa = 0; this.valor = null;
    this.el.innerHTML = `<input type="text" placeholder="${esc(placeholder)}" disabled autocomplete="off"><ul class="opcoes" hidden></ul>`;
    this.input = this.el.querySelector("input"); this.lista = this.el.querySelector("ul");
    this.input.addEventListener("focus", () => { this.input.select(); this.filtrar(""); });
    this.input.addEventListener("input", () => this.filtrar(this.input.value));
    this.input.addEventListener("blur", () => setTimeout(() => this.fechar(), 150));
    this.input.addEventListener("keydown", e => this.tecla(e));
    this.lista.addEventListener("mousedown", e => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); this.escolher(this.visiveis[+li.dataset.i]); }
    });
  }
  definir(opcoes, valor = null) {
    this.opcoes = opcoes; this.valor = valor; this.input.value = valor ? valor.texto : ""; this.input.disabled = !opcoes.length;
  }
  limpar() { this.definir([]); this.lista.hidden = true; }
  filtrar(texto) {
    const t = normalizar(texto.trim());
    this.visiveis = this.opcoes.filter(o => !t || normalizar(o.texto).includes(t));
    this.ativa = 0;
    this.lista.innerHTML = this.visiveis.map((o, i) => `<li data-i="${i}">${o.html}</li>`).join("")
      || '<li class="origem">Nada encontrado</li>';
    this.lista.hidden = false; this.marcar();
  }
  marcar() {
    this.lista.querySelectorAll("li[data-i]").forEach((li, i) => li.classList.toggle("ativa", i === this.ativa));
    this.lista.querySelector("li.ativa")?.scrollIntoView({block: "nearest"});
  }
  tecla(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (this.lista.hidden) { this.filtrar(this.input.value); return; }
      this.ativa = Math.max(0, Math.min(this.visiveis.length - 1, this.ativa + (e.key === "ArrowDown" ? 1 : -1)));
      this.marcar();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (!this.lista.hidden && this.visiveis[this.ativa]) this.escolher(this.visiveis[this.ativa]);
    } else if (e.key === "Escape") {
      this.lista.hidden = true; this.input.value = this.valor ? this.valor.texto : "";
    }
  }
  escolher(o) {
    this.valor = o; this.input.value = o.texto; this.lista.hidden = true;
    Promise.resolve(this.aoEscolher(o)).catch(e => avisar(e.message));
  }
  fechar() {
    this.lista.hidden = true;
    if (document.activeElement !== this.input) this.input.value = this.valor ? this.valor.texto : "";
  }
}

async function opcoesMontadoras() {
  return (await pedirJson("/api/veiculos/montadoras")).map(m => ({id: m.id, texto: m.nome, logo_url: m.logo_url,
    html: `${imgOuVazio(m.logo_url)}<span>${esc(m.nome)}</span>`}));
}
async function opcoesModelos(id, logo) {  // modelo sem foto mostra o logo da montadora
  return (await pedirJson("/api/veiculos/modelos?montadora=" + id)).map(m => ({id: m.id, texto: m.nome, foto_url: m.foto_url,
    html: `${imgOuVazio(m.foto_url || logo)}<span>${esc(m.nome)}</span>`
          + (m.tipo !== "carro" ? `<span class="selo tipo">${esc(m.tipo)}</span>` : "")
          + `<span class="origem">${esc(faixaAnos(m.ano_inicio, m.ano_fim))}</span>`}));
}
async function opcoesAnos(id) {
  return (await pedirJson("/api/veiculos/anos?modelo=" + id)).map(a => ({id: a, texto: String(a), html: esc(a)}));
}
async function opcoesVersoes(idModelo, ano) {
  const versoes = await pedirJson(`/api/veiculos/versoes?modelo=${idModelo}&ano=${ano}`);
  return [{id: null, texto: "Todas as versões", html: "<em>Todas as versões</em>"},
          ...versoes.map(v => ({id: v.id, texto: v.nome, html: esc(v.nome)}))];
}

let veiculo = {montadora: null, modelo: null, ano: null, versao: null};
const selMontadora = new Seletor("selMontadora", "Montadora", async o => {
  veiculo = {montadora: o, modelo: null, ano: null, versao: null};
  selAno.limpar(); selVersao.limpar();
  selModelo.definir(await opcoesModelos(o.id, o.logo_url)); veiculoMudou(false); selModelo.input.focus();
});
const selModelo = new Seletor("selModelo", "Modelo", async o => {
  Object.assign(veiculo, {modelo: o, ano: null, versao: null});
  selVersao.limpar(); selAno.definir(await opcoesAnos(o.id)); veiculoMudou(false); selAno.input.focus();
});
const selAno = new Seletor("selAno", "Ano", async o => {
  Object.assign(veiculo, {ano: o, versao: null});
  selVersao.definir(await opcoesVersoes(veiculo.modelo.id, o.id)); veiculoMudou(true);
});
const selVersao = new Seletor("selVersao", "Versão (opcional)", o => {
  veiculo.versao = o.id ? o : null; veiculoMudou(true);
});

const veiculoCompleto = () => Boolean(veiculo.modelo && veiculo.ano);
function paramsVeiculo() {
  if (!veiculoCompleto()) return "";
  return `&modelo=${veiculo.modelo.id}&ano=${veiculo.ano.id}` + (veiculo.versao ? `&versao=${veiculo.versao.id}` : "");
}

function veiculoMudou(buscar) {
  try { localStorage.setItem("veiculo", JSON.stringify(veiculo)); } catch (e) {}
  const caixa = document.getElementById("veiculoEscolhido");
  caixa.hidden = !veiculoCompleto();
  if (veiculoCompleto()) {
    const img = caixa.querySelector("img"), url = veiculo.modelo.foto_url || veiculo.montadora.logo_url;
    img.onerror = () => { img.hidden = true; };
    img.hidden = !url; if (url) img.src = url;
    caixa.querySelector("span").textContent = `${veiculo.montadora.texto} ${veiculo.modelo.texto} ${veiculo.ano.texto}`
      + (veiculo.versao ? " · " + veiculo.versao.texto : "");
  }
  if (buscar) document.getElementById("formBusca").requestSubmit();
}

document.getElementById("limparVeiculo").onclick = () => {
  veiculo = {montadora: null, modelo: null, ano: null, versao: null};
  selMontadora.definir(selMontadora.opcoes); selModelo.limpar(); selAno.limpar(); selVersao.limpar();
  veiculoMudou(true);
};

async function iniciarVeiculo() {
  let montadoras;
  try { montadoras = await opcoesMontadoras(); } catch (e) { return; }  // sem base de veículos: o quadro fica escondido
  document.getElementById("quadroVeiculo").hidden = false;
  selMontadora.definir(montadoras);
  let salvo = null;
  try { salvo = JSON.parse(localStorage.getItem("veiculo") || "null"); } catch (e) {}
  if (!salvo || !salvo.montadora) return;
  try {  // o veículo guardado só volta se ainda existe na base; senão é limpo
    const montadora = montadoras.find(o => o.id === salvo.montadora.id);
    if (!montadora) throw new Error("montadora sumiu");
    selMontadora.definir(montadoras, montadora); veiculo = {montadora, modelo: null, ano: null, versao: null};
    const modelos = await opcoesModelos(montadora.id, montadora.logo_url);
    selModelo.definir(modelos);
    if (salvo.modelo) {
      const modelo = modelos.find(o => o.id === salvo.modelo.id);
      if (!modelo) throw new Error("modelo sumiu");
      selModelo.definir(modelos, modelo); veiculo.modelo = modelo;
      const anos = await opcoesAnos(modelo.id);
      selAno.definir(anos);
      if (salvo.ano) {
        const ano = anos.find(o => o.id === salvo.ano.id);
        if (!ano) throw new Error("ano sumiu");
        selAno.definir(anos, ano); veiculo.ano = ano;
        const versoes = await opcoesVersoes(modelo.id, ano.id);
        const versao = salvo.versao ? versoes.find(o => o.id === salvo.versao.id) : null;
        if (salvo.versao && !versao) throw new Error("versão sumiu");
        selVersao.definir(versoes, versao || null); veiculo.versao = versao || null;
      }
    }
  } catch (e) {
    veiculo = {montadora: null, modelo: null, ano: null, versao: null};
    selMontadora.definir(montadoras); selModelo.limpar(); selAno.limpar(); selVersao.limpar();
  }
  veiculoMudou(false);
}
```

- [ ] **Step 4: JS — busca com veículo**

Troque `seletorSite.onchange` por:

```js
seletorSite.onchange = () => {
  try { localStorage.setItem("site", seletorSite.value); } catch (e) {}
  if (document.getElementById("q").value.trim() || veiculoCompleto()) document.getElementById("formBusca").requestSubmit();
};
```

Troque o `onsubmit` do `formBusca` por:

```js
document.getElementById("formBusca").onsubmit = async e => {
  e.preventDefault();
  const q = document.getElementById("q").value.trim();
  if (!q && !veiculoCompleto()) {
    main.innerHTML = '<div class="vazio">Busque uma peça nos catálogos dos sites ou escolha um veículo.</div>'; return;
  }
  consulta = q; siteBusca = seletorSite.value; offset = 0; resultados = []; filtroVeiculo = paramsVeiculo();
  main.innerHTML = '<div class="vazio">Buscando…</div>';
  await buscarMais();
};
```

Em `buscarMais`, troque as duas linhas do `fetch` e do `offset += POR_PAGINA;` por:

```js
  const resp = await fetch(`/api/catalogo/busca?q=${encodeURIComponent(consulta)}&site=${encodeURIComponent(siteBusca)}&offset=${offset}${filtroVeiculo}`);
  const d = await resp.json();
  if (!resp.ok) {
    avisar(d.erro || "Erro na busca");
    if (filtroVeiculo && consulta && !resultados.length) { filtroVeiculo = ""; return buscarMais(); }  // base ocupada: sem veículo
    if (botao) { botao.disabled = false; botao.textContent = "Mais produtos"; }
    if (!resultados.length) main.innerHTML = `<div class="vazio">${esc(d.erro || "Erro na busca")}</div>`;
    return;
  }
  offset += POR_PAGINA;
```

E a mensagem de lista vazia passa a citar o veículo:

```js
    main.innerHTML = `<div class="vazio">Nada encontrado ${esc(onde)}${filtroVeiculo ? " para este veículo" : ""}.</div>`; return;
```

Em `linhaHtml`, a linha da descrição ganha o selo de confiança:

```js
        <div class="desc"><span class="selo site">${esc(r.site_nome)}</span>
          ${r.confianca ? `<span class="selo conf-${r.confianca}">${SELOS[r.confianca]}</span>` : ""} ${esc(r.nome)}</div>
```

Em `abrir`, o `fetch` da sugestão leva o veículo (carro principal e "Seu veículo"):

```js
  const d = await (await fetch("/api/catalogo/sugestao/" + id + (paramsVeiculo() ? "?" + paramsVeiculo().slice(1) : ""))).json();
```

Na última linha do script, depois de `carregarSites();`, acrescente:

```js
iniciarVeiculo();
```

- [ ] **Step 5: Subir o painel e conferir no navegador**

```bash
cd /mnt/nvme/PROJETOS/dffrancisco/auri-scraper
.venv/bin/python painel_wayap.py --porta 8765    # em segundo plano; lê o cadastro do Wayap (só leitura)
```

Em http://localhost:8765/cadastro:
1. O quadro aparece; Montadora abre com logos, Volkswagen/Chevrolet/Fiat no topo; digitar "chev" filtra.
2. Chevrolet → Modelo mostra fotos, faixa de anos e selinho em moto/pesado; Onix → Ano → 2019: a busca roda sozinha
   sem texto e lista peças com selos; com "pastilha" no campo, só pastilhas.
3. Versão "LT 1.4…" refaz a busca; "Todas as versões" também; "Limpar" esconde o veículo e volta ao "Busque uma peça…".
4. Recarregar a página mantém o veículo.
5. **Review Focus — veículo que sumiu:** no console do navegador,
   `localStorage.setItem("veiculo", JSON.stringify({montadora: {id: 1, texto: "x"}, modelo: {id: 999999, texto: "y"}, ano: null, versao: null}))`
   e recarregue: o quadro aparece limpo, sem erro no console.
6. Escolher um veículo e clicar Cadastrar num item: o carro principal sugerido é o do veículo (se a sociedade tiver).
7. Sem veículo, buscar "GC5045": resultado igual ao de antes da mudança.

Anote o que não bateu e corrija antes do commit.

- [ ] **Step 6: Commit**

```bash
git add painel_wayap.py
git commit -m "$(printf 'painel: quadro \"Confira se serve no seu veículo\" na aba Cadastrar, com selos de confiança na busca\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 8: Tela — veículos compatíveis no formulário (lista, árvore e seu veículo)

**Files:**
- Modify: `painel_wayap.py` — CSS em `CABECALHO`, HTML do formulário e JS em `CADASTRO`

**Interfaces:**
- Consumes: `veiculos_fonte`, `veiculos_lista`, `veiculos_arvore`, `seu_veiculo` da sugestão (Tarefa 6);
  `esc`, `normalizar`, `imgOuVazio` (Tarefa 7).

- [ ] **Step 1: CSS — acrescentar em `CABECALHO`, antes de `@media (max-width: 700px) {`**

```css
.vlista { list-style: none; margin: 0 0 8px; padding: 0; max-height: 260px; overflow-y: auto; border: 1px solid var(--line);
          border-radius: 8px; }
.vlista li { padding: 5px 10px; border-bottom: 1px solid var(--line); font-size: 14px; }
.arvore { border: 1px solid var(--line); border-radius: 8px; margin-bottom: 8px; max-height: 320px; overflow-y: auto; }
.arvore .no { display: flex; gap: 8px; align-items: center; width: 100%; text-align: left; font-weight: 400; padding: 6px 10px;
              border: 0; border-bottom: 1px solid var(--line); border-radius: 0; background: transparent; color: var(--text); }
.arvore button.no { cursor: pointer; } .arvore button.no:hover { background: var(--accent-bg); }
.arvore .no.voltar { font-weight: 600; }
.arvore .seta { margin-left: auto; color: var(--muted); }
.arvore input { margin: 6px 10px; width: calc(100% - 20px); }
.arvore .aviso-no { padding: 6px 10px; color: var(--warn); font-size: 14px; }
.seu-veiculo { padding: 8px 12px; border-radius: 8px; margin-bottom: 8px; font-weight: 600; background: var(--warn-bg);
               color: var(--warn); }
.seu-veiculo.serve { background: var(--ok-bg); color: var(--ok); }
.seu-veiculo.nao { background: var(--bad-bg); color: var(--bad); }
.alterna { display: inline-flex; margin-left: 8px; vertical-align: middle; }
.alterna button { padding: 3px 10px; font-size: 13px; border-radius: 0; }
.alterna button.ativa { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }
```

- [ ] **Step 2: HTML — trocar o cabeçalho do bloco de veículos do formulário**

Troque:

```html
    <p style="margin:6px 0 6px;font-weight:600">Veículos compatíveis (<span id="siteVeiculos"></span>) →
      carros de venda com complemento <span class="origem" id="resumoVeiculos"></span></p>
    <div id="veiculosForm"></div>
```

por:

```html
    <p style="margin:6px 0 6px;font-weight:600">Veículos compatíveis (<span id="siteVeiculos"></span>)
      <span class="alterna" id="alternaVista" hidden><button type="button" class="secundario" data-vista="lista">Lista</button><button
        type="button" class="secundario" data-vista="arvore">Árvore</button></span></p>
    <div id="seuVeiculo" class="seu-veiculo" hidden></div>
    <div id="vistaVeiculos"></div>
    <p style="margin:10px 0 6px;font-weight:600">Carros de venda com complemento <span class="origem" id="resumoVeiculos"></span></p>
    <div id="veiculosForm"></div>
```

- [ ] **Step 3: JS — vistas Lista e Árvore, logo antes de `async function abrir(id) {`**

```js
let dadosVeiculos = null, arvoreNav = {m: null, mo: null, a: null, filtro: ""}, vistaVeiculos = "lista";
try { vistaVeiculos = localStorage.getItem("vistaVeiculos") || "lista"; } catch (e) {}

const seloAno = a => a.todas ? ' <span class="selo conf-todas_versoes">todas as versões</span>'
                   : a.confira && !a.versoes.length ? ' <span class="selo confira">confira a versão</span>' : "";

function htmlLista(lista) {
  return `<ul class="vlista">${lista.map(l => `<li>${esc(l.texto)}`
    + (l.selo ? ` <span class="selo ${l.selo === "confira a versão" ? "confira" : "conf-todas_versoes"}">${esc(l.selo)}</span>` : "")
    + (l.tipo !== "carro" ? ` <span class="selo tipo">${esc(l.tipo)}</span>` : "") + "</li>").join("")}</ul>`;
}

function htmlArvore(arvore) {  // montadora -> modelos -> anos -> versões, um nível por vez, como na KarHub
  const n = arvoreNav;
  const no = (acao, conteudo) => `<button type="button" class="no" data-acao="${acao}">${conteudo}<span class="seta">→</span></button>`;
  const voltar = conteudo => `<button type="button" class="no voltar" data-acao="voltar">← ${conteudo}</button>`;
  if (n.m == null)
    return `<div class="arvore">${arvore.map((m, i) => no(`m:${i}`,
      `${imgOuVazio(m.logo_url)}<span>${esc(m.nome)}</span><span class="origem">${m.modelos.length} modelo(s)</span>`)).join("")}</div>`;
  const m = arvore[n.m];
  if (n.mo == null) {
    const t = normalizar(n.filtro);
    return `<div class="arvore">${voltar(`${imgOuVazio(m.logo_url)}<span>${esc(m.nome)}</span>`)}
      <input type="text" id="filtroModelos" placeholder="Pesquisar modelos" value="${esc(n.filtro)}" autocomplete="off">
      ${m.modelos.map((mo, i) => [mo, i]).filter(([mo]) => !t || normalizar(mo.nome).includes(t)).map(([mo, i]) => no(`mo:${i}`,
        `${imgOuVazio(mo.foto_url || m.logo_url)}<span>${esc(mo.nome)}</span>`
        + (mo.tipo !== "carro" ? `<span class="selo tipo">${esc(mo.tipo)}</span>` : "")
        + `<span class="origem">${esc(mo.faixa)}</span>`)).join("")}</div>`;
  }
  const mo = m.modelos[n.mo];
  if (n.a == null)
    return `<div class="arvore">${voltar(`${imgOuVazio(mo.foto_url || m.logo_url)}<span>${esc(m.nome)} ${esc(mo.nome)}</span>`)}
      ${mo.anos.map((a, i) => no(`a:${i}`, `<span>${a.ano}</span>${seloAno(a)}`)).join("")
        || '<div class="aviso-no">Confira a versão: a base não informa os anos.</div>'}</div>`;
  const a = mo.anos[n.a];
  return `<div class="arvore">${voltar(`${imgOuVazio(mo.foto_url || m.logo_url)}<span>${esc(m.nome)} ${esc(mo.nome)} ${a.ano}</span>${seloAno(a)}`)}
    ${a.confira && !a.versoes.length ? '<div class="aviso-no">Confira a versão: a base não diz quais versões.</div>' : ""}
    ${a.versoes.map(v => `<div class="no">${esc(v)}</div>`).join("")}</div>`;
}

function desenharVeiculos() {
  const d = dadosVeiculos, alvo = document.getElementById("vistaVeiculos"), daBase = d.veiculos_fonte === "base";
  document.getElementById("alternaVista").hidden = !daBase;
  document.querySelectorAll("#alternaVista button").forEach(b => b.classList.toggle("ativa", b.dataset.vista === vistaVeiculos));
  alvo.innerHTML = !daBase ? "" : vistaVeiculos === "arvore" ? htmlArvore(d.veiculos_arvore) : htmlLista(d.veiculos_lista);
}

const vistaEl = document.getElementById("vistaVeiculos");
vistaEl.addEventListener("click", e => {
  const b = e.target.closest("[data-acao]"); if (!b) return;
  const [tipo, i] = b.dataset.acao.split(":"), n = arvoreNav;
  if (tipo === "voltar") { if (n.a != null) n.a = null; else if (n.mo != null) n.mo = null; else { n.m = null; n.filtro = ""; } }
  else if (tipo === "m") n.m = +i; else if (tipo === "mo") n.mo = +i; else if (tipo === "a") n.a = +i;
  desenharVeiculos();
});
vistaEl.addEventListener("input", e => {
  if (e.target.id !== "filtroModelos") return;
  arvoreNav.filtro = e.target.value; const pos = e.target.selectionStart;
  desenharVeiculos();
  const campo = document.getElementById("filtroModelos"); campo.focus(); campo.setSelectionRange(pos, pos);
});
vistaEl.addEventListener("keydown", e => { if (e.key === "Enter") e.preventDefault(); });  // não cadastrar pelo Enter do filtro
document.getElementById("alternaVista").addEventListener("click", e => {
  const b = e.target.closest("button[data-vista]"); if (!b) return;
  vistaVeiculos = b.dataset.vista;
  try { localStorage.setItem("vistaVeiculos", vistaVeiculos); } catch (err) {}
  desenharVeiculos();
});
```

- [ ] **Step 4: JS — `abrir` desenha o bloco**

Em `abrir`, apague a linha `document.getElementById("siteVeiculos").textContent = itemAtual.site_nome;`.

Troque o trecho que começa em `document.getElementById("resumoVeiculos").textContent = c.veiculos.length` e termina no
`|| \`<span class="origem">${esc(itemAtual.site_nome)} não informa veículos compatíveis para esta peça.</span>\`;` por:

```js
  dadosVeiculos = d;
  arvoreNav = {m: d.veiculos_arvore.length === 1 ? 0 : null, mo: null, a: null, filtro: ""};
  const daBase = d.veiculos_fonte === "base", unidade = daBase ? "linha(s) da base" : "versões";
  document.getElementById("siteVeiculos").textContent = daBase ? "base de peças" : itemAtual.site_nome;
  const seu = document.getElementById("seuVeiculo");
  seu.hidden = !d.seu_veiculo;
  if (d.seu_veiculo) {
    const conf = d.seu_veiculo.confianca;
    seu.className = "seu-veiculo" + (conf === "versao" || conf === "todas_versoes" ? " serve" : conf ? "" : " nao");
    seu.textContent = `Seu veículo: ${d.seu_veiculo.veiculo} — ${d.seu_veiculo.veredito}`;
  }
  desenharVeiculos();
  document.getElementById("resumoVeiculos").textContent = c.veiculos.length
    ? `(${c.veiculos.length} modelo(s), ${c.veiculos.reduce((t, v) => t + v.versoes, 0)} ${unidade})` : "";
  document.getElementById("veiculosForm").innerHTML = c.veiculos.map(v => `
    <div class="veiculo">
      <input type="checkbox" class="vIncluir"${v.id_carro ? " checked" : ""} title="Incluir este carro no produto">
      <select class="vCarro"><option value="">— escolher carro —</option>${opcoes(d.carros, "id_carro", "descricao", v.id_carro)}</select>
      <input type="text" class="vCompl" maxlength="1000" value="${esc(v.complemento)}" title="Complemento do carro">
      <span class="origem">${esc(v.modelo_origem)} · ${v.versoes} ${unidade}</span>
    </div>`).join("") || `<span class="origem">${esc(daBase ? "A base" : itemAtual.site_nome)} não informa veículos compatíveis para esta peça.</span>`;
```

- [ ] **Step 5: Conferir no navegador (painel da Tarefa 7 rodando; reinicie-o para pegar o código novo)**

1. Buscar "GDB2031" (pastilha TRW da KarHub) e abrir: título "Veículos compatíveis (base de peças)", Lista com linhas
   `BMW 116I ...` e selos; Árvore: BMW (logo) → modelos com campo de busca → anos → versões; "←" volta um nível.
2. Comparar com "Veículos Compatíveis" da página da KarHub dessa peça
   (https://www.karhub.com.br/p/jogo-pastilhas-freio-dianteira-antirruido-cotec-trw-gdb2031-7950373): mesmos modelos e anos.
3. Com veículo escolhido (BMW 116i 2015), o topo mostra "Seu veículo: … — Serve" em verde.
4. Enter dentro do "Pesquisar modelos" não cadastra.
5. Um item da CarBlue sem peça no helper: título com o nome do site, sem alternância, carros de venda como antes.
6. Carros de venda e complemento do produto preenchidos; resumo "(N modelo(s), M linha(s) da base)".
7. Não clicar em "Cadastrar no Wayap" (grava no Wayap): só se o dono pedir.

- [ ] **Step 6: Commit**

```bash
git add painel_wayap.py
git commit -m "$(printf 'painel: veículos compatíveis da base no formulário (lista, árvore e seu veículo)\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

---

### Task 9: README e verificação final

**Files:**
- Modify: `README.md` (seção "Painel", item "Cadastrar dos sites")

- [ ] **Step 1: README — trocar a frase dos veículos**

No item **Cadastrar dos sites**, troque só a frase que começa em "Os veículos compatíveis vêm da página da KarHub;" e
termina em `"Gol, Parati - 1998 1999"...).` (o resto do item fica igual) por:

```markdown
  **Busca por veículo:** o quadro "Confira se serve no seu veículo" (montadora → modelo → ano →
  versão opcional, com logos e fotos do helper) filtra a busca pelas peças que servem, com selo de confiança
  ("Serve nesta versão", "Confira a versão"...); o veículo fica guardado no navegador. **Veículos compatíveis:** vêm do
  `helper.sqlite` (lista e árvore, como na KarHub) quando o anúncio chega a uma peça do helper com veículos, e deles
  saem os carros de venda e o complemento do produto; sem isso, vêm da página da KarHub ou da aplicação escrita no
  catálogo ("GOL G2 96 97 98", "Fiat: Palio 01 a 12"...). O painel só lê o `helper.sqlite`: rode `helper.py veiculos`
  com o painel fechado. Spec: `docs/superpowers/specs/2026-10-06-painel-veiculos-design.md`.
```

- [ ] **Step 2: Verificação final no navegador, como a seção 9 da spec**

Com o painel rodando:
1. Chevrolet Tracker 2021, versão "4x2 Aut. 1.2 12v L3 Turbo", texto "pastilha" e depois "tambor".
2. Volkswagen Gol 2010, os mesmos textos.
3. Fiat Palio 2005, os mesmos textos.

Para cada um, abrir a página de categoria da KarHub filtrada pelo mesmo veículo e conferir que as peças que ela
mostra aparecem com "Serve nesta versão" ou "Serve em todas as versões". Abrir um item da Universal que seja a mesma
peça de um da KarHub (mesmo código) e conferir que mostra os mesmos veículos. Anotar tempos de resposta da busca só
com o veículo (Gol 2010) — esperado abaixo de 2 s.

- [ ] **Step 3: Suíte inteira**

Run: `.venv/bin/python -m pytest -q`
Expected: tudo passa.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "$(printf 'README: busca por veículo e veículos compatíveis da base no painel\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')"
```

- [ ] **Step 5: Fechar o branch**

Use superpowers:finishing-a-development-branch para levar `painel-veiculos` para a `main`.
