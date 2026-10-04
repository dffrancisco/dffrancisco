"""Fotos de modelo (WebP com transparência) e logos de montadora (PNG) — spec de veículos, seção 7, passo 2.
Imagem própria em <saida>/proprias/ tem prioridade; modelo sem foto herda a do modelo-prefixo da mesma montadora."""
import hashlib
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from wayap_fotos import n_marca

LADO_LOGO = 200
EXTENSOES = {".png", ".jpg", ".jpeg", ".webp", ".avif"}


def para_webp(dados):
    im = Image.open(BytesIO(dados)).convert("RGBA")
    buf = BytesIO()
    im.save(buf, format="WEBP", quality=90, method=6)
    return buf.getvalue()


def para_png(dados, lado=LADO_LOGO):
    im = Image.open(BytesIO(dados)).convert("RGBA")
    im.thumbnail((lado, lado), Image.LANCZOS)
    buf = BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _proprias(pasta):
    """n_marca(nome do arquivo sem extensão) -> caminho. 'Chevrolet-Tracker.png' -> 'CHEVROLETTRACKER'."""
    pasta = Path(pasta)
    if not pasta.exists():
        return {}
    return {n_marca(a.stem): a for a in sorted(pasta.iterdir()) if a.suffix.lower() in EXTENSOES}


def _origem(propria, url, pasta_imagens):
    if propria:
        return propria.read_bytes(), "propria"
    if url:
        arq = Path(pasta_imagens) / urlsplit(url).path.lstrip("/")
        if arq.exists():
            return arq.read_bytes(), "karhub"
    return None, None


def _gravar(db, conteudo, pasta_saida, subpasta, prefixo, extensao):
    nome = f"{prefixo}_{hashlib.sha1(conteudo).hexdigest()[:8]}{extensao}"
    destino = Path(pasta_saida) / subpasta / nome
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
    caminho = f"veiculos/{subpasta}/{nome}"  # relativo a /home/wayap/helper/, como montadoras.logo do Wayap
    db.execute("INSERT OR IGNORE INTO veiculo_arquivo (caminho, publicado) VALUES (?, 0)", (caminho,))
    return caminho


def _converter(db, dados, origem, conversor, pasta_saida, subpasta, prefixo, extensao, r, tipo):
    """Converte e grava; imagem que não abre (HTML de erro, arquivo truncado) conta como inválida e devolve None."""
    if not dados:
        return None
    try:
        caminho = _gravar(db, conversor(dados), pasta_saida, subpasta, prefixo, extensao)
    except (OSError, ValueError, SyntaxError):  # PIL.UnidentifiedImageError é OSError
        r[f"{tipo}_invalida"] += 1
        return None
    r[f"{tipo}_{origem}"] += 1
    return caminho


def modelo_pai(nome, nomes_da_montadora, fotos):
    """Modelo da mesma montadora cujo nome é o prefixo mais longo (em palavras) do nome e que tem foto própria."""
    palavras = nome.split()
    for n in range(len(palavras) - 1, 0, -1):
        id_pai = nomes_da_montadora.get(" ".join(palavras[:n]))
        if id_pai and fotos.get(id_pai):
            return id_pai
    return None


def processar_imagens(db, pasta_imagens, pasta_saida):
    pasta_saida = Path(pasta_saida)
    r = Counter()
    logos_proprios = _proprias(pasta_saida / "proprias" / "montadoras")
    fotos_proprias = _proprias(pasta_saida / "proprias" / "modelos")
    for m in db.execute("SELECT id_veiculo_montadora, nome, logo_fonte FROM veiculo_montadora WHERE ativo = 1").fetchall():
        dados, origem = _origem(logos_proprios.get(n_marca(m["nome"])), m["logo_fonte"], pasta_imagens)
        logo = _converter(db, dados, origem, para_png, pasta_saida, "montadoras", m["id_veiculo_montadora"], ".png", r, "logo")
        if logo is None and not dados:
            r["logo_sem"] += 1
        db.execute("UPDATE veiculo_montadora SET logo = ? WHERE id_veiculo_montadora = ?", (logo, m["id_veiculo_montadora"]))
    modelos = db.execute("""SELECT mo.id_modelo, mo.id_veiculo_montadora, mo.nome, mo.foto_fonte, vm.nome AS montadora
                            FROM veiculo_modelo mo JOIN veiculo_montadora vm USING (id_veiculo_montadora)
                            WHERE mo.ativo = 1""").fetchall()
    fotos = {}
    for mo in modelos:
        dados, origem = _origem(fotos_proprias.get(n_marca(mo["montadora"] + mo["nome"])), mo["foto_fonte"], pasta_imagens)
        fotos[mo["id_modelo"]] = _converter(db, dados, origem, para_webp, pasta_saida, "modelos", mo["id_modelo"], ".webp", r, "foto")
    nomes = defaultdict(dict)
    for mo in modelos:
        nomes[mo["id_veiculo_montadora"]][mo["nome"]] = mo["id_modelo"]
    for mo in modelos:
        foto, herdada = fotos[mo["id_modelo"]], 0
        if foto is None:
            pai = modelo_pai(mo["nome"], nomes[mo["id_veiculo_montadora"]], fotos)
            if pai:
                foto, herdada = fotos[pai], 1
                r["foto_herdada"] += 1
            else:
                r["foto_sem"] += 1
        db.execute("UPDATE veiculo_modelo SET foto = ?, foto_herdada = ? WHERE id_modelo = ?", (foto, herdada, mo["id_modelo"]))
    db.commit()
    return dict(r)
