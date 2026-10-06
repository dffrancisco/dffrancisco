# Helper: veículos (montadora → modelo → ano → versão), fotos e peças por veículo

Data: 2026-10-03. Status: aprovado em conversa (helper não grava em tabela do Wayap), aguardando
revisão do texto. Em 2026-10-04 o escopo passou de "só carros e utilitários" para **todos os
veículos** (carros, utilitários, motos, caminhões e ônibus), com o tipo gravado em cada modelo.
Também em 2026-10-04, a pedido do dono, todo objeto de veículos no banco (tabelas, índices, views
e funções) passou a começar com `vei_`, para aparecerem juntos e se distinguirem das tabelas do
Wayap: `veiculo_modelo` virou `vei_modelo`, `peca_veiculo` virou `vei_peca`, `v_veiculo_modelo`
virou `vei_v_modelo`, `pecas_por_veiculo` virou `vei_pecas_por_veiculo` e assim por diante.
Colunas não mudaram.

Complementa a spec do helper (`2026-10-02-helper-design.md`). Acrescenta um coletor, tabelas e
consultas ao contrato da seção 7 daquela spec, e sobe `versao_esquema` para 3 (o 2 foi a
`peca_localizador`, emenda de 2026-10-04 daquela spec). Nada do que já
existe muda de significado.

## 1. Objetivo

Levar para o Wayap o filtro "Confira se serve no seu veículo" do KarHub: montadora (com logo) →
modelo (com foto do carro) → ano → versão. Com ele, o Wayap vai ter a tela **"Peças para o
veículo"** no balcão: o vendedor escolhe o veículo, digita o que procura ("pastilha") e vê duas
listas:

- **No seu estoque:** produtos do cliente que servem, com quantidade e preço.
- **No mercado:** peças do helper que servem e que o cliente não tem, para encomendar ou
  cadastrar.

O cliente não cadastra aplicação nenhuma. O produto dele se liga à peça do helper pelo EAN ou
pelo código do fabricante, e a peça do helper sabe em quais veículos serve. Em 2026-10-02 essa
ligação já alcançava 41% dos produtos da topcar (28 mil de 68 mil; Universal e Perfect acima
de 95%), e cresce a cada site raspado.

Esta spec cobre só a **fase 1, no helper**: coletar a árvore de veículos, logos, fotos e
compatibilidade, ligar às peças, publicar e garantir as consultas. As telas do Wayap são specs
próprias (seção 13).

## 2. O que já existe e orienta o desenho

**Fonte: API do próprio site do KarHub** (rotas `/api/...` do site, testadas em 2026-10-03):

| Rota | Devolve |
|---|---|
| `/api/get-vehicles` | 159 montadoras (`label`, `handle`) |
| `/api/get-vehicles?brand=chevrolet` | modelos da montadora (3.495 no total, misturando carros, utilitários, caminhões, ônibus e motos) |
| `...&model=Tracker` | anos do modelo, cada um com os ids de veículo daquele ano |
| `...&year=2021` | versões do ano (`label`, `handle`) com **um id de veículo cada** (ex.: "4x2 Aut. 1.2 12v L3 Turbo" = 62329) |
| `/api/get-automaker-content?handle=chevrolet/tracker` | foto do modelo (`images.karhub.com.br/veiculos/chevrolet-tracker.avif`, 600×450, fundo transparente) e logo da montadora (`.../assets/montadoras/chevrolet.avif`, 200×200, fundo transparente) |
| `/api/product-compatible-ids?handles=h1,h2,...` | para cada produto, os ids de veículo que ele atende; até 50 por chamada (com 100, volta vazio sem erro) |

- **Id de veículo:** é um par (versão, ano). Os ids de um ano são exatamente a união dos ids das
  versões daquele ano, e não há rótulo de versão repetido no mesmo ano.
- **Logos:** 156 das 159 montadoras têm (faltam Iros, MG e Mottu).
- **Fotos de modelo:** só os modelos mais vendidos têm, cerca de 1 em 4 (Chevrolet 16 de 75:
  Onix, Tracker, S10, Celta...; Fiat 15 de 49: Uno, Palio, Strada, Toro...). Variações costumam
  ficar sem foto (Astra Hatch sem, Astra com).
- **Acesso:** o site e as imagens ficam atrás do Cloudflare. `requests` puro recebe 403; o
  `Fetcher` do Scrapling com `stealthy_headers` passa, como em `catalogo_karhub.py`. Durante os
  testes houve alguns minutos de conexão recusada no meio de uma sequência de chamadas.

**A API não diz o tipo do veículo**, e as montadoras misturam tipos (Mercedes-Benz tem 565
modelos, a maioria caminhão e ônibus; Honda tem carros e motos). Duas fontes resolvem:

- **FIPE** (`parallelum.com.br/fipe/api/v1`, pública, sem token): três listas, "carros"
  (a categoria oficial é "Carros e utilitários pequenos"), "motos" e "caminhoes" ("Caminhões e
  micro-ônibus"), com os modelos de cada marca. Testada nas marcas mistas, ela classifica uns
  50% dos modelos do KarHub pelo nome; o resto tem grafia diferente ou é antigo demais.
- **Nome das versões no KarHub:** moto traz cilindrada em cc ("Ks 100cc"); caminhão e ônibus
  trazem tração 6x2/6x4/8x2/8x4 ou motor grande com fase de emissão P ("4x2 6.0 12v L6 E 1 P 3");
  carro traz portas e câmbio ("4p Mec."). Utilitário diesel leve também tem fase P, mas motor
  pequeno ("Daily: Furgão 4x2 2.3 16v Turbo E 5 P 6").

**O banco `helper` no Postgres já tem tabelas do próprio Wayap**, além das do helper:
`montadoras` (71 linhas, global, mantida pelo Wayap e pela pesquisa por placa; `carro.id_montadora`
de cada sociedade aponta para ela; `logo` guarda caminho relativo como `montadoras/11.png`),
`placas_detalhes`, `schema_migrations`, `menu` e outras. Em `/home/wayap/helper/montadoras/`
estão 5 logos feitos pelo Francisco (Chevrolet, Citroën, Fiat, Toyota e BYD). O helper **não
grava em nenhuma tabela nem pasta do Wayap**: tem as suas, com prefixo `vei_` para não
colidir com nomes que o Wayap use ou venha a usar no mesmo banco, e só lê a `montadoras` para
ligar as duas.

**A tabela `carro` de cada sociedade continua como está.** Ela é por cliente, no nível de modelo,
e é usada em `produto`, `produto_venda`, `similar`, filtros e relatórios. A árvore entra ao lado.

**As aplicações que o helper já tem** (667 mil linhas, texto de todos os sites): 78% casam com
um nome de modelo da árvore pelo prefixo. Elas dão a ligação de nível "modelo" para as peças que
o KarHub não cobre.

## 3. Decisões fechadas

| Decisão | Escolha | Motivo |
|---|---|---|
| Fonte da árvore e da compatibilidade | API do site do KarHub, coletada aqui | Única fonte com versão por ano, foto do modelo e ligação produto → versão |
| Escopo de veículos | **Todas as montadoras e todos os modelos** do KarHub (carros, utilitários, motos, caminhões e ônibus), cada modelo com `tipo` `carro`, `moto` ou `pesado` (seção 5.1) | Pedido do dono em 2026-10-04 (antes eram só carros e utilitários); o Wayap filtra pelo tipo |
| Na dúvida | Tipo `carro`, e aparece no relatório para conferir | Tipo errado só põe o modelo na aba errada do filtro; `helper_veiculos_tipo.csv` corrige |
| Montadora | Tabela própria `vei_montadora` com `id_montadora` apontando para a `montadoras` do Wayap quando o nome casa (nulo quando não existe lá) | O helper não grava em tabela do Wayap; o Wayap decide se cria a montadora do lado dele |
| Logo exibido | O da `montadoras` do Wayap quando existe (os 5 do Francisco), senão o do helper | O que o dono fez prevalece, sem o helper tocar nos arquivos dele |
| Granularidade | `vei_modelo`, `vei_versao` e os anos de cada versão (`vei_versao_ano`) | É o que o filtro precisa: ano mostra as versões daquele ano |
| Ids | Inteiros atribuídos aqui, estáveis por nome canônico; o id do KarHub fica só no banco local | Mesmo princípio das peças: id publicado nunca muda nem é reaproveitado |
| Remoção | Modelo, versão ou montadora que some vira `ativo = false`, nunca é apagado | Telas podem guardar o id |
| Ligação peça → veículo | `vei_peca` agrupada por versão e faixa de anos, `id_versao` nulo quando serve em todas as versões | Sem agrupar seriam ~70 milhões de linhas (cerca de 400 versões-ano por produto) |
| Níveis de confiança | `versao` (confirmada pelo KarHub) e `modelo` (deduzida do texto de aplicação) | É o selo "serve nesta versão" ou "confira a versão" da tela |
| Foto do modelo | WebP com transparência, qualidade 90, 600×450 como vem | 34 KB contra 211 KB do PNG; todos os navegadores atuais abrem |
| Modelo sem foto | Herda a do modelo da mesma montadora cujo nome é o prefixo mais longo do seu (Astra Hatch → Astra), marcada como herdada | Cobre as variações sem foto; o Wayap pode mostrar genérica se preferir |
| Logo da montadora | PNG 200×200 com transparência, como os 5 que já existem | Mesmo formato |
| Foto e logo próprios | Arquivo em `helper_fotos_veiculos/proprias/` tem prioridade sobre o do KarHub | O dono troca qualquer imagem sem mexer em código |
| Arquivos no servidor | `/home/wayap/helper/veiculos/modelos/` e `/home/wayap/helper/veiculos/montadoras/`, servidos por `/files/aGVscGVy/` | Pasta só do helper; caminho relativo no banco, como `montadoras.logo` |

## 4. Coleta: `catalogo_karhub_veiculos.py`

Novo coletor na raiz, no padrão dos outros `catalogo_*.py`. Grava em `veiculos/`, e não em
`catalogos/`, porque o `preparar` lê todo `catalogos/*.jsonl` como anúncio.

```
python catalogo_karhub_veiculos.py fipe
python catalogo_karhub_veiculos.py arvore [--do-inicio] [--montadora chevrolet]
python catalogo_karhub_veiculos.py compat [--do-inicio]
```

**`fipe`** baixa as marcas e os modelos das três listas da FIPE para `veiculos/fipe.json`
(cerca de 240 chamadas, uma por segundo). Roda uma vez e quando a FIPE ganhar modelos novos.

**`arvore`** percorre as montadoras do KarHub e, para cada modelo, pede os anos e as versões do
ano mais recente. Com isso classifica o modelo (seção 5.1). Um modelo sem nenhum ano vai para
`veiculos/karhub_excluidos.jsonl` (montadora, modelo, tipo `sem_anos`) e segue. Os demais, de
qualquer tipo, seguem: pede as versões dos demais anos e o conteúdo do modelo, baixa a foto e o
logo originais para `veiculos/imagens/` (nome = caminho da URL; uma imagem que dá 404 fica como
ausente) e grava uma linha por modelo **completo** em `veiculos/karhub_arvore.jsonl`:

```json
{"montadora": {"label": "Chevrolet", "handle": "chevrolet", "logo_url": "https://images.karhub.com.br/assets/montadoras/chevrolet.avif"},
 "modelo": {"label": "Tracker", "handle": "Tracker", "foto_url": "https://images.karhub.com.br/veiculos/chevrolet-tracker.avif"},
 "tipo": "carro", "motivo_tipo": "fipe",
 "anos": [{"ano": 2021, "versoes": [{"label": "4x2 Aut. 1.2 12v L3 Turbo", "handle": "4x2-aut-12-12v-l3-turbo", "ids_fonte": ["62329"]}]}],
 "coletado_em": "2026-10-03"}
```

Retoma pulando os modelos que já estão na árvore e os sem anos. Motos e pesados que coletas de
antes de 2026-10-04 deixaram em `karhub_excluidos.jsonl` (só com versões de exemplo) são
coletados inteiros na rodada seguinte. `--do-inicio` coleta tudo de novo em arquivos novos e só
os troca pelos antigos no fim. Custo: as versões de todos os anos e o conteúdo de cada um dos
cerca de 3.500 modelos; estimativa de 6 a 9 horas.

**`compat`** lê os handles de `catalogos/karhub.jsonl` (caminho da URL, sem a query das
variantes), consulta 50 por chamada e grava `{"handle", "ids", "coletado_em"}` em
`veiculos/karhub_compat.jsonl`. Retoma pelos handles já gravados. Se um lote inteiro voltar
vazio, repete em lotes de 10 para separar "produto sem compatibilidade" de "lote recusado".
Cerca de 3.700 chamadas, de 1 a 2 horas.

Ritmo e falhas como em `catalogo_karhub.py`: uma chamada por vez, pausa de 0,3 s, novas
tentativas com espera crescente (5, 15, 30, 60 s) para erro de conexão, 429 e 5xx; HTTP 403/430
ou captcha contam como bloqueio, com espera quatro vezes maior; esgotadas as tentativas, o
coletor para com código 2 e uma mensagem para rodar de novo mais tarde. Log em `veiculos/*.log`.

## 5. Regras

### 5.1 Tipo do modelo (`helper/veiculo_tipo.py`)

Em ordem; a primeira que decide vale:

1. **Ajuste do dono:** `helper_veiculos_tipo.csv` (`montadora;modelo;tipo`, com tipo `carro`,
   `moto` ou `pesado`).
2. **FIPE:** procura o modelo nas listas da marca correspondente (nome da marca casado pelas
   mesmas regras da seção 5.2, considerando também as partes de nomes como "GM - Chevrolet" e
   "Caoa Chery/Chery"). Um modelo casa quando algum nome da FIPE, normalizado (maiúsculas, sem
   acento, só letras, números e espaços), é igual ao nome do modelo ou começa com ele seguido de
   espaço. Está em "carros" → `carro` (mesmo que também esteja em "caminhoes", como Marruá e
   Delivery Express). Só em "motos" → `moto`. Só em "caminhoes" → `pesado`.
3. **Versões:** alguma versão com cilindrada em cc → `moto`. Alguma com tração 6x2, 6x4, 8x2 ou
   8x4, ou com fase de emissão P junto de motor de 4.0 ou mais → `pesado`.
4. **Nome:** nome do modelo com `BUS`, `ONIBUS`, `MICRO`, `RODOVIARIO` ou `URBANO` → `pesado`.
5. **Na dúvida:** `carro`.

O motivo (`ajuste`, `fipe`, `versao`, `nome`, `padrao`) vai junto, para o relatório. O tipo
não tira modelo nenhum da árvore: vai para `vei_modelo.tipo`. Um ajuste em
`helper_veiculos_tipo.csv` vale no `helper.py veiculos` seguinte, sem coletar de novo.

### 5.2 Montadora (`helper/montadoras.py`)

- **Nome canônico:** maiúsculas, sem acento, espaços simples; antes, o arquivo editável
  `helper_montadoras.csv` (`apelido;nome`) troca grafias que diferem de verdade, já com a grafia
  da `montadoras` do Wayap: `KIA` → `KIA MOTORS`, `JAC` → `JAC MOTORS`, `ASIA` → `ASIA MOTORS`,
  `MERCEDES BENZ` → `MERCEDES-BENZ`, `GM` → `CHEVROLET`, `VW` → `VOLKSWAGEN`, `BMW BMW` → `BMW`.
- **Comparação:** dois nomes são a mesma montadora quando ficam iguais só com letras e números
  (`MERCEDES BENZ` = `MERCEDES-BENZ`).
- A mesma regra serve para o campo `montadora` das aplicações e para ligar `vei_montadora`
  à `montadoras` do Wayap.

### 5.3 Agrupamento da ligação de nível `versao`

Para uma peça e um modelo:

1. Para cada ano do modelo, compara as versões que a peça atende naquele ano com todas as versões
   que existem naquele ano. Se forem todas, o ano é **completo**.
2. Anos completos seguidos viram linhas com `id_versao` nulo. "Seguidos" conta só os anos que o
   modelo tem: um ano sem versão nenhuma não quebra a faixa.
3. Nos anos que não são completos, cada versão atendida vira linhas com seu `id_versao`, com
   faixas seguidas contadas só nos anos em que aquela versão existe.

Uma linha (`modelo`, versão ou nulo, `i`, `f`) quer dizer: "serve na versão (ou em todas) em
todos os anos entre `i` e `f` em que ela existe". Ids de veículo da compatibilidade que não estão
na árvore (veículos novos desde a última coleta) são ignorados e contados no relatório.

### 5.4 Ligação de nível `modelo`

Das aplicações de todos os sites, só de peças ativas. A montadora casa pela seção 5.2; o modelo é
o prefixo mais longo de `aplicacao.modelo` (em palavras) que é nome de modelo da árvore naquela
montadora. Sem montadora, ou com montadora fora da árvore, só casa se o nome existir em uma única
montadora; caso contrário, vai para o relatório. Um par (peça, modelo) que já tem linha de nível
`versao` não ganha linha de nível `modelo`. Faixas sobrepostas ou adjacentes do mesmo par se
juntam; uma aplicação sem ano vale para qualquer ano e absorve as outras do mesmo par.

## 6. Modelo de dados

Tabelas no `helper.sqlite` e, quando indicado, no Postgres `helper`.

### 6.1 `vei_montadora` (local e Postgres)

| Campo | Conteúdo |
|---|---|
| `id_veiculo_montadora` | inteiro, chave, estável |
| `nome` | canônico (seção 5.2), único |
| `nome_exibicao` | como o KarHub escreve ("Mercedes Benz") |
| `logo` | caminho relativo, `veiculos/montadoras/<id>_<8 primeiros do sha1>.png`, ou nulo |
| `id_montadora` | id na `montadoras` do Wayap quando o nome casa; nulo quando não existe lá. Recalculado a cada publicação, só lendo |
| `qtd_pecas` | peças ativas ligadas a algum modelo da montadora |
| `ativo` | booleano; falso quando a montadora não tem modelo ativo |

Só local: `logo_fonte` (URL de onde veio).

### 6.2 `vei_modelo` (local e Postgres)

| Campo | Conteúdo |
|---|---|
| `id_modelo` | inteiro, chave, estável |
| `id_veiculo_montadora` | referência |
| `nome` | canônico, maiúsculas sem acento, espaços simples (`TRACKER`, `ONIX PLUS`) |
| `nome_exibicao` | como o KarHub escreve (`Tracker`) |
| `tipo` | `carro`, `moto` ou `pesado` (seção 5.1); entra no `hash_conteudo` |
| `foto` | caminho relativo, `veiculos/modelos/<id_modelo>_<8 do sha1>.webp`, ou nulo |
| `foto_herdada` | booleano; verdadeiro quando a foto é de outro modelo (seção 3) |
| `ano_inicio`, `ano_fim` | menor e maior ano com versão |
| `qtd_pecas` | peças ativas ligadas ao modelo, em qualquer nível (para ordenar e esconder modelos vazios) |
| `ativo` | booleano |
| `hash_conteudo` | hash do modelo, das suas versões e dos anos delas, para publicar por diferença |
| `atualizado_em` | data da última mudança |

Chave única: (`id_veiculo_montadora`, `nome`). Só local: `foto_fonte` (URL de onde veio).

### 6.3 `vei_versao` (local e Postgres)

| Campo | Conteúdo |
|---|---|
| `id_versao` | inteiro, chave, estável |
| `id_modelo` | referência |
| `nome` | canônico, maiúsculas sem acento, espaços simples |
| `nome_exibicao` | como o KarHub escreve (`4x2 Aut. 1.2 12v L3 Turbo`) |
| `motor` | cilindrada lida do nome (`1.2`), ou nulo |
| `ativo` | booleano |

Chave única: (`id_modelo`, `nome`).

### 6.4 `vei_versao_ano` (local e Postgres)

(`id_versao`, `ano`), chave composta: em quais anos cada versão existe.

### 6.5 `vei_peca` (local e Postgres)

| Campo | Conteúdo |
|---|---|
| `id_peca` | peça |
| `id_modelo` | modelo |
| `id_versao` | versão, ou **nulo = todas as versões do modelo** nos anos da faixa |
| `ano_inicio`, `ano_fim` | faixa; nulos só no nível `modelo` quando a aplicação não informa ano |
| `nivel` | `versao` (compatibilidade do KarHub) ou `modelo` (texto de aplicação) |

Índices: (`id_modelo`, `ano_inicio`, `ano_fim`) e (`id_peca`). Sem chave estrangeira no
Postgres, para a carga de milhões de linhas ser rápida; a ordem da publicação (peças antes)
garante a integridade.

### 6.6 Tabelas de controle

- `vei_peca_estado` (`id_peca`, `hash`), local e Postgres: hash das linhas de `vei_peca`
  de cada peça, para publicar por diferença comparando com o que está no destino.
- `vei_fonte` (`site`, `id_fonte`, `id_versao`, `ano`), só local: traduz o id do KarHub.
- `vei_arquivo` (`caminho`, `publicado`), só local: fotos e logos gerados e se já foram
  enviados.

## 7. Preparação: `python helper.py veiculos`

Roda depois do `preparar`, porque usa peças, origens e aplicações. Recalcula tudo a partir de
`veiculos/*.jsonl` e do `helper.sqlite`; com as mesmas entradas, gera os mesmos ids e hashes.

1. **Árvore:** lê `veiculos/karhub_arvore.jsonl` e grava montadoras, modelos, versões, anos e
   `vei_fonte`. O que não está no arquivo vira `ativo = 0`.
2. **Imagens:** converte a foto de cada modelo para WebP e o logo de cada montadora para PNG, a
   partir de `veiculos/imagens/`. Antes, procura imagem própria em
   `helper_fotos_veiculos/proprias/modelos/<MONTADORA>-<MODELO>.(png|jpg|webp)` e
   `helper_fotos_veiculos/proprias/montadoras/<MONTADORA>.(png|jpg|webp)` (nome comparado só por
   letras e números), que têm prioridade. Depois, modelos ainda sem foto herdam (seção 3). Saída
   em `helper_fotos_veiculos/modelos/` e `helper_fotos_veiculos/montadoras/`.
3. **Nível `versao`:** para cada peça ativa com origem `karhub`, pega o handle da URL, procura os
   ids em `karhub_compat.jsonl`, traduz pelo `vei_fonte` e agrupa (seção 5.3). O arquivo de
   compatibilidade tem centenas de MB e é lido em fluxo, sem carregar tudo na memória.
4. **Nível `modelo`:** seção 5.4.
5. **Fechamento:** `qtd_pecas`, hashes, `vei_peca_estado`, relatório
   `helper_relatorios/<data>-veiculos.md` e a planilha `helper_relatorios/<data>-veiculos-tipos.csv`
   com o tipo de todos os modelos e o motivo, para o dono revisar e copiar correções para
   `helper_veiculos_tipo.csv`. Grava em `meta` a hora em que rodou.

Comando de conferência, para comparar com o site:

```
python helper.py pecas-do-veiculo CHEVROLET TRACKER 2021 [--versao "4x2 Aut. 1.2 12v L3 Turbo"] [--texto TAMBOR]
```

Ele imprime as peças com a confiança, usando a mesma regra da consulta do contrato (seção 9),
implementada também no SQLite em `helper/consulta.py`, como as consultas que já existem.

Rotina completa: `preparar` → `veiculos` → `fotos` → `publicar`. O `preparar` passa a gravar em
`meta` a hora em que rodou, e o `publicar` se recusa a começar se o `veiculos` for mais antigo que
o último `preparar` (uma fusão de peças pode ter mudado ids), pedindo para rodar `helper.py
veiculos`. Sem nenhum `veiculos` rodado, o `publicar` publica só as peças, como hoje.

## 8. Publicação (dentro do `publicar` que já existe)

Depois das peças, porque `vei_peca` aponta para `peca`. Arquivos antes das linhas do banco.

1. **Ligação com o Wayap:** se a tabela `montadoras` existir no banco, lê `id_montadora` e
   `descricao` e casa pela seção 5.2. Só leitura.
2. **Arquivos:** `rsync` de `helper_fotos_veiculos/` para `/home/wayap/helper/veiculos/`, sem a
   pasta `proprias/`, com as mesmas opções de hoje (sem apagar no destino, dono root, 755/644,
   retomável). Só roda se houver arquivo ainda não enviado (`vei_arquivo`).
3. **Montadoras e árvore:** grava as montadoras cujo conteúdo difere do destino e os modelos cujo
   `hash_conteudo` mudou ou que não existem lá: upsert do modelo e das versões (ids estáveis,
   versão nunca é apagada) e troca dos anos das versões daquele modelo. Uma transação.
4. **`vei_peca`:** compara `vei_peca_estado` local com o do destino; para as peças novas
   ou alteradas, apaga as linhas no destino e insere as novas por `COPY`; peça que saiu do local
   perde as linhas. Em lotes de 5 mil peças, com commit por lote: uma queda no meio continua de
   onde parou na rodada seguinte.
5. `--ensaio` mostra as contagens por tabela e os arquivos a enviar, sem gravar nada. Rodar duas
   vezes seguidas grava zero linhas e envia zero arquivos.
6. A linha da `carga` da rodada recebe `modelos_publicados` e `ligacoes_veiculo`.
   `versao_esquema` = 3.

## 9. Contrato com o Wayap: consultas novas

Numeradas depois das quatro da spec do helper. Todas devolvem só montadoras, modelos e versões
ativos e peças ativas, e nunca expõem `origem`, `vei_fonte` nem ids do KarHub. URLs de arquivo:
`'/files/aGVscGVy/' || caminho_relativo`.

5. **`vei_v_montadora`:** `id_veiculo_montadora`, `id_montadora`, `nome`, `nome_exibicao`,
   `logo_url` (o logo da `montadoras` do Wayap quando existe, senão o do helper), `qtd_modelos`,
   `qtd_pecas`, `tipos` (array com os tipos dos modelos ativos, para listar só as montadoras de
   moto, por exemplo: `WHERE 'moto' = ANY(tipos)`).
6. **`vei_v_modelo`:** `id_modelo`, `id_veiculo_montadora`, `nome`, `nome_exibicao`,
   `foto_url` (nula sem foto), `foto_herdada`, `ano_inicio`, `ano_fim`, `qtd_pecas`, `tipo`.
7. **`vei_anos_do_modelo(id_modelo)`:** anos em ordem decrescente.
   **`vei_versoes_do_ano(id_modelo, ano)`:** `id_versao`, `nome_exibicao`, `motor`.
8. **`vei_pecas_por_veiculo(id_modelo, ano, id_versao DEFAULT NULL, texto DEFAULT NULL,
   limite DEFAULT 100)`:** `id_peca`, `id_marca`, `marca`, `codigo`, `ean`, `desc_curta`,
   `desc_completa`, `tipo_peca`, `ncm_sugerido`, `unidade_sugerida`, `tem_foto`, `qtd_fontes`,
   `confianca`. Com `texto`, filtra `desc_curta` como a `busca_texto`.
9. **`vei_ids_por_veiculo(id_modelo, ano, id_versao DEFAULT NULL)`:** `id_peca`, `confianca`, sem
   limite. É para o Wayap cruzar com o estoque do cliente pelo id da peça guardado no produto,
   já que o Postgres não junta tabelas de dois bancos.

Regra da `confianca`, para o modelo M e o ano A escolhidos:

| Situação da peça | Versão escolhida | Sem versão escolhida |
|---|---|---|
| Linha `versao` com `id_versao` nulo cobrindo A | `versao` | `todas_versoes` |
| Linha `versao` com a versão escolhida cobrindo A | `versao` | não se aplica |
| Só linhas `versao` de outras versões cobrindo A | **fica de fora** (o KarHub diz que não serve) | `algumas_versoes` |
| Sem linha `versao` em (M, A), com linha `modelo` cobrindo A | `modelo_ano` | `modelo_ano` |

Ordem: `versao` e `todas_versoes`, depois `algumas_versoes`, depois `modelo_ano`; dentro de cada
grupo, semelhança com o texto (quando há), `tem_foto` e `qtd_fontes`, como nas outras consultas.

## 10. Verificação

- **Testes unitários** (pytest), com respostas no formato real da API do KarHub e da FIPE
  (Chevrolet/Tracker, Volkswagen/Gol, Honda/Biz, Mercedes-Benz/1214 K, Iveco/Daily): coletor
  (carro e moto descendo com o tipo, sem anos registrado, excluído antigo revisitado, retomada,
  lote de compatibilidade vazio, bloqueio);
  tipo (cada regra da seção 5.1 com casos reais); montadora (`MERCEDES BENZ` com
  `MERCEDES-BENZ`, `KIA` com `KIA MOTORS`, nome novo); árvore (ids estáveis ao recarregar,
  ausente vira inativo); imagens (conversão, imagem própria primeiro, herança por prefixo);
  agrupamento (ano completo vira `id_versao` nulo, ano incompleto lista versões, ano sem versão
  não quebra a faixa, id desconhecido contado); nível `modelo` (com montadora, sem montadora e
  único, sem montadora e ambíguo, par já coberto por `versao`); `confianca` da tabela da seção 9
  no SQLite.
- **Publicação:** com conexão falsa, como nos testes atuais: arquivos antes do banco; ensaio não
  grava; segunda publicação grava zero linhas; nenhum comando de escrita na `montadoras`;
  `publicar` recusa `veiculos` mais antigo que `preparar`. Integração real com
  `HELPER_TESTE_PG=1`, como hoje, cobrindo as funções e views da seção 9.
- **Relatório `veiculos.md`:** modelos por tipo e motivo; montadoras
  (ligadas à `montadoras` do Wayap e sem par lá); modelos com foto própria, do KarHub, herdada e
  sem foto, e os 100 modelos com mais peças sem foto (candidatos a foto própria); peças ligadas
  por nível; linhas de `vei_peca`; ids de veículo desconhecidos; as 50 aplicações mais comuns
  que não casaram.
- **Conferência manual:** para três veículos (Tracker 2021 1.2 Turbo, Gol 2010, Palio 2005),
  `pecas-do-veiculo` com `--texto TAMBOR` e `--texto PASTILHA` comparado com a página de categoria
  do KarHub filtrada pelo mesmo veículo. As peças que o KarHub mostra precisam aparecer com
  confiança `versao` ou `todas_versoes`.
- **Antes da primeira carga:** o Francisco revisa a planilha de tipos e o `publicar --ensaio`.

## 11. Operação e volumes

- **Primeira carga:** `fipe`, `arvore` (6 a 9 h), `compat` (1 a 2 h), `helper.py veiculos`,
  revisão da planilha de tipos, `pecas-do-veiculo` nos três veículos, `publicar --ensaio`,
  `publicar`.
- **Rotina:** `arvore --do-inicio` uma vez por mês (sem a opção, ele só completa modelos ainda
  ausentes e não pega anos novos dos que já estão no arquivo); `compat --do-inicio` sempre que o
  `catalogo_karhub.py` for rodado de novo; depois `veiculos` e `publicar`.
- **Volumes:** as 159 montadoras e os cerca de 3.500 modelos do KarHub (na primeira coleta,
  parcial: 47% dos modelos vistos eram carro ou utilitário, 26% moto e 27% pesado). Fotos: cerca de 1 em 4 modelos,
  mais as herdadas, 35 KB cada. Logos: cerca de 20 KB cada. `vei_peca`: estimativa de 5 a 15
  milhões de linhas (cerca de 1 GB com índices), medida pelo relatório; o servidor tem cerca de
  300 GB livres.

## 12. Riscos

- **Dados e imagens são do KarHub.** O nome do site nunca aparece no Wayap; imagens próprias
  substituem as do KarHub sem mexer em código (seção 7, passo 2).
- **O KarHub pode mudar ou fechar a API.** O coletor para com erro claro; os dados já publicados
  continuam valendo; a ligação de nível `modelo` não depende do KarHub.
- **Bloqueio.** Ritmo baixo, uma chamada por vez, tudo retomável.
- **Classificação errada de tipo.** Na dúvida o tipo é carro; a planilha de tipos mostra tudo
  com o motivo; `helper_veiculos_tipo.csv` corrige já no `helper.py veiculos` seguinte.
- **Montadora do helper sem par na `montadoras` do Wayap.** Fica com `id_montadora` nulo; quem
  decide criar do lado do Wayap é o Wayap (seção 13). Grafias diferentes da mesma montadora se
  resolvem em `helper_montadoras.csv`.
- **Ligação errada pelo texto de aplicação.** O nível `modelo` sempre aparece como "confira a
  versão", nunca como confirmado.

## 13. Fases seguintes (Wayap, cada uma com spec própria)

1. **Produto guarda o `id_peca` do helper**, preenchido por uma rotina que casa EAN e código (as
   consultas 1 e 2 do contrato). Sem isso, o estoque do cliente não cruza com a consulta 9.
2. **Tela "Peças para o veículo"**, com o componente do filtro (montadora com logo, modelo com
   foto, ano, versão) feito uma vez e reaproveitado, e as duas listas (estoque e mercado). Quando
   o vendedor escolher uma montadora com `id_montadora` nulo e o Wayap precisar dela (cadastro de
   carro, por exemplo), o próprio Wayap a cria na `montadoras`, como a pesquisa por placa já faz.
3. **Aba "Placa" do filtro:** a pesquisa por placa do Wayap já grava em `placas_detalhes` marca,
   modelo, ano e versão. Casar esse texto com a árvore leva a placa direto à versão.
4. **`carro_cliente` escolhido pela árvore** em vez de texto livre, para a venda ou a OS já
   abrirem o filtro no carro do cliente.
5. **Cadastro de produto** mostrando os veículos da peça do helper.
