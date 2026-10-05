"""Lista de peças de um cliente (planilha do ERP dele) casada com o helper: por EAN, depois pelo código do catálogo.

Os ajustes de grafia daqui (prefixo que o cliente põe no código, barra, sufixo) valem só para casar a lista;
o dado do helper fica como o fabricante imprime.
"""
import re
from dataclasses import dataclass, field

import openpyxl

from helper.consulta import por_codigo, por_ean
from helper.marcas import nome_canonico
from helper.normalizar import normalizar_codigo
from wayap_fotos import n_ean, n_marca

# marca genérica não diz o fabricante: só casa por EAN
GENERICAS = {n_marca(m) for m in ("IMPORTADO", "ORIGINAL SI", "ORIGINAL", "USO E CONSUMO", "DIVERSOS", "INATIVOS", "DESATIVADO")}
INATIVAS = {n_marca(m) for m in ("INATIVOS", "DESATIVADO")}
# n_marca(marca canônica) -> (prefixo que o cliente põe no código, sufixo que o cliente põe no código)
AJUSTES = {"DS": ("DS", ""), "VP": ("VP", ""), "MAXAUTO": ("MAX", ""), "RAINHADASSETE": ("ETE", ""), "TECFIL": ("", "B")}
COLUNAS = {"cod": "Código", "catalogo": "Catálogo", "adicionais": "Códigos Adicionais", "ean": "Cód Barra", "marca": "Marca",
           "nome": "Nome", "grupo": "Grupo", "ativo": "Ativo"}


@dataclass
class Item:
    cod: str
    ean: str | None
    codigos: list = field(default_factory=list)
    marca: str = ""
    catalogo: str = ""
    nome: str = ""
    grupo: str = ""
    ativo: bool = True


def ean_do_cliente(texto):
    """EAN válido e que não seja número interno da loja (prefixo 2, zeros na frente ou 7000000 + código)."""
    e = n_ean(texto)
    if not e or e.startswith(("2", "0000", "7000000")):
        return None
    return e


def codigos_do_campo(texto):
    """'SP08 / 0242235661 / SP22 { }' -> ['SP08', '0242235661', 'SP22']. Barra sem espaço (PD/1494) é do código."""
    codigos = []
    for parte in re.split(r"\s+/\s+|\|", (texto or "").replace("{", " ").replace("}", " ").replace("*", " ")):
        c = normalizar_codigo(parte)
        if c and c not in codigos:
            codigos.append(c)
    return codigos


def _celula(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def ler_planilha(caminho, colunas=COLUNAS):
    ws = openpyxl.load_workbook(caminho, read_only=True).worksheets[0]
    linhas = ws.iter_rows(values_only=True)
    cabecalho = {_celula(n): i for i, n in enumerate(next(linhas))}
    itens = []
    for linha in linhas:
        valor = {k: _celula(linha[cabecalho[nome]]) if nome in cabecalho else "" for k, nome in colunas.items()}
        if not any(valor.values()):
            continue
        ativo = valor["ativo"] in ("", "S") and valor["grupo"] != "INATIVOS" and n_marca(valor["marca"]) not in INATIVAS
        # adicionais: códigos da própria marca (Bosch SP11 = F000KE0P11) e equivalências de outras, barradas pela marca
        codigos = codigos_do_campo(valor["catalogo"])
        codigos += [c for c in codigos_do_campo(valor["adicionais"]) if c not in codigos]
        itens.append(Item(cod=valor["cod"], ean=valor["ean"] or None, codigos=codigos,
                          marca=valor["marca"], catalogo=valor["catalogo"], nome=valor["nome"], grupo=valor["grupo"],
                          ativo=ativo))
    return itens


class Casador:
    def __init__(self, db, marcas):
        self.db, self.marcas = db, marcas
        self._marca_da_peca = {}
        self.sem_barra = {}  # código com barra sem a barra -> ids ('PD/1494' casa com 'PD1494')
        for id_peca, valor in db.execute("""SELECT id_peca, codigo FROM peca WHERE status='ativa' AND codigo LIKE '%/%'
                                            UNION SELECT a.id_peca, a.valor FROM codigo_alternativo a JOIN peca p USING (id_peca)
                                            WHERE p.status='ativa' AND a.valor LIKE '%/%'"""):
            self.sem_barra.setdefault(valor.replace("/", ""), set()).add(id_peca)

    def marca_da_peca(self, id_peca):
        if id_peca not in self._marca_da_peca:
            self._marca_da_peca[id_peca] = self.db.execute(
                "SELECT m.nome FROM peca p JOIN marca m USING (id_marca) WHERE id_peca=?", (id_peca,)).fetchone()[0]
        return self._marca_da_peca[id_peca]

    def compativel(self, marca_cliente, id_peca):
        """Mesma marca, apelido, ou mesma primeira palavra (VP x VP VIRTUAL PLASTIC); só usada junto com código igual."""
        outra = self.marca_da_peca(id_peca)
        if self.marcas.compativeis(marca_cliente, outra):
            return True
        a, b = nome_canonico(marca_cliente).split(), nome_canonico(outra).split()
        return bool(a and b) and len(a[0]) >= 2 and n_marca(a[0]) == n_marca(b[0])

    def candidatos(self, codigo, marca_cliente):
        prefixo, sufixo = AJUSTES.get(n_marca(self.marcas.canonica(marca_cliente)[0]), ("", ""))
        lista = [codigo]
        if prefixo and codigo.startswith(prefixo) and len(codigo) > len(prefixo):
            lista.append(codigo[len(prefixo):])
        if sufixo and codigo.endswith(sufixo) and len(codigo) > len(sufixo):
            lista.append(codigo[:-len(sufixo)])
        return lista

    def casar(self, item):
        ean = ean_do_cliente(item.ean)
        if ean:
            ids = por_ean(self.db, ean)
            if ids:
                generica = n_marca(item.marca) in GENERICAS
                divergente = not generica and not any(self.compativel(item.marca, i) for i in ids)
                return {"via": "ean", "ids": ids, "marca_divergente": divergente}
        if n_marca(item.marca) and n_marca(item.marca) not in GENERICAS:
            for codigo in item.codigos:
                for c in self.candidatos(codigo, item.marca):
                    ids = set(por_codigo(self.db, c)) | self.sem_barra.get(c.replace("/", ""), set())
                    certos = sorted(i for i in ids if self.compativel(item.marca, i))
                    if certos:
                        return {"via": "codigo", "ids": certos, "marca_divergente": False}
        return {"via": None, "ids": [], "marca_divergente": False}


def situacao_foto(db, ids):
    if not ids:
        return ""
    marcas = ",".join("?" * len(ids))
    if db.execute(f"SELECT 1 FROM peca WHERE id_peca IN ({marcas}) AND tem_foto=1", ids).fetchone():
        return "tem_foto"
    if db.execute(f"SELECT 1 FROM foto_pendente WHERE id_peca IN ({marcas}) AND tentativas < 3", ids).fetchone():
        return "pendente"
    return "sem_fonte_foto"
