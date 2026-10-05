#!/usr/bin/env python3
"""Catálogo (só metadados, sem baixar fotos) da Iguaçu Componentes Automotivos, pela busca do site do fabricante.

Uso: python catalogo_iguacu.py   ->  catalogos/iguacu.jsonl (progresso em catalogos/iguacu.log)

A busca (www.iguacu.ind.br/busca) é um formulário ASP.NET (POST) que devolve uma linha por aplicação:
montadora, referência original, código Iguaçu, veículo, motor, combustível, observação e ano. Não há
página por produto, nome nem EAN. Cada família de código ("201." sensor do líquido de arrefecimento,
"401." válvula termostática...) sai de uma busca só, com todas as aplicações dos seus códigos.

O site escreve "201.0831" e "301.0425-92/97"; o código sai como o cliente escreve e como o próprio site
nomeia a foto: só letras e dígitos ("2010831", "30104259297"; a barra viraria kit no helper). As lojas
(Auri, Altese) anunciam pelo código antigo "IG" ("IG806" = 201.0806), que o site não mostra.
O nome vem da família; a aplicação junta os anos do mesmo veículo e motor. A foto (600x600, arte com logo)
tem o endereço montado pelo código e é conferida uma a uma (HEAD).
"""
import json
import logging
import re
import socket
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
import urllib3.util.connection
from lxml import html as lhtml

# esta rede não tem rota IPv6: igual ao helper/fotos.py
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

BASE = "https://www.iguacu.ind.br/"
BUSCA = BASE + "busca"
SAIDA = Path("catalogos/iguacu.jsonl")
INTERVALO = 0.6        # no máximo ~2 requisições por segundo
ESPERAS = (5, 15, 30, 60)  # backoff em timeout, erro de conexão e 5xx
CODIGO_RE = re.compile(r"\d{3}\.\d{4}\S*")  # 201.0831, 301.0425-92/97
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
# famílias do menu "Produtos" do site, no singular
FAMILIAS = {
    "201": "Sensor de Temperatura do Líquido de Arrefecimento", "202": "Sensor de Temperatura do Ar",
    "203": "Sensor de Temperatura do Painel", "204": "Sensor de Temperatura para Partida a Frio",
    "205": "Sensor de Temperatura Externo", "206": "Sensor de Temperatura do Ar-Condicionado",
    "207": "Sensor de Temperatura do Óleo do Motor", "208": "Sensor de Temperatura dos Gases de Escape",
    "209": "Sensor de Temperatura do Câmbio", "210": "Sensor de Nível do Líquido de Arrefecimento",
    "211": "Sensor TPMS", "212": "Sensor de Distância",
    "301": "Termo-Interruptor do Radiador", "302": "Termo-Interruptor para Sinalizador de Advertência",
    "303": "Termo-Interruptor Duplex",
    "401": "Válvula Termostática", "402": "Válvula Termostática com Carcaça",
    "501": "Injetor de Combustível", "502": "Injetor de Combustível", "503": "Injetor de Combustível",
    "504": "Injetor de Combustível", "505": "Injetor de Combustível",
    "601": "Combinado de Válvula Termostática", "602": "Combinado para Arrefecimento",
    "701": "Bomba d'Água Elétrica"}
MONTADORAS = {"GM": "CHEVROLET", "CITRÖEN": "CITROEN", "HON": "HONDA", "YAM": "YAMAHA", "SUZ": "SUZUKI"}
SEM_VALOR = {"", "-", "--", "---"}
COLUNAS = ("montadora", "referencia", "codigo", "veiculo", "motor", "combustivel", "obs", "ano")

log = logging.getLogger("catalogo_iguacu")
_sessao = None
_form = None
_ultimo = 0.0


def _pedir(metodo, url, dados=None):
    """Timeout, recusa e 5xx são passageiros; 4xx não."""
    global _sessao, _ultimo
    if _sessao is None:
        _sessao = requests.Session()
        _sessao.headers["User-Agent"] = USER_AGENT
    for espera in ESPERAS + (None,):
        falta = _ultimo + INTERVALO - time.monotonic()
        if falta > 0:
            time.sleep(falta)
        _ultimo = time.monotonic()
        try:
            r = _sessao.request(metodo, url, data=dados, timeout=120, allow_redirects=metodo != "HEAD")
            if r.status_code < 500:
                return r
            erro = f"HTTP {r.status_code} em {url}"
        except (requests.ConnectionError, requests.Timeout) as e:
            erro = f"{e} em {url}"
        if espera is None:
            break
        log.info("AVISO %s; nova tentativa em %ss", erro, espera)
        time.sleep(espera)
    raise RuntimeError(erro)


def campos(texto):
    """Campos escondidos do formulário (__VIEWSTATE, __EVENTVALIDATION...), que o POST precisa devolver."""
    return {i.get("name"): i.get("value") or "" for i in lhtml.fromstring(texto).xpath('//form[@id="form1"]//input[@type="hidden"]')}


def linhas(texto):
    """Linhas da tabela de resultado: uma por aplicação, com a foto do código."""
    resultado = []
    for tr in lhtml.fromstring(texto).xpath('//*[@id="GridReferencia"]//tr[td]'):
        celulas = [" ".join(td.text_content().split()) for td in tr.xpath("./td")]
        if len(celulas) < 9:
            continue
        linha = dict(zip(COLUNAS, celulas[1:9]))
        linha["foto"] = (tr.xpath(".//img/@src") or [""])[0]
        resultado.append(linha)
    return resultado


def _pagina_da_busca(metodo, dados=None):
    r = _pedir(metodo, BUSCA, dados)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} em {BUSCA}")
    return r.text


def buscar(termo):
    """Linhas da busca por 'termo'. O POST devolve o formulário com o viewstate da próxima busca; se ele for
    recusado, a busca é refeita com um formulário novo."""
    global _form
    for novo in (False, True):
        if novo or _form is None:
            _form = campos(_pagina_da_busca("GET"))
        dados = dict(_form, TxtPesquisaCatalogo=termo, TxtPesquisaVeiculo="", chks="RB_Iguacu",
                     BtnPesquisa="Pesquisar", ddlCategoria="-1", ddlMontadora="-1", ddlVeiculos="-1")
        try:
            texto = _pagina_da_busca("POST", dados)
        except RuntimeError:
            if novo:
                raise
            continue
        _form = campos(texto)
        return linhas(texto)


def descobrir(buscar=buscar):
    """Códigos do site. A busca não é um "contém" confiável: cada termo traz só uma parte dos códigos ("207."
    não acha 207.2201; "201.0826" só aparece buscando "2010"). Então junta as buscas de cada dígito, de cada
    família ("201.") e de cada família com o primeiro dígito do número ("2010")."""
    codigos = set()

    def juntar(termo):
        codigos.update(l["codigo"] for l in buscar(termo) if CODIGO_RE.fullmatch(l["codigo"]))
    for digito in "0123456789":
        juntar(digito)
    for familia in sorted(set(FAMILIAS) | {c[:3] for c in codigos}):
        juntar(f"{familia}.")
    for inicio in sorted({c[:3] + c[4] for c in codigos}):
        juntar(inicio)
    return codigos


def aplicacoes_do_codigo(codigo):
    """A busca pelo código exato traz todas as aplicações dele (as buscas da descoberta podem trazer só parte)."""
    return [l for l in buscar(codigo) if l["codigo"] == codigo]


def foto_existe(url):
    r = _pedir("HEAD", url)
    return r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/")


def _ano4(aa):
    return int(aa) + (1900 if int(aa) >= 30 else 2000)  # mesmo corte do aplicacao_texto.ler_anos


def anos(texto):
    """'07-15' e '01 02' -> (2007, 2015); '08->' e '02 >' -> (2008, None); '>-86' -> (None, 1986);
    '---', '>->' e vazio -> None (sem ano)."""
    t = (texto or "").strip()
    if m := re.fullmatch(r"(\d{2})\s*[- ]\s*(\d{2})", t):
        return _ano4(m[1]), _ano4(m[2])
    if m := re.fullmatch(r"(\d{2})\s*-?\s*>", t):
        return _ano4(m[1]), None
    if m := re.fullmatch(r">\s*-\s*(\d{2})", t):
        return None, _ano4(m[1])
    return None


def _juntar(intervalos):
    """Uma ponta em aberto (None) em qualquer linha deixa a ponta do grupo em aberto."""
    inicios, fins = [i[0] for i in intervalos], [i[1] for i in intervalos]
    return (None if None in inicios else min(inicios)), (None if None in fins else max(fins))


def _texto_anos(intervalo):
    if not intervalo or intervalo == (None, None):
        return ""
    de, ate = intervalo
    if de is None:
        return f"Até {ate}"
    if ate is None:
        return f"Após {de}"
    return str(de) if de == ate else f"{de}-{ate}"


def veiculos(aplicacoes):
    """Linhas do site -> 'FIAT PALIO 1996-2002 1.0 8V; AUDI A3 Após 2002 1.6 8V'. Linhas do mesmo veículo e
    motor (variam combustível e observação) viram uma, com os anos juntos."""
    grupos = {}
    for l in aplicacoes:
        montadora = MONTADORAS.get(l["montadora"], l["montadora"])
        motor = "" if l["motor"] in SEM_VALOR else " ".join(l["motor"].replace(" - ", " ").split())
        chave = (montadora, l["veiculo"], motor)
        grupos.setdefault(chave, [])
        if intervalo := anos(l["ano"]):
            grupos[chave].append(intervalo)
    partes = [" ".join(filter(None, (montadora, veiculo, _texto_anos(_juntar(ints) if ints else None), motor)))
              for (montadora, veiculo, motor), ints in grupos.items()]
    return "; ".join(dict.fromkeys(p for p in partes if p)) or None


def registros(aplicacoes):
    """Um registro por código Iguaçu, na ordem em que aparecem; a linha sem código (o site às vezes manda uma
    vazia) fica de fora."""
    por_codigo = {}
    for l in aplicacoes:
        if l["codigo"]:
            por_codigo.setdefault(l["codigo"], []).append(l)
    for cod, apls in por_codigo.items():
        familia = FAMILIAS.get(cod.split(".")[0], "Componente Automotivo")
        fotos = [urljoin(BASE, l["foto"]) for l in apls if l["foto"]]
        yield {"site": "iguacu", "url": f"{BUSCA}#{cod}", "nome": f"{familia} - Iguaçu {cod}", "marca": "IGUACU",
               "codigo_fabricante": re.sub(r"[^0-9A-Za-z]", "", cod).upper(), "ean": None,
               "carro": veiculos(apls), "imagens": list(dict.fromkeys(fotos))[:1]}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(SAIDA.with_suffix(".log"), encoding="utf-8")])
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    inicio, aplicacoes = time.time(), []
    codigos = sorted(descobrir())
    log.info("%s códigos descobertos em %s famílias: %s", len(codigos), len({c[:3] for c in codigos}),
             ", ".join(f"{f} {FAMILIAS.get(f, 'FORA DO MENU')}" for f in sorted({c[:3] for c in codigos})))
    for n, codigo in enumerate(codigos, 1):
        apls = aplicacoes_do_codigo(codigo)
        if not apls:
            log.info("AVISO %s não voltou na busca pelo código", codigo)
        aplicacoes += apls
        if n % 50 == 0:
            log.info("aplicações: %s de %s códigos, %s linhas, %.0f min", n, len(codigos), len(aplicacoes),
                     (time.time() - inicio) / 60)
    regs = list(registros(aplicacoes))
    sem_foto = []
    for n, r in enumerate(regs, 1):
        if r["imagens"] and not foto_existe(r["imagens"][0]):
            sem_foto.append(r["codigo_fabricante"])
            r["imagens"] = []
        if n % 100 == 0:
            log.info("fotos conferidas: %s de %s (%s faltando)", n, len(regs), len(sem_foto))
    if sem_foto:
        log.info("códigos sem foto no site: %s", " ".join(sem_foto))
    SAIDA.parent.mkdir(exist_ok=True)
    with SAIDA.open("w", encoding="utf-8") as f:
        for r in regs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.info("fim: %s códigos (%s com foto, %s com aplicação) de %s aplicações em %.0f min -> %s", len(regs),
             sum(bool(r["imagens"]) for r in regs), sum(bool(r["carro"]) for r in regs), len(aplicacoes),
             (time.time() - inicio) / 60, SAIDA)


if __name__ == "__main__":
    main()
