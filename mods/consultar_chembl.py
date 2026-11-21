"""
consultar_chembl.py  -  ETAPA "chembl" (complemento ao PubMed)

Para cada composto de especies_com_compostos_bioativos.csv, busca no
ChEMBL as atividades biológicas MEDIDAS em ensaios (IC50, Ki, MIC, % de
inibição...), identificando o composto pelo InChIKey (correspondência
exata de estrutura, sem depender de nome ou sinônimo).

As atividades são ligadas às atividades do input.txt ([termos_pubmed]) pelo
nome do alvo e pela descrição do ensaio. Para isso, os termos são reduzidos
ao "núcleo": "tyrosinase inhibit*" -> tyrosinase, "UVB-induced" -> UVB,
"anti-glycation" -> glycation. Com [termos_pubmed] vazio, cada alvo ativo
vira uma atividade ("Alvo (tipo de medida)").

Um registro conta como ATIVO se:
  - pchembl_value >= pchembl_minimo (5 = 10 µM; 6 = 1 µM), ou
  - o ChEMBL o marca como ativo (activity_comment "active"),
e não tem alerta de validade (data_validity_comment).

Opcional (prever_por_similaridade = true): para compostos SEM dado no
ChEMBL, busca moléculas parecidas (similaridade >= similaridade_minima, a
partir do SMILES) e informa as atividades medidas DELAS, como PREVISÃO.
Previsões são hipóteses, não evidências: ficam numa coluna separada, com a
molécula vizinha e a similaridade que as sustentam.

Estereoisômeros (estereoisomeros = true): se o InChIKey completo não
existe no ChEMBL, procura moléculas com a mesma CONECTIVIDADE (os 14
primeiros caracteres do InChIKey) - em geral o mesmo composto registrado
com outra configuração espacial. O resultado é marcado como estereoisômero.

Para localizar os compostos, a etapa baixa uma vez o arquivo oficial de
estruturas do ChEMBL (chemreps, ~300 MB, em dados/chembl/) e compara
localmente; se o download falhar, consulta a API (mais lento).

Fonte de cada ensaio: o documento de origem no ChEMBL é consultado e o
PMID (e DOI, ano, revista) entra nas evidências e no resumo.

Isto é um COMPLEMENTO à etapa "pubmed" (que lê os artigos com o modelo):
a etapa "pubmed" junta estas colunas a especies_atividades.csv.

Saídas:
  compostos_chembl.csv   InChIKey, chembl_id, correspondencia_chembl,
                         atividades_chembl [+ atividades_previstas_chembl]
  evidencias_chembl.csv  um registro de ensaio por linha, com PMID
"""

import gzip
import json
import os

import caminhos as _C
import re
import sys
import time
from urllib.parse import quote

import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry

from config_pipeline import carregar_config_chembl, gravar_csv, ler_input, trocar

try:
    from tqdm.auto import tqdm
except ImportError:
    def tqdm(iteravel, **_):
        return iteravel

ENTRADA = "especies_com_compostos_bioativos.csv"
SAIDA = "compostos_chembl.csv"
SAIDA_EVIDENCIAS = "evidencias_chembl.csv"
CACHE_MOLECULAS = _C.cache("cache_chembl_moleculas.jsonl")
CACHE_ATIVIDADES = _C.cache("cache_chembl_atividades.jsonl")
CACHE_SIMILARES = _C.cache("cache_chembl_similares.jsonl")
CACHE_ESTEREO = _C.cache("cache_chembl_estereo.jsonl")
CACHE_DOCUMENTOS = _C.cache("cache_chembl_documentos.jsonl")
PASTA_DADOS = _C.dados("chembl")
PAGINA_CHEMBL = "https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/"
MAX_ESTEREO = 5         # estereoisômeros considerados por composto
LOTE_DOCUMENTOS = 50

API = "https://www.ebi.ac.uk/chembl/api/data/"
RAIZ = "https://www.ebi.ac.uk"
PAUSA = 0.2
LOTE_MOLECULAS = 50
LOTE_ATIVIDADES = 20
MAX_VIZINHOS = 5

CFG = carregar_config_chembl()
FOCO = ler_input()["termos_pubmed"]
RE_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")

CAMPOS_ATIVIDADE = ("molecule_chembl_id,target_pref_name,target_organism,target_chembl_id,"
                    "assay_description,assay_type,standard_type,standard_relation,"
                    "standard_value,standard_units,pchembl_value,activity_comment,"
                    "data_validity_comment,document_chembl_id")

# palavras que descrevem o efeito, não o alvo: saem do "núcleo" do termo
GENERICAS = re.compile(r"^(inhibit\w*|activat\w*|induc\w*|effect\w*|activit\w*|"
                       r"synthesis|potential|assay\w*)$", re.I)

STATUS_SEM_INCHIKEY = "sem InChIKey válido"
STATUS_NAO_ENCONTRADO = "composto não encontrado no ChEMBL"
STATUS_SEM_ATIVO = "no ChEMBL, sem atividade do input medida como ativa"
STATUS_PENDENTE = "consulta pendente (rode de novo)"


# =============================================================================
# Utilidades
# =============================================================================
def carregar_cache(caminho, chave):
    dados = {}
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                try:
                    item = json.loads(linha)
                    dados[item[chave]] = item
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
    return dados


def gravar_cache(caminho, item):
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def criar_sessao():
    s = requests.Session()
    s.headers.update({"User-Agent": "Pipeline-Prospeccao-Plantas-Bioativos/2.0",
                      "Accept": "application/json"})
    retry = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def obter(sessao, url, params=None):
    """GET em JSON; None em falha."""
    try:
        r = sessao.get(url, params=params, timeout=120)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None
    finally:
        time.sleep(PAUSA)


def paginar(sessao, url, params, chave_lista):
    """Junta todas as páginas de um recurso do ChEMBL; None em falha."""
    itens, dados = [], obter(sessao, url, params)
    while True:
        if dados is None:
            return None
        itens += dados.get(chave_lista, [])
        proxima = (dados.get("page_meta") or {}).get("next")
        if not proxima:
            return itens
        dados = obter(sessao, RAIZ + proxima)


def inchikey_valido(v):
    if not isinstance(v, str):
        return None
    v = v.strip().upper()
    return v if RE_INCHIKEY.match(v) else None


# =============================================================================
# Ligação com as atividades do input
# =============================================================================
def nucleo(termo: str) -> str:
    t = re.sub(r"\[[^\]]*\]", "", termo).replace('"', "").strip()
    palavras = [p for p in t.split() if not GENERICAS.match(p.rstrip("*"))]
    t = " ".join(palavras) or t
    t = re.sub(r"-(induced|mediated|dependent)\b", "", t, flags=re.I)
    t = re.sub(r"^anti-", "", t, flags=re.I)
    return t.strip()


def regex_termo(termo: str):
    n = nucleo(termo)
    if len(n.replace("*", "")) < 3:
        return None
    corpo = (re.escape(n).replace(r"\*", r"\w*").replace(r"\-", "\x00")
             .replace(r"\ ", r"[\s\-]+").replace("\x00", r"[\s\-]?"))
    return re.compile(rf"(?<![A-Za-z0-9]){corpo}(?![A-Za-z0-9])", re.I)


PADROES_FOCO = {rotulo: [r for r in map(regex_termo, termos) if r]
                for rotulo, termos in FOCO.items()}


def eh_ativo(reg: dict) -> bool:
    if reg.get("data_validity_comment"):
        return False
    try:
        if reg.get("pchembl_value") is not None and float(reg["pchembl_value"]) >= CFG["pchembl_minimo"]:
            return True
    except (TypeError, ValueError):
        pass
    comentario = str(reg.get("activity_comment") or "").lower()
    return comentario in {"active", "ativo"} or (comentario.startswith("active")
                                                  and "inactive" not in comentario)


def rotulos_do_registro(reg: dict) -> list:
    alvo = reg.get("target_pref_name") or ""
    if not FOCO:
        tipo = reg.get("standard_type") or "atividade"
        return [f"{alvo} ({tipo})"] if alvo else []
    texto = f"{alvo} {reg.get('assay_description') or ''}"
    return [r for r, padroes in PADROES_FOCO.items() if any(p.search(texto) for p in padroes)]


def descrever(reg: dict) -> str:
    valor = reg.get("standard_value")
    medida = reg.get("standard_type") or ""
    if valor not in (None, ""):
        try:
            v = float(valor)
            valor = f"{v:.0f}" if abs(v) >= 100 else f"{v:.3g}"
        except (TypeError, ValueError):
            pass
        medida += f" {reg.get('standard_relation') or '='} {valor} {reg.get('standard_units') or ''}"
    elif reg.get("activity_comment"):
        medida += f" ({reg['activity_comment']})"
    return f"{reg.get('target_pref_name') or 'alvo não informado'}, {medida.strip()}"


def resumir(registros: list) -> tuple[dict, list]:
    """{rótulo: (melhor registro, nº de registros ativos)}, [(rótulo, registro)]"""
    por_rotulo, pares = {}, []
    for reg in registros:
        if not eh_ativo(reg):
            continue
        for rotulo in rotulos_do_registro(reg):
            pares.append((rotulo, reg))
            melhor, n = por_rotulo.get(rotulo, (None, 0))
            p_novo = float(reg.get("pchembl_value") or 0)
            p_melhor = float((melhor or {}).get("pchembl_value") or 0)
            por_rotulo[rotulo] = (reg if melhor is None or p_novo > p_melhor else melhor, n + 1)
    return por_rotulo, pares


def pmids_de(registros: list, docs: dict) -> list:
    pmids = {str(docs.get(r.get("document_chembl_id"), {}).get("pmid") or "") for r in registros}
    return sorted((p for p in pmids if p.isdigit()), key=int)


def formatar(por_rotulo: dict, pares: list, docs: dict, prefixo: str = "") -> str:
    ordem = sorted(por_rotulo.items(), key=lambda kv: (-kv[1][1], kv[0]))
    partes = []
    for r, (reg, n) in ordem:
        pmids = pmids_de([g for rr, g in pares if rr == r], docs)
        fonte = ""
        if pmids:
            fonte = "; PMID " + ", ".join(pmids[:8]) + (" ..." if len(pmids) > 8 else "")
        marca = f"{prefixo}{reg.get('molecule_chembl_id')}: " if prefixo else ""
        partes.append(f"{r} ({marca}{descrever(reg)}, {n} registro{'s' if n > 1 else ''}{fonte})")
    return "; ".join(partes)


# =============================================================================
# Consultas ao ChEMBL
# =============================================================================
def moleculas_por_inchikey(sessao, inchikeys: list) -> dict:
    """{inchikey: chembl_id | None}. Em lote; o que falhar é tentado um a um."""
    cache = carregar_cache(CACHE_MOLECULAS, "inchikey")
    pendentes = [ik for ik in inchikeys if ik not in cache]
    print(f"ChEMBL: localizando {len(pendentes)} composto(s) pelo InChIKey "
          f"({len(inchikeys) - len(pendentes)} em cache)")
    lotes = [pendentes[i:i + LOTE_MOLECULAS] for i in range(0, len(pendentes), LOTE_MOLECULAS)]
    for lote in tqdm(lotes, desc="ChEMBL moléculas"):
        itens = paginar(sessao, API + "molecule.json", {
            "molecule_structures__standard_inchi_key__in": ",".join(lote),
            "only": "molecule_chembl_id,molecule_structures", "limit": 1000}, "molecules")
        if itens is None:      # lote recusado: um a um
            for ik in lote:
                dados = obter(sessao, API + f"molecule/{ik}.json",
                              {"only": "molecule_chembl_id"})
                if dados is None:
                    continue
                cache[ik] = {"inchikey": ik, "chembl_id": dados.get("molecule_chembl_id")}
                gravar_cache(CACHE_MOLECULAS, cache[ik])
            continue
        achados = {}
        for m in itens:
            ik = inchikey_valido(((m.get("molecule_structures") or {}).get("standard_inchi_key")))
            if ik in lote and ik not in achados:
                achados[ik] = m.get("molecule_chembl_id")
        for ik in lote:
            cache[ik] = {"inchikey": ik, "chembl_id": achados.get(ik)}
            gravar_cache(CACHE_MOLECULAS, cache[ik])
    return {ik: cache[ik]["chembl_id"] for ik in inchikeys if ik in cache}


def atividades_por_molecula(sessao, chembl_ids: list) -> dict:
    """{chembl_id: [registros]} (só os campos usados)."""
    cache = carregar_cache(CACHE_ATIVIDADES, "chembl_id")
    pendentes = [c for c in chembl_ids if c not in cache]
    if pendentes:
        print(f"ChEMBL: baixando atividades de {len(pendentes)} molécula(s) "
              f"({len(chembl_ids) - len(pendentes)} em cache)")
    lotes = [pendentes[i:i + LOTE_ATIVIDADES] for i in range(0, len(pendentes), LOTE_ATIVIDADES)]
    for lote in tqdm(lotes, desc="ChEMBL atividades"):
        itens = paginar(sessao, API + "activity.json", {
            "molecule_chembl_id__in": ",".join(lote), "only": CAMPOS_ATIVIDADE,
            "limit": 1000}, "activities")
        if itens is None:
            continue
        por_mol = {c: [] for c in lote}
        for a in itens:
            por_mol.setdefault(a.get("molecule_chembl_id"), []).append(
                {k: a.get(k) for k in CAMPOS_ATIVIDADE.split(",")})
        for c in lote:
            cache[c] = {"chembl_id": c, "atividades": por_mol.get(c, [])}
            gravar_cache(CACHE_ATIVIDADES, cache[c])
    return {c: cache[c]["atividades"] for c in chembl_ids if c in cache}


ARQUIVO_ESTRUTURAS = os.path.join(PASTA_DADOS, "chembl_chemreps.txt.gz")
CACHES_CHEMBL = [CACHE_MOLECULAS, CACHE_ATIVIDADES, CACHE_ESTEREO, CACHE_DOCUMENTOS,
                 CACHE_SIMILARES]


def baixar_estruturas(sessao) -> str | None:
    """Arquivo chemreps do ChEMBL (chembl_id + InChIKey de todas as
    moléculas). None se não for possível baixar."""
    os.makedirs(PASTA_DADOS, exist_ok=True)
    destino = os.path.join(PASTA_DADOS, "chembl_chemreps.txt.gz")
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return destino
    url = CFG["estruturas_url"]
    try:
        if not url:
            html = sessao.get(PAGINA_CHEMBL, timeout=60).text
            nomes = sorted(set(re.findall(r"chembl_\d+_chemreps\.txt\.gz", html)))
            if not nomes:
                raise RuntimeError("arquivo chemreps não encontrado na página do ChEMBL")
            url = PAGINA_CHEMBL + nomes[-1]
        print(f"ChEMBL: baixando o arquivo de estruturas ({url}) - só na primeira vez...")
        tmp = destino + ".parcial"
        with sessao.get(url, stream=True, timeout=900) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for bloco in r.iter_content(chunk_size=1 << 20):
                    f.write(bloco)
        trocar(tmp, destino)
        return destino
    except Exception as e:
        print(f"  AVISO: não foi possível baixar as estruturas do ChEMBL ({e}) - "
              "usando a API, mais lenta.")
        return None


def localizar_local(caminho: str, inchikeys: list) -> tuple[dict, dict]:
    """({inchikey: chembl_id} exatos, {inchikey: [chembl_ids]} com a mesma
    conectividade), comparando com o arquivo chemreps."""
    pedidos = set(inchikeys)
    blocos = {ik[:14] for ik in inchikeys}
    exatos, por_bloco = {}, {}
    print("ChEMBL: comparando InChIKeys com o arquivo de estruturas...")
    with gzip.open(caminho, "rt", encoding="utf-8", errors="replace") as f:
        for bloco in pd.read_csv(f, sep="\t", usecols=["chembl_id", "standard_inchi_key"],
                                 dtype=str, chunksize=500_000):
            bloco = bloco.dropna()
            for cid, ik in zip(bloco["chembl_id"], bloco["standard_inchi_key"]):
                if ik in pedidos:
                    exatos.setdefault(ik, cid)
                elif ik[:14] in blocos:
                    por_bloco.setdefault(ik[:14], []).append(cid)
    estereo = {ik: sorted(por_bloco[ik[:14]])[:MAX_ESTEREO]
               for ik in inchikeys if ik not in exatos and ik[:14] in por_bloco}
    return exatos, estereo


def estereo_api(sessao, inchikeys: list) -> dict:
    """{inchikey: [chembl_ids]} com a mesma conectividade, pela API (1 por composto)."""
    cache = carregar_cache(CACHE_ESTEREO, "inchikey")
    pendentes = [ik for ik in inchikeys if ik not in cache]
    if pendentes:
        print(f"ChEMBL: procurando estereoisômeros de {len(pendentes)} composto(s) pela API "
              f"({len(inchikeys) - len(pendentes)} em cache)")
    for ik in tqdm(pendentes, desc="ChEMBL estereoisômeros"):
        itens = paginar(sessao, API + "molecule.json", {
            "molecule_structures__standard_inchi_key__startswith": ik[:14],
            "only": "molecule_chembl_id", "limit": MAX_ESTEREO}, "molecules")
        if itens is None:
            continue
        ids = sorted({m.get("molecule_chembl_id") for m in itens if m.get("molecule_chembl_id")})
        cache[ik] = {"inchikey": ik, "ids": ids[:MAX_ESTEREO]}
        gravar_cache(CACHE_ESTEREO, cache[ik])
    return {ik: cache[ik]["ids"] for ik in inchikeys if cache.get(ik, {}).get("ids")}


def documentos(sessao, doc_ids: list) -> dict:
    """{document_chembl_id: {pmid, doi, ano, revista, titulo}}"""
    cache = carregar_cache(CACHE_DOCUMENTOS, "doc")
    pendentes = [d for d in doc_ids if d and d not in cache]
    if pendentes:
        print(f"ChEMBL: buscando a fonte (PMID) de {len(pendentes)} documento(s) "
              f"({len(doc_ids) - len(pendentes)} em cache)")
    lotes = [pendentes[i:i + LOTE_DOCUMENTOS] for i in range(0, len(pendentes), LOTE_DOCUMENTOS)]
    for lote in tqdm(lotes, desc="ChEMBL documentos"):
        itens = paginar(sessao, API + "document.json", {
            "document_chembl_id__in": ",".join(lote), "limit": 1000,
            "only": "document_chembl_id,pubmed_id,doi,year,journal,title"}, "documents")
        if itens is None:
            continue
        achados = {d.get("document_chembl_id"): d for d in itens}
        for doc in lote:
            d = achados.get(doc, {})
            pmid = str(d.get("pubmed_id") or "").split(".")[0]
            cache[doc] = {"doc": doc, "pmid": pmid if pmid.isdigit() else None, "doi": d.get("doi"),
                          "ano": d.get("year"), "revista": d.get("journal"),
                          "titulo": d.get("title")}
            gravar_cache(CACHE_DOCUMENTOS, cache[doc])
    return {d: cache[d] for d in doc_ids if d in cache}


def similares(sessao, inchikey: str, smiles: str, cache: dict) -> list | None:
    if inchikey in cache:
        return cache[inchikey]["vizinhos"]
    dados = obter(sessao, API + f"similarity/{quote(smiles, safe='')}/{CFG['similaridade_minima']}.json",
                  {"only": "molecule_chembl_id,pref_name,similarity", "limit": MAX_VIZINHOS})
    if dados is None:
        return None
    vizinhos = [{"chembl_id": m.get("molecule_chembl_id"), "nome": m.get("pref_name"),
                 "similaridade": float(m.get("similarity") or 0)}
                for m in dados.get("molecules", [])]
    cache[inchikey] = {"inchikey": inchikey, "vizinhos": vizinhos}
    gravar_cache(CACHE_SIMILARES, cache[inchikey])
    return vizinhos


# =============================================================================
def main():
    colunas = ["InChIKey", "chembl_id", "correspondencia_chembl", "atividades_chembl"] + \
        (["atividades_previstas_chembl"] if CFG["prever_por_similaridade"] else [])
    if not CFG["ativar"]:
        gravar_csv(pd.DataFrame(columns=colunas), SAIDA)
        print("[chembl] ativar = false - etapa desligada no input.txt.")
        return
    if not os.path.exists(ENTRADA):
        sys.exit(f"{ENTRADA} não encontrado. Rode a etapa 'bioativos' primeiro.")
    df = pd.read_csv(ENTRADA, dtype=str)
    df["_ik"] = df["composto_inchikey"].map(inchikey_valido)
    if "composto_smiles" not in df:
        df["composto_smiles"] = None
    compostos = (df.dropna(subset=["_ik"]).groupby("_ik")
                 .agg(nome=("composto_nome", "first"), smiles=("composto_smiles", "first"))
                 .reset_index())
    print(f"{len(compostos)} composto(s) com InChIKey "
          f"({df['_ik'].isna().sum()} linha(s) sem InChIKey ficam de fora)")
    if FOCO:
        print("Atividades do input -> núcleos procurados no alvo/ensaio do ChEMBL:")
        for rotulo, termos in FOCO.items():
            print(f"  {rotulo}: {', '.join(sorted({nucleo(t) for t in termos}))}")
    else:
        print("[termos_pubmed] vazio: todos os alvos com atividade ativa são listados.")

    # --- 1. localizar os compostos (exato e, opcionalmente, estereoisômeros) ---
    sessao = criar_sessao()
    iks = compostos["_ik"].tolist()
    arquivo = baixar_estruturas(sessao)
    if arquivo:
        exatos, estereo = localizar_local(arquivo, iks)
        chembl = {ik: exatos.get(ik) for ik in iks}
    else:
        chembl = moleculas_por_inchikey(sessao, iks)
        estereo = {}
        if CFG["estereoisomeros"]:
            sem = [ik for ik in iks if ik in chembl and not chembl[ik]]
            estereo = estereo_api(sessao, sem)
    if not CFG["estereoisomeros"]:
        estereo = {}
    n_exato = sum(1 for v in chembl.values() if v)
    print(f"{n_exato} composto(s) encontrados no ChEMBL pelo InChIKey completo"
          + (f"; {len(estereo)} outro(s) por estereoisômero (mesma conectividade)"
             if CFG["estereoisomeros"] else ""))

    ids = sorted({c for c in chembl.values() if c} | {c for v in estereo.values() for c in v})
    atividades = atividades_por_molecula(sessao, ids)

    # --- 2. resumir por composto --------------------------------------------
    linhas, resumos, todos_pares = [], {}, []
    for _, c in compostos.iterrows():
        ik = c["_ik"]
        linha = {"InChIKey": ik, "chembl_id": chembl.get(ik), "correspondencia_chembl": ""}
        if ik not in chembl:
            linha["atividades_chembl"] = STATUS_PENDENTE
        elif chembl[ik]:
            linha["correspondencia_chembl"] = "exata"
            if chembl[ik] not in atividades:
                linha["atividades_chembl"] = STATUS_PENDENTE
            else:
                por_rotulo, pares = resumir(atividades[chembl[ik]])
                resumos[ik] = (por_rotulo, pares, "")
                todos_pares += [(ik, c["nome"], chembl[ik], "exata", r, g) for r, g in pares]
        elif ik in estereo:
            ids_e = estereo[ik]
            linha["chembl_id"] = "; ".join(ids_e)
            linha["correspondencia_chembl"] = "estereoisômero (mesma conectividade)"
            regs = [dict(g, molecule_chembl_id=g.get("molecule_chembl_id")) for m in ids_e
                    for g in atividades.get(m, [])]
            if not all(m in atividades for m in ids_e):
                linha["atividades_chembl"] = STATUS_PENDENTE
            else:
                por_rotulo, pares = resumir(regs)
                resumos[ik] = (por_rotulo, pares, "estereoisômero ")
                todos_pares += [(ik, c["nome"], g.get("molecule_chembl_id"), "estereoisômero", r, g)
                                for r, g in pares]
        else:
            linha["atividades_chembl"] = STATUS_NAO_ENCONTRADO
        linhas.append(linha)

    # --- 3. previsão por similaridade (opcional) --------------------------
    previsoes = {}
    if CFG["prever_por_similaridade"]:
        cache_sim = carregar_cache(CACHE_SIMILARES, "inchikey")
        sem_dado = {ik for ik in iks if ik not in resumos or not resumos[ik][0]}
        alvos = [l for l in linhas if l["InChIKey"] in sem_dado
                 and l.get("atividades_chembl") != STATUS_PENDENTE]
        smiles = dict(zip(compostos["_ik"], compostos["smiles"]))
        print(f"\nPrevisão por similaridade (>= {CFG['similaridade_minima']}%): "
              f"{len(alvos)} composto(s) sem atividade medida no ChEMBL")
        vizinhos_por_ik = {}
        for l in tqdm(alvos, desc="ChEMBL similaridade"):
            smi = smiles.get(l["InChIKey"])
            if isinstance(smi, str) and smi.strip():
                v = similares(sessao, l["InChIKey"], smi.strip(), cache_sim)
                if v is not None:
                    proprios = set(str(l["chembl_id"] or "").split("; "))
                    vizinhos_por_ik[l["InChIKey"]] = [x for x in v if x["chembl_id"] not in proprios]
        ids_viz = sorted({x["chembl_id"] for v in vizinhos_por_ik.values() for x in v})
        ativ_viz = atividades_por_molecula(sessao, ids_viz) if ids_viz else {}
        nomes = dict(zip(compostos["_ik"], compostos["nome"]))
        for l in alvos:
            viz = vizinhos_por_ik.get(l["InChIKey"])
            if viz is None:
                previsoes[l["InChIKey"]] = "sem SMILES ou consulta pendente"
                continue
            melhores = {}
            for x in sorted(viz, key=lambda x: -x["similaridade"]):
                por_rotulo, pares = resumir(ativ_viz.get(x["chembl_id"], []))
                for rotulo, (reg, n) in por_rotulo.items():
                    if rotulo not in melhores:   # vizinho mais parecido vence
                        melhores[rotulo] = (x, reg, n)
                todos_pares += [(l["InChIKey"], nomes.get(l["InChIKey"]), x["chembl_id"],
                                 f"prevista (similaridade {x['similaridade']:.0f}%)", r, g)
                                for r, g in pares]
            previsoes[l["InChIKey"]] = melhores

    # --- 4. fonte de cada ensaio (PMID) --------------------------------------
    docs = documentos(sessao, sorted({g.get("document_chembl_id") for *_, g in todos_pares
                                      if g.get("document_chembl_id")}))

    for l in linhas:
        ik = l["InChIKey"]
        if ik in resumos:
            por_rotulo, pares, prefixo = resumos[ik]
            l["atividades_chembl"] = formatar(por_rotulo, pares, docs, prefixo) or STATUS_SEM_ATIVO
        if CFG["prever_por_similaridade"]:
            p = previsoes.get(ik, "")
            if isinstance(p, dict):
                textos = []
                for r, (x, reg, n) in sorted(p.items()):
                    pm = pmids_de([reg], docs)
                    textos.append(f"{r} (via {x['chembl_id']}{' ' + x['nome'] if x['nome'] else ''}, "
                                  f"similaridade {x['similaridade']:.0f}%: {descrever(reg)}"
                                  + (f"; PMID {pm[0]}" if pm else "") + ")")
                p = "; ".join(textos) or "nenhum vizinho com atividade do input"
            l["atividades_previstas_chembl"] = p

    evidencias = []
    for ik, nome, molecula, tipo, rotulo, g in todos_pares:
        d = docs.get(g.get("document_chembl_id"), {})
        evidencias.append({"InChIKey": ik, "composto": nome, "atividade": rotulo,
                           "correspondencia": tipo, "molecula_ensaiada": molecula,
                           "alvo": g.get("target_pref_name"), "organismo_alvo": g.get("target_organism"),
                           "descricao_ensaio": g.get("assay_description"),
                           "tipo_ensaio": g.get("assay_type"), "medida": g.get("standard_type"),
                           "relacao": g.get("standard_relation"), "valor": g.get("standard_value"),
                           "unidade": g.get("standard_units"), "pchembl": g.get("pchembl_value"),
                           "comentario": g.get("activity_comment"),
                           "PMID": d.get("pmid"), "DOI": d.get("doi"), "ano": d.get("ano"),
                           "revista": d.get("revista"),
                           "documento_chembl": g.get("document_chembl_id")})

    saida = pd.DataFrame(linhas, columns=colunas)
    gravar_csv(pd.DataFrame(evidencias), SAIDA_EVIDENCIAS)
    gravar_csv(saida, SAIDA)          # por último: marca a etapa como concluída
    com_ativ = ~saida["atividades_chembl"].isin(
        [STATUS_NAO_ENCONTRADO, STATUS_SEM_ATIVO, STATUS_PENDENTE])
    n_est = (com_ativ & (saida["correspondencia_chembl"] != "exata")).sum()
    print(f"\nConcluído: {SAIDA} ({len(saida)} compostos)")
    print(f"  {com_ativ.sum()} composto(s) com atividade do input medida como ativa no ChEMBL"
          + (f" ({n_est} via estereoisômero)" if n_est else ""))
    com_pmid = sum(1 for e in evidencias if e["PMID"])
    if evidencias:
        print(f"  {com_pmid} de {len(evidencias)} registro(s) de ensaio com PMID da fonte")
    pend = (saida["atividades_chembl"] == STATUS_PENDENTE).sum()
    if pend:
        print(f"  {pend} consulta(s) pendente(s) por falha de rede - rode a etapa de novo")
    print(f"  registros de ensaio em {SAIDA_EVIDENCIAS}")


if __name__ == "__main__":
    main()
