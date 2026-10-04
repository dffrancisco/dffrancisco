# Helper: veículos (montadora → modelo → ano → versão), fotos de modelo e peças por veículo

Data: 2026-10-03. Status: direção aprovada em conversa, aguardando revisão do texto.

Complementa a spec do helper (`2026-10-02-helper-design.md`). Acrescenta tabelas, um coletor e
consultas ao contrato da seção 7 daquela spec, e sobe `versao_esquema` para 2. Nada do que já
existe muda de significado.

## 1. Objetivo

Levar para o Wayap o filtro "Confira se serve no seu veículo" do KarHub: montadora → modelo
(com foto do carro) → ano → versão. Com ele, o Wayap vai ter a tela **"Peças para o veículo"**
no balcão: o vendedor escolhe o veículo, digita o que procura ("pastilha") e vê duas listas:

- **No seu estoque:** produtos do cliente que servem, com quantidade e preço.
- **No mercado:** peças do helper que servem e que o cliente não tem, para encomendar ou
  cadastrar.

O cliente não cadastra aplicação nenhuma. O produto dele se liga à peça do helper pelo EAN ou
pelo código do fabricante, e a peça do helper sabe em quais veículos serve. Em 2026-10-02 essa
ligação já alcançava 41% dos produtos da topcar (28 mil de 68 mil; Universal e Perfect acima
de 95%), e cresce a cada site raspado.

Esta spec cobre só a **fase 1, no helper**: coletar a árvore de veículos, as fotos e a
compatibilidade, ligar às peças, publicar e garantir as consultas. As telas do Wayap são specs
próprias (seção 12).

## 2. O que já existe e orienta o desenho

**Fonte: API do próprio site do KarHub** (Shopify Hydrogen, rotas `/api/...` do servidor do
site; testadas em 2026-10-03):

| Rota | Devolve |
|---|---|
| `/api/get-vehicles` | 159 montadoras (`label`, `handle`) |
| `/api/get-vehicles?brand=chevrolet` | modelos da montadora (3.495 no total; inclui caminhões, ônibus e motos) |
| `...&model=Tracker` | anos do modelo, cada um com os ids de veículo daquele ano |
| `...&year=2021` | versões do ano (`label`, `handle`) com **um id de veículo cada** (ex.: "4x2 Aut. 1.2 12v L3 Turbo" = 62329) |
| `/api/get-automaker-content?handle=chevrolet/tracker` | foto do modelo (`images.karhub.com.br/veiculos/chevrolet-tracker.avif`, 600×450 com fundo transparente) e logo da montadora (200×200) |
| `/api/product-compatible-ids?handles=h1,h2,...` | para cada produto, os ids de veículo que ele atende; aceita até 50 por chamada (com 100, volta vazio sem erro) |

O id de veículo do KarHub é um par (versão, ano): os ids de um ano são exatamente a união dos
ids das versões daquele ano, e não há rótulo de versão repetido no mesmo ano. O site e as
imagens ficam atrás do Cloudflare: `requests` puro recebe 403, o `Fetcher` do Scrapling com
`stealthy_headers` passa, como já acontece em `catalogo_karhub.py`. Nem todo modelo tem foto
(o Camaro, por exemplo, dá 404, e o site mostra um carro genérico).

**O banco `helper` no Postgres já tem tabelas do Wayap**, além das do helper: `montadoras`
(71 linhas, global, mantida pelo Wayap; `carro.id_montadora` de cada sociedade aponta para
ela; `logo` guarda caminho relativo como `montadoras/11.png`), `placas_detalhes` (pesquisa por
placa do Wayap), `schema_migrations` e outras. Em `/home/wayap/helper/montadoras/` estão 5
logos feitos pelo Francisco (`11.png`, `13.png`, `18.png`, `63.png`, `70.png`). Por isso a árvore
usa `montadoras.id_montadora` e não cria uma tabela de montadora própria no Postgres.

**A tabela `carro` de cada sociedade continua como está.** Ela é por cliente, no nível de
modelo, e é usada em `produto`, `produto_venda`, `similar`, filtros e relatórios. A árvore
entra ao lado; o Wayap casa `modelo` com `carro` por (`id_montadora`, nome) quando precisar.

**As aplicações que o helper já tem** (667 mil linhas, texto de todos os sites): 78% casam com
um nome de modelo da árvore pelo prefixo. Elas dão a ligação de nível "modelo" para as peças que
o KarHub não cobre.

## 3. Decisões fechadas

| Decisão | Escolha | Motivo |
|---|---|---|
| Fonte da árvore e da compatibilidade | API do site do KarHub, coletada aqui | Única fonte com versão por ano, foto do modelo e ligação produto → versão |
| Montadora | `montadoras` do Wayap, no banco `helper`; o helper insere só as que faltam e preenche `logo` só onde está vazio | Uma montadora só para o Wayap inteiro; não pisar no que o Wayap e o Francisco já cadastraram |
| Escopo de veículos | Tudo que o KarHub lista: carros, utilitários, caminhões, ônibus e motos | Custo de coleta baixo; o Wayap pode esconder o que não usar |
| Granularidade | `modelo`, `versao` e os anos de cada versão (`versao_ano`) | É o que o filtro precisa: ano mostra as versões daquele ano |
| Ids | Inteiros atribuídos aqui, estáveis por nome canônico; o id do KarHub fica só no banco local | Mesmo princípio das peças: id publicado nunca muda nem é reaproveitado |
| Remoção | Modelo ou versão que some da coleta vira `ativo = false`, nunca é apagado | Telas podem guardar o id |
| Ligação peça → veículo | Tabela `peca_veiculo` agrupada por versão e faixa de anos, com `id_versao` nulo quando a peça serve em todas as versões | Sem agrupar seriam ~70 milhões de linhas (cerca de 400 versões-ano por produto) |
| Níveis de confiança | `versao` (confirmada pelo KarHub) e `modelo` (deduzida do texto de aplicação, versão não confirmada) | É o selo "serve nesta versão" ou "confira a versão" da tela |
| Foto do modelo | WebP com transparência, qualidade 90, sem redimensionar | 34 KB contra 211 KB do PNG; todos os navegadores atuais abrem |
| Logo da montadora | PNG, como os que já existem | Mesmo formato dos 5 logos atuais |
| Foto própria | Arquivo em `helper_fotos_veiculos/proprias/` tem prioridade sobre o do KarHub | O dono pode trocar qualquer foto ou logo sem mexer em código |
| Onde ficam os arquivos no servidor | `/home/wayap/helper/modelos/` e `/home/wayap/helper/montadoras/`, servidos por `/files/aGVscGVy/` | Mesma convenção do `montadoras.logo` (caminho relativo a `/home/wayap/helper/`) |

## 4. Coleta: `catalogo_karhub_veiculos.py`

Novo coletor na raiz, no padrão dos outros `catalogo_*.py`. Grava em `veiculos/`, e não em
`catalogos/`, porque o `preparar` lê todo `catalogos/*.jsonl` como anúncio.

```
python catalogo_karhub_veiculos.py arvore [--do-inicio] [--montadora chevrolet]
python catalogo_karhub_veiculos.py compat [--do-inicio]
```

**`arvore`** percorre montadora → modelos → anos → versões, mais o conteúdo de cada modelo
(foto e logo), e baixa as imagens originais para `veiculos/imagens/` (nome = caminho da URL).
Grava uma linha por modelo **completo** em `veiculos/karhub_arvore.jsonl`:

```json
{"montadora": {"label": "Chevrolet", "handle": "chevrolet", "logo_url": "https://images.karhub.com.br/assets/montadoras/chevrolet.avif"},
 "modelo": {"label": "Tracker", "handle": "Tracker", "foto_url": "https://images.karhub.com.br/veiculos/chevrolet-tracker.avif"},
 "anos": [{"ano": 2021, "versoes": [{"label": "4x2 Aut. 1.2 12v L3 Turbo", "handle": "4x2-aut-12-12v-l3-turbo", "id_fonte": "62329"}]}],
 "coletado_em": "2026-10-03"}
```

Retoma pulando os modelos que já estão no arquivo; `--do-inicio` coleta tudo de novo num
arquivo novo e só o troca pelo antigo no fim. São cerca de 3.500 chamadas de anos, 35 a 40 mil
de versões e 3.500 de conteúdo: de 6 a 10 horas.

**`compat`** lê os handles de `catalogos/karhub.jsonl` (caminho da URL, sem a query das
variantes), consulta 50 por chamada e grava `{"handle", "ids", "coletado_em"}` em
`veiculos/karhub_compat.jsonl`. Retoma pelos handles já gravados. Se um lote inteiro voltar
vazio, repete em lotes de 10 para separar "produto sem compatibilidade" de "lote recusado".
São cerca de 3.700 chamadas, de 1 a 2 horas.

Ritmo e falhas iguais aos de `catalogo_karhub.py`: uma chamada por vez, pausa de 0,3 s, novas
tentativas com espera crescente, HTTP 403/430 ou captcha contam como bloqueio, e o coletor para
com código 2 e uma mensagem para rodar de novo mais tarde. Log em `veiculos/*.log`.

## 5. Modelo de dados

Tabelas no `helper.sqlite` e, quando indicado, no Postgres `helper`.

### 5.1 `montadora` (só local)

| Campo | Conteúdo |
|---|---|
| `nome` | chave; canônico: a `descricao` da `montadoras` do Wayap quando casa, senão maiúsculas sem acento do rótulo do KarHub |
| `nome_exibicao` | como o KarHub escreve ("Mercedes Benz") |
| `logo` | arquivo local já convertido, ou nulo |
| `id_montadora` | id na `montadoras` do Wayap; preenchido pelo `publicar` |

Casamento com a `montadoras` do Wayap: compara os nomes em maiúsculas, sem acento e só com
letras e números (`MERCEDES BENZ` = `MERCEDES-BENZ`), e depois consulta o arquivo editável
`helper_montadoras.csv` (`apelido;montadora`) para os casos que diferem de verdade: `KIA` →
`KIA MOTORS`, `JAC` → `JAC MOTORS`, `GM` → `CHEVROLET`, `VW` → `VOLKSWAGEN`, `BMW BMW` → `BMW`.
O mesmo casamento serve para o campo `montadora` das aplicações.

### 5.2 `modelo` (local e Postgres)

| Campo | Conteúdo |
|---|---|
| `id_modelo` | inteiro, chave, estável |
| `id_montadora` | referência à `montadoras` do Wayap (no local, a montadora é guardada pelo `nome`) |
| `nome` | canônico, maiúsculas sem acento, espaços simples (`TRACKER`, `ONIX PLUS`) |
| `nome_exibicao` | como o KarHub escreve (`Tracker`) |
| `foto` | caminho relativo, `modelos/<id_modelo>_<8 primeiros do sha1>.webp`, ou nulo |
| `ano_inicio`, `ano_fim` | menor e maior ano com versão |
| `qtd_pecas` | peças ativas ligadas ao modelo, em qualquer nível (para ordenar e esconder modelos vazios) |
| `ativo` | booleano |
| `hash_conteudo` | hash do modelo, das suas versões e dos anos delas, para publicar por diferença |
| `atualizado_em` | data da última mudança |

Chave única: (`id_montadora`, `nome`).

### 5.3 `versao` (local e Postgres)

| Campo | Conteúdo |
|---|---|
| `id_versao` | inteiro, chave, estável |
| `id_modelo` | referência |
| `nome` | canônico, maiúsculas sem acento, espaços simples |
| `nome_exibicao` | como o KarHub escreve (`4x2 Aut. 1.2 12v L3 Turbo`) |
| `motor` | cilindrada lida do nome (`1.2`), ou nulo |
| `ativo` | booleano |

Chave única: (`id_modelo`, `nome`).

### 5.4 `versao_ano` (local e Postgres)

(`id_versao`, `ano`), chave composta: em quais anos cada versão existe. O filtro de ano mostra
os anos com alguma versão; o filtro de versão mostra as versões do ano escolhido.

### 5.5 `peca_veiculo` (local e Postgres)

| Campo | Conteúdo |
|---|---|
| `id_peca` | referência à `peca` |
| `id_modelo` | referência |
| `id_versao` | referência, ou **nulo = todas as versões do modelo** nos anos da faixa |
| `ano_inicio`, `ano_fim` | faixa; nulos só no nível `modelo` quando a aplicação não informa ano (vale para qualquer ano) |
| `nivel` | `versao` (veio da compatibilidade do KarHub) ou `modelo` (veio do texto de aplicação) |

Índices: (`id_modelo`, `ano_inicio`, `ano_fim`) e (`id_peca`).

**Agrupamento do nível `versao`**, para uma peça e um modelo:

1. Para cada ano do modelo, compara as versões que a peça atende naquele ano com todas as
   versões que existem naquele ano. Se forem todas, o ano é **completo**.
2. Anos completos seguidos viram linhas com `id_versao` nulo. "Seguidos" conta só os anos que o
   modelo tem: um ano sem versão nenhuma não quebra a faixa.
3. Nos anos que não são completos, cada versão atendida vira linhas com seu `id_versao`, com
   faixas seguidas contadas só nos anos em que aquela versão existe.

Uma linha (`modelo`, `versão` ou nulo, `i`, `f`) quer dizer: "serve na versão (ou em todas) em
todos os anos entre `i` e `f` em que ela existe". Ids de veículo da compatibilidade que não
estão na árvore são ignorados e contados no relatório.

**Nível `modelo`**, das aplicações de todos os sites: a montadora casa pelo item 5.1, e o
modelo é o prefixo mais longo de `aplicacao.modelo` que é nome de modelo da árvore naquela
montadora. Sem montadora, só casa se o nome existir em uma única montadora; caso contrário, vai
para o relatório. Um par (peça, modelo) que já tem linha de nível `versao` não ganha linha de
nível `modelo`. Faixas sobrepostas ou adjacentes do mesmo par se juntam.

### 5.6 Tabelas só locais

- `veiculo_fonte` (`site`, `id_fonte`, `id_versao`, `ano`): traduz o id do KarHub para
  versão e ano. Proveniência; não é publicada.
- `peca_veiculo_estado` (`id_peca`, `hash`, `hash_publicado`): hash das linhas de
  `peca_veiculo` de cada peça, para publicar por diferença.

## 6. Preparação: `python helper.py veiculos`

Roda depois do `preparar`, porque usa peças, origens e aplicações. Recalcula tudo a partir de
`veiculos/*.jsonl` e do `helper.sqlite`; com as mesmas entradas, gera os mesmos ids e os mesmos
hashes.

1. **Árvore:** lê `veiculos/karhub_arvore.jsonl` e grava montadora, modelo, versão, anos e
   `veiculo_fonte`. Modelo ou versão ausente da coleta vira `ativo = 0`.
2. **Imagens:** converte a foto de cada modelo para WebP e o logo de cada montadora para PNG,
   a partir de `veiculos/imagens/`. Antes, procura foto própria em
   `helper_fotos_veiculos/proprias/modelos/<MONTADORA>-<MODELO>.(png|jpg|webp)` e
   `helper_fotos_veiculos/proprias/montadoras/<MONTADORA>.png`, que têm prioridade. Saída em
   `helper_fotos_veiculos/modelos/` e `helper_fotos_veiculos/logos/`. Modelo sem foto fica com
   `foto` nulo, e o Wayap mostra uma imagem genérica.
3. **Nível `versao`:** para cada peça ativa com origem `karhub`, pega o handle da URL, procura
   os ids em `karhub_compat.jsonl`, traduz pelo `veiculo_fonte` e agrupa (item 5.5).
4. **Nível `modelo`:** a partir das aplicações das peças ativas (item 5.5).
5. **Fechamento:** calcula `qtd_pecas`, os hashes e o relatório
   `helper_relatorios/<data>-veiculos.md`. Grava em `meta` a hora em que rodou.

Comando de conferência, para comparar com o site:

```
python helper.py pecas-do-veiculo CHEVROLET TRACKER 2021 [--versao "4x2 Aut. 1.2 12v L3 Turbo"] [--texto TAMBOR]
```

Ele imprime as peças com a confiança, usando a mesma regra da consulta do contrato (item 8),
implementada também no SQLite em `helper/consulta.py`, como as consultas que já existem.

Rotina completa: `preparar` → `veiculos` → `fotos` → `publicar`. O `preparar` passa a gravar
em `meta` a hora em que rodou, e o `publicar` se recusa a gravar a parte de veículos se o
`veiculos` for mais antigo que o último `preparar`, porque uma fusão de peças pode ter mudado
ids, e pede para rodar `helper.py veiculos`.

## 7. Publicação (dentro do `publicar` que já existe)

Depois das peças, porque `peca_veiculo` aponta para `peca`. Fotos antes das linhas do banco,
como já é regra.

1. **Montadoras:** lê a `montadoras` do Wayap e casa pelo item 5.1. As que faltam são
   inseridas com `descricao` = nome canônico e `sigla` nula, como a pesquisa por placa do
   Wayap já faz. O `id_montadora` volta para o banco local. O helper **nunca altera**
   `descricao` nem `sigla` de montadora existente.
2. **Logos:** para cada montadora com `logo` nulo no Postgres e logo local, monta numa pasta
   temporária `montadoras/<id_montadora>.png` e envia por `rsync --ignore-existing` para
   `/home/wayap/helper/montadoras/`, o que nunca sobrescreve os arquivos do Francisco. Depois,
   `UPDATE montadoras SET logo = 'montadoras/<id>.png' WHERE id_montadora = ? AND logo IS NULL`.
3. **Fotos de modelo:** `rsync` de `helper_fotos_veiculos/modelos/` para
   `/home/wayap/helper/modelos/`, com as mesmas opções de hoje (sem apagar no destino, dono
   root, 755/644, retomável).
4. **Árvore:** grava só os modelos cujo `hash_conteudo` mudou ou que não existem no destino:
   upsert do modelo e das versões (ids estáveis, versão nunca é apagada) e troca dos anos de
   cada versão daquele modelo.
5. **`peca_veiculo`:** grava só as peças cujo `hash` difere do `hash_publicado`: apaga as
   linhas da peça no destino e insere as novas, em lotes de 500 peças. Peça inativada perde as
   linhas. A primeira carga, de milhões de linhas, usa `COPY`.
6. Uma transação por etapa (montadoras, árvore, `peca_veiculo`). Uma falha no meio deixa as
   etapas seguintes para a próxima rodada, que continua de onde parou, porque tudo é por
   diferença.
7. `--ensaio` mostra as montadoras que seriam inseridas (pelo nome), os logos e as fotos a
   enviar e as contagens por tabela, sem gravar nada. Rodar duas vezes seguidas grava zero
   linhas e envia zero arquivos.
8. `carga` ganha as colunas `modelos_publicados` e `ligacoes_veiculo`. `versao_esquema` = 2.

## 8. Contrato com o Wayap: consultas novas

Numeradas depois das quatro da spec do helper. Todas devolvem só modelos e versões ativos e
peças ativas, e nunca expõem `origem`, `veiculo_fonte` nem ids do KarHub. URLs de arquivo:
`'/files/aGVscGVy/' || caminho_relativo`.

5. **`v_montadora_veiculo`:** `id_montadora`, `descricao`, `logo_url`, `qtd_modelos`,
   `qtd_pecas`; só montadoras com modelo ativo.
6. **`v_modelo`:** `id_modelo`, `id_montadora`, `nome`, `nome_exibicao`, `foto_url` (nula sem
   foto), `ano_inicio`, `ano_fim`, `qtd_pecas`.
7. **`anos_do_modelo(id_modelo)`:** anos em ordem decrescente.
   **`versoes_do_ano(id_modelo, ano)`:** `id_versao`, `nome_exibicao`, `motor`.
8. **`pecas_por_veiculo(id_modelo, ano, id_versao DEFAULT NULL, texto DEFAULT NULL,
   limite DEFAULT 100)`:** colunas de `v_peca` mais `confianca`. Com `texto`, filtra
   `desc_curta` como a `busca_texto`.
9. **`ids_por_veiculo(id_modelo, ano, id_versao DEFAULT NULL)`:** `id_peca`, `confianca`, sem
   limite. É para o Wayap cruzar com o estoque do cliente pelo id da peça guardado no produto,
   já que o Postgres não junta tabelas de dois bancos.

Regra da `confianca`, para o modelo M e o ano A escolhidos:

| Situação da peça | Versão escolhida | Sem versão escolhida |
|---|---|---|
| Linha `versao` com `id_versao` nulo cobrindo A | `versao` | `todas_versoes` |
| Linha `versao` com a versão escolhida cobrindo A | `versao` | não se aplica |
| Só linhas `versao` de outras versões cobrindo A | **fica de fora** (o KarHub diz que não serve) | `algumas_versoes` |
| Sem linha `versao` em (M, A), com linha `modelo` cobrindo A | `modelo_ano` | `modelo_ano` |

Ordem: `versao` e `todas_versoes`, depois `algumas_versoes`, depois `modelo_ano`; dentro de
cada grupo, semelhança com o texto (quando há), `tem_foto` e `qtd_fontes`, como nas outras
consultas.

## 9. Verificação

- **Testes unitários** (pytest), com respostas reais da API do KarHub guardadas em
  `tests/dados/karhub_veiculos/` (Chevrolet/Tracker, Volkswagen/Gol): leitura da árvore;
  agrupamento do item 5.5 (ano completo vira `id_versao` nulo; ano incompleto lista versões;
  ano sem versão não quebra a faixa; id desconhecido é contado); casamento de montadora
  (`MERCEDES BENZ` com `MERCEDES-BENZ`, `KIA` com `KIA MOTORS`, nome novo); nível `modelo`
  (com montadora, sem montadora e único, sem montadora e ambíguo); ids estáveis ao recarregar a
  árvore; modelo ausente vira inativo; foto própria tem prioridade; regra de `confianca` da
  tabela do item 8 na versão SQLite.
- **Publicação:** com um Postgres falso, como nos testes atuais: montadora existente não é
  alterada; `logo` preenchido não é tocado; o rsync de logos usa `--ignore-existing`; segunda
  publicação grava zero linhas. Integração real com `HELPER_TESTE_PG=1`, como hoje, cobrindo
  as funções do item 8.
- **Relatório `veiculos.md`:** montadoras (casadas com as do Wayap, novas a inserir), modelos,
  versões, anos-versão, modelos com e sem foto, peças ligadas por nível, linhas de
  `peca_veiculo`, ids de veículo desconhecidos, as 50 aplicações mais comuns que não casaram.
- **Conferência manual:** para três veículos (Tracker 2021 1.2 Turbo, Gol 2010, Palio 2005),
  `pecas-do-veiculo` com `--texto TAMBOR` e `--texto PASTILHA` comparado com a página de
  categoria do KarHub filtrada pelo mesmo veículo. As peças que o KarHub mostra precisam
  aparecer com confiança `versao` ou `todas_versoes`.
- **Antes da primeira carga:** `publicar --ensaio` revisado pelo Francisco, principalmente a
  lista de montadoras novas.

## 10. Operação e volumes

- **Primeira carga:** `catalogo_karhub_veiculos.py arvore` (6 a 10 h), `compat` (1 a 2 h),
  `helper.py veiculos`, `pecas-do-veiculo` nos três veículos, `publicar --ensaio`, `publicar`.
- **Rotina:** `arvore --do-inicio` uma vez por mês (sem a opção, ele só completaria modelos
  ainda ausentes e não pegaria anos novos dos que já estão no arquivo); `compat --do-inicio`
  sempre que o `catalogo_karhub.py` for rodado de novo; depois `veiculos` e `publicar`.
- **Volumes:** 159 montadoras (cerca de 90 a inserir na `montadoras` do Wayap), 3.495
  modelos; versões e anos-versão medidos na primeira coleta. Fotos: cerca de 3.500 × 35 KB ≈
  120 MB. `peca_veiculo`: estimativa de 5 a 15 milhões de linhas (cerca de 1 GB com índices),
  medida pelo relatório da primeira preparação; o servidor tem cerca de 300 GB livres.

## 11. Riscos

- **Dados e fotos são do KarHub.** O nome do site nunca aparece no Wayap; foto e logo próprios
  substituem os do KarHub sem mexer em código (seção 6, passo 2).
- **O KarHub pode mudar ou fechar a API.** O coletor para com erro claro; os dados já
  publicados continuam valendo; a ligação de nível `modelo` não depende do KarHub.
- **Bloqueio.** Ritmo baixo, uma chamada por vez, tudo retomável.
- **Montadora duplicada na tabela do Wayap** (inserir `KIA` com `KIA MOTORS` já existente):
  normalização, `helper_montadoras.csv` e o ensaio, que lista as inserções antes da primeira
  carga.
- **Lista de montadoras do Wayap fica maior.** Entram cerca de 90, inclusive de motos,
  caminhões e ônibus, e aparecem onde o Wayap lista montadoras hoje (cadastro de carro, por
  exemplo). Se incomodar, o Wayap filtra pelas que têm `qtd_pecas` em `v_montadora_veiculo`.
- **Ligação errada pelo texto de aplicação.** O nível `modelo` sempre aparece como "confira a
  versão", nunca como confirmado.

## 12. Fases seguintes (Wayap, cada uma com spec própria)

1. **Produto guarda o `id_peca` do helper**, preenchido por uma rotina que casa EAN e código
   (as consultas 1 e 2 do contrato). Sem isso, o estoque do cliente não cruza com a consulta 9.
2. **Tela "Peças para o veículo"**, com o componente do filtro (montadora, modelo com foto,
   ano, versão) feito uma vez e reaproveitado, e as duas listas (estoque e mercado).
3. **Aba "Placa" do filtro:** a pesquisa por placa do Wayap já grava em `placas_detalhes`
   marca, modelo, ano e versão. Casar esse texto com a árvore leva a placa direto à versão. O
   Wayap já tem fonte própria de placa, então não depende da consulta de placa do KarHub.
4. **`carro_cliente` escolhido pela árvore** em vez de texto livre, para a venda ou a OS já
   abrirem o filtro no carro do cliente.
5. **Cadastro de produto** mostrando os veículos da peça do helper.
