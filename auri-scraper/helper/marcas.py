"""Marca canônica do helper e apelidos usados pelos sites (helper_marcas.csv, editável)."""
import csv
from collections import Counter
from pathlib import Path

from wayap_fotos import marcas_compativeis, n_marca, sem_acento

TIPOS = {"reposicao", "montadora", "desconhecida"}


def nome_canonico(nome):
    return " ".join(sem_acento(nome or "").upper().split())


class Marcas:
    def __init__(self):
        self.por_chave = {}  # n_marca(nome ou apelido) -> (nome canônico, tipo)
        self.desconhecidas = Counter()

    @classmethod
    def carregar(cls, caminho):
        m = cls()
        with Path(caminho).open(encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f, delimiter=";"):
                nome, tipo = nome_canonico(linha["nome"]), (linha.get("tipo") or "reposicao").strip()
                if tipo not in TIPOS:
                    raise ValueError(f"helper_marcas.csv: tipo '{tipo}' inválido na marca {nome}")
                for apelido in [nome] + [a for a in (linha.get("apelidos") or "").split("|") if a.strip()]:
                    m.por_chave.setdefault(n_marca(apelido), (nome, tipo))
        return m

    def canonica(self, nome):
        chave = n_marca(nome)
        if not chave:
            return "", "desconhecida"
        if chave in self.por_chave:
            return self.por_chave[chave]
        canon = nome_canonico(nome)
        self.desconhecidas[canon] += 1
        return canon, "desconhecida"

    def compativeis(self, a, b):
        ca, cb = self.canonica(a)[0], self.canonica(b)[0]
        return bool(ca and cb) and (ca == cb or marcas_compativeis(n_marca(ca), n_marca(cb)))

    def salvar_desconhecidas(self, caminho):
        with Path(caminho).open("w", encoding="utf-8", newline="") as f:
            f.write("marca;ocorrencias\n")
            for nome, n in self.desconhecidas.most_common():
                f.write(f"{nome};{n}\n")
