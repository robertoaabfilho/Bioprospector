"""
cruzar_especies_bioativos.py  -  ETAPA 3 ("bioativos")

Levanta, no COCONUT, no NPASS e no Dr. Duke (USDA), os compostos de
produtos naturais registrados para as plantas de plantas.csv (etapa
"plantas").

Fontes (downloads oficiais em lote, cacheados em dados/bioativos/):
  COCONUT  CSV COMPLETO (não o "lite"): traz a coluna de organismos de
           origem, além de InChIKey e classificação química (NP Classifier,
           ClassyFire, QED, NP-likeness). A versão mais recente é
           descoberta automaticamente em coconut.naturalproducts.net/download.
  NPASS 3.0  pares composto-espécie, taxonomia das espécies, nomes,
           ESTRUTURAS (é lá que fica o InChIKey), registros de ATIVIDADE e
           ALVOS - usados para preencher atividade_ou_alvo.
  Dr. Duke  (opcional, usar_duke em [bioativos]) composto x planta x PARTE
           da planta x TEOR, e atividades por composto (duke.py). Os nomes
           são convertidos em InChIKey pelo PubChem.
  LOTUS    (opcional, usar_lotus) pares composto x organismo com a
           REFERÊNCIA (DOI) de cada par (lotus.py).
  FooDB    (opcional, usar_foodb) compostos de ALIMENTOS, com o alimento e
           o TEOR (foodb.py). Uso comercial exige permissão dos autores.

Correspondência de nomes: SÓ pela coluna nomes_busca de plantas.csv, que a
etapa "plantas" preenche com todos os nomes de cada planta (o científico, o
aceito, sinônimos e grafias). Os nomes são comparados sem autor, "cf." e
"×", e com a variedade/subespécie quando houver. Como plantas.csv tem uma
linha por ESPÉCIE (as variedades estão em nomes_busca), os compostos são
salvos por espécie; um registro de variedade que não esteja em nomes_busca
também vai para a linha da espécie. Um nome que esteja em mais de
uma linha leva o composto a todas elas. Os mesmos compostos vindos de várias
bases (mesmo InChIKey) para a mesma planta são consolidados numa linha, ex.:
base = "COCONUT; DUKE".

Saída: especies_com_compostos_bioativos.csv
    especie_normalizada (nome(s) sob o qual o composto está registrado nas
    bases químicas), base, composto_id, composto_nome,
    composto_inchikey, atividade_ou_alvo, nome_cientifico, reino, familia,
    nome_popular_pt, fonte, pubchem_cid, + classificação química do COCONUT
    + parte_planta_duke, teor_ppm_duke, atividades_duke (com o Dr. Duke)
    + referencias_lotus (com o LOTUS)
    + alimento_foodb, teor_foodb (com o FooDB)

Saída de rastreabilidade (v3.17): ocorrencias_compostos_bruto.csv, um
registro de cada base para cada planta, com o nome, o InChIKey, o SMILES e o
CID que AQUELA base informa (antes da consolidação). É a entrada da etapa
"normalizacao".
"""

import json
import time
import os

import caminhos as _C
import re

import pandas as pd
import requests

import distribuicao as DIST
import duke as D
import foodb as F
import fontes_compostos as FC
import lotus as L
import taxonomia as T
from config_pipeline import (carregar_config_bioativos, carregar_config_bioativos_escopo,
                             carregar_config_bioativos_reino, extrair_zip, gravar_csv,
                             trocar)

# bases complementares: (chave em [bioativos], módulo, rótulo, colunas próprias)
# (chave do input.txt, módulo, rótulo, colunas extras, função, padrão)
# As três do pacote mais as achadas em mods/fonte_*.py - é assim que uma base
# nova (NPAtlas, HMDB...) entra sem que este arquivo mude. Ver
# fontes_compostos.py e a seção 26 do README.
FONTES_EXTRA = [("usar_duke", D, "Dr. Duke (USDA)", D.COLUNAS_DUKE, "cruzar_duke", None),
                ("usar_lotus", L, "LOTUS", L.COLUNAS_LOTUS, "cruzar_lotus", None),
                ("usar_foodb", F, "FooDB", F.COLUNAS_FOODB, "cruzar_foodb", None),
                ] + FC.descobertas()
COLUNAS_EXTRA = [c for fonte in FONTES_EXTRA for c in fonte[3]]

ENTRADA = "plantas.csv"
SAIDA = "especies_com_compostos_bioativos.csv"
PASTA_DADOS = _C.dados("bioativos")
HEADERS = {"User-Agent": "Pipeline-Prospeccao-Plantas-Bioativos/2.0"}

PAGINA_COCONUT = "https://coconut.naturalproducts.net/download"
URL_COCONUT_PADRAO = ("https://coconut.s3.uni-jena.de/prod/downloads/2026-10/"
                      "coconut_csv-10-2026.zip")
NPASS = "https://bidd.group/NPASS/downloadFiles/NPASS3.0_{}.txt"
ARQUIVOS_NPASS = {
    "species_pair": "naturalproducts_species_pair",
    "species_info": "species_info",
    "general_info": "naturalproducts_generalinfo",
    "structure": "naturalproducts_structure",
    "activities": "activities",
    "target": "target",
}

COLUNAS_ENRIQUECIMENTO = ["np_classifier_pathway", "np_classifier_superclass",
                          "np_classifier_class", "chemical_class",
                          "qed_drug_likeliness", "np_likeness", "molecular_formula"]
# ClassyFire completo do COCONUT (superclasse, subclasse, pai direto): usado
# pela etapa "normalizacao" como alternativa quando o ClassyFire não responde
COLUNAS_CLASSYFIRE_COCONUT = ["chemical_super_class", "chemical_sub_class",
                              "direct_parent_classification"]
COLUNAS_ENRIQUECIMENTO += COLUNAS_CLASSYFIRE_COCONUT

# Rastreabilidade (etapa "normalizacao"): cada registro de cada base, ANTES da
# consolidação, com os valores que AQUELA base dá ao composto
SAIDA_OCORRENCIAS = "ocorrencias_compostos_bruto.csv"
OCORRENCIAS_BRUTAS = None
COLUNAS_BASE = ["composto_nome", "composto_id", "composto_inchikey",
                "especie_normalizada", "base", "atividade_ou_alvo", "nome_cientifico",
                "reino", "familia", "nome_popular_pt", "fonte", "na_regiao",
                "estados_br", "estados_composto",
                "pubchem_cid",
                "composto_smiles", "fonte_smiles", "smiles_npass", "smiles_coconut",
                "smiles_lotus", "smiles_pubchem", "conferencia_smiles"]
# SMILES de cada fonte, lado a lado (para conferir divergências); vazio = a
# fonte não tem estrutura para o composto
COLUNAS_SMILES_FONTE = {"NPASS": "smiles_npass", "COCONUT": "smiles_coconut",
                        "LOTUS": "smiles_lotus"}

CACHE_CID_PUBCHEM = _C.cache("cache_pubchem_cid.jsonl")   # gravado pela etapa "pubmed"
RE_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
MAX_ATIVIDADES_POR_COMPOSTO = 15


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def inchikey_valido(valor) -> str | None:
    if not isinstance(valor, str):
        return None
    v = valor.strip().upper()
    return v if RE_INCHIKEY.match(v) else None


def baixar(url: str, destino: str):
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        print(f"  já baixado: {os.path.basename(destino)}")
        return
    print(f"  baixando: {url}")
    tmp = destino + ".parcial"
    with requests.get(url, headers=HEADERS, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(chunk_size=1 << 20):
                f.write(bloco)
    trocar(tmp, destino)


def url_coconut() -> str:
    configurada = carregar_config_bioativos()["coconut_url"]
    if configurada:
        return configurada
    try:
        html = requests.get(PAGINA_COCONUT, headers=HEADERS, timeout=60).text
        links = re.findall(r"https://coconut\.s3\.uni-jena\.de/prod/downloads/[\w\-/]+?"
                           r"/coconut_csv-\d{2}-\d{4}\.zip", html)
        if links:
            return sorted(set(links))[-1]
    except requests.RequestException as e:
        print(f"  (não consegui ler a página de downloads do COCONUT: {e})")
    print(f"  usando URL padrão do COCONUT: {URL_COCONUT_PADRAO}")
    return URL_COCONUT_PADRAO


def ler_tsv(caminho: str, **kw) -> pd.DataFrame:
    return pd.read_csv(caminho, sep="\t", dtype=str, on_bad_lines="skip",
                       low_memory=False, encoding_errors="replace", **kw)


def col(colunas, *candidatos, obrigatoria=None) -> str | None:
    """Acha a coluna por nome exato (sem diferenciar maiúsculas) e, se não
    achar, por substring - na ordem dos candidatos."""
    mapa = {c.lower(): c for c in colunas}
    for c in candidatos:
        if c.lower() in mapa:
            return mapa[c.lower()]
    for c in candidatos:
        for nome in colunas:
            if c.lower() in nome.lower():
                return nome
    if obrigatoria:
        raise RuntimeError(f"Não achei a coluna de {obrigatoria}. Colunas "
                           f"disponíveis: {list(colunas)}. Ajuste o nome em "
                           "cruzar_especies_bioativos.py.")
    return None


# ---------------------------------------------------------------------------
# Plantas-alvo
# ---------------------------------------------------------------------------
def chave_nome(nome) -> str:
    """Nome normalizado para comparação: gênero + epíteto (+ categoria e
    nome infraespecífico), em minúsculas, sem autor, "cf.", "aff." ou "×".
    'Erythroxylum coca var. ipadu Plowman' -> 'erythroxylum coca var. ipadu'."""
    if not isinstance(nome, str) or not nome.strip():
        return ""
    return T.chave(nome)


# Escopo da etapa ([bioativos] escopo):
#   "regiao"   - só os compostos das plantas de plantas.csv (padrão);
#   "completo" - todos os compostos de organismos VEGETAIS das bases químicas.
#                As plantas de fora da região entram com na_regiao = "não" e
#                sem as colunas de distribuição, que só existem para a região.
# O escopo "completo" é o que a construção do banco publicável usa; o "regiao"
# é o que serve à prospecção de uma área.
ESCOPO = "regiao"
# [bioativos] reino: "vegetal" (padrão) confere o gênero de cada organismo das
# bases químicas nos gêneros do WFO/WCVP; "qualquer" aceita qualquer organismo,
# que é o que uma base de bactérias, fungos ou metabólitos humanos (NPAtlas,
# HMDB) precisa. Só tem efeito com escopo = completo: no escopo regional os
# organismos são casados contra o plantas.csv, que já é só de plantas.
REINO = "vegetal"
FORA_DA_REGIAO = "não"                # valor da coluna na_regiao
SEM_DISTRIBUICAO = DIST.FORA_DA_REGIAO  # ≠ "distribuição desconhecida" (dentro da região)
GENEROS_PLANTA = set()   # gêneros de WFO/WCVP: o filtro de reino vegetal
FORA = {}                # chave do nome -> nome como está na base química

LINHAS = {}          # nº da linha de plantas.csv -> metadados da planta
INDICE = {}          # nome de busca normalizado -> [linhas de plantas.csv]
INDICE_GENERO = {}   # gênero (linhas GENUS de plantas.csv) -> [linhas]
GENERO_FORA = {}     # gênero -> espécies das bases químicas que ficaram de fora


def carregar_generos_planta() -> set:
    """Gêneros de plantas, do WFO e do WCVP (listas mundiais, já baixadas e
    consultadas no próprio computador). É o filtro de reino do escopo
    "completo": um organismo de base química só entra se o gênero dele estiver
    aqui. A Flora e Funga do Brasil fica de fora deste teste de propósito -
    ela também cataloga fungos e algas.

    Sem nenhuma das duas listas não há como conferir o reino sem internet, e a
    etapa volta ao escopo "regiao"."""
    global GENEROS_PLANTA
    if GENEROS_PLANTA:
        return GENEROS_PLANTA
    listas = T.listas_baixadas()
    print("  carregando os gêneros de plantas do WFO/WCVP (usa alguns GB de "
          "memória por alguns minutos)...")
    for chave in ("wfo", "wcvp"):
        lista = listas.get(chave)
        if lista is None:
            continue
        try:
            lista.genero_existe("Euterpe")     # dispara a carga da lista
            GENEROS_PLANTA |= set(lista.generos)
        except Exception as e:
            print(f"  AVISO: {chave.upper()} indisponível ({e})")
    if GENEROS_PLANTA:
        print(f"  {len(GENEROS_PLANTA)} gêneros de plantas para o filtro de reino")
    return GENEROS_PLANTA


def reino_aceito(chave: str) -> bool:
    """O organismo entra no banco? Com reino = vegetal, só se o gênero estiver
    entre os gêneros de plantas do WFO/WCVP; com reino = qualquer, sempre."""
    if not chave:
        return False
    return True if REINO == "qualquer" else chave.split()[0] in GENEROS_PLANTA


def carregar_alvos():
    """Lê plantas.csv e monta o índice de busca SÓ com a coluna nomes_busca
    (que a etapa "plantas" preenche com todos os nomes de cada planta: o
    científico, o aceito, sinônimos e grafias). Um mesmo nome pode estar em
    mais de uma linha (ex.: dois nomes da sua lista que são a mesma
    espécie): o composto achado por ele vai para TODAS essas linhas."""
    if not os.path.exists(ENTRADA):
        raise FileNotFoundError(f"{ENTRADA} não encontrado. Rode a etapa \"plantas\" "
                                "(montar_lista_plantas.py) primeiro.")
    plantas = pd.read_csv(ENTRADA, dtype=str)
    # nomes que nenhuma base taxonômica reconheceu (ex.: bactérias citadas em
    # artigos) ficam de fora, a menos que incluir_nao_reconhecidos = true
    if "situacao_nome" in plantas.columns and not carregar_config_bioativos()["incluir_nao_reconhecidos"]:
        nao_rec = plantas["situacao_nome"].fillna("").str.strip() == "não reconhecido"
        if nao_rec.any():
            nomes = plantas.loc[nao_rec, "nome_cientifico"].tolist()
            print(f"  {len(nomes)} nome(s) não reconhecido(s) por nenhuma base ficam de fora "
                  f"(incluir_nao_reconhecidos = false): {', '.join(nomes[:10])}"
                  + (" ..." if len(nomes) > 10 else ""))
            plantas = plantas[~nao_rec]
    LINHAS.clear(), INDICE.clear(), INDICE_GENERO.clear()
    sem_nomes_busca = 0
    for n_linha, linha in plantas.reset_index(drop=True).iterrows():
        nomes = [n.strip() for n in str(linha.get("nomes_busca") or "").split(";")
                 if n.strip() and n.strip().lower() != "nan"]
        if not nomes:      # plantas.csv de versão antiga, sem nomes_busca
            nomes = [linha["nome_cientifico"]]
            sem_nomes_busca += 1
        LINHAS[n_linha] = {k: linha.get(k) for k in ["nome_cientifico", "reino", "familia",
                                                     "nome_popular_pt", "fonte", "estados_br"]}
        for n in nomes:
            k = chave_nome(n)
            if not k:
                continue
            destino = INDICE_GENERO if " " not in k else INDICE
            if n_linha not in destino.setdefault(k, []):
                destino[k].append(n_linha)
    if sem_nomes_busca:
        print(f"  AVISO: {sem_nomes_busca} linha(s) sem nomes_busca - usado o nome_cientifico")
    print(f"  {len(LINHAS)} plantas-alvo; {len(INDICE)} nomes de busca de espécies"
          + (f" e {len(INDICE_GENERO)} gêneros" if INDICE_GENERO else ""))
    return INDICE, INDICE_GENERO


def casar(nomes: pd.Series, especies: dict, generos: dict) -> pd.Series:
    """Para cada nome de organismo de uma base de compostos, devolve o nome
    de busca (normalizado) com que ele casou, ou ''.

      1. o nome completo, como está na base (inclusive var./subsp.);
      2. se o registro é de uma variedade/subespécie e ela não está entre os
         nomes de busca, a espécie dela (a variedade faz parte da espécie);
         o contrário não vale: um registro da espécie não vai para uma
         linha de variedade;
      3. registro só de gênero ("Copaifera sp."): casa com as linhas de
         gênero da sua lista. Um gênero não traz espécies novas: as espécies
         dele que entram são só as que já estão em plantas.csv."""
    memo = {}

    def f(nome):
        if nome in memo:
            return memo[nome]
        k = chave_nome(nome)
        res = ""
        if k in especies:
            res = k
        elif k.count(" ") >= 3 and " ".join(k.split()[:2]) in especies:
            res = " ".join(k.split()[:2])
        elif k and " " not in k and k in generos:
            res = "g:" + k
        else:
            if k and k.split()[0] in generos:
                GENERO_FORA.setdefault(k.split()[0], set()).add(" ".join(k.split()[:2]))
            # escopo "completo": a planta de fora da região também entra, com
            # o nome da própria base como identidade (não há linha em plantas.csv)
            if ESCOPO == "completo" and reino_aceito(k):
                especie = " ".join(k.split()[:2]) if " " in k else k
                res = "x:" + especie
                FORA.setdefault(especie, nome.strip())
        memo[nome] = res
        return res
    return nomes.map(f)


def linhas_do_nome(chave: str) -> list:
    if chave.startswith("g:"):
        return INDICE_GENERO.get(chave[2:], [])
    if chave.startswith("x:"):
        return [chave]          # planta de fora da região: a chave é a identidade
    return INDICE.get(chave, [])


def meta_da_linha(n):
    """Metadados da planta de uma linha. Linha de plantas.csv (número) ou
    planta de fora da região (chave "x:nome")."""
    if isinstance(n, str) and n.startswith("x:"):
        nome = FORA.get(n[2:], n[2:])
        return {"nome_cientifico": nome[:1].upper() + nome[1:], "reino": "Plantae",
                "na_regiao": FORA_DA_REGIAO, "estados_br": SEM_DISTRIBUICAO}
    return {**LINHAS.get(int(n), {}), "na_regiao": "sim"}


# ---------------------------------------------------------------------------
# NPASS
# ---------------------------------------------------------------------------
def arquivo_npass(chave: str) -> str:
    return os.path.join(PASTA_DADOS, f"npass_{chave}.txt")


def resumir_atividades_npass(np_ids: set) -> dict:
    """{np_id: 'Alvo (tipo); Alvo (tipo); ...'} só para os compostos pedidos."""
    if not np_ids:
        return {}
    atv = ler_tsv(arquivo_npass("activities"))
    c_np = col(atv.columns, "np_id", obrigatoria="np_id em activities")
    c_alvo = col(atv.columns, "target_id")
    c_tipo = col(atv.columns, "activity_type_grouped", "activity_type")
    atv = atv[atv[c_np].isin(np_ids)]
    if atv.empty:
        return {}

    nomes_alvo = {}
    if c_alvo and os.path.exists(arquivo_npass("target")):
        alvos = ler_tsv(arquivo_npass("target"))
        t_id = col(alvos.columns, "target_id")
        t_nome = col(alvos.columns, "target_name", "pref_name")
        t_org = col(alvos.columns, "target_organism")
        if t_id and t_nome:
            for _, a in alvos.iterrows():
                nome = a[t_nome]
                org = a[t_org] if t_org else None
                if isinstance(org, str) and org and org.lower() not in str(nome).lower() \
                        and org.lower() != "homo sapiens":
                    nome = f"{nome} [{org}]"
                nomes_alvo[a[t_id]] = nome

    def rotulo(linha):
        alvo = nomes_alvo.get(linha[c_alvo], linha[c_alvo]) if c_alvo else "alvo não informado"
        tipo = linha[c_tipo] if c_tipo and isinstance(linha[c_tipo], str) else ""
        return f"{alvo} ({tipo})" if tipo else str(alvo)

    atv = atv.assign(_rotulo=atv.apply(rotulo, axis=1))
    resumo = {}
    for np_id, grupo in atv.groupby(c_np):
        contagem = grupo["_rotulo"].value_counts()
        itens = list(contagem.index[:MAX_ATIVIDADES_POR_COMPOSTO])
        if len(contagem) > MAX_ATIVIDADES_POR_COMPOSTO:
            itens.append(f"+{len(contagem) - MAX_ATIVIDADES_POR_COMPOSTO} outras")
        resumo[np_id] = "; ".join(itens)
    return resumo


RE_CID = re.compile(r"(?<![\w.])(\d{1,10})(?:\.0+)?(?![\w.])")


def cid_npass(valor) -> str | None:
    """PubChem CID do NPASS em qualquer formato ('5280343', '5280343.0',
    'CID:5280343', '5280343; 123', '5280343|123') -> '5280343'.
    'n.a.', vazio e zero -> None."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    m = RE_CID.search(str(valor))
    return m.group(1) if m and int(m.group(1)) > 0 else None


def cids_do_cache_pubchem() -> dict:
    """{InChIKey: CID} já resolvidos pela etapa "pubmed" (cache_pubchem_cid.jsonl)."""
    if not os.path.exists(CACHE_CID_PUBCHEM):
        return {}
    saida = {}
    with open(CACHE_CID_PUBCHEM, encoding="utf-8") as f:
        for linha in f:
            try:
                item = json.loads(linha)
            except json.JSONDecodeError:
                continue
            cid = cid_npass(item.get("cid")) if isinstance(item, dict) else None
            if cid and item.get("inchikey"):
                saida[item["inchikey"]] = cid
    return saida


def cruzar_npass(especies: dict, generos: dict) -> pd.DataFrame:
    info = ler_tsv(arquivo_npass("species_info"))
    pares = ler_tsv(arquivo_npass("species_pair"))
    i_id = col(info.columns, "org_id", obrigatoria="org_id em species_info")
    i_nomes = [c for c in [col(info.columns, "org_name"), col(info.columns, "species_name")] if c]
    if not i_nomes:
        col(info.columns, "org_name", obrigatoria="nome do organismo em species_info")
    p_org = col(pares.columns, "org_id", obrigatoria="org_id em species_pair")
    p_np = col(pares.columns, "np_id", obrigatoria="np_id em species_pair")

    casamento = pd.Series("", index=info.index)
    for c in i_nomes:  # org_name primeiro; species_name cobre subespécies/variedades
        faltando = casamento == ""
        casamento[faltando] = casar(info.loc[faltando, c], especies, generos)
    info = info.assign(_especie=casamento)
    info = info[info["_especie"] != ""][[i_id, "_especie"]]
    print(f"  NPASS: {info['_especie'].nunique()} táxons-alvo encontrados")

    df = pares[[p_org, p_np]].merge(info, left_on=p_org, right_on=i_id)
    df = df[[p_np, "_especie"]].drop_duplicates()
    if df.empty:
        return pd.DataFrame(columns=["especie_normalizada", "base", "composto_id",
                                     "composto_nome", "composto_inchikey", "atividade_ou_alvo"])

    gerais = ler_tsv(arquivo_npass("general_info"))
    g_np = col(gerais.columns, "np_id", obrigatoria="np_id em generalinfo")
    g_nome = col(gerais.columns, "pref_name", "name")
    g_iupac = col(gerais.columns, "iupac_name")
    g_cid = col(gerais.columns, "pubchem_cid", "pubchem", "cid")
    gerais = gerais[gerais[g_np].isin(df[p_np])]
    nomes = {}
    for _, g in gerais.iterrows():
        nome = g[g_nome] if g_nome and isinstance(g[g_nome], str) and g[g_nome].strip() else None
        if not nome and g_iupac and isinstance(g[g_iupac], str):
            nome = g[g_iupac]
        nomes[g[g_np]] = nome
    cids = {}
    if g_cid:
        for np_id, cid in zip(gerais[g_np], gerais[g_cid]):
            cid = cid_npass(cid)
            if cid:
                cids[np_id] = cid

    estrut = ler_tsv(arquivo_npass("structure"))
    s_np = col(estrut.columns, "np_id", obrigatoria="np_id em structure")
    s_ik = col(estrut.columns, "inchikey", "standard_inchi_key", "inchi_key",
               obrigatoria="InChIKey em structure")
    estrut = estrut[estrut[s_np].isin(df[p_np])]
    inchikeys = dict(zip(estrut[s_np], estrut[s_ik].map(inchikey_valido)))
    s_smi = col(estrut.columns, "smiles", "canonical_smiles")
    smiles = dict(zip(estrut[s_np], estrut[s_smi])) if s_smi else {}

    # o NPASS 3.0 pode trazer o CID na tabela de estrutura em vez da geral
    e_cid = col(estrut.columns, "pubchem_cid", "pubchem", "cid")
    if e_cid:
        for np_id, cid in zip(estrut[s_np], estrut[e_cid]):
            cid = cid_npass(cid)
            if cid and np_id not in cids:
                cids[np_id] = cid
    n_cid = df[p_np].drop_duplicates().map(cids).notna().sum()
    print(f"  NPASS: PubChem CID para {n_cid} de {df[p_np].nunique()} compostos "
          f"(coluna: {g_cid or e_cid or 'nenhuma'})")
    if n_cid == 0:
        brutos = [str(v) for v in (gerais[g_cid] if g_cid else estrut[e_cid] if e_cid else [])][:5]
        print("  AVISO: nenhum CID lido do NPASS. Colunas de generalinfo: "
              f"{list(gerais.columns)}; exemplos de valores: {brutos}")

    atividades = resumir_atividades_npass(set(df[p_np]))
    print(f"  NPASS: {df[p_np].nunique()} compostos, "
          f"{len(atividades)} com registro de atividade biológica")

    return pd.DataFrame({
        "especie_normalizada": df["_especie"].values,
        "base": "NPASS",
        "composto_id": df[p_np].values,
        "composto_nome": df[p_np].map(nomes).values,
        "composto_inchikey": df[p_np].map(inchikeys).values,
        "pubchem_cid": df[p_np].map(cids).values,
        "composto_smiles": df[p_np].map(smiles).values,
        "atividade_ou_alvo": df[p_np].map(atividades).values,
    })


# ---------------------------------------------------------------------------
# COCONUT (leitura em blocos: o CSV completo é grande)
# ---------------------------------------------------------------------------
def localizar_csv_coconut() -> str:
    pasta = os.path.join(PASTA_DADOS, "coconut_extraido")
    for raiz, _, arquivos in os.walk(pasta):
        for a in arquivos:
            if a.lower().endswith(".csv"):
                return os.path.join(raiz, a)
    raise FileNotFoundError(f"CSV do COCONUT não encontrado em {pasta}.")


def processar_coconut(especies: dict, generos: dict, inchikeys_npass: set):
    """Uma única passada pelo COCONUT que (a) acha compostos das plantas-alvo
    pela coluna de organismos e (b) guarda a classificação química dos
    compostos já achados no NPASS (por InChIKey)."""
    caminho = localizar_csv_coconut()
    cabecalho = pd.read_csv(caminho, nrows=0).columns
    c_id = col(cabecalho, "identifier", "coconut_id")
    c_nome = col(cabecalho, "name")
    c_iupac = next((c for c in cabecalho if c.lower() == "iupac_name"), None)
    c_ik = col(cabecalho, "standard_inchi_key", "inchikey", "inchi_key")
    c_org = col(cabecalho, "organisms", "organism")
    c_smi = next((c for c in cabecalho if c.lower() in ("canonical_smiles", "smiles")), None)
    enriq = [c for c in COLUNAS_ENRIQUECIMENTO if c in cabecalho]
    if c_org is None:
        print("  AVISO: o CSV do COCONUT não tem coluna de organismos - ele será "
              "usado só para enriquecer os compostos do NPASS. Colunas: "
              f"{list(cabecalho)}")
    usar = [c for c in dict.fromkeys([c_id, c_nome, c_iupac, c_ik, c_org, c_smi] + enriq) if c]

    achados, enriquecimento = [], []
    for i, bloco in enumerate(pd.read_csv(caminho, usecols=usar, dtype=str,
                                          chunksize=50_000, on_bad_lines="skip"), 1):
        if c_ik:
            bloco["_ik"] = bloco[c_ik].map(inchikey_valido)
            if enriq:
                enriquecimento.append(bloco.loc[bloco["_ik"].isin(inchikeys_npass), ["_ik"] + enriq])
        if c_org:
            com_org = bloco[bloco[c_org].notna()]
            explodido = com_org.assign(_org=com_org[c_org].str.split(r"\s*[|;]\s*")).explode("_org")
            explodido["_especie"] = casar(explodido["_org"], especies, generos)
            explodido = explodido[explodido["_especie"] != ""]
            if not explodido.empty:
                achados.append(explodido)
        if i % 4 == 0:
            print(f"  ... {i * 50_000:,} moléculas do COCONUT lidas")

    if achados:
        a = pd.concat(achados).drop_duplicates([c_id, "_especie"] if c_id else None)
        resultado = pd.DataFrame({
            "especie_normalizada": a["_especie"].values,
            "base": "COCONUT",
            "composto_id": a[c_id].values if c_id else None,
            # sem nome comum no COCONUT: usa o nome IUPAC
            "composto_nome": (a[c_nome].where(a[c_nome].fillna("").str.strip() != "",
                                              a[c_iupac] if c_iupac else None).values
                              if c_nome else (a[c_iupac].values if c_iupac else None)),
            "composto_inchikey": a["_ik"].values if c_ik else None,
            "composto_smiles": a[c_smi].values if c_smi else None,
            "atividade_ou_alvo": None,
            **{c: a[c].values for c in enriq},
        })
    else:
        resultado = pd.DataFrame(columns=["especie_normalizada", "base", "composto_id",
                                          "composto_nome", "composto_inchikey",
                                          "atividade_ou_alvo"] + enriq)
    print(f"  COCONUT: {resultado['composto_id'].nunique()} compostos para "
          f"{resultado['especie_normalizada'].nunique()} táxons-alvo")

    tabela_enriq = (pd.concat(enriquecimento).drop_duplicates("_ik")
                    if enriquecimento else pd.DataFrame(columns=["_ik"] + enriq))
    return resultado, tabela_enriq


# ---------------------------------------------------------------------------
# Consolidação
# ---------------------------------------------------------------------------
# Caracteres que chegaram corrompidos em nomes do COCONUT (codificação
# chinesa GB2312 convertida em texto): "(¡À)" -> "(±)", "6¡ä" -> "6′",
# "(1¡ú2)" -> "(1→2)"
CORRECOES_NOME = [(re.compile(r"\s*inverted exclamation markA"), "±"),
                  (re.compile(r"\s*inverted exclamation marka"), "′"),
                  (re.compile(r"\s*inverted exclamation marku"), "→")]


def limpar_nome_composto(nome):
    if not isinstance(nome, str):
        return None
    for padrao, certo in CORRECOES_NOME:
        nome = padrao.sub(certo, nome)
    nome = nome.strip()
    return nome or None


def _juntar(valores) -> str | None:
    itens = []
    for v in valores:
        if isinstance(v, str):
            for parte in v.split("; "):
                if parte and parte not in itens:
                    itens.append(parte)
    return "; ".join(itens) if itens else None


def _primeiro(valores):
    for v in valores:
        if pd.notna(v) and str(v).strip():
            return v
    return None


def guardar_ocorrencias_brutas(todos: pd.DataFrame):
    """Fotografia dos registros de cada base antes de qualquer preenchimento
    cruzado (nome, CID, SMILES e classificação de uma base copiados para as
    linhas de outra). A classificação do COCONUT que foi anexada às linhas de
    outras bases pelo InChIKey é apagada aqui: cada linha mostra só o que a
    própria base informa."""
    global OCORRENCIAS_BRUTAS
    bruto = todos.copy()
    nao_coconut = bruto["base"] != "COCONUT"
    for c in COLUNAS_ENRIQUECIMENTO:
        if c in bruto.columns:
            bruto.loc[nao_coconut, c] = None
    bruto["composto_nome"] = bruto["composto_nome"].map(limpar_nome_composto)
    bruto["_linha"] = bruto["especie_normalizada"].map(linhas_do_nome)
    bruto = bruto.explode("_linha").dropna(subset=["_linha"])
    bruto["especie_normalizada"] = bruto["especie_normalizada"].str.replace(r"^g:", "", regex=True)
    OCORRENCIAS_BRUTAS = bruto


def gravar_ocorrencias_brutas():
    """ocorrencias_compostos_bruto.csv: uma linha por registro de base x planta."""
    if OCORRENCIAS_BRUTAS is None or OCORRENCIAS_BRUTAS.empty:
        gravar_csv(pd.DataFrame(columns=["base", "composto_id"]), SAIDA_OCORRENCIAS)
        return
    df = OCORRENCIAS_BRUTAS.copy()
    metas = df["_linha"].map(meta_da_linha)
    for campo in ["nome_cientifico", "reino", "familia", "na_regiao"]:
        df[campo] = metas.map(lambda m: m.get(campo))
    df = df.rename(columns={"composto_smiles": "smiles_na_base",
                            "composto_inchikey": "inchikey_declarado",
                            "composto_nome": "nome_na_base",
                            "composto_id": "id_na_base",
                            "pubchem_cid": "pubchem_cid_na_base",
                            "especie_normalizada": "organismo_na_base"})
    primeiras = ["base", "id_na_base", "nome_na_base", "inchikey_declarado", "smiles_na_base",
                 "pubchem_cid_na_base", "organismo_na_base", "nome_cientifico", "familia", "reino",
                 "na_regiao", "atividade_ou_alvo"]
    resto = [c for c in df.columns if c not in primeiras and not c.startswith("_")
             and c not in ("fonte_smiles", "nome_popular_pt", "fonte", "estados_br")
             and not c.startswith("smiles_")]
    df = df[[c for c in primeiras if c in df.columns] + resto].drop_duplicates()
    gravar_csv(df, SAIDA_OCORRENCIAS)
    print(f"  {len(df)} registro(s) de base x planta em {SAIDA_OCORRENCIAS} "
          "(rastreabilidade, para a etapa 'normalizacao')")


def consolidar(npass: pd.DataFrame, coconut: pd.DataFrame,
               tabela_enriq: pd.DataFrame, extras: list | None = None) -> pd.DataFrame:
    extras = [e for e in (extras or []) if e is not None and not e.empty]
    for c in COLUNAS_ENRIQUECIMENTO + ["pubchem_cid", "composto_smiles"] + COLUNAS_EXTRA:
        for df in [npass, coconut] + extras:
            if c not in df.columns:
                df[c] = None

    def enriquecer(df):
        if tabela_enriq.empty or df.empty:
            return df
        df = df.drop(columns=[c for c in COLUNAS_ENRIQUECIMENTO if c in tabela_enriq.columns])
        return df.merge(tabela_enriq, left_on="composto_inchikey", right_on="_ik",
                        how="left").drop(columns="_ik")
    npass = enriquecer(npass)
    extras = [enriquecer(e) for e in extras]

    # NPASS primeiro: nomes e atividades; bases complementares por último
    todos = pd.concat([npass, coconut] + extras, ignore_index=True)
    if todos.empty:
        return todos
    # tipo genérico em todas as colunas: no pandas 3, uma coluna de texto
    # ("str") recusa qualquer valor que não seja texto nas atribuições abaixo
    todos = todos.astype(object).where(todos.notna(), None)
    guardar_ocorrencias_brutas(todos)

    # de onde veio cada SMILES (a base da própria linha); COCONUT e NPASS vêm
    # primeiro em `todos`, então só valem as outras quando eles não têm
    tem_smiles = todos["composto_smiles"].fillna("").astype(str).str.strip() != ""
    todos["composto_smiles"] = todos["composto_smiles"].where(tem_smiles, None)
    todos["fonte_smiles"] = todos["base"].where(tem_smiles, None)
    # uma coluna por fonte: o SMILES que AQUELA base dá ao composto (pelo
    # InChIKey, vale para todas as linhas do composto, de qualquer planta)
    for base, coluna in COLUNAS_SMILES_FONTE.items():
        todos[coluna] = todos["composto_smiles"].where(todos["base"] == base, None)
        por_ik = (todos.dropna(subset=["composto_inchikey", coluna])
                  .drop_duplicates("composto_inchikey").set_index("composto_inchikey")[coluna])
        falta = todos[coluna].isna() & todos["composto_inchikey"].notna()
        todos.loc[falta, coluna] = todos.loc[falta, "composto_inchikey"].map(por_ik)
    todos["smiles_pubchem"] = None
    # SMILES escolhido: o MESMO para o composto em todas as plantas, na ordem
    # NPASS > COCONUT > LOTUS (o PubChem só entra depois, para os que faltarem)
    for base, coluna in reversed(list(COLUNAS_SMILES_FONTE.items())):
        tem = todos[coluna].notna()
        todos.loc[tem, "composto_smiles"] = todos.loc[tem, coluna]
        todos.loc[tem, "fonte_smiles"] = base

    # nomes com caracteres corrompidos na origem (COCONUT)
    todos["composto_nome"] = todos["composto_nome"].map(limpar_nome_composto)
    # nome, CID e SMILES que faltam numa base mas existem em outra para o
    # mesmo InChIKey (ex.: CID do NPASS para a linha do COCONUT)
    for campo in ["composto_nome", "pubchem_cid"]:
        por_ik = (todos.dropna(subset=["composto_inchikey", campo])
                  .drop_duplicates("composto_inchikey")
                  .set_index("composto_inchikey")[campo])
        falta = todos[campo].isna() & todos["composto_inchikey"].notna()
        todos.loc[falta, campo] = todos.loc[falta, "composto_inchikey"].map(por_ik)
    # SMILES de outras bases (ex.: FooDB) para os compostos ainda sem nenhum
    com_smi = (todos.dropna(subset=["composto_inchikey", "composto_smiles"])
               .drop_duplicates("composto_inchikey").set_index("composto_inchikey"))
    falta = todos["composto_smiles"].isna() & todos["composto_inchikey"].notna()
    for campo in ["composto_smiles", "fonte_smiles"]:
        todos.loc[falta, campo] = todos.loc[falta, "composto_inchikey"].map(com_smi[campo])

    # atividade NPASS também para as linhas do COCONUT com o mesmo InChIKey
    atv_por_ik = (todos.dropna(subset=["composto_inchikey", "atividade_ou_alvo"])
                  .drop_duplicates("composto_inchikey")
                  .set_index("composto_inchikey")["atividade_ou_alvo"])
    faltando = todos["atividade_ou_alvo"].isna() & todos["composto_inchikey"].notna()
    todos.loc[faltando, "atividade_ou_alvo"] = todos.loc[faltando, "composto_inchikey"].map(atv_por_ik)

    # cada nome casado vai para TODAS as linhas de plantas.csv que o têm em
    # nomes_busca; o mesmo composto achado por dois nomes da mesma linha
    # (ex.: o científico e um sinônimo) vira uma linha só
    todos["_linha"] = todos["especie_normalizada"].map(linhas_do_nome)
    todos = todos.explode("_linha").dropna(subset=["_linha"])
    todos["especie_normalizada"] = todos["especie_normalizada"].str.replace(r"^g:", "", regex=True)
    todos["_chave"] = todos["composto_inchikey"].fillna(
        todos["base"] + ":" + todos["composto_id"].astype(str))
    agregacao = {"especie_normalizada": _juntar, "base": _juntar, "composto_id": _juntar,
                 "composto_nome": _primeiro,
                 "composto_inchikey": _primeiro, "pubchem_cid": _primeiro,
                 "composto_smiles": _primeiro, "fonte_smiles": _primeiro,
                 **{c: _primeiro for c in list(COLUNAS_SMILES_FONTE.values()) + ["smiles_pubchem"]},
                 "atividade_ou_alvo": _primeiro,
                 **{c: _primeiro for c in COLUNAS_ENRIQUECIMENTO},
                 **{c: _juntar for c in COLUNAS_EXTRA}}
    consolidado = todos.groupby(["_linha", "_chave"], as_index=False,
                                sort=False).agg(agregacao)
    # CID que faltou no NPASS: o que a etapa "pubmed" já achou no PubChem
    cache_cid = cids_do_cache_pubchem()
    if cache_cid:
        sem_cid = consolidado["pubchem_cid"].isna() & consolidado["composto_inchikey"].notna()
        consolidado.loc[sem_cid, "pubchem_cid"] = consolidado.loc[sem_cid, "composto_inchikey"].map(cache_cid)
    consolidado["base"] = consolidado["base"].map(
        lambda b: "; ".join(sorted(b.split("; "))) if isinstance(b, str) else b)
    return consolidado.drop(columns="_chave")


# ---------------------------------------------------------------------------
# SMILES do PubChem: só para os compostos que nenhuma base trouxe com estrutura
# ---------------------------------------------------------------------------
URL_PUBCHEM_SMILES = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/inchikey/{}/"
                      "property/{}/JSON")
CACHE_SMILES = _C.cache("cache_pubchem_smiles.jsonl")
MAX_FALHAS_PUBCHEM = 20


def _smiles_pubchem(sessao, inchikey: str):
    """SMILES do PubChem para um InChIKey. "" = o PubChem não tem o composto
    (vai para o cache); None = falha de rede/servidor (tenta de novo depois)."""
    # o PubChem trocou os nomes das propriedades em 2025 (SMILES / IsomericSMILES)
    for prop in ("SMILES", "IsomericSMILES"):
        try:
            r = sessao.get(URL_PUBCHEM_SMILES.format(inchikey, prop), headers=HEADERS,
                           timeout=(10, 30))
        except requests.RequestException:
            return None
        if r.status_code == 404:
            return ""
        if r.status_code == 400:
            continue                      # propriedade com outro nome: tenta a próxima
        if r.status_code == 429 or r.status_code >= 500:
            return None
        try:
            props = r.json()["PropertyTable"]["Properties"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            return ""
        return next((props[k] for k in ("SMILES", "IsomericSMILES", "CanonicalSMILES")
                     if props.get(k)), "")
    return ""


COLUNAS_SMILES = ["composto_smiles", "fonte_smiles", "smiles_npass", "smiles_coconut",
                  "smiles_lotus", "smiles_pubchem", "conferencia_smiles"]


def _texto(v):
    """Só texto não vazio vale como SMILES (o cache pode ter valores estranhos)."""
    return v.strip() if isinstance(v, str) and v.strip() else None


def _colunas_genericas(df: pd.DataFrame) -> pd.DataFrame:
    """No pandas 3, colunas de texto têm tipo próprio ("str"), que recusa
    qualquer valor que não seja texto. As colunas de SMILES passam para o
    tipo genérico, para as atribuições abaixo nunca derrubarem a etapa."""
    for c in COLUNAS_SMILES:
        if c in df.columns:
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


URL_PUBCHEM_LOTE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/property/{}/JSON"
TAMANHO_LOTE = 200


def _smiles_por_cid(sessao, cids: list):
    """{CID: (SMILES, InChIKey)} de um lote de CIDs numa só consulta. None =
    falha de rede/servidor (o lote é tentado de novo depois)."""
    for props in ("SMILES,InChIKey", "IsomericSMILES,InChIKey"):
        try:
            r = sessao.post(URL_PUBCHEM_LOTE.format(props), data={"cid": ",".join(cids)},
                            headers=HEADERS, timeout=(10, 120))
        except requests.RequestException:
            return None
        if r.status_code == 400:
            continue                      # nome antigo/novo da propriedade: tenta o outro
        if r.status_code == 404:
            return {}
        if r.status_code == 429 or r.status_code >= 500:
            return None
        try:
            itens = r.json()["PropertyTable"]["Properties"]
        except (ValueError, KeyError, TypeError):
            return {}
        return {str(p.get("CID")): (next((p[k] for k in ("SMILES", "IsomericSMILES",
                                                          "CanonicalSMILES") if p.get(k)), ""),
                                    str(p.get("InChIKey") or "").upper())
                for p in itens}
    return {}


def completar_smiles_pubchem(df: pd.DataFrame) -> pd.DataFrame:
    """Coluna smiles_pubchem: o SMILES do PubChem para TODOS os compostos com
    InChIKey (para comparar com as bases). No composto_smiles, o PubChem só
    entra para os que NPASS, COCONUT e LOTUS não têm. Consultas em lote pelo
    CID (até 200 por vez) e, sem CID, uma a uma pelo InChIKey. Tudo em cache."""
    iks = sorted(set(df["composto_inchikey"].dropna()))
    if not iks:
        return df
    cache = {}
    if os.path.exists(CACHE_SMILES):
        with open(CACHE_SMILES, encoding="utf-8") as f:
            for linha in f:
                try:
                    item = json.loads(linha)
                    cache[item["inchikey"]] = _texto(item.get("smiles")) or ""
                except (ValueError, KeyError, TypeError, AttributeError):
                    continue
    novos = [ik for ik in iks if ik not in cache]
    print(f"  SMILES do PubChem: {len(iks)} composto(s) com InChIKey "
          f"({len(iks) - len(novos)} já em cache, {len(novos)} a consultar)")
    if novos:
        cid_por_ik = (df.dropna(subset=["composto_inchikey", "pubchem_cid"])
                      .drop_duplicates("composto_inchikey")
                      .set_index("composto_inchikey")["pubchem_cid"].astype(str)
                      .str.extract(r"^(\d+)")[0].dropna().to_dict())
        sessao = requests.Session()
        with open(CACHE_SMILES, "a", encoding="utf-8") as f:
            def guardar(ik, smi):
                smi = _texto(smi) or ""
                cache[ik] = smi
                f.write(json.dumps({"inchikey": ik, "smiles": smi}, ensure_ascii=False) + "\n")

            # 1) em lote, pelo CID (rápido)
            com_cid = [ik for ik in novos if ik in cid_por_ik]
            ik_por_cid = {}
            for ik in com_cid:
                ik_por_cid.setdefault(cid_por_ik[ik], []).append(ik)
            cids = list(ik_por_cid)
            falhas = 0
            if cids:
                print(f"  ... {len(com_cid)} pelo CID, em lotes de {TAMANHO_LOTE}")
            for n, ini in enumerate(range(0, len(cids), TAMANHO_LOTE), 1):
                lote = cids[ini:ini + TAMANHO_LOTE]
                res = _smiles_por_cid(sessao, lote)
                time.sleep(0.25)
                if res is None:
                    falhas += 1
                    if falhas >= 5:
                        print("  PubChem sem resposta em 5 lotes seguidos - o restante fica para "
                              "a próxima rodada da etapa.")
                        break
                    continue
                falhas = 0
                for cid in lote:
                    smi, ik_pc = res.get(cid, ("", ""))
                    for ik in ik_por_cid[cid]:
                        # o CID das bases às vezes é de outra forma da molécula
                        # (outro estereoisômero, sal): aí vale a busca pelo InChIKey
                        if smi and ik_pc == ik:
                            guardar(ik, smi)
                if n % 50 == 0:
                    f.flush()
                    print(f"  ... {min(ini + TAMANHO_LOTE, len(cids))}/{len(cids)} CIDs")
            # 2) um a um, pelo InChIKey (sem CID, ou CID de outra forma da molécula)
            restantes = [ik for ik in novos if ik not in cache]
            if restantes:
                print(f"  ... {len(restantes)} pelo InChIKey, um a um "
                      f"(cerca de {max(1, round(len(restantes) * 0.3 / 60))} min)")
            falhas = 0
            for i, ik in enumerate(restantes, 1):
                smi = _smiles_pubchem(sessao, ik)
                time.sleep(0.22)          # o PubChem aceita até 5 consultas por segundo
                if smi is None:
                    falhas += 1
                    if falhas >= MAX_FALHAS_PUBCHEM:
                        print(f"  PubChem sem resposta em {MAX_FALHAS_PUBCHEM} consultas seguidas - "
                              "o restante fica para a próxima rodada da etapa.")
                        break
                    continue
                falhas = 0
                guardar(ik, smi)
                if i % 500 == 0:
                    f.flush()
                    print(f"  ... {i}/{len(restantes)}")
    achados = {ik: t for ik, t in ((k, _texto(v)) for k, v in cache.items()) if t}
    df = _colunas_genericas(df)
    df["smiles_pubchem"] = [achados.get(ik) if isinstance(ik, str) else None
                            for ik in df["composto_inchikey"]]
    df["smiles_pubchem"] = df["smiles_pubchem"].astype(object)
    sem = df["composto_smiles"].isna() & df["smiles_pubchem"].notna()
    df["composto_smiles"] = df["composto_smiles"].where(~sem, df["smiles_pubchem"])
    df["fonte_smiles"] = df["fonte_smiles"].where(~sem, "PubChem")
    print(f"  SMILES do PubChem: {df.loc[df['smiles_pubchem'].notna(), 'composto_inchikey'].nunique()} "
          f"composto(s) com SMILES no PubChem; {df.loc[sem, 'composto_inchikey'].nunique()} "
          "deles só tinham estrutura lá")
    return df


# ---------------------------------------------------------------------------
# Conferência dos SMILES das fontes (RDKit, opcional)
# ---------------------------------------------------------------------------
def _comparar_smiles(smiles: dict, Chem) -> tuple[str | None, list]:
    """smiles = {fonte: SMILES}. Compara as ESTRUTURAS (não o texto: a mesma
    molécula pode ser escrita de várias formas). Devolve (resultado, fontes
    com SMILES inválido)."""
    canon, sem_estereo, invalidos = {}, {}, []
    for fonte, smi in smiles.items():
        m = Chem.MolFromSmiles(smi)
        if m is None:
            invalidos.append(fonte)
            continue
        canon[fonte] = Chem.MolToSmiles(m)
        sem_estereo[fonte] = Chem.MolToSmiles(m, isomericSmiles=False)
    partes = []
    if invalidos:
        partes.append("SMILES inválido: " + ", ".join(invalidos))
    if len(canon) >= 2:
        def agrupar(formas):    # fontes que concordam ficam juntas: "NPASS/PubChem x COCONUT"
            grupos = {}
            for fonte, c in formas.items():
                grupos.setdefault(c, []).append(fonte)
            return " x ".join("/".join(g) for g in grupos.values())
        if len(set(canon.values())) == 1:
            partes.append("mesma molécula")
        elif len(set(sem_estereo.values())) == 1:
            partes.append("estereoquímica diferente: " + agrupar(canon))
        else:
            partes.append("estruturas diferentes: " + agrupar(sem_estereo))
    return ("; ".join(partes) or None), invalidos


ORDEM_FONTES_SMILES = {"NPASS": "smiles_npass", "COCONUT": "smiles_coconut",
                       "LOTUS": "smiles_lotus", "PubChem": "smiles_pubchem"}


def conferir_smiles(df: pd.DataFrame) -> pd.DataFrame:
    """Com o RDKit: (1) valida o SMILES de cada fonte - se o escolhido for
    inválido, passa para a próxima fonte válida (NPASS > COCONUT > LOTUS >
    PubChem); (2) para compostos com SMILES em 2+ fontes, compara as
    estruturas. Resultado na coluna conferencia_smiles: "mesma molécula",
    "estereoquímica diferente: ...", "estruturas diferentes: ..." e/ou
    "SMILES inválido: ...". Sem o RDKit, a coluna fica vazia."""
    df = _colunas_genericas(df)
    df["conferencia_smiles"] = pd.Series(None, index=df.index, dtype=object)
    colunas = ORDEM_FONTES_SMILES
    alvo = df[df[list(colunas.values())].notna().any(axis=1)]
    if alvo.empty:
        return df
    try:
        from rdkit import Chem, RDLogger
        RDLogger.DisableLog("rdApp.*")
    except ImportError:
        print("  Conferência dos SMILES entre fontes: pulada (RDKit não instalado; para "
              "ativá-la: pip install rdkit no ambiente do pipeline).")
        return df
    chave = alvo["composto_inchikey"].fillna(alvo["base"] + ":" + alvo["composto_id"].astype(str))
    resultado, escolha = {}, {}
    for k, linha in alvo.assign(_k=chave).drop_duplicates("_k").set_index("_k").iterrows():
        smiles = {f: _texto(linha[c]) for f, c in colunas.items() if _texto(linha[c])}
        resultado[k], invalidos = _comparar_smiles(smiles, Chem)
        validas = [f for f in colunas if f in smiles and f not in invalidos]
        escolha[k] = (smiles[validas[0]], validas[0]) if validas else (None, None)
    # SMILES escolhido: o da primeira fonte VÁLIDA (os de outras bases, ex.: FooDB, ficam)
    conf, novo, nova_fonte = df["conferencia_smiles"].tolist(), df["composto_smiles"].tolist(), \
        df["fonte_smiles"].tolist()
    tem_fonte = df[list(colunas.values())].notna().any(axis=1).tolist()
    chave_todas = df["composto_inchikey"].fillna(
        df["base"] + ":" + df["composto_id"].astype(str)).tolist()
    for n, (tem, k) in enumerate(zip(tem_fonte, chave_todas)):    # por posição
        if tem:
            conf[n] = resultado.get(k)
            novo[n], nova_fonte[n] = escolha.get(k, (None, None))
    df["conferencia_smiles"] = pd.Series(conf, index=df.index, dtype=object)
    df["composto_smiles"] = pd.Series(novo, index=df.index, dtype=object)
    df["fonte_smiles"] = pd.Series(nova_fonte, index=df.index, dtype=object)
    contagem = {}
    for v in resultado.values():
        for parte in (v or "").split("; "):
            if parte:
                rotulo = parte.split(":")[0]
                contagem[rotulo] = contagem.get(rotulo, 0) + 1
    n2 = sum(1 for v in resultado.values() if v and ("molécula" in v or "diferente" in v))
    print(f"  Conferência dos SMILES ({n2} compostos com 2+ fontes válidas): "
          + (", ".join(f"{k} {v}" for k, v in contagem.items()) or "nada a comparar"))
    return df


def anexar_metadados(df: pd.DataFrame, especies: dict, generos: dict) -> pd.DataFrame:
    """Dados da planta (de plantas.csv) para cada linha, pelo nº da linha."""
    metas = df["_linha"].map(meta_da_linha)
    for campo in ["nome_cientifico", "reino", "familia", "nome_popular_pt", "fonte",
                  "na_regiao", "estados_br"]:
        df[campo] = metas.map(lambda m: m.get(campo))
    return df.drop(columns="_linha")


# ---------------------------------------------------------------------------
def preparar_bases():
    """Garante COCONUT e NPASS em dados/bioativos/, baixando só o que faltar.
    (A atualização para versões novas é feita pela etapa "downloads".)"""
    os.makedirs(PASTA_DADOS, exist_ok=True)
    print("COCONUT:")
    zip_coconut = os.path.join(PASTA_DADOS, "coconut_csv.zip")
    pasta_ext = os.path.join(PASTA_DADOS, "coconut_extraido")
    marcador = os.path.join(PASTA_DADOS, "coconut_versao.txt")
    if os.path.exists(zip_coconut) or os.path.exists(pasta_ext):
        versao = open(marcador, encoding="utf-8").read().strip() if os.path.exists(marcador) else zip_coconut
        print(f"  já baixado ({os.path.basename(versao)})")
    else:
        url = url_coconut()
        baixar(url, zip_coconut)
        with open(marcador, "w", encoding="utf-8") as f:
            f.write(url)
    if not os.path.exists(pasta_ext):
        print("  extraindo...")
        extrair_zip(zip_coconut, pasta_ext)
    print("NPASS:")
    for chave, nome in ARQUIVOS_NPASS.items():
        baixar(NPASS.format(nome), arquivo_npass(chave))


def arquivos_coconut() -> list:
    return [os.path.join(PASTA_DADOS, n) for n in
            ("coconut_csv.zip", "coconut_extraido", "coconut_versao.txt")]


def versao_coconut_instalada() -> str | None:
    marcador = os.path.join(PASTA_DADOS, "coconut_versao.txt")
    return open(marcador, encoding="utf-8").read().strip() if os.path.exists(marcador) else None


def main():
    global ESCOPO, REINO
    cfg = carregar_config_bioativos()
    ESCOPO = carregar_config_bioativos_escopo()
    REINO = carregar_config_bioativos_reino()
    if FC.descobertas():
        print(f"Fontes de compostos acrescentadas: {FC.resumo()}")
    print("Bases COCONUT e NPASS (baixadas na etapa 'downloads'; só baixa aqui o que faltar):")
    preparar_bases()

    print("\nCarregando plantas-alvo...")
    especies, generos = carregar_alvos()
    if ESCOPO == "completo":
        print("\n[bioativos] escopo = completo: entram os compostos de TODAS as plantas "
              "das bases\n  químicas, e não só os da região. As de fora ficam com "
              f"na_regiao = \"{FORA_DA_REGIAO}\".")
        if REINO == "qualquer":
            print("  [bioativos] reino = qualquer: entram organismos de qualquer reino "
                  "(bactérias,\n  fungos, metabólitos humanos), e não só plantas.")
        elif not carregar_generos_planta():
            ESCOPO = "regiao"
            print("  AVISO: sem o WFO e sem o WCVP não há como conferir, sem internet, se "
                  "um organismo\n  é planta. A etapa segue no escopo \"regiao\". Rode a "
                  "etapa \"downloads\" para baixá-los, ou use reino = qualquer para "
                  "dispensar\n  a conferência.")

    print("\nCruzando com NPASS...")
    npass = cruzar_npass(especies, generos)

    extras, colunas_extra = [], []
    for chave, modulo, rotulo, colunas, funcao, padrao in FONTES_EXTRA:
        # padrao None = base do pacote (a chave sempre existe no input.txt)
        if not (cfg.get(chave) if padrao is None else cfg.get(chave, padrao)):
            continue
        colunas_extra += colunas
        print(f"\nCruzando com {rotulo}...")
        try:
            modulo.baixar()
            extras.append(getattr(modulo, funcao)(casar, especies, generos))
        except Exception as e:  # base complementar: a etapa segue sem ela
            print(f"  AVISO: {rotulo} indisponível ({e}) - seguindo sem esta base.")
    colunas_saida = COLUNAS_BASE + COLUNAS_ENRIQUECIMENTO + colunas_extra

    print("\nCruzando com COCONUT (leitura em blocos)...")
    iks = set(npass["composto_inchikey"].dropna())
    for e in extras:
        if not e.empty:
            iks |= set(e["composto_inchikey"].dropna())
    coconut, tabela_enriq = processar_coconut(especies, generos, iks)

    print("\nConsolidando...")
    resultado = consolidar(npass, coconut, tabela_enriq, extras)
    if not resultado.empty and cfg.get("smiles_pubchem", True):
        resultado = completar_smiles_pubchem(resultado)
    if not resultado.empty:
        resultado = conferir_smiles(resultado)
    if resultado.empty:
        resultado = pd.DataFrame(columns=colunas_saida)
    else:
        resultado = anexar_metadados(resultado, especies, generos)
        # estados do composto: união dos estados de todas as plantas em que ocorre
        resultado["estados_br"] = resultado["estados_br"].fillna(DIST.DESCONHECIDA)
        chave_c = resultado["composto_inchikey"].fillna(
            resultado["base"] + ":" + resultado["composto_id"].astype(str))
        uniao = resultado.groupby(chave_c)["estados_br"].agg(DIST.juntar_estados)
        resultado["estados_composto"] = chave_c.map(uniao)
        # composto que só ocorre em plantas de fora da região: não é
        # "distribuição desconhecida" (que vale dentro da região), é "fora da região"
        if (resultado["na_regiao"] == FORA_DA_REGIAO).any():
            na_regiao = resultado.groupby(chave_c)["na_regiao"].agg(
                lambda v: (v != FORA_DA_REGIAO).any())
            so_fora = ~chave_c.map(na_regiao) & (resultado["estados_composto"] == DIST.DESCONHECIDA)
            resultado.loc[so_fora, "estados_composto"] = SEM_DISTRIBUICAO
        if cfg["apenas_com_atividade_npass"]:
            antes = len(resultado)
            resultado = resultado[resultado["atividade_ou_alvo"].notna()]
            print(f"  apenas_com_atividade_npass = true: {antes - len(resultado)} "
                  "linhas sem atividade registrada removidas")
        # organizado por composto: o mesmo composto em várias plantas fica junto
        resultado = resultado[colunas_saida]
        resultado = resultado.assign(_ordem=resultado["composto_nome"].fillna(
            resultado["composto_inchikey"]).fillna(resultado["composto_id"]).str.lower()) \
            .sort_values(["_ordem", "nome_cientifico"], na_position="last").drop(columns="_ordem")

    gravar_ocorrencias_brutas()
    gravar_csv(resultado, SAIDA)
    print(f"\nConcluído: {len(resultado)} pares espécie x composto em {SAIDA}")
    if GENERO_FORA and ESCOPO != "completo":
        print("\nGêneros da sua lista: espécies com compostos nas bases químicas que ficaram "
              "de fora (não estão no plantas.csv - nem na região do GBIF, nem nos artigos):")
        for g, especies_fora in sorted(GENERO_FORA.items()):
            nomes = sorted(e.capitalize() for e in especies_fora)
            print(f"  {g.capitalize()}: {len(nomes)} espécie(s) - {', '.join(nomes[:8])}"
                  + (" ..." if len(nomes) > 8 else ""))
    if not resultado.empty and ESCOPO == "completo":
        dentro = resultado["na_regiao"] != FORA_DA_REGIAO
        print(f"  escopo completo: {resultado.loc[dentro, 'nome_cientifico'].nunique()} plantas "
              f"da região e {resultado.loc[~dentro, 'nome_cientifico'].nunique()} de fora; "
              f"{resultado.loc[dentro, 'composto_inchikey'].nunique()} InChIKeys na região de "
              f"{resultado['composto_inchikey'].nunique()} no total")
    if not resultado.empty:
        print(f"  {resultado['nome_cientifico'].nunique()} plantas com compostos; "
              f"{resultado['composto_inchikey'].nunique()} InChIKeys distintos; "
              f"{resultado['atividade_ou_alvo'].notna().sum()} pares com atividade "
              "registrada no NPASS")
        print(f"  {resultado['pubchem_cid'].notna().sum()} pares com PubChem CID")
        fontes_smi = (resultado.dropna(subset=["composto_smiles"])
                      .assign(_c=lambda d: d["composto_inchikey"].fillna(d["composto_id"]))
                      .drop_duplicates("_c")["fonte_smiles"].fillna("?"))
        n_comp = resultado.assign(_c=resultado["composto_inchikey"].fillna(
            resultado["composto_id"]))["_c"].nunique()
        print(f"  SMILES: {len(fontes_smi)} de {n_comp} compostos; origem: "
              + ", ".join(f"{k} {v}" for k, v in fontes_smi.value_counts().items()))
        if "atividades_duke" in resultado:
            print(f"  {resultado['base'].str.contains('DUKE', na=False).sum()} pares vindos do "
                  f"Dr. Duke; {resultado['atividades_duke'].notna().sum()} com atividade registrada nele")
        if "referencias_lotus" in resultado:
            print(f"  {resultado['referencias_lotus'].notna().sum()} pares com referência (DOI) do LOTUS")
        if "teor_foodb" in resultado:
            print(f"  {resultado['base'].str.contains('FOODB', na=False).sum()} pares vindos do FooDB; "
                  f"{resultado['teor_foodb'].notna().sum()} com teor")
        print("\nPares por base:")
        print(resultado["base"].value_counts().to_string())
        print("\nPlantas com mais compostos:")
        print(resultado["nome_cientifico"].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()
