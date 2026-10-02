#!/usr/bin/env python3
"""Troca as fotos "da loja" de uma marca pelas de um catálogo (ex.: Arteb pela KarHub).

Uso (mesmas variáveis WAYAP_* do wayap_fotos.py):
    python trocar_fotos_marca.py --marca Arteb --site karhub --simular   # só mostra o que faria
    python trocar_fotos_marca.py --marca Arteb --site karhub [--limite 2]

Para cada produto da marca que casa com o catálogo (mesmas regras do wayap_fotos.py):
- apaga as fotos que já estavam no Wayap (as "da loja"), com backup local antes;
- mantém as que o wayap_fotos.py enviou (reconhecidas pelo conteúdo, não pelo nome);
- sobe as fotos do catálogo e as coloca na frente (a primeira vira capa). Se uma delas já estiver
  entre as mantidas, só muda de posição.
Resultado em fotos_wayap_<sociedade>_<marca>_<site>/: plano.json (entra na curadoria) e backup/.
"""
import argparse
import glob
import json
import socket
import time
from pathlib import Path

import requests
import urllib3.util.connection

from wayap_fotos import (DISTANCIA_DUPLICADA, LADO_ENVIO, MENOR_LADO, Wayap, abrir_rgb, casar, dhash, distancia,
                         gravar_plano, n_codigo, n_ean, n_marca)

# esta rede não tem rota IPv6 e o cdn.shopify.com às vezes resolve primeiro para IPv6
urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET
MAX_WAYAP = 10  # limite de fotos por produto no servidor


def hash_url(url):
    """None só se não der para baixar nem depois das novas tentativas."""
    conteudo = baixar(url)
    try:
        return dhash(abrir_rgb(conteudo)) if conteudo else None
    except Exception:
        return None


def baixar(url):
    for espera in (5, 15, 30, None):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200:
                return r.content
        except requests.RequestException:
            pass
        if espera is None:
            return None
        time.sleep(espera)


def fotos_no_wayap(w, cod):
    """[(nome, hash)] na ordem atual do Wayap."""
    return [(n, hash_url(w.url_fotos + n)) for n in w.fotos(cod)]


def nossas_por_produto(sociedade, cods):
    """Hashes das fotos que o wayap_fotos.py/painel enviaram, por produto (de todos os planos)."""
    nossas = {}
    for arq in glob.glob(f"fotos_wayap_{sociedade}*/plano.json"):
        for p in json.loads(Path(arq).read_text(encoding="utf-8")):
            if p["cod_produto"] in cods:
                for f in p["fotos"]:
                    if f["status"] == "enviado" and Path(f["preparada"]).exists():
                        nossas.setdefault(p["cod_produto"], []).append(dhash(abrir_rgb(f["preparada"])))
    return nossas


def eh_nossa(h, hashes):
    return h is not None and any(distancia(h, x) <= DISTANCIA_DUPLICADA for x in hashes)


def preparar_do_catalogo(urls, destino_dir):
    """Baixa, descarta pequenas e repetidas; devolve [(caminho_jpeg, hash, url, w, h)] na ordem do catálogo."""
    prontas = []
    for url in urls:
        try:
            r = requests.get(url, timeout=60)
            im = abrir_rgb(r.content) if r.status_code == 200 else None
        except Exception:
            im = None
        if im is None or min(im.size) < MENOR_LADO:
            continue
        h = dhash(im)
        if any(distancia(h, x[1]) <= DISTANCIA_DUPLICADA for x in prontas):
            continue
        largura, altura = im.size
        destino = destino_dir / f"{len(prontas) + 1}.jpg"
        destino.parent.mkdir(parents=True, exist_ok=True)
        im.thumbnail((LADO_ENVIO, LADO_ENVIO))
        im.save(destino, "JPEG", quality=92)
        prontas.append((destino, h, url, largura, altura))
    return prontas


def atualizar_planos_antigos(sociedade, cod, finais):
    """Depois de apagar/reordenar, os nomes das nossas fotos mudaram: acha cada uma pelo conteúdo."""
    for arq in glob.glob(f"fotos_wayap_{sociedade}*/plano.json"):
        plano = json.loads(Path(arq).read_text(encoding="utf-8"))
        mudou = False
        for p in plano:
            if p["cod_produto"] != cod:
                continue
            for f in p["fotos"]:
                if f["status"] == "enviado" and Path(f["preparada"]).exists():
                    h = dhash(abrir_rgb(f["preparada"]))
                    nome = next((n for n, x in finais if x is not None and distancia(h, x) <= DISTANCIA_DUPLICADA), None)
                    if nome and nome != f["nome_wayap"]:
                        f["nome_wayap"], mudou = nome, True
        if mudou:
            gravar_plano(plano, Path(arq).parent)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--marca", required=True)
    ap.add_argument("--site", default="karhub", help="catálogo em catalogos/<site>.jsonl")
    ap.add_argument("--simular", action="store_true", help="só mostra o que seria feito")
    ap.add_argument("--limite", type=int, help="só os N primeiros produtos (piloto)")
    args = ap.parse_args()

    w = Wayap()
    marca = n_marca(args.marca)
    produtos = [p for p in {p["cod_produto"]: p for p in w.produtos()}.values() if n_marca(p["marca"]) == marca]
    catalogo = [json.loads(l) for l in open(f"catalogos/{args.site}.jsonl", encoding="utf-8") if l.strip()]
    registros = [{"fonte": args.site, "pasta": c["url"], "nome": c.get("nome") or "", "marca": n_marca(c.get("marca")),
                  "codigo": n_codigo(c.get("codigo_fabricante")), "ean": n_ean(c.get("ean")),
                  "imagens": c.get("imagens") or [], "url": c["url"]}
                 for c in catalogo if n_marca(c.get("marca")) == marca and c.get("imagens")]
    casados, _ = casar(produtos, registros)
    casados = casados[:args.limite] if args.limite else casados
    print(f"{len(produtos)} produtos {args.marca} no Wayap, {len(registros)} no catálogo {args.site}, "
          f"{len(casados)} casados")

    saida = Path(f"fotos_wayap_{w.sociedade}_{marca.lower()}_{args.site}")
    plano_arq = saida / "plano.json"
    plano = json.loads(plano_arq.read_text(encoding="utf-8")) if plano_arq.exists() else []
    feitos = {p["cod_produto"] for p in plano}
    nossas = nossas_por_produto(w.sociedade, {p["cod_produto"] for p, _ in casados})
    totais = {"apagar": 0, "manter": 0, "subir": 0, "reaproveitar": 0}

    for n, (p, aceitos) in enumerate(casados, 1):
        cod = p["cod_produto"]
        if cod in feitos:
            continue
        urls = [u for i in aceitos for u in registros[i]["imagens"]]
        atuais = fotos_no_wayap(w, cod)
        if any(h is None for _, h in atuais):  # sem ver a foto não dá para saber se é nossa: não mexe
            print(f"    {cod}: alguma foto não baixou, produto pulado", flush=True)
            continue
        da_loja = [(nm, h) for nm, h in atuais if not eh_nossa(h, nossas.get(cod, []))]
        mantidas = [(nm, h) for nm, h in atuais if eh_nossa(h, nossas.get(cod, []))]
        novas = preparar_do_catalogo(urls, saida / "enviar" / str(cod))
        # foto do catálogo que já está entre as mantidas: só muda de posição
        reaproveitar = [nv for nv in novas if eh_nossa(nv[1], [h for _, h in mantidas])]
        subir = [nv for nv in novas if nv not in reaproveitar][:MAX_WAYAP - len(mantidas)]
        totais["apagar"] += len(da_loja)
        totais["manter"] += len(mantidas)
        totais["subir"] += len(subir)
        totais["reaproveitar"] += len(reaproveitar)
        print(f"[{n}/{len(casados)}] {cod} {p['desc_produto']}: apagar {len(da_loja)} da loja, manter "
              f"{len(mantidas)} nossas, subir {len(subir)} do {args.site}"
              + (f", {len(reaproveitar)} já existia" if reaproveitar else ""), flush=True)
        if args.simular or not novas:
            continue

        backup = saida / "backup" / str(cod)
        copias = {nome: baixar(w.url_fotos + nome) for nome, _ in da_loja}
        if not all(copias.values()):  # sem backup de todas, não apaga nada deste produto
            print(f"    {cod}: não consegui fazer backup das fotos da loja, produto pulado", flush=True)
            continue
        for nome, conteudo in copias.items():
            backup.mkdir(parents=True, exist_ok=True)
            (backup / nome).write_bytes(conteudo)
        # do último para o primeiro: apagar renumera só as fotos que vêm depois
        for nome, _ in reversed([a for a in atuais if a in da_loja]):
            w.apagar_foto(cod, nome)
        registradas = []
        for caminho, h, url, largura, altura in subir:
            r = w.enviar_foto(cod, str(caminho))
            ok = isinstance(r, dict) and r.get("img")
            registradas.append({"origem": url, "fonte": args.site, "pasta": "", "url_origem": registros[next(iter(aceitos))]["url"],
                                "principal": not registradas, "w": largura, "h": altura, "casamento": "troca " + marca.lower(),
                                "status": "enviado" if ok else "erro", "nome_wayap": r.get("img") if ok else None,
                                "preparada": str(caminho), "enviado_em": time.strftime("%Y-%m-%d %H:%M:%S")})
        # ordem final: fotos do catálogo (na ordem dele) na frente, depois as nossas que ficaram
        finais = fotos_no_wayap(w, cod)
        if any(h is None for _, h in finais):
            print(f"    {cod}: alguma foto não baixou, ordem não conferida (rode de novo)", flush=True)
        frente = []
        for _, h, *_ in novas:
            nome = next((nm for nm, x in finais if x is not None and nm not in frente
                         and distancia(h, x) <= DISTANCIA_DUPLICADA), None)
            if nome:
                frente.append(nome)
        ordem = frente + [nm for nm, _ in finais if nm not in frente]
        if ordem != [nm for nm, _ in finais]:
            w.reordenar_fotos(cod, ordem)
        finais = fotos_no_wayap(w, cod)
        for f in registradas:
            h = dhash(abrir_rgb(f["preparada"]))
            f["nome_wayap"] = next((nm for nm, x in finais if x is not None and distancia(h, x) <= DISTANCIA_DUPLICADA),
                                   f["nome_wayap"])
        atualizar_planos_antigos(w.sociedade, cod, finais)
        plano.append({"cod_produto": cod, "desc_produto": p["desc_produto"], "marca": p["marca"], "carro": p.get("carro"),
                      "num_fabricante": p["num_fabricante"], "cod_barra": p["cod_barra"],
                      "fotos_existentes": len(mantidas), "casamento": sorted(set(aceitos.values())),
                      "fotos_apagadas": [str(backup / nome) for nome, _ in da_loja], "fotos": registradas})
        gravar_plano(plano, saida)

    print(("SIMULAÇÃO: " if args.simular else "") + f"apagar {totais['apagar']} da loja, manter {totais['manter']} "
          f"nossas, subir {totais['subir']} do {args.site}, reposicionar {totais['reaproveitar']} que já existiam")


if __name__ == "__main__":
    main()
