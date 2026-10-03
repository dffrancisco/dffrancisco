#!/usr/bin/env python3
"""Helper: base de peças do mercado para o cadastro nos clientes do Wayap. Ver docs/superpowers/specs/2026-10-02-helper-design.md.

    python helper.py preparar            # lê catalogos/ e pecas_*, funde e grava helper.sqlite
    python helper.py fotos --limite 500  # baixa e cura fotos pendentes
    python helper.py relatorio
    python helper.py cobertura           # quanto da topcar o helper encontra
    python helper.py publicar --ensaio   # mostra o que mudaria no Postgres/servidor
"""
import sys

from helper.cli import main

if __name__ == "__main__":
    sys.exit(main())
