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
