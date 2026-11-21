"""
foodb.py  -  FooDB (compostos de alimentos)

Módulo usado pela etapa "bioativos" (cruzar_especies_bioativos.py).

O que o FooDB acrescenta, para plantas ALIMENTÍCIAS (açaí, cacau, guaraná,
castanha, mandioca, frutas...):
  - o ALIMENTO em que o composto foi medido (ex.: "Cocoa bean");
  - o TEOR (ex.: "Cocoa bean, seed: 12-40 mg/100 g").

Dados: export completo em CSV (foodb_2020_04_07_csv.tar.gz, ~950 MB), do
grupo de D. Wishart (Universidade de Alberta). ATENÇÃO À LICENÇA: uso
acadêmico livre; uso COMERCIAL exige permissão (https://foodb.ca/about).
Tabelas usadas: Food.csv (alimento e nome científico), Content.csv (teor de
cada composto em cada alimento) e Compound.csv (nome e InChIKey).
Só as três tabelas são extraídas do arquivo; o .tar.gz é apagado depois.
"""

import os

import caminhos as _C
import re
import tarfile

import pandas as pd
import requests

from config_pipeline import carregar_config_bioativos, trocar

PASTA_DADOS = _C.dados("bioativos")
PASTA = os.path.join(PASTA_DADOS, "foodb")
ARQUIVO_TAR = os.path.join(PASTA_DADOS, "foodb_csv.tar.gz")
URL_FOODB = "https://foodb.ca/public/system/downloads/foodb_2020_4_7_csv.tar.gz"
TABELAS = ("Food.csv", "Content.csv", "Compound.csv")
UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
      "Accept": "*/*", "Referer": "https://foodb.ca/downloads"}
RE_INCHIKEY = re.compile(r"[A-Z]{14}-[A-Z]{10}-[A-Z]")
MAX_TEORES = 6

COLUNAS_FOODB = ["alimento_foodb", "teor_foodb"]


def cfg() -> dict:
    return carregar_config_bioativos()


def url() -> str:
    return cfg().get("foodb_url") or URL_FOODB


def arquivos() -> list:
    return [PASTA]


def instalado() -> bool:
    return all(os.path.exists(os.path.join(PASTA, t)) for t in TABELAS)


def _baixado_a_mao() -> str | None:
    """Arquivo do FooDB salvo à mão em dados/bioativos/, com qualquer nome
    que comece por "foodb" (ex.: o original foodb_2020_4_7_csv.tar.gz) e
    compactado ou não (.tar.gz, .tgz ou .tar - alguns navegadores já
    descompactam o .gz)."""
    if not os.path.isdir(PASTA_DADOS):
        return None
    candidatos = [os.path.join(PASTA_DADOS, n) for n in os.listdir(PASTA_DADOS)
                  if n.lower().startswith("foodb") and n.lower().endswith((".tar.gz", ".tgz", ".tar"))
                  and not n.endswith(".parcial")]
    candidatos = [c for c in candidatos if os.path.getsize(c) > 0]
    return max(candidatos, key=os.path.getmtime) if candidatos else None


def baixar():
    """Baixa o export do FooDB e extrai só Food, Content e Compound."""
    if instalado():
        print("FooDB: já baixado")
        return
    os.makedirs(PASTA_DADOS, exist_ok=True)
    manual = _baixado_a_mao()
    if manual and manual != ARQUIVO_TAR and not os.path.exists(ARQUIVO_TAR):
        print(f"FooDB: usando o arquivo baixado à mão ({os.path.basename(manual)})")
        trocar(manual, ARQUIVO_TAR)
    if not (os.path.exists(ARQUIVO_TAR) and os.path.getsize(ARQUIVO_TAR) > 0):
        print(f"FooDB: baixando {url()} (~950 MB) ...")
        tmp = ARQUIVO_TAR + ".parcial"
        with requests.get(url(), headers=UA, stream=True, timeout=900) as r:
            if r.status_code in (401, 403):
                raise RuntimeError(
                    f"o site recusou o download automático (HTTP {r.status_code}). Baixe pelo "
                    f"navegador ({url()}) e salve o arquivo como "
                    f"{os.path.abspath(ARQUIVO_TAR)} - na próxima rodada ele é extraído. "
                    "Ou desligue a base: usar_foodb = false em [bioativos]")
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for bloco in r.iter_content(1 << 20):
                    f.write(bloco)
        trocar(tmp, ARQUIVO_TAR)
    print("  extraindo Food.csv, Content.csv e Compound.csv ...")
    os.makedirs(PASTA, exist_ok=True)
    achados = set()
    try:
        tar = tarfile.open(ARQUIVO_TAR, "r:*")       # .tar.gz ou .tar (já descompactado)
    except tarfile.ReadError as e:
        raise RuntimeError(f"{ARQUIVO_TAR} não é um arquivo .tar.gz válido (download "
                           "incompleto ou página de erro salva no lugar do arquivo?). Apague-o "
                           "e baixe de novo.") from e
    with tar:
        for membro in tar:
            nome = os.path.basename(membro.name)
            if membro.isfile() and nome in TABELAS and nome not in achados:
                origem = tar.extractfile(membro)
                final = os.path.join(PASTA, nome)
                with open(final + ".parcial", "wb") as destino:
                    while True:
                        bloco = origem.read(1 << 20)
                        if not bloco:
                            break
                        destino.write(bloco)
                trocar(final + ".parcial", final)   # só fica com o nome final se completo
                achados.add(nome)
    faltando = set(TABELAS) - achados
    if faltando:
        raise RuntimeError(f"FooDB: tabelas não encontradas no arquivo: {', '.join(sorted(faltando))}")
    os.remove(ARQUIVO_TAR)   # ~1 GB que não é mais necessário


def _col(colunas, *candidatos):
    mapa = {c.lower(): c for c in colunas}
    for c in candidatos:
        if c.lower() in mapa:
            return mapa[c.lower()]
    return None


def _ler(nome, **kw) -> pd.DataFrame:
    return pd.read_csv(os.path.join(PASTA, nome), dtype=str, on_bad_lines="skip",
                       encoding="utf-8", encoding_errors="replace", **kw)


def _num(v):
    try:
        x = float(str(v).replace(",", "."))
        return x if x > 0 else None
    except ValueError:
        return None


def _teor(lo, hi, media, unidade) -> str:
    a, b, m = _num(lo), _num(hi), _num(media)
    u = f" {unidade}" if isinstance(unidade, str) and unidade.strip() else ""
    if a and b and a != b:
        return f"{a:g}-{b:g}{u}"
    if m or a or b:
        return f"{(m or a or b):g}{u}"
    return ""


def cruzar_foodb(casar, especies: dict, generos: dict) -> pd.DataFrame:
    """Linhas no formato da etapa bioativos, base = 'FOODB', com as colunas
    alimento_foodb e teor_foodb."""
    vazio = pd.DataFrame(columns=["especie_normalizada", "base", "composto_id", "composto_nome",
                                  "composto_inchikey", "atividade_ou_alvo"] + COLUNAS_FOODB)
    food = _ler("Food.csv")
    f_id = _col(food.columns, "id")
    f_nome = _col(food.columns, "name")
    f_cient = _col(food.columns, "name_scientific")
    if not (f_id and f_cient):
        raise RuntimeError(f"FooDB: colunas id/name_scientific não encontradas em Food.csv ({list(food.columns)})")
    food = food.dropna(subset=[f_cient])
    food["_especie"] = casar(food[f_cient], especies, generos)
    food = food[food["_especie"] != ""]
    print(f"  FooDB: {food['_especie'].nunique()} táxons-alvo encontrados "
          f"({len(food)} alimento(s))")
    if food.empty:
        return vazio
    alimento = dict(zip(food[f_id], food[f_nome] if f_nome else food[f_cient]))
    especie_do_alimento = dict(zip(food[f_id], food["_especie"]))

    cab = _ler("Content.csv", nrows=0).columns
    c_src = _col(cab, "source_id")
    c_tipo = _col(cab, "source_type")
    c_food = _col(cab, "food_id")
    c_parte = _col(cab, "orig_food_part")
    c_cont = _col(cab, "orig_content", "standard_content")
    c_min = _col(cab, "orig_min")
    c_max = _col(cab, "orig_max")
    c_un = _col(cab, "orig_unit")
    if not (c_src and c_food):
        raise RuntimeError(f"FooDB: colunas source_id/food_id não encontradas em Content.csv ({list(cab)})")
    usar = [c for c in [c_src, c_tipo, c_food, c_parte, c_cont, c_min, c_max, c_un] if c]
    pedacos = []
    for bloco in _ler("Content.csv", usecols=usar, chunksize=500_000):
        bloco = bloco[bloco[c_food].isin(alimento)]
        if c_tipo:
            bloco = bloco[bloco[c_tipo].fillna("").str.lower() == "compound"]
        if not bloco.empty:
            pedacos.append(bloco)
    if not pedacos:
        return vazio
    cont = pd.concat(pedacos, ignore_index=True)

    comp = _ler("Compound.csv")
    k_id = _col(comp.columns, "id")
    k_nome = _col(comp.columns, "name")
    k_pub = _col(comp.columns, "public_id")
    k_ik = next((c for c in comp.columns if "inchikey" in c.lower()), None)
    k_cas = _col(comp.columns, "cas_number")
    comp = comp[comp[k_id].isin(cont[c_src])]
    nomes = dict(zip(comp[k_id], comp[k_nome])) if k_nome else {}
    pubs = dict(zip(comp[k_id], comp[k_pub])) if k_pub else {}
    iks = {}
    if k_ik:
        for i, v in zip(comp[k_id], comp[k_ik]):
            m = RE_INCHIKEY.search(str(v))
            if m:
                iks[i] = m.group(0)
    sem_ik = {i for i in comp[k_id] if i not in iks and isinstance(nomes.get(i), str)}
    if sem_ik:   # completa pelo PubChem (mesmo mecanismo e cache do Dr. Duke)
        import duke as D
        cas = dict(zip(comp[k_id], comp[k_cas])) if k_cas else {}
        pedido = {nomes[i]: (str(cas.get(i)) if re.fullmatch(r"\d{2,7}-\d{2}-\d", str(cas.get(i) or "")) else "")
                  for i in sem_ik}
        resolvidos = D.resolver_inchikeys(pedido, fonte="FooDB")
        for i in sem_ik:
            ik = (resolvidos.get(nomes[i]) or {}).get("inchikey")
            if ik:
                iks[i] = ik

    cont["_especie"] = cont[c_food].map(especie_do_alimento)
    cont["_alimento"] = cont[c_food].map(alimento)
    linhas = []
    for (especie, src), g in cont.groupby(["_especie", c_src], sort=False):
        alimentos = list(dict.fromkeys(a for a in g["_alimento"] if isinstance(a, str)))
        teores = []
        for _, r in g.iterrows():
            t = _teor(r.get(c_min) if c_min else None, r.get(c_max) if c_max else None,
                      r.get(c_cont) if c_cont else None, r.get(c_un) if c_un else None)
            if t:
                parte = r.get(c_parte) if c_parte else None
                rot = r["_alimento"] + (f", {parte.strip().lower()}" if isinstance(parte, str) and parte.strip() else "")
                teores.append(f"{rot}: {t}")
        teores = list(dict.fromkeys(teores))
        extra = f" (+{len(teores) - MAX_TEORES})" if len(teores) > MAX_TEORES else ""
        linhas.append({
            "especie_normalizada": especie, "base": "FOODB",
            "composto_id": f"FOODB:{pubs.get(src) or src}",
            "composto_nome": nomes.get(src),
            "composto_inchikey": iks.get(src),
            "atividade_ou_alvo": None,
            "alimento_foodb": "; ".join(alimentos) or None,
            "teor_foodb": ("; ".join(teores[:MAX_TEORES]) + extra) if teores else None,
        })
    res = pd.DataFrame(linhas)
    print(f"  FooDB: {len(res)} pares espécie x composto; "
          f"{res['composto_inchikey'].notna().sum()} com InChIKey; "
          f"{res['teor_foodb'].notna().sum()} com teor")
    return res
