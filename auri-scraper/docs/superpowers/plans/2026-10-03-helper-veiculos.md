# Helper: veículos — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coletar do KarHub a árvore montadora → modelo → ano → versão (só carros e utilitários), com logos, fotos de modelo e a compatibilidade produto → veículo; ligar às peças do helper e publicar no Postgres `helper` e em `/home/wayap/helper/veiculos/`, com as consultas do contrato para o filtro "Peças para o veículo" do Wayap.

**Architecture:** Um coletor na raiz (`catalogo_karhub_veiculos.py`) só faz rede e grava arquivos brutos em `veiculos/`. O pacote `helper/` ganha módulos pequenos: `montadoras.py` (nome canônico), `veiculo_tipo.py` (carro, moto ou pesado), `veiculos.py` (árvore no SQLite), `veiculos_fotos.py` (WebP e PNG), `veiculos_ligar.py` (`peca_veiculo` e fechamento), `veiculos_relatorio.py`; `consulta.py`, `banco.py`, `publicar.py` e `cli.py` recebem as partes novas. Tudo é preparado no `helper.sqlite` e publicado por diferença, arquivos antes do banco, sem nunca escrever em tabela do Wayap.

**Tech Stack:** Python 3.12 (`.venv`), sqlite3, Pillow ≥ 11.3 (lê AVIF), Scrapling `Fetcher` (KarHub, atrás do Cloudflare), requests (FIPE), psycopg2 (`execute_batch`, `copy_expert`), pytest, rsync.

**Spec:** `docs/superpowers/specs/2026-10-03-helper-veiculos-design.md` (complementa `docs/superpowers/specs/2026-10-02-helper-design.md`).

## Global Constraints

- **O helper não grava em nenhuma tabela nem pasta do Wayap.** No Postgres, só `SELECT` em `montadoras`; nada de `INSERT/UPDATE/DELETE/ALTER` em `montadoras`, `placas_detalhes` ou outra tabela que não seja do helper. No servidor, os arquivos de veículos vão só para `/home/wayap/helper/veiculos/` (nunca `/home/wayap/helper/montadoras/`).
- Tabelas novas com prefixo `veiculo_` (mais `peca_veiculo` e `peca_veiculo_estado`), porque o banco `helper` é compartilhado com tabelas do Wayap.
- Só **carros e utilitários** entram na árvore (regras da spec, seção 5.1). Na dúvida, entra como carro.
- Ids (`id_veiculo_montadora`, `id_modelo`, `id_versao`) atribuídos localmente, estáveis por nome canônico, nunca reaproveitados. Montadora, modelo e versão nunca são apagados: viram `ativo = 0`.
- Arquivos (rsync) antes das linhas do banco. Publicar duas vezes seguidas grava zero linhas e envia zero arquivos.
- Nenhuma consulta do contrato expõe `origem`, `veiculo_fonte` ou id do KarHub. `veiculo_fonte` não existe no Postgres.
- KarHub: `Fetcher.get(url, stealthy_headers=True)` do Scrapling (requests puro leva 403), uma chamada por vez, pausa de 0,3 s, esperas 5, 15, 30, 60 s; 403/430/captcha = bloqueio (espera × 4) e, esgotado, código de saída 2. FIPE: `requests`, pausa de 1 s.
- Código de produto é string com zero à esquerda (regra do helper): nada aqui normaliza `codigo`.
- Idioma de código, mensagens, docstrings e commits: português. Rodar com `.venv/bin/python` e `.venv/bin/pytest`.
- **A árvore de trabalho tem mudanças do Francisco ainda sem commit** (`.gitignore`, `README.md`, `catalogo_para_pecas.py`, `helper/fotos.py`, `helper_marcas.csv`, `tests/test_fotos.py`, `wayap_fotos.py` e arquivos novos como `catalogo_altese.py`). Cada commit deste plano faz `git add` só dos arquivos da própria tarefa, pelo nome. Nunca `git add -A`, `git add .` ou `git commit -a`.
- Commits terminam com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Coleta interrompida no meio** (queda, Ctrl-C): a última linha do `.jsonl` pode ficar cortada; a próxima rodada corta a linha, não refaz o que já está gravado e não grava modelo pela metade. Teste na Task 3.
2. **Imagem baixada que não é imagem** (HTML de erro do Cloudflare, arquivo truncado): o modelo fica sem foto (ou herda), sem derrubar o `veiculos`. Teste na Task 7.
3. **Mesma peça com dois anúncios do KarHub** (variante `?Lado=...` ou duas peças fundidas): os ids de veículo dos dois se somam antes de agrupar, sem linhas duplicadas. Teste na Task 8.
4. **Queda no meio da carga de `peca_veiculo`** (milhões de linhas): os lotes já confirmados ficam, e a rodada seguinte grava só o resto. Teste na Task 13.
5. **Veículo digitado do jeito do usuário** no `pecas-do-veiculo` (`vw gol`, minúsculas, versão sem acento): acha o modelo pelo nome canônico e pelos apelidos. Teste na Task 11.

## Estrutura de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `catalogo_karhub_veiculos.py` (novo) | Coletor: `fipe`, `arvore`, `compat`; cliente HTTP com novas tentativas |
| `veiculos/.gitignore` (novo) | Ignora tudo que o coletor grava |
| `helper/montadoras.py` (novo) | Nome canônico de montadora e casamento com a `montadoras` do Wayap |
| `helper_montadoras.csv` (novo) | Apelidos editáveis (`apelido;nome`) |
| `helper/veiculo_tipo.py` (novo) | Tipo do modelo: ajuste, FIPE, versões, nome, padrão |
| `helper_veiculos_tipo.csv` (novo) | Ajustes do dono (`montadora;modelo;tipo`) |
| `helper/banco.py` | Tabelas locais de veículos; `gravar_meta`, `ler_meta`, `agora`; `VERSAO_ESQUEMA = 2` |
| `helper/veiculos.py` (novo) | Lê `karhub_arvore.jsonl` e grava a árvore com ids estáveis |
| `helper/veiculos_fotos.py` (novo) | Foto WebP, logo PNG, imagens próprias, herança por prefixo |
| `helper_fotos_veiculos/.gitignore` (novo) | Ignora as imagens geradas e as próprias |
| `helper/veiculos_ligar.py` (novo) | Agrupamento, nível versão, nível modelo, `qtd_pecas`, hashes |
| `helper/veiculos_relatorio.py` (novo) | `veiculos.md` e planilha de tipos |
| `helper/consulta.py` | `ids_por_veiculo`, `pecas_por_veiculo` (SQLite) |
| `helper/publicar.py` | DDL, views e funções de veículos; `publicar_veiculos`; `veiculos_preparados`; `comando_rsync(excluir=...)` |
| `helper/cli.py` | `veiculos`, `pecas-do-veiculo`; `preparar` grava `preparado_em`; `publicar` publica veículos |
| `requirements.txt` | `pillow>=11.3` |
| `README.md` | Seção de veículos |
| `tests/test_montadoras.py`, `tests/test_veiculo_tipo.py`, `tests/test_catalogo_karhub_veiculos.py`, `tests/test_veiculos.py`, `tests/test_veiculos_fotos.py`, `tests/test_veiculos_ligar.py` (novos); `tests/test_banco.py`, `tests/test_consulta.py`, `tests/test_cli.py`, `tests/test_publicar.py` | Testes |

---

### Task 1: Montadoras canônicas

**Files:**
- Create: `helper/montadoras.py`
- Create: `helper_montadoras.csv`
- Test: `tests/test_montadoras.py`

**Interfaces:**
- Consumes: `wayap_fotos.n_marca(s) -> str` (só letras e números, maiúsculas), `wayap_fotos.sem_acento(s) -> str`.
- Produces:
  - `nome_canonico(nome: str | None) -> str` — maiúsculas, sem acento, espaços simples (também usado para nomes de modelo e versão).
  - `class Montadoras(apelidos: dict[str, str] | None)`; `Montadoras.carregar(caminho=ARQUIVO_PADRAO) -> Montadoras`; `.canonica(nome) -> str | None`; `.chaves(nome) -> set[str]`.
  - `casar_wayap(nome: str, montadoras_wayap: list[tuple[int, str]]) -> int | None`.

- [ ] **Step 1: Escrever os testes**

`tests/test_montadoras.py`:

```python
from helper.montadoras import Montadoras, casar_wayap, nome_canonico


def _montadoras(tmp_path):
    arq = tmp_path / "m.csv"
    arq.write_text("apelido;nome\nKIA;KIA MOTORS\nMERCEDES BENZ;MERCEDES-BENZ\nGM;CHEVROLET\nBMW BMW;BMW\n", encoding="utf-8")
    return Montadoras.carregar(arq)


def test_nome_canonico():
    assert nome_canonico("  Citroën  C4 ") == "CITROEN C4"
    assert nome_canonico(None) == ""


def test_canonica_usa_apelidos_e_normaliza(tmp_path):
    m = _montadoras(tmp_path)
    assert m.canonica("Kia") == "KIA MOTORS"
    assert m.canonica("Mercedes Benz") == "MERCEDES-BENZ" and m.canonica("MERCEDES-BENZ") == "MERCEDES-BENZ"
    assert m.canonica("gm") == "CHEVROLET" and m.canonica("BMW BMW") == "BMW"
    assert m.canonica("Caoa Chery") == "CAOA CHERY"  # sem apelido: maiúsculas sem acento
    assert m.canonica("") is None and m.canonica(None) is None


def test_chaves_do_nome_como_veio_e_canonico(tmp_path):
    assert _montadoras(tmp_path).chaves("Kia") == {"KIA", "KIAMOTORS"}
    assert _montadoras(tmp_path).chaves("") == set()


def test_casar_wayap_por_letras_e_numeros():
    wayap = [(43, "MERCEDES-BENZ"), (34, "KIA MOTORS"), (11, "CHEVROLET")]
    assert casar_wayap("MERCEDES BENZ", wayap) == 43
    assert casar_wayap("KIA MOTORS", wayap) == 34
    assert casar_wayap("CAOA CHERY", wayap) is None
    assert casar_wayap("", wayap) is None


def test_arquivo_do_repositorio_tem_os_apelidos_da_spec():
    m = Montadoras.carregar()
    for apelido, nome in [("KIA", "KIA MOTORS"), ("JAC", "JAC MOTORS"), ("ASIA", "ASIA MOTORS"),
                          ("MERCEDES BENZ", "MERCEDES-BENZ"), ("GM", "CHEVROLET"), ("VW", "VOLKSWAGEN"), ("BMW BMW", "BMW")]:
        assert m.canonica(apelido) == nome
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_montadoras.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'helper.montadoras'`

- [ ] **Step 3: Implementar**

`helper_montadoras.csv`:

```
apelido;nome
KIA;KIA MOTORS
JAC;JAC MOTORS
ASIA;ASIA MOTORS
MERCEDES BENZ;MERCEDES-BENZ
MERCEDES;MERCEDES-BENZ
GM;CHEVROLET
GM CHEVROLET;CHEVROLET
VW;VOLKSWAGEN
VW VOLKSWAGEN;VOLKSWAGEN
BMW BMW;BMW
```

`helper/montadoras.py`:

```python
"""Nome canônico de montadora (helper_montadoras.csv, editável) e casamento com a tabela montadoras do Wayap.
Spec de veículos, seção 5.2: dois nomes são a mesma montadora quando ficam iguais só com letras e números."""
import csv
from pathlib import Path

from wayap_fotos import n_marca, sem_acento

ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / "helper_montadoras.csv"


def nome_canonico(nome):
    return " ".join(sem_acento(nome or "").upper().split())


class Montadoras:
    def __init__(self, apelidos=None):
        self.apelidos = apelidos or {}  # n_marca(apelido) -> nome canônico

    @classmethod
    def carregar(cls, caminho=ARQUIVO_PADRAO):
        apelidos = {}
        with Path(caminho).open(encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f, delimiter=";"):
                apelidos[n_marca(linha["apelido"])] = nome_canonico(linha["nome"])
        return cls(apelidos)

    def canonica(self, nome):
        """'Mercedes Benz' -> 'MERCEDES-BENZ' (pelo apelido); sem apelido, maiúsculas sem acento; vazio -> None."""
        chave = n_marca(nome)
        if not chave:
            return None
        return self.apelidos.get(chave, nome_canonico(nome))

    def chaves(self, nome):
        """Formas comparáveis do nome como veio e do canônico, para casar com listas de terceiros (FIPE)."""
        return {c for c in (n_marca(nome), n_marca(self.canonica(nome) or "")) if c}


def casar_wayap(nome, montadoras_wayap):
    """montadoras_wayap: [(id_montadora, descricao)] lidos da tabela do Wayap. Só leitura."""
    chave = n_marca(nome)
    if not chave:
        return None
    for id_montadora, descricao in montadoras_wayap:
        if n_marca(descricao) == chave:
            return id_montadora
    return None
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_montadoras.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Commit**

```bash
git add helper/montadoras.py helper_montadoras.csv tests/test_montadoras.py
git commit -m "helper: montadoras canônicas e casamento com a montadoras do Wayap

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Tipo do modelo (carro, moto, pesado)

**Files:**
- Create: `helper/veiculo_tipo.py`
- Create: `helper_veiculos_tipo.csv`
- Test: `tests/test_veiculo_tipo.py`

**Interfaces:**
- Consumes: `wayap_fotos.n_marca`, `wayap_fotos.sem_acento`.
- Produces:
  - `normalizar(texto) -> str` — maiúsculas, sem acento, só letras/números/espaços.
  - `carregar_ajustes(caminho=AJUSTES_PADRAO) -> dict[tuple[str, str], str]` — chave `(n_marca(montadora), normalizar(modelo))`.
  - `chaves_marca_fipe(nome) -> set[str]`.
  - `indexar_fipe(fipe: dict) -> dict[str, dict[str, list[str]]]` — `{chave_marca: {lista: [nomes normalizados]}}`.
  - `classificar(chaves_montadora: set[str], modelo: str, versoes: list[str], indice_fipe, ajustes) -> tuple[str, str]` — `(tipo, motivo)`, tipo em `carro|moto|pesado`, motivo em `ajuste|fipe|versao|nome|padrao`.

- [ ] **Step 1: Escrever os testes**

`tests/test_veiculo_tipo.py`:

```python
import pytest

from helper.veiculo_tipo import carregar_ajustes, chaves_marca_fipe, classificar, indexar_fipe, normalizar

# nomes no formato da API da FIPE (parallelum)
FIPE = {
    "carros": {"GM - Chevrolet": ["Tracker LT 1.0 Turbo 12V Flex Aut.", "ONIX HATCH LT 1.0 12V Flex 5p Mec."],
               "Honda": ["Civic Sedan EXL 2.0 Flex 16V Aut.4p"], "Agrale": ["MARRUÁ AM 200 2.8 CS TDI Diesel"],
               "Mercedes-Benz": ["A 200 Style 1.6 Turbo 16V"]},
    "motos": {"HONDA": ["CG 160 FAN"]},
    "caminhoes": {"Mercedes-Benz": ["L-1620 6x2 2p (diesel)"], "Agrale": ["MARRUÁ AM 200 CD 4x4 TDI Diesel"]},
}
IDX = indexar_fipe(FIPE)


def test_normalizar_e_chaves_da_marca_fipe():
    assert normalizar("Cr-v  EXL") == "CR V EXL"
    assert chaves_marca_fipe("GM - Chevrolet") == {"GMCHEVROLET", "GM", "CHEVROLET"}
    assert chaves_marca_fipe("Caoa Chery/Chery") == {"CAOACHERYCHERY", "CAOACHERY", "CHERY"}
    assert chaves_marca_fipe("Mercedes-Benz") == {"MERCEDESBENZ"}


def test_fipe_decide_quando_conhece_o_modelo():
    assert classificar({"CHEVROLET"}, "Tracker", [], IDX, {}) == ("carro", "fipe")
    assert classificar({"HONDA"}, "Civic", [], IDX, {}) == ("carro", "fipe")
    assert classificar({"HONDA"}, "CG 160", [], IDX, {}) == ("moto", "fipe")
    assert classificar({"MERCEDESBENZ"}, "L 1620", [], IDX, {}) == ("pesado", "fipe")
    # em "carros" e em "caminhoes": na dúvida, carro
    assert classificar({"AGRALE"}, "Marrua", [], IDX, {}) == ("carro", "fipe")
    # prefixo só em fronteira de palavra: "ONI" não casa "ONIX HATCH..."
    assert classificar({"CHEVROLET"}, "Oni", [], IDX, {}) == ("carro", "padrao")


def test_versoes_decidem_quando_a_fipe_nao_conhece():
    assert classificar({"HONDA"}, "Biz 100", ["Ks 100cc (6,4 Cv)"], IDX, {}) == ("moto", "versao")
    assert classificar({"MERCEDESBENZ"}, "1214 K", ["4x2 6.0 12v L6 E 1 P 3"], IDX, {}) == ("pesado", "versao")
    assert classificar({"VOLVO"}, "B 12", ["R 6x2 12.0 24v L6 Turbo E 3 P 5 (420 Cv)"], IDX, {}) == ("pesado", "versao")
    assert classificar({"CHEVROLET"}, "D 6000", ["4x2 4.0 8v E 0 P 2"], IDX, {}) == ("pesado", "versao")
    # utilitário diesel leve: fase P com motor pequeno continua carro
    assert classificar({"IVECO"}, "Daily 30 130", ["Furgão 4x2 2.3 16v Turbo E 5 P 6"], IDX, {}) == ("carro", "padrao")
    assert classificar({"HYUNDAI"}, "Hr Hd", ["Cabine Simples 2.5 8v Turbo"], IDX, {}) == ("carro", "padrao")
    # portas ("4p") não são fase de emissão
    assert classificar({"CHEVROLET"}, "Astra Hatch", ["Advantage 4p Aut. 2.0 8v Flex (133 140 Cv)"], IDX, {}) == ("carro", "padrao")


def test_nome_de_onibus():
    assert classificar({"IVECO"}, "Bus 170 S28", [], IDX, {}) == ("pesado", "nome")


def test_ajuste_do_dono_vence_tudo(tmp_path):
    arq = tmp_path / "t.csv"
    arq.write_text("montadora;modelo;tipo\nIveco;Daily 30 130;pesado\nHonda;Civic;moto\n", encoding="utf-8")
    aj = carregar_ajustes(arq)
    assert classificar({"IVECO"}, "Daily 30-130", ["Furgão 4x2 2.3"], IDX, aj) == ("pesado", "ajuste")
    assert classificar({"HONDA"}, "Civic", [], IDX, aj) == ("moto", "ajuste")
    assert carregar_ajustes(tmp_path / "nao_existe.csv") == {}


def test_ajuste_com_tipo_invalido_avisa(tmp_path):
    arq = tmp_path / "t.csv"
    arq.write_text("montadora;modelo;tipo\nIveco;Daily;caminhao\n", encoding="utf-8")
    with pytest.raises(ValueError, match="caminhao"):
        carregar_ajustes(arq)


def test_arquivo_de_ajustes_do_repositorio_carrega():
    assert isinstance(carregar_ajustes(), dict)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_veiculo_tipo.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'helper.veiculo_tipo'`

- [ ] **Step 3: Implementar**

`helper_veiculos_tipo.csv` (só o cabeçalho; o dono preenche depois de ver a planilha de tipos):

```
montadora;modelo;tipo
```

`helper/veiculo_tipo.py`:

```python
"""Tipo do modelo de veículo (carro, moto, pesado) — spec de veículos, seção 5.1.
Ordem: ajuste do dono, FIPE, versões, nome, padrão (carro). Só 'carro' entra na árvore."""
import csv
import re
from pathlib import Path

from wayap_fotos import n_marca, sem_acento

AJUSTES_PADRAO = Path(__file__).resolve().parents[1] / "helper_veiculos_tipo.csv"
TIPOS = {"carro", "moto", "pesado"}
CC_RE = re.compile(r"\b\d{2,4}\s?cc\b", re.I)          # moto: "Ks 100cc"
EIXOS_RE = re.compile(r"\b[68]x[24]\b", re.I)            # caminhão/ônibus: 6x2, 6x4, 8x2, 8x4
FASE_P_RE = re.compile(r"\bP\s?\d\b")                     # fase Proconve de pesados ("E 1 P 3"); "4p" (portas) não casa
CILINDRADA_RE = re.compile(r"\b(\d{1,2})[.,](\d)\b")
NOME_PESADO = {"BUS", "ONIBUS", "MICRO", "RODOVIARIO", "URBANO"}


def normalizar(texto):
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sem_acento(texto or "").upper()).split())


def carregar_ajustes(caminho=AJUSTES_PADRAO):
    caminho = Path(caminho)
    if not caminho.exists():
        return {}
    ajustes = {}
    with caminho.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            tipo = (linha.get("tipo") or "").strip().lower()
            if tipo not in TIPOS:
                raise ValueError(f"helper_veiculos_tipo.csv: tipo '{tipo}' inválido em {linha.get('montadora')} {linha.get('modelo')}"
                                 f" (use carro, moto ou pesado)")
            ajustes[(n_marca(linha["montadora"]), normalizar(linha["modelo"]))] = tipo
    return ajustes


def chaves_marca_fipe(nome):
    """'GM - Chevrolet' -> {'GMCHEVROLET', 'GM', 'CHEVROLET'}; 'Caoa Chery/Chery' -> {..., 'CAOACHERY', 'CHERY'}."""
    partes = [nome] + re.split(r"\s+-\s+|/", nome)
    return {n_marca(p) for p in partes if n_marca(p)}


def indexar_fipe(fipe):
    """fipe: {'carros': {marca: [modelos]}, 'motos': ..., 'caminhoes': ...} -> {chave_marca: {lista: [nomes normalizados]}}."""
    indice = {}
    for lista, marcas in fipe.items():
        for nome_marca, modelos in marcas.items():
            nomes = [normalizar(m) for m in modelos]
            for chave in chaves_marca_fipe(nome_marca):
                indice.setdefault(chave, {}).setdefault(lista, []).extend(nomes)
    return indice


def _cilindrada(versao):
    return max((float(f"{a}.{b}") for a, b in CILINDRADA_RE.findall(versao)), default=0.0)


def classificar(chaves_montadora, modelo, versoes, indice_fipe, ajustes):
    alvo = normalizar(modelo)
    for chave in chaves_montadora:
        if (chave, alvo) in ajustes:
            return ajustes[(chave, alvo)], "ajuste"
    listas = set()
    for chave in chaves_montadora:
        for lista, nomes in indice_fipe.get(chave, {}).items():
            if any(n == alvo or n.startswith(alvo + " ") for n in nomes):
                listas.add(lista)
    if "carros" in listas:
        return "carro", "fipe"
    if listas == {"motos"}:
        return "moto", "fipe"
    if listas:
        return "pesado", "fipe"
    if any(CC_RE.search(v) for v in versoes):
        return "moto", "versao"
    if any(EIXOS_RE.search(v) or (FASE_P_RE.search(v) and _cilindrada(v) >= 4.0) for v in versoes):
        return "pesado", "versao"
    if NOME_PESADO & set(alvo.split()):
        return "pesado", "nome"
    return "carro", "padrao"
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_veiculo_tipo.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Commit**

```bash
git add helper/veiculo_tipo.py helper_veiculos_tipo.csv tests/test_veiculo_tipo.py
git commit -m "helper: tipo do modelo de veículo (ajuste, FIPE, versões, nome)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Coletor — cliente HTTP, FIPE e árvore

**Files:**
- Create: `catalogo_karhub_veiculos.py`
- Create: `veiculos/.gitignore`
- Test: `tests/test_catalogo_karhub_veiculos.py`

**Interfaces:**
- Consumes: `helper.montadoras.Montadoras` (`.carregar()`, `.chaves(nome)`), `helper.veiculo_tipo.carregar_ajustes`, `indexar_fipe`, `classificar`.
- Produces (usados pela Task 4 e pela execução real):
  - `SITE`, `FIPE`, `LISTAS_FIPE = ("carros", "motos", "caminhoes")`, `class Bloqueado(Exception)`.
  - `class Cliente(buscar=None, esperas=ESPERAS, pausa=PAUSA, log=print)`; `.get(url, aceitar_404=False) -> (bytes | None, content_type)`; `.json(url)`. `buscar(url) -> (status, corpo_bytes, content_type)`.
  - `ler_jsonl(caminho) -> list[dict]` (corta a última linha incompleta).
  - `coletar_fipe(cliente, saida: Path) -> dict`.
  - `coletar_arvore(cliente, pasta: Path, indice_fipe, ajustes, montadoras, so_montadora=None, do_inicio=False, log=print) -> Counter`.
  - Linha de `karhub_arvore.jsonl`: `{"montadora": {"label", "handle", "logo_url"}, "modelo": {"label", "handle", "foto_url"}, "tipo": "carro", "motivo_tipo", "anos": [{"ano": int, "versoes": [{"label", "handle", "ids_fonte": [str]}]}], "coletado_em"}`. `logo_url`/`foto_url` são `None` quando a imagem não existe.
  - Linha de `karhub_excluidos.jsonl`: `{"montadora": {"label", "handle"}, "modelo": {"label", "handle"}, "tipo", "motivo_tipo", "versoes_exemplo": [str], "coletado_em"}`; `tipo = "sem_anos"` para modelo sem ano.

- [ ] **Step 1: Escrever os testes**

`tests/test_catalogo_karhub_veiculos.py`:

```python
import json

import pytest

import catalogo_karhub_veiculos as cv
from helper.montadoras import Montadoras
from helper.veiculo_tipo import indexar_fipe

GV = f"{cv.SITE}/api/get-vehicles"
CT = f"{cv.SITE}/api/get-automaker-content?handle="
LOGO = "https://images.karhub.com.br/assets/montadoras/chevrolet.avif"
FOTO = "https://images.karhub.com.br/veiculos/chevrolet-tracker.avif"


def _json(obj):
    return (200, json.dumps(obj).encode(), "application/json")


def _item(label, ids=(), handle=None):
    return {"id": 0, "label": label, "value": label, "handle": handle or label, "compatible_ids": list(ids)}


class Web:
    """Servidor falso: url -> (status, corpo, tipo) | Exception. Rota ausente = 404 em HTML, como o Cloudflare."""
    def __init__(self, rotas):
        self.rotas, self.pedidos = rotas, []

    def __call__(self, url):
        self.pedidos.append(url)
        r = self.rotas.get(url)
        if r is None:
            return (404, b"<html>404</html>", "text/html")
        if isinstance(r, Exception):
            raise r
        return r


def _rotas():
    return {
        GV: _json({"brands": [_item("Chevrolet", handle="chevrolet"), _item("Honda", handle="honda")]}),
        f"{GV}?brand=chevrolet": _json({"models": [_item("Tracker")]}),
        f"{GV}?brand=honda": _json({"models": [_item("Biz 100")]}),
        f"{GV}?brand=chevrolet&model=Tracker": _json({"years": [_item("2021", ["62329", "62330"]), _item("2020", ["5"])]}),
        f"{GV}?brand=chevrolet&model=Tracker&year=2021": _json({"versions": [_item("4x2 Aut. 1.2 12v L3 Turbo", ["62329"], "a"),
                                                                             _item("Lt 1.0", ["62330"], "b")]}),
        f"{GV}?brand=chevrolet&model=Tracker&year=2020": _json({"versions": [_item("Lt 1.0", ["5"], "b")]}),
        f"{GV}?brand=honda&model=Biz+100": _json({"years": [_item("2015", ["9"])]}),
        f"{GV}?brand=honda&model=Biz+100&year=2015": _json({"versions": [_item("Ks 100cc (6,4 Cv)", ["9"])]}),
        f"{CT}chevrolet": _json({"data": {"data": {"brand": {"image_url": LOGO}}}}),
        f"{CT}chevrolet/Tracker": _json({"data": {"data": {"model": {"image_url": FOTO}}}}),
        LOGO: (200, b"LOGO", "image/avif"),
        FOTO: (200, b"FOTO", "image/avif"),
    }


def _cliente(web):
    return cv.Cliente(buscar=web, esperas=(), pausa=0, log=lambda m: None)


def _coletar(tmp_path, web, ajustes=None, **kw):
    return cv.coletar_arvore(_cliente(web), tmp_path, indexar_fipe({}), ajustes or {}, Montadoras({}), log=lambda m: None, **kw)


def _ler(arq):
    return [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines()]


def test_cliente_repete_erro_de_conexao_e_5xx(monkeypatch):
    respostas = [ConnectionError("recusada"), (500, b"", "text/html"), (200, b'{"ok": 1}', "application/json")]

    def buscar(url):
        r = respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    esperas = []
    monkeypatch.setattr(cv.time, "sleep", esperas.append)
    c = cv.Cliente(buscar=buscar, esperas=(5, 15, 30), pausa=0, log=lambda m: None)
    assert c.json("u") == {"ok": 1} and esperas == [5, 15]


def test_cliente_bloqueado_espera_quatro_vezes_e_desiste(monkeypatch):
    esperas = []
    monkeypatch.setattr(cv.time, "sleep", esperas.append)
    c = cv.Cliente(buscar=lambda url: (403, b"<html>captcha</html>", "text/html"), esperas=(5, 15), pausa=0, log=lambda m: None)
    with pytest.raises(cv.Bloqueado):
        c.json("u")
    assert esperas == [20, 60]


def test_imagem_404_volta_none_sem_novas_tentativas():
    web = Web({})
    assert _cliente(web).get("https://x/y.avif", aceitar_404=True) == (None, "text/html")
    assert len(web.pedidos) == 1


def test_fipe_grava_marcas_e_modelos_das_tres_listas(tmp_path):
    rotas = {}
    for lista in cv.LISTAS_FIPE:
        rotas[f"{cv.FIPE}/{lista}/marcas"] = _json([{"codigo": "1", "nome": f"Marca {lista}"}])
        rotas[f"{cv.FIPE}/{lista}/marcas/1/modelos"] = _json({"modelos": [{"codigo": 1, "nome": f"Modelo {lista}"}], "anos": []})
    r = cv.coletar_fipe(_cliente(Web(rotas)), tmp_path / "fipe.json")
    assert json.loads((tmp_path / "fipe.json").read_text()) == {l: {f"Marca {l}": [f"Modelo {l}"]} for l in cv.LISTAS_FIPE}
    assert r == {"carros": 1, "motos": 1, "caminhoes": 1}


def test_arvore_grava_carro_completo_e_separa_moto(tmp_path):
    web = Web(_rotas())
    r = _coletar(tmp_path, web)
    (t,) = _ler(tmp_path / "karhub_arvore.jsonl")
    assert t["montadora"] == {"label": "Chevrolet", "handle": "chevrolet", "logo_url": LOGO}
    assert t["modelo"] == {"label": "Tracker", "handle": "Tracker", "foto_url": FOTO}
    assert (t["tipo"], t["motivo_tipo"]) == ("carro", "padrao")
    assert t["anos"] == [{"ano": 2021, "versoes": [{"label": "4x2 Aut. 1.2 12v L3 Turbo", "handle": "a", "ids_fonte": ["62329"]},
                                                  {"label": "Lt 1.0", "handle": "b", "ids_fonte": ["62330"]}]},
                         {"ano": 2020, "versoes": [{"label": "Lt 1.0", "handle": "b", "ids_fonte": ["5"]}]}]
    (e,) = _ler(tmp_path / "karhub_excluidos.jsonl")
    assert (e["modelo"]["label"], e["tipo"], e["motivo_tipo"], e["versoes_exemplo"]) == ("Biz 100", "moto", "versao", ["Ks 100cc (6,4 Cv)"])
    assert (tmp_path / "imagens/veiculos/chevrolet-tracker.avif").read_bytes() == b"FOTO"
    assert (tmp_path / "imagens/assets/montadoras/chevrolet.avif").read_bytes() == b"LOGO"
    assert r["carros"] == 1 and r["excluido_moto"] == 1
    assert not any(u.startswith(f"{CT}honda") for u in web.pedidos)  # moto não pede conteúdo nem logo


def test_foto_404_fica_ausente(tmp_path):
    rotas = _rotas()
    del rotas[FOTO]
    _coletar(tmp_path, Web(rotas))
    assert _ler(tmp_path / "karhub_arvore.jsonl")[0]["modelo"]["foto_url"] is None


def test_retoma_pulando_modelos_gravados_e_corta_linha_incompleta(tmp_path):
    _coletar(tmp_path, Web(_rotas()))
    with (tmp_path / "karhub_arvore.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"montadora": {"lab')  # queda no meio da gravação
    web2 = Web(_rotas())
    r = _coletar(tmp_path, web2)
    assert r["ja_feitos"] == 2 and r.get("carros", 0) == 0
    assert len(_ler(tmp_path / "karhub_arvore.jsonl")) == 1
    assert not any("year=" in u for u in web2.pedidos)


def test_excluido_que_virou_carro_por_ajuste_e_coletado(tmp_path):
    _coletar(tmp_path, Web(_rotas()))
    rotas = _rotas()
    rotas[f"{CT}honda"] = _json({"data": None})
    rotas[f"{CT}honda/Biz%20100"] = _json({"data": None})
    r = _coletar(tmp_path, Web(rotas), ajustes={("HONDA", "BIZ 100"): "carro"})
    assert r["carros"] == 1
    biz = [t for t in _ler(tmp_path / "karhub_arvore.jsonl") if t["modelo"]["label"] == "Biz 100"][0]
    assert biz["motivo_tipo"] == "ajuste" and biz["montadora"]["logo_url"] is None


def test_modelo_sem_anos_e_registrado_e_nao_volta(tmp_path):
    rotas = _rotas()
    rotas[f"{GV}?brand=chevrolet&model=Tracker"] = _json({"years": []})
    _coletar(tmp_path, Web(rotas))
    assert [e["tipo"] for e in _ler(tmp_path / "karhub_excluidos.jsonl")] == ["sem_anos", "moto"]
    assert _coletar(tmp_path, Web(rotas))["ja_feitos"] == 2


def test_do_inicio_grava_em_arquivo_novo_e_troca_no_fim(tmp_path):
    _coletar(tmp_path, Web(_rotas()))
    antigo = (tmp_path / "karhub_arvore.jsonl").read_text(encoding="utf-8")
    r = _coletar(tmp_path, Web(_rotas()), do_inicio=True)
    assert r["carros"] == 1 and not (tmp_path / "karhub_arvore.jsonl.novo").exists()
    assert json.loads((tmp_path / "karhub_arvore.jsonl").read_text(encoding="utf-8"))["anos"] == json.loads(antigo)["anos"]


def test_so_uma_montadora(tmp_path):
    r = _coletar(tmp_path, Web(_rotas()), so_montadora="honda")
    assert r.get("carros", 0) == 0 and r["excluido_moto"] == 1


def test_main_recusa_montadora_com_do_inicio(tmp_path):
    with pytest.raises(SystemExit):
        cv.main(["arvore", "--pasta", str(tmp_path), "--montadora", "chevrolet", "--do-inicio"])


def test_main_arvore_sem_fipe_avisa(tmp_path):
    assert cv.main(["arvore", "--pasta", str(tmp_path)]) == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_catalogo_karhub_veiculos.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'catalogo_karhub_veiculos'`

- [ ] **Step 3: Implementar**

`veiculos/.gitignore`:

```
*
!.gitignore
```

`catalogo_karhub_veiculos.py`:

```python
#!/usr/bin/env python3
"""Árvore de veículos da KarHub (montadora → modelo → ano → versão), fotos de modelo, logos e compatibilidade
produto → veículo, para o helper. Só carros e utilitários descem até as versões; motos e pesados ficam registrados
em karhub_excluidos.jsonl. Spec: docs/superpowers/specs/2026-10-03-helper-veiculos-design.md

Uso:
    python catalogo_karhub_veiculos.py fipe       # listas da FIPE para classificar o tipo (veiculos/fipe.json)
    python catalogo_karhub_veiculos.py arvore     # retoma pelos modelos já gravados; --montadora chevrolet; --do-inicio
    python catalogo_karhub_veiculos.py compat     # ids de veículo de cada produto de catalogos/karhub.jsonl; --do-inicio

Saída em veiculos/: karhub_arvore.jsonl, karhub_excluidos.jsonl, karhub_compat.jsonl, fipe.json, imagens/ e <comando>.log.
"""
import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import requests
from curl_cffi.requests.exceptions import RequestException as ErroCurl

from helper.montadoras import Montadoras
from helper.veiculo_tipo import carregar_ajustes, classificar, indexar_fipe

SITE = "https://www.karhub.com.br"
FIPE = "https://parallelum.com.br/fipe/api/v1"
LISTAS_FIPE = ("carros", "motos", "caminhoes")
ESPERAS = (5, 15, 30, 60)
PAUSA = 0.3
LOTE_COMPAT = 50  # com 100 handles a API devolve {} sem erro
ERROS_REDE = (requests.RequestException, ErroCurl, OSError)


class Bloqueado(Exception):
    pass


def buscar_scrapling(url):
    from scrapling.fetchers import Fetcher  # o site e as imagens ficam atrás do Cloudflare: requests puro leva 403
    r = Fetcher.get(url, stealthy_headers=True, timeout=60, headers={"Accept": "application/json, image/avif, image/*"})
    return r.status, r.body, (r.headers.get("content-type") or "")


def buscar_requests(url):
    r = requests.get(url, timeout=60)
    return r.status_code, r.content, r.headers.get("content-type", "")


class Cliente:
    """GET com novas tentativas. buscar(url) -> (status, corpo, content_type); trocado por um falso nos testes."""

    def __init__(self, buscar=None, esperas=ESPERAS, pausa=PAUSA, log=print):
        self.buscar = buscar or buscar_scrapling
        self.esperas, self.pausa, self.log = esperas, pausa, log

    def get(self, url, aceitar_404=False):
        bloqueios = 0
        for espera in (*self.esperas, None):
            try:
                status, corpo, tipo = self.buscar(url)
                erro = None
            except ERROS_REDE as e:  # conexão recusada ou timeout: houve minutos assim nos testes de 2026-10-03
                status, corpo, tipo, erro = None, b"", "", f"conexão: {e}"
            if status == 200:
                if self.pausa:
                    time.sleep(self.pausa)
                return corpo, tipo
            if status == 404 and aceitar_404:
                return None, tipo
            if status in (403, 430) or (status and b"captcha" in corpo[:3000].lower()):
                bloqueios += 1
                erro = f"BLOQUEIO HTTP {status}"
                espera = espera and espera * 4
            elif erro is None:
                erro = f"HTTP {status}"
            if espera is None:
                raise (Bloqueado if bloqueios else RuntimeError)(f"{erro} em {url}")
            self.log(f"{erro}; nova tentativa em {espera}s")
            time.sleep(espera)

    def json(self, url):
        return json.loads(self.get(url)[0])


def ler_jsonl(caminho):
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    texto = caminho.read_text(encoding="utf-8")
    if texto and not texto.endswith("\n"):  # última linha cortada por uma interrupção
        texto = texto[:texto.rfind("\n") + 1]
        caminho.write_text(texto, encoding="utf-8")
    return [json.loads(l) for l in texto.splitlines() if l.strip()]


# ---------- FIPE ----------

def coletar_fipe(cliente, saida):
    dados = {}
    for lista in LISTAS_FIPE:
        dados[lista] = {}
        for marca in cliente.json(f"{FIPE}/{lista}/marcas"):
            modelos = cliente.json(f"{FIPE}/{lista}/marcas/{marca['codigo']}/modelos")["modelos"]
            dados[lista][marca["nome"]] = [m["nome"] for m in modelos]
    Path(saida).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return {lista: len(v) for lista, v in dados.items()}


# ---------- árvore ----------

def api_veiculos(cliente, **params):
    return cliente.json(f"{SITE}/api/get-vehicles" + (f"?{urlencode(params)}" if params else ""))


def conteudo(cliente, handle):
    """get-automaker-content: {'brand': {...}, 'model': {...}} ou {} quando o KarHub não tem conteúdo."""
    d = cliente.json(f"{SITE}/api/get-automaker-content?handle={quote(handle)}")
    return (d.get("data") or {}).get("data") or {}


def baixar_imagem(cliente, url, pasta):
    """Guarda em pasta/<caminho da URL>. Devolve a URL se a imagem existe; None se não há URL ou deu 404."""
    if not url:
        return None
    destino = Path(pasta) / urlsplit(url).path.lstrip("/")
    if destino.exists():
        return url
    corpo, tipo = cliente.get(url, aceitar_404=True)
    if corpo is None or not tipo.startswith("image/"):
        return None
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(corpo)
    return url


def _versoes(itens):
    return [{"label": v["label"], "handle": v["handle"], "ids_fonte": [str(i) for i in v["compatible_ids"]]}
            for v in itens if v.get("compatible_ids")]


def _feitos(arq_arvore, arq_excl, indice_fipe, ajustes, montadoras):
    feitos = {(l["montadora"]["handle"], l["modelo"]["handle"]) for l in ler_jsonl(arq_arvore)}
    for l in ler_jsonl(arq_excl):
        if l.get("tipo") == "sem_anos":
            feitos.add((l["montadora"]["handle"], l["modelo"]["handle"]))
            continue
        # um ajuste novo em helper_veiculos_tipo.csv pode ter transformado o excluído em carro: aí ele é coletado
        tipo, _ = classificar(montadoras.chaves(l["montadora"]["label"]), l["modelo"]["label"], l.get("versoes_exemplo") or [],
                              indice_fipe, ajustes)
        if tipo != "carro":
            feitos.add((l["montadora"]["handle"], l["modelo"]["handle"]))
    return feitos


def coletar_arvore(cliente, pasta, indice_fipe, ajustes, montadoras, so_montadora=None, do_inicio=False, log=print):
    pasta = Path(pasta)
    arq_arvore, arq_excl = pasta / "karhub_arvore.jsonl", pasta / "karhub_excluidos.jsonl"
    alvo_arvore = Path(f"{arq_arvore}.novo") if do_inicio else arq_arvore
    alvo_excl = Path(f"{arq_excl}.novo") if do_inicio else arq_excl
    feitos = _feitos(alvo_arvore, alvo_excl, indice_fipe, ajustes, montadoras)
    hoje, r, logos = date.today().isoformat(), Counter(), {}
    with alvo_arvore.open("a", encoding="utf-8") as f_arv, alvo_excl.open("a", encoding="utf-8") as f_exc:
        def gravar(arquivo, registro):
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
            arquivo.flush()

        for marca in api_veiculos(cliente)["brands"]:
            if so_montadora and marca["handle"] != so_montadora:
                continue
            chaves = montadoras.chaves(marca["label"])
            for modelo in api_veiculos(cliente, brand=marca["handle"])["models"]:
                if (marca["handle"], modelo["handle"]) in feitos:
                    r["ja_feitos"] += 1
                    continue
                base = {"montadora": {"label": marca["label"], "handle": marca["handle"]},
                        "modelo": {"label": modelo["label"], "handle": modelo["handle"]}}
                anos = api_veiculos(cliente, brand=marca["handle"], model=modelo["handle"])["years"]
                if not anos:
                    gravar(f_exc, {**base, "tipo": "sem_anos", "motivo_tipo": "sem_anos", "versoes_exemplo": [], "coletado_em": hoje})
                    r["sem_anos"] += 1
                    continue
                recentes = api_veiculos(cliente, brand=marca["handle"], model=modelo["handle"], year=anos[0]["value"])["versions"]
                rotulos = [v["label"] for v in recentes]
                tipo, motivo = classificar(chaves, modelo["label"], rotulos, indice_fipe, ajustes)
                if tipo != "carro":
                    gravar(f_exc, {**base, "tipo": tipo, "motivo_tipo": motivo, "versoes_exemplo": rotulos[:5], "coletado_em": hoje})
                    r[f"excluido_{tipo}"] += 1
                    log(f"{marca['label']} {modelo['label']}: {tipo} ({motivo}), fora da árvore")
                    continue
                lista_anos = [{"ano": int(anos[0]["value"]), "versoes": _versoes(recentes)}]
                for ano in anos[1:]:
                    itens = api_veiculos(cliente, brand=marca["handle"], model=modelo["handle"], year=ano["value"])["versions"]
                    lista_anos.append({"ano": int(ano["value"]), "versoes": _versoes(itens)})
                if marca["handle"] not in logos:
                    url_logo = (conteudo(cliente, marca["handle"]).get("brand") or {}).get("image_url")
                    logos[marca["handle"]] = baixar_imagem(cliente, url_logo, pasta / "imagens")
                url_foto = (conteudo(cliente, f"{marca['handle']}/{modelo['handle']}").get("model") or {}).get("image_url")
                gravar(f_arv, {"montadora": {**base["montadora"], "logo_url": logos[marca["handle"]]},
                               "modelo": {**base["modelo"], "foto_url": baixar_imagem(cliente, url_foto, pasta / "imagens")},
                               "tipo": tipo, "motivo_tipo": motivo, "anos": lista_anos, "coletado_em": hoje})
                r["carros"] += 1
                log(f"{marca['label']} {modelo['label']}: carro ({motivo}), {len(lista_anos)} anos")
    if do_inicio:
        alvo_arvore.replace(arq_arvore)
        alvo_excl.replace(arq_excl)
    return r


# ---------- linha de comando ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("comando", choices=["fipe", "arvore", "compat"])
    ap.add_argument("--pasta", type=Path, default=Path("veiculos"))
    ap.add_argument("--catalogo", type=Path, default=Path("catalogos/karhub.jsonl"), help="compat: de onde vêm os handles")
    ap.add_argument("--montadora", help="arvore: só esta montadora (handle do KarHub, ex.: chevrolet)")
    ap.add_argument("--do-inicio", action="store_true", help="coleta tudo de novo em arquivos .novo e troca no fim")
    args = ap.parse_args(argv)
    if args.montadora and args.do_inicio:
        ap.error("--montadora não combina com --do-inicio (a troca no fim apagaria as outras montadoras)")
    args.pasta.mkdir(parents=True, exist_ok=True)
    with open(args.pasta / f"{args.comando}.log", "a", encoding="utf-8") as f_log:
        def log(msg):
            linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
            print(linha, flush=True)
            f_log.write(linha + "\n")
            f_log.flush()

        try:
            if args.comando == "fipe":
                r = coletar_fipe(Cliente(buscar=buscar_requests, pausa=1.0, log=log), args.pasta / "fipe.json")
            elif args.comando == "arvore":
                arq_fipe = args.pasta / "fipe.json"
                if not arq_fipe.exists():
                    log(f"sem {arq_fipe}: rode antes python catalogo_karhub_veiculos.py fipe")
                    return 2
                r = coletar_arvore(Cliente(log=log), args.pasta, indexar_fipe(json.loads(arq_fipe.read_text(encoding="utf-8"))),
                                   carregar_ajustes(), Montadoras.carregar(), so_montadora=args.montadora,
                                   do_inicio=args.do_inicio, log=log)
            else:
                r = coletar_compat(Cliente(log=log), args.catalogo, args.pasta / "karhub_compat.jsonl", do_inicio=args.do_inicio, log=log)
        except Bloqueado as e:
            log(f"PARADO por bloqueio ({e}). Rode de novo mais tarde; retoma de onde parou.")
            return 2
        log("fim: " + ", ".join(f"{k} {v}" for k, v in sorted(dict(r).items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`coletar_compat` é escrita na Task 4; até lá o subcomando `compat` não é usado pelos testes desta tarefa.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_catalogo_karhub_veiculos.py -v`
Expected: PASS (14 testes)

- [ ] **Step 5: Commit**

```bash
git add catalogo_karhub_veiculos.py veiculos/.gitignore tests/test_catalogo_karhub_veiculos.py
git commit -m "catalogo_karhub_veiculos: árvore de carros e utilitários do KarHub, FIPE e imagens

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Coletor — compatibilidade produto → veículo

**Files:**
- Modify: `catalogo_karhub_veiculos.py` (acrescentar antes de `# ---------- linha de comando ----------`)
- Test: `tests/test_catalogo_karhub_veiculos.py` (acrescentar)

**Interfaces:**
- Consumes: `Cliente`, `ler_jsonl`, `SITE`, `LOTE_COMPAT` (Task 3).
- Produces:
  - `handles_do_catalogo(caminho) -> list[str]` — handle = último pedaço do caminho da URL, sem query; ordem de primeira aparição; linhas inválidas ignoradas.
  - `coletar_compat(cliente, catalogo, saida, do_inicio=False, log=print) -> Counter` (`com_ids`, `sem_ids`).
  - Linha de `karhub_compat.jsonl`: `{"handle": str, "ids": [str], "coletado_em": "AAAA-MM-DD"}`.

- [ ] **Step 1: Escrever os testes** (acrescentar ao fim de `tests/test_catalogo_karhub_veiculos.py`)

```python
def _catalogo(tmp_path, n):
    arq = tmp_path / "karhub.jsonl"
    linhas = [json.dumps({"url": f"https://www.karhub.com.br/p/peca-{i}"}) for i in range(n)]
    linhas.append(json.dumps({"url": "https://www.karhub.com.br/p/peca-0?Lado=Direito"}))  # variante: mesmo handle
    arq.write_text("\n".join(linhas) + "\n{cortada", encoding="utf-8")
    return arq


def _rota_compat(handles):
    return f"{cv.SITE}/api/product-compatible-ids?handles={','.join(handles)}"


def test_handles_do_catalogo(tmp_path):
    assert cv.handles_do_catalogo(_catalogo(tmp_path, 3)) == ["peca-0", "peca-1", "peca-2"]


def test_compat_em_lotes_de_50(tmp_path):
    handles = [f"peca-{i}" for i in range(60)]
    rotas = {_rota_compat(handles[:50]): _json({h: [1, 2] for h in handles[:50]}),
             _rota_compat(handles[50:]): _json({"peca-55": ["7"]})}
    r = cv.coletar_compat(_cliente(Web(rotas)), _catalogo(tmp_path, 60), tmp_path / "compat.jsonl", log=lambda m: None)
    por_handle = {l["handle"]: l["ids"] for l in _ler(tmp_path / "compat.jsonl")}
    assert len(por_handle) == 60 and por_handle["peca-0"] == ["1", "2"]
    assert por_handle["peca-55"] == ["7"] and por_handle["peca-56"] == []
    assert r["com_ids"] == 51 and r["sem_ids"] == 9


def test_lote_inteiro_vazio_repete_em_lotes_de_10(tmp_path):
    handles = [f"peca-{i}" for i in range(50)]
    rotas = {_rota_compat(handles): _json({})}
    for j in range(0, 50, 10):
        rotas[_rota_compat(handles[j:j + 10])] = _json({h: ["3"] for h in handles[j:j + 10]})
    cv.coletar_compat(_cliente(Web(rotas)), _catalogo(tmp_path, 50), tmp_path / "compat.jsonl", log=lambda m: None)
    assert all(l["ids"] == ["3"] for l in _ler(tmp_path / "compat.jsonl"))


def test_compat_retoma_pelos_handles_gravados(tmp_path):
    (tmp_path / "compat.jsonl").write_text(json.dumps({"handle": "peca-0", "ids": ["1"], "coletado_em": "2026-10-01"}) + "\n", encoding="utf-8")
    web = Web({_rota_compat(["peca-1", "peca-2"]): _json({"peca-1": ["9"]})})
    cv.coletar_compat(_cliente(web), _catalogo(tmp_path, 3), tmp_path / "compat.jsonl", log=lambda m: None)
    assert [l["handle"] for l in _ler(tmp_path / "compat.jsonl")] == ["peca-0", "peca-1", "peca-2"]
    assert len(web.pedidos) == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_catalogo_karhub_veiculos.py -v -k "compat or handles"`
Expected: FAIL com `AttributeError: module 'catalogo_karhub_veiculos' has no attribute 'handles_do_catalogo'`

- [ ] **Step 3: Implementar** (em `catalogo_karhub_veiculos.py`, antes de `# ---------- linha de comando ----------`)

```python
# ---------- compatibilidade produto -> veículo ----------

def handles_do_catalogo(caminho):
    vistos = {}
    with Path(caminho).open(encoding="utf-8") as f:
        for linha in f:
            try:
                url = json.loads(linha)["url"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
            vistos.setdefault(urlsplit(url).path.rsplit("/", 1)[-1], None)
    return list(vistos)


def _compat(cliente, handles):
    resposta = cliente.json(f"{SITE}/api/product-compatible-ids?handles={','.join(quote(h) for h in handles)}")
    return resposta if isinstance(resposta, dict) else {}


def coletar_compat(cliente, catalogo, saida, do_inicio=False, log=print):
    saida = Path(saida)
    alvo = Path(f"{saida}.novo") if do_inicio else saida
    feitos = {l["handle"] for l in ler_jsonl(alvo)}
    pendentes = [h for h in handles_do_catalogo(catalogo) if h not in feitos]
    hoje, r = date.today().isoformat(), Counter()
    log(f"compat: {len(feitos)} handles já gravados, {len(pendentes)} a consultar")
    with alvo.open("a", encoding="utf-8") as f:
        for i in range(0, len(pendentes), LOTE_COMPAT):
            lote = pendentes[i:i + LOTE_COMPAT]
            resposta = _compat(cliente, lote)
            if not resposta and len(lote) > 10:
                # lote inteiro vazio: recusado ou ninguém com compatibilidade? em lotes de 10 dá para saber
                resposta = {}
                for j in range(0, len(lote), 10):
                    resposta.update(_compat(cliente, lote[j:j + 10]))
            for h in lote:
                ids = [str(x) for x in resposta.get(h) or []]
                f.write(json.dumps({"handle": h, "ids": ids, "coletado_em": hoje}) + "\n")
                r["com_ids" if ids else "sem_ids"] += 1
            f.flush()
            if (i // LOTE_COMPAT) % 20 == 0:
                log(f"compat: {i + len(lote)} de {len(pendentes)}")
    if do_inicio:
        alvo.replace(saida)
    return r
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_catalogo_karhub_veiculos.py -v`
Expected: PASS (18 testes)

- [ ] **Step 5: Commit**

```bash
git add catalogo_karhub_veiculos.py tests/test_catalogo_karhub_veiculos.py
git commit -m "catalogo_karhub_veiculos: compatibilidade produto -> veículo em lotes de 50

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Banco local — tabelas de veículos e `meta`

**Files:**
- Modify: `helper/banco.py`
- Modify: `helper/cli.py` (função `preparar`)
- Test: `tests/test_banco.py`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - Tabelas locais `veiculo_montadora`, `veiculo_modelo`, `veiculo_versao`, `veiculo_versao_ano`, `veiculo_fonte`, `peca_veiculo`, `peca_veiculo_estado`, `veiculo_arquivo` (colunas abaixo).
  - `VERSAO_ESQUEMA = 2`; `INDICES_PECA_VEICULO: list[str]` (os dois `CREATE INDEX` de `peca_veiculo`).
  - `gravar_meta(db, chave, valor)`, `ler_meta(db, chave) -> str | None`, `agora() -> str` (ISO, segundos).
  - `meta.preparado_em` gravado pelo `preparar`.

- [ ] **Step 1: Escrever os testes**

Acrescentar a `tests/test_banco.py` (e trocar a linha `from helper.banco import VERSAO_ESQUEMA, abrir, id_marca` por `from helper.banco import VERSAO_ESQUEMA, abrir, agora, gravar_meta, id_marca, ler_meta`):

```python
def test_tabelas_de_veiculos_e_meta(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    nomes = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"veiculo_montadora", "veiculo_modelo", "veiculo_versao", "veiculo_versao_ano", "veiculo_fonte",
            "peca_veiculo", "peca_veiculo_estado", "veiculo_arquivo"} <= nomes
    gravar_meta(db, "x", "1")
    gravar_meta(db, "x", "2")
    assert ler_meta(db, "x") == "2" and ler_meta(db, "nada") is None
    assert VERSAO_ESQUEMA == 2 and ler_meta(db, "versao_esquema") == "2"
    assert len(agora()) == 19


def test_versao_do_esquema_sobe_em_banco_antigo(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    gravar_meta(db, "versao_esquema", "1")
    db.commit()
    db.close()
    assert ler_meta(abrir(tmp_path / "h.sqlite"), "versao_esquema") == "2"
```

Acrescentar a `tests/test_cli.py` (e incluir `ler_meta` no import: `from helper.banco import abrir, ler_meta`):

```python
def test_preparar_grava_a_hora_em_meta(tmp_path):
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    assert ler_meta(abrir(tmp_path / "helper.sqlite"), "preparado_em")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_banco.py tests/test_cli.py -v`
Expected: FAIL com `ImportError: cannot import name 'agora' from 'helper.banco'`

- [ ] **Step 3: Implementar**

Em `helper/banco.py`:

1. Trocar `import sqlite3` por:

```python
import sqlite3
from datetime import datetime
```

2. Trocar `VERSAO_ESQUEMA = 1` por `VERSAO_ESQUEMA = 2`.

3. Acrescentar ao fim da lista `DDL` (antes do `]`):

```python
    # ---- veículos (spec de veículos, seção 6); prefixo veiculo_ porque o banco helper do Postgres é dividido com o Wayap
    """CREATE TABLE IF NOT EXISTS veiculo_montadora (
         id_veiculo_montadora INTEGER PRIMARY KEY AUTOINCREMENT,
         nome TEXT NOT NULL UNIQUE, nome_exibicao TEXT NOT NULL,
         logo TEXT, logo_fonte TEXT, id_montadora INTEGER,
         qtd_pecas INTEGER NOT NULL DEFAULT 0, ativo INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS veiculo_modelo (
         id_modelo INTEGER PRIMARY KEY AUTOINCREMENT,
         id_veiculo_montadora INTEGER NOT NULL REFERENCES veiculo_montadora(id_veiculo_montadora),
         nome TEXT NOT NULL, nome_exibicao TEXT NOT NULL,
         foto TEXT, foto_herdada INTEGER NOT NULL DEFAULT 0, foto_fonte TEXT,
         ano_inicio INTEGER, ano_fim INTEGER, qtd_pecas INTEGER NOT NULL DEFAULT 0,
         ativo INTEGER NOT NULL DEFAULT 1, hash_conteudo TEXT, atualizado_em TEXT,
         UNIQUE (id_veiculo_montadora, nome))""",
    """CREATE TABLE IF NOT EXISTS veiculo_versao (
         id_versao INTEGER PRIMARY KEY AUTOINCREMENT,
         id_modelo INTEGER NOT NULL REFERENCES veiculo_modelo(id_modelo),
         nome TEXT NOT NULL, nome_exibicao TEXT NOT NULL, motor TEXT, ativo INTEGER NOT NULL DEFAULT 1,
         UNIQUE (id_modelo, nome))""",
    """CREATE TABLE IF NOT EXISTS veiculo_versao_ano (
         id_versao INTEGER NOT NULL REFERENCES veiculo_versao(id_versao), ano INTEGER NOT NULL,
         PRIMARY KEY (id_versao, ano))""",
    """CREATE TABLE IF NOT EXISTS veiculo_fonte (
         site TEXT NOT NULL, id_fonte TEXT NOT NULL, id_versao INTEGER NOT NULL, ano INTEGER NOT NULL,
         PRIMARY KEY (site, id_fonte))""",
    """CREATE TABLE IF NOT EXISTS peca_veiculo (
         id_peca INTEGER NOT NULL, id_modelo INTEGER NOT NULL, id_versao INTEGER,
         ano_inicio INTEGER, ano_fim INTEGER, nivel TEXT NOT NULL CHECK (nivel IN ('versao','modelo')))""",
    """CREATE TABLE IF NOT EXISTS peca_veiculo_estado (id_peca INTEGER PRIMARY KEY, hash TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS veiculo_arquivo (caminho TEXT PRIMARY KEY, publicado INTEGER NOT NULL DEFAULT 0)""",
```

4. Logo depois da lista `DDL`, acrescentar:

```python
# a carga de peca_veiculo (milhões de linhas) apaga os índices e recria no fim: veiculos_ligar.py usa esta lista
INDICES_PECA_VEICULO = [
    "CREATE INDEX IF NOT EXISTS peca_veiculo_peca ON peca_veiculo (id_peca)",
    "CREATE INDEX IF NOT EXISTS peca_veiculo_modelo ON peca_veiculo (id_modelo, ano_inicio, ano_fim)",
]
```

5. Em `abrir`, trocar o laço e o `INSERT OR IGNORE` da versão por:

```python
    for comando in DDL + INDICES_PECA_VEICULO:
        db.execute(comando)
    db.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES ('versao_esquema', ?)", (str(VERSAO_ESQUEMA),))
```

6. Acrescentar ao fim do arquivo:

```python
def gravar_meta(db, chave, valor):
    db.execute("INSERT OR REPLACE INTO meta (chave, valor) VALUES (?, ?)", (chave, valor))


def ler_meta(db, chave):
    linha = db.execute("SELECT valor FROM meta WHERE chave = ?", (chave,)).fetchone()
    return linha[0] if linha else None


def agora():
    return datetime.now().isoformat(timespec="seconds")
```

Em `helper/cli.py`, na função `preparar`, logo depois de `resultado = fusao.gravar(...)`:

```python
    banco.gravar_meta(db, "preparado_em", banco.agora())  # o publicar recusa veículos ligados antes desta fusão
    db.commit()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_banco.py tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add helper/banco.py helper/cli.py tests/test_banco.py tests/test_cli.py
git commit -m "helper: tabelas locais de veículos, meta preparado_em e esquema 2

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Árvore no SQLite

**Files:**
- Create: `helper/veiculos.py`
- Test: `tests/test_veiculos.py`

**Interfaces:**
- Consumes: `helper.montadoras.Montadoras` (`.canonica`), `nome_canonico`; tabelas da Task 5.
- Produces:
  - `ler_arvore(caminho) -> list[dict]` — última linha de cada `(montadora.handle, modelo.handle)` vale; linhas inválidas ignoradas.
  - `motor(rotulo) -> str | None` — primeira cilindrada `\d.\d`.
  - `carregar_arvore(db, linhas, montadoras) -> dict` com `montadoras`, `modelos`, `versoes`, `anos_versao` (contagens dos ativos).
  - Helper de teste reaproveitado nas Tasks 7, 8, 9 e 13: `tests.test_veiculos._linha(montadora="Chevrolet", mh="chevrolet", modelo="Tracker", anos=None, foto=..., tipo="carro")`.

- [ ] **Step 1: Escrever os testes**

`tests/test_veiculos.py`:

```python
import json

from helper.banco import abrir
from helper.montadoras import Montadoras
from helper.veiculos import carregar_arvore, ler_arvore, motor

FOTO_TRACKER = "https://images.karhub.com.br/veiculos/chevrolet-tracker.avif"


def _linha(montadora="Chevrolet", mh="chevrolet", modelo="Tracker", anos=None, foto=FOTO_TRACKER, tipo="carro"):
    """Linha de karhub_arvore.jsonl. Tracker padrão: 2021 {4x2 (62329), Lt (62330)}, 2020 {Lt (5)}.
    Outros modelos recebem os mesmos anos com ids prefixados (<handle>-<modelo>-62329...), para não colidirem."""
    if anos is None:
        p = "" if (mh, modelo) == ("chevrolet", "Tracker") else f"{mh}-{modelo}-"
        anos = [{"ano": 2021, "versoes": [{"label": "4x2 Aut. 1.2 12v L3 Turbo", "handle": "a", "ids_fonte": [f"{p}62329"]},
                                          {"label": "Lt 1.0", "handle": "b", "ids_fonte": [f"{p}62330"]}]},
                {"ano": 2020, "versoes": [{"label": "Lt 1.0", "handle": "b", "ids_fonte": [f"{p}5"]}]}]
    return {"montadora": {"label": montadora, "handle": mh, "logo_url": f"https://images.karhub.com.br/assets/montadoras/{mh}.avif"},
            "modelo": {"label": modelo, "handle": modelo, "foto_url": foto}, "tipo": tipo, "motivo_tipo": "fipe",
            "anos": anos, "coletado_em": "2026-10-03"}


M = Montadoras({"MERCEDESBENZ": "MERCEDES-BENZ"})


def test_motor():
    assert motor("Lt 1.0") == "1.0" and motor("4p Mec. (g7) 1.0 12v L3 (75 82 Cv)") == "1.0"
    assert motor("Ks 100cc (6,4 Cv)") is None


def test_ler_arvore_ultima_linha_vale_e_invalida_e_ignorada(tmp_path):
    arq = tmp_path / "a.jsonl"
    arq.write_text(json.dumps(_linha(foto=None)) + "\n" + json.dumps(_linha()) + "\n{cortada", encoding="utf-8")
    linhas = ler_arvore(arq)
    assert len(linhas) == 1 and linhas[0]["modelo"]["foto_url"] == FOTO_TRACKER


def test_carrega_montadora_modelo_versoes_e_anos(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    assert carregar_arvore(db, [_linha()], M) == {"montadoras": 1, "modelos": 1, "versoes": 2, "anos_versao": 3}
    mo = db.execute("SELECT * FROM veiculo_modelo").fetchone()
    assert (mo["nome"], mo["nome_exibicao"], mo["ano_inicio"], mo["ano_fim"], mo["ativo"]) == ("TRACKER", "Tracker", 2020, 2021, 1)
    assert mo["foto_fonte"] == FOTO_TRACKER
    assert db.execute("SELECT logo_fonte FROM veiculo_montadora").fetchone()[0].endswith("chevrolet.avif")
    vs = {r["nome"]: r for r in db.execute("SELECT * FROM veiculo_versao")}
    assert set(vs) == {"4X2 AUT. 1.2 12V L3 TURBO", "LT 1.0"} and vs["LT 1.0"]["motor"] == "1.0"
    assert vs["LT 1.0"]["nome_exibicao"] == "Lt 1.0"
    assert db.execute("SELECT ano FROM veiculo_fonte WHERE id_fonte = '5'").fetchone()[0] == 2020
    anos_lt = [r[0] for r in db.execute("SELECT va.ano FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao) "
                                        "WHERE v.nome = 'LT 1.0' ORDER BY va.ano")]
    assert anos_lt == [2020, 2021]


def test_ids_estaveis_ao_recarregar_e_ausente_vira_inativo(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, [_linha(), _linha(modelo="Onix")], M)
    ids = dict(db.execute("SELECT nome, id_modelo FROM veiculo_modelo"))
    sql_lt = ("SELECT v.id_versao FROM veiculo_versao v JOIN veiculo_modelo m USING (id_modelo) "
              "WHERE m.nome = 'TRACKER' AND v.nome = 'LT 1.0'")
    lt = db.execute(sql_lt).fetchone()[0]
    carregar_arvore(db, [_linha(modelo="Onix"), _linha()], M)  # outra ordem
    assert dict(db.execute("SELECT nome, id_modelo FROM veiculo_modelo")) == ids
    assert db.execute(sql_lt).fetchone()[0] == lt
    r = carregar_arvore(db, [_linha(modelo="Onix")], M)
    assert db.execute("SELECT ativo FROM veiculo_modelo WHERE nome = 'TRACKER'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM veiculo_versao v JOIN veiculo_modelo m USING (id_modelo) "
                      "WHERE m.nome = 'TRACKER' AND v.ativo = 1").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM veiculo_fonte WHERE id_fonte = '62329'").fetchone()[0] == 0
    assert r["modelos"] == 1


def test_montadora_canonica_e_tipos_que_nao_sao_carro_ficam_fora(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, [_linha(montadora="Mercedes Benz", mh="mercedes-benz", modelo="A 200"),
                         _linha(montadora="Honda", mh="honda", modelo="Biz", tipo="moto")], M)
    assert [tuple(r) for r in db.execute("SELECT nome, nome_exibicao FROM veiculo_montadora")] == [("MERCEDES-BENZ", "Mercedes Benz")]


def test_ano_sem_versao_nao_conta(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    anos = [{"ano": 2022, "versoes": []}, {"ano": 2021, "versoes": [{"label": "Lt", "handle": "x", "ids_fonte": ["1"]}]}]
    carregar_arvore(db, [_linha(anos=anos)], M)
    assert tuple(db.execute("SELECT ano_inicio, ano_fim FROM veiculo_modelo").fetchone()) == (2021, 2021)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_veiculos.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'helper.veiculos'`

- [ ] **Step 3: Implementar**

`helper/veiculos.py`:

```python
"""Árvore de veículos no helper.sqlite (montadora, modelo, versão e anos), com ids estáveis por nome canônico.
Lê veiculos/karhub_arvore.jsonl, gravado por catalogo_karhub_veiculos.py. Spec de veículos, seções 6 e 7."""
import json
import re
from pathlib import Path

from helper.montadoras import nome_canonico

MOTOR_RE = re.compile(r"\b\d\.\d\b")


def ler_arvore(caminho):
    linhas = {}
    with Path(caminho).open(encoding="utf-8") as f:
        for texto in f:
            try:
                l = json.loads(texto)
                linhas[(l["montadora"]["handle"], l["modelo"]["handle"])] = l
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return list(linhas.values())


def motor(rotulo):
    m = MOTOR_RE.search(rotulo or "")
    return m[0] if m else None


def _montadora(db, nome, exibicao, logo_fonte):
    l = db.execute("SELECT id_veiculo_montadora FROM veiculo_montadora WHERE nome = ?", (nome,)).fetchone()
    if l:
        db.execute("UPDATE veiculo_montadora SET nome_exibicao = ?, logo_fonte = coalesce(?, logo_fonte), ativo = 1 "
                   "WHERE id_veiculo_montadora = ?", (exibicao, logo_fonte, l[0]))
        return l[0]
    return db.execute("INSERT INTO veiculo_montadora (nome, nome_exibicao, logo_fonte) VALUES (?, ?, ?)",
                      (nome, exibicao, logo_fonte)).lastrowid


def _modelo(db, id_vm, nome, exibicao, foto_fonte):
    l = db.execute("SELECT id_modelo FROM veiculo_modelo WHERE id_veiculo_montadora = ? AND nome = ?", (id_vm, nome)).fetchone()
    if l:
        db.execute("UPDATE veiculo_modelo SET nome_exibicao = ?, foto_fonte = ?, ativo = 1 WHERE id_modelo = ?",
                   (exibicao, foto_fonte, l[0]))
        return l[0]
    return db.execute("INSERT INTO veiculo_modelo (id_veiculo_montadora, nome, nome_exibicao, foto_fonte) VALUES (?, ?, ?, ?)",
                      (id_vm, nome, exibicao, foto_fonte)).lastrowid


def _versao(db, id_modelo, nome, exibicao):
    l = db.execute("SELECT id_versao FROM veiculo_versao WHERE id_modelo = ? AND nome = ?", (id_modelo, nome)).fetchone()
    if l:
        db.execute("UPDATE veiculo_versao SET nome_exibicao = ?, motor = ?, ativo = 1 WHERE id_versao = ?",
                   (exibicao, motor(exibicao), l[0]))
        return l[0]
    return db.execute("INSERT INTO veiculo_versao (id_modelo, nome, nome_exibicao, motor) VALUES (?, ?, ?, ?)",
                      (id_modelo, nome, exibicao, motor(exibicao))).lastrowid


def carregar_arvore(db, linhas, montadoras):
    # anos e ids do KarHub saem inteiros do arquivo; montadora, modelo e versão nunca são apagados (ids publicados)
    db.execute("DELETE FROM veiculo_versao_ano")
    db.execute("DELETE FROM veiculo_fonte")
    for tabela in ("veiculo_montadora", "veiculo_modelo", "veiculo_versao"):
        db.execute(f"UPDATE {tabela} SET ativo = 0")
    for l in linhas:
        if l.get("tipo", "carro") != "carro":
            continue
        id_vm = _montadora(db, montadoras.canonica(l["montadora"]["label"]), l["montadora"]["label"], l["montadora"].get("logo_url"))
        id_modelo = _modelo(db, id_vm, nome_canonico(l["modelo"]["label"]), l["modelo"]["label"], l["modelo"].get("foto_url"))
        for a in l["anos"]:
            for v in a["versoes"]:
                id_versao = _versao(db, id_modelo, nome_canonico(v["label"]), v["label"])
                db.execute("INSERT OR IGNORE INTO veiculo_versao_ano (id_versao, ano) VALUES (?, ?)", (id_versao, a["ano"]))
                for id_fonte in v["ids_fonte"]:
                    db.execute("INSERT OR REPLACE INTO veiculo_fonte (site, id_fonte, id_versao, ano) VALUES ('karhub', ?, ?, ?)",
                               (str(id_fonte), id_versao, a["ano"]))
    # anos do modelo saem dos anos das versões (dois handles do KarHub podem dar o mesmo nome canônico)
    db.execute("""UPDATE veiculo_modelo SET
                    ano_inicio = (SELECT min(va.ano) FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao)
                                  WHERE v.id_modelo = veiculo_modelo.id_modelo),
                    ano_fim = (SELECT max(va.ano) FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao)
                               WHERE v.id_modelo = veiculo_modelo.id_modelo)""")
    db.commit()
    um = lambda sql: db.execute(sql).fetchone()[0]
    return {"montadoras": um("SELECT count(*) FROM veiculo_montadora WHERE ativo = 1"),
            "modelos": um("SELECT count(*) FROM veiculo_modelo WHERE ativo = 1"),
            "versoes": um("SELECT count(*) FROM veiculo_versao WHERE ativo = 1"),
            "anos_versao": um("SELECT count(*) FROM veiculo_versao_ano")}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_veiculos.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add helper/veiculos.py tests/test_veiculos.py
git commit -m "helper: árvore de veículos no SQLite com ids estáveis

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Fotos de modelo e logos

**Files:**
- Create: `helper/veiculos_fotos.py`
- Create: `helper_fotos_veiculos/.gitignore`
- Modify: `requirements.txt` (`pillow>=10` → `pillow>=11.3`)
- Test: `tests/test_veiculos_fotos.py`

**Interfaces:**
- Consumes: tabelas `veiculo_montadora` (`logo_fonte`), `veiculo_modelo` (`foto_fonte`) preenchidas pela Task 6; `wayap_fotos.n_marca`.
- Produces:
  - `para_webp(dados: bytes) -> bytes`, `para_png(dados: bytes, lado=200) -> bytes`.
  - `modelo_pai(nome: str, nomes_da_montadora: dict[str, int], fotos: dict[int, str | None]) -> int | None`.
  - `processar_imagens(db, pasta_imagens: Path, pasta_saida: Path) -> dict` — chaves `foto_karhub`, `foto_propria`, `foto_herdada`, `foto_sem`, `foto_invalida`, `logo_karhub`, `logo_propria`, `logo_sem`, `logo_invalida`. Grava `veiculo_modelo.foto`/`foto_herdada`, `veiculo_montadora.logo` (caminho relativo `veiculos/modelos/<id>_<sha8>.webp` e `veiculos/montadoras/<id>_<sha8>.png`) e linhas em `veiculo_arquivo`.
  - Arquivos em `pasta_saida/modelos/` e `pasta_saida/montadoras/`; imagens próprias lidas de `pasta_saida/proprias/modelos/` e `pasta_saida/proprias/montadoras/`.

- [ ] **Step 1: Escrever os testes**

`tests/test_veiculos_fotos.py`:

```python
from io import BytesIO

from PIL import Image

from helper.banco import abrir
from helper.montadoras import Montadoras
from helper.veiculos import carregar_arvore
from helper.veiculos_fotos import modelo_pai, para_png, para_webp, processar_imagens
from tests.test_veiculos import _linha


def _img(cor=(200, 0, 0, 255), tam=(600, 450)):
    im = Image.new("RGBA", tam, (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (100, 100), cor), (10, 10))
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _base(tmp_path, linhas):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, linhas, Montadoras({}))
    return db


def _imagens_karhub(tmp_path, foto=None, logo=None):
    imgs = tmp_path / "veiculos/imagens"
    (imgs / "veiculos").mkdir(parents=True)
    (imgs / "assets/montadoras").mkdir(parents=True)
    if foto is not None:
        (imgs / "veiculos/chevrolet-tracker.avif").write_bytes(foto)
    if logo is not None:
        (imgs / "assets/montadoras/chevrolet.avif").write_bytes(logo)
    return imgs


def test_conversoes_mantem_transparencia():
    w = Image.open(BytesIO(para_webp(_img())))
    assert w.format == "WEBP" and w.mode == "RGBA" and w.size == (600, 450) and w.getpixel((500, 400))[3] == 0
    p = Image.open(BytesIO(para_png(_img(tam=(400, 400)))))
    assert p.format == "PNG" and p.size == (200, 200) and p.mode == "RGBA"


def test_foto_do_karhub_logo_e_heranca(tmp_path):
    db = _base(tmp_path, [_linha(), _linha(modelo="Tracker Premier", foto=None), _linha(modelo="Onix", foto=None)])
    imgs = _imagens_karhub(tmp_path, foto=_img(), logo=_img(tam=(200, 200)))
    r = processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    fotos = {x["nome"]: (x["foto"], x["foto_herdada"]) for x in db.execute("SELECT nome, foto, foto_herdada FROM veiculo_modelo")}
    foto_tracker = fotos["TRACKER"][0]
    assert foto_tracker.startswith("veiculos/modelos/") and foto_tracker.endswith(".webp") and fotos["TRACKER"][1] == 0
    assert fotos["TRACKER PREMIER"] == (foto_tracker, 1)
    assert fotos["ONIX"] == (None, 0)
    logo = db.execute("SELECT logo FROM veiculo_montadora").fetchone()[0]
    assert logo.startswith("veiculos/montadoras/") and logo.endswith(".png")
    assert (tmp_path / "helper_fotos_veiculos" / foto_tracker.removeprefix("veiculos/")).exists()
    assert {a[0] for a in db.execute("SELECT caminho FROM veiculo_arquivo WHERE publicado = 0")} == {foto_tracker, logo}
    assert (r["foto_karhub"], r["foto_herdada"], r["foto_sem"], r["logo_karhub"]) == (1, 1, 1, 1)


def test_imagem_propria_tem_prioridade(tmp_path):
    db = _base(tmp_path, [_linha()])
    imgs = _imagens_karhub(tmp_path, foto=_img((200, 0, 0, 255)))
    proprias = tmp_path / "helper_fotos_veiculos/proprias"
    (proprias / "modelos").mkdir(parents=True)
    (proprias / "modelos/Chevrolet-Tracker.png").write_bytes(_img((0, 0, 200, 255)))
    (proprias / "montadoras").mkdir(parents=True)
    (proprias / "montadoras/chevrolet.png").write_bytes(_img(tam=(200, 200)))
    r = processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    foto = db.execute("SELECT foto FROM veiculo_modelo").fetchone()[0]
    px = Image.open(tmp_path / "helper_fotos_veiculos" / foto.removeprefix("veiculos/")).convert("RGBA").getpixel((50, 50))
    assert px[2] > 150 and px[0] < 50  # azul da própria, não o vermelho do KarHub
    assert r["foto_propria"] == 1 and r["logo_propria"] == 1


def test_imagem_corrompida_nao_derruba(tmp_path):
    db = _base(tmp_path, [_linha()])
    imgs = _imagens_karhub(tmp_path, foto=b"<html>erro do cloudflare</html>", logo=b"\x89PNG truncado")
    r = processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    assert db.execute("SELECT foto FROM veiculo_modelo").fetchone()[0] is None
    assert db.execute("SELECT logo FROM veiculo_montadora").fetchone()[0] is None
    assert r["foto_invalida"] == 1 and r["logo_invalida"] == 1


def test_rodar_de_novo_nao_duplica_arquivo(tmp_path):
    db = _base(tmp_path, [_linha()])
    imgs = _imagens_karhub(tmp_path, foto=_img())
    processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    processar_imagens(db, imgs, tmp_path / "helper_fotos_veiculos")
    assert len(list((tmp_path / "helper_fotos_veiculos/modelos").iterdir())) == 1
    assert db.execute("SELECT count(*) FROM veiculo_arquivo").fetchone()[0] == 1


def test_modelo_pai():
    nomes = {"ASTRA": 1, "ASTRA HATCH": 2, "ASTRA HATCH GSI": 3}
    assert modelo_pai("ASTRA HATCH GSI", nomes, {1: "a.webp", 2: None}) == 1
    assert modelo_pai("ASTRA HATCH GSI", nomes, {1: "a.webp", 2: "b.webp"}) == 2
    assert modelo_pai("ASTRA", nomes, {1: "a.webp"}) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_veiculos_fotos.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'helper.veiculos_fotos'`

- [ ] **Step 3: Implementar**

`requirements.txt`: trocar a linha `pillow>=10` por `pillow>=11.3` (abre AVIF, o formato das imagens do KarHub).

`helper_fotos_veiculos/.gitignore`:

```
*
!.gitignore
```

`helper/veiculos_fotos.py`:

```python
"""Fotos de modelo (WebP com transparência) e logos de montadora (PNG) — spec de veículos, seção 7, passo 2.
Imagem própria em <saida>/proprias/ tem prioridade; modelo sem foto herda a do modelo-prefixo da mesma montadora."""
import hashlib
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from wayap_fotos import n_marca

LADO_LOGO = 200
EXTENSOES = {".png", ".jpg", ".jpeg", ".webp", ".avif"}


def para_webp(dados):
    im = Image.open(BytesIO(dados)).convert("RGBA")
    buf = BytesIO()
    im.save(buf, format="WEBP", quality=90, method=6)
    return buf.getvalue()


def para_png(dados, lado=LADO_LOGO):
    im = Image.open(BytesIO(dados)).convert("RGBA")
    im.thumbnail((lado, lado), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _proprias(pasta):
    """n_marca(nome do arquivo sem extensão) -> caminho. 'Chevrolet-Tracker.png' -> 'CHEVROLETTRACKER'."""
    pasta = Path(pasta)
    if not pasta.exists():
        return {}
    return {n_marca(a.stem): a for a in sorted(pasta.iterdir()) if a.suffix.lower() in EXTENSOES}


def _origem(propria, url, pasta_imagens):
    if propria:
        return propria.read_bytes(), "propria"
    if url:
        arq = Path(pasta_imagens) / urlsplit(url).path.lstrip("/")
        if arq.exists():
            return arq.read_bytes(), "karhub"
    return None, None


def _gravar(db, conteudo, pasta_saida, subpasta, prefixo, extensao):
    nome = f"{prefixo}_{hashlib.sha1(conteudo).hexdigest()[:8]}{extensao}"
    destino = Path(pasta_saida) / subpasta / nome
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
    caminho = f"veiculos/{subpasta}/{nome}"  # relativo a /home/wayap/helper/, como montadoras.logo do Wayap
    db.execute("INSERT OR IGNORE INTO veiculo_arquivo (caminho, publicado) VALUES (?, 0)", (caminho,))
    return caminho


def _converter(db, dados, origem, conversor, pasta_saida, subpasta, prefixo, extensao, r, tipo):
    """Converte e grava; imagem que não abre (HTML de erro, arquivo truncado) conta como inválida e devolve None."""
    if not dados:
        return None
    try:
        caminho = _gravar(db, conversor(dados), pasta_saida, subpasta, prefixo, extensao)
    except (OSError, ValueError, SyntaxError):  # PIL.UnidentifiedImageError é OSError
        r[f"{tipo}_invalida"] += 1
        return None
    r[f"{tipo}_{origem}"] += 1
    return caminho


def modelo_pai(nome, nomes_da_montadora, fotos):
    """Modelo da mesma montadora cujo nome é o prefixo mais longo (em palavras) do nome e que tem foto própria."""
    palavras = nome.split()
    for n in range(len(palavras) - 1, 0, -1):
        id_pai = nomes_da_montadora.get(" ".join(palavras[:n]))
        if id_pai and fotos.get(id_pai):
            return id_pai
    return None


def processar_imagens(db, pasta_imagens, pasta_saida):
    pasta_saida = Path(pasta_saida)
    r = Counter()
    logos_proprios = _proprias(pasta_saida / "proprias" / "montadoras")
    fotos_proprias = _proprias(pasta_saida / "proprias" / "modelos")
    for m in db.execute("SELECT id_veiculo_montadora, nome, logo_fonte FROM veiculo_montadora WHERE ativo = 1").fetchall():
        dados, origem = _origem(logos_proprios.get(n_marca(m["nome"])), m["logo_fonte"], pasta_imagens)
        logo = _converter(db, dados, origem, para_png, pasta_saida, "montadoras", m["id_veiculo_montadora"], ".png", r, "logo")
        if logo is None and not dados:
            r["logo_sem"] += 1
        db.execute("UPDATE veiculo_montadora SET logo = ? WHERE id_veiculo_montadora = ?", (logo, m["id_veiculo_montadora"]))
    modelos = db.execute("""SELECT mo.id_modelo, mo.id_veiculo_montadora, mo.nome, mo.foto_fonte, vm.nome AS montadora
                            FROM veiculo_modelo mo JOIN veiculo_montadora vm USING (id_veiculo_montadora)
                            WHERE mo.ativo = 1""").fetchall()
    fotos = {}
    for mo in modelos:
        dados, origem = _origem(fotos_proprias.get(n_marca(mo["montadora"] + mo["nome"])), mo["foto_fonte"], pasta_imagens)
        fotos[mo["id_modelo"]] = _converter(db, dados, origem, para_webp, pasta_saida, "modelos", mo["id_modelo"], ".webp", r, "foto")
    nomes = defaultdict(dict)
    for mo in modelos:
        nomes[mo["id_veiculo_montadora"]][mo["nome"]] = mo["id_modelo"]
    for mo in modelos:
        foto, herdada = fotos[mo["id_modelo"]], 0
        if foto is None:
            pai = modelo_pai(mo["nome"], nomes[mo["id_veiculo_montadora"]], fotos)
            if pai:
                foto, herdada = fotos[pai], 1
                r["foto_herdada"] += 1
            else:
                r["foto_sem"] += 1
        db.execute("UPDATE veiculo_modelo SET foto = ?, foto_herdada = ? WHERE id_modelo = ?", (foto, herdada, mo["id_modelo"]))
    db.commit()
    return dict(r)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pip install -r requirements.txt -q && .venv/bin/pytest tests/test_veiculos_fotos.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add helper/veiculos_fotos.py helper_fotos_veiculos/.gitignore requirements.txt tests/test_veiculos_fotos.py
git commit -m "helper: fotos de modelo em WebP, logos em PNG, imagens próprias e herança por prefixo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Ligação de nível versão

**Files:**
- Create: `helper/veiculos_ligar.py`
- Test: `tests/test_veiculos_ligar.py`

**Interfaces:**
- Consumes: tabelas da Task 5 preenchidas pela Task 6 (`veiculo_fonte`, `veiculo_versao_ano`); `peca`, `origem`; `helper.banco.INDICES_PECA_VEICULO`; `helper.veiculo_tipo.normalizar`.
- Produces:
  - `faixas(selecionados, universo) -> list[tuple[int, int]]`.
  - `agrupar(versoes_por_ano, anos_por_versao, atendidas_por_ano) -> list[tuple[int | None, int, int]]`.
  - `handle_da_url(url) -> str`.
  - `class Arvore(db)` com `.linhas_versao(ids_fonte, contagem) -> list[tuple[id_modelo, id_versao | None, ano_inicio, ano_fim, "versao"]]` e `.modelo_da_aplicacao(montadora_canonica | None, modelo) -> int | None` (usado na Task 9).
  - `ligar_versao(db, arvore, caminho_compat) -> Counter` (`pecas_nivel_versao`, `ids_desconhecidos`, `handles_sem_compat`). Apaga `peca_veiculo` inteira antes.

- [ ] **Step 1: Escrever os testes**

`tests/test_veiculos_ligar.py`:

```python
import json

from helper.banco import abrir
from helper.montadoras import Montadoras
from helper.veiculos import carregar_arvore
from helper.veiculos_ligar import Arvore, agrupar, faixas, ligar_versao
from tests.test_veiculos import _linha


def test_faixas_contam_so_os_anos_do_universo():
    assert faixas({2010, 2011, 2013}, [2010, 2011, 2013]) == [(2010, 2013)]  # 2012 não existe: não quebra
    assert faixas({2010, 2013}, [2010, 2011, 2013]) == [(2010, 2010), (2013, 2013)]
    assert faixas(set(), [2010]) == []


def test_ano_completo_vira_todas_as_versoes():
    versoes_por_ano = {2020: {1, 2}, 2021: {1, 2}, 2022: {1, 3}}
    anos_por_versao = {1: [2020, 2021, 2022], 2: [2020, 2021], 3: [2022]}
    assert agrupar(versoes_por_ano, anos_por_versao, {2020: {1, 2}, 2021: {1, 2}, 2022: {1}}) == [(None, 2020, 2021), (1, 2022, 2022)]


def test_versao_em_anos_nao_seguidos():
    versoes_por_ano = {2018: {1, 2}, 2019: {1, 2}, 2021: {1, 2}}
    anos_por_versao = {1: [2018, 2019, 2021], 2: [2018, 2019, 2021]}
    assert agrupar(versoes_por_ano, anos_por_versao, {a: {1, 2} for a in (2018, 2019, 2021)}) == [(None, 2018, 2021)]
    assert agrupar(versoes_por_ano, anos_por_versao, {2018: {2}, 2021: {2}}) == [(2, 2018, 2018), (2, 2021, 2021)]


def _base(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    carregar_arvore(db, [_linha()], Montadoras({}))  # Tracker: 2021 {62329 4x2, 62330 Lt}, 2020 {5 Lt}
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'X', 'reposicao')")
    for i in (1, 2, 3):
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?, 1, ?, ?, 'PECA', 'ativa')",
                   (i, f"X|{i}", str(i)))
    db.execute("UPDATE peca SET status = 'inativa' WHERE id_peca = 3")
    for id_peca, url in [(1, "https://www.karhub.com.br/p/p1"), (2, "https://www.karhub.com.br/p/p2a"),
                         (2, "https://www.karhub.com.br/p/p2b?Lado=Direito"), (3, "https://www.karhub.com.br/p/p3")]:
        db.execute("INSERT INTO origem (id_peca, site, url) VALUES (?, 'karhub', ?)", (id_peca, url))
    db.commit()
    compat = tmp_path / "compat.jsonl"
    compat.write_text("\n".join(json.dumps(l) for l in [
        {"handle": "p1", "ids": ["62329", "62330", "5", "999999"]},  # tudo do Tracker + um id fora da árvore
        {"handle": "p2a", "ids": ["62329"]}, {"handle": "p2b", "ids": ["5"]},  # mesma peça, dois anúncios
        {"handle": "p1", "ids": ["1"]},  # repetida: vale a primeira
        {"handle": "p3", "ids": ["5"]}]) + "\n{cortada", encoding="utf-8")
    return db, compat


def _linhas(db, id_peca):
    return [tuple(l) for l in db.execute("SELECT id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo WHERE id_peca = ? "
                                         "ORDER BY id_versao IS NOT NULL, id_versao, ano_inicio", (id_peca,))]


def test_ligar_nivel_versao(tmp_path):
    db, compat = _base(tmp_path)
    r = ligar_versao(db, Arvore(db), compat)
    v4x2 = db.execute("SELECT id_versao FROM veiculo_versao WHERE nome LIKE '4X2%'").fetchone()[0]
    assert _linhas(db, 1) == [(None, 2020, 2021, "versao")]
    assert _linhas(db, 2) == [(None, 2020, 2020, "versao"), (v4x2, 2021, 2021, "versao")]
    assert _linhas(db, 3) == []  # peça inativa
    assert r["ids_desconhecidos"] == 1 and r["pecas_nivel_versao"] == 2
    assert {i[1] for i in db.execute("PRAGMA index_list(peca_veiculo)")} >= {"peca_veiculo_peca", "peca_veiculo_modelo"}


def test_sem_arquivo_de_compatibilidade(tmp_path):
    db, _ = _base(tmp_path)
    r = ligar_versao(db, Arvore(db), tmp_path / "nao_existe.jsonl")
    assert r["pecas_nivel_versao"] == 0 and r["handles_sem_compat"] == 3  # p3 é de peça inativa: nem entra
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_veiculos_ligar.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'helper.veiculos_ligar'`

- [ ] **Step 3: Implementar**

`helper/veiculos_ligar.py`:

```python
"""Ligação peça -> veículo (spec de veículos, seções 5.3 e 5.4): nível 'versao' pela compatibilidade do KarHub,
nível 'modelo' pelas aplicações em texto. karhub_compat.jsonl tem centenas de MB: é lido em fluxo."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from helper.banco import INDICES_PECA_VEICULO
from helper.veiculo_tipo import normalizar

LOTE = 20000


def faixas(selecionados, universo):
    """Anos de `selecionados` em faixas contínuas dentro da sequência ordenada `universo`
    (um ano que não está no universo não quebra a faixa)."""
    sel, saida, atual = set(selecionados), [], None
    for ano in universo:
        if ano in sel:
            atual = (ano, ano) if atual is None else (atual[0], ano)
        elif atual is not None:
            saida.append(atual)
            atual = None
    if atual is not None:
        saida.append(atual)
    return saida


def agrupar(versoes_por_ano, anos_por_versao, atendidas_por_ano):
    """versoes_por_ano: {ano: {id_versao}} do modelo; anos_por_versao: {id_versao: [anos ordenados]};
    atendidas_por_ano: {ano: {id_versao}} da peça. -> [(id_versao ou None = todas, ano_inicio, ano_fim)]."""
    anos_modelo = sorted(versoes_por_ano)
    completos = {a for a in anos_modelo if atendidas_por_ano.get(a) and versoes_por_ano[a] <= atendidas_por_ano[a]}
    linhas = [(None, i, f) for i, f in faixas(completos, anos_modelo)]
    restantes = defaultdict(list)
    for ano, versoes in atendidas_por_ano.items():
        if ano not in completos:
            for v in versoes:
                restantes[v].append(ano)
    for v in sorted(restantes):
        linhas += [(v, i, f) for i, f in faixas(restantes[v], anos_por_versao[v])]
    return linhas


def handle_da_url(url):
    return urlsplit(url or "").path.rsplit("/", 1)[-1]


class Arvore:
    """A árvore ativa em memória: tradução do id do KarHub e nomes de modelo por montadora."""

    def __init__(self, db):
        self.fonte = {}  # id_fonte -> (id_modelo, id_versao, ano)
        self.versoes_por_ano = defaultdict(lambda: defaultdict(set))  # id_modelo -> ano -> {id_versao}
        self.anos_por_versao = defaultdict(list)
        for id_fonte, id_versao, ano, id_modelo in db.execute(
                """SELECT f.id_fonte, f.id_versao, f.ano, v.id_modelo FROM veiculo_fonte f
                   JOIN veiculo_versao v USING (id_versao) JOIN veiculo_modelo m USING (id_modelo)
                   WHERE f.site = 'karhub' AND v.ativo = 1 AND m.ativo = 1"""):
            self.fonte[id_fonte] = (id_modelo, id_versao, ano)
        for id_versao, ano, id_modelo in db.execute(
                """SELECT va.id_versao, va.ano, v.id_modelo FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao)
                   WHERE v.ativo = 1 ORDER BY va.id_versao, va.ano"""):
            self.versoes_por_ano[id_modelo][ano].add(id_versao)
            self.anos_por_versao[id_versao].append(ano)
        self.modelos = defaultdict(dict)  # nome canônico da montadora -> {nome normalizado do modelo: id_modelo}
        self.modelos_do_nome = defaultdict(set)  # nome normalizado -> {id_modelo} (em qualquer montadora)
        for id_modelo, nome, montadora in db.execute(
                """SELECT mo.id_modelo, mo.nome, vm.nome FROM veiculo_modelo mo
                   JOIN veiculo_montadora vm USING (id_veiculo_montadora) WHERE mo.ativo = 1"""):
            self.modelos[montadora][normalizar(nome)] = id_modelo
            self.modelos_do_nome[normalizar(nome)].add(id_modelo)

    def linhas_versao(self, ids_fonte, contagem):
        por_modelo = defaultdict(lambda: defaultdict(set))
        for i in ids_fonte:
            alvo = self.fonte.get(str(i))
            if alvo is None:  # moto, pesado ou veículo que ainda não está na árvore
                contagem["ids_desconhecidos"] += 1
                continue
            id_modelo, id_versao, ano = alvo
            por_modelo[id_modelo][ano].add(id_versao)
        linhas = []
        for id_modelo in sorted(por_modelo):
            for id_versao, i, f in agrupar(self.versoes_por_ano[id_modelo], self.anos_por_versao, por_modelo[id_modelo]):
                linhas.append((id_modelo, id_versao, i, f, "versao"))
        return linhas

    def modelo_da_aplicacao(self, montadora, modelo):
        """Prefixo mais longo (em palavras) do modelo que é nome de modelo da árvore. Com montadora da árvore, só nela;
        sem montadora (ou fora da árvore), só se o nome existir numa única montadora."""
        palavras = normalizar(modelo).split()
        if montadora and montadora in self.modelos:
            nomes = self.modelos[montadora]
            for n in range(len(palavras), 0, -1):
                if " ".join(palavras[:n]) in nomes:
                    return nomes[" ".join(palavras[:n])]
            return None
        for n in range(len(palavras), 0, -1):
            ids = self.modelos_do_nome.get(" ".join(palavras[:n]))
            if ids:
                return next(iter(ids)) if len(ids) == 1 else None
        return None


def _inserir(db, linhas):
    db.executemany("INSERT INTO peca_veiculo (id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel) VALUES (?, ?, ?, ?, ?, ?)",
                   linhas)


def ligar_versao(db, arvore, caminho_compat):
    r = Counter()
    db.execute("DELETE FROM peca_veiculo")
    for nome in ("peca_veiculo_peca", "peca_veiculo_modelo"):
        db.execute(f"DROP INDEX IF EXISTS {nome}")  # milhões de linhas: os índices voltam no fim
    peca_do_handle = defaultdict(set)
    for id_peca, url in db.execute("SELECT o.id_peca, o.url FROM origem o JOIN peca p USING (id_peca) "
                                   "WHERE o.site = 'karhub' AND p.status = 'ativa'"):
        peca_do_handle[handle_da_url(url)].add(id_peca)
    qtd_handles = Counter(p for pecas in peca_do_handle.values() for p in pecas)
    acumulado, lote, vistos, ligadas = defaultdict(list), [], set(), set()

    def gravar(id_peca, ids):
        linhas = arvore.linhas_versao(ids, r)
        if linhas:
            ligadas.add(id_peca)
        lote.extend((id_peca, *l) for l in linhas)
        if len(lote) >= LOTE:
            _inserir(db, lote)
            lote.clear()

    caminho = Path(caminho_compat)
    if caminho.exists():
        with caminho.open(encoding="utf-8") as f:
            for texto in f:
                try:
                    l = json.loads(texto)
                    handle, ids = l["handle"], l.get("ids") or []
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                if handle in vistos:
                    continue
                vistos.add(handle)
                for id_peca in peca_do_handle.get(handle, ()):
                    if qtd_handles[id_peca] > 1:  # dois anúncios da mesma peça: soma antes de agrupar
                        acumulado[id_peca].extend(ids)
                    else:
                        gravar(id_peca, ids)
    for id_peca in sorted(acumulado):
        gravar(id_peca, acumulado[id_peca])
    _inserir(db, lote)
    for sql in INDICES_PECA_VEICULO:
        db.execute(sql)
    db.commit()
    r["pecas_nivel_versao"] = len(ligadas)
    r["handles_sem_compat"] = len(set(peca_do_handle) - vistos)
    return r
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_veiculos_ligar.py -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Commit**

```bash
git add helper/veiculos_ligar.py tests/test_veiculos_ligar.py
git commit -m "helper: ligação peça -> versão pela compatibilidade do KarHub, agrupada por faixa de anos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Ligação de nível modelo e fechamento

**Files:**
- Modify: `helper/veiculos_ligar.py` (acrescentar ao fim)
- Test: `tests/test_veiculos_ligar.py` (acrescentar)

**Interfaces:**
- Consumes: `Arvore`, `ligar_versao` (Task 8); `Montadoras.canonica` (Task 1); `helper.banco.gravar_meta`, `agora`.
- Produces:
  - `juntar_faixas(faixas: list[tuple[int | None, int | None]]) -> list[tuple]`.
  - `ligar_modelo(db, arvore, montadoras) -> tuple[Counter, Counter]` — contagens (`linhas_nivel_modelo`, `pecas_nivel_modelo`, `aplicacoes_sem_modelo`) e `sem_modelo` (texto da aplicação -> ocorrências).
  - `atualizar_hashes_modelos(db) -> int`.
  - `fechar(db) -> dict` (`pecas_ligadas`, `linhas_peca_veiculo`, `modelos_alterados`); grava `meta.veiculos_em`.
  - `ligar(db, caminho_compat, montadoras) -> tuple[dict, Counter]` — faz versão, modelo e fechamento.

- [ ] **Step 1: Escrever os testes** (acrescentar a `tests/test_veiculos_ligar.py`; trocar o import de `helper.veiculos_ligar` por `from helper.veiculos_ligar import Arvore, agrupar, faixas, juntar_faixas, ligar, ligar_versao` e incluir `from helper.banco import abrir, ler_meta`)

```python
def test_juntar_faixas():
    assert juntar_faixas([(1996, 1998), (1999, 2001), (2005, 2006)]) == [(1996, 2001), (2005, 2006)]
    assert juntar_faixas([(1996, 1998), (None, None)]) == [(None, None)]
    assert juntar_faixas([(2005, None), (2000, 2004)]) == [(2000, None)]
    assert juntar_faixas([(None, 1999), (1998, 2003)]) == [(None, 2003)]


def test_ligar_completo_nivel_modelo_e_fechamento(tmp_path):
    db = abrir(tmp_path / "h.sqlite")
    m = Montadoras({"VW": "VOLKSWAGEN"})
    carregar_arvore(db, [_linha(), _linha(montadora="Volkswagen", mh="volkswagen", modelo="Gol"),
                         _linha(montadora="Ford", mh="ford", modelo="Ka"), _linha(montadora="Kia", mh="kia", modelo="Ka")], m)
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'X', 'reposicao')")
    for i in range(1, 7):
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (?, 1, ?, ?, 'PECA', 'ativa')",
                   (i, f"X|{i}", str(i)))
    db.execute("UPDATE peca SET status = 'inativa' WHERE id_peca = 6")
    db.executemany("INSERT INTO aplicacao (id_peca, montadora, modelo, ano_inicio, ano_fim) VALUES (?, ?, ?, ?, ?)", [
        (1, "VW", "GOL G4", 2006, 2008), (1, "VOLKSWAGEN", "GOL", 2009, 2010),  # junta em 2006-2010
        (2, None, "GOL", 2001, 2000),                                           # sem montadora, nome único; anos invertidos
        (3, None, "KA", 2010, 2012),                                            # sem montadora, KA em Ford e Kia: ambíguo
        (4, "CHEVROLET", "TRACKER", 2021, 2021),                                # já confirmado pelo KarHub
        (5, "FORD", "FIESTA", 2010, 2012),                                      # montadora na árvore, modelo não
        (6, "VW", "GOL", 2000, 2001)])                                          # peça inativa
    db.execute("INSERT INTO origem (id_peca, site, url) VALUES (4, 'karhub', 'https://www.karhub.com.br/p/p4')")
    db.commit()
    compat = tmp_path / "compat.jsonl"
    compat.write_text(json.dumps({"handle": "p4", "ids": ["5"]}) + "\n", encoding="utf-8")
    r, sem_modelo = ligar(db, compat, m)
    gol = db.execute("SELECT id_modelo FROM veiculo_modelo WHERE nome = 'GOL'").fetchone()[0]

    def linhas_de(p):
        return [tuple(l) for l in db.execute("SELECT id_modelo, id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo WHERE id_peca = ?", (p,))]
    assert linhas_de(1) == [(gol, None, 2006, 2010, "modelo")]
    assert linhas_de(2) == [(gol, None, 2000, 2001, "modelo")]
    assert linhas_de(3) == [] and linhas_de(5) == [] and linhas_de(6) == []
    assert [l[4] for l in linhas_de(4)] == ["versao"]  # o texto não repete o que o KarHub confirmou
    assert sem_modelo["KA"] == 1 and sem_modelo["FORD FIESTA"] == 1
    assert r["pecas_nivel_versao"] == 1 and r["pecas_nivel_modelo"] == 2 and r["pecas_ligadas"] == 3
    assert db.execute("SELECT qtd_pecas FROM veiculo_modelo WHERE id_modelo = ?", (gol,)).fetchone()[0] == 2
    assert db.execute("SELECT qtd_pecas FROM veiculo_montadora WHERE nome = 'VOLKSWAGEN'").fetchone()[0] == 2
    assert db.execute("SELECT count(*) FROM peca_veiculo_estado").fetchone()[0] == 3
    assert ler_meta(db, "veiculos_em")
    assert db.execute("SELECT count(*) FROM veiculo_modelo WHERE hash_conteudo IS NULL").fetchone()[0] == 0
    hashes_pecas = dict(db.execute("SELECT id_peca, hash FROM peca_veiculo_estado"))
    hashes_modelos = dict(db.execute("SELECT id_modelo, hash_conteudo FROM veiculo_modelo"))
    r2, _ = ligar(db, compat, m)  # mesma entrada: mesmos hashes, nenhum modelo alterado
    assert dict(db.execute("SELECT id_peca, hash FROM peca_veiculo_estado")) == hashes_pecas
    assert dict(db.execute("SELECT id_modelo, hash_conteudo FROM veiculo_modelo")) == hashes_modelos
    assert r2["modelos_alterados"] == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_veiculos_ligar.py -v`
Expected: FAIL com `ImportError: cannot import name 'juntar_faixas'`

- [ ] **Step 3: Implementar** (acrescentar ao fim de `helper/veiculos_ligar.py`; e trocar o import de `helper.banco` por `from helper.banco import INDICES_PECA_VEICULO, agora, gravar_meta`, e acrescentar `import hashlib` aos imports)

```python
def juntar_faixas(faixas_):
    """[(ini, fim)], None = sem limite. Sem ano nenhum absorve tudo; sobrepostas ou adjacentes se juntam."""
    if any(i is None and f is None for i, f in faixas_):
        return [(None, None)]
    itens = sorted((i if i is not None else 0, f if f is not None else 9999) for i, f in faixas_)
    saida = []
    for i, f in itens:
        if saida and i <= saida[-1][1] + 1:
            saida[-1][1] = max(saida[-1][1], f)
        else:
            saida.append([i, f])
    return [(None if i == 0 else i, None if f == 9999 else f) for i, f in saida]


def ligar_modelo(db, arvore, montadoras):
    r, sem_modelo, pares = Counter(), Counter(), defaultdict(list)
    for id_peca, montadora, modelo, ini, fim in db.execute(
            "SELECT a.id_peca, a.montadora, a.modelo, a.ano_inicio, a.ano_fim FROM aplicacao a "
            "JOIN peca p USING (id_peca) WHERE p.status = 'ativa'"):
        id_modelo = arvore.modelo_da_aplicacao(montadoras.canonica(montadora), modelo)
        if id_modelo is None:
            sem_modelo[f"{montadora or ''} {modelo}".strip()] += 1
            continue
        if ini is not None and fim is not None and ini > fim:
            ini, fim = fim, ini
        pares[(id_peca, id_modelo)].append((ini, fim))
    db.execute("CREATE TEMP TABLE IF NOT EXISTS candidato_modelo (id_peca INTEGER, id_modelo INTEGER, ano_inicio INTEGER, ano_fim INTEGER)")
    db.execute("DELETE FROM candidato_modelo")
    db.executemany("INSERT INTO candidato_modelo VALUES (?, ?, ?, ?)",
                   ((p, m, i, f) for (p, m), fx in pares.items() for i, f in juntar_faixas(fx)))
    # par (peça, modelo) já confirmado pelo KarHub não ganha linha de texto
    r["linhas_nivel_modelo"] = db.execute(
        """INSERT INTO peca_veiculo (id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel)
           SELECT c.id_peca, c.id_modelo, NULL, c.ano_inicio, c.ano_fim, 'modelo' FROM candidato_modelo c
           WHERE NOT EXISTS (SELECT 1 FROM peca_veiculo pv
                             WHERE pv.id_peca = c.id_peca AND pv.id_modelo = c.id_modelo AND pv.nivel = 'versao')""").rowcount
    db.commit()
    r["pecas_nivel_modelo"] = db.execute("SELECT count(DISTINCT id_peca) FROM peca_veiculo WHERE nivel = 'modelo'").fetchone()[0]
    r["aplicacoes_sem_modelo"] = sum(sem_modelo.values())
    return r, sem_modelo


def _hash(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False).encode()).hexdigest()


def atualizar_hashes_modelos(db):
    anos, versoes = defaultdict(list), defaultdict(list)
    for id_versao, ano in db.execute("SELECT id_versao, ano FROM veiculo_versao_ano ORDER BY id_versao, ano"):
        anos[id_versao].append(ano)
    for v in db.execute("SELECT id_versao, id_modelo, nome, nome_exibicao, motor, ativo FROM veiculo_versao ORDER BY id_versao"):
        versoes[v["id_modelo"]].append([v["id_versao"], v["nome"], v["nome_exibicao"], v["motor"], v["ativo"], anos[v["id_versao"]]])
    mudados = []
    for m in db.execute("""SELECT mo.*, vm.nome AS montadora FROM veiculo_modelo mo
                           JOIN veiculo_montadora vm USING (id_veiculo_montadora)""").fetchall():
        h = _hash([m["montadora"], m["id_veiculo_montadora"], m["nome"], m["nome_exibicao"], m["foto"], m["foto_herdada"],
                   m["ano_inicio"], m["ano_fim"], m["qtd_pecas"], m["ativo"], versoes[m["id_modelo"]]])
        if h != m["hash_conteudo"]:
            mudados.append((h, agora(), m["id_modelo"]))
    db.executemany("UPDATE veiculo_modelo SET hash_conteudo = ?, atualizado_em = ? WHERE id_modelo = ?", mudados)
    return len(mudados)


def fechar(db):
    db.execute("UPDATE veiculo_modelo SET qtd_pecas = (SELECT count(DISTINCT pv.id_peca) FROM peca_veiculo pv "
               "WHERE pv.id_modelo = veiculo_modelo.id_modelo)")
    db.execute("""UPDATE veiculo_montadora SET qtd_pecas = (
                    SELECT count(DISTINCT pv.id_peca) FROM peca_veiculo pv JOIN veiculo_modelo mo ON mo.id_modelo = pv.id_modelo
                    WHERE mo.id_veiculo_montadora = veiculo_montadora.id_veiculo_montadora)""")
    estados, atual, linhas, total = [], None, [], 0
    for l in db.execute("SELECT id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo "
                        "ORDER BY id_peca, id_modelo, nivel, id_versao, ano_inicio"):
        total += 1
        if l[0] != atual:
            if atual is not None:
                estados.append((atual, _hash(linhas)))
            atual, linhas = l[0], []
        linhas.append(list(l[1:]))
    if atual is not None:
        estados.append((atual, _hash(linhas)))
    db.execute("DELETE FROM peca_veiculo_estado")
    db.executemany("INSERT INTO peca_veiculo_estado (id_peca, hash) VALUES (?, ?)", estados)
    alterados = atualizar_hashes_modelos(db)
    gravar_meta(db, "veiculos_em", agora())
    db.commit()
    return {"pecas_ligadas": len(estados), "linhas_peca_veiculo": total, "modelos_alterados": alterados}


def ligar(db, caminho_compat, montadoras):
    arvore = Arvore(db)
    r = dict(ligar_versao(db, arvore, caminho_compat))
    r_modelo, sem_modelo = ligar_modelo(db, arvore, montadoras)
    r.update(r_modelo)
    r.update(fechar(db))
    return r, sem_modelo
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_veiculos_ligar.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Commit**

```bash
git add helper/veiculos_ligar.py tests/test_veiculos_ligar.py
git commit -m "helper: ligação peça -> modelo pelas aplicações, qtd_pecas e hashes para publicar por diferença

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Consulta por veículo no SQLite

**Files:**
- Modify: `helper/consulta.py` (acrescentar ao fim)
- Test: `tests/test_consulta.py` (acrescentar)

**Interfaces:**
- Consumes: `peca_veiculo`, `peca`, `marca`.
- Produces:
  - `ids_por_veiculo(db, id_modelo, ano, id_versao=None) -> dict[int, str]` — `id_peca -> confianca` (`versao`, `todas_versoes`, `algumas_versoes`, `modelo_ano`); só peças ativas.
  - `pecas_por_veiculo(db, id_modelo, ano, id_versao=None, texto=None, limite=100) -> list[dict]` — chaves `id_peca, id_marca, marca, codigo, ean, desc_curta, desc_completa, tipo_peca, ncm_sugerido, unidade_sugerida, tem_foto, qtd_fontes, confianca`; ordem: confiança, `tem_foto` desc, `qtd_fontes` desc, `id_peca`.

- [ ] **Step 1: Escrever os testes** (acrescentar a `tests/test_consulta.py`; incluir `ids_por_veiculo, pecas_por_veiculo` no import de `helper.consulta`)

```python
def _db_veiculo(tmp_path):
    db = abrir(tmp_path / "v.sqlite")
    db.execute("INSERT INTO marca (id_marca, nome, tipo) VALUES (1, 'FREMAX', 'reposicao')")
    for id_peca, desc, foto, fontes in [(1, "TAMBOR FREIO", 1, 5), (2, "TAMBOR FREIO", 0, 9), (3, "PASTILHA FREIO", 0, 1),
                                        (4, "TAMBOR FREIO", 0, 2), (5, "TAMBOR FREIO", 1, 1), (6, "TAMBOR FREIO", 1, 3)]:
        db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, tem_foto, qtd_fontes, status) "
                   "VALUES (?, 1, ?, ?, ?, ?, ?, 'ativa')", (id_peca, f"F|{id_peca}", str(id_peca), desc, foto, fontes))
    db.execute("UPDATE peca SET status = 'inativa' WHERE id_peca = 6")
    db.executemany("INSERT INTO peca_veiculo VALUES (?, ?, ?, ?, ?, ?)", [
        (1, 10, None, 2020, 2022, "versao"),   # todas as versões
        (2, 10, 100, 2021, 2021, "versao"),    # só a versão 100
        (3, 10, None, None, None, "modelo"),   # texto, qualquer ano
        (4, 10, None, 2015, 2019, "modelo"),   # texto, outros anos
        (5, 10, 200, 2021, 2021, "versao"), (5, 10, None, 2010, 2012, "versao"),
        (6, 10, None, 2020, 2022, "versao")])  # peça inativa
    db.commit()
    return db


def test_confianca_sem_versao(tmp_path):
    assert ids_por_veiculo(_db_veiculo(tmp_path), 10, 2021) == {1: "todas_versoes", 2: "algumas_versoes", 3: "modelo_ano",
                                                                 5: "algumas_versoes"}


def test_confianca_com_versao_tira_quem_o_karhub_diz_que_nao_serve(tmp_path):
    db = _db_veiculo(tmp_path)
    assert ids_por_veiculo(db, 10, 2021, 100) == {1: "versao", 2: "versao", 3: "modelo_ano"}
    assert ids_por_veiculo(db, 10, 2021, 200) == {1: "versao", 3: "modelo_ano", 5: "versao"}
    assert ids_por_veiculo(db, 10, 2016) == {3: "modelo_ano", 4: "modelo_ano"}
    assert ids_por_veiculo(db, 99, 2021) == {}


def test_pecas_por_veiculo_texto_ordem_e_limite(tmp_path):
    db = _db_veiculo(tmp_path)
    r = pecas_por_veiculo(db, 10, 2021, texto="tambor")
    assert [p["id_peca"] for p in r] == [1, 5, 2]  # todas_versoes; depois algumas_versoes com foto antes
    assert r[0]["marca"] == "FREMAX" and r[0]["confianca"] == "todas_versoes" and "origem" not in r[0]
    assert [p["id_peca"] for p in pecas_por_veiculo(db, 10, 2021, texto="pastilha")] == [3]
    assert len(pecas_por_veiculo(db, 10, 2021, limite=1)) == 1
    assert pecas_por_veiculo(db, 99, 2021) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_consulta.py -v`
Expected: FAIL com `ImportError: cannot import name 'ids_por_veiculo'`

- [ ] **Step 3: Implementar** (ao fim de `helper/consulta.py`; acrescentar aos imports `from collections import defaultdict` e `from wayap_fotos import sem_acento`)

```python
# ---------- consultas 8 e 9 da spec de veículos (o Postgres implementa as mesmas regras em publicar.py) ----------

ORDEM_CONFIANCA = {"versao": 1, "todas_versoes": 1, "algumas_versoes": 2, "modelo_ano": 3}


def ids_por_veiculo(db, id_modelo, ano, id_versao=None):
    versao = defaultdict(lambda: {"todas": False, "esta": False})
    for id_peca, v in db.execute(
            """SELECT pv.id_peca, pv.id_versao FROM peca_veiculo pv JOIN peca p USING (id_peca)
               WHERE pv.id_modelo = ? AND pv.nivel = 'versao' AND ? BETWEEN pv.ano_inicio AND pv.ano_fim AND p.status = 'ativa'""",
            (id_modelo, ano)):
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
            """SELECT DISTINCT pv.id_peca FROM peca_veiculo pv JOIN peca p USING (id_peca)
               WHERE pv.id_modelo = ? AND pv.nivel = 'modelo' AND p.status = 'ativa'
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_consulta.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add helper/consulta.py tests/test_consulta.py
git commit -m "helper: consulta de peças por veículo com confiança, no SQLite

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Relatório e comandos `veiculos` e `pecas-do-veiculo`

**Files:**
- Create: `helper/veiculos_relatorio.py`
- Modify: `helper/cli.py`
- Test: `tests/test_cli.py` (acrescentar)

**Interfaces:**
- Consumes: `veiculos.ler_arvore`, `carregar_arvore` (Task 6); `veiculos_fotos.processar_imagens` (Task 7); `veiculos_ligar.ligar` (Task 9); `consulta.pecas_por_veiculo` (Task 10); `relatorio.salvar` (existente); `Montadoras`, `nome_canonico` (Task 1).
- Produces:
  - `veiculos_relatorio.salvar_tipos_csv(pasta_veiculos, destino) -> Counter[(tipo, motivo)]`.
  - `veiculos_relatorio.gerar(db, estat: dict, tipos: Counter, sem_modelo: Counter) -> str`.
  - CLI: `python helper.py veiculos [--base] [--banco] [--montadoras]` (código 2 sem `veiculos/karhub_arvore.jsonl`); `python helper.py pecas-do-veiculo MONTADORA MODELO ANO [--versao] [--texto] [--limite]` (código 1 quando não acha).
  - Opção comum nova `--montadoras` (padrão `helper_montadoras.csv` do repositório).

- [ ] **Step 1: Escrever os testes** (acrescentar a `tests/test_cli.py`)

```python
def _arvore_gol(tmp_path):
    arvore = {"montadora": {"label": "Volkswagen", "handle": "volkswagen", "logo_url": None},
              "modelo": {"label": "Gol", "handle": "Gol", "foto_url": None}, "tipo": "carro", "motivo_tipo": "fipe",
              "anos": [{"ano": a, "versoes": [{"label": "1.0 8v", "handle": "x", "ids_fonte": [str(a)]}]} for a in (1999, 2000, 2001)],
              "coletado_em": "2026-10-03"}
    _escrever(tmp_path / "veiculos/karhub_arvore.jsonl", json.dumps(arvore) + "\n")
    _escrever(tmp_path / "veiculos/karhub_excluidos.jsonl", json.dumps({
        "montadora": {"label": "Honda", "handle": "honda"}, "modelo": {"label": "Biz", "handle": "Biz"},
        "tipo": "moto", "motivo_tipo": "versao", "versoes_exemplo": ["Ks 100cc"], "coletado_em": "2026-10-03"}) + "\n")
    # o anúncio da KarHub em _montar_base tem url https://k/p/1: handle "1"
    _escrever(tmp_path / "veiculos/karhub_compat.jsonl", json.dumps({"handle": "1", "ids": ["1999", "2000"]}) + "\n")


def test_veiculos_ponta_a_ponta(tmp_path, capsys):
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    _arvore_gol(tmp_path)
    assert main(["veiculos", "--base", str(tmp_path)]) == 0
    db = abrir(tmp_path / "helper.sqlite")
    gc = db.execute("SELECT id_peca FROM peca WHERE codigo = 'GC5045'").fetchone()[0]
    assert [tuple(l) for l in db.execute("SELECT id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo WHERE id_peca = ?", (gc,))] == \
        [(None, 1999, 2000, "versao")]
    farol = db.execute("SELECT id_peca FROM peca WHERE codigo = '0160818'").fetchone()[0]
    assert [tuple(l) for l in db.execute("SELECT ano_inicio, ano_fim, nivel FROM peca_veiculo WHERE id_peca = ?", (farol,))] == \
        [(1995, 1999, "modelo")]
    rel = list((tmp_path / "helper_relatorios").glob("*-veiculos.md"))[0].read_text(encoding="utf-8")
    assert "Modelos ativos: 1" in rel and "| moto | versao | 1 |" in rel
    tipos = list((tmp_path / "helper_relatorios").glob("*-veiculos-tipos.csv"))[0].read_text(encoding="utf-8")
    assert "Honda;Biz;moto;versao;Ks 100cc" in tipos and "Volkswagen;Gol;carro;fipe;1.0 8v" in tipos


def test_veiculos_sem_arvore_avisa(tmp_path):
    _montar_base(tmp_path)
    assert main(["veiculos", "--base", str(tmp_path)]) == 2


def test_pecas_do_veiculo_aceita_o_jeito_do_usuario(tmp_path, capsys):
    _montar_base(tmp_path)
    main(["preparar", "--base", str(tmp_path)])
    _arvore_gol(tmp_path)
    main(["veiculos", "--base", str(tmp_path)])
    capsys.readouterr()
    assert main(["pecas-do-veiculo", "volkswagen", "gol", "2000", "--base", str(tmp_path)]) == 0
    saida = capsys.readouterr().out
    assert "todas_versoes" in saida and "GC5045" in saida
    assert main(["pecas-do-veiculo", "vw", "Gol", "1997", "--base", str(tmp_path)]) == 0  # 1997: só o texto da Arteb
    assert "modelo_ano" in capsys.readouterr().out
    assert main(["pecas-do-veiculo", "VW", "GOL", "2000", "--versao", "1.0 8V", "--texto", "cabo", "--base", str(tmp_path)]) == 0
    saida = capsys.readouterr().out
    assert "versao" in saida and "GC5045" in saida and "0160818" not in saida
    assert main(["pecas-do-veiculo", "VW", "FUSCA", "2000", "--base", str(tmp_path)]) == 1
    assert main(["pecas-do-veiculo", "VW", "GOL", "2000", "--versao", "2.0 turbo", "--base", str(tmp_path)]) == 1
    assert "1.0 8v" in capsys.readouterr().out  # lista as versões do ano
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL com `SystemExit: 2` (argparse: `invalid choice: 'veiculos'`)

- [ ] **Step 3: Implementar**

`helper/veiculos_relatorio.py`:

```python
"""Relatório do `helper.py veiculos` (markdown) e planilha com o tipo de todos os modelos coletados."""
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path


def _jsonl(caminho):
    caminho = Path(caminho)
    if not caminho.exists():
        return []
    saida = []
    for texto in caminho.read_text(encoding="utf-8").splitlines():
        try:
            saida.append(json.loads(texto))
        except json.JSONDecodeError:
            continue
    return saida


def _primeira_versao(linha):
    for a in linha.get("anos") or []:
        if a["versoes"]:
            return a["versoes"][0]["label"]
    return ""


def salvar_tipos_csv(pasta_veiculos, destino):
    pasta = Path(pasta_veiculos)
    linhas = [(l["montadora"]["label"], l["modelo"]["label"], l.get("tipo", "carro"), l.get("motivo_tipo", ""), _primeira_versao(l))
              for l in _jsonl(pasta / "karhub_arvore.jsonl")]
    linhas += [(l["montadora"]["label"], l["modelo"]["label"], l.get("tipo", ""), l.get("motivo_tipo", ""),
                (l.get("versoes_exemplo") or [""])[0]) for l in _jsonl(pasta / "karhub_excluidos.jsonl")]
    with Path(destino).open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\n")
        w.writerow(["montadora", "modelo", "tipo", "motivo", "versao_exemplo"])
        w.writerows(sorted(linhas))
    return Counter((t, m) for _, _, t, m, _ in linhas)


def gerar(db, estat, tipos, sem_modelo):
    def um(sql):
        return db.execute(sql).fetchone()[0]
    img, lig = estat.get("imagens", {}), estat.get("ligacao", {})
    por_nivel = dict(db.execute("SELECT nivel, count(*) FROM peca_veiculo GROUP BY nivel").fetchall())
    L = [f"# Helper: veículos em {date.today().isoformat()}", "", "## Árvore", "",
         f"- Montadoras ativas: {um('SELECT count(*) FROM veiculo_montadora WHERE ativo = 1')}",
         f"- Modelos ativos: {um('SELECT count(*) FROM veiculo_modelo WHERE ativo = 1')}",
         f"- Versões ativas: {um('SELECT count(*) FROM veiculo_versao WHERE ativo = 1')}",
         f"- Anos-versão: {um('SELECT count(*) FROM veiculo_versao_ano')}", "",
         "## Tipos (incluídos e excluídos)", "", "| tipo | motivo | modelos |", "|---|---|---|"]
    L += [f"| {t} | {m} | {n} |" for (t, m), n in sorted(tipos.items())]
    L += ["", "Planilha completa em `<data>-veiculos-tipos.csv`; correções vão em `helper_veiculos_tipo.csv`.", "",
          "## Montadoras", "",
          f"- Ligadas à `montadoras` do Wayap (na última publicação): "
          f"{um('SELECT count(*) FROM veiculo_montadora WHERE ativo = 1 AND id_montadora IS NOT NULL')}",
          "- Sem par no Wayap: " + (", ".join(r[0] for r in db.execute(
              "SELECT nome FROM veiculo_montadora WHERE ativo = 1 AND id_montadora IS NULL ORDER BY nome")) or "nenhuma"), "",
          "## Imagens", "",
          f"- Fotos de modelo: do KarHub {img.get('foto_karhub', 0)}, próprias {img.get('foto_propria', 0)}, "
          f"herdadas {img.get('foto_herdada', 0)}, sem foto {img.get('foto_sem', 0)}, inválidas {img.get('foto_invalida', 0)}",
          f"- Logos: do KarHub {img.get('logo_karhub', 0)}, próprios {img.get('logo_propria', 0)}, "
          f"sem logo {img.get('logo_sem', 0)}, inválidos {img.get('logo_invalida', 0)}", "",
          "### 100 modelos com mais peças sem foto (candidatos a foto própria)", "", "| montadora | modelo | peças |", "|---|---|---|"]
    L += [f"| {a} | {b} | {n} |" for a, b, n in db.execute(
        """SELECT vm.nome, mo.nome, mo.qtd_pecas FROM veiculo_modelo mo JOIN veiculo_montadora vm USING (id_veiculo_montadora)
           WHERE mo.ativo = 1 AND mo.foto IS NULL ORDER BY mo.qtd_pecas DESC, vm.nome, mo.nome LIMIT 100""")]
    L += ["", "## Ligação peça → veículo", "",
          f"- Peças com nível versão (KarHub): {lig.get('pecas_nivel_versao', 0)}",
          f"- Peças com nível modelo (texto de aplicação): {lig.get('pecas_nivel_modelo', 0)}",
          f"- Linhas de peca_veiculo: {sum(por_nivel.values())} "
          f"(versão {por_nivel.get('versao', 0)}, modelo {por_nivel.get('modelo', 0)})",
          f"- Ids de veículo fora da árvore (motos, pesados ou novos): {lig.get('ids_desconhecidos', 0)}",
          f"- Anúncios do KarHub sem linha de compatibilidade: {lig.get('handles_sem_compat', 0)}",
          f"- Aplicações que não casaram com modelo: {lig.get('aplicacoes_sem_modelo', 0)}", "",
          "### 50 aplicações mais comuns sem modelo", "", "| aplicação | ocorrências |", "|---|---|"]
    L += [f"| {texto} | {n} |" for texto, n in sem_modelo.most_common(50)]
    return "\n".join(L) + "\n"
```

Em `helper/cli.py`:

1. Imports: trocar `from helper import banco, consulta, fontes, fusao, relatorio, topcar` por
   `from helper import banco, consulta, fontes, fusao, relatorio, topcar, veiculos, veiculos_fotos, veiculos_ligar, veiculos_relatorio`
   e acrescentar `from helper.montadoras import ARQUIVO_PADRAO as MONTADORAS_PADRAO, Montadoras, nome_canonico`.

2. Em `_args_comuns`, acrescentar:

```python
    p.add_argument("--montadoras", type=Path, default=MONTADORAS_PADRAO, help="apelidos de montadora (helper_montadoras.csv)")
```

3. Acrescentar as funções (antes de `def main`):

```python
def cmd_veiculos(args):
    inicio = time.time()
    pasta = args.base / "veiculos"
    arq_arvore = pasta / "karhub_arvore.jsonl"
    if not arq_arvore.exists():
        print(f"sem {arq_arvore}: rode python catalogo_karhub_veiculos.py fipe e depois arvore", file=sys.stderr)
        return 2
    db = banco.abrir(args.banco)
    montadoras = Montadoras.carregar(args.montadoras)
    estat = {"arvore": veiculos.carregar_arvore(db, veiculos.ler_arvore(arq_arvore), montadoras)}
    print("árvore:", ", ".join(f"{k} {v}" for k, v in estat["arvore"].items()))
    estat["imagens"] = veiculos_fotos.processar_imagens(db, pasta / "imagens", args.base / "helper_fotos_veiculos")
    print("imagens:", ", ".join(f"{k} {v}" for k, v in sorted(estat["imagens"].items())))
    estat["ligacao"], sem_modelo = veiculos_ligar.ligar(db, pasta / "karhub_compat.jsonl", montadoras)
    print("ligação:", ", ".join(f"{k} {v}" for k, v in sorted(estat["ligacao"].items())))
    args.relatorios.mkdir(parents=True, exist_ok=True)
    tipos = veiculos_relatorio.salvar_tipos_csv(pasta, args.relatorios / f"{time.strftime('%Y-%m-%d')}-veiculos-tipos.csv")
    caminho = relatorio.salvar(veiculos_relatorio.gerar(db, estat, tipos, sem_modelo), args.relatorios, "veiculos.md")
    print(f"relatório em {caminho}; {time.time() - inicio:.0f}s")
    return 0


def cmd_pecas_do_veiculo(args):
    db = banco.abrir(args.banco)
    montadora = Montadoras.carregar(args.montadoras).canonica(args.montadora)
    modelo = db.execute("""SELECT mo.id_modelo FROM veiculo_modelo mo JOIN veiculo_montadora vm USING (id_veiculo_montadora)
                           WHERE vm.nome = ? AND mo.nome = ? AND mo.ativo = 1""", (montadora, nome_canonico(args.modelo))).fetchone()
    if not modelo:
        print(f"modelo não encontrado: {montadora} {nome_canonico(args.modelo)}", file=sys.stderr)
        return 1
    id_versao = None
    if args.versao:
        versao = db.execute("SELECT id_versao FROM veiculo_versao WHERE id_modelo = ? AND nome = ? AND ativo = 1",
                            (modelo[0], nome_canonico(args.versao))).fetchone()
        if not versao:
            print(f"versão não encontrada: {args.versao}. Versões de {args.ano}:")
            for (nome,) in db.execute("""SELECT v.nome_exibicao FROM veiculo_versao v JOIN veiculo_versao_ano va USING (id_versao)
                                         WHERE v.id_modelo = ? AND va.ano = ? AND v.ativo = 1 ORDER BY 1""", (modelo[0], args.ano)):
                print(f"  {nome}")
            return 1
        id_versao = versao[0]
    pecas = consulta.pecas_por_veiculo(db, modelo[0], args.ano, id_versao, args.texto, args.limite)
    for p in pecas:
        print(f"{p['confianca']:<16} {p['marca'][:20]:<20} {(p['codigo'] or ''):<18} {p['desc_curta']}")
    print(f"{len(pecas)} peças")
    return 0
```

4. Em `main`, depois do bloco do subcomando `cobertura`, acrescentar:

```python
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

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add helper/veiculos_relatorio.py helper/cli.py tests/test_cli.py
git commit -m "helper: comandos veiculos e pecas-do-veiculo, relatório e planilha de tipos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Esquema Postgres de veículos (tabelas, views, funções)

**Files:**
- Modify: `helper/publicar.py`
- Test: `tests/test_publicar.py` (acrescentar)

**Interfaces:**
- Consumes: `DDL_POSTGRES` e `funcoes_sql` existentes (a view `v_peca` precisa existir antes de `pecas_por_veiculo`).
- Produces:
  - `ddl_veiculos(tem_montadoras: bool) -> list[str]` — tabelas, índices, colunas novas em `carga`, views `v_veiculo_montadora` (logo do Wayap primeiro quando `tem_montadoras`) e `v_veiculo_modelo`.
  - `funcoes_veiculos(com_trgm: bool) -> list[str]` — `anos_do_modelo`, `versoes_do_ano`, `ids_por_veiculo`, `pecas_por_veiculo`.
  - `instalar_esquema(con)` passa a criar também o esquema de veículos (descobre sozinho se a tabela `montadoras` existe).

- [ ] **Step 1: Escrever os testes** (acrescentar a `tests/test_publicar.py`; incluir `ddl_veiculos, funcoes_veiculos` no import de `helper.publicar`)

```python
def test_ddl_de_veiculos_e_funcoes_do_contrato():
    ddl = "\n".join(ddl_veiculos(tem_montadoras=True))
    for t in ("veiculo_montadora", "veiculo_modelo", "veiculo_versao", "veiculo_versao_ano", "peca_veiculo", "peca_veiculo_estado"):
        assert f"CREATE TABLE IF NOT EXISTS {t} (" in ddl
    assert "coalesce(w.logo, vm.logo)" in ddl and "LEFT JOIN montadoras w" in ddl
    assert "montadoras w" not in "\n".join(ddl_veiculos(tem_montadoras=False))
    fs = "\n".join(funcoes_veiculos(True))
    tudo = ddl + fs
    for comando in ("INSERT INTO montadoras", "UPDATE montadoras", "DELETE FROM montadoras", "ALTER TABLE montadoras",
                    "CREATE TABLE IF NOT EXISTS montadoras"):
        assert comando not in tudo  # o helper nunca escreve na tabela do Wayap
    for f in ("anos_do_modelo", "versoes_do_ano", "ids_por_veiculo", "pecas_por_veiculo"):
        assert f"FUNCTION {f}" in fs
    assert "veiculo_fonte" not in tudo and "origem" not in fs
    assert "similarity" in fs and "similarity" not in "\n".join(funcoes_veiculos(False))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_publicar.py -v -k veiculos`
Expected: FAIL com `ImportError: cannot import name 'ddl_veiculos'`

- [ ] **Step 3: Implementar** (em `helper/publicar.py`, depois de `funcoes_sql`)

```python
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
```

E em `instalar_esquema`, trocar o laço `for sql in DDL_POSTGRES + funcoes_sql(com_trgm):` por:

```python
        cur.execute("SELECT to_regclass('public.montadoras') IS NOT NULL")
        tem_montadoras = bool(cur.fetchone()[0])  # tabela do Wayap: só lida pela view v_veiculo_montadora
        for sql in DDL_POSTGRES + ddl_veiculos(tem_montadoras) + funcoes_sql(com_trgm) + funcoes_veiculos(com_trgm):
            cur.execute(sql)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_publicar.py -v`
Expected: PASS (o teste de integração continua pulado sem `HELPER_TESTE_PG`)

- [ ] **Step 5: Commit**

```bash
git add helper/publicar.py tests/test_publicar.py
git commit -m "helper: esquema Postgres de veículos, views e funções do contrato

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Publicação de veículos por diferença

**Files:**
- Modify: `helper/publicar.py`
- Modify: `helper/cli.py` (função `cmd_publicar`)
- Test: `tests/test_publicar.py` (acrescentar)

**Interfaces:**
- Consumes: `diferencas`, `comando_rsync`, `_linhas` (existentes em `publicar.py`); `helper.banco.ler_meta`; `helper.montadoras.casar_wayap`; tabelas locais preenchidas pelas Tasks 6, 7 e 9; tabelas Postgres da Task 12.
- Produces:
  - `comando_rsync(origem, destino_ssh, pasta_remota, excluir=())` — cada item vira `--exclude=<item>` antes dos caminhos.
  - `veiculos_preparados(db) -> bool` — `False` se o `veiculos` nunca rodou; `RuntimeError` se `veiculos_em < preparado_em`.
  - `publicar_veiculos(db, con, ensaio, executar_rsync, pasta_fotos, destino_ssh, pasta_remota, lote_pecas=5000) -> dict` com `montadoras`, `modelos`, `pecas_veiculo`, `pecas_veiculo_apagar`, `arquivos_veiculo` e, fora do ensaio, `ligacoes_gravadas`.
  - `cmd_publicar` recusa (código 2) `veiculos` desatualizado antes de qualquer gravação e publica veículos depois das peças. Pasta remota: `HELPER_VEICULOS_DIR` (padrão `/home/wayap/helper/veiculos`).

- [ ] **Step 1: Escrever os testes** (acrescentar a `tests/test_publicar.py`; incluir `publicar_veiculos, veiculos_preparados` no import de `helper.publicar` e `from helper.banco import abrir, gravar_meta`)

```python
class ConVeiculos(ConFalsa):
    """Responde às leituras da publicação de veículos com o estado 'remoto' dado e guarda o que vai por COPY."""
    def __init__(self, montadoras_wayap=(), remoto_montadoras=(), remoto_modelos=(), remoto_estado=()):
        super().__init__(remoto={})
        self.respostas = {"FROM montadoras": list(montadoras_wayap), "FROM veiculo_montadora": list(remoto_montadoras),
                          "FROM veiculo_modelo": list(remoto_modelos), "FROM peca_veiculo_estado": list(remoto_estado)}
        self.copias = []

    def fetchall(self):
        for trecho, linhas in self.respostas.items():
            if trecho in self._ultimo:
                return linhas
        return super().fetchall()

    def fetchone(self):
        return (True,)  # to_regclass: a tabela montadoras do Wayap existe

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
    id_modelo = db.execute("SELECT id_modelo FROM veiculo_modelo").fetchone()[0]
    db.execute("INSERT INTO peca_veiculo VALUES (1, ?, NULL, 2020, 2021, 'versao')", (id_modelo,))
    db.execute("UPDATE veiculo_modelo SET foto = 'veiculos/modelos/1_abc.webp'")
    db.execute("INSERT INTO veiculo_arquivo (caminho) VALUES ('veiculos/modelos/1_abc.webp')")
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
    assert db.execute("SELECT id_montadora FROM veiculo_montadora").fetchone()[0] == 11
    assert any(s.startswith("INSERT INTO veiculo_modelo") for s in con.sql) and any(s.startswith("COPY peca_veiculo") for s in con.sql)
    assert con.copias[0].startswith("1\t") and "\\N" in con.copias[0]
    assert not any(s.startswith(("INSERT INTO montadoras", "UPDATE montadoras", "DELETE FROM montadoras")) for s in con.sql)
    assert (r["modelos"], r["pecas_veiculo"], r["arquivos_veiculo"], r["ligacoes_gravadas"]) == (1, 1, 1, 1)
    assert db.execute("SELECT publicado FROM veiculo_arquivo").fetchone()[0] == 1


def test_segunda_publicacao_de_veiculos_nao_grava_nada(tmp_path):
    db = _db_veiculos(tmp_path)
    _pub_v(db, ConVeiculos(montadoras_wayap=[(11, "CHEVROLET")]), tmp_path)
    m = db.execute("SELECT id_veiculo_montadora, nome, nome_exibicao, logo, id_montadora, qtd_pecas, ativo FROM veiculo_montadora").fetchone()
    con2 = ConVeiculos(montadoras_wayap=[(11, "CHEVROLET")], remoto_montadoras=[(m[0], m[1], m[2], m[3], m[4], m[5], bool(m[6]))],
                       remoto_modelos=[tuple(l) for l in db.execute("SELECT id_modelo, hash_conteudo FROM veiculo_modelo")],
                       remoto_estado=[tuple(l) for l in db.execute("SELECT id_peca, hash FROM peca_veiculo_estado")])
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
    assert db.execute("SELECT publicado FROM veiculo_arquivo").fetchone()[0] == 0


def test_peca_que_saiu_perde_as_linhas_no_destino(tmp_path):
    db = _db_veiculos(tmp_path)
    con = ConVeiculos(remoto_estado=[(99, "h")])
    r = _pub_v(db, con, tmp_path)
    assert r["pecas_veiculo_apagar"] == 1
    assert any(s.startswith("DELETE FROM peca_veiculo") for s in con.sql) and any(s.startswith("DELETE FROM peca_veiculo_estado") for s in con.sql)


def test_queda_no_meio_da_peca_veiculo_mantem_lotes_ja_gravados(tmp_path):
    from helper.veiculos_ligar import fechar
    db = _db_veiculos(tmp_path)
    id_modelo = db.execute("SELECT id_modelo FROM veiculo_modelo").fetchone()[0]
    db.execute("INSERT INTO peca (id_peca, id_marca, chave, codigo, desc_curta, status) VALUES (2, 1, 'ARTEB|2', '2', 'X', 'ativa')")
    db.execute("INSERT INTO peca_veiculo VALUES (2, ?, NULL, 2020, 2020, 'versao')", (id_modelo,))
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
    assert con.eventos.count("commit") >= 2  # árvore + primeiro lote de peca_veiculo ficaram


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
    id_modelo = db.execute("SELECT id_modelo FROM veiculo_modelo").fetchone()[0]
    with con.cursor() as cur:
        cur.execute("SELECT ano FROM anos_do_modelo(%s)", (id_modelo,))
        assert [a for (a,) in cur.fetchall()] == [2021, 2020]
        cur.execute("SELECT id_peca, confianca FROM ids_por_veiculo(%s, 2021)", (id_modelo,))
        assert cur.fetchall() == [(1, "todas_versoes")]
        cur.execute("SELECT id_peca, confianca FROM pecas_por_veiculo(%s, 2021, NULL, 'farol')", (id_modelo,))
        assert cur.fetchall() == [(1, "todas_versoes")]
        cur.execute("SELECT foto_url FROM v_veiculo_modelo WHERE id_modelo = %s", (id_modelo,))
        assert cur.fetchone()[0] == "/files/aGVscGVy/veiculos/modelos/1_abc.webp"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/pytest tests/test_publicar.py -v`
Expected: FAIL com `ImportError: cannot import name 'publicar_veiculos'`

- [ ] **Step 3: Implementar**

Em `helper/publicar.py`:

1. Imports: acrescentar `import io`, e trocar `from helper.banco import VERSAO_ESQUEMA` por:

```python
from helper.banco import VERSAO_ESQUEMA, ler_meta
from helper.montadoras import casar_wayap
```

2. Trocar `comando_rsync` por (o corpo e os comentários atuais ficam; só entram o parâmetro e as exclusões):

```python
def comando_rsync(origem, destino_ssh, pasta_remota, excluir=()):
    # --partial-dir: transferência interrompida fica fora do nome final e é completada na próxima rodada.
    # Sem --delete: nunca apaga no destino. -a já pula arquivo idêntico, então não precisa de --ignore-existing.
    # --no-owner/--no-group: no servidor os arquivos ficam do usuário que recebe (root, como os da topcar), não do uid local.
    return (["rsync", "-a", "--no-owner", "--no-group", "--chmod=D755,F644", "--partial", "--partial-dir=.rsync-partial", "--info=stats1"]
            + [f"--exclude={e}" for e in excluir]
            + [f"{str(origem).rstrip('/')}/", f"{destino_ssh}:{str(pasta_remota).rstrip('/')}/"])
```

3. Acrescentar ao fim do arquivo:

```python
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
```

Em `helper/cli.py`, em `cmd_publicar`, logo depois de `db = banco.abrir(args.banco)`:

```python
    try:
        com_veiculos = pub.veiculos_preparados(db)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
```

e, depois da linha `print(("ENSAIO: " if args.ensaio else "publicado: ") + ...)`:

```python
    if com_veiculos:
        rv = pub.publicar_veiculos(db, con, ensaio=args.ensaio, executar_rsync=pub.executar_rsync_real,
                                   pasta_fotos=args.base / "helper_fotos_veiculos", destino_ssh=destino_ssh,
                                   pasta_remota=os.environ.get("HELPER_VEICULOS_DIR", "/home/wayap/helper/veiculos"))
        print(("ENSAIO veículos: " if args.ensaio else "veículos publicados: ") + ", ".join(f"{k} {v}" for k, v in rv.items()))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/pytest tests/test_publicar.py -v`
Expected: PASS (as duas integrações continuam puladas sem `HELPER_TESTE_PG`)

Depois, a suíte inteira: `.venv/bin/pytest -q`
Expected: tudo passa (109 testes de antes + os novos), só as integrações puladas.

- [ ] **Step 5: Commit**

```bash
git add helper/publicar.py helper/cli.py tests/test_publicar.py
git commit -m "helper: publicação de veículos por diferença (arquivos, árvore, peca_veiculo por COPY em lotes)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Documentação e primeira execução real

**Files:**
- Modify: `README.md` (seção do helper)

**Interfaces:**
- Consumes: tudo das Tasks 1 a 13.
- Produces: `veiculos/` coletado, `helper.sqlite` com veículos, relatório e planilha de tipos, `publicar --ensaio` para o Francisco revisar. **A publicação de verdade não faz parte desta tarefa**: só com o ok dele.

- [ ] **Step 1: Documentar no README**

Antes de editar, rode `git diff --stat README.md`. Se o README ainda tiver mudanças do Francisco sem commit, faça a edição mas **não** inclua o README no commit; avise no relatório final que a seção de veículos ficou no arquivo sem commit.

Acrescentar ao fim da seção "Helper" do `README.md`:

````markdown
### Veículos (montadora → modelo → ano → versão)

Spec: `docs/superpowers/specs/2026-10-03-helper-veiculos-design.md`. Só carros e utilitários; motos, caminhões e
ônibus ficam fora (FIPE + nome das versões; ajustes em `helper_veiculos_tipo.csv`).

```bash
python catalogo_karhub_veiculos.py fipe        # listas da FIPE (veiculos/fipe.json), uma vez
python catalogo_karhub_veiculos.py arvore      # 4 a 7 h, retomável; --montadora chevrolet para testar; --do-inicio todo mês
python catalogo_karhub_veiculos.py compat      # 1 a 2 h; --do-inicio quando o catalogo_karhub.py rodar de novo
python helper.py veiculos                      # árvore, imagens, peca_veiculo, relatório e planilha de tipos
python helper.py pecas-do-veiculo CHEVROLET TRACKER 2021 --texto TAMBOR   # conferência contra o site
python helper.py publicar --ensaio             # agora inclui veículos
```

- Apelidos de montadora: `helper_montadoras.csv` (grafia da `montadoras` do Wayap).
- Fotos e logos próprios: `helper_fotos_veiculos/proprias/modelos/<MONTADORA>-<MODELO>.png` e
  `helper_fotos_veiculos/proprias/montadoras/<MONTADORA>.png` têm prioridade sobre os do KarHub.
- Publicação: `/home/wayap/helper/veiculos/` (rsync) e tabelas `veiculo_*`, `peca_veiculo` no Postgres `helper`. O helper
  só lê a `montadoras` do Wayap (para `id_montadora`); nunca escreve nela.
- Contrato: views `v_veiculo_montadora`, `v_veiculo_modelo`; funções `anos_do_modelo`, `versoes_do_ano`,
  `pecas_por_veiculo`, `ids_por_veiculo`.
- Rotina: `preparar` → `veiculos` → `fotos` → `publicar` (o `publicar` recusa `veiculos` mais antigo que o `preparar`).
````

- [ ] **Step 2: Commit da documentação**

```bash
git diff --stat README.md   # se aparecerem mudanças que não são desta tarefa, não faça este commit (ver Step 1)
git add README.md
git commit -m "README: veículos no helper

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 3: FIPE e uma montadora de teste**

```bash
.venv/bin/python catalogo_karhub_veiculos.py fipe
.venv/bin/python catalogo_karhub_veiculos.py arvore --montadora chevrolet
```

Expected: `veiculos/fipe.json` com as três listas; `veiculos/karhub_arvore.jsonl` com 60 a 70 modelos da Chevrolet
(carros) e `veiculos/karhub_excluidos.jsonl` com os caminhões (C 60, D 40, D 60, D 70, D 6000...). Abra 3 linhas e
confira que Tracker tem foto e anos de 2005 em diante.

- [ ] **Step 4: Coleta completa em segundo plano**

```bash
.venv/bin/python catalogo_karhub_veiculos.py arvore   # rodar em segundo plano; acompanha por veiculos/arvore.log
.venv/bin/python catalogo_karhub_veiculos.py compat   # depois da árvore; acompanha por veiculos/compat.log
```

Se parar com código 2 (bloqueio), espere uma hora e rode o mesmo comando: ele retoma.

- [ ] **Step 5: Preparar veículos e conferir**

```bash
.venv/bin/python helper.py veiculos
.venv/bin/python helper.py pecas-do-veiculo CHEVROLET TRACKER 2021 --versao "4x2 Aut. 1.2 12v L3 Turbo" --texto TAMBOR
.venv/bin/python helper.py pecas-do-veiculo VOLKSWAGEN GOL 2010 --texto PASTILHA
.venv/bin/python helper.py pecas-do-veiculo FIAT PALIO 2005 --texto PASTILHA
```

Compare cada lista com a página de categoria do KarHub filtrada pelo mesmo veículo (por exemplo
`https://www.karhub.com.br/c/autopecas/sistema-de-freio/tambor-de-freio` com o filtro Chevrolet / Tracker / 2021 / versão).
As peças que o KarHub mostra têm de aparecer como `versao` ou `todas_versoes`. Anote no relatório final quantas
batem e as que não batem.

- [ ] **Step 6: Ensaio da publicação e parada para revisão**

```bash
.venv/bin/python helper.py publicar --ensaio
```

Pare aqui. Entregue ao Francisco: o caminho de `helper_relatorios/<data>-veiculos.md`, da planilha
`helper_relatorios/<data>-veiculos-tipos.csv` (para revisar o que entrou e saiu como carro), o resultado do ensaio e a
conferência do Step 5. A publicação de verdade (`python helper.py publicar`) só depois do ok dele.
