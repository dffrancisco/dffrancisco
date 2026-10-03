# Auri Auto Peças → Wayap

Extrai dados completos e fotos de peças de https://www.auriautopecas.com.br usando
[Scrapling](https://github.com/D4Vinci/Scrapling), gerando um `produto.json` por peça
para cadastro no Wayap.

```bash
pip install -r requirements.txt
python auri_scraper.py https://www.auriautopecas.com.br/acessorios/farol-dianteiro-0160123
# várias peças de uma vez:
python auri_scraper.py URL1 URL2 URL3 -o pecas
# todas as peças de uma marca:
python auri_scraper.py --marca Arteb
```

Saída: `pecas/<slug-da-url>/produto.json` + `foto_1.jpg`, `foto_2.jpg`... e
`pecas/produtos.json` com todas as peças num único arquivo (para importação em lote).
A `foto_1` é a principal; as fotos são baixadas na maior resolução disponível no site
(JPEG, ou PNG quando o original é PNG).

A pasta `pecas/` já contém a marca **Arteb** completa: 84 peças, 193 fotos, 717 aplicações.

Campos do JSON: `nome`, `descricao_curta`, `marca`, `codigo_fabricante`, `ean`, `sku`,
`referencia`, `categoria`, `preco`, `moeda`, `disponivel`, `ficha_tecnica` (chave → valor),
`aplicacoes` (montadora, veículo, motor, ano_inicio, ano_fim), `observacoes`
(notas como "MÁSCARA NEGRA", "COM AVARIA"), `descricao_html`, `imagens`, `url_origem`.

## AutoNext

`autonext_scraper.py` faz o mesmo para https://www.autonext.com.br (loja VTEX), lendo a
API pública de catálogo da VTEX em vez do HTML. Gera o mesmo formato de `produto.json`.

```bash
python autonext_scraper.py --marca Arteb            # saída em pecas_autonext/
python autonext_scraper.py https://www.autonext.com.br/<slug-do-produto>/p
```

Diferenças em relação ao Auri:
- Cada anúncio da AutoNext tem variações (lado direito/esquerdo) com EAN, código e fotos
  próprios, então é gerada **uma pasta por SKU**: `pecas_autonext/<slug>-<codigo>/`.
- A mesma peça (mesmo EAN) anunciada em mais de uma página vira um único registro, com as
  aplicações de todos os anúncios.
- Anos não contínuos (ex.: 1991–1993 e 2002–2004) viram aplicações separadas.
- `codigo_fabricante` vem como o site mostra (ex.: `160818`); no Auri a Arteb aparece com
  zero à esquerda (`0160818`).

## Hipervarejo

`hipervarejo_scraper.py` faz o mesmo para https://hipervarejo.com.br (também VTEX; a parte
comum às lojas VTEX fica em `vtex.py`).

```bash
python hipervarejo_scraper.py --marca Arteb         # saída em pecas_hipervarejo/
python hipervarejo_scraper.py https://hipervarejo.com.br/<slug-do-produto>/p
```

O cadastro dessa loja é pouco padronizado, então o scraper aplica algumas regras:
- `codigo_fabricante` vem do RefId do SKU (`0460447_ART` → `0460447`, mesmo formato do Auri).
  Pares (`KT...`) viram `0460361 + 0460362` e ficam **sem EAN**: o EAN cadastrado neles é o de
  uma das peças avulsas.
- EAN: só EAN-13 com dígito verificador válido. Em produto de um SKU, quando o EAN do SKU e o da
  ficha divergem, vale o da ficha (conferido contra a AutoNext); em produto com direito/esquerdo,
  vale o do SKU. EAN repetido nos dois lados é descartado.
- Aplicações: usa o campo "Aplicação" (faixa de anos por veículo) e, na falta dele, os campos
  Nome/Modelo/Ano da ficha. Alguns produtos não têm aplicação nenhuma cadastrada.
- O mesmo código anunciado em várias páginas vira um registro só (chave: código + lado).

## Enviar fotos para o Wayap

`wayap_fotos.py` cruza os produtos de um banco do Wayap com as três pastas acima e sobe as
melhores fotos pela API do Wayap (mesmo endpoint da tela de fotos do produto). As credenciais
vão só em variáveis de ambiente:

```bash
export WAYAP_URL=https://wayap.com.br/admin2 WAYAP_SOCIEDADE=topcar WAYAP_LOGIN=<cpf> WAYAP_SENHA=<senha>
python wayap_fotos.py planejar            # só leitura: gera fotos_wayap_topcar/plano.csv e revisar.csv
python wayap_fotos.py enviar --limite 3   # piloto
python wayap_fotos.py enviar              # resto (retomável); --repetir-erros tenta de novo as falhas
python wayap_fotos.py desfazer            # apaga do Wayap o que este script enviou
```

- Casamento por EAN (com marca ou número do código confirmando) ou por código + marca + palavra da
  descrição em comum. O que não tem essa confirmação vai para `revisar.csv` e não é enviado.
- Fotos: mínimo 250 px, sem logos/"sem foto", sem repetir as que o produto já tem; no máximo 5 por
  produto, sem apagar nenhuma existente. PNG transparente ganha fundo branco.
- Marcação do que subiu: coluna `status`/`nome_no_wayap` do `plano.csv` e um `wayap_<sociedade>.json`
  em cada pasta de peça cuja foto foi usada.

## Catálogos de outras lojas (só metadados)

Para achar fotos de produtos sem foto, cada loja tem um `catalogo_<loja>.py` que grava
`catalogos/<loja>.jsonl` (nome, marca, código do fabricante, EAN, URLs das fotos, aplicação),
sem baixar imagens:

| Loja | Como | Serve para casar? |
|---|---|---|
| KarHub | API Storefront do Shopify (token público da página) | Sim: código + marca em 100%, EAN em 83% |
| ShopPeças | API GraphQL da Wake (token público da página) | Sim: grupo Universal, EAN e código |
| CarBlue | Wake | ver `catalogos/carblue.log` |
| ClicPeças | API da WS Lojas | Não: a loja não publica EAN nem código do fabricante |
| Fuscão Preto | API VTEX | Não: sem código do fabricante e EANs internos da loja |
| Universal Automotive | API VTEX da loja do fabricante (busca dividida por faixa de preço) | Sim: grupo Universal (Universal/Univel, Micro, Uniflex, Amortex, Unick, Carto), EAN em todos e código no RefId. A "M CARTO" do cadastro é outra marca |
| AZ Acessórios | Wake, por marca (`--marca`, padrão Loma Plast) | Pouco: só 75 das 299 variações Loma Plast trazem o código LHT; o resto é código interno |

```bash
python catalogo_para_pecas.py karhub shoppecas     # casa com os produtos SEM foto e baixa só essas fotos
python wayap_fotos.py planejar --so-sem-foto --saida fotos_wayap_topcar_sites \
    --fontes karhub=pecas_karhub/*/produto.json shoppecas=pecas_shoppecas/*/produto.json
python wayap_fotos.py enviar --saida fotos_wayap_topcar_sites
```

Universal (18 mil produtos, ~10 min):

```bash
python catalogo_universal.py
python catalogo_para_pecas.py universal
python wayap_fotos.py planejar --so-sem-foto --saida fotos_wayap_topcar_universal \
    --fontes universal=pecas_universal/*/produto.json
python wayap_fotos.py enviar --saida fotos_wayap_topcar_universal
```

## Painel (curadoria de fotos e cadastro pelos sites)

```bash
python painel_wayap.py            # http://localhost:8765 (mesmas variáveis WAYAP_*)
```

- **Curadoria de fotos:** escolhe o lote (`fotos_wayap_<sociedade>*`), uma linha por foto enviada com
  descrição, carro, marca, nº fabricante e cód. barras. "Foto certa" tira da lista; "Foto errada" tira
  da lista e apaga a foto no Wayap (a foto é localizada pelo conteúdo, porque apagar renumera as outras).
  Atalhos: C / E / ↑↓.
- **Cadastrar dos sites:** busca por código, EAN ou descrição em todos os catálogos de `catalogos/*.jsonl`
  (KarHub, CarBlue, ShopPeças, Universal, ClicPeças, Fuscão Preto, AZ Acessórios), ou só em um site pelo
  seletor. O índice SQLite fica em `catalogos/catalogos.sqlite`; na abertura do painel só é refeito o site cujo
  `.jsonl` mudou (todos juntos levam ~10 s). Um catálogo novo entra sozinho ao ser gravado nessa pasta.
  O que já existe no cadastro aparece marcado. "Cadastrar" abre o formulário com sugestões tiradas do
  próprio cadastro (marca, carro, fornecedor e unidade mais usados pela marca, NCM pelo tipo de peça); custo e
  venda entram zerados. Os veículos compatíveis vêm da página da KarHub; nos outros sites, da aplicação escrita
  no catálogo ("GOL G2 96 97 98", "Fiat: Palio 01 a 12", "Gol, Parati - 1998 1999"...). ClicPeças, Fuscão
  Preto e quase toda a AZ Acessórios não trazem código do fabricante: o Nº fabricante tem de ser preenchido à
  mão. As fotos escolhidas sobem junto e vão para a curadoria (lote `fotos_wayap_<sociedade>_cadastro`; os
  cadastros antigos da KarHub continuam no lote `fotos_wayap_<sociedade>_karhub`).

## Helper (base de peças do mercado para os clientes do Wayap)

Spec: `docs/superpowers/specs/2026-10-02-helper-design.md`. Junta os catálogos (`catalogos/*.jsonl`) e as peças
raspadas (`pecas_*/**/produto.json`) em **uma linha por peça** (marca + código, com o zero à esquerda preservado),
com EAN, códigos alternativos, aplicações e fotos, e publica no banco Postgres `helper` do Wayap e na pasta
`/home/wayap/helper/store/foto_produto/<id_peca>/<hash>.jpg` (miniatura `<hash>_p.jpg`). O Wayap só lê.

```bash
python helper.py preparar                      # lê tudo, funde, grava helper.sqlite e helper_relatorios/<data>-preparar.md
python helper.py fotos --limite 5000           # baixa/cura fotos pendentes (locais primeiro); --prioridade, --marca, --tipo
python helper.py relatorio                     # situação do banco local
python helper.py cobertura                     # quanto dos produtos da topcar o helper encontra (EAN/código)
python helper.py publicar --ensaio             # o que mudaria no Postgres e nas fotos
python helper.py publicar                      # rsync das fotos (HELPER_SSH), depois o banco, por diferença
```

- Marcas canônicas e apelidos: `helper_marcas.csv` (semeado com as marcas da topcar). Marcas que os sites usam e não
  estão lá saem em `helper_relatorios/<data>-marcas-desconhecidas.csv`; classifique e rode `preparar` de novo (os ids
  das peças não mudam).
- Fotos: `helper_fotos.toml` (sites/hosts de fabricante, tipos prioritários, limite para detectar logo).
- Conflitos de EAN/código entre fontes: `helper_relatorios/<data>-conflitos.csv`.
- Contrato com o Wayap (funções no Postgres `helper`): `busca_codigo(texto)`, `busca_ean(texto)`,
  `busca_texto(texto, limite)`, `busca_tipo(tipo, montadora, modelo, so_com_foto, limite)`; views `v_peca` e
  `v_foto_publicavel` (com a URL pronta). Nenhuma delas expõe `origem`.
- `preparar` relê todas as fontes a cada rodada (cerca de 80 s para 420 mil anúncios); a fusão é global e os ids
  ficam estáveis entre rodadas.
- Rotina: re-raspar catálogo → `preparar` → `fotos --prioridade --limite N` → `publicar --ensaio` → `publicar`.
- Testes: `pip install -r requirements-dev.txt && pytest`.
