"""Linhas de peca_localizador (consulta 10 do contrato): a busca do Wayap casa cada palavra com ILIKE no texto
de uma aplicação, e o ano digitado tem de cair na faixa dessa mesma aplicação."""
from helper.marcas import nome_canonico


def _texto(*partes):
    return nome_canonico(" ".join(str(p) for p in partes if p))


def linhas_localizador(peca, alternativos, aplicacoes):
    base = [peca["desc_curta"], peca["desc_completa"], peca["marca"], peca["codigo"], *alternativos, peca["ean"], peca["tipo_peca"]]
    if not aplicacoes:
        return [(peca["id_peca"], None, None, _texto(*base))]
    return [(peca["id_peca"], a["ano_inicio"], a["ano_fim"],
             _texto(*base, a["montadora"], a["modelo"], a["motor"], a["observacao"])) for a in aplicacoes]
