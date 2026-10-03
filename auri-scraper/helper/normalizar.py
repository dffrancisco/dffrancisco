"""Normalização dos dados das fontes para o helper.

Regra de ouro: o código do fabricante é TEXTO e o zero à esquerda faz parte dele. Nunca usar
wayap_fotos.n_codigo aqui (ele faz lstrip("0")).
"""
import re

from wayap_fotos import n_ean, sem_acento

CONECTIVOS = {"PARA", "DA", "DE", "DO", "DAS", "DOS", "E", "COM"}
GENERICAS = {"JOGO", "KIT", "PAR", "PARA", "COM", "SEM", "PECA", "PECAS"}
UNIDADE_PELA_PALAVRA = {"JOGO": "JG", "KIT": "KT", "PAR": "PA"}
TAMANHO_DESC_CURTA = 45
TAMANHO_DESC_COMPLETA = 400


def normalizar_codigo(s):
    """Maiúsculas, sem acento, só letras, dígitos e '/'. '+' e ';' viram '/'. Zeros à esquerda ficam."""
    t = sem_acento(s or "").upper()
    t = re.sub(r"[+;]", "/", t)
    t = re.sub(r"[^A-Z0-9/]", "", t)
    t = re.sub(r"/+", "/", t).strip("/")
    return t


def codigos_kit(codigo):
    """'GS2116/GS2118' -> ['GS2116', 'GS2118']; código simples -> []."""
    partes = [p for p in (codigo or "").split("/") if p]
    return partes if len(partes) > 1 else []


def so_zeros_diferem(a, b):
    return a != b and a.lstrip("0") == b.lstrip("0") and bool(a.lstrip("0"))


def normalizar_ean(s):
    return n_ean(s)


def _palavras(texto):
    return sem_acento(texto or "").upper().split()


def desc_curta(nome, marca=None, codigo=None):
    """Padrão da casa: só a primeira parte antes de ' - ', sem marca, sem código, sem conectivos, até 45."""
    base = (nome or "").split(" - ")[0]
    retirar = set(_palavras(marca)) | {normalizar_codigo(codigo)} if (marca or codigo) else set()
    retirar.discard("")
    palavras = []
    for p in _palavras(base):
        p_limpa = re.sub(r"[^A-Z0-9/]", "", p)
        if not p_limpa or p_limpa in CONECTIVOS or p_limpa in retirar or normalizar_codigo(p) in retirar:
            continue
        palavras.append(p_limpa)
    d = " ".join(palavras)
    if len(d) > TAMANHO_DESC_CURTA:
        d = d[:TAMANHO_DESC_CURTA].rsplit(" ", 1)[0]
    return d.strip()


def desc_completa(nome):
    return " ".join((nome or "").split())[:TAMANHO_DESC_COMPLETA]


def tipo_peca(desc):
    ps = [p for p in re.findall(r"[A-Z]{3,}", sem_acento(desc or "").upper()) if p not in GENERICAS | CONECTIVOS]
    return " ".join(ps[:2])


def unidade_sugerida(desc, moda_marca=None):
    primeira = (desc or "").split(" ")[0]
    return UNIDADE_PELA_PALAVRA.get(primeira) or moda_marca or "PC"
