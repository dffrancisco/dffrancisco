#!/usr/bin/env python3
"""Envia uma pasta para um link de compartilhamento público do Nextcloud (WebDAV).

Uso:
    python nextcloud_upload.py PASTA https://servidor/s/TOKEN [--destino nome] [-j 8]

O link precisa permitir envio de arquivos. Se tiver senha, defina NEXTCLOUD_SENHA.
Pode ser executado várias vezes: arquivos já enviados com o mesmo tamanho são pulados
(registro em PASTA/_enviados.json).
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlparse

import requests


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta")
    ap.add_argument("link", help="link público, ex.: https://nextcloud.exemplo.com/s/AbC123")
    ap.add_argument("--destino", default="", help="subpasta no Nextcloud (padrão: raiz do link)")
    ap.add_argument("-j", "--jobs", type=int, default=8)
    args = ap.parse_args()

    pasta = Path(args.pasta)
    u = urlparse(args.link)
    token = u.path.rstrip("/").split("/")[-1]
    base = f"{u.scheme}://{u.netloc}/public.php/webdav"
    auth = (token, os.environ.get("NEXTCLOUD_SENHA", ""))
    registro = pasta / "_enviados.json"
    enviados = json.loads(registro.read_text()) if registro.exists() else {}
    trava = threading.Lock()
    local = threading.local()

    def sessao():
        if not hasattr(local, "s"):
            local.s = requests.Session()
            local.s.auth = auth
        return local.s

    def remoto(rel):
        return base + "/" + quote("/".join(p for p in (args.destino, rel) if p))

    arquivos = sorted(p for p in pasta.rglob("*") if p.is_file() and not p.name.startswith("_"))
    pendentes = [p for p in arquivos
                 if enviados.get(p.relative_to(pasta).as_posix()) != p.stat().st_size]
    print(f"{len(arquivos)} arquivos, {len(pendentes)} para enviar", flush=True)

    # Cria as pastas antes (pais primeiro); 405 = já existe
    pastas = {Path(args.destino)} if args.destino else set()
    for p in pendentes:
        rel = p.relative_to(pasta).parent
        for i in range(1, len(rel.parts) + 1):
            pastas.add(Path(args.destino, *rel.parts[:i]))
    s = requests.Session()
    s.auth = auth
    for d in sorted(pastas, key=lambda x: len(x.parts)):
        r = s.request("MKCOL", base + "/" + quote(d.as_posix()))
        if r.status_code not in (201, 405):
            sys.exit(f"Erro ao criar pasta {d}: HTTP {r.status_code} {r.text[:200]}")

    def enviar(p):
        rel = p.relative_to(pasta).as_posix()
        for _ in range(3):
            try:
                with p.open("rb") as f:
                    r = sessao().put(remoto(rel), data=f, timeout=120)
                if r.status_code in (200, 201, 204):
                    return rel, p.stat().st_size, None
                erro = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                erro = str(e)
        return rel, None, erro

    erros = 0
    with ThreadPoolExecutor(args.jobs) as ex:
        for n, fut in enumerate(as_completed([ex.submit(enviar, p) for p in pendentes]), 1):
            rel, tamanho, erro = fut.result()
            with trava:
                if erro:
                    erros += 1
                    print(f"ERRO {rel}: {erro}", file=sys.stderr, flush=True)
                else:
                    enviados[rel] = tamanho
                if n % 500 == 0 or n == len(pendentes):
                    registro.write_text(json.dumps(enviados))
                    print(f"[{n}/{len(pendentes)}] enviados ({erros} erros)", flush=True)
    registro.write_text(json.dumps(enviados))
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
