"""
lotus.py  -  LOTUS (natural products occurrence database, Wikidata)

Módulo usado pela etapa "bioativos" (cruzar_especies_bioativos.py).

O que o LOTUS acrescenta:
  a REFERÊNCIA bibliográfica (DOI) de cada par composto x organismo.
  O COCONUT 2.0 já incorpora os pares do LOTUS, mas sem dizer em qual
  artigo cada composto foi relatado naquela planta.

Dados: export "frozen" do LOTUS (CC0), publicado no Zenodo e atualizado
periodicamente - uma linha por trio composto (InChIKey) x organismo x
referência. A versão mais recente é descoberta pela API do Zenodo.
  https://zenodo.org/records/19360665
Colunas usadas: structure_inchikey, organism_name, reference_doi
(e structure_wikidata / manual_validation, se presentes).
"""

import gzip
import os

import caminhos as _C

import pandas as pd
import requests

from config_pipeline import carregar_config_bioativos, trocar

PASTA_DADOS = _C.dados("bioativos")
ARQUIVO = os.path.join(PASTA_DADOS, "lotus_frozen.csv.gz")
MARCADOR = os.path.join(PASTA_DADOS, "lotus_versao.txt")
ZENODO_REGISTRO = "19360665"           # LOTUS frozen, v11 (abril/2026)
URL_FIXA = f"https://zenodo.org/records/{ZENODO_REGISTRO}/files/260413_frozen.csv.gz?download=1"
UA = {"User-Agent": "Pipeline-Prospeccao-Plantas-Bioativos/2.0"}
MAX_REFERENCIAS = 10                   # DOIs listados por par planta x composto

COLUNAS_LOTUS = ["referencias_lotus"]


def cfg() -> dict:
    return carregar_config_bioativos()


def arquivos() -> list:
    return [ARQUIVO, MARCADOR]


def url_recente() -> str | None:
    """Endereço do arquivo *_frozen.csv.gz na versão mais recente do registro."""
    try:
        r = requests.get(f"https://zenodo.org/api/records/{ZENODO_REGISTRO}/versions/latest",
                         headers=UA, timeout=60)
        r.raise_for_status()
        for f in r.json().get("files", []):
            nome = f.get("key", "")
            if nome.endswith("_frozen.csv.gz"):
                return f["links"]["self"]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def baixar():
    """Baixa o export do LOTUS, se ainda não estiver presente."""
    os.makedirs(PASTA_DADOS, exist_ok=True)
    if os.path.exists(ARQUIVO) and os.path.getsize(ARQUIVO) > 0:
        print("LOTUS: já baixado")
        return
    candidatos = [cfg().get("lotus_url") or None, url_recente(), URL_FIXA]
    erros = []
    for url in [u for u in candidatos if u]:
        print(f"LOTUS: baixando {url} ...")
        tmp = ARQUIVO + ".parcial"
        try:
            with requests.get(url, headers=UA, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for bloco in r.iter_content(1 << 20):
                        f.write(bloco)
            with open(tmp, "rb") as f:
                if f.read(2) != b"\x1f\x8b":
                    raise RuntimeError("o arquivo baixado não é .gz")
            trocar(tmp, ARQUIVO)
            with open(MARCADOR, "w", encoding="utf-8") as f:
                f.write(url)
            return
        except (requests.RequestException, RuntimeError) as e:
            erros.append(f"{url}: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)
    raise RuntimeError("LOTUS: não foi possível baixar. " + " | ".join(erros) +
                       f" | Alternativa: baixe pelo navegador em https://zenodo.org/records/"
                       f"{ZENODO_REGISTRO} o arquivo *_frozen.csv.gz e salve como "
                       f"{os.path.abspath(ARQUIVO)}")


def _col(colunas, *candidatos):
    mapa = {c.lower(): c for c in colunas}
    for c in candidatos:
        if c.lower() in mapa:
            return mapa[c.lower()]
    for c in candidatos:   # nome parcial (ex.: 'structure_inchikey' em versões futuras)
        for k, v in mapa.items():
            if c.lower() in k:
                return v
    return None


def cruzar_lotus(casar, especies: dict, generos: dict) -> pd.DataFrame:
    """Linhas no formato da etapa bioativos, base = 'LOTUS', com a coluna
    referencias_lotus (DOIs dos artigos que relatam o par)."""
    vazio = pd.DataFrame(columns=["especie_normalizada", "base", "composto_id", "composto_nome",
                                  "composto_inchikey", "atividade_ou_alvo"] + COLUNAS_LOTUS)
    with gzip.open(ARQUIVO, "rt", encoding="utf-8", errors="replace") as f:
        primeira = f.readline()
    sep = "\t" if primeira.count("\t") > primeira.count(",") else ","
    cab = [c.strip().strip('"') for c in primeira.rstrip("\n").split(sep)]
    c_ik = _col(cab, "structure_inchikey", "inchikey")
    c_org = _col(cab, "organism_name", "organism")
    c_doi = _col(cab, "reference_doi", "doi")
    c_wd = _col(cab, "structure_wikidata")
    # estrutura, nome e CID: só completam o que o COCONUT e o NPASS não têm
    # (na consolidação, essas duas bases vêm primeiro)
    exatas = {c.lower(): c for c in cab}
    c_smi = exatas.get("structure_smiles") or exatas.get("structure_smiles_2d")
    c_nome = exatas.get("structure_nametraditional") or exatas.get("structure_nameiupac")
    c_cid = exatas.get("structure_cid")
    if not c_ik or not c_org:
        raise RuntimeError(f"LOTUS: colunas de InChIKey/organismo não encontradas ({list(cab)})")
    usar = [c for c in dict.fromkeys([c_ik, c_org, c_doi, c_wd, c_smi, c_nome, c_cid]) if c]
    df = pd.read_csv(ARQUIVO, sep=sep, usecols=usar, dtype=str)
    df = df.dropna(subset=[c_ik, c_org])

    orgs = pd.Series(df[c_org].unique())
    casados = dict(zip(orgs, casar(orgs, especies, generos)))
    df["_especie"] = df[c_org].map(casados)
    df = df[df["_especie"] != ""]
    print(f"  LOTUS: {df['_especie'].nunique()} táxons-alvo encontrados")
    if df.empty:
        return vazio

    linhas = []
    for (especie, ik), g in df.groupby(["_especie", c_ik], sort=False):
        dois = []
        if c_doi:
            for d in g[c_doi].dropna():
                for parte in str(d).split("|"):
                    parte = parte.strip()
                    if parte and parte not in dois:
                        dois.append(parte)
        texto = None
        if dois:
            extra = f" (+{len(dois) - MAX_REFERENCIAS})" if len(dois) > MAX_REFERENCIAS else ""
            texto = "DOI " + ", ".join(dois[:MAX_REFERENCIAS]) + extra
        def primeiro(c):
            if not c or not g[c].notna().any():
                return None
            v = str(g[c].dropna().iloc[0]).strip()
            return v or None
        wd = primeiro(c_wd)
        cid = primeiro(c_cid)
        if cid:
            cid = cid.split("|")[0].split(".")[0].strip()
            cid = cid if cid.isdigit() and int(cid) > 0 else None
        linhas.append({
            "especie_normalizada": especie, "base": "LOTUS",
            "composto_id": f"LOTUS:{str(wd).rsplit('/', 1)[-1]}" if wd else f"LOTUS:{ik}",
            "composto_nome": primeiro(c_nome), "composto_inchikey": ik.strip().upper(),
            "composto_smiles": primeiro(c_smi), "pubchem_cid": cid,
            "atividade_ou_alvo": None, "referencias_lotus": texto,
        })
    res = pd.DataFrame(linhas)
    print(f"  LOTUS: {len(res)} pares espécie x composto; "
          f"{res['referencias_lotus'].notna().sum()} com DOI; "
          f"{res['composto_smiles'].notna().sum()} com SMILES")
    return res
