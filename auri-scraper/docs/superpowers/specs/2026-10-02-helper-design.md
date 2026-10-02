# Helper: base de peças do mercado para auxiliar o cadastro nos clientes do Wayap

Data: 2026-10-02. Status: aprovado em conversa, aguardando revisão do texto.

## 1. Contexto e objetivo

O Wayap é um ERP de autopeças com um banco Postgres por sociedade (cliente) e uma pasta de
fotos por sociedade em `/home/wayap/<sociedade>/store/foto_produto/<cod_produto>/<arquivo>`.
Este repositório já raspa catálogos de sete lojas (`catalogos/*.jsonl`, 377 mil anúncios,
940 mil URLs de foto) e peças completas de outras três (`pecas_*/produto.json`, cerca de
17 mil peças com fotos baixadas, 11 GB), e tem um painel local (`painel_wayap.py`) que usa
esses dados para cadastrar produtos na sociedade `topcar`.

O **helper** leva essa capacidade para dentro do Wayap, para todos os clientes: um banco de
leitura com **uma linha por peça do mercado**, com códigos, EAN, aplicações e fotos, montado e
mantido aqui e publicado no servidor do Wayap. Três telas do Wayap vão consumi-lo, cada uma
em sua própria spec futura:

1. **Cadastro de produto:** o cliente digita código, EAN ou descrição e recebe o formulário
   pré-preenchido com fotos.
2. **Entrada de nota fiscal:** para cada item da nota sem produto cadastrado, o Wayap consulta
   o helper pelo EAN e pelo código e oferece o cadastro.
3. **Reconhecimento de peça usada:** fotos tiradas no estoque passam por um modelo de visão
   que lê códigos e identifica tipo, montadora e lado; o helper devolve candidatos para a
   pessoa escolher.

Nenhuma tela mostra de que site veio o dado. O nome do site fica no helper apenas como
proveniência interna.

### Divisão de responsabilidades

- **Aqui (este repositório):** raspar, normalizar, fundir, curar fotos, publicar. Todo o
  trabalho pesado e toda correção acontecem aqui, antes de publicar.
- **Wayap:** só lê o helper, casa marca e carro com os ids de cada cliente e chama o cadastro
  de produto e a subida de fotos que já existem. Nesta fase o Wayap **não escreve** no helper.
- **Contrato entre os dois:** o esquema do banco `helper`, as quatro consultas garantidas e a
  regra de URL das fotos (seção 7). Mudança nesse contrato passa por esta spec.

## 2. Escopo

Dentro desta spec:

- Banco local de preparação (`helper.sqlite`) e pasta local de fotos (`helper_fotos/`).
- Comando `helper.py` com os passos de preparação, fotos, publicação e relatórios.
- Banco Postgres `helper` no servidor do Wayap e pasta `/home/wayap/helper/store/foto_produto/`.
- Primeira carga (todas as peças, fotos já baixadas) e ondas seguintes de fotos por prioridade.
- Testes de normalização, fusão, cobertura contra a topcar e idempotência da publicação.

Fora desta spec, de propósito, cada um como spec própria depois:

- As três telas do Wayap.
- Assinatura visual (embedding) das fotos para o Reconhecimento. O modelo reserva o campo.
- Fila de fotos por demanda pedida pelo Wayap (exigiria o Wayap escrever no helper).
- Volta de dados dos clientes para o helper (peças, correções e fotos de peça usada).
- Mudanças nos scrapers e no painel. O painel pode passar a ler o `helper.sqlite` no futuro.

## 3. Decisões fechadas

| Decisão | Escolha | Motivo |
|---|---|---|
| Granularidade | Uma linha por peça, fundida aqui | Cliente não deve escolher entre 4 anúncios iguais; a fusão é trabalho pesado e fica onde se corrige |
| Identidade da peça | Marca canônica + código do fabricante | É como o mercado identifica a peça; EAN é segunda chave de junção |
| **Código do fabricante** | **String, exatamente como vem, com zero à esquerda** | O código impresso pelo fabricante é o oficial. Nunca se tira zero nem se cria variante sem zero |
| Onde o helper mora | Banco `helper` no mesmo Postgres das sociedades; fotos em `/home/wayap/helper/store/foto_produto/` | Infra que já existe; URL de foto igual à da topcar trocando a sociedade |
| Como publica | Postgres direto (`.env_admin`) e `rsync` por SSH | Carga em massa e retomável; sem endpoint novo no Wayap |
| Ids | Inteiros atribuídos aqui, nunca reaproveitados nem alterados após publicar | O id é o nome da pasta de fotos e a referência que as telas guardam |
| Remoção | Nunca apaga peça publicada; marca inativa | Telas e clientes podem ter referência ao id |
| Proveniência | Guardada por anúncio, nunca exibida | Reprocessar, desempatar, apagar uma fonte inteira se preciso |
| Fotos | Todas as que passarem na curadoria, com origem classificada e flag publicável | Servidor tem 1 TB livre; a decisão de mostrar foto de loja fica com o dono, por flag |
| Ordem de publicação | Fotos antes do banco | Banco nunca aponta para arquivo ausente |

## 4. Modelo de dados

Mesmo modelo no `helper.sqlite` local e no Postgres `helper`. Nomes em português, no padrão
do Wayap. Tipos em palavras; o plano de implementação fixa o DDL.

### 4.1 `peca`

Uma linha por peça do mercado.

| Campo | Conteúdo |
|---|---|
| `id_peca` | inteiro, chave, atribuído aqui, estável |
| `id_marca` | referência a `marca` |
| `codigo` | texto, código do fabricante **como o fabricante imprime**, com zeros; sem espaços, pontos e traços de separação; maiúsculas |
| `ean` | texto de 13 dígitos ou nulo; EAN principal (o mais confirmado) |
| `desc_curta` | texto até 45 caracteres, padrão da casa (maiúsculas, sem conectivos, sem marca e código no fim) |
| `desc_completa` | texto até 400, nome mais descritivo entre as fontes |
| `tipo_peca` | texto, primeiras palavras significativas da descrição (ex.: `LANTERNA TRASEIRA`, `JOGO CABO VELA`) |
| `ncm_sugerido` | texto de 8 dígitos ou nulo; estatística da topcar por tipo e marca, é sugestão |
| `unidade_sugerida` | `PC`, `JG`, `KT`, `PA`...; pela primeira palavra ou pela moda da marca |
| `tem_foto` | booleano; verdadeiro quando há ao menos uma foto publicável |
| `qtd_fontes` | inteiro, quantos anúncios contribuíram |
| `status` | `ativa` ou `inativa` |
| `fundida_em` | `id_peca` da sobrevivente quando esta foi inativada por fusão; nulo nos demais casos |
| `hash_conteudo` | hash de todos os campos acima, para publicar por diferença |
| `atualizado_em` | data da última mudança de conteúdo |

Chave única: (`id_marca`, `codigo`).

### 4.2 `codigo_alternativo`

Vários por peça. Chave única (`id_peca`, `tipo`, `valor`).

| Campo | Conteúdo |
|---|---|
| `id_peca` | referência |
| `tipo` | `ean` (EANs adicionais), `original` (código de montadora informado pelo site), `kit` (código de componente de kit), `fabricante` (código secundário do próprio fabricante quando a fonte traz dois) |
| `valor` | texto, como veio, com zeros |
| `qtd_fontes` | quantas fontes confirmam |

Não existe tipo "sem zero": grafia divergente só no zero à esquerda fica na `origem`, não aqui.

### 4.3 `aplicacao`

Várias por peça. Chave única (`id_peca`, `montadora`, `modelo`, `ano_inicio`, `ano_fim`, `motor`).

| Campo | Conteúdo |
|---|---|
| `id_peca` | referência |
| `montadora` | texto canônico (`VOLKSWAGEN`, `FIAT`...), nulo quando a fonte não diz |
| `modelo` | texto canônico (`GOL`, `LOGAN`...), vocabulário inicial = tabela de carros da topcar |
| `ano_inicio`, `ano_fim` | inteiros de 4 dígitos ou nulos; faixas não contínuas viram linhas separadas |
| `motor` | texto ou nulo |
| `observacao` | texto ou nulo (`LADO ESQUERDO`, `COM AVARIA`...) |
| `texto_original` | como a fonte escreveu, para auditoria |

### 4.4 `foto`

Várias por peça, ordenadas. Chave única (`id_peca`, `arquivo`).

| Campo | Conteúdo |
|---|---|
| `id_peca` | referência |
| `ordem` | 1 = principal |
| `arquivo` | `<sha1 do conteúdo>.jpg` (ou `.png` quando o original é PNG sem transparência) |
| `largura`, `altura`, `bytes` | inteiros |
| `dhash` | 64 bits, para duplicata |
| `origem_tipo` | `fabricante` ou `loja` |
| `publicavel` | booleano; padrão verdadeiro; o dono pode desligar por origem ou por foto |
| `assinatura_visual` | reservado, nulo nesta fase (vetor para semelhança no Reconhecimento) |
| `url_fonte` | URL de onde foi baixada |

A miniatura `<sha1>_p.jpg` (300 px no maior lado) existe sempre e não tem linha própria.

### 4.5 `origem`

Uma linha por anúncio de site que contribuiu. Nunca exibida.

| Campo | Conteúdo |
|---|---|
| `id_peca` | referência |
| `site` | `karhub`, `carblue`, `shoppecas`, `universal`, `clicpecas`, `fuscaopreto`, `azacessorios`, `auri`, `autonext`, `hipervarejo`, e novos |
| `url` | URL do anúncio |
| `nome_original`, `marca_original`, `codigo_original`, `ean_original`, `carro_original` | como o site mostrou |
| `coletado_em` | data do arquivo de catálogo lido |

Chave única (`site`, `url`).

### 4.6 `marca`

| Campo | Conteúdo |
|---|---|
| `id_marca` | inteiro |
| `nome` | texto canônico, maiúsculas sem acento |
| `tipo` | `reposicao`, `montadora`, `desconhecida` |

E `marca_apelido` (`id_marca`, `apelido`): grafias que os sites usam (`UNIVERSAL`, `UNIVEL`, `UNIVERSAL AUTOMOTIVE`...). Carregada de um arquivo editável `helper_marcas.csv` neste repositório, que começa com as marcas da topcar e os pares que `marcas_compativeis` reconhece hoje.

### 4.7 `carga`

Histórico de publicações: `id_carga`, `iniciada_em`, `terminada_em`, `pecas_ativas`, `pecas_inativadas`, `fotos_publicadas`, `bytes_fotos`, `versao_esquema`, `commit` do repositório.

## 5. Preparação (`helper.py`, roda aqui)

Subcomandos independentes e retomáveis, todos gravando no `helper.sqlite`:

```
python helper.py preparar [--site X] [--marca Y]   # lê fontes, normaliza, funde, gera peças
python helper.py fotos [--prioridade|--marca|--tipo|--limite N]   # baixa, cura, gera miniaturas
python helper.py relatorio                           # contagens e qualidade da fusão
python helper.py cobertura                           # quanto da topcar o helper encontra
python helper.py publicar [--ensaio]                 # rsync das fotos, depois Postgres
```

### 5.1 Fontes lidas

- `catalogos/*.jsonl`: campos `site, url, nome, marca, codigo_fabricante, ean, carro, imagens`
  (ClicPeças traz também `codigo_original` e `codigo_loja`).
- `pecas_*/*/produto.json`: `nome, marca, codigo_fabricante, ean, categoria, ficha_tecnica,
  aplicacoes` estruturadas, `observacoes`, `imagens` locais. Têm prioridade sobre o catálogo do
  mesmo site por serem mais ricas.
- Dados da topcar (via API, como o painel faz): tabela de marcas e carros como vocabulário e
  estatística de NCM e unidade por tipo e marca. Lidos uma vez e guardados em cache local.

Um site novo entra ao gravar seu `.jsonl` em `catalogos/`; o `preparar` indexa só o que mudou
desde a última vez, pela data do arquivo, como o painel já faz.

### 5.2 Normalização

- **Marca:** procura em `marca_apelido`; sem apelido, cria marca `desconhecida` com o nome como
  veio e registra no relatório para o dono classificar no `helper_marcas.csv`.
- **Código:** remove espaços, pontos e traços de separação; maiúsculas. **Mantém zeros à
  esquerda.** Não gera nenhuma variante.
- **Kit** (`GS2116 / GS2118`): o código da peça é o texto completo normalizado; cada parte vira
  `codigo_alternativo` do tipo `kit`.
- **EAN:** só EAN-13 com dígito verificador válido; o resto é descartado e contado.
- **Descrição curta:** regra atual do painel (`sugestao`): tira marca e código do fim, remove
  conectivos, maiúsculas sem acento, corta em 45 caracteres em fronteira de palavra.
- **Tipo de peça:** primeiras duas palavras significativas da descrição curta, ignorando
  `JOGO`, `KIT`, `PAR` e conectivos; `palavras_chave` do painel.
- **Aplicação:** texto livre passa por `ocorrencias_do_texto` e `juntar_anos` do painel;
  aplicações estruturadas dos `produto.json` entram direto; modelo casado com o vocabulário
  por `achar_carro`; o que não casa fica com `modelo` igual ao texto e vai para o relatório.

### 5.3 Fusão

Processada por marca, em ordem determinística (site, url), para o resultado ser reproduzível.

1. Anúncios com mesma marca canônica e mesmo código fundem-se.
2. Anúncios com mesmo EAN e marcas compatíveis fundem-se, mesmo com códigos diferentes.
   Códigos que diferem só em zero à esquerda: o código oficial da peça é o que tem zero; a
   outra grafia fica só na `origem`. Códigos realmente diferentes com mesmo EAN: vale o código
   que mais fontes confirmam, o outro vira `codigo_alternativo` do tipo `fabricante`, e o caso
   vai para o relatório de conflitos.
3. EAN divergente entre fontes com mesmo código: principal é o mais confirmado; os demais
   viram `codigo_alternativo` do tipo `ean`; conta como conflito.
4. Dois anúncios com mesmo código e marcas diferentes e não compatíveis **não** se fundem.
5. Sem marca e sem EAN: a peça é criada com marca `desconhecida`; entra no relatório e não se
   funde com ninguém por código.
6. Descrições: curta pela fonte de maior prioridade (`produto.json` > Universal > KarHub >
   ShopPeças > CarBlue > demais); completa é a mais longa até 400.
7. Aplicações: união de todas, com junção de anos adjacentes.
8. Fotos: união das URLs, deduplicadas por URL agora e por dHash após o download.

Ids: peça nova recebe o próximo id; peça que já existe (mesma marca e código) mantém o id. Se
uma fusão juntar duas peças que já tinham ids publicados, a de menor id fica e a outra vira
`inativa` com um campo `fundida_em` apontando para a sobrevivente. Ids nunca voltam a ser
usados.

### 5.4 Fotos

Reaproveita as funções de `wayap_fotos.py`:

- Download com cache e repetição; IPv4 forçado como no painel.
- Descarta menor lado < 250 px, logos e "sem foto" pelas listas existentes.
- Reduz para no máximo 1024 px no maior lado; PNG transparente ganha fundo branco e vira JPEG.
- Duplicata por dHash (distância ≤ 6) dentro da mesma peça: fica a de maior resolução.
- Ordem: fotos do `produto.json` primeiro (já curadas), depois por prioridade de site.
- Miniatura de 300 px, `<sha1>_p.jpg`, gerada sempre.
- `origem_tipo`: `fabricante` quando o site é loja do próprio fabricante (hoje: `universal`)
  ou quando o host da imagem está numa lista de domínios de fabricantes em `helper_fotos.toml`;
  `loja` nos demais. Lista editável.
- Sem limite de fotos por peça no helper (o limite de 5 é do envio para a sociedade).

Ondas: `fotos --limite` com `--prioridade` baixa primeiro os tipos de peça da lista de
prioridade (lanterna, farol, para-choque, retrovisor, grade, porta, capô, paralama), depois o
resto por ordem de `qtd_fontes`.

## 6. Publicação

- Credenciais do Postgres: `.env_admin` do Wayap (`POSTGRES_HOST`, `PORT`, `USER`,
  `PASSWORD`). Banco `helper` criado pelo próprio `publicar` se não existir, com o esquema da
  seção 4 e as extensões `unaccent` e `pg_trgm` (se indisponíveis, a busca por texto cai para
  `to_tsvector` simples e o relatório avisa).
- Destino das fotos: `HELPER_SSH` no `.env` deste repositório (ex.: `wayap@servidor`), pasta
  `/home/wayap/helper/store/foto_produto/<id_peca>/`. `rsync -a --partial` da pasta local
  `helper_fotos/`, só arquivos novos; nunca apaga no destino.
- Ordem: fotos, depois linhas do banco, dentro de uma transação por tabela, em lotes.
- Diferença: só grava linhas cujo `hash_conteudo` mudou ou que não existem no destino.
  Peça ausente da preparação vira `inativa`. Rodar duas vezes seguidas grava zero linhas.
- `--ensaio` imprime o que mudaria (contagens por tabela, bytes de fotos) sem gravar.
- Cada execução grava uma linha em `carga`.

## 7. Contrato com as telas do Wayap

O helper garante estas consultas, cada uma com índice próprio no Postgres:

1. **Por código:** busca em `peca.codigo` e em `codigo_alternativo.valor` (todos os tipos),
   com o texto digitado normalizado da mesma forma (sem espaços, pontos, traços; maiúsculas).
   Tolerância: se não houver resultado exato, tenta também ignorando zeros à esquerda **do
   texto digitado e do banco na comparação**, sem alterar o dado. Devolve peças ativas.
2. **Por EAN:** `peca.ean` e `codigo_alternativo` tipo `ean`.
3. **Por texto:** `desc_curta`, `desc_completa` e nomes de aplicação, sem acento e com
   tolerância a erro de digitação (`pg_trgm`), ordenado por semelhança e `qtd_fontes`.
4. **Por tipo de peça e montadora/modelo:** filtro para o Reconhecimento, com opção de
   `tem_foto = true`; devolve com a foto principal.

Resposta de uma peça: campos de `peca`, nome da marca, lista de aplicações, lista de fotos
publicáveis em ordem. Nunca inclui `origem`.

URL de foto: `/files/<base64("helper")>/store/foto_produto/<id_peca>/<arquivo>`, igual à
topcar com a sociedade trocada; miniatura em `<arquivo sem extensão>_p.jpg`.

O Wayap faz, por conta própria: casar `marca.nome` com o `id_marca` do cliente (criando a
marca se não existir), casar `aplicacao.modelo` com o `id_carro` do cliente, e aplicar os
limites do produto do cliente (`desc_produto` 100, `num_fabricante` 15, `cod_barra` 13,
`ncm` 8, `unidade` 2). Códigos com mais de 15 caracteres são avisados ao usuário, nunca
cortados.

## 8. Verificação

- **Testes unitários** (pytest, novo neste repositório) de normalização e fusão com casos
  reais do projeto: Arteb `0160818` vs `160818` com mesmo EAN (funde, código fica com zero)
  e sem EAN (não funde); kit `0460361 + 0460362` da Hipervarejo; EAN divergente AutoNext vs
  ficha; mesma peça KarHub e CarBlue com nomes diferentes; marcas Universal/Univel; peça sem
  marca.
- **`helper.py cobertura`:** para cada produto da topcar com EAN ou código, verifica se o helper
  encontra a peça pelas consultas 1 e 2 do contrato. Imprime cobertura por marca. É a medida de
  "quanto o helper já serve".
- **`helper.py relatorio`:** anúncios lidos por site, peças ativas, inativas, fundidas,
  conflitos de EAN e de código, peças sem marca, sem código, sem aplicação, sem foto, marcas
  desconhecidas a classificar, modelos de carro não reconhecidos. Guardado em
  `helper_relatorios/<data>.md` para comparar entre cargas.
- **Publicação:** `--ensaio` antes de toda carga; teste de idempotência (publicar duas vezes,
  segunda grava zero linhas e zero fotos); conferência amostral de 20 URLs de foto no servidor
  depois da primeira carga.
- **Reprodutibilidade:** `preparar` duas vezes sobre as mesmas fontes gera o mesmo
  `hash_conteudo` em todas as peças.

## 9. Operação

- Primeira carga: `preparar` completo, `fotos` só do que já está baixado (`pecas_*`),
  `relatorio`, `cobertura`, `publicar --ensaio`, `publicar`.
- Rotina: quando um catálogo é re-raspado, `preparar` (incremental), `fotos --prioridade
  --limite`, `publicar`. Logs em `helper_relatorios/`.
- Volumes esperados: 377 mil anúncios devem virar bem menos peças (KarHub e CarBlue se
  sobrepõem muito; o relatório da primeira preparação dá o número). Fotos: até 940 mil URLs,
  estimativa de 400 a 500 mil após dedup, 90 a 120 GB; cabe no 1 TB livre do servidor.
- Tempo: download de fotos é limitado pelos CDNs das lojas; conta-se em dias, por isso as ondas.

## 10. Riscos e como a spec os trata

- **Fotos de loja são obra de terceiros.** Classificadas por origem e com flag `publicavel`;
  decisão de exibir é do dono, por configuração, não acidente. Nome do site nunca aparece.
- **Fusão errada junta peças diferentes.** Só funde por código+marca ou EAN+marca compatível;
  nunca por semelhança de nome; conflitos vão para o relatório; peças fundidas ficam
  rastreáveis por `fundida_em` e `origem`.
- **Catálogos desatualizados.** Visível em `origem.coletado_em` e no relatório; re-raspar é
  rotina existente.
- **Contrato muda.** Toda consulta nova do Wayap passa por esta spec; `carga.versao_esquema`
  permite ao Wayap checar compatibilidade.

## 11. Fases seguintes (fora desta spec)

1. Tela de cadastro de produto consumindo o helper.
2. Entrada de nota fiscal: itens sem produto consultados por EAN e código.
3. Reconhecimento de peça usada: modelo de visão + consultas 1, 3 e 4; depois assinatura
   visual preenchendo `foto.assinatura_visual`; antes disso, o Wayap precisa guardar o
   histórico dos reconhecimentos resolvidos (fotos + produto escolhido) como gabarito.
4. Fila de fotos por demanda e volta de dados dos clientes para o helper.
