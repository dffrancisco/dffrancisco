"""Marcas, carros e produtos da topcar (via API do Wayap) em cache local: vocabulário e estatísticas."""
import json
from collections import Counter, defaultdict
from pathlib import Path

from helper.normalizar import tipo_peca
from wayap_fotos import sem_acento

CACHE_PADRAO = Path("helper_cache/topcar.json")


def carregar(cache=CACHE_PADRAO, renovar=False, wayap=None):
    cache = Path(cache) if cache else None
    if cache and cache.exists() and not renovar:
        return json.loads(cache.read_text(encoding="utf-8"))
    if wayap is None:
        from wayap_fotos import Wayap  # exige WAYAP_* no ambiente
        wayap = Wayap()
    produtos = list({p["cod_produto"]: p for p in wayap.produtos()}.values())
    dados = {"marcas": wayap.chamar("/produto", "getMarca"), "carros": wayap.chamar("/produto", "getCarro"),
             "produtos": [{k: p.get(k) for k in ("cod_produto", "desc_produto", "marca", "id_marca", "ncm", "unidade",
                                                 "id_fornecedor", "num_fabricante", "num_fabricante2", "cod_barra")}
                          for p in produtos]}
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return dados


def vocabulario_carros(dados):
    return {sem_acento(c["descricao"]).upper().strip(): sem_acento(c["descricao"]).upper().strip() for c in dados["carros"]}


class Estatisticas:
    def __init__(self, produtos):
        self.stats = defaultdict(Counter)
        for p in produtos:
            marca, tipo = sem_acento(p.get("marca") or "").upper(), tipo_peca(p.get("desc_produto") or "")
            uma = tipo.split(" ")[0] if tipo else ""
            if (p.get("ncm") or "").strip():
                for chave in (("ncm", marca, tipo), ("ncm", None, tipo), ("ncm", marca, uma), ("ncm", None, uma), ("ncm", marca, None)):
                    self.stats[chave][p["ncm"].strip()] += 1
            if p.get("unidade"):
                self.stats[("unidade", marca)][p["unidade"]] += 1

    def _moda(self, chave):
        c = self.stats.get(chave)
        return c.most_common(1)[0][0] if c else None

    def ncm(self, tipo, marca_nome):
        marca, uma = sem_acento(marca_nome or "").upper(), (tipo or "").split(" ")[0]
        for chave in (("ncm", marca, tipo), ("ncm", None, tipo), ("ncm", marca, uma), ("ncm", None, uma), ("ncm", marca, None)):
            if self._moda(chave):
                return self._moda(chave)
        return None

    def unidade(self, marca_nome):
        return self._moda(("unidade", sem_acento(marca_nome or "").upper()))


def produtos_para_cobertura(dados):
    return [p for p in dados["produtos"] if p.get("cod_barra") or p.get("num_fabricante")]
