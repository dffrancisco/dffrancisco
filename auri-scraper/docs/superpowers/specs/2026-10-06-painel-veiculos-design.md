# Painel: veículos do helper na aba Cadastrar (busca por veículo e veículos compatíveis)

Data: 2026-10-06. Status: desenho aprovado em conversa, aguardando revisão do texto.

Leva para a aba **Cadastrar dos sites** do `painel_wayap.py` o que o site da KarHub faz com veículos,
usando a árvore e a ligação peça → veículo que o helper já tem (spec
`2026-10-03-helper-veiculos-design.md`):

1. **Busca por veículo:** o quadro "Confira se serve no seu veículo" (montadora → modelo → ano →
   versão opcional) ao lado da busca; a lista mostra só os itens que servem no veículo, com selo de
   confiança.
2. **Veículos compatíveis no formulário:** a lista e a árvore (montadora com logo → modelo com foto →
   anos → versões) da peça, lidas do helper em vez da página da KarHub aberta na hora; os carros de
   venda e o complemento do produto saem delas.

Fica de fora: a aba "Placa" da KarHub, criar no Wayap os carros que a sociedade não tem, e qualquer
mudança no Wayap ou no Postgres.

## 1. O que já existe e orienta o desenho

**Na KarHub** (conferido no site em 2026-10-06):

- Busca: campo de texto e o quadro "Confira se serve no seu veículo", com a alternância Placa |
  Modelo; em Modelo, quatro listas (Montadora, Modelo, Ano, Versão opcional) e o botão Escolher.
- Página da peça: "Confira se serve no seu veículo" (as mesmas quatro listas e "Confirmar
  Compatibilidade") e "Veículos Compatíveis" em duas vistas: **lista** (uma linha por versão e ano,
  "BMW 116i 2015 (F21) 1.6 16V TURBO") e **árvore** (logo da montadora → modelos, com campo de busca →
  anos → versões).

**No painel hoje** (`painel_wayap.py`):

- A busca é no `catalogos/catalogos.sqlite` (um item por anúncio de cada site, índice FTS5), sem
  ligação com o helper.
- Os veículos do formulário vêm de `veiculos_sugeridos`: na KarHub, a página do produto baixada na
  hora pelo Scrapling (lista "Veículos Compatíveis"); nos outros sites, o texto de aplicação
  (`ocorrencias_do_texto`). As ocorrências passam por `agrupar_veiculos`, que casa o modelo com um
  carro da sociedade pelo prefixo mais longo (`carro_do_modelo`, com `ALIAS_MODELOS`) e monta o
  complemento no padrão da casa ("1.0 / 1.4 00/12 WAGON"). O complemento do produto é a lista de
  linhas da página.
- O painel não tem testes.

**No helper:**

- O código de veículos está no branch `helper-veiculos` (worktree
  `.worktrees/helper-veiculos`), ainda fora da `main`. A `main` tem um commit a mais (`f652d0c`,
  coletores novos e `helper/cli.py`). O `painel_wayap.py` é igual nos dois.
- Tabelas locais `vei_montadora`, `vei_modelo` (com `tipo` carro/moto/pesado), `vei_versao`,
  `vei_versao_ano`, `vei_peca` (`id_peca`, `id_modelo`, `id_versao` ou nulo = todas as versões,
  `ano_inicio`, `ano_fim`, `nivel` `versao` ou `modelo`). `helper/consulta.py` tem
  `ids_por_veiculo(db, id_modelo, ano, id_versao)` → `{id_peca: confianca}` com as regras de
  confiança da spec de veículos (seção 9), e `ORDEM_CONFIANCA`.
- Logos e fotos gerados ficam em `helper_fotos_veiculos/montadoras/` e
  `helper_fotos_veiculos/modelos/`; o banco guarda `veiculos/montadoras/<arquivo>` e
  `veiculos/modelos/<arquivo>` (o prefixo `veiculos/` é a pasta no servidor).
- `nome_exibicao` das versões vem com maiúsculas estranhas ("Ss 6.2 16v V8 (461 Cv)"); o `nome`
  canônico é maiúsculo ("SS 6.2 16V V8 (461 CV)").
- **Os dados locais estão atrasados:** o `helper.py veiculos` rodou em 2026-10-04 18:54, antes de a
  coleta terminar. Hoje: 1.267 modelos e só ligações de nível `modelo`. A coleta completa está em
  `veiculos/`: 3.498 modelos em `karhub_arvore.jsonl` e 182.317 produtos em `karhub_compat.jsonl`
  (144.096 com veículos).

**Ligação item do catálogo → peça do helper:** `origem` (chave `site, url`) com a URL do item. Medida
em 2026-10-06:

| Site | Itens | Com peça no helper |
|---|---|---|
| KarHub | 182.317 | 100% |
| CarBlue | 125.294 | 70% |
| ShopPeças | 38.817 | ~100% |
| Universal | 18.428 | 100% |
| Altese | 13.449 | 100% |
| ClicPeças | 10.538 | 100% |
| Fuscão Preto | 1.338 | 100% |
| AZ Acessórios | 299 | 86% |

## 2. Decisões

| Decisão | Escolha | Motivo |
|---|---|---|
| Fonte dos veículos | `helper.sqlite` local, só leitura | O painel é local, ao lado do helper; vale assim que o `veiculos` roda, sem publicar nem rede |
| Tipos no seletor | Todos (carro, moto, pesado), misturados como na KarHub, com selinho "moto"/"pesado" no modelo | Pedido do dono |
| Item sem peça no helper, na busca por veículo | Fica de fora | Não há como saber se serve |
| Item sem veículos no helper, no formulário | Volta ao comportamento de hoje (página da KarHub ou texto do site) | Não perder o que já funciona |
| Nomes na lista e no complemento | Canônicos, em maiúsculas | Os de exibição das versões vêm com maiúsculas estranhas; a lista da KarHub é maiúscula |
| Código novo | Módulo `painel_veiculos.py`; o `painel_wayap.py` ganha só rotas finas e o HTML/JS | O painel já tem 1.196 linhas; o módulo é testável sem Flask |

## 3. Pré-requisitos (antes de mexer no painel)

1. **Merge do `helper-veiculos` na `main`**, resolvendo o conflito com o `f652d0c` em
   `helper/cli.py`; `pytest` passando. O `veiculos/coleta_completa.sh` passa a apontar para o
   `catalogo_karhub_veiculos.py` da `main`.
2. **Reprocessar:** conferir com `pgrep -af helper.py` que nenhum outro processo grava no
   `helper.sqlite`; rodar `python helper.py veiculos` em `systemd-run --user` (some junto com a
   sessão se rodar no terminal); conferir o relatório `helper_relatorios/<data>-veiculos.md` (modelos
   por tipo, peças ligadas por nível, linhas de `vei_peca`). Esperado: os 3.498 modelos e linhas de
   nível `versao`. Publicar no Postgres não faz parte desta spec.

## 4. Leitura do helper no painel (`painel_veiculos.py`)

- Constantes: `HELPER_DB = Path("helper.sqlite")`, `FOTOS_VEICULOS = Path("helper_fotos_veiculos")`.
- Conexão por chamada, `sqlite3.connect("file:helper.sqlite?mode=ro", uri=True, timeout=5)`, com
  `row_factory = sqlite3.Row`. Só leitura: o painel nunca grava no helper.
- **Disponível** quando o arquivo existe e `vei_modelo` tem modelo ativo. Indisponível: o quadro de
  veículo não aparece e o formulário usa o comportamento de hoje.
- **Ocupado** (`sqlite3.OperationalError` de lock): as rotas de veículo devolvem 503 com
  `{"erro": "Base de veículos ocupada, tente de novo"}`; a tela mostra o aviso e a busca segue sem
  veículo; o formulário usa o comportamento de hoje.

Funções (todas recebem a conexão do helper, para os testes usarem um banco montado na hora):

| Função | Devolve |
|---|---|
| `montadoras(db)` | ativas com algum modelo ativo: `id`, `nome` (exibição), `logo_url`, `qtd_pecas`; ordem `qtd_pecas` decrescente, depois nome |
| `modelos(db, id_montadora)` | ativos: `id`, `nome` (exibição), `tipo`, `foto_url` (nula sem foto), `ano_inicio`, `ano_fim`; ordem alfabética |
| `anos(db, id_modelo)` | anos com alguma versão ativa, decrescente |
| `versoes(db, id_modelo, ano)` | versões ativas que existem no ano: `id`, `nome` (canônico); ordem alfabética |
| `peca_do_item(db, site, url)` | `id_peca` pela `origem`, ou `None` |
| `veiculos_da_peca(db, id_peca)` | as linhas (seção 6.1), ou lista vazia |
| `arvore(db, linhas)` | a árvore (seção 6.2) |
| `seu_veiculo(db, id_peca, id_modelo, ano, id_versao)` | o veredito (seção 6.3) |
| `ocorrencias(db, linhas)` | entrada do `agrupar_veiculos` (seção 6.4) |
| `linhas_complemento(linhas)` | texto do complemento do produto (seção 6.5) |

URLs de imagem: `/veiculos/img/<caminho sem o prefixo veiculos/>`.

## 5. Busca por veículo

### 5.1 Tela

Segunda linha do cabeçalho da aba Cadastrar, abaixo da busca atual: o quadro **"Confira se serve no
seu veículo"** com quatro seletores em sequência.

| Seletor | Cada opção | Ordem |
|---|---|---|
| Montadora | logo + nome | `qtd_pecas` decrescente |
| Modelo | miniatura da foto + nome + faixa de anos + selinho "moto" ou "pesado" | alfabética |
| Ano | o ano | decrescente |
| Versão (opcional) | nome canônico | alfabética |

- Seletores próprios em JS (não `<select>`, por causa das imagens): campo que filtra enquanto se
  digita (sem acento, sem diferenciar maiúsculas), setas, Enter escolhe, Esc fecha. Cada um só abre
  depois do anterior escolhido; trocar um limpa os seguintes.
- Veículo completo (até o ano): o quadro mostra a foto do modelo (ou o logo da montadora, sem foto)
  e "Chevrolet Onix 2019 · LT 1.4 8V FLEX", e o botão **Limpar**.
- Ao escolher o ano, trocar ou limpar a versão, ou limpar o veículo, a busca roda de novo com o
  texto atual.
- O veículo fica no `localStorage` (`veiculo`: ids e nomes), dentro de try/catch. Ao abrir a
  página, se o modelo ou a versão guardados não existem mais (as listas não os trazem), o veículo é
  limpo.

### 5.2 `GET /api/catalogo/busca`

Ganha `modelo`, `ano` e `versao` (opcional). Com `modelo` e `ano`, o `q` passa a ser opcional.

1. `ids_por_veiculo(helper, modelo, ano, versao)` → `{id_peca: confianca}`. Vazio: nada encontrado.
2. Os ids vão para uma tabela temporária com a ordem de `ORDEM_CONFIANCA`, numa conexão do
   `catalogos.sqlite` aberta por URI com o helper anexado só para leitura
   (`ATTACH 'file:helper.sqlite?mode=ro' AS h`).
3. Item do catálogo que serve: `temp ids → h.origem (id_peca) → item (site, url)`. O
   `indexar_catalogos` cria `item_site_url ON item (site, url)`.
4. Com `q`: os achados exatos por EAN e código da primeira página (como hoje) só entram se servem;
   a busca textual junta `busca MATCH` com os itens que servem e ordena por confiança e depois
   `rank`. Sem `q`: ordem por confiança, depois itens com foto, depois `item.id`.
5. Filtro de site, página de 40 e `tem_mais` como hoje.
6. Cada item ganha `confianca`.

Sem `modelo`, a busca é exatamente a de hoje.

**Selo na linha:**

| `confianca` | Selo |
|---|---|
| `versao` | Serve nesta versão |
| `todas_versoes` | Serve em todas as versões |
| `algumas_versoes` | Serve em algumas versões |
| `modelo_ano` | Confira a versão |

### 5.3 Carro principal

`GET /api/catalogo/sugestao/<id>` ganha `modelo`, `ano` e `versao`. Com veículo escolhido, o carro
principal sugerido é `carro_do_modelo(<nome canônico do modelo>)`, se a sociedade tiver o carro;
senão seguem as regras de hoje (carro do título, primeiro compatível, `achar_carro`).

## 6. Veículos compatíveis no formulário

`api_sugestao` pega a peça do item (`peca_do_item`) e as linhas dela. Com linhas, a fonte é a
**base**; sem peça ou sem linhas, a fonte é o **site** e tudo segue como hoje
(`veiculos_sugeridos`). A resposta ganha `veiculos_fonte` (`base` ou `site`), `veiculos_lista`,
`veiculos_arvore` e `seu_veiculo`; `campos.veiculos` (carros de venda) e
`campos.complemento_produto` continuam onde estão.

### 6.1 Linhas

Uma por linha de `vei_peca` da peça, com modelo e montadora ativos (e versão ativa, quando há):
`montadora` e `modelo` (canônico e exibição), `tipo`, `versao` (canônico, ou nulo = todas),
`ano_inicio`, `ano_fim`, `nivel`, `motores` (seção 6.4). Ordem: montadora, modelo, `ano_inicio`
(nulo primeiro), versão (nula primeiro).

**Vista Lista**, uma linha de texto por linha:

| Linha | Texto |
|---|---|
| versão | `CHEVROLET ONIX 2013-2019 LT 1.4 8V FLEX` |
| todas as versões | `CHEVROLET ONIX 2013-2019` + selo "todas as versões" |
| nível `modelo` | `CHEVROLET ONIX 2013-2019` + selo "confira a versão" |
| sem anos (nível `modelo`) | `CHEVROLET ONIX` + selo "confira a versão" |

Faixa de um ano só: `2019`.

### 6.2 Vista Árvore

Montadora (logo, nome, quantos modelos) → modelo (foto, nome, faixa, selinho de tipo) → anos
(decrescente) → versões daquele ano. Cada nível abre ao clicar, com "voltar", como na KarHub; o nível
de modelos tem campo de busca.

- Linha de uma versão: o ano entra quando a versão existe nele (`vei_versao_ano`) e está na faixa.
- Linha de todas as versões: o ano entra quando o modelo tem versão nele e está na faixa; as
  versões listadas são todas as que existem no ano, com a marca "todas as versões".
- Linha de nível `modelo`: os anos do modelo na faixa (todos, sem faixa), sem versões, com "confira
  a versão".

### 6.3 Seu veículo

Com veículo escolhido na busca, no topo do bloco: "Seu veículo: Chevrolet Onix 2019 LT 1.4 8V
FLEX" e o veredito, pelas regras da confiança aplicadas só a esta peça:

| Situação | Veredito |
|---|---|
| `versao` / `todas_versoes` | Serve |
| `algumas_versoes` | Serve em algumas versões: escolha a versão |
| `modelo_ano` | Confira a versão |
| versão escolhida e a peça só serve em outras | Não serve nesta versão |
| nada | Não consta para este veículo |

### 6.4 Carros de venda

Cada linha vira uma ocorrência do `agrupar_veiculos`: `[rótulo, modelo, anos, motores]`, com rótulo
`MONTADORA MODELO`, modelo = nome canônico do modelo, anos = `(ano_inicio, ano_fim)` ou `None`.

Motores: linha de versão → o `motor` dela; linha de todas as versões → os `motor` distintos das
versões que existem nos anos da faixa; nível `modelo` → nenhum.

O resto é o `agrupar_veiculos` de hoje, sem mudança: carro pelo prefixo, `ALIAS_MODELOS`, faixa de
anos e complemento do carro. A tela dos carros de venda não muda, só o resumo do título:
"(N modelo(s), M linhas da base)".

### 6.5 Complemento do produto

O texto da vista Lista, uma linha por linha, sem os selos. Continua editável.

### 6.6 Tela do bloco

- Título "Veículos compatíveis (base de peças)" com a alternância **Lista | Árvore** (a última
  escolhida fica no `localStorage`). Fonte `site`: título e bloco como hoje.
- Avisos: com fonte `base`, o de modelos sem carro passa a dizer "Alguns modelos da base não existem
  no cadastro de carros: escolha o carro ou desmarque."; os de código e marca continuam citando o
  site, porque vêm do item. Sem veículos em nenhuma das fontes, continua o aviso de hoje.

## 7. Rotas novas e alteradas (`painel_wayap.py`)

| Rota | O que faz |
|---|---|
| `GET /api/veiculos/montadoras` | `montadoras` |
| `GET /api/veiculos/modelos?montadora=` | `modelos` |
| `GET /api/veiculos/anos?modelo=` | `anos` |
| `GET /api/veiculos/versoes?modelo=&ano=` | `versoes` |
| `GET /veiculos/img/<caminho>` | arquivo de `helper_fotos_veiculos/`, só dentro de `montadoras/` e `modelos/` (`send_from_directory`); sem arquivo, 404 e a tela mostra um quadro vazio |
| `GET /api/catalogo/busca` | seção 5.2 |
| `GET /api/catalogo/sugestao/<id>` | seções 5.3 e 6 |

Helper indisponível: as rotas `/api/veiculos/*` devolvem 404 com `{"erro": "Base de veículos não
encontrada"}` e a tela esconde o quadro. Helper ocupado: 503 (seção 4).

O `/api/catalogo/cadastrar` não muda: recebe os carros de venda e o complemento da tela, como hoje.

## 8. Erros

| Situação | Comportamento |
|---|---|
| `helper.sqlite` ausente ou sem modelos | quadro de veículo escondido; formulário como hoje |
| Helper ocupado (lock) | aviso "Base de veículos ocupada, tente de novo"; busca sem veículo; formulário como hoje |
| `helper.py veiculos` rodando (tabelas a meio caminho) | o painel pode ver dados incompletos; não rodar o painel e o `veiculos` juntos |
| Item sem peça no helper | fora da busca por veículo; no formulário, fonte `site` |
| Peça sem linhas em `vei_peca` | fonte `site` |
| Modelo sem foto | logo da montadora no lugar; sem logo, quadro vazio |
| Veículo guardado que sumiu | limpo ao abrir a página |
| Montadora, modelo ou versão inativos | não aparecem nas listas nem nas linhas |

## 9. Verificação

- **Testes unitários** (`tests/test_painel_veiculos.py`), com um `helper.sqlite` pequeno montado no
  teste (como `test_consulta.py`) e um `catalogos.sqlite` pequeno:
  - listas: ordem das montadoras por `qtd_pecas`, modelos inativos fora, anos decrescentes, versões
    só do ano;
  - `veiculos_da_peca`: linha de versão, de todas as versões, de nível `modelo` com e sem anos;
    ordem; inativos fora;
  - `arvore`: anos de uma versão só onde ela existe; todas as versões listando as do ano; nível
    `modelo` sem versões;
  - `seu_veiculo`: cada linha da tabela da seção 6.3;
  - `ocorrencias` → `agrupar_veiculos`: motores de versão, de todas as versões e nenhum; faixa;
    carro pelo prefixo;
  - `linhas_complemento`: os quatro formatos da seção 6.1;
  - busca: com veículo e sem texto, com veículo e texto, EAN exato que não serve fica de fora, ordem
    por confiança, filtro de site, item sem peça fora, paginação;
  - fonte: item sem peça e peça sem linhas caem em `site`.
- **No navegador**, com o painel rodando: Chevrolet Tracker 2021 (versão "4x2 Aut. 1.2 12v L3
  Turbo"), Volkswagen Gol 2010 e Fiat Palio 2005, buscando "pastilha" e "tambor": as peças que a
  KarHub mostra para o veículo aparecem com "Serve nesta versão" ou "Serve em todas as versões"; a
  árvore e a lista de uma peça da KarHub batem com "Veículos Compatíveis" da página dela; um item da
  Universal fundido com uma peça da KarHub mostra os mesmos veículos; cadastrar um produto de teste
  só se o dono pedir.
