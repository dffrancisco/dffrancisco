#!/usr/bin/env python3
"""Extrai dados e fotos de peças do site Hipervarejo (VTEX) usando Scrapling.

Uso:
    python hipervarejo_scraper.py URL [URL ...] [-o pasta_saida]
    python hipervarejo_scraper.py --marca Arteb

Mesmo formato de saída do autonext_scraper.py: uma pasta por SKU
    <saida>/<slug-do-produto>-<codigo>/produto.json + foto_1.jpg ...

O cadastro da Hipervarejo é menos padronizado que o da AutoNext:
- o código do fabricante vem no RefId do SKU ("0460447_ART", "KT0460361ART" = par);
- as especificações do produto (EAN, lado, número de peça) muitas vezes descrevem só
  uma das variações (direito/esquerdo);
- as aplicações vêm em três formatos diferentes (ver aplicacoes()).
"""
import html
import re

from auri_scraper import clean, separar_montadora
from vtex import aplicacoes_por_faixa, executar, normaliza_montadora

BASE = "https://hipervarejo.com.br"

# Especificações que viram campos próprios do JSON, internas da loja ou sem conteúdo útil
IGNORAR_SPECS = {"Descrição Anymarket", "Nome Anymarket", "Código Fortbras", "Número de peça",
                 "Código do fabricante", "Código de barras (EAN)", "Marca", "Montadora", "Modelo", "Nome",
                 "Ano", "Ano Inicial", "Ano Final", "Versão", "Aplicação", "Tipo de Aplicação",
                 "Cor do Produto", "Observação"}
# Mesma informação com nomes diferentes conforme o anúncio
RENOMEAR_SPECS = {"Prazo garantia": "Prazo de garantia", "Origem do produto": "Origem",
                  "Tensão (V)": "Tensão elétrica"}
# Código Arteb de 7 dígitos, sem pegar pedaço de código de montadora como "5U1941005"
CODIGO_RE = re.compile(r"(?<![\dA-Z])\d{7}(?![\dA-Z])")
# RefId com o código Arteb; um RefId só com dígitos ("0636397") é código interno da loja
REFID_RE = re.compile(r"^(?P<kit>KIT|KT)?(?:VAR)?(?P<codigo>\d{7})_?ART\d?$")
# "S10 2012 até 2018", "Uno Mille - 2005 até 2012", "GOL G2 95 até 2003 (EXCETO GTI)",
# "KOMBI CARAT 1997 até 2002, 2006 até 2010", "HB20 Comfort 1.0 de 2016 a 2019"
ANO = r"(?:19|20)?\d{2}"
FAIXA = rf"{ANO}(?:\s*(?:até|a|-)\s*{ANO})?"
LINHA_APLICACAO_RE = re.compile(
    rf"^(?P<veiculo>.+?)\s*(?:-|\bde)?\s+(?P<anos>{FAIXA}(?:\s*,\s*{FAIXA})*)\.?\s*(?:\((?P<nota>[^)]*)\))?$", re.I)


def texto(valor):
    """HTML de especificação -> texto de uma linha ('<p>0460361<br />0460362</p>' -> '0460361, 0460362')."""
    partes = re.split(r"<br\s*/?>|</?p\b[^>]*>|;", valor or "", flags=re.I)
    partes = [clean(html.unescape(re.sub(r"<[^>]+>", " ", p))) for p in partes]
    return ", ".join(dict.fromkeys(p for p in partes if p))


def spec(produto, nome):
    return texto(", ".join(produto.get(nome) or []))


def ean_valido(ean):
    if not re.fullmatch(r"\d{13}", ean or ""):
        return False
    return sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(ean)) % 10 == 0


def codigo_fabricante(produto, item):
    ref = item["referenceId"][0]["Value"] if item.get("referenceId") else ""
    m = REFID_RE.match(ref)
    if m and m["kit"]:  # par: código das duas peças que vêm no kit
        codigos = list(dict.fromkeys(CODIGO_RE.findall(spec(produto, "Número de peça"))))
        return " + ".join(codigos) if len(codigos) > 1 else f"KIT {m['codigo']}"
    if m:
        return m["codigo"]
    if len(produto["items"]) == 1:  # sem código no RefId: ficha do produto ou nome ("... 0160986_ART Arteb")
        m = CODIGO_RE.search(f"{spec(produto, 'Código do fabricante')} {spec(produto, 'Número de peça')} "
                             f"{produto['productName']}")
        return m[0] if m else None
    return None


def ean(produto, item, codigo):
    if "+" in (codigo or "") or (codigo or "").startswith("KIT"):
        return None  # o par não tem EAN próprio: o cadastrado é o de uma das peças avulsas
    do_item = item.get("ean") if ean_valido(item.get("ean")) else None
    if sum(i.get("ean") == do_item for i in produto["items"]) > 1:
        do_item = None  # mesmo EAN nos dois lados: não dá para saber de qual é
    da_ficha = [e for e in spec(produto, "Código de barras (EAN)").split(", ") if ean_valido(e)]
    da_ficha = da_ficha[0] if len(da_ficha) == 1 else None
    if len(produto["items"]) == 1:
        # Quando os dois divergem, o da ficha é o que bate com o código (conferido com a AutoNext)
        return da_ficha or do_item
    # Com direito/esquerdo, a ficha traz o EAN de só um deles: usa se o número de peça é o deste SKU
    numeros = set(CODIGO_RE.findall(f"{spec(produto, 'Número de peça')} {spec(produto, 'Código do fabricante')}"))
    return do_item or (da_ficha if numeros == {codigo} else None)


def ano(valor):
    a = int(valor)
    return a if a > 100 else a + (1900 if a >= 30 else 2000)  # "95" -> 1995, "03" -> 2003


def aplicacoes_do_html(valor, montadora):
    """Campo 'Aplicação' em HTML: cabeçalhos de montadora + uma linha por veículo."""
    raw = re.sub(r"<br\s*/?>|</?(p|div|li)\b[^>]*>", "\n", valor, flags=re.I)
    linhas = [clean(l) for l in html.unescape(re.sub(r"<[^>]+>", " ", raw)).split("\n")]
    aplicacoes, observacoes = [], []
    for linha in filter(None, linhas):
        m = LINHA_APLICACAO_RE.match(linha)
        if m:
            anos = []
            for inicio, fim in re.findall(rf"({ANO})(?:\s*(?:até|a|-)\s*({ANO}))?", m["anos"], re.I):
                anos += range(ano(inicio), ano(fim or inicio) + 1)
            mont, veiculo = separar_montadora(m["veiculo"].strip(" -"), montadora)
            aplicacoes += aplicacoes_por_faixa(mont, veiculo, anos)
            if m["nota"]:
                observacoes.append(f"{veiculo}: {m['nota'].strip()}")
        elif len(linha.split()) <= 4 and ":" not in linha and not re.search(r"\d", linha):
            montadora = normaliza_montadora(linha)  # "Chevrolet", "VW - VOLKSWAGEN"...
    return aplicacoes, observacoes


def aplicacoes_da_ficha(produto, montadora):
    """Campos Nome (veículo) + Modelo (versões) + Ano Inicial/Final, ou Modelo (veículo) + Ano (lista)."""
    nomes, modelos = produto.get("Nome") or [], produto.get("Modelo") or []
    limites = [int(a) for a in produto.get("Ano Inicial", []) + produto.get("Ano Final", []) if a.isdigit()]
    anos = range(min(limites), max(limites) + 1) if limites else \
        [int(a) for a in produto.get("Ano", []) if a.isdigit()]
    if len(nomes) == 1 and modelos:
        veiculos = [m if m.upper().startswith(nomes[0].upper()) else f"{nomes[0]} {m}" for m in modelos]
    else:  # com vários veículos não dá para saber de qual é cada versão
        veiculos = nomes or modelos
    return [a for v in dict.fromkeys(clean(v) for v in veiculos) for a in aplicacoes_por_faixa(montadora, v, anos)]


def aplicacoes(produto):
    montadoras = list(dict.fromkeys(normaliza_montadora(m) for m in produto.get("Montadora") or []))
    montadora = " / ".join(montadoras) or None
    observacoes = [texto(o) for o in produto.get("Observação") or [] if texto(o)]
    # "Aplicação" também é nome de grupo de especificações; só é o texto quando está em allSpecifications
    if "Aplicação" in produto.get("allSpecifications", []):
        apl, obs = aplicacoes_do_html("\n".join(produto["Aplicação"]), montadora)
        if apl:  # o HTML traz a faixa de anos de cada veículo; a ficha junta tudo
            return apl, observacoes + obs
    return aplicacoes_da_ficha(produto, montadora), observacoes


def ficha_tecnica(produto, item):
    ficha = {}
    for nome in produto.get("allSpecifications", []):
        if nome not in IGNORAR_SPECS and spec(produto, nome):
            ficha.setdefault(RENOMEAR_SPECS.get(nome, nome).upper(), spec(produto, nome).upper())
    for var in item.get("variations", []):  # "Posição" do SKU é o lado: LADO ESQUERDO MOTORISTA
        ficha["LADO"] = ", ".join(item[var]).upper()
    return ficha


def lado(reg):
    """'E', 'D' ou None (par ou sem informação), pelo LADO da ficha ou pelo nome."""
    t = (reg["ficha_tecnica"].get("LADO") or reg["nome"]).upper()
    esquerdo = re.search(r"\b(ESQUERD[OA]|MOTORISTA|LE)\b", t)
    direito = re.search(r"\b(DIREIT[OA]|PASSAGEIRO|LD)\b", t)
    return "E" if esquerdo and not direito else "D" if direito and not esquerdo else None


def chave(reg):
    # O mesmo código aparece em vários anúncios ("0160704_ART", "VAR0160704_ART1"...) e vira um registro só.
    # O lado entra na chave porque há anúncios de direito e esquerdo com o mesmo número de peça na ficha
    return (reg["codigo_fabricante"] or reg["sku"], lado(reg))


def pasta(slug, codigo):
    sufixo = codigo.lower().replace(" + ", "-").replace(" ", "-")
    # muitos slugs já terminam com o código ("...-arteb-0460412")
    return slug if slug.endswith(sufixo) else f"{slug}-{sufixo}"


def registros(produto):
    """Um registro (sem fotos baixadas ainda) por SKU do produto."""
    apl, observacoes = aplicacoes(produto)
    categoria = produto["categories"][0].strip("/") if produto.get("categories") else None
    for item in produto["items"]:
        oferta = item["sellers"][0]["commertialOffer"] if item.get("sellers") else {}
        codigo = codigo_fabricante(produto, item)
        variacao = ", ".join(v for var in item.get("variations", []) for v in item[var])
        yield {
            # o nome do SKU às vezes está trocado (esquerdo chamado de direito); o da variação é confiável
            "nome": f"{produto['productName']} - {variacao}" if len(produto["items"]) > 1 and variacao
                    else produto["productName"],
            "descricao_curta": produto.get("metaTagDescription"),
            "marca": produto.get("brand"),
            "codigo_fabricante": codigo,
            "ean": ean(produto, item, codigo),
            "sku": item["itemId"],
            "referencia": item["referenceId"][0]["Value"] if item.get("referenceId") else None,
            "categoria": categoria,
            "preco": oferta.get("Price") or None,
            "moeda": "BRL",
            "disponivel": bool(oferta.get("IsAvailable") and oferta.get("AvailableQuantity")),
            "ficha_tecnica": ficha_tecnica(produto, item),
            "aplicacoes": list(apl),
            "observacoes": list(observacoes),
            "descricao_html": produto.get("description"),
            "imagens": [img["imageUrl"] for img in item.get("images", [])],
            # o "link" da API aponta para o domínio interno da VTEX (fortbras.vtexcommercestable.com.br)
            "url_origem": f"{BASE}/{produto['linkText']}/p?skuId={item['itemId']}",
            "_pasta": pasta(produto["linkText"], codigo or item["itemId"]),
        }


if __name__ == "__main__":
    executar(__doc__, BASE, registros, chave, "pecas_hipervarejo")
