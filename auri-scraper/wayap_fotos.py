#!/usr/bin/env python3
"""Escolhe as melhores fotos das pastas raspadas e sobe para os produtos de um banco do Wayap.

Uso (credenciais por variável de ambiente ou num .env ao lado do script, nunca no código):
    export WAYAP_URL=https://wayap.com.br/admin2 WAYAP_SOCIEDADE=topcar WAYAP_LOGIN=... WAYAP_SENHA=...
    python wayap_fotos.py planejar      # cruza produtos x fotos e gera <saida>/plano.csv (nada é enviado)
    python wayap_fotos.py enviar        # sobe as fotos do plano (retomável: pula o que já foi enviado)
    python wayap_fotos.py desfazer      # apaga do Wayap as fotos que este script enviou

Casamento produto do Wayap x peça raspada (pastas pecas_auri, pecas_autonext, pecas_hipervarejo):
- EAN igual (EAN-13 válido e que só aparece em um produto do Wayap), com a marca compatível ou
  o código/descrição confirmando;
- ou código do fabricante (num_fabricante/num_fabricante2, sem zeros à esquerda) + mesma marca,
  com pelo menos uma palavra da descrição em comum.
Casamentos sem essa confirmação vão para <saida>/revisar.csv e não são enviados.

Fotos: descarta menores que 250 px, logos/"sem foto" (mesma imagem em várias peças diferentes) e
duplicadas (inclusive das que o produto já tem no Wayap). O produto fica com no máximo 5 fotos.
"""
import argparse
import base64
import csv
import glob
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

FONTES = ["autonext=pecas_autonext/*/produto.json", "hipervarejo=pecas_hipervarejo/*/produto.json",
          "auri=pecas_auri/*/*/produto.json"]
MAX_FOTOS = 5
MENOR_LADO = 250
LADO_ENVIO = 1024  # o Wayap reduz para 1024 px de qualquer jeito; enviar menor economiza banda
DISTANCIA_DUPLICADA = 6  # bits diferentes no dHash de 64 bits
PARALELO_WAYAP = 3  # mais que isso o servidor do Wayap passa a recusar conexões por um tempo
# credenciais do Postgres do Wayap: leitura das fotos apagadas (a API não lista) e gravação do complemento no painel
ENV_ADMIN = Path(os.environ.get("WAYAP_ENV_ADMIN", "/home/alves/PROJETOS/WAYAP/.env_admin"))
MARCAS_GENERICAS = {"UNIVERSAL", "IMPORTADO", "FLINHA", "SEMMARCA", "ORIGINAL", "DIVERSOS", "GENERICO"}
PALAVRAS_IGNORADAS = {"PARA", "COM", "SEM", "KIT", "JOGO", "PECA", "PECAS", "MODELO", "LADO", "ORIGINAL",
                      "UNIVERSAL", "TODOS", "LINHA", "APLICACAO"}


def carregar_env(arquivo=Path(__file__).with_name(".env")):
    """WAYAP_* do .env ao lado do script (fora do git); variável já exportada tem prioridade."""
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            chave, sep, valor = linha.strip().partition("=")
            if sep and not chave.startswith("#"):
                os.environ.setdefault(chave.strip(), valor.strip())


carregar_env()


def sem_acento(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def n_marca(s):
    return re.sub(r"[^A-Z0-9]", "", sem_acento(s).upper())


def n_codigo(s):
    return re.sub(r"[^A-Z0-9]", "", sem_acento(s).upper()).lstrip("0")


def n_ean(s):
    d = re.sub(r"\D", "", s or "")
    if len(d) == 14 and d[0] == "0":
        d = d[1:]
    if len(d) == 12:
        d = "0" + d
    if len(d) != 13 or len(set(d)) == 1:
        return None
    return d if sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d)) % 10 == 0 else None


def palavras(s):
    return {p for p in re.findall(r"[A-Z]{4,}", sem_acento(s).upper()) if p not in PALAVRAS_IGNORADAS}


def palavras_em_comum(a, b):
    """Conta palavras que batem por prefixo ("DIANT" x "DIANTEIRO", "RETROV" x "RETROVISOR")."""
    return sum(any(x.startswith(y) or y.startswith(x) for y in b) for x in a)


def numeros_compativeis(a, b):
    """Compara só os dígitos: '2779-SAMPEL' x 'SIL2779' e '15139-KITCIA' x 'KC15139' são a mesma peça."""
    x, y = re.sub(r"\D", "", a).lstrip("0"), re.sub(r"\D", "", b).lstrip("0")
    return bool(x and y) and (x == y or (min(len(x), len(y)) >= 3 and (x in y or y in x)))


def marcas_compativeis(a, b):
    return a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))


# ---------- Wayap ----------

class Wayap:
    def __init__(self):
        faltando = [v for v in ("WAYAP_URL", "WAYAP_SOCIEDADE", "WAYAP_LOGIN", "WAYAP_SENHA") if not os.environ.get(v)]
        if faltando:
            raise SystemExit(f"defina as variáveis de ambiente: {', '.join(faltando)}")
        self.url = os.environ["WAYAP_URL"].rstrip("/")
        self.sociedade = os.environ["WAYAP_SOCIEDADE"]
        # arquivos estáticos ficam em /files/<id_sociedade em base64>/store/foto_produto/<cod>/<nome_imagem>
        self.url_fotos = (self.url.rsplit("/", 1)[0] + "/files/" + base64.b64encode(self.sociedade.encode()).decode()
                          + "/store/foto_produto/")
        self.token = None
        self.ids = {}  # nome da foto ('<cod>/<nome_imagem>') -> id_produto_foto
        self.login()

    def login(self):
        param = {"id_sociedade": self.sociedade, "cod_funcionario": os.environ["WAYAP_LOGIN"],
                 "senha": base64.b64encode(os.environ["WAYAP_SENHA"].encode()).decode(), "id_menu": 138,
                 "config": None}
        empresas = self._post("/login", {"call": "preLogin", "id_sociedade": self.sociedade, "param": param})
        if isinstance(empresas, dict):
            raise SystemExit(f"login recusado: {empresas.get('msg')}")
        param["id_empresa"] = empresas[0]["id_empresa"]  # fotos são por sociedade, qualquer empresa serve
        r = self._post("/login", {"call": "getLogin", "id_sociedade": self.sociedade, "param": param})
        if not r.get("token"):
            raise SystemExit(f"login recusado: {r.get('msg')}")
        self.token = r["token"]

    def _post(self, rota, json_=None, files=None, data=None):
        esperas = [5, 15, 30, 60]
        for tentativa in range(len(esperas) + 1):
            try:
                r = requests.post(self.url + rota, json=json_, files=files, data=data, timeout=120,
                                  headers={"Authorization": self.token} if self.token else {})
                if r.status_code == 401 and self.token:  # token expirado
                    self.token = None
                    self.login()
                    continue
                return r.json()
            except (requests.RequestException, ValueError):
                if tentativa == len(esperas):
                    raise
                time.sleep(esperas[tentativa])

    def chamar(self, rota, call, **dados):
        return self._post(rota, {"call": call, **dados})

    def produtos(self):
        todos, offset, lote = [], 0, 2000
        while True:
            r = self._post("/produto", {"call": "getProdutos", "param": {"maxItem": lote}, "offset": offset})
            todos += r
            if len(r) < lote:
                return todos
            offset += lote

    def checar_api_fotos(self):
        """Fotos agora ficam na tabela produto_foto, uma pasta por produto. A API antiga lê a pasta plana (que a
        migração esvaziou): lista tudo vazio e grava fora da tabela. Ela devolve [] para cod_produto inválido;
        a nova recusa."""
        if getattr(self, "_api_nova", False):
            return
        if isinstance(self._post("/produto", {"call": "getListaFotoJson", "cod_produto": 0}), list):
            raise SystemExit(f"{self.url}: a API de fotos ainda é a antiga (pasta plana); publique o erp_server "
                             "com produto_foto antes de mexer em fotos")
        self._api_nova = True

    def fotos(self, cod_produto):
        """Fotos ativas na ordem do produto, como caminho relativo a url_fotos ('<cod>/<nome_imagem>')."""
        self.checar_api_fotos()
        r = self._post("/produto", {"call": "getListaFotoJson", "cod_produto": cod_produto})
        if not isinstance(r, list):
            raise RuntimeError(f"getListaFotoJson({cod_produto}): {r}")
        nomes = []
        for f in sorted(r, key=lambda f: f["ordem_imagem"]):
            nome = f"{cod_produto}/{f['nome_imagem']}"
            self.ids[nome] = f["id_produto_foto"]
            nomes.append(nome)
        return nomes

    def id_foto(self, cod_produto, nome):
        if nome not in self.ids:
            self.fotos(cod_produto)
        return self.ids.get(nome)

    def hash_foto(self, nome):
        """dHash de uma foto que já está no Wayap (None se não der para baixar/abrir)."""
        try:
            r = requests.get(self.url_fotos + nome, timeout=60)
            return dhash(abrir_rgb(r.content)) if r.status_code == 200 else None
        except Exception:
            return None

    def enviar_foto(self, cod_produto, caminho):
        """Resposta do Wayap; em caso de sucesso, com 'img' = nome da foto no formato de fotos()."""
        self.checar_api_fotos()
        with open(caminho, "rb") as f:
            r = self._post("/produto", data={"call": "uploadFoto", "codProduto": str(cod_produto)},
                           files={"foto": (Path(caminho).name, f, "image/jpeg")})
        if isinstance(r, dict) and r.get("id_produto_foto") and r.get("nome_imagem"):
            r["img"] = f"{cod_produto}/{r['nome_imagem']}"
            self.ids[r["img"]] = r["id_produto_foto"]
        return r

    def apagar_foto(self, cod_produto, nome):
        self.checar_api_fotos()
        id_foto = self.id_foto(cod_produto, nome)
        if not id_foto:
            return {"msg": f"foto {nome} não está mais no produto {cod_produto}"}
        return self._post("/produto", {"call": "deleteFoto", "cod_produto": cod_produto, "id_produto_foto": id_foto})

    def reordenar_fotos(self, cod_produto, nomes):
        self.checar_api_fotos()
        ids = [self.id_foto(cod_produto, n) for n in nomes]
        return self._post("/produto", {"call": "alterarOrdemFoto", "cod_produto": cod_produto, "ids": ids})


# ---------- imagens ----------

def abrir_rgb(origem):
    im = Image.open(origem if not isinstance(origem, bytes) else BytesIO(origem))
    if im.mode in ("RGBA", "LA", "P"):
        # fundo transparente vira branco (o Wayap converte para JPEG e o transparente ficaria preto)
        im = im.convert("RGBA")
        fundo = Image.new("RGBA", im.size, "white")
        im = Image.alpha_composite(fundo, im)
    return im.convert("RGB")


def dhash(im):
    g = im.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.tobytes())
    return sum(1 << i for i in range(64) if px[(i // 8) * 9 + i % 8] > px[(i // 8) * 9 + i % 8 + 1])


def distancia(a, b):
    return bin(a ^ b).count("1")


def info_foto(caminho):
    try:
        im = abrir_rgb(caminho)
        return caminho, {"w": im.width, "h": im.height, "hash": dhash(im)}
    except Exception:
        return caminho, None


# ---------- planejar ----------

def carregar_fontes(base, fontes=FONTES):
    registros = []
    for fonte, padrao in (f.split("=", 1) for f in fontes):
        for arq in glob.glob(str(base / padrao)):
            r = json.loads(Path(arq).read_text(encoding="utf-8"))
            pasta = Path(arq).parent
            imagens = [str(pasta / i["arquivo"]) for i in r.get("imagens", []) if (pasta / i["arquivo"]).exists()]
            if imagens:
                registros.append({"fonte": fonte, "pasta": str(pasta.relative_to(base)), "nome": r.get("nome") or "",
                                  "marca": n_marca(r.get("marca")), "codigo": n_codigo(r.get("codigo_fabricante")),
                                  "ean": n_ean(r.get("ean")), "imagens": imagens, "url": r.get("url_origem")})
    return registros


def casar(produtos, registros):
    por_ean, por_codigo = defaultdict(list), defaultdict(list)
    for i, r in enumerate(registros):
        if r["ean"]:
            por_ean[r["ean"]].append(i)
        if len(r["codigo"]) >= 3:
            por_codigo[(r["marca"], r["codigo"])].append(i)
    eans_wayap = Counter(n_ean(p["cod_barra"]) for p in produtos)

    casados, revisar = [], []
    for p in produtos:
        marca = n_marca(p["marca"])
        ean = n_ean(p["cod_barra"])
        codigos = {c for c in (n_codigo(p["num_fabricante"]), n_codigo(p["num_fabricante2"])) if len(c) >= 3}
        desc = palavras(p["desc_produto"])
        pelo_ean = por_ean.get(ean, []) if ean and eans_wayap[ean] == 1 else []
        pelo_codigo = [i for c in codigos for i in por_codigo.get((marca, c), [])]
        aceitos, motivos = {}, {}
        for i in dict.fromkeys(pelo_ean + pelo_codigo):
            r = registros[i]
            comum = palavras_em_comum(desc, palavras(r["nome"]))
            codigo_confere = any(c == r["codigo"] or c in n_codigo(r["nome"]) for c in codigos)
            # EAN igual mas número do código diferente (ex.: JCV 1046.11 x 104612): peça vizinha ou cadastro errado
            codigo_diverge = bool(codigos and r["codigo"]) and not codigo_confere and \
                not any(numeros_compativeis(c, r["codigo"]) for c in codigos)
            if i in pelo_ean and i in pelo_codigo:
                aceitos[i] = "ean+codigo"
            elif i in pelo_ean and codigo_diverge:
                motivos[i] = "ean igual, codigo diferente"
            elif i in pelo_ean and (marcas_compativeis(marca, r["marca"]) or codigo_confere or comum >= 1):
                aceitos[i] = "ean"
            elif i in pelo_codigo and comum >= (2 if marca in MARCAS_GENERICAS else 1):
                aceitos[i] = "codigo+marca"
            else:
                motivos[i] = "ean com marca diferente" if i in pelo_ean else "codigo sem descricao em comum"
        if aceitos:
            casados.append((p, aceitos))
        for i, motivo in motivos.items():
            revisar.append((p, registros[i], motivo))
    return casados, revisar


def apagadas_no_banco(sociedade, cods):
    """{cod: ['<cod>/<nome_imagem>']} das fotos que alguém apagou (a API só lista as ativas, então lê o banco)."""
    if not ENV_ADMIN.exists():
        print(f"aviso: {ENV_ADMIN} não encontrado; fotos apagadas no Wayap podem voltar", file=sys.stderr)
        return {}
    import psycopg2
    env = dict(re.findall(r"^(POSTGRES_[A-Z]+)=(.*)$", ENV_ADMIN.read_text(), re.M))
    con = psycopg2.connect(host=env["POSTGRES_HOST"], port=env["POSTGRES_PORT"], user=env["POSTGRES_USER"],
                           password=env["POSTGRES_PASSWORD"], dbname=sociedade, connect_timeout=15)
    try:
        con.set_session(readonly=True)
        with con.cursor() as cur:
            cur.execute("SELECT cod_produto, nome_imagem FROM produto_foto WHERE deletado_em IS NOT NULL "
                        "AND nome_imagem <> '' AND cod_produto = ANY(%s)", (list(cods),))
            apagadas = defaultdict(list)
            for cod, nome in cur.fetchall():
                apagadas[cod].append(f"{cod}/{nome}")
            return apagadas
    finally:
        con.close()


def fotos_recusadas(wayap, existentes, hashes_existentes):
    """Hashes, por produto, das fotos que alguém apagou no Wayap: não voltam.

    Duas origens: as apagadas que o banco ainda guarda (deletado_em) e as que subimos em qualquer lote e não
    estão mais no produto (apagadas antes da tabela produto_foto). Só olha os produtos em `existentes`; foto
    atual que não dá para comparar (hash None) faz o produto ser pulado na segunda, para não recusar à toa."""
    enviadas = defaultdict(set)
    for arq in glob.glob(f"fotos_wayap_{wayap.sociedade}*/plano.json"):
        for p in json.loads(Path(arq).read_text(encoding="utf-8")):
            if p["cod_produto"] in existentes:
                for f in p["fotos"]:
                    if f["status"] in ("enviado", "apagado_curadoria") and Path(f.get("preparada") or "").is_file():
                        enviadas[p["cod_produto"]].add(f["preparada"])
    caminhos = sorted({c for cs in enviadas.values() for c in cs})
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        hashes = {c: d["hash"] for c, d in pool.map(info_foto, caminhos) if d}
    recusadas = defaultdict(list)
    for cod, cs in enviadas.items():
        atuais = [hashes_existentes.get(n) for n in existentes[cod]]
        if None in atuais:
            continue
        recusadas[cod] += [hashes[c] for c in cs if c in hashes
                           and all(distancia(hashes[c], h) > DISTANCIA_DUPLICADA for h in atuais)]
    apagadas = apagadas_no_banco(wayap.sociedade, existentes)
    nomes = [n for ns in apagadas.values() for n in ns]
    with ThreadPoolExecutor(max_workers=PARALELO_WAYAP) as pool:
        hashes_apagadas = dict(zip(nomes, pool.map(wayap.hash_foto, nomes)))
    for cod, ns in apagadas.items():
        recusadas[cod] += [h for n in ns if (h := hashes_apagadas[n]) is not None]
    return {cod: hs for cod, hs in recusadas.items() if hs}


def planejar(args):
    base = Path(args.base)
    saida = Path(args.saida)
    wayap = Wayap()
    print("lendo produtos do Wayap...")
    # a listagem do Wayap repete alguns produtos (um por linha de estoque/carro); um envio por produto
    produtos = list({p["cod_produto"]: p for p in wayap.produtos()}.values())
    if args.so_sem_foto:
        produtos = [p for p in produtos if not (p["foto"] or "").strip()]
    registros = carregar_fontes(base, args.fontes)
    print(f"{len(produtos)} produtos no Wayap, {len(registros)} peças com foto nas pastas")
    casados, revisar = casar(produtos, registros)
    print(f"{len(casados)} produtos casados, {len(revisar)} casamentos para revisar")

    with ThreadPoolExecutor(max_workers=PARALELO_WAYAP) as pool:
        existentes = dict(zip([p["cod_produto"] for p, _ in casados],
                              pool.map(lambda p: wayap.fotos(p["cod_produto"]) if (p["foto"] or "").strip() else [],
                                       [p for p, _ in casados])))
        nomes_existentes = [n for ns in existentes.values() for n in ns]
        print(f"baixando {len(nomes_existentes)} fotos que já estão no Wayap para não repetir...")
        hashes_existentes = dict(zip(nomes_existentes, pool.map(wayap.hash_foto, nomes_existentes)))
    recusadas = fotos_recusadas(wayap, existentes, hashes_existentes)
    print(f"{sum(map(len, recusadas.values()))} fotos apagadas no Wayap (não voltam) "
          f"em {len(recusadas)} produtos")

    candidatas = sorted({img for _, aceitos in casados for i in aceitos for img in registros[i]["imagens"]})
    print(f"analisando {len(candidatas)} fotos candidatas...")
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        info = dict(pool.map(info_foto, candidatas))

    # A mesma imagem em peças de códigos diferentes é logo da marca ou "sem foto"
    codigos_por_hash = defaultdict(set)
    for r in registros:
        for img in r["imagens"]:
            if info.get(img):
                codigos_por_hash[info[img]["hash"]].add(r["codigo"] or r["pasta"])
    genericas = {h for h, cods in codigos_por_hash.items() if len(cods) >= 3}

    plano = []
    for p, aceitos in casados:
        ja_tem = existentes.get(p["cod_produto"], [])
        vagas = MAX_FOTOS - len(ja_tem)
        if vagas <= 0:
            continue
        fotos = []
        for i in aceitos:
            r = registros[i]
            for ordem, img in enumerate(r["imagens"]):
                d = info.get(img)
                if d and min(d["w"], d["h"]) >= MENOR_LADO and d["hash"] not in genericas:
                    fotos.append({"origem": img, "fonte": r["fonte"], "pasta": r["pasta"], "url_origem": r["url"],
                                  "principal": ordem == 0,
                                  "w": d["w"], "h": d["h"], "hash": d["hash"], "casamento": aceitos[i]})
        # capa: a foto principal de maior resolução; depois as demais por resolução
        fotos.sort(key=lambda f: (not (f["principal"] and not ja_tem), -min(f["w"], f["h"], 1200), not f["principal"]))
        escolhidas, vistos = [], [h for n in ja_tem if (h := hashes_existentes.get(n)) is not None]
        recusadas_aqui = recusadas.get(p["cod_produto"], [])
        for f in fotos:
            if all(distancia(f["hash"], h) > DISTANCIA_DUPLICADA for h in vistos + recusadas_aqui):
                escolhidas.append(f)
                vistos.append(f["hash"])
            if len(escolhidas) == vagas:
                break
        if escolhidas:
            plano.append({"cod_produto": p["cod_produto"], "desc_produto": p["desc_produto"], "marca": p["marca"],
                          "carro": p.get("carro"), "num_fabricante": p["num_fabricante"], "cod_barra": p["cod_barra"],
                          "fotos_existentes": len(ja_tem),
                          "casamento": sorted(set(aceitos.values())),
                          "fotos": [{k: v for k, v in f.items() if k != "hash"} | {"status": "pendente", "nome_wayap": None}
                                    for f in escolhidas]})

    preparar(plano, saida)
    gravar_plano(plano, saida)
    with open(saida / "revisar.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cod_produto", "desc_produto", "marca", "num_fabricante", "cod_barra", "motivo", "fonte",
                    "peca_encontrada", "marca_peca", "pasta"])
        for p, r, motivo in revisar:
            w.writerow([p["cod_produto"], p["desc_produto"], p["marca"], p["num_fabricante"], p["cod_barra"], motivo,
                        r["fonte"], r["nome"], r["marca"], r["pasta"]])
    total = sum(len(p["fotos"]) for p in plano)
    print(f"plano: {total} fotos para {len(plano)} produtos "
          f"({sum(1 for p in plano if not p['fotos_existentes'])} sem foto hoje). Veja {saida / 'plano.csv'}")


def preparar(plano, saida):
    """JPEG com fundo branco e no máximo 1024 px, pronto para enviar: <saida>/enviar/<cod_produto>/<n>.jpg"""
    def uma(args):
        cod, n, f = args
        destino = saida / "enviar" / str(cod) / f"{n}.jpg"
        destino.parent.mkdir(parents=True, exist_ok=True)
        im = abrir_rgb(f["origem"])
        im.thumbnail((LADO_ENVIO, LADO_ENVIO), Image.LANCZOS)
        im.save(destino, "JPEG", quality=92)
        f["preparada"] = str(destino)

    tarefas = [(p["cod_produto"], n, f) for p in plano for n, f in enumerate(p["fotos"], 1)]
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as pool:
        list(pool.map(uma, tarefas))


def gravar_plano(plano, saida):
    saida.mkdir(parents=True, exist_ok=True)
    tmp = saida / "plano.json.tmp"
    tmp.write_text(json.dumps(plano, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(saida / "plano.json")
    # planilha: uma linha por foto, com a marcação do que sobe (ou já subiu) para o Wayap
    with open(saida / "plano.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["cod_produto", "desc_produto", "marca", "num_fabricante", "cod_barra", "casamento",
                    "fotos_ja_no_wayap", "ordem", "fonte", "foto_origem", "resolucao", "status", "nome_no_wayap"])
        for p in plano:
            for n, foto in enumerate(p["fotos"], 1):
                w.writerow([p["cod_produto"], p["desc_produto"], p["marca"], p["num_fabricante"], p["cod_barra"],
                            "+".join(p["casamento"]), p["fotos_existentes"], n, foto["fonte"], foto["origem"],
                            f"{foto['w']}x{foto['h']}", foto["status"], foto["nome_wayap"] or ""])


# ---------- enviar / desfazer ----------

def marcar_pastas(plano, base):
    """Em cada pasta de origem, wayap_<sociedade>.json diz qual foto foi para qual produto."""
    sociedade = os.environ["WAYAP_SOCIEDADE"]
    por_pasta = defaultdict(list)
    for p in plano:
        for f in p["fotos"]:
            if f["status"] == "enviado":
                por_pasta[f["pasta"]].append({"cod_produto": p["cod_produto"], "foto": Path(f["origem"]).name,
                                              "nome_no_wayap": f["nome_wayap"], "enviado_em": f.get("enviado_em")})
    for pasta, fotos in por_pasta.items():
        (base / pasta / f"wayap_{sociedade}.json").write_text(json.dumps(fotos, ensure_ascii=False, indent=1),
                                                                encoding="utf-8")


def enviar(args):
    saida = Path(args.saida)
    plano = json.loads((saida / "plano.json").read_text(encoding="utf-8"))
    if args.limite:
        plano_envio = [p for p in plano if any(f["status"] == "pendente" for f in p["fotos"])][:args.limite]
    else:
        plano_envio = plano
    wayap = Wayap()
    erros = []
    if args.repetir_erros:
        # só reenvia se o Wayap tiver exatamente as fotos que o plano diz (a que falhou não entrou)
        for p in plano:
            if any(f["status"] == "erro" for f in p["fotos"]):
                esperado = p["fotos_existentes"] + sum(f["status"] == "enviado" for f in p["fotos"])
                novo = "pendente" if len(wayap.fotos(p["cod_produto"])) == esperado else "verificar"
                for f in p["fotos"]:
                    if f["status"] == "erro":
                        f["status"] = novo

    def um_produto(p):
        pendentes = [f for f in p["fotos"] if f["status"] == "pendente"]
        if not pendentes:
            return
        try:
            # confere de novo no Wayap: alguém pode ter cadastrado foto depois do planejamento
            vagas = MAX_FOTOS - len(wayap.fotos(p["cod_produto"]))
        except Exception as e:
            erros.append((p["cod_produto"], e))
            return
        for f in pendentes:
            if vagas <= 0:
                f["status"] = "sem_vaga"
                continue
            try:
                r = wayap.enviar_foto(p["cod_produto"], f["preparada"])
            except Exception as e:  # sem resposta: a foto pode ou não ter entrado; não reenvia sozinho
                r = str(e)
            if isinstance(r, dict) and r.get("img"):
                f["status"], f["nome_wayap"] = "enviado", r["img"]
                f["enviado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
                vagas -= 1
            else:
                f["status"] = "erro"
                erros.append((p["cod_produto"], r))
                return  # a ordem das fotos importa: não sobe as seguintes deste produto

    feitos = 0
    try:
        with ThreadPoolExecutor(max_workers=args.paralelo) as pool:
            for _ in pool.map(um_produto, plano_envio):
                feitos += 1
                if feitos % 50 == 0:
                    gravar_plano(plano, saida)
                    print(f"{feitos}/{len(plano_envio)} produtos, {len(erros)} erros", flush=True)
    finally:  # grava o que já subiu mesmo se for interrompido, para não reenviar
        gravar_plano(plano, saida)
        marcar_pastas(plano, Path(args.base))
    enviadas = sum(f["status"] == "enviado" for p in plano for f in p["fotos"])
    print(f"{enviadas} fotos enviadas no total, {len(erros)} erros nesta execução")
    for cod, r in erros[:20]:
        print(f"  ERRO produto {cod}: {r}", file=sys.stderr)


def desfazer(args):
    saida = Path(args.saida)
    plano = json.loads((saida / "plano.json").read_text(encoding="utf-8"))
    wayap = Wayap()
    apagadas = 0
    for p in plano:
        # do último para o primeiro: apagar reordena as fotos seguintes, e as nossas são as últimas
        for f in reversed(p["fotos"]):
            if f["status"] == "enviado" and f["nome_wayap"] in wayap.fotos(p["cod_produto"]):
                wayap.apagar_foto(p["cod_produto"], f["nome_wayap"])
                f["status"], f["nome_wayap"] = "desfeito", None
                apagadas += 1
    gravar_plano(plano, saida)
    marcar_pastas(plano, Path(args.base))
    print(f"{apagadas} fotos apagadas do Wayap")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("acao", choices=["planejar", "enviar", "desfazer"])
    ap.add_argument("--base", default=".", help="pasta com pecas_auri, pecas_autonext e pecas_hipervarejo")
    ap.add_argument("--saida", default=None, help="pasta do plano (padrão: fotos_wayap_<sociedade>)")
    ap.add_argument("--fontes", nargs="+", default=FONTES, metavar="NOME=GLOB",
                    help="planejar: pastas de peças (padrão: auri, autonext e hipervarejo)")
    ap.add_argument("--so-sem-foto", action="store_true", help="planejar: só produtos que não têm nenhuma foto")
    ap.add_argument("--limite", type=int, help="enviar: só os N primeiros produtos pendentes (teste)")
    ap.add_argument("--repetir-erros", action="store_true", help="enviar: tenta de novo as fotos que deram erro")
    ap.add_argument("--paralelo", type=int, default=PARALELO_WAYAP, help="enviar: envios simultâneos")
    args = ap.parse_args()
    args.saida = args.saida or f"fotos_wayap_{os.environ.get('WAYAP_SOCIEDADE', 'sociedade')}"
    {"planejar": planejar, "enviar": enviar, "desfazer": desfazer}[args.acao](args)


if __name__ == "__main__":
    main()
