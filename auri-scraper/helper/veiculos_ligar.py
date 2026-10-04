"""Ligação peça -> veículo (spec de veículos, seções 5.3 e 5.4): nível 'versao' pela compatibilidade do KarHub,
nível 'modelo' pelas aplicações em texto. karhub_compat.jsonl tem centenas de MB: é lido em fluxo."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from helper.banco import INDICES_PECA_VEICULO, agora, gravar_meta
from helper.veiculo_tipo import normalizar

LOTE = 20000


def faixas(selecionados, universo):
    """Anos de `selecionados` em faixas contínuas dentro da sequência ordenada `universo`
    (um ano que não está no universo não quebra a faixa)."""
    sel, saida, atual = set(selecionados), [], None
    for ano in universo:
        if ano in sel:
            atual = (ano, ano) if atual is None else (atual[0], ano)
        elif atual is not None:
            saida.append(atual)
            atual = None
    if atual is not None:
        saida.append(atual)
    return saida


def agrupar(versoes_por_ano, anos_por_versao, atendidas_por_ano):
    """versoes_por_ano: {ano: {id_versao}} do modelo; anos_por_versao: {id_versao: [anos ordenados]};
    atendidas_por_ano: {ano: {id_versao}} da peça. -> [(id_versao ou None = todas, ano_inicio, ano_fim)]."""
    anos_modelo = sorted(versoes_por_ano)
    completos = {a for a in anos_modelo if atendidas_por_ano.get(a) and versoes_por_ano[a] <= atendidas_por_ano[a]}
    linhas = [(None, i, f) for i, f in faixas(completos, anos_modelo)]
    restantes = defaultdict(list)
    for ano, versoes in atendidas_por_ano.items():
        if ano not in completos:
            for v in versoes:
                restantes[v].append(ano)
    for v in sorted(restantes):
        linhas += [(v, i, f) for i, f in faixas(restantes[v], anos_por_versao[v])]
    return linhas


def handle_da_url(url):
    return urlsplit(url or "").path.rsplit("/", 1)[-1]


class Arvore:
    """A árvore ativa em memória: tradução do id do KarHub e nomes de modelo por montadora."""

    def __init__(self, db):
        self.fonte = {}  # id_fonte -> (id_modelo, id_versao, ano)
        self.versoes_por_ano = defaultdict(lambda: defaultdict(set))  # id_modelo -> ano -> {id_versao}
        self.anos_por_versao = defaultdict(list)
        for id_fonte, id_versao, ano, id_modelo in db.execute(
                """SELECT f.id_fonte, f.id_versao, f.ano, v.id_modelo FROM veiculo_fonte f
                   JOIN veiculo_versao v USING (id_versao) JOIN veiculo_modelo m USING (id_modelo)
                   WHERE f.site = 'karhub' AND v.ativo = 1 AND m.ativo = 1"""):
            self.fonte[id_fonte] = (id_modelo, id_versao, ano)
        for id_versao, ano, id_modelo in db.execute(
                """SELECT va.id_versao, va.ano, v.id_modelo FROM veiculo_versao_ano va JOIN veiculo_versao v USING (id_versao)
                   WHERE v.ativo = 1 ORDER BY va.id_versao, va.ano"""):
            self.versoes_por_ano[id_modelo][ano].add(id_versao)
            self.anos_por_versao[id_versao].append(ano)
        self.modelos = defaultdict(dict)  # nome canônico da montadora -> {nome normalizado do modelo: id_modelo}
        self.modelos_do_nome = defaultdict(set)  # nome normalizado -> {id_modelo} (em qualquer montadora)
        for id_modelo, nome, montadora in db.execute(
                """SELECT mo.id_modelo, mo.nome, vm.nome FROM veiculo_modelo mo
                   JOIN veiculo_montadora vm USING (id_veiculo_montadora) WHERE mo.ativo = 1"""):
            self.modelos[montadora][normalizar(nome)] = id_modelo
            self.modelos_do_nome[normalizar(nome)].add(id_modelo)

    def linhas_versao(self, ids_fonte, contagem):
        por_modelo = defaultdict(lambda: defaultdict(set))
        for i in ids_fonte:
            alvo = self.fonte.get(str(i))
            if alvo is None:  # moto, pesado ou veículo que ainda não está na árvore
                contagem["ids_desconhecidos"] += 1
                continue
            id_modelo, id_versao, ano = alvo
            por_modelo[id_modelo][ano].add(id_versao)
        linhas = []
        for id_modelo in sorted(por_modelo):
            for id_versao, i, f in agrupar(self.versoes_por_ano[id_modelo], self.anos_por_versao, por_modelo[id_modelo]):
                linhas.append((id_modelo, id_versao, i, f, "versao"))
        return linhas

    def modelo_da_aplicacao(self, montadora, modelo):
        """Prefixo mais longo (em palavras) do modelo que é nome de modelo da árvore. Com montadora da árvore, só nela;
        sem montadora (ou fora da árvore), só se o nome existir numa única montadora."""
        palavras = normalizar(modelo).split()
        if montadora and montadora in self.modelos:
            nomes = self.modelos[montadora]
            for n in range(len(palavras), 0, -1):
                if " ".join(palavras[:n]) in nomes:
                    return nomes[" ".join(palavras[:n])]
            return None
        for n in range(len(palavras), 0, -1):
            ids = self.modelos_do_nome.get(" ".join(palavras[:n]))
            if ids:
                return next(iter(ids)) if len(ids) == 1 else None
        return None


def _inserir(db, linhas):
    db.executemany("INSERT INTO peca_veiculo (id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel) VALUES (?, ?, ?, ?, ?, ?)",
                   linhas)


def ligar_versao(db, arvore, caminho_compat):
    r = Counter()
    db.execute("DELETE FROM peca_veiculo")
    for nome in ("peca_veiculo_peca", "peca_veiculo_modelo"):
        db.execute(f"DROP INDEX IF EXISTS {nome}")  # milhões de linhas: os índices voltam no fim
    peca_do_handle = defaultdict(set)
    for id_peca, url in db.execute("SELECT o.id_peca, o.url FROM origem o JOIN peca p USING (id_peca) "
                                   "WHERE o.site = 'karhub' AND p.status = 'ativa'"):
        peca_do_handle[handle_da_url(url)].add(id_peca)
    qtd_handles = Counter(p for pecas in peca_do_handle.values() for p in pecas)
    acumulado, lote, vistos, ligadas = defaultdict(list), [], set(), set()

    def gravar(id_peca, ids):
        linhas = arvore.linhas_versao(ids, r)
        if linhas:
            ligadas.add(id_peca)
        lote.extend((id_peca, *l) for l in linhas)
        if len(lote) >= LOTE:
            _inserir(db, lote)
            lote.clear()

    caminho = Path(caminho_compat)
    if caminho.exists():
        with caminho.open(encoding="utf-8") as f:
            for texto in f:
                try:
                    l = json.loads(texto)
                    handle, ids = l["handle"], l.get("ids") or []
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                if handle in vistos:
                    continue
                vistos.add(handle)
                for id_peca in peca_do_handle.get(handle, ()):
                    if qtd_handles[id_peca] > 1:  # dois anúncios da mesma peça: soma antes de agrupar
                        acumulado[id_peca].extend(ids)
                    else:
                        gravar(id_peca, ids)
    for id_peca in sorted(acumulado):
        gravar(id_peca, acumulado[id_peca])
    _inserir(db, lote)
    for sql in INDICES_PECA_VEICULO:
        db.execute(sql)
    db.commit()
    r["pecas_nivel_versao"] = len(ligadas)
    r["handles_sem_compat"] = len(set(peca_do_handle) - vistos)
    return r


def juntar_faixas(faixas_):
    """[(ini, fim)], None = sem limite. Sem ano nenhum absorve tudo; sobrepostas ou adjacentes se juntam."""
    if any(i is None and f is None for i, f in faixas_):
        return [(None, None)]
    itens = sorted((i if i is not None else 0, f if f is not None else 9999) for i, f in faixas_)
    saida = []
    for i, f in itens:
        if saida and i <= saida[-1][1] + 1:
            saida[-1][1] = max(saida[-1][1], f)
        else:
            saida.append([i, f])
    return [(None if i == 0 else i, None if f == 9999 else f) for i, f in saida]


def ligar_modelo(db, arvore, montadoras):
    r, sem_modelo, pares = Counter(), Counter(), defaultdict(list)
    for id_peca, montadora, modelo, ini, fim in db.execute(
            "SELECT a.id_peca, a.montadora, a.modelo, a.ano_inicio, a.ano_fim FROM aplicacao a "
            "JOIN peca p USING (id_peca) WHERE p.status = 'ativa'"):
        id_modelo = arvore.modelo_da_aplicacao(montadoras.canonica(montadora), modelo)
        if id_modelo is None:
            sem_modelo[f"{montadora or ''} {modelo}".strip()] += 1
            continue
        if ini is not None and fim is not None and ini > fim:
            ini, fim = fim, ini
        pares[(id_peca, id_modelo)].append((ini, fim))
    db.execute("CREATE TEMP TABLE IF NOT EXISTS candidato_modelo (id_peca INTEGER, id_modelo INTEGER, ano_inicio INTEGER, ano_fim INTEGER)")
    db.execute("DELETE FROM candidato_modelo")
    db.executemany("INSERT INTO candidato_modelo VALUES (?, ?, ?, ?)",
                   ((p, m, i, f) for (p, m), fx in pares.items() for i, f in juntar_faixas(fx)))
    # par (peça, modelo) já confirmado pelo KarHub não ganha linha de texto
    r["linhas_nivel_modelo"] = db.execute(
        """INSERT INTO peca_veiculo (id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel)
           SELECT c.id_peca, c.id_modelo, NULL, c.ano_inicio, c.ano_fim, 'modelo' FROM candidato_modelo c
           WHERE NOT EXISTS (SELECT 1 FROM peca_veiculo pv
                             WHERE pv.id_peca = c.id_peca AND pv.id_modelo = c.id_modelo AND pv.nivel = 'versao')""").rowcount
    db.commit()
    r["pecas_nivel_modelo"] = db.execute("SELECT count(DISTINCT id_peca) FROM peca_veiculo WHERE nivel = 'modelo'").fetchone()[0]
    r["aplicacoes_sem_modelo"] = sum(sem_modelo.values())
    return r, sem_modelo


def _hash(obj):
    return hashlib.sha1(json.dumps(obj, ensure_ascii=False).encode()).hexdigest()


def atualizar_hashes_modelos(db):
    anos, versoes = defaultdict(list), defaultdict(list)
    for id_versao, ano in db.execute("SELECT id_versao, ano FROM veiculo_versao_ano ORDER BY id_versao, ano"):
        anos[id_versao].append(ano)
    for v in db.execute("SELECT id_versao, id_modelo, nome, nome_exibicao, motor, ativo FROM veiculo_versao ORDER BY id_versao"):
        versoes[v["id_modelo"]].append([v["id_versao"], v["nome"], v["nome_exibicao"], v["motor"], v["ativo"], anos[v["id_versao"]]])
    mudados = []
    for m in db.execute("""SELECT mo.*, vm.nome AS montadora FROM veiculo_modelo mo
                           JOIN veiculo_montadora vm USING (id_veiculo_montadora)""").fetchall():
        h = _hash([m["montadora"], m["id_veiculo_montadora"], m["nome"], m["nome_exibicao"], m["tipo"], m["foto"], m["foto_herdada"],
                   m["ano_inicio"], m["ano_fim"], m["qtd_pecas"], m["ativo"], versoes[m["id_modelo"]]])
        if h != m["hash_conteudo"]:
            mudados.append((h, agora(), m["id_modelo"]))
    db.executemany("UPDATE veiculo_modelo SET hash_conteudo = ?, atualizado_em = ? WHERE id_modelo = ?", mudados)
    return len(mudados)


def fechar(db):
    db.execute("UPDATE veiculo_modelo SET qtd_pecas = (SELECT count(DISTINCT pv.id_peca) FROM peca_veiculo pv "
               "WHERE pv.id_modelo = veiculo_modelo.id_modelo)")
    db.execute("""UPDATE veiculo_montadora SET qtd_pecas = (
                    SELECT count(DISTINCT pv.id_peca) FROM peca_veiculo pv JOIN veiculo_modelo mo ON mo.id_modelo = pv.id_modelo
                    WHERE mo.id_veiculo_montadora = veiculo_montadora.id_veiculo_montadora)""")
    estados, atual, linhas, total = [], None, [], 0
    for l in db.execute("SELECT id_peca, id_modelo, id_versao, ano_inicio, ano_fim, nivel FROM peca_veiculo "
                        "ORDER BY id_peca, id_modelo, nivel, id_versao, ano_inicio"):
        total += 1
        if l[0] != atual:
            if atual is not None:
                estados.append((atual, _hash(linhas)))
            atual, linhas = l[0], []
        linhas.append(list(l[1:]))
    if atual is not None:
        estados.append((atual, _hash(linhas)))
    db.execute("DELETE FROM peca_veiculo_estado")
    db.executemany("INSERT INTO peca_veiculo_estado (id_peca, hash) VALUES (?, ?)", estados)
    alterados = atualizar_hashes_modelos(db)
    gravar_meta(db, "veiculos_em", agora())
    db.commit()
    return {"pecas_ligadas": len(estados), "linhas_peca_veiculo": total, "modelos_alterados": alterados}


def ligar(db, caminho_compat, montadoras):
    arvore = Arvore(db)
    r = dict(ligar_versao(db, arvore, caminho_compat))
    r_modelo, sem_modelo = ligar_modelo(db, arvore, montadoras)
    r.update(r_modelo)
    r.update(fechar(db))
    return r, sem_modelo
