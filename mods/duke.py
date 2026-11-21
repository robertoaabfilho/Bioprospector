"""
duke.py  -  Dr. Duke's Phytochemical and Ethnobotanical Databases (USDA)

Módulo usado pela etapa "bioativos" (cruzar_especies_bioativos.py).

O que o Dr. Duke acrescenta ao COCONUT/NPASS:
  - a PARTE DA PLANTA em que cada composto foi encontrado (folha, casca...);
  - o TEOR (ppm), quando registrado;
  - as ATIVIDADES BIOLÓGICAS atribuídas a cada composto na literatura.

Dados: export oficial em CSV (domínio público, CC0), publicado no Ag Data
Commons do USDA:
  https://agdatacommons.nal.usda.gov/articles/dataset/Dr_Duke_s_Phytochemical_and_Ethnobotanical_Databases/24660351
Tabelas usadas (nomes do export):
  FNFTAX        táxons (FNFNUM, GENUS, SPECIES ...)
  FARMACY_NEW   planta x composto x parte x teor (FNFNUM, CHEM, PPCO, AMT_LO, AMT_HI)
  PARTS         códigos das partes da planta (PPCO -> PPNA)
  AGGREGAC      composto x atividade (CHEM, ACTIVITY, DOSAGE ...)
  CHEMICALS     composto (CHEM, nº CAS), opcional

O Dr. Duke não traz InChIKey: os compostos são identificados pelo nome
(ex.: CAFFEIC-ACID). O InChIKey é obtido no PubChem pelo nº CAS (quando
existe) ou pelo nome, com cache em cache_pubchem_duke.jsonl. Com o InChIKey,
o composto se une ao mesmo composto vindo do COCONUT/NPASS.
"""

import json
import os

import caminhos as _C
import re
import time
import zipfile
from urllib.parse import quote

import pandas as pd
import requests

from config_pipeline import carregar_config_bioativos, extrair_zip, ler_input, trocar

PASTA_DADOS = _C.dados("bioativos")
ARQUIVO_ZIP = os.path.join(PASTA_DADOS, "duke_csv.zip")
PASTA_EXTRAIDA = os.path.join(PASTA_DADOS, "duke_extraido")
URL_DUKE = "https://ndownloader.figshare.com/files/43363335"   # Duke-Source-CSV.zip
CACHE_PUBCHEM = _C.cache("cache_pubchem_duke.jsonl")
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{}/property/InChIKey,Title/JSON"
PAUSA_PUBCHEM = 0.22
UA = {"User-Agent": "Pipeline-Prospeccao-Plantas-Bioativos/2.0"}
MAX_ATIVIDADES = 40        # sem [termos_pubmed], atividades listadas por composto
RE_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")

COLUNAS_DUKE = ["parte_planta_duke", "teor_ppm_duke", "atividades_duke"]


def cfg() -> dict:
    return carregar_config_bioativos()


def url() -> str:
    return cfg().get("duke_url") or URL_DUKE


def arquivos() -> list:
    return [ARQUIVO_ZIP, PASTA_EXTRAIDA]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def baixar():
    """Baixa e extrai o export do Dr. Duke, se ainda não estiver presente."""
    os.makedirs(PASTA_DADOS, exist_ok=True)
    if not (os.path.exists(ARQUIVO_ZIP) and os.path.getsize(ARQUIVO_ZIP) > 0):
        print(f"Dr. Duke: baixando {url()} ...")
        tmp = ARQUIVO_ZIP + ".parcial"
        with requests.get(url(), headers=UA, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for bloco in r.iter_content(1 << 20):
                    f.write(bloco)
        if not zipfile.is_zipfile(tmp):
            os.remove(tmp)
            raise RuntimeError("o download do Dr. Duke não é um .zip válido")
        trocar(tmp, ARQUIVO_ZIP)
    else:
        print("Dr. Duke: já baixado")
    if not os.path.isdir(PASTA_EXTRAIDA):
        print("  extraindo...")
        extrair_zip(ARQUIVO_ZIP, PASTA_EXTRAIDA)


# ---------------------------------------------------------------------------
# Leitura das tabelas
# ---------------------------------------------------------------------------
def _arquivo(*nomes) -> str | None:
    """Caminho do CSV com um dos nomes (sem diferenciar maiúsculas), em
    qualquer subpasta da extração."""
    alvos = [n.lower() + ".csv" for n in nomes]
    for alvo in alvos:
        for raiz, _, arqs in os.walk(PASTA_EXTRAIDA):
            for a in arqs:
                if a.lower() == alvo:
                    return os.path.join(raiz, a)
    return None


def _ler(*nomes, obrigatoria=True) -> pd.DataFrame | None:
    caminho = _arquivo(*nomes)
    if caminho is None:
        if obrigatoria:
            existentes = sorted(a for _, _, arqs in os.walk(PASTA_EXTRAIDA) for a in arqs)
            raise RuntimeError(f"Dr. Duke: tabela {nomes[0]}.csv não encontrada. "
                               f"Arquivos do export: {', '.join(existentes[:40])}")
        return None
    # o export mistura codificações; latin-1 lê tudo sem erro
    df = pd.read_csv(caminho, dtype=str, encoding="latin-1", low_memory=False,
                     on_bad_lines="skip")
    df.columns = [c.strip().upper() for c in df.columns]
    return df


def _col(df, *candidatos, obrigatoria=None):
    for c in candidatos:
        if c.upper() in df.columns:
            return c.upper()
    if obrigatoria:
        raise RuntimeError(f"Dr. Duke: coluna {obrigatoria} não encontrada "
                           f"(colunas: {', '.join(df.columns)})")
    return None


def _txt(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def nome_legivel(chem: str) -> str:
    """'CAFFEIC-ACID' -> 'caffeic acid'; '1,8-CINEOLE' mantém o hífen."""
    return re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", " ", chem).strip().lower()


# ---------------------------------------------------------------------------
# PubChem: nome/CAS -> InChIKey
# ---------------------------------------------------------------------------
def _carregar_cache() -> dict:
    cache = {}
    if os.path.exists(CACHE_PUBCHEM):
        with open(CACHE_PUBCHEM, encoding="utf-8") as f:
            for linha in f:
                try:
                    item = json.loads(linha)
                    cache[item["chem"]] = item
                except (ValueError, KeyError):
                    continue
    return cache


def _consultar(sessao, termo: str):
    """(inchikey, titulo) | (None, None) se não existe | False se falhou."""
    try:
        r = sessao.get(PUBCHEM.format(quote(termo, safe="")), timeout=30)
        if r.status_code in (400, 404):
            return None, None
        r.raise_for_status()
        p = r.json()["PropertyTable"]["Properties"][0]
        ik = str(p.get("InChIKey") or "").strip().upper()
        return (ik if RE_INCHIKEY.match(ik) else None), p.get("Title")
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return False
    finally:
        time.sleep(PAUSA_PUBCHEM)


def resolver_inchikeys(chems: dict, fonte: str = "Dr. Duke") -> dict:
    """chems: {CHEM: cas ou ''} -> {CHEM: {"inchikey", "titulo"}}.
    `fonte` só rotula a barra de progresso (o cache do PubChem é compartilhado)."""
    cache = _carregar_cache()
    pendentes = [c for c in chems if c not in cache]
    if pendentes:
        print(f"  PubChem: buscando o InChIKey de {len(pendentes)} composto(s) (só nome/CAS) "
              f"({len(chems) - len(pendentes)} em cache)...")
    sessao = requests.Session()
    sessao.headers.update(UA)
    falhas = 0
    try:
        from tqdm import tqdm
    except ImportError:
        def tqdm(x, **_):
            return x
    with open(CACHE_PUBCHEM, "a", encoding="utf-8") as f:
        for chem in tqdm(pendentes, desc=f"PubChem ({fonte})"):
            termos = [chems[chem]] if chems[chem] else []
            termos += list(dict.fromkeys([chem.lower(), nome_legivel(chem)]))
            item, falhou = {"chem": chem, "inchikey": None, "titulo": None}, False
            for t in termos:
                res = _consultar(sessao, t)
                if res is False:
                    falhou = True
                    break
                if res[0]:
                    item["inchikey"], item["titulo"] = res
                    break
            if falhou:
                falhas += 1
                continue    # não grava: tenta de novo na próxima execução
            cache[chem] = item
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    if falhas:
        print(f"  ! {falhas} consulta(s) ao PubChem falharam - rode a etapa de novo para completá-las.")
    return {c: cache[c] for c in chems if c in cache}


# ---------------------------------------------------------------------------
# Atividades (AGGREGAC)
# ---------------------------------------------------------------------------
def _padroes_foco() -> dict:
    """{rótulo: [regex]} das atividades de [termos_pubmed] (vazio = todas)."""
    foco = ler_input()["termos_pubmed"]
    if not foco:
        return {}
    from descoberta_artigos import regex_termo
    return {r: [p for p in map(regex_termo, termos) if p] for r, termos in foco.items()}


def atividades_por_composto(chems: set) -> dict:
    """{CHEM: 'texto'}. Com [termos_pubmed]: só as atividades que casam com
    as suas, agrupadas por rótulo, ex.: 'clareadora (Tyrosinase-Inhibitor)'.
    Sem: todas as atividades registradas (até MAX_ATIVIDADES)."""
    agg = _ler("AGGREGAC", obrigatoria=False)
    if agg is None:
        print("  AVISO: Dr. Duke sem a tabela AGGREGAC - atividades não disponíveis.")
        return {}
    c_chem = _col(agg, "CHEM", obrigatoria="CHEM em AGGREGAC")
    c_atv = _col(agg, "ACTIVITY", "ACTIVITIES", obrigatoria="ACTIVITY em AGGREGAC")
    agg = agg[agg[c_chem].isin(chems)]
    foco = _padroes_foco()
    from descoberta_artigos import _sem_acento
    saida = {}
    for chem, grupo in agg.groupby(c_chem):
        atvs = sorted({_txt(a) for a in grupo[c_atv] if _txt(a)}, key=str.lower)
        if foco:
            partes = []
            for rotulo, padroes in foco.items():
                casadas = [a for a in atvs
                           if any(p.search(_sem_acento(a.replace("-", " "))) or
                                  p.search(_sem_acento(a)) for p in padroes)]
                if casadas:
                    partes.append(f"{rotulo} ({', '.join(casadas)})")
            if partes:
                saida[chem] = "; ".join(partes)
        elif atvs:
            extra = f" ... (+{len(atvs) - MAX_ATIVIDADES})" if len(atvs) > MAX_ATIVIDADES else ""
            saida[chem] = "; ".join(atvs[:MAX_ATIVIDADES]) + extra
    return saida


# ---------------------------------------------------------------------------
# Cruzamento com as plantas-alvo
# ---------------------------------------------------------------------------
def _faixa(lo, hi) -> str:
    def num(v):
        try:
            x = float(str(v).replace(",", "."))
            return x if x > 0 else None
        except ValueError:
            return None
    a, b = num(lo), num(hi)
    if a and b and a != b:
        return f"{a:g}-{b:g} ppm"
    if a or b:
        return f"{(a or b):g} ppm"
    return ""


def cruzar_duke(casar, especies: dict, generos: dict) -> pd.DataFrame:
    """Linhas no formato da etapa bioativos, base = 'DUKE', mais as colunas
    parte_planta_duke, teor_ppm_duke e atividades_duke."""
    vazio = pd.DataFrame(columns=["especie_normalizada", "base", "composto_id", "composto_nome",
                                  "composto_inchikey", "atividade_ou_alvo"] + COLUNAS_DUKE)
    tax = _ler("FNFTAX")
    t_num = _col(tax, "FNFNUM", obrigatoria="FNFNUM em FNFTAX")
    t_gen = _col(tax, "GENUS", obrigatoria="GENUS em FNFTAX")
    t_esp = _col(tax, "SPECIES")
    t_taxon = _col(tax, "TAXON")
    if t_esp:
        nomes = (tax[t_gen].fillna("").str.strip() + " " + tax[t_esp].fillna("").str.strip()).str.strip()
    else:
        nomes = tax[t_taxon].fillna("") if t_taxon else tax[t_gen].fillna("")
    tax = tax.assign(_especie=casar(nomes, especies, generos))
    tax = tax[tax["_especie"] != ""][[t_num, "_especie"]].drop_duplicates()
    print(f"  Dr. Duke: {tax['_especie'].nunique()} táxons-alvo encontrados")
    if tax.empty:
        return vazio

    farm = _ler("FARMACY_NEW", "FARMACY")
    f_num = _col(farm, "FNFNUM", obrigatoria="FNFNUM em FARMACY")
    f_chem = _col(farm, "CHEM", obrigatoria="CHEM em FARMACY")
    f_parte = _col(farm, "PPCO", "PLANTPART", "PART")
    f_lo = _col(farm, "AMT_LO", "LOW", "AMOUNT_LO")
    f_hi = _col(farm, "AMT_HI", "HIGH", "AMOUNT_HI")
    df = farm.merge(tax, left_on=f_num, right_on=t_num)
    df = df[df[f_chem].fillna("").str.strip() != ""]
    if df.empty:
        return vazio

    partes = _ler("PARTS", obrigatoria=False)
    nome_parte = {}
    if partes is not None and _col(partes, "PPCO") and _col(partes, "PPNA"):
        nome_parte = {_txt(a): _txt(b) for a, b in zip(partes["PPCO"], partes["PPNA"])}

    df["_chem"] = df[f_chem].str.strip()
    df["_parte"] = (df[f_parte].fillna("").str.strip().map(lambda p: nome_parte.get(p, p))
                    if f_parte else "")
    df["_teor"] = [_faixa(a, b) for a, b in zip(df[f_lo] if f_lo else [None] * len(df),
                                                 df[f_hi] if f_hi else [None] * len(df))]

    # nº CAS (melhor identificador para o PubChem), se a tabela existir
    cas = {}
    quim = _ler("CHEMICALS", obrigatoria=False)
    if quim is not None and _col(quim, "CHEM"):
        c_cas = next((c for c in quim.columns if "CAS" in c), None)
        if c_cas:
            for chem, n in zip(quim["CHEM"], quim[c_cas]):
                n = _txt(n)
                if re.fullmatch(r"\d{2,7}-\d{2}-\d", n):
                    cas[_txt(chem)] = n
    chems = {c: cas.get(c, "") for c in df["_chem"].unique()}
    print(f"  Dr. Duke: {len(chems)} compostos para as plantas-alvo")
    ids = resolver_inchikeys(chems)
    atividades = atividades_por_composto(set(chems))

    linhas = []
    for (especie, chem), g in df.groupby(["_especie", "_chem"], sort=False):
        teores = [f"{p}: {t}" if p else t for p, t in zip(g["_parte"], g["_teor"]) if t]
        info = ids.get(chem, {})
        linhas.append({
            "especie_normalizada": especie, "base": "DUKE",
            "composto_id": f"DUKE:{chem}",
            "composto_nome": info.get("titulo") or nome_legivel(chem),
            "composto_inchikey": info.get("inchikey"),
            "atividade_ou_alvo": None,
            "parte_planta_duke": "; ".join(dict.fromkeys(p for p in g["_parte"] if p)) or None,
            "teor_ppm_duke": "; ".join(dict.fromkeys(teores)) or None,
            "atividades_duke": atividades.get(chem),
        })
    res = pd.DataFrame(linhas)
    print(f"  Dr. Duke: {len(res)} pares espécie x composto; "
          f"{res['composto_inchikey'].notna().sum()} com InChIKey; "
          f"{res['atividades_duke'].notna().sum()} com atividade registrada")
    return res
