#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Bosch Reposição Automotiva (am.boschaftermarket.com/br/pt).

Uso: python catalogo_bosch.py --lista helper_listas/soinjecao/pendentes.csv  ->  catalogos/bosch.jsonl
     python catalogo_bosch.py --categorias   ->  o mesmo arquivo, com injeção, ignição, sensores e filtros do site
     (as duas opções podem ir juntas; o log fica em catalogos/bosch.log)

É o catálogo do próprio fabricante, numa API JSON aberta (ps.am.dxtservice.com) que só responde em IPv4.
O número Bosch sai como o mercado escreve: 10 caracteres, sem espaço e com o zero à esquerda ("0280156439",
"F000KE0P11"); o site mostra "0 280 156 439". A busca da lista usa o catálogo mundial (o brasileiro não tem
vários itens que a Bosch ainda vende aqui) e acha também os códigos curtos ("SP11" -> F000KE0P11, "OB1016" ->
0986B01016, "FR78"), conferidos na ficha técnica. As fotos têm 560x400; o site não informa EAN. A aplicação
vem da aba "Uso em veículos", uma consulta por montadora, só das montadoras vendidas no Brasil.
Retoma de onde parou: números que já estão no arquivo não são lidos de novo.
"""
import argparse
import csv
import json
import logging
import re
import socket
import time
from pathlib import Path
from urllib.parse import quote

import requests
import urllib3.util.connection

from wayap_fotos import sem_acento

# o servidor não responde em IPv6 e o requests tentaria ele primeiro
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

BASE_API = "https://ps.am.dxtservice.com/ps/api/pt/br"
URL_PRODUTO = "https://am.boschaftermarket.com/br/pt/pe%C3%A7as/product-search.html?prodKey={}"
CATALOGO_BR = "queryPIM=true&catalogId=AA_WEBSITE_BR&pimCountry=br&pimLanguage=pt_br"
SAIDA = Path("catalogos/bosch.jsonl")
CABECALHOS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36",
              "Referer": "https://am.boschaftermarket.com/", "Accept-Language": "pt-BR"}
INTERVALO = 0.7  # segundos entre requisições: no máximo ~1,5 por segundo
ESPERAS = (5, 15, 30, 60)  # backoff em erro de conexão, 429 e 5xx
POR_PAGINA = 30  # a busca devolve no máximo 30 por página, e para em 999 resultados
FICHAS_POR_CODIGO_CURTO = 5  # resultados da busca cuja ficha é aberta para conferir um código curto
FORMATO_BOSCH = re.compile(r"[0-9F][0-9A-Z]{9}")
NUMERO_NO_NOME = re.compile(r"(?<![A-Z0-9])[0-9F][0-9A-Z]{9}(?![A-Z0-9])")
ROTULO_CODIGO = re.compile(r"Designa|KSN|HKB|IAM")  # "Designação" "FR 78", "Número de busca (KSN)" "Sp 11"...
FOTO_TECNICA = re.compile(r"dimension|circuit|diagram|drawing|360", re.I)  # desenho com medidas, esquema elétrico
# buscas do catálogo brasileiro (cada uma bem abaixo do limite de 999) para --categorias
TERMOS_CATEGORIAS = ["injeção", "injetor", "combustível", "borboleta", "massa de ar", "ignição", "vela", "bobina",
                     "sensor", "lambda", "filtro", "filtrante"]
# montadora do "Uso em veículos" -> nome que os outros catálogos usam no "carro"; as que não estão aqui
# (GAZ, Opel, Holden...) não são vendidas no Brasil e não são consultadas
MONTADORAS = {
    "VW (VOLKSWAGEN)": "Volkswagen", "CHEVROLET": "Chevrolet", "FIAT": "Fiat", "FORD": "Ford", "RENAULT": "Renault",
    "PEUGEOT": "Peugeot", "CITROEN": "Citroen", "TOYOTA": "Toyota", "HONDA": "Honda", "HYUNDAI": "Hyundai",
    "NISSAN": "Nissan", "MITSUBISHI": "Mitsubishi", "JEEP": "Jeep", "KIA": "Kia", "MERCEDES-BENZ": "Mercedes-Benz",
    "AUDI": "Audi", "BMW": "BMW", "MINI (BMW)": "Mini", "MINI": "Mini", "VOLVO": "Volvo", "LAND ROVER": "Land Rover",
    "LAND ROVER GROUP": "Land Rover", "JAGUAR": "Jaguar", "PORSCHE": "Porsche", "SUBARU": "Subaru", "SUZUKI": "Suzuki",
    "CHERY": "Chery", "CAOA CHERY": "Chery", "JAC": "JAC", "JAC MOTORS": "JAC", "LIFAN": "Lifan", "DODGE": "Dodge",
    "CHRYSLER": "Chrysler", "RAM": "RAM", "TROLLER": "Troller", "SSANGYONG": "SsangYong", "MAZDA": "Mazda",
    "LEXUS": "Lexus", "BYD": "BYD", "GWM": "GWM", "GREAT WALL": "GWM", "DAEWOO": "Daewoo", "DAIHATSU": "Daihatsu",
    "ASIA MOTORS": "Asia", "GURGEL": "Gurgel", "LADA": "Lada", "SMART": "Smart", "EFFA": "Effa", "HAFEI": "Hafei",
    "MAHINDRA": "Mahindra", "ISUZU": "Isuzu", "SEAT": "Seat", "ALFA ROMEO": "Alfa Romeo",
    "AGRALE": "Agrale", "IVECO": "Iveco", "SCANIA": "Scania", "MAN": "MAN", "DAF": "DAF", "MARCOPOLO": "Marcopolo",
    "VOLARE": "Volare",
}

log = logging.getLogger("bosch")
_sessao = None
_ultima = 0.0


def api(caminho):
    """GET na API com no máximo uma requisição a cada INTERVALO. Erro de servidor que vem como página HTML com
    status 200 ("An unexpected server error", ficha ou montadora inexistente) vira None sem nova tentativa."""
    global _sessao, _ultima
    if _sessao is None:
        _sessao = requests.Session()
        _sessao.headers.update(CABECALHOS)
    for espera in ESPERAS + (None,):
        pausa = _ultima + INTERVALO - time.monotonic()
        if pausa > 0:
            time.sleep(pausa)
        _ultima = time.monotonic()
        try:
            r = _sessao.get(BASE_API + caminho, timeout=60)
            if r.status_code == 200:
                if "json" not in (r.headers.get("content-type") or ""):
                    return None
                return r.json()
            erro = f"HTTP {r.status_code}"
            if r.status_code < 500 and r.status_code != 429:
                break
        except (requests.ConnectionError, requests.Timeout) as e:
            erro = str(e)
        if espera is None:
            break
        log.warning("%s em %s; nova tentativa em %ss", erro, caminho, espera)
        time.sleep(espera)
    raise RuntimeError(f"{erro} em {caminho}")


def numero(texto):
    """Só letras maiúsculas e dígitos: 'F 000 KE0 P11' -> 'F000KE0P11', 'Sp 11' -> 'SP11'."""
    return re.sub(r"[^A-Z0-9]", "", sem_acento(texto or "").upper())


def termos(catalogo):
    """Campo 'catalogo' da lista -> códigos a buscar: 'SP08 / 0242235661' -> ['SP08', '0242235661'].
    Sai o comentário entre chaves e o pedaço sem dígito ('LARANJA') ou curto demais ('035')."""
    texto = re.sub(r"\{[^}\]]*[}\]]?", " ", catalogo or "")
    saida = [numero(p) for p in re.split(r"[\s/()*,;+]+", texto)]
    return list(dict.fromkeys(t for t in saida if len(t) >= 4 and re.search(r"\d", t)))


def numeros_no_nome(nome):
    """Números Bosch escritos na descrição da lista ('VELA IGN F000KE0P06 (BKUR6ET-10)' -> ['F000KE0P06'])."""
    achados = NUMERO_NO_NOME.findall(sem_acento(nome or "").upper())
    return list(dict.fromkeys(n for n in achados if len(re.findall(r"\d", n)) >= 4))


def confere(termo, detalhe):
    """O termo é o número do produto ou um dos códigos curtos da ficha técnica (Designação, KSN, HKB)."""
    if numero(detalhe.get("productNumber")) == termo:
        return True
    return any(ROTULO_CODIGO.search(linha["columnData"][0]) and numero(linha["columnData"][1]) == termo
               for linha in detalhe.get("specificationTabData") or [] if len(linha.get("columnData") or []) == 2)


def ficha(n, fichas):
    if n not in fichas:
        fichas[n] = api(f"/search-details/{n}?queryPIM=false")
    return fichas[n]


def buscar(termo):
    resposta = api(f"/search/{quote(termo)}?pageNumber=1&pageSize=10&queryPIM=false") or {}
    return [numero(p.get("productNumber")) for p in resposta.get("products") or []]


def achar(termo, fichas):
    """Números Bosch para um termo da lista, com o modo como foram achados. A ficha lida para conferir um código
    curto fica em `fichas` (número -> ficha) para não ser pedida de novo."""
    resultados = buscar(termo)
    if termo in resultados:
        return [(termo, "número")]
    if FORMATO_BOSCH.fullmatch(termo) or not re.search(r"[A-Z]", termo):
        return []  # número que a busca não devolveu, ou só dígitos: a busca trouxe parecidos, não o mesmo
    # código curto: a busca só acha "SP06" escrito como na ficha ("Sp 6"); o zero sai só da busca, não do código
    for variante in dict.fromkeys((termo, re.sub(r"(?<=[A-Z])0+(?=\d)", "", termo))):
        if variante != termo:
            resultados = buscar(variante)
        achados = [(n, "código curto") for n in resultados[:FICHAS_POR_CODIGO_CURTO]
                   if (f := ficha(n, fichas)) and confere(variante, f)]
        if achados:
            return achados
    return []


def achar_item(item, fichas):
    """Todos os códigos do campo 'catalogo' e os números Bosch escritos no nome que ainda não foram buscados
    ('VELA IGN 9240081510' com catalogo 'D9BC', 'PEDAL ACELERADOR 0280755067' com o número da montadora)."""
    achados, buscados = {}, termos(item.get("catalogo"))
    for termo in buscados:
        for n, como in achar(termo, fichas):
            achados.setdefault(n, como)
    for termo in numeros_no_nome(item.get("nome")):
        if termo not in buscados and termo not in achados:
            for n, _ in achar(termo, fichas):
                achados.setdefault(n, "nome")
    return list(achados.items())


def fotos(detalhe):
    """Fotos na ordem do site (pela sequência), sem desenho técnico nem repetidas."""
    imagens = [i for i in detalhe.get("images") or [] if not FOTO_TECNICA.search(i.get("type") or "")
               and (i.get("url") or "").startswith(("https://", "//"))]  # o site descarta url "https:" vazia
    imagens.sort(key=lambda i: (i.get("sequence") or 0) + (0 if i.get("type") == "gallery" else 50))
    return list(dict.fromkeys(("https:" + i["url"]) if i["url"].startswith("//") else i["url"] for i in imagens))


def montadoras_para_ler(resposta):
    """Resposta de /usage-in-vehicles/<número>/makers -> ([(id, nome, números, número para OE)], ignoradas)."""
    lidas, ignoradas = [], []
    for m in (resposta or {}).get("makers") or []:
        nome = MONTADORAS.get(sem_acento(m.get("displayName") or "").upper())
        if not nome:
            ignoradas.append(m.get("displayName"))
            continue
        oe = resposta.get("productNumber") if resposta.get("oeNumbersRelevant") else None
        lidas.append((m["id"], nome, [p["number"] for p in m.get("productNumbers") or []], oe))
    return lidas, ignoradas


def carro(veiculos):
    """[(montadora, veículos da API)] -> 'Fiat Palio 1.0 MPI 8V Flex 2010-2011; ...'. O mesmo tipo em várias
    carrocerias ou séries vira um trecho só, do primeiro ao último ano; produção sem fim vira 'após 2005'."""
    faixas = {}
    for montadora, lista in veiculos:
        for v in lista:
            tipo = " ".join(re.sub(r",|\s-\s", " ", v.get("type") or "").split())  # ',' e ' - ' separam trechos
            if not tipo:
                continue
            periodo = v.get("productionPeriod") or {}
            de = (periodo.get("from") or {}).get("year")
            ate = (periodo.get("to") or {}).get("year")
            chave = (montadora, tipo)
            if chave in faixas:
                de0, ate0 = faixas[chave]
                de = min(a for a in (de, de0) if a) if de or de0 else None
                ate = None if None in (ate, ate0) else max(ate, ate0)
            faixas[chave] = (de, ate)
    partes = []
    for (montadora, tipo), (de, ate) in faixas.items():
        anos = "" if not de else f"após {de}" if not ate else str(de) if de == ate else f"{de}-{ate}"
        partes.append(" ".join(filter(None, (montadora, tipo, anos))))
    return "; ".join(partes) or None


def registro(detalhe, veiculos):
    n = numero(detalhe["productNumber"])
    return {"site": "bosch", "url": URL_PRODUTO.format(n), "nome": " ".join((detalhe.get("name") or "").split()),
            "marca": "BOSCH", "codigo_fabricante": n, "ean": None, "imagens": fotos(detalhe), "carro": carro(veiculos)}


def veiculos_do_produto(n, ignoradas):
    lidas, fora = montadoras_para_ler(api(f"/usage-in-vehicles/{n}/makers"))
    ignoradas.update(fora)
    veiculos = []
    for ident, nome, numeros, oe in lidas:
        caminho = f"/usage-in-vehicles/{','.join(numeros or [n])}/vehicles/{ident}"
        resposta = api(caminho + (f"?productNumberForOe={oe}" if oe else "")) or {}
        veiculos.append((nome, resposta.get("vehicles") or []))
    return veiculos


def ler_produto(n, fichas, ignoradas):
    """Registro do número, ou None se a Bosch não tem ficha ou foto dele (aí nem a aplicação é consultada)."""
    detalhe = ficha(n, fichas)
    if not detalhe or not detalhe.get("productNumber") or not fotos(detalhe):
        return None
    return registro(detalhe, veiculos_do_produto(n, ignoradas))


def itens_da_lista(caminho):
    with open(caminho, encoding="utf-8-sig", newline="") as f:
        return [l for l in csv.DictReader(f, delimiter=";") if (l.get("marca") or "").strip().upper() == "BOSCH"]


def ja_gravados(saida):
    feitos = set()
    if Path(saida).exists():
        for linha in Path(saida).read_text(encoding="utf-8").splitlines():
            try:
                feitos.add(json.loads(linha)["codigo_fabricante"])
            except (json.JSONDecodeError, KeyError):
                continue  # linha cortada de uma execução interrompida
    return feitos


def numeros_das_categorias():
    numeros = {}
    for termo in TERMOS_CATEGORIAS:
        pagina, achados, total = 1, 0, 0
        while True:
            resposta = api(f"/search/{quote(termo)}?pageNumber={pagina}&pageSize={POR_PAGINA}&{CATALOGO_BR}") or {}
            total = resposta.get("foundResults") or 0
            for p in resposta.get("products") or []:
                numeros.setdefault(numero(p.get("productNumber")), termo)
                achados += 1
            if not resposta.get("hasMoreData") or not resposta.get("products"):
                break
            pagina += 1
        if total >= 999:
            log.warning("busca %r parou no limite de 999 resultados", termo)
        log.info("categoria %r: %s produtos (%s no total das buscas)", termo, achados, len(numeros))
    return list(numeros)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lista", type=Path, help="pendentes.csv (cod;ean;catalogo;marca;nome;grupo): busca os itens BOSCH")
    ap.add_argument("--categorias", action="store_true", help="lê injeção, ignição, sensores e filtros do site")
    ap.add_argument("--saida", type=Path, default=SAIDA)
    args = ap.parse_args()
    if not (args.lista or args.categorias):
        ap.error("informe --lista e/ou --categorias")
    args.saida.parent.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(args.saida.with_suffix(".log"), encoding="utf-8")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    gravados, fichas, ignoradas, numeros, da_lista = ja_gravados(args.saida), {}, set(), [], []
    log.info("INICIO %s números já no arquivo", len(gravados))
    if args.lista:
        itens = itens_da_lista(args.lista)
        for i, item in enumerate(itens, 1):
            achados = achar_item(item, fichas)
            log.info("item %s/%s cod=%s catalogo=%r -> %s", i, len(itens), item["cod"], item["catalogo"],
                     ", ".join(f"{n} ({como})" for n, como in achados) or "NAO ACHADO")
            da_lista.append((item, achados))
            numeros += [n for n, _ in achados]
    if args.categorias:
        numeros += numeros_das_categorias()
    novos = [n for n in dict.fromkeys(numeros) if n not in gravados]
    log.info("%s números a ler (%s já estavam no arquivo)", len(novos), len(set(numeros)) - len(novos))
    sem_foto = 0
    with args.saida.open("a", encoding="utf-8") as f:
        for i, n in enumerate(novos, 1):
            r = ler_produto(n, fichas, ignoradas)
            fichas.pop(n, None)
            if r is None:
                sem_foto += 1
                log.info("sem ficha ou sem foto: %s", n)
            else:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                gravados.add(n)
            if i % 50 == 0 or i == len(novos):
                log.info("%s/%s lidos", i, len(novos))
    if da_lista:
        modos = {}
        for _, achados in da_lista:
            if achados:
                modos[achados[0][1]] = modos.get(achados[0][1], 0) + 1
        com_foto = sum(any(n in gravados for n, _ in achados) for _, achados in da_lista)
        log.info("LISTA %s itens BOSCH: %s achados %s, %s com foto no arquivo", len(da_lista),
                 sum(modos.values()), modos, com_foto)
        for item, achados in da_lista:
            if not any(n in gravados for n, _ in achados):
                log.info("%s cod=%s catalogo=%r nome=%r", "SEM FOTO" if achados else "NAO ACHADO", item["cod"],
                         item["catalogo"], item["nome"])
    log.info("FIM %s registros novos, %s sem ficha ou sem foto; montadoras ignoradas: %s", len(novos) - sem_foto,
             sem_foto, ", ".join(sorted(ignoradas)) or "nenhuma")

if __name__ == "__main__":
    main()
