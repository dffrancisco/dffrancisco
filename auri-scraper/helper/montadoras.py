"""Nome canônico de montadora (helper_montadoras.csv, editável) e casamento com a tabela montadoras do Wayap.
Spec de veículos, seção 5.2: dois nomes são a mesma montadora quando ficam iguais só com letras e números."""
import csv
from pathlib import Path

from wayap_fotos import n_marca, sem_acento

ARQUIVO_PADRAO = Path(__file__).resolve().parents[1] / "helper_montadoras.csv"


def nome_canonico(nome):
    return " ".join(sem_acento(nome or "").upper().split())


class Montadoras:
    def __init__(self, apelidos=None):
        self.apelidos = apelidos or {}  # n_marca(apelido) -> nome canônico

    @classmethod
    def carregar(cls, caminho=ARQUIVO_PADRAO):
        apelidos = {}
        with Path(caminho).open(encoding="utf-8", newline="") as f:
            for linha in csv.DictReader(f, delimiter=";"):
                apelidos[n_marca(linha["apelido"])] = nome_canonico(linha["nome"])
        return cls(apelidos)

    def canonica(self, nome):
        """'Mercedes Benz' -> 'MERCEDES-BENZ' (pelo apelido); sem apelido, maiúsculas sem acento; vazio -> None."""
        chave = n_marca(nome)
        if not chave:
            return None
        return self.apelidos.get(chave, nome_canonico(nome))

    def chaves(self, nome):
        """Formas comparáveis do nome como veio e do canônico, para casar com listas de terceiros (FIPE)."""
        return {c for c in (n_marca(nome), n_marca(self.canonica(nome) or "")) if c}


def casar_wayap(nome, montadoras_wayap):
    """montadoras_wayap: [(id_montadora, descricao)] lidos da tabela do Wayap. Só leitura."""
    chave = n_marca(nome)
    if not chave:
        return None
    for id_montadora, descricao in montadoras_wayap:
        if n_marca(descricao) == chave:
            return id_montadora
    return None
