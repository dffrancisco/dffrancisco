"""Aplicações (veículos compatíveis) de um anúncio, com modelo no vocabulário canônico."""
import re

from aplicacao_texto import ocorrencias_do_texto
from wayap_fotos import sem_acento


def casar_modelo(modelo, vocab):
    """Prefixo mais longo do modelo que existe no vocabulário ('CORSA SEDAN GL' -> 'CORSA'). vocab: nome -> nome canônico."""
    palavras = sem_acento(modelo or "").upper().split()
    for n in range(len(palavras), 0, -1):
        chave = " ".join(palavras[:n])
        if chave in vocab:
            return vocab[chave], True
    return " ".join(palavras), False


def _motor(texto):
    m = re.search(r"\b\d\.\d\b", texto or "")
    return m[0] if m else None


def _linha(montadora, modelo, ano_inicio, ano_fim, motor, observacao, texto_original, vocab):
    canonico, reconhecido = casar_modelo(modelo, vocab)
    return {"montadora": sem_acento(montadora).upper() if montadora else None, "modelo": canonico,
            "ano_inicio": ano_inicio, "ano_fim": ano_fim, "motor": motor, "observacao": observacao,
            "texto_original": texto_original, "modelo_reconhecido": reconhecido}


def aplicacoes_do_anuncio(anuncio, vocab):
    observacao = "; ".join(anuncio.get("observacoes") or []) or None
    linhas = []
    for ap in anuncio.get("aplicacoes") or []:  # estruturadas (produto.json) têm prioridade
        texto = " ".join(str(x) for x in (ap.get("montadora"), ap.get("veiculo"), ap.get("motor")) if x)
        anos = f"{ap.get('ano_inicio') or ''}-{ap.get('ano_fim') or ''}".strip("-")
        linhas.append(_linha(ap.get("montadora"), ap.get("veiculo") or "", ap.get("ano_inicio"), ap.get("ano_fim"),
                             _motor(ap.get("motor")), observacao, (texto + " " + anos).strip(), vocab))
    if not linhas and anuncio.get("carro"):
        # um trecho por ';'. 'Fiat: Palio 01 a 12' traz a montadora antes dos dois-pontos, que ocorrencias_do_texto descarta
        for trecho in (t.strip() for t in anuncio["carro"].split(";") if t.strip()):
            prefixo = None
            if ":" in trecho:
                prefixo = sem_acento(re.sub(r"\([^)]*\)", "", trecho.split(":", 1)[0])).upper().strip() or None
            for rotulo, modelo, intervalo, motores in ocorrencias_do_texto(trecho):
                montadora = rotulo[:len(rotulo) - len(modelo)].strip() or prefixo
                inicio, fim = intervalo or (None, None)
                for motor in motores or [None]:
                    linhas.append(_linha(montadora, modelo, inicio, fim, motor, observacao, trecho, vocab))
    return juntar_aplicacoes(linhas)


def juntar_aplicacoes(linhas):
    """Mesmo modelo/motor: une faixas de anos sobrepostas ou adjacentes (1996-1998 + 1999-2001).
    A montadora não entra na chave porque muitas fontes a omitem ('GOL 96 97 98'); fica a primeira informada."""
    grupos = {}
    for l in linhas:
        grupos.setdefault((l["modelo"], l["motor"]), []).append(l)
    saida = []
    for faixas in grupos.values():
        faixas.sort(key=lambda l: (l["ano_inicio"] is not None, l["ano_inicio"] or 0))
        atual = None
        for l in faixas:
            if atual and _adjacentes(atual, l):
                atual["ano_inicio"] = None if None in (atual["ano_inicio"], l["ano_inicio"]) else min(atual["ano_inicio"], l["ano_inicio"])
                atual["ano_fim"] = None if None in (atual["ano_fim"], l["ano_fim"]) else max(atual["ano_fim"], l["ano_fim"])
                atual["montadora"] = atual["montadora"] or l["montadora"]
                atual["modelo_reconhecido"] = atual["modelo_reconhecido"] or l["modelo_reconhecido"]
                continue
            atual = dict(l)
            saida.append(atual)
    return saida


def _adjacentes(a, b):
    if a["ano_inicio"] is None and a["ano_fim"] is None or b["ano_inicio"] is None and b["ano_fim"] is None:
        return True  # sem ano: é a mesma aplicação genérica
    fim_a, inicio_b = a["ano_fim"], b["ano_inicio"]
    if fim_a is None or inicio_b is None:
        return True  # faixa aberta cobre a outra
    return inicio_b <= fim_a + 1
