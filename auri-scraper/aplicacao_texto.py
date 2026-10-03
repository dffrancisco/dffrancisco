"""Leitura da aplicação escrita nos catálogos ('GOL G2 96 97 98', 'Fiat: Palio 01 a 12'...).
Compartilhado pelo painel_wayap.py e pelo helper."""
import re

from wayap_fotos import sem_acento

MONTADORAS_TITULO = {"CHEVROLET", "GM", "VOLKSWAGEN", "VW", "FIAT", "FORD", "RENAULT", "PEUGEOT", "CITROEN", "HYUNDAI",
                     "TOYOTA", "HONDA", "NISSAN", "KIA", "MITSUBISHI", "JEEP", "MERCEDES", "BENZ", "AUDI", "BMW"}
MONTADORAS = MONTADORAS_TITULO | {
    "GMC", "MERCEDES-BENZ", "MERCEDEZ-BENZ", "MERCEDES BENZ", "ALFA ROMEO", "LAND ROVER", "ASIA", "ASIA MOTORS",
    "KIA MOTORS", "CHRYSLER", "DODGE", "JAC", "CHERY", "SUZUKI", "SUBARU", "VOLVO", "SEAT", "AGRALE", "IVECO", "SCANIA",
    "TROLLER", "LIFAN", "SSANGYONG", "CAOA", "BYD", "GWM", "DAEWOO", "GURGEL", "WILLYS", "MAHINDRA", "EFFA", "JAGUAR",
    "PORSCHE", "LEXUS"}
PALAVRAS_ANO = {"APOS", "ATE", "TODOS", "TODAS", "EXCETO"}  # 'Topic Após 08', 'Apollo até 92', 'Blazer todos'


def ler_anos(palavra):
    """'1981-2003' -> [1981, 2003]; '96' -> [1996]; '07' -> [2007]; outra coisa -> []."""
    if re.fullmatch(r"(?:19|20)\d{2}(?:-(?:19|20)\d{2})?", palavra):
        return [int(a) for a in palavra.split("-")]
    if re.fullmatch(r"\d{2}", palavra):
        return [int(palavra) + (1900 if int(palavra) >= 30 else 2000)]
    return []

def juntar_anos(a, b):
    """Une dois intervalos (início, fim); None no início ou no fim é 'em aberto' ('até 92', 'após 07')."""
    if not a:
        return b
    return (None if None in (a[0], b[0]) else min(a[0], b[0]), None if None in (a[1], b[1]) else max(a[1], b[1]))

def ocorrencias_do_texto(texto):
    """Aplicação escrita no catálogo -> ocorrências (ver agrupar_veiculos). Formatos dos sites:
    'Ford Escort 1981-2003 1.8 16V' (KarHub, Universal), 'GOL G2 96 97 98; GOL G3 2000 2001' (CarBlue),
    'Fiat: Palio 01 a 12, Siena Após 08' e 'GM, Blazer todos' (ShopPeças), 'Gol, Parati - 1998 1999' (ClicPeças)."""
    texto = sem_acento(re.sub(r"\([^)]*\)", " ", texto or "")).upper()  # '(PALHETA TRASEIRA)', '(GMC)'
    ocorrencias, sem_ano, anterior_so_anos = [], [], False
    for trecho in texto.split(";"):
        for parte in re.split(r",|\s+-\s+", trecho.split(":", 1)[-1]):  # 'FIAT: PALIO ...' / 'GOL, PARATI - 1998'
            palavras = parte.split()
            inicio = len(palavras)
            while palavras and (" ".join(palavras[:2]) in MONTADORAS or palavras[0] in MONTADORAS):
                palavras = palavras[2:] if " ".join(palavras[:2]) in MONTADORAS else palavras[1:]
            montadora = parte.split()[:inicio - len(palavras)]
            # só anos ('2014', '2000 1.6 16V'); '80 AVANT 91 A 98' e 'AUDI 80 1991' começam pelo modelo (Audi 80)
            so_anos = not montadora and all(ler_anos(p) or re.fullmatch(r"\d\.\d|\d+V", p) or p in PALAVRAS_ANO | {"A", "E"}
                                            for p in palavras)
            n = next((i for i, p in enumerate(palavras)
                      if (i or so_anos) and (ler_anos(p) or re.match(r"\d\.\d", p) or p in PALAVRAS_ANO)), len(palavras))
            modelo, anos, apos, ate = " ".join(palavras[:n]), [], False, False
            for p in palavras[n:]:
                apos, ate = apos or (p == "APOS" and not anos), ate or (p == "ATE" and not anos)
                anos += ler_anos(p)
            intervalo = (None if ate else min(anos), None if apos else max(anos)) if anos else None
            motores = re.findall(r"\b\d\.\d\b", parte)
            if modelo:
                if intervalo or anterior_so_anos:
                    sem_ano = []
                ocorrencias.append([" ".join(montadora + palavras[:n]), modelo, intervalo, motores])
                if not intervalo:
                    sem_ano.append(ocorrencias[-1])
                anterior_so_anos = False
            elif intervalo:  # parte só com anos: vale para os modelos sem ano logo antes ('GOL, PARATI - 1998')
                for o in sem_ano or ocorrencias[-1:]:
                    o[2], o[3] = juntar_anos(o[2], intervalo), o[3] + motores
                anterior_so_anos = True
    return ocorrencias
