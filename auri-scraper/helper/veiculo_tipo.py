"""Tipo do modelo de veículo (carro, moto, pesado) — spec de veículos, seção 5.1.
Ordem: ajuste do dono, FIPE, versões, nome, padrão (carro). Todos os tipos entram na árvore; o tipo vai para o modelo."""
import csv
import re
from pathlib import Path

from wayap_fotos import n_marca, sem_acento

AJUSTES_PADRAO = Path(__file__).resolve().parents[1] / "helper_veiculos_tipo.csv"
TIPOS = {"carro", "moto", "pesado"}
CC_RE = re.compile(r"\b\d{2,4}\s?cc\b", re.I)          # moto: "Ks 100cc"
EIXOS_RE = re.compile(r"\b[68]x[24]\b", re.I)            # caminhão/ônibus: 6x2, 6x4, 8x2, 8x4
FASE_P_RE = re.compile(r"\bP\s?\d\b")                     # fase Proconve de pesados ("E 1 P 3"); "4p" (portas) não casa
CILINDRADA_RE = re.compile(r"\b(\d{1,2})[.,](\d)\b")
NOME_PESADO = {"BUS", "ONIBUS", "MICRO", "RODOVIARIO", "URBANO"}


def normalizar(texto):
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", sem_acento(texto or "").upper()).split())


def carregar_ajustes(caminho=AJUSTES_PADRAO):
    caminho = Path(caminho)
    if not caminho.exists():
        return {}
    ajustes = {}
    with caminho.open(encoding="utf-8", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            tipo = (linha.get("tipo") or "").strip().lower()
            if tipo not in TIPOS:
                raise ValueError(f"helper_veiculos_tipo.csv: tipo '{tipo}' inválido em {linha.get('montadora')} {linha.get('modelo')}"
                                 f" (use carro, moto ou pesado)")
            ajustes[(n_marca(linha["montadora"]), normalizar(linha["modelo"]))] = tipo
    return ajustes


def chaves_marca_fipe(nome):
    """'GM - Chevrolet' -> {'GMCHEVROLET', 'GM', 'CHEVROLET'}; 'Caoa Chery/Chery' -> {..., 'CAOACHERY', 'CHERY'}."""
    partes = [nome] + re.split(r"\s+-\s+|/", nome)
    return {n_marca(p) for p in partes if n_marca(p)}


def indexar_fipe(fipe):
    """fipe: {'carros': {marca: [modelos]}, 'motos': ..., 'caminhoes': ...} -> {chave_marca: {lista: [nomes normalizados]}}."""
    indice = {}
    for lista, marcas in fipe.items():
        for nome_marca, modelos in marcas.items():
            nomes = [normalizar(m) for m in modelos]
            for chave in chaves_marca_fipe(nome_marca):
                indice.setdefault(chave, {}).setdefault(lista, []).extend(nomes)
    return indice


def _cilindrada(versao):
    return max((float(f"{a}.{b}") for a, b in CILINDRADA_RE.findall(versao)), default=0.0)


def ajuste_de(ajustes, chaves_montadora, modelo):
    """Tipo que o dono deu ao modelo em helper_veiculos_tipo.csv, ou None."""
    alvo = normalizar(modelo)
    return next((ajustes[(c, alvo)] for c in chaves_montadora if (c, alvo) in ajustes), None)


def classificar(chaves_montadora, modelo, versoes, indice_fipe, ajustes):
    alvo = normalizar(modelo)
    tipo = ajuste_de(ajustes, chaves_montadora, modelo)
    if tipo:
        return tipo, "ajuste"
    listas = set()
    for chave in chaves_montadora:
        for lista, nomes in indice_fipe.get(chave, {}).items():
            if any(n == alvo or n.startswith(alvo + " ") for n in nomes):
                listas.add(lista)
    if "carros" in listas:
        return "carro", "fipe"
    if listas == {"motos"}:
        return "moto", "fipe"
    if listas:
        return "pesado", "fipe"
    if any(CC_RE.search(v) for v in versoes):
        return "moto", "versao"
    if any(EIXOS_RE.search(v) or (FASE_P_RE.search(v) and _cilindrada(v) >= 4.0) for v in versoes):
        return "pesado", "versao"
    if NOME_PESADO & set(alvo.split()):
        return "pesado", "nome"
    return "carro", "padrao"
