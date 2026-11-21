"""
gerar_banco.py  -  ETAPA "banco" (v3.20)

Monta os CSVs relacionais interligados pelo InChIKey canônico, com esquema
documentado e dicionário de dados público (pasta banco/), e calcula drogabilidade
e perfil ADMET básico (RDKit) para todo composto com SMILES canônico.

Entradas (das etapas anteriores):
  compostos_normalizados.csv       (normalizacao) - identidade química
  normalizacao_ocorrencias.csv     (normalizacao) - rastreabilidade
  normalizacao_sinonimos.csv       (normalizacao)
  normalizacao_conflitos.csv       (normalizacao)
  normalizacao_mapa_inchikey.csv   (normalizacao)
  plantas.csv                      (plantas)      - taxonomia e distribuição
  compostos_chembl.csv/evidencias_chembl.csv (chembl)   - bioatividade medida
  atividades_compostos.csv/evidencias_pubmed.csv (pubmed) - bioatividade relatada

Saídas (pasta banco/): um CSV por tabela do esquema_banco.py, mais
  dicionario_dados.csv, ESQUEMA.md, datapackage.json (metadados FAIR + licença),
  PROVENIENCIA_E_LICENCAS.md e LEIA-ME.txt - os três últimos com nome e prosa
  em inglês quando [banco] idioma_banco = en (SCHEMA.md, README.txt...).

Consulta o PubChem (vias, espectros) e usa o RDKit (ADMET). Caches:
  cache_pubchem_vias.jsonl, cache_pubchem_espectros.jsonl
"""

import os

import caminhos as _C
import sys
from collections import defaultdict
from datetime import date, datetime, timezone

import pandas as pd

import espectros as ESP
import esquema_banco as E
import quimio as Q
from config_pipeline import carregar_config_banco, carregar_config_chembl, gravar_csv

VERSAO = "3.20"
LICENCA = "CC-BY-SA-4.0"
PASTA = "banco"
COMPOSTOS = "compostos_normalizados.csv"
OCORRENCIAS = "normalizacao_ocorrencias.csv"
SINONIMOS = "normalizacao_sinonimos.csv"
CONFLITOS = "normalizacao_conflitos.csv"
MAPA = "normalizacao_mapa_inchikey.csv"
PLANTAS = "plantas.csv"
CHEMBL = "compostos_chembl.csv"
CHEMBL_EV = "evidencias_chembl.csv"
PUBMED_EV = "evidencias_pubmed.csv"

CACHE_VIAS = _C.cache("cache_pubchem_vias.jsonl")

CFG = carregar_config_banco()
E.IDIOMA = CFG.get("idioma_banco", "en")   # nomes do banco: "en" (padrão) ou "pt"

# medidas de afinidade em unidade molar que viram pvalor = -log10(mol/L)
MEDIDAS_MOLARES = {"IC50", "EC50", "KI", "KD", "AC50", "GI50", "ED50", "MIC", "XC50", "POTENCY"}
FATOR_MOLAR = {"M": 1.0, "MOL/L": 1.0, "MM": 1e-3, "UM": 1e-6, "µM": 1e-6, "NM": 1e-9,
               "PM": 1e-12, "FM": 1e-15}


def ler(nome, **kw) -> pd.DataFrame:
    if os.path.exists(nome):
        return pd.read_csv(nome, dtype=str, keep_default_na=False, na_values=[""], **kw)
    return pd.DataFrame()


def preparar_ocorrencias(ocorr: pd.DataFrame) -> pd.DataFrame:
    """Mapeia as colunas específicas de cada base (atividade_ou_alvo,
    atividades_duke, parte_planta_duke, teor_ppm_duke, teor_foodb,
    referencias_lotus) para as colunas genéricas do esquema (atividade_na_base,
    parte_planta, teor, referencia), que o resto da etapa consome."""
    if ocorr.empty:
        return ocorr
    df = ocorr.copy()

    def juntar(cols):
        existentes = [c for c in cols if c in df.columns]
        if not existentes:
            return pd.Series([None] * len(df), index=df.index)
        def linha(r):
            vals = []
            for c in existentes:
                v = r.get(c)
                if pd.notna(v) and str(v).strip():
                    for parte in str(v).split("; "):
                        if parte.strip() and parte not in vals:
                            vals.append(parte.strip())
            return "; ".join(vals) or None
        return df.apply(linha, axis=1)

    df["atividade_na_base"] = juntar(["atividade_ou_alvo", "atividades_duke"])
    df["parte_planta"] = juntar(["parte_planta_duke"])
    df["teor"] = juntar(["teor_ppm_duke", "teor_foodb"])
    df["referencia"] = juntar(["referencias_lotus"])
    return df


def num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def frame(tabela: str, linhas: list, manter_extras=False) -> pd.DataFrame:
    """DataFrame com exatamente as colunas do esquema, na ordem do esquema.
    manter_extras=True preserva colunas fora do esquema (ADMET-AI em perfil_admet)."""
    cols = E.colunas(tabela)
    df = pd.DataFrame(linhas)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    extras = [c for c in df.columns if c not in cols] if manter_extras else []
    return df[cols + extras]


# ---------------------------------------------------------------------------
# bioatividade (ChEMBL medido + NPASS + PubMed relatado)
# ---------------------------------------------------------------------------
def pvalor_de(medida, relacao, valor, unidade, pchembl):
    """pChEMBL quando a fonte dá; senão calcula -log10(mol/L) para medidas de
    afinidade em unidade molar e relação '='."""
    p = num(pchembl)
    if p is not None:
        return p
    v = num(valor)
    if v is None or v <= 0 or (relacao or "=").strip() not in ("=", "", "~"):
        return None
    if str(medida or "").strip().upper() not in MEDIDAS_MOLARES:
        return None
    fator = FATOR_MOLAR.get(str(unidade or "").strip().upper())
    if not fator:
        return None
    import math
    return round(-math.log10(v * fator), 3)


def bioatividade(ev_chembl: pd.DataFrame, ev_pubmed: pd.DataFrame,
                 ocorr: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    n = 0
    try:
        minimo = float(carregar_config_chembl().get("pchembl_minimo", 5.0))
    except Exception:
        minimo = 5.0

    # ChEMBL: um registro de ensaio por linha (quantitativo)
    for _, r in ev_chembl.iterrows():
        ik = Q.inchikey_valido(r.get("InChIKey"))
        if not ik:
            continue
        n += 1
        pv = pvalor_de(r.get("medida"), r.get("relacao"), r.get("valor"),
                       r.get("unidade"), r.get("pchembl"))
        ativo = (pv is not None and pv >= minimo) or \
                "ativ" in str(r.get("comentario") or "").lower()
        linhas.append({
            "id_bioatividade": f"BA{n:07d}", "inchikey": ik, "fonte": "ChEMBL",
            "natureza": "quantitativa", "correspondencia": r.get("correspondencia"),
            "molecula_ensaiada": r.get("molecula_ensaiada"), "atividade_input": r.get("atividade"),
            "alvo": r.get("alvo"), "organismo_alvo": r.get("organismo_alvo"),
            "tipo_ensaio": r.get("tipo_ensaio"), "descricao_ensaio": r.get("descricao_ensaio"),
            "tipo_medida": r.get("medida"), "relacao": r.get("relacao"),
            "valor": num(r.get("valor")), "unidade": r.get("unidade"), "pvalor": pv,
            "ativo": bool(ativo), "pmid": r.get("PMID"), "doi": r.get("DOI"),
            "ano": r.get("ano"), "id_registro_fonte": r.get("documento_chembl")})

    # NPASS e Dr. Duke: atividade/alvo registrado por composto (qualitativo).
    # As colunas vêm da rastreabilidade: NPASS em 'atividade_ou_alvo'; Duke em
    # 'atividades_duke'. 'preparar_ocorrencias' já deixou tudo em 'atividade_na_base'.
    if not ocorr.empty and "atividade_na_base" in ocorr.columns:
        qual = ocorr[ocorr["base"].isin(["NPASS", "DUKE"]) & ocorr["inchikey"].notna()
                     & ocorr["atividade_na_base"].notna()]
        vistos = set()
        for _, r in qual.iterrows():
            ik = r["inchikey"]
            for alvo in str(r["atividade_na_base"]).split("; "):
                chave = (ik, r["base"], alvo)
                if not alvo.strip() or chave in vistos:
                    continue
                vistos.add(chave)
                n += 1
                linhas.append({"id_bioatividade": f"BA{n:07d}", "inchikey": ik, "fonte": r["base"],
                               "natureza": "qualitativa", "correspondencia": "-",
                               "alvo": alvo.strip(), "ativo": True})

    # PubMed: artigos positivos lidos pelo modelo (qualitativo)
    if not ev_pubmed.empty:
        comp = ev_pubmed[ev_pubmed["tipo_entidade"] == "composto"] \
            if "tipo_entidade" in ev_pubmed.columns else pd.DataFrame()
        for _, r in comp.iterrows():
            ik = Q.inchikey_valido(r.get("InChIKey"))
            if not ik:
                continue
            n += 1
            linhas.append({
                "id_bioatividade": f"BA{n:07d}", "inchikey": ik, "fonte": "PubMed",
                "natureza": "qualitativa", "correspondencia": "-",
                "atividade_input": r.get("atividades"), "tipo_ensaio": r.get("tipo_estudo"),
                "descricao_ensaio": r.get("justificativa_llm"), "ativo": True,
                "pmid": r.get("PMID"), "doi": r.get("DOI"), "ano": r.get("ano")})
    return frame("bioatividade", linhas)


# ---------------------------------------------------------------------------
# vias metabólicas (PubChem + NPClassifier)
# ---------------------------------------------------------------------------
def iks_da_regiao(ocorr: pd.DataFrame) -> set | None:
    """InChIKeys com pelo menos uma ocorrência em planta da região. Com
    [banco] enriquecer_apenas_regiao = true, só eles recebem as consultas de
    um pedido por composto ao PubChem (vias e espectros): com [bioativos]
    escopo = completo as bases entram inteiras e esses pedidos não terminariam
    em tempo útil. None = sem restrição."""
    if not CFG.get("enriquecer_apenas_regiao", True) or "na_regiao" not in ocorr.columns:
        return None
    dentro = ocorr["na_regiao"].fillna("").str.strip().str.lower() != "não"
    if dentro.all():
        return None
    return set(ocorr.loc[dentro, "inchikey"].dropna())


def apenas_regiao(compostos: pd.DataFrame, iks: set | None, rotulo: str) -> pd.DataFrame:
    """Compostos que recebem as consultas caras ao PubChem."""
    if iks is None:
        return compostos
    recorte = compostos[compostos["inchikey"].isin(iks)]
    print(f"  enriquecer_apenas_regiao = true: {rotulo} só para os {len(recorte)} compostos "
          f"da região (de {len(compostos)})")
    return recorte


def vias(compostos: pd.DataFrame, iks_regiao: set | None = None) -> pd.DataFrame:
    linhas = []
    # via biossintética do NPClassifier (já no compostos.csv)
    for _, c in compostos.iterrows():
        via = c.get("np_classifier_pathway")
        if Q.texto(via):
            linhas.append({"inchikey": c["inchikey"], "tipo": "via biossintética (NPClassifier)",
                           "via_id": None, "via_nome": via, "fonte": "NPClassifier (COCONUT)",
                           "categoria": "biossíntese", "organismo": None, "url": None})
    if not CFG["vias_pubchem"]:
        return frame("vias_metabolicas", linhas)

    com_cid = apenas_regiao(compostos, iks_regiao, "vias").dropna(subset=["pubchem_cid"])
    cache = Q.Cache(CACHE_VIAS)
    faltam = [c for c in dict.fromkeys(com_cid["pubchem_cid"]) if f"v|{c}" not in cache]
    if faltam:
        print(f"  PubChem (vias): {len(faltam)} CID(s) a consultar")
        cli = Q.Cliente("PubChem (vias)", intervalo=0.25)
        for i, cid in enumerate(faltam, 1):
            res = Q.pubchem_vias(cli, cid)
            if res is None:
                if cli.desistiu:
                    break
                continue
            cache.gravar(f"v|{cid}", res)
            if i % 200 == 0:
                print(f"  ... {i}/{len(faltam)}")
    cache.fechar()
    for _, c in com_cid.iterrows():
        for v in cache.get(f"v|{c['pubchem_cid']}") or []:
            linhas.append({"inchikey": c["inchikey"], "tipo": "via (base de vias)",
                           "via_id": v.get("via_id"), "via_nome": v.get("via_nome"),
                           "fonte": v.get("fonte"), "categoria": v.get("categoria"),
                           "organismo": v.get("organismo"), "url": v.get("url")})
    return frame("vias_metabolicas", linhas)


# ---------------------------------------------------------------------------
# dados espectrais (PubChem experimental + m/z teóricos do RDKit)
# ---------------------------------------------------------------------------
def espectros(compostos: pd.DataFrame, admet: pd.DataFrame,
              iks_regiao: set | None = None) -> pd.DataFrame:
    """Reúne os registros das FONTES ESPECTRAIS. Esta etapa não conhece
    nenhuma fonte: quem as descobre (em mods/espectros_*.py) e as chama é o
    registro em espectros.py. Para acrescentar o GNPS, o MassBank ou o MoNA
    basta criar o módulo da fonte - nada aqui muda. Ver a seção 26 do README."""
    print(f"  fontes espectrais encontradas: {ESP.resumo()}")
    contexto = {"admet": admet, "iks_regiao": iks_regiao, "cfg": CFG}
    return frame("dados_espectrais",
                 ESP.coletar_tudo(apenas_regiao(compostos, iks_regiao, "espectros"), contexto))


# ---------------------------------------------------------------------------
# perfil ADMET (RDKit)
# ---------------------------------------------------------------------------
def perfil_admet(compostos: pd.DataFrame) -> pd.DataFrame:
    if not Q.TEM_RDKIT:
        print("  AVISO: RDKit não instalado - perfil_admet.csv fica vazio. "
              "Instale: pip install rdkit")
        return frame("perfil_admet", [])
    smiles_col = "smiles_canonico" if "smiles_canonico" in compostos.columns else "smiles_isomerico"
    com = compostos.dropna(subset=[smiles_col]) if smiles_col in compostos.columns else pd.DataFrame()
    print(f"  ADMET/drogabilidade (RDKit): {len(com)} composto(s) com SMILES")
    metodo = f"RDKit {getattr(__import__('rdkit'), '__version__', '?')}"
    linhas = []
    for _, c in com.iterrows():
        smi = c[smiles_col]
        d = Q.descritores_admet(smi)
        if not d:
            linhas.append({"inchikey": c["inchikey"], "smiles_canonico": smi,
                           "status_admet": "SMILES inválido", "metodo": metodo})
            continue
        d.pop("mz_M+H", None); d.pop("mz_M+Na", None); d.pop("mz_M-H", None)
        linhas.append({"inchikey": c["inchikey"],
                       "smiles_canonico": d.pop("smiles_canonico", None) or smi,
                       "status_admet": "calculado", "metodo": metodo, **d})

    if CFG["admet_ai"] and linhas:
        print("  ADMET-AI (opcional): carregando modelo e prevendo (pode demorar)...")
        smis = [l["smiles_canonico"] for l in linhas if l["status_admet"] == "calculado"]
        pred = Q.admet_ai(smis)
        if pred is not None:
            pred = pred.add_prefix(E.PREFIXO_ADMET_AI)
            for l in linhas:
                s = l["smiles_canonico"]
                if s in getattr(pred, "index", []):
                    linha = pred.loc[s]
                    linha = linha.iloc[0] if isinstance(linha, pd.DataFrame) else linha
                    l.update({k: (num(v) if num(v) is not None else v)
                              for k, v in linha.to_dict().items()})
    return frame("perfil_admet", linhas, manter_extras=True)


# ---------------------------------------------------------------------------
# organismos, origem biológica, distribuição (de plantas.csv + ocorrências)
# ---------------------------------------------------------------------------
def na_regiao_de(grp: pd.DataFrame, m) -> str:
    """"sim"/"não": o organismo é da região da rodada? Vem da coluna na_regiao
    das ocorrências ([bioativos] escopo = completo); sem ela, da presença do
    organismo em plantas.csv - e aí todos são da região."""
    if "na_regiao" in grp.columns and grp["na_regiao"].notna().any():
        return "não" if (grp["na_regiao"].fillna("").str.strip().str.lower()
                         == "não").all() else "sim"
    return "sim" if (m is not None and hasattr(m, "get")) else "não"


def organismos_e_origem(compostos: pd.DataFrame, ocorr: pd.DataFrame,
                        plantas: pd.DataFrame):
    # nome -> metadados da planta
    meta = {}
    if not plantas.empty:
        for _, r in plantas.iterrows():
            meta[r.get("nome_cientifico")] = r
    com_ik = ocorr[ocorr["inchikey"].notna()] if not ocorr.empty else pd.DataFrame()

    # origem biológica: composto x organismo
    origem, dist = [], []
    orgs_com_composto = defaultdict(set)
    na_regiao_org = {}
    if not com_ik.empty and "nome_cientifico" in com_ik.columns:
        g = com_ik.dropna(subset=["nome_cientifico"])
        for (ik, nome), grp in g.groupby(["inchikey", "nome_cientifico"]):
            orgs_com_composto[nome].add(ik)
            m = meta.get(nome, {})
            na_regiao_org.setdefault(nome, na_regiao_de(grp, m))
            origem.append({
                "inchikey": ik, "nome_cientifico": nome,
                "na_regiao": na_regiao_de(grp, m),
                "familia": grp["familia"].dropna().iloc[0] if grp["familia"].notna().any() else None,
                "bases": "; ".join(sorted(set(grp["base"].dropna()))),
                "n_bases": grp["base"].nunique(),
                "nomes_organismo_nas_bases": "; ".join(sorted(set(
                    x for x in grp.get("organismo_na_base", pd.Series(dtype=str)).dropna()))) or None,
                "parte_planta": "; ".join(sorted(set(
                    x for x in grp.get("parte_planta", pd.Series(dtype=str)).dropna()))) or None,
                "teor": "; ".join(sorted(set(
                    x for x in grp.get("teor", pd.Series(dtype=str)).dropna()))) or None,
                "referencias": "; ".join(sorted(set(
                    x for x in grp.get("referencia", pd.Series(dtype=str)).dropna())))[:500] or None,
                "ids_ocorrencias": "; ".join(grp["id_ocorrencia"].dropna().tolist()[:50])})

            # distribuição: uma linha por UF do organismo
            estados = str((m.get("estados_br") if hasattr(m, "get") else None) or "").strip()
            ufs = [u.strip() for u in estados.replace(";", ",").split(",") if u.strip()
                   and "desconhec" not in u.lower()] or [None]
            for uf in ufs:
                dist.append({
                    "inchikey": ik, "nome_cientifico": nome, "uf": uf,
                    "dominios_br": m.get("dominios_br") if hasattr(m, "get") else None,
                    "endemismo_br": m.get("endemismo_br") if hasattr(m, "get") else None,
                    "origem_br": m.get("origem_br") if hasattr(m, "get") else None,
                    "fonte_distribuicao": m.get("fonte_distribuicao") if hasattr(m, "get") else None})

    # organismos: só os que têm ao menos um composto
    orgs = []
    for nome, iks in sorted(orgs_com_composto.items()):
        m = meta.get(nome, {})
        g = (lambda k: (m.get(k) if hasattr(m, "get") else None))
        orgs.append({"nome_cientifico": nome, "nome_aceito": g("nome_aceito"),
                     "na_regiao": na_regiao_org.get(nome),
                     "categoria_taxonomica": g("categoria_taxonomica"), "reino": g("reino"),
                     "filo": g("filo"), "classe": g("classe"), "ordem": g("ordem"),
                     "familia": g("familia"), "nome_popular_pt": g("nome_popular_pt"),
                     "speciesKey": g("speciesKey"), "estados_br": g("estados_br"),
                     "dominios_br": g("dominios_br"), "endemismo_br": g("endemismo_br"),
                     "origem_br": g("origem_br"), "fonte_distribuicao": g("fonte_distribuicao"),
                     "n_compostos": len(iks)})
    return (frame("organismos", orgs), frame("origem_biologica", origem),
            frame("distribuicao_geografica", dist))


# ---------------------------------------------------------------------------
# tabela compostos (acrescenta contagens das outras tabelas)
# ---------------------------------------------------------------------------
def montar_compostos(norm: pd.DataFrame, bioat, vias_df, espec, admet, origem) -> pd.DataFrame:
    df = norm.copy()
    if "smiles_canonico" not in df.columns:
        df["smiles_canonico"] = None
    def conta(tab, col="inchikey"):
        return tab.groupby(col).size() if not tab.empty else pd.Series(dtype=int)
    n_ba = conta(bioat)
    n_ba_q = conta(bioat[bioat["natureza"] == "quantitativa"]) if not bioat.empty else pd.Series(dtype=int)
    n_vias = conta(vias_df)
    n_esp = conta(espec[espec["origem"] == "experimental"]) if not espec.empty else pd.Series(dtype=int)
    tem_admet = set(admet[admet["status_admet"] == "calculado"]["inchikey"]) \
        if not admet.empty else set()
    df["n_bioatividades"] = df["inchikey"].map(n_ba).fillna(0).astype(int)
    df["n_bioatividades_quantitativas"] = df["inchikey"].map(n_ba_q).fillna(0).astype(int)
    df["n_vias"] = df["inchikey"].map(n_vias).fillna(0).astype(int)
    df["n_espectros"] = df["inchikey"].map(n_esp).fillna(0).astype(int)
    df["tem_admet"] = df["inchikey"].isin(tem_admet)
    return frame("compostos", df.to_dict("records"))


def main():
    if not os.path.exists(COMPOSTOS):
        sys.exit(f"{COMPOSTOS} não encontrado. Rode a etapa 'normalizacao' primeiro.")
    norm = ler(COMPOSTOS)
    if "inchikey" in norm.columns:
        norm = norm[norm["inchikey"].notna()]
    if norm.empty:
        # nenhum composto com estrutura: grava o banco vazio (com esquema e
        # dicionário) para a etapa concluir e o --retomar reconhecê-la
        os.makedirs(PASTA, exist_ok=True)
        contagens = {}
        for nome in E.TABELAS:
            gravar_csv(E.traduzir(frame(nome, []), nome),
                       os.path.join(PASTA, f"{E.nome_tabela(nome)}.csv"))
            contagens[nome] = 0
        escrever_metadados(contagens)
        gravar_csv(E.traduzir(frame("compostos", []), "compostos"), SAIDA_MARCADOR)
        print("Nenhum composto com estrutura: banco/ gravado vazio (com esquema e dicionário).")
        return
    print(f"{len(norm)} composto(s) normalizado(s) em {COMPOSTOS}")

    ocorr = preparar_ocorrencias(ler(OCORRENCIAS))
    sin = ler(SINONIMOS)
    conf = ler(CONFLITOS)
    mapa = ler(MAPA)
    plantas = ler(PLANTAS)
    ev_chembl = ler(CHEMBL_EV)
    ev_pubmed = ler(PUBMED_EV) if CFG["incluir_pubmed"] else pd.DataFrame()

    os.makedirs(PASTA, exist_ok=True)

    print("\n1. Perfil ADMET e drogabilidade (RDKit)")
    admet = perfil_admet(norm)

    print("\n2. Bioatividade (ChEMBL medido + NPASS + PubMed relatado)")
    bioat = bioatividade(ev_chembl, ev_pubmed, ocorr)
    print(f"  {len(bioat)} registro(s) de bioatividade "
          f"({(bioat['natureza'] == 'quantitativa').sum()} quantitativos)" if not bioat.empty
          else "  nenhum registro de bioatividade")

    print("\n3. Vias metabólicas (PubChem + NPClassifier)")
    iks_regiao = iks_da_regiao(ocorr)
    vias_df = vias(norm, iks_regiao)
    print(f"  {len(vias_df)} registro(s) de via")

    print("\n4. Dados espectrais (PubChem + m/z teóricos)")
    espec = espectros(norm, admet, iks_regiao)
    print(f"  {len(espec)} registro(s) espectral(is)")

    print("\n5. Organismos, origem biológica e distribuição")
    orgs, origem, dist = organismos_e_origem(norm, ocorr, plantas)
    print(f"  {len(orgs)} organismo(s); {len(origem)} par(es) composto x organismo; "
          f"{len(dist)} linha(s) de distribuição")

    print("\n6. Identidade química e ligações")
    compostos = montar_compostos(norm, bioat, vias_df, espec, admet, origem)

    # sinônimos: reordena para o esquema
    sin_df = frame("sinonimos", sin.to_dict("records")) if not sin.empty else frame("sinonimos", [])
    # fontes.csv = rastreabilidade (ocorrências já no formato certo, só renomeia campos)
    fontes = reindexar_fontes(ocorr)
    conf_df = frame("conflitos", conf.to_dict("records")) if not conf.empty else frame("conflitos", [])
    mapa_df = frame("mapa_inchikey", mapa.to_dict("records")) if not mapa.empty else frame("mapa_inchikey", [])

    tabelas = {"compostos": compostos, "fontes": fontes, "sinonimos": sin_df,
               "organismos": orgs, "origem_biologica": origem,
               "distribuicao_geografica": dist, "bioatividade": bioat,
               "vias_metabolicas": vias_df, "dados_espectrais": espec,
               "perfil_admet": admet, "conflitos": conf_df, "mapa_inchikey": mapa_df}

    print("\n7. Gravando banco/ (CSVs, dicionário, esquema, datapackage)")
    contagens = {}
    for nome, df in tabelas.items():
        arquivo = f"{E.nome_tabela(nome)}.csv"
        gravar_csv(E.traduzir(df, nome), os.path.join(PASTA, arquivo))
        contagens[nome] = len(df)
        print(f"  banco/{arquivo}: {len(df)} linha(s)")

    extras = {"perfil_admet": [c for c in admet.columns if c.startswith(E.PREFIXO_ADMET_AI)]}
    escrever_metadados(contagens, extras)

    gravar_csv(E.traduzir(compostos, "compostos"), SAIDA_MARCADOR)   # por último: marca a etapa
    print(f"\nConcluído: banco/ com {len(tabelas)} tabelas relacionais (InChIKey canônico), "
          f"dicionário de dados e datapackage.json.\n  {len(compostos)} compostos; "
          f"{contagens['bioatividade']} registros de bioatividade; "
          f"{contagens['perfil_admet']} perfis ADMET.")


SAIDA_MARCADOR = "banco_compostos.csv"   # cópia de banco/compostos.csv na raiz (marcador do --retomar)


def escrever_metadados(contagens: dict, extras: dict | None = None):
    """Grava os arquivos de esquema/metadados FAIR da pasta banco/."""
    hoje = date.today().isoformat()
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")   # RFC3339 p/ datapackage
    gravar_csv(pd.DataFrame(E.dicionario()),
               os.path.join(PASTA, E.nome_meta("dicionario_dados.csv")))
    with open(os.path.join(PASTA, "datapackage.json"), "w", encoding="utf-8") as f:
        f.write(E.datapackage(versao=VERSAO, extras=extras, licenca=LICENCA, criado=agora))
    # nomes e prosa no idioma do banco ([banco] idioma_banco)
    with open(os.path.join(PASTA, E.nome_meta("ESQUEMA.md")), "w", encoding="utf-8") as f:
        f.write(E.esquema_md(contagens))
    with open(os.path.join(PASTA, E.nome_meta("PROVENIENCIA_E_LICENCAS.md")), "w",
              encoding="utf-8") as f:
        f.write(E.proveniencia_md(versao=VERSAO, licenca=LICENCA, criado=hoje))
    with open(os.path.join(PASTA, E.nome_meta("LEIA-ME.txt")), "w", encoding="utf-8") as f:
        f.write(E.leia_me())


def reindexar_fontes(ocorr: pd.DataFrame) -> pd.DataFrame:
    """ocorr já passou por preparar_ocorrencias (tem atividade_na_base,
    parte_planta, teor, referencia). Só acrescenta a URL e seleciona o esquema."""
    if ocorr.empty:
        return frame("fontes", [])
    df = ocorr.copy()
    df["url_registro"] = df.apply(url_registro, axis=1)
    return frame("fontes", df.to_dict("records"))


def url_registro(r) -> str | None:
    base, idb = r.get("base"), str(r.get("id_na_base") or "")
    if not idb or idb == "nan":
        return None
    if base == "COCONUT":
        return f"https://coconut.naturalproducts.net/compounds/{idb}"
    if base == "NPASS":
        return f"https://bidd.group/NPASS/compound.php?compoundID={idb}"
    if base == "LOTUS" and idb.startswith("LOTUS:Q"):
        return f"https://www.wikidata.org/wiki/{idb.split(':', 1)[1]}"
    return None


if __name__ == "__main__":
    main()
