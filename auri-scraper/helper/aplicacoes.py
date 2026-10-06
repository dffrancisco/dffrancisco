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


def _linha(montadora, modelo, ano_inicio, ano_fim, motor, observacao, texto_original, vocab, de_karhub):
    canonico, reconhecido = casar_modelo(modelo, vocab)
    return {"montadora": sem_acento(montadora).upper() if montadora else None, "modelo": canonico,
            "ano_inicio": ano_inicio, "ano_fim": ano_fim, "motor": motor, "observacao": observacao,
            "texto_original": texto_original, "modelo_reconhecido": reconhecido, "de_karhub": de_karhub}


def aplicacoes_do_anuncio(anuncio, vocab):
    observacao = "; ".join(anuncio.get("observacoes") or []) or None
    de_karhub = anuncio.get("site") == "karhub"  # a compatibilidade do KarHub é conferida contra o texto dos outros sites
    linhas = []
    for ap in anuncio.get("aplicacoes") or []:  # estruturadas (produto.json) têm prioridade
        texto = " ".join(str(x) for x in (ap.get("montadora"), ap.get("veiculo"), ap.get("motor")) if x)
        inicio, fim = ap.get("ano_inicio"), ap.get("ano_fim")
        if (inicio is None) != (fim is None) and "APOS" not in sem_acento(ap.get("veiculo") or "").upper():
            inicio = fim = inicio if inicio is not None else fim  # 'ECOSPORT 2003' sem 'após': só o ano citado
        anos = f"{inicio or ''}-{fim or ''}".strip("-")
        linhas.append(_linha(ap.get("montadora"), ap.get("veiculo") or "", inicio, fim,
                             _motor(ap.get("motor")), observacao, (texto + " " + anos).strip(), vocab, de_karhub))
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
                    linhas.append(_linha(montadora, modelo, inicio, fim, motor, observacao, trecho, vocab, de_karhub))
    return juntar_aplicacoes(linhas)


def juntar_aplicacoes(linhas):
    """Mesmo modelo/motor: une faixas de anos sobrepostas ou adjacentes (1996-1998 + 1999-2001).
    A montadora não entra na chave porque muitas fontes a omitem ('GOL 96 97 98'); fica a primeira informada.
    Sem ano só se une a sem ano: não engole a faixa datada ('Gol G3' + 'GOL 2000-2005')."""
    grupos = {}
    for l in linhas:
        grupos.setdefault((l["modelo"], l["motor"]), []).append(l)
    saida = []
    for faixas in grupos.values():
        faixas.sort(key=lambda l: (not _sem_ano(l), l["ano_inicio"] is not None, l["ano_inicio"] or 0))
        atual = None
        for l in faixas:
            if atual and _adjacentes(atual, l):
                atual["ano_inicio"] = None if None in (atual["ano_inicio"], l["ano_inicio"]) else min(atual["ano_inicio"], l["ano_inicio"])
                atual["ano_fim"] = None if None in (atual["ano_fim"], l["ano_fim"]) else max(atual["ano_fim"], l["ano_fim"])
                atual["montadora"] = atual["montadora"] or l["montadora"]
                atual["modelo_reconhecido"] = atual["modelo_reconhecido"] or l["modelo_reconhecido"]
                atual["de_karhub"] = atual.get("de_karhub", False) and l.get("de_karhub", False)
                continue
            atual = dict(l)
            saida.append(atual)
    return saida


def _sem_ano(l):
    return l["ano_inicio"] is None and l["ano_fim"] is None


def _adjacentes(a, b):
    if _sem_ano(a) or _sem_ano(b):
        return _sem_ano(a) and _sem_ano(b)  # sem ano com sem ano é a mesma aplicação genérica
    fim_a, inicio_b = a["ano_fim"], b["ano_inicio"]
    if fim_a is None or inicio_b is None:
        return True  # faixa aberta cobre a outra
    return inicio_b <= fim_a + 1
