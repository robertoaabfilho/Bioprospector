"""
consultar_atividades_pubmed.py  -  ETAPA 5 ("pubmed")

Consulta resumos do PubMed sobre as atividades biológicas das PLANTAS e
dos COMPOSTOS de especies_com_compostos_bioativos.csv (etapa "bioativos")
e usa um modelo local (Ollama) para manter SOMENTE os artigos que relatam
uma relação POSITIVA de causa e efeito, como:
    "o extrato etanólico das folhas de X inibiu o crescimento de S. aureus"
    "o composto Z reduziu o edema de pata em ratos"
São descartados: uso tradicional/etnobotânico sem teste, simples menção,
resultados negativos ou não significativos, efeito atribuído a outra
espécie/composto, química analítica sem ensaio biológico, revisões.

Como os artigos de cada COMPOSTO são encontrados (duas vias combinadas):
  1. InChIKey (identificação pela estrutura, sem depender de nome):
       InChIKey -> CID no PubChem -> artigos do PubMed que o PubChem associa
       ao composto (indexação MeSH feita pela NLM + vínculos de depositantes)
       -> mantidos só os que tratam das atividades de [termos_pubmed].
       O CID vem do NPASS (coluna pubchem_cid) ou é obtido no PubChem.
  2. Nome (busca no título/resumo do PubMed), conforme
     busca_composto_por_nome em [pubmed]:
       complemento -> só para compostos SEM nenhum artigo vinculado no
                      PubChem (padrão)
       sempre      -> para todos os compostos com nome pesquisável
       nunca       -> só a via InChIKey
Os artigos das duas vias são somados (sem repetição) antes do modelo.

Plantas: são pesquisadas TODAS as espécies de plantas.csv (etapa
"plantas"), com ou sem compostos conhecidos - opção plantas_pesquisadas em
[pubmed] -, por todos os nomes de cada uma (nomes_busca), no título/resumo.
As que têm compostos vêm primeiro. Nomes não reconhecidos em nenhuma base
ficam de fora, salvo incluir_nao_reconhecidos = true.

Para cada artigo positivo o modelo informa também o TIPO DE ESTUDO
(in vitro, in vivo, ex vivo, clínico) e, para plantas, a PARTE DA PLANTA
testada (folha, casca, raiz...).

Fluxo (cada fase tem cache em disco: dá para interromper e retomar):
  1. PubChem: InChIKey, nome preferido e CID          -> cache_pubchem*.jsonl
  2. PubChem -> PubMed: artigos vinculados a cada CID -> cache_pubchem_vinculos.jsonl
  3. Filtro desses artigos pelas atividades           -> cache_pubmed_filtro.jsonl
  4. Buscas por nome (plantas e compostos)            -> cache_pubmed_buscas.jsonl
  5. Resumos                                          -> cache_pubmed_artigos.jsonl
  6. Pré-filtro de menção (só para a via por nome)
  7. Modelo (Ollama, saída JSON)                       -> cache_llm_classificacao.jsonl
  8. Consolidação

Saídas:
  atividades_plantas.csv   = uma linha por planta de plantas.csv
      atividades, melhor evidência, tipos de estudo, partes da planta,
      nº de compostos por base química
  atividades_compostos.csv = uma linha por composto (InChIKey)
      plantas de origem, atividades, melhor evidência, tipos de estudo,
      bases químicas, atividades do Dr. Duke, referências do LOTUS
      + colunas do ChEMBL (etapa "chembl")
  especies_atividades.csv  = combinado planta x composto: colunas de
      especies_com_compostos_bioativos.csv + InChIKey + atividades e
      estudos do composto e da planta + colunas do ChEMBL
  evidencias_pubmed.csv    = um artigo positivo por linha (PMID, título, ano,
      revista, DOI, atividades, tipo de estudo, parte da planta,
      justificativa do modelo, via da busca, link).

Requer Ollama rodando com o modelo do input.txt (seção [ollama]).
"""

import json
import os

import caminhos as _C
import re
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from urllib.parse import quote

import pandas as pd
import requests

from distribuicao import DESCONHECIDA, juntar_estados
from config_pipeline import COMANDO, NO_WINDOWS, carregar_config_ollama, gravar_csv
import literatura
from literatura import (ASSINATURA_FOCO, CFG_PUBMED, EUTILS, FOCO, PAUSA_NCBI, Disjuntor, sem_chave,
                        baixar_artigos, buscar_pmids, carregar_cache, criar_sessao,
                        esearch_post, filtros_atividade, finalizar, gravar_cache,
                        hash_curto, menciona, padroes_planta, params_ncbi,
                        query_planta, tqdm)

ENTRADA = "especies_com_compostos_bioativos.csv"
SAIDA = "especies_atividades.csv"
SAIDA_EVIDENCIAS = "evidencias_pubmed.csv"
SAIDA_PLANTAS = "atividades_plantas.csv"
SAIDA_COMPOSTOS = "atividades_compostos.csv"
COLUNAS_SMILES_FONTE = ["smiles_npass", "smiles_coconut", "smiles_lotus", "smiles_pubchem",
                        "conferencia_smiles"]
ENTRADA_CHEMBL = "compostos_chembl.csv"
ENTRADA_PLANTAS = "plantas.csv"
ENTRADA_DESCOBERTA = "plantas_artigos_evidencias.csv"   # artigos da descoberta (etapa 2)
# Com plantas_pesquisadas = com_compostos, as plantas sem compostos que a etapa 2
# achou em artigos da região com termos de atividade (coluna atividades_artigos)
# também são pesquisadas. Sem chave no input.txt: ligado por padrão.
CITADAS_EM_ARTIGOS = bool(CFG_PUBMED.get("plantas_citadas_em_artigos", True))
CACHE_PUBCHEM = _C.cache("cache_pubchem.jsonl")
CACHE_CID = _C.cache("cache_pubchem_cid.jsonl")
CACHE_VINCULOS = _C.cache("cache_pubchem_vinculos.jsonl")
CACHE_FILTRO = _C.cache("cache_pubmed_filtro.jsonl")
CACHE_LLM = _C.cache("cache_llm_classificacao.jsonl")

CFG_OLLAMA = carregar_config_ollama()
VERSAO_PROMPT = "v3"   # mude se alterar o prompt, para não reaproveitar o cache antigo
# respostas NEGATIVAS de versões anteriores do prompt continuam valendo (o
# critério de positivo não mudou; a v3 só acrescentou tipo de estudo e parte
# da planta, que não existem em artigos negativos) - evita reclassificar tudo
VERSOES_NEGATIVO_REAPROVEITAVEL = ["v2"]

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/"
PAUSA_PUBCHEM = 0.22
RE_INCHIKEY = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")
LOTE_ELINK = 100        # CIDs por consulta de vínculos
LOTE_FILTRO = 400       # PMIDs por consulta de filtro de atividade
LOTE_CID = 200          # InChIKeys por consulta de CID em lote

STATUS_SEM_BUSCA = "não pesquisado: sem vínculo no PubChem e sem nome adequado para busca"
STATUS_FORA_LIMITE = "não pesquisado: fora do limite max_compostos"
STATUS_SEM_ARTIGOS = "nenhum artigo encontrado no PubMed"
STATUS_PENDENTE = "busca pendente (rode de novo)"
STATUS_NAO_RECONHECIDO = ("não pesquisado: nome não reconhecido em nenhuma base "
                          "(incluir_nao_reconhecidos = false)")
STATUS_SO_COM_COMPOSTOS = "não pesquisado: plantas_pesquisadas = com_compostos"
STATUS_FORA_LIMITE_PLANTAS = "não pesquisado: fora do limite max_plantas"
STATUS_SEM_ESPECIE = "não pesquisado: táxon sem nível de espécie"
STATUS_LLM_PENDENTE = "artigos encontrados; leitura pelo modelo pendente"
# --parcial: gera as planilhas só com o que o modelo já leu (não lê nada novo).
# Pode rodar numa 2ª janela enquanto a etapa continua na 1ª.
PARCIAL = "--parcial" in sys.argv
if PARCIAL:
    # modo parcial: NÃO toca a internet (só caches) e grava em arquivos
    # *_parcial.csv, para não se confundir com o resultado final (nem fazer o
    # --retomar achar que a etapa terminou)
    literatura.SO_CACHE = True
    SAIDA, SAIDA_EVIDENCIAS, SAIDA_PLANTAS, SAIDA_COMPOSTOS = (
        n.replace(".csv", "_parcial.csv") for n in (SAIDA, SAIDA_EVIDENCIAS, SAIDA_PLANTAS, SAIDA_COMPOSTOS))
STATUS_SEM_POSITIVO = ("nenhuma relação causal positiva encontrada"
                       + (" para as atividades de [termos_pubmed]" if FOCO else ""))

VOCABULARIO = (
    "antioxidante, anti-inflamatória, antibacteriana, antifúngica, antiviral, "
    "antiparasitária, antiprotozoária, antimalárica, leishmanicida, tripanocida, "
    "anti-helmíntica, larvicida, inseticida, acaricida, repelente, moluscicida, "
    "herbicida, citotóxica, antitumoral, antiproliferativa, pró-apoptótica, "
    "analgésica, antinociceptiva, antipirética, cicatrizante, hepatoprotetora, "
    "nefroprotetora, neuroprotetora, cardioprotetora, gastroprotetora, "
    "antiulcerogênica, imunomoduladora, antialérgica, antidiabética, "
    "hipoglicemiante, hipolipemiante, anti-obesidade, anti-hipertensiva, "
    "vasodilatadora, antitrombótica, antiplaquetária, ansiolítica, sedativa, "
    "antidepressiva, anticonvulsivante, antiespasmódica, diurética, "
    "fotoprotetora, antienvelhecimento, antiveneno, "
    "inibição de <enzima> (ex.: inibição de acetilcolinesterase)"
)

TIPOS_ESTUDO = ["clínico", "in vivo", "ex vivo", "in vitro"]   # da evidência mais forte à mais fraca
SEM_INFORMACAO = "não informado"
PARTES = [  # (rótulo, padrões em português/inglês)
    ("folha", r"folh|leaf|leaves|foliar"),
    ("casca", r"casca|bark|peel|rind|pericarp"),
    ("raiz", r"raiz|ra[ií]zes|root"),
    ("rizoma", r"rizoma|rhizome"),
    ("tubérculo/bulbo", r"tub[eé]rcul|tuber|bulb"),
    ("caule", r"caule|stem|twig|ramo|galho|wood|madeira|cerne|heartwood|trunk|tronco"),
    ("flor", r"\bflor|flower|inflorescen|petal"),
    ("fruto", r"fruto|fruit|berr|polpa|pulp|epicarp|mesocarp"),
    ("semente", r"semente|seed|kernel|am[eê]ndoa|nut\b"),
    ("parte aérea", r"a[eé]rea|aerial"),
    ("planta inteira", r"inteira|whole"),
    ("exsudato (látex/resina)", r"l[aá]tex|resin|resina|oleo-?resin|gum\b|goma|sap\b|seiva|exsudat"),
    ("broto/calo/cultura", r"brot|sprout|callus|calo|cultura|culture|cell suspension"),
]
TIPOS_ESTUDO_RE = [
    ("clínico", r"cl[ií]nic|human|humano|paciente|patient|volunt[aá]ri|trial"),
    ("in vivo", r"in vivo|animal|rat|mouse|mice|camundong|zebrafish|rato"),
    ("ex vivo", r"ex vivo"),
    ("in vitro", r"in vitro|cel|cell|enzim|enzym|bact|fung|cultur"),
]

PROMPT_SISTEMA = (
    "Você é um farmacologista especialista em produtos naturais que avalia "
    "evidências científicas com rigor. Responda sempre e somente com JSON válido."
)

PROMPT_USUARIO = """Leia o título e o resumo abaixo e decida se eles relatam uma RELAÇÃO POSITIVA DE CAUSA E EFEITO para a seguinte entidade:

ENTIDADE: {entidade}
TIPO: {descricao_tipo}

{foco}Considere POSITIVO (true) somente se o texto relatar um RESULTADO EXPERIMENTAL (in vitro, in vivo, ex vivo ou clínico) em que {regra_entidade} PRODUZIU um efeito biológico/farmacológico.
Exemplos positivos: "o extrato inibiu o crescimento de S. aureus (CIM 125 µg/mL)"; "o composto reduziu o edema de pata em 45%"; "o óleo apresentou atividade larvicida contra Aedes aegypti (CL50 = 30 ppm)".

Considere NEGATIVO (false) se:
- a entidade é só mencionada, ou o texto trata de outra espécie/composto;
- é apenas uso tradicional/etnobotânico, sem teste experimental;
- o resultado foi nulo, fraco/não significativo, ou a entidade foi "inativa";
- o artigo é só de química analítica, isolamento ou identificação estrutural, sem ensaio de atividade;
- é uma revisão ou especulação ("pode ter", "potencialmente útil") sem dado experimental próprio.

{instrucao_atividades}

Em "tipo_estudo", liste o(s) tipo(s) de experimento em que o efeito foi demonstrado, usando somente: "in vitro" (células, enzimas, microrganismos), "ex vivo" (tecidos/órgãos isolados), "in vivo" (animais) ou "clínico" (seres humanos). Estudos apenas in silico (docking, simulação computacional) NÃO contam como resultado experimental.
{instrucao_parte}
Responda APENAS com este JSON:
{{"relacao_causal_positiva": true ou false, "atividades": ["..."], "tipo_estudo": ["..."],{campo_parte} "justificativa": "uma frase curta citando o resultado"}}

TÍTULO: {titulo}

RESUMO: {resumo}"""


# =============================================================================
# Nomes de compostos
# =============================================================================
def inchikey_valido(valor) -> str | None:
    if not isinstance(valor, str):
        return None
    v = valor.strip().upper()
    return v if RE_INCHIKEY.match(v) else None


def limpar_nome(nome):
    """Remove prefixos estereoquímicos simples, que os resumos costumam
    omitir: '(-)-epicatechin' -> 'epicatechin', '(E)-caryophyllene' ->
    'caryophyllene'."""
    if not isinstance(nome, str):
        return nome
    return re.sub(r"^(?:\((?:[+-]|±|[EZRS]|[+-]/[+-])\)-)+", "", nome.strip())


def nome_pesquisavel(nome) -> bool:
    """Descarta IDs de banco e nomes sistemáticos (IUPAC), que quase nunca
    aparecem literalmente em resumos e geram buscas inúteis."""
    if not isinstance(nome, str):
        return False
    n = nome.strip()
    if not 3 <= len(n) <= 60:
        return False
    if re.match(r"^(NPC|CNP|CHEMBL|CID|NPASS)\s*\d+", n, re.I):
        return False
    if any(ch in n for ch in "[]{},;") or n.count("(") > 1 or "..." in n:
        return False
    # locantes estereoquímicos típicos de IUPAC: (2S), (3R,4S), 5R
    if re.search(r"\(\d+[RSEZ]|\b\d+[RS]\b", n):
        return False
    if sum(ch.isdigit() for ch in n) > 3:
        return False
    return True


# =============================================================================
# 1. PubChem: InChIKey, nome preferido e CID
# =============================================================================
def consultar_pubchem(sessao, inchikey: str | None, nome: str | None) -> dict | None:
    """Retorna {"inchikey", "titulo", "cid"} (campos podem ser None quando o
    PubChem não conhece o composto). None = falha de rede: não deve ir para o
    cache, para ser tentado de novo na próxima execução."""
    urls, falhou = [], False
    if inchikey:
        urls.append(f"{PUBCHEM}inchikey/{inchikey}/property/InChIKey,Title/JSON")
    if nome and nome_pesquisavel(nome):
        urls.append(f"{PUBCHEM}name/{quote(nome, safe='')}/property/InChIKey,Title/JSON")
    for url in urls:
        try:
            r = sessao.get(url, timeout=30)
            time.sleep(PAUSA_PUBCHEM)
            if r.status_code == 404:
                continue
            r.raise_for_status()
            props = r.json()["PropertyTable"]["Properties"][0]
            return {"inchikey": inchikey_valido(props.get("InChIKey")),
                    "titulo": props.get("Title"),
                    "cid": str(props["CID"]) if props.get("CID") else None}
        except requests.RequestException:
            falhou = True
            continue
        except (KeyError, IndexError, ValueError):
            continue
    return None if falhou else {"inchikey": None, "titulo": None, "cid": None}


def titulos_em_lote(sessao, cids: list) -> dict | None:
    """{cid: (titulo, inchikey)} para um lote de CIDs, numa única chamada ao
    PubChem. None = falha (tenta de novo depois)."""
    try:
        r = sessao.post(f"{PUBCHEM}cid/property/Title,InChIKey/JSON",
                        data={"cid": ",".join(cids)}, timeout=120)
        time.sleep(PAUSA_PUBCHEM)
        r.raise_for_status()
        props = r.json()["PropertyTable"]["Properties"]
    except (requests.RequestException, ValueError, KeyError):
        return None
    return {str(p["CID"]): (p.get("Title"), inchikey_valido(p.get("InChIKey")))
            for p in props if p.get("CID")}


def cid_por_inchikey(sessao, inchikey: str) -> str | None | bool:
    """CID de um InChIKey. None = não existe no PubChem; False = falha."""
    try:
        r = sessao.get(f"{PUBCHEM}inchikey/{inchikey}/cids/JSON", timeout=30)
        time.sleep(PAUSA_PUBCHEM)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        cids = r.json().get("IdentifierList", {}).get("CID", [])
        return str(cids[0]) if cids and cids[0] else None
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return False


def cids_em_lote(sessao, inchikeys: list) -> dict | None:
    """{inchikey: cid} para um lote de InChIKeys, em duas chamadas ao NCBI
    (esearch no banco de compostos do PubChem + esummary para saber qual
    CID corresponde a qual InChIKey). Só devolve correspondências exatas;
    o que faltar é resolvido um a um por cid_por_inchikey. None = falha."""
    termo = " OR ".join(f"{ik}[InChIKey]" for ik in inchikeys)
    try:
        r = sessao.post(EUTILS + "esearch.fcgi", timeout=120, data={
            **params_ncbi(), "db": "pccompound", "term": termo,
            "retmode": "json", "retmax": len(inchikeys) * 3})
        r.raise_for_status()
        cids = r.json()["esearchresult"].get("idlist", [])
        time.sleep(PAUSA_NCBI)
        if not cids:
            return {}
        r = sessao.post(EUTILS + "esummary.fcgi", timeout=120, data={
            **params_ncbi(), "db": "pccompound", "id": ",".join(cids), "retmode": "json"})
        r.raise_for_status()
        resultado = r.json().get("result", {})
    except (requests.RequestException, ValueError, KeyError):
        return None
    finally:
        time.sleep(PAUSA_NCBI)
    pedidos = set(inchikeys)
    encontrados = {}
    for cid in resultado.get("uids", []):
        doc = resultado.get(cid) or {}
        ik = inchikey_valido(doc.get("inchikey") or doc.get("InChIKey"))
        if ik in pedidos:   # o menor CID vence (registro principal do PubChem)
            atual = encontrados.get(ik)
            if atual is None or int(cid) < int(atual):
                encontrados[ik] = str(cid)
    return encontrados


def _obj(df: pd.DataFrame, valores: list) -> pd.Series:
    """Coluna de tipo genérico: mantém None (o pandas 3 trocaria por NaN,
    que conta como 'verdadeiro' em testes como `if valor`)."""
    return pd.Series(valores, index=df.index, dtype=object)


def texto_ou_none(valor) -> str | None:
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def cid_valido(valor) -> str | None:
    if valor is None or (isinstance(valor, float) and valor != valor):
        return None
    texto = str(valor).strip()
    texto = texto[:-2] if texto.endswith(".0") else texto
    return texto if texto.isdigit() else None


def chave_composto(df: pd.DataFrame) -> pd.Series:
    ik = df["composto_inchikey"].map(inchikey_valido)
    return ik.fillna("nome:" + df["composto_nome"].fillna(df["composto_id"].astype(str)).str.lower())


def preparar_compostos(df: pd.DataFrame, sessao) -> pd.DataFrame:
    """Uma linha por composto distinto, com InChIKey final, CID, termos de
    busca por nome e prioridade."""
    if df.empty:
        return pd.DataFrame(columns=["_chave", "inchikey", "nome", "cid_npass", "n_especies",
                                     "tem_atividade", "inchikey_final", "titulo_pubchem",
                                     "cid", "termos", "nome_exibicao"])
    df = df.copy()
    df["_ik"] = df["composto_inchikey"].map(inchikey_valido)
    df["_chave"] = chave_composto(df)
    df["_cid"] = (df["pubchem_cid"].astype(str).str.extract(r"^(\d+)")[0]
                  if "pubchem_cid" in df.columns else None)

    compostos = df.groupby("_chave", sort=False).agg(
        inchikey=("_ik", "first"),
        nome=("composto_nome", "first"),
        cid_npass=("_cid", "first"),
        n_especies=("nome_cientifico", "nunique"),
        tem_atividade=("atividade_ou_alvo", lambda s: s.notna().any()),
    ).reset_index()

    cache = carregar_cache(CACHE_PUBCHEM, "chave")
    pendentes = compostos[~compostos["_chave"].isin(cache.keys())]
    if PARCIAL:
        pendentes = pendentes.iloc[0:0]   # modo parcial: só o cache
    if len(pendentes):
        print(f"PubChem: consultando {len(pendentes)} composto(s) "
              f"({len(compostos) - len(pendentes)} já em cache)...")

    # 1) compostos com InChIKey: CID e nome em LOTES (2 + 1 chamadas por 200
    #    compostos, em vez de 1 por composto)
    com_ik = pendentes[pendentes["inchikey"].map(lambda x: isinstance(x, str) and bool(x)).astype(bool)]
    chave_por_ik = dict(zip(com_ik["inchikey"], com_ik["_chave"]))
    iks = sorted(chave_por_ik)
    lotes = [iks[i:i + LOTE_CID] for i in range(0, len(iks), LOTE_CID)]
    nao_achados = []
    disjuntor = Disjuntor("PubChem (em lote)")
    for lote in tqdm(lotes, desc="PubChem (em lote)"):
        achados = cids_em_lote(sessao, lote)
        if achados is None:
            if disjuntor.falha():
                break
            continue                       # falha: fica para a próxima execução
        titulos = titulos_em_lote(sessao, sorted(set(achados.values()))) if achados else {}
        if titulos is None:
            if disjuntor.falha():
                break
            continue
        disjuntor.sucesso()
        for ik in lote:
            if ik in achados:
                cid = achados[ik]
                titulo = (titulos.get(cid) or (None, None))[0]
                item = {"chave": chave_por_ik[ik], "inchikey": ik, "titulo": titulo, "cid": cid}
                cache[item["chave"]] = item
                gravar_cache(CACHE_PUBCHEM, item)
            else:
                nao_achados.append(ik)

    # 2) o resto, um a um: InChIKeys que o lote não achou e compostos só com nome
    um_a_um = pendentes[~pendentes["_chave"].isin(cache.keys())]
    if len(um_a_um):
        print(f"PubChem: {len(um_a_um)} composto(s) conferidos um a um "
              f"({len(nao_achados)} InChIKey(s) não achados em lote; o resto só tem nome)")
    disjuntor = Disjuntor("PubChem (um a um)")
    for _, c in tqdm(list(um_a_um.iterrows()), desc="PubChem (um a um)"):
        res = consultar_pubchem(sessao, c["inchikey"], c["nome"])
        if res is None:
            if disjuntor.falha():
                break
            continue                       # falha de rede: tenta de novo depois
        disjuntor.sucesso()
        item = {"chave": c["_chave"], **res}
        cache[c["_chave"]] = item
        gravar_cache(CACHE_PUBCHEM, item)

    compostos["inchikey_final"] = _obj(compostos, [
        inchikey_valido(ik) or inchikey_valido(cache.get(ch, {}).get("inchikey"))
        for ik, ch in zip(compostos["inchikey"], compostos["_chave"])])
    compostos["titulo_pubchem"] = _obj(compostos, [
        texto_ou_none(cache.get(ch, {}).get("titulo")) for ch in compostos["_chave"]])
    compostos["nome"] = _obj(compostos, [texto_ou_none(n) for n in compostos["nome"]])

    # CID: NPASS > consulta anterior ao PubChem > busca pelo InChIKey
    cid = [cid_valido(c) or cid_valido(cache.get(ch, {}).get("cid"))
           for c, ch in zip(compostos["cid_npass"], compostos["_chave"])]
    compostos["cid"] = _obj(compostos, cid)
    cache_cid = carregar_cache(CACHE_CID, "inchikey")
    # (só para InChIKeys ainda sem CID; o resultado fica em cache_pubchem_cid,
    # então cada InChIKey é procurado uma única vez)
    faltando = sorted({ik for ik, c, ch in zip(compostos["inchikey_final"], compostos["cid"],
                                               compostos["_chave"])
                       if ik and not c and ik not in cache_cid and not (cache.get(ch) or {}).get("cid")}) if not PARCIAL else []
    if faltando:
        print(f"PubChem: obtendo o CID de {len(faltando)} InChIKey(s) "
              f"({len(cache_cid)} já em cache), em lotes de {LOTE_CID}...")
    lotes = [faltando[i:i + LOTE_CID] for i in range(0, len(faltando), LOTE_CID)]
    disjuntor = Disjuntor("PubChem (CID em lote)")
    for lote in tqdm(lotes, desc="PubChem (CID em lote)"):
        res = cids_em_lote(sessao, lote)
        if res is None:
            if disjuntor.falha():
                break
        else:
            disjuntor.sucesso()
        for ik, cid in (res or {}).items():
            cache_cid[ik] = {"inchikey": ik, "cid": cid}
            gravar_cache(CACHE_CID, cache_cid[ik])
    faltando = [ik for ik in faltando if ik not in cache_cid]
    if faltando:
        print(f"PubChem: {len(faltando)} InChIKey(s) não resolvidos em lote - "
              "conferindo um a um...")
    disjuntor = Disjuntor("PubChem (CID)")
    for ik in tqdm(faltando, desc="PubChem (CID)"):
        res = cid_por_inchikey(sessao, ik)
        if res is False:
            if disjuntor.falha():
                break
            continue  # falha de rede: tenta de novo na próxima execução
        disjuntor.sucesso()
        cache_cid[ik] = {"inchikey": ik, "cid": res}
        gravar_cache(CACHE_CID, cache_cid[ik])
    compostos["cid"] = _obj(compostos, [
        c or (cid_valido(cache_cid.get(ik, {}).get("cid")) if ik else None)
        for c, ik in zip(compostos["cid"], compostos["inchikey_final"])])

    def termos(linha):
        candidatos = [limpar_nome(linha["titulo_pubchem"]), limpar_nome(linha["nome"])]
        vistos, saida = set(), []
        for t in candidatos:
            if nome_pesquisavel(t) and t.strip().lower() not in vistos:
                vistos.add(t.strip().lower())
                saida.append(t.strip())
        return saida[:2]

    compostos["termos"] = compostos.apply(termos, axis=1)
    compostos["nome_exibicao"] = _obj(compostos, [
        (t[0] if t else None) or tp or n or ik or ch
        for t, tp, n, ik, ch in zip(compostos["termos"], compostos["titulo_pubchem"],
                                    compostos["nome"], compostos["inchikey_final"],
                                    compostos["_chave"])])
    compostos = compostos.sort_values(["tem_atividade", "n_especies"], ascending=False)
    return compostos.reset_index(drop=True)


# =============================================================================
# 2-3. Via InChIKey: artigos vinculados no PubChem, filtrados por atividade
# =============================================================================
RESPOSTA_CORTADA = "cortada"   # elink_lote: resposta grande demais, interrompida no meio


def elink_lote(sessao, cids: list, avisar: bool = True) -> dict | str | None:
    """{cid: [pmids]} para um lote de CIDs (todos os vínculos PubChem->PubMed:
    MeSH, depositantes e editoras). None se o servidor falhou; RESPOSTA_CORTADA
    se a resposta veio interrompida ou incompleta (lotes com substâncias muito
    citadas, como o ácido acético, com ~40 mil artigos, passam do que o NCBI
    entrega de uma vez): aí quem chama divide o lote."""
    dados = [(k, v) for k, v in params_ncbi().items()]
    dados += [("dbfrom", "pccompound"), ("db", "pubmed"), ("retmode", "json")]
    dados += [("id", c) for c in cids]
    try:
        r = sessao.post(EUTILS + "elink.fcgi", data=dados, timeout=120)
        r.raise_for_status()
        conjuntos = r.json().get("linksets", [])
    except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ContentDecodingError,
            ValueError) as e:
        if len(cids) > 1:
            return RESPOSTA_CORTADA
        if avisar:
            print(f"  ! elink falhou para o CID {cids[0]} ({sem_chave(e)}) - será tentado na próxima execução")
        return None
    except requests.RequestException as e:
        if avisar:
            print(f"  ! elink falhou ({sem_chave(e)}) - será tentado na próxima execução")
        return None
    finally:
        time.sleep(PAUSA_NCBI)
    resultado = {str(c): set() for c in cids}
    for ls in conjuntos:
        ids = [str(i) for i in ls.get("ids", [])]
        for db in ls.get("linksetdbs", []):
            if db.get("dbto") == "pubmed":
                for cid in ids:
                    resultado.setdefault(cid, set()).update(str(p) for p in db.get("links", []))
    return {c: sorted(p) for c, p in resultado.items()}


def vinculos_pubchem(sessao, cids: list) -> dict:
    cache = carregar_cache(CACHE_VINCULOS, "cid")
    pendentes = [c for c in cids if c not in cache] if not PARCIAL else []
    print(f"PubChem -> PubMed: {len(pendentes)} CID(s) a consultar "
          f"({len(cids) - len(pendentes)} em cache)")
    lotes = [pendentes[i:i + LOTE_ELINK] for i in range(0, len(pendentes), LOTE_ELINK)]
    disjuntor = Disjuntor("PubChem vínculos")
    divididos = 0
    for lote in tqdm(lotes, desc="PubChem vínculos"):
        fila, parar = [lote], False
        while fila:
            parte = fila.pop()
            res = elink_lote(sessao, parte)
            if res == RESPOSTA_CORTADA:   # resposta grande demais: tenta as duas metades
                meio = len(parte) // 2
                fila += [parte[meio:], parte[:meio]]
                divididos += 1
                continue
            if res is None:
                if disjuntor.falha():
                    parar = True
                    break
                continue
            disjuntor.sucesso()
            for cid in parte:
                cache[cid] = {"cid": cid, "pmids": res.get(cid, [])}
                gravar_cache(CACHE_VINCULOS, cache[cid])
        if parar:
            break
    if divididos:
        print(f"  {divididos} lote(s) com resposta grande demais (substâncias muito citadas) "
              "foram divididos em consultas menores")
    return {c: cache[c]["pmids"] for c in cids if c in cache}


def filtrar_por_atividade(sessao, pmids: set, filtros: list) -> dict:
    """{rótulo: set(pmids)} - quais PMIDs (vindos dos vínculos) tratam de
    cada atividade, com resumo e (se configurado) sem revisões."""
    linhas = carregar_cache(CACHE_FILTRO, "chave").values()
    aprovados = {}
    for rotulo, filtro in filtros:
        assinatura = hash_curto(finalizar(filtro))
        verificados, ok = set(), set()
        for item in linhas:
            if item.get("filtro") == assinatura:
                verificados.update(item["verificados"])
                ok.update(item["aprovados"])
        faltando = sorted(pmids - verificados, key=int) if not PARCIAL else []
        lotes = [faltando[i:i + LOTE_FILTRO] for i in range(0, len(faltando), LOTE_FILTRO)]
        rotulo_txt = rotulo or "geral"
        if lotes:
            print(f"Filtro '{rotulo_txt}': {len(faltando)} artigo(s) vinculado(s) a verificar "
                  f"({len(pmids) - len(faltando)} em cache)")
        disjuntor = Disjuntor(f"Filtro {rotulo_txt}")
        for lote in tqdm(lotes, desc=f"Filtro {rotulo_txt}"):
            ids = " OR ".join(f"{p}[uid]" for p in lote)
            consulta = finalizar(f"({ids}) AND hasabstract AND {filtro}")
            res = esearch_post(sessao, consulta, len(lote))
            if res is None:
                if disjuntor.falha():
                    break
                continue
            disjuntor.sucesso()
            item = {"chave": f"{assinatura}|{hash_curto(','.join(lote))}",
                    "filtro": assinatura, "verificados": lote, "aprovados": res}
            gravar_cache(CACHE_FILTRO, item)
            ok.update(res)
        aprovados[rotulo] = ok & pmids
    return aprovados


# =============================================================================
# 4. Busca por nome
# =============================================================================
def query_composto(termos: list, filtro: str) -> str:
    alternativa = " OR ".join(f'"{t}"[tiab]' for t in termos)
    return finalizar(f"({alternativa}) AND hasabstract AND {filtro}")


def padroes_composto(termos: list) -> list:
    return [re.compile(rf"(?<![\w-]){re.escape(t)}(?![\w-])", re.I) for t in termos]


def pre_checagem(sessao, buscas: list, filtros: list) -> tuple:
    """Evita uma busca por atividade para quem não tem NENHUM artigo.

    Para cada planta/composto, faz antes UMA busca com todas as atividades
    juntas (OU). Só se ela trouxer algum artigo são feitas as buscas por
    atividade. Como a grande maioria das plantas não tem artigo nenhum sobre
    as atividades, isso troca N buscas por 1. Entidades cujas buscas por
    atividade já estão todas no cache não passam pela pré-checagem.
    Retorna (buscas a fazer, {entidades sem nenhum artigo})."""
    if len(filtros) < 2:
        return buscas, set()
    from literatura import CACHE_BUSCAS
    cache = carregar_cache(CACHE_BUSCAS, "chave")
    filtro_total = "(" + " OR ".join(f for _, f in filtros) + ")"
    por_ent = {}
    for b in buscas:
        por_ent.setdefault(b[1], []).append(b)

    prontas, pre = [], []
    for ent, bs in por_ent.items():
        if all((cache.get(cb) or {}).get("query") == q and (cache.get(cb) or {}).get("retmax") == rm
               for cb, _, q, rm in bs):
            prontas.extend(bs)            # já buscado antes, atividade por atividade
            continue
        _, f0 = filtros[0]
        q0 = bs[0][2]
        # mesma consulta da 1ª atividade, trocando o filtro pelo filtro conjunto
        consulta = q0.replace(f0, filtro_total, 1) if f0 in q0 else None
        if consulta is None:
            prontas.extend(bs)
            continue
        pre.append((f"pre|{ent}", consulta, 1, ent))
    if not pre:
        return prontas, set()
    print(f"Pré-checagem: {len(pre)} planta(s)/composto(s) - uma busca com todas as "
          f"{len(filtros)} atividades juntas antes das buscas por atividade")
    res = buscar_pmids(sessao, [(c, q, rm) for c, q, rm, _ in pre], descricao="PubMed (pré-checagem)")
    sem_artigo, com_artigo = set(), 0
    for chave, _, _, ent in pre:
        if chave not in res:
            continue                      # falhou: fica pendente para a próxima execução
        if res[chave]:
            prontas.extend(por_ent[ent])
            com_artigo += 1
        else:
            sem_artigo.add(ent)
    print(f"  {com_artigo} com algum artigo (seguem para as buscas por atividade); "
          f"{len(sem_artigo)} sem nenhum (buscas por atividade evitadas: "
          f"{len(sem_artigo) * (len(filtros) - 1)})")
    return prontas, sem_artigo


# =============================================================================
# 5. Classificação com modelo (Ollama)
# =============================================================================
def _iniciar_ollama_local(url: str) -> bool:
    """Se o Ollama local está fora do ar, inicia `ollama serve` com
    OLLAMA_NUM_PARALLEL = [ollama] paralelo (registro em resultados/logs/
    ollama.log; o painel o reconhece pelo ollama.pid). True se ficou no ar."""
    import processos
    binario = processos.ollama_bin()
    if not binario or not re.match(r"https?://(localhost|127\.0\.0\.1)(:\d+)?/?$", url):
        return False
    env = processos.env_ollama(CFG_OLLAMA.get("paralelo"))
    print("Ollama fora do ar: iniciando `ollama serve`"
          + (f" com OLLAMA_NUM_PARALLEL={env['OLLAMA_NUM_PARALLEL']}" if env else "")
          + f" (registro em {_C.LOGS / 'ollama.log'})")
    try:
        proc = processos.iniciar([binario, "serve"], _C.LOGS / "ollama.log", _C.RAIZ, env_extra=env)
    except OSError as e:   # ex.: Windows, ollama.log preso por um Ollama antigo que não responde
        print(f"  ! não foi possível iniciar o Ollama ({e})")
        return False
    (_C.LOGS / "ollama.pid").write_text(str(proc.pid))
    for _ in range(30):
        time.sleep(1)
        try:
            if requests.get(f"{url}/api/tags", timeout=2).ok:
                return True
        except requests.RequestException:
            pass
    return False


def verificar_ollama():
    url, modelo = CFG_OLLAMA["url"], CFG_OLLAMA["modelo"]
    try:
        r = requests.get(f"{url}/api/tags", timeout=5)
        r.raise_for_status()
    except requests.RequestException:
        r = None
    if r is None and _iniciar_ollama_local(url):
        r = requests.get(f"{url}/api/tags", timeout=5)
    if r is None:
        sys.exit(f"ERRO: Ollama não está acessível em {url}. Esta etapa precisa "
                 "do Ollama para filtrar os artigos.\n"
                 + ("  1) Instale: https://ollama.com/download\n" if NO_WINDOWS else
                    "  1) Instale: curl -fsSL https://ollama.com/install.sh | sh\n")
                 + f"  2) Baixe o modelo: ollama pull {modelo}\n"
                 + ("  3) Deixe rodando: ollama serve\n" if NO_WINDOWS else
                    "  3) Deixe rodando: sudo systemctl start ollama  (ou: ollama serve)\n")
                 + f"Depois rode: {COMANDO} --a-partir-de pubmed")
    modelos = [m["name"] for m in r.json().get("models", [])]
    if not any(m == modelo or m.startswith(modelo + ":") or m.split(":")[0] == modelo
               for m in modelos):
        sys.exit(f"ERRO: modelo '{modelo}' não encontrado no Ollama. Baixe com: "
                 f"ollama pull {modelo}\nModelos disponíveis: {', '.join(modelos) or 'nenhum'}")
    n_paralelo = max(1, int(CFG_OLLAMA.get("paralelo") or 1))
    if n_paralelo > 1:
        import processos
        no_servidor = processos.paralelo_do_ollama()
        if no_servidor is not None and no_servidor < n_paralelo:
            print(f"AVISO: [ollama] paralelo = {n_paralelo}, mas o Ollama em execução aceita só "
                  f"{no_servidor} pedido(s) por vez (OLLAMA_NUM_PARALLEL): os demais esperam na fila "
                  "e a leitura fica mais lenta. Pare o Ollama e rode esta etapa de novo (o pipeline "
                  "o inicia já com o valor certo), ou reinicie-o com "
                  f"OLLAMA_NUM_PARALLEL={n_paralelo} ollama serve (README, seção 17).")
    if re.search(r"[:\-]([1-4](\.\d)?)b\b", modelo):
        print(f"AVISO: '{modelo}' é muito pequeno para julgar causalidade com "
              "confiabilidade; prefira qwen3.5:35b-a3b (input.txt, seção [ollama]).")


def normalizar_atividade(a: str) -> str:
    a = str(a).strip().lower().strip(" .;:-\"'")
    a = re.sub(r"^(atividades?|efeitos?|a[cç][aã]o)\s+(de\s+)?", "", a)
    return re.sub(r"\s+", " ", a)


def rotulo_do_foco(atividade: str) -> str | None:
    """Associa a atividade devolvida pelo modelo a um rótulo de [termos_pubmed]
    (pelo próprio rótulo ou por um dos termos dele); None se não casar."""
    a = atividade.lower()
    for rotulo, termos in FOCO.items():
        candidatos = [rotulo] + [re.sub(r"\[.*?\]|[\"*]", "", t).strip().lower() for t in termos]
        if any(c and (c == a or c in a or (len(a) >= 4 and a in c)) for c in candidatos):
            return rotulo
    return None


def _lista(valor) -> list:
    if isinstance(valor, str):
        valor = re.split(r"[;,/]| e | and ", valor)
    return [str(v).strip() for v in (valor or []) if str(v).strip()]


def _normalizar(valores: list, regras: list) -> list:
    saida = []
    for v in valores:
        v = v.lower()
        for rotulo, padrao in regras:
            if re.search(padrao, v):
                saida.append(rotulo)
                break
    return list(dict.fromkeys(saida))


def normalizar_estudos(valores: list) -> list:
    """Tipos de estudo devolvidos pelo modelo -> rótulos de TIPOS_ESTUDO, na
    ordem da evidência mais forte para a mais fraca. 'in silico' é descartado."""
    achados = _normalizar([v for v in valores if "silico" not in v.lower()
                           and "docking" not in v.lower()], TIPOS_ESTUDO_RE)
    return [t for t in TIPOS_ESTUDO if t in achados]


def normalizar_partes(valores: list) -> list:
    return _normalizar(valores, PARTES)


def classificar_llm(entidade: str, tipo: str, artigo: dict) -> dict | None:
    if tipo == "planta":
        descricao = "planta (espécie vegetal)"
        regra = ("um extrato, fração, óleo, resina, látex, suco ou outro preparado "
                 "DESTA planta, ou uma substância isolada DELA,")
    else:
        descricao = "composto químico (substância isolada ou sintética)"
        regra = "ESTE composto (isolado, purificado ou sintético)"
    if FOCO:
        linhas = "\n".join(f"- {r}: {', '.join(t)}" for r, t in FOCO.items())
        foco = ("FOCO DA ANÁLISE: interessam SOMENTE as atividades abaixo "
                "(rótulo: termos relacionados):\n" + linhas + "\n"
                "Responda true apenas se a entidade demonstrou pelo menos UMA "
                "delas; ignore qualquer outra atividade relatada no texto.\n\n")
        instrucao = ("Em \"atividades\", liste apenas os RÓTULOS acima que foram "
                     "demonstrados, copiados exatamente como estão escritos.")
    else:
        foco = ""
        instrucao = ("Para cada atividade demonstrada, use termos curtos em "
                     "português, minúsculos e no feminino, preferindo este "
                     f"vocabulário quando couber:\n{VOCABULARIO}")
    if tipo == "planta":
        instrucao_parte = (
            'Em "parte_planta", liste a(s) parte(s) da planta de que veio o material '
            "testado, em português, preferindo: folha, caule, casca, raiz, rizoma, "
            "flor, fruto, semente, parte aérea, planta inteira, exsudato (látex/resina). "
            f'Use "{SEM_INFORMACAO}" se o resumo não disser.\n')
        campo_parte = ' "parte_planta": ["..."],'
    else:
        instrucao_parte, campo_parte = "", ""
    prompt = PROMPT_USUARIO.format(
        entidade=entidade, descricao_tipo=descricao, regra_entidade=regra,
        foco=foco, instrucao_atividades=instrucao, instrucao_parte=instrucao_parte,
        campo_parte=campo_parte, titulo=artigo.get("titulo", ""),
        resumo=artigo.get("resumo", "")[:6000])
    payload = {"model": CFG_OLLAMA["modelo"], "stream": False, "format": "json",
               # num_predict: teto para a resposta (o JSON pedido tem bem menos);
               # keep_alive: o modelo fica carregado entre um pedido e outro
               # com raciocínio ligado, os tokens do raciocínio contam no limite
               "options": {"temperature": 0, "num_ctx": 8192 if CFG_OLLAMA.get("pensar") else 4096,
                           "num_predict": 4096 if CFG_OLLAMA.get("pensar") else 512},
               "keep_alive": "30m",
               # modelos com "raciocínio" (Qwen 3.5/3.6, gpt-oss...): desligado
               # por padrão ([ollama] pensar); os outros ignoram
               "think": bool(CFG_OLLAMA.get("pensar", False)),
               "messages": [{"role": "system", "content": PROMPT_SISTEMA},
                            {"role": "user", "content": prompt}]}
    for _ in range(2):
        try:
            r = requests.post(f"{CFG_OLLAMA['url']}/api/chat", json=payload,
                              timeout=CFG_OLLAMA["timeout_segundos"])
            if r.status_code == 400 and "think" in r.text.lower() and "think" in payload:
                # Ollama antigo ou modelo que recusa a opção: tenta sem ela
                payload.pop("think")
                r = requests.post(f"{CFG_OLLAMA['url']}/api/chat", json=payload,
                                  timeout=CFG_OLLAMA["timeout_segundos"])
            r.raise_for_status()
            resposta = json.loads(r.json()["message"]["content"])
            positivo = resposta.get("relacao_causal_positiva")
            if isinstance(positivo, str):
                positivo = positivo.strip().lower() in {"true", "sim", "yes"}
            atividades = resposta.get("atividades") or []
            if isinstance(atividades, str):
                atividades = re.split(r"[;,]", atividades)
            atividades = list(dict.fromkeys(
                normalizar_atividade(a) for a in atividades if str(a).strip()))
            if FOCO:  # descarta o que não corresponde a um rótulo-foco
                atividades = list(dict.fromkeys(
                    r for r in map(rotulo_do_foco, atividades) if r))
            estudos_brutos = _lista(resposta.get("tipo_estudo"))
            estudos = normalizar_estudos(estudos_brutos)
            if estudos_brutos and not estudos and any(
                    "silico" in e.lower() or "docking" in e.lower() for e in estudos_brutos):
                positivo = False   # só in silico: não é resultado experimental
            partes = (normalizar_partes(_lista(resposta.get("parte_planta")))
                      if tipo == "planta" else [])
            positivo = bool(positivo) and bool(atividades)
            return {"positivo": positivo, "atividades": atividades if positivo else [],
                    "tipo_estudo": (estudos or [SEM_INFORMACAO]) if positivo else [],
                    "parte_planta": (partes or [SEM_INFORMACAO]) if positivo and tipo == "planta" else [],
                    "justificativa": str(resposta.get("justificativa", ""))[:400]}
        except (requests.RequestException, json.JSONDecodeError, KeyError, TypeError, AttributeError):
            time.sleep(1)
    return None


class _barra:
    """Barra de progresso com total conhecido (tqdm, se instalado; senão, um
    contador simples a cada 1%)."""
    def __init__(self, total: int, desc: str):
        try:
            from tqdm.auto import tqdm as _tqdm
            self._b = _tqdm(total=total, desc=desc)
        except ImportError:
            self._b, self.total, self.n, self.desc = None, total, 0, desc
            self._passo, self._inicio = max(1, total // 100), time.time()

    def update(self, k: int = 1):
        if self._b is not None:
            self._b.update(k)
            return
        self.n += k
        if self.n % self._passo == 0 or self.n == self.total:
            dt = time.time() - self._inicio
            print(f"{self.desc}: {self.n}/{self.total} ({dt / self.n:.2f} s/it)", flush=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self._b is not None:
            self._b.close()


def classificar_tudo(pares: list, artigos: dict, so_cache: bool = False) -> dict:
    """pares: [(tipo, chave_entidade, nome_exibicao, pmid)] -> {chave_cache: resultado}"""
    cache = carregar_cache(CACHE_LLM, "chave")
    modelo = CFG_OLLAMA["modelo"]

    def chave_cache(tipo, chave, pmid, versao=VERSAO_PROMPT):
        return f"{versao}|{ASSINATURA_FOCO}|{modelo}|{tipo}|{chave}|{pmid}"

    reaproveitados = 0
    for tipo, chave, _, pmid in pares:
        if chave_cache(tipo, chave, pmid) in cache:
            continue
        for versao in VERSOES_NEGATIVO_REAPROVEITAVEL:
            antigo = cache.get(chave_cache(tipo, chave, pmid, versao))
            if antigo and antigo.get("positivo") is False:
                cache[chave_cache(tipo, chave, pmid)] = {**antigo, "chave": chave_cache(tipo, chave, pmid)}
                reaproveitados += 1
                break
    if reaproveitados:
        print(f"Modelo: {reaproveitados} resposta(s) negativa(s) da versão anterior "
              "do prompt reaproveitada(s); os positivos são reclassificados para "
              "obter tipo de estudo e parte da planta.")
    pendentes = [p for p in pares if chave_cache(p[0], p[1], p[3]) not in cache]
    print(f"Modelo ({modelo}): {len(pendentes)} par(es) entidade x artigo a "
          f"classificar ({len(pares) - len(pendentes)} em cache)")
    if so_cache:
        print("  --parcial: nenhum artigo novo será lido; as planilhas saem com o que já foi lido.")
        pendentes = []
    falhas = 0
    n_paralelo = max(1, int(CFG_OLLAMA.get("paralelo") or 1))
    trava = threading.Lock()

    def guardar(par, res):
        nonlocal falhas
        tipo, chave, _, pmid = par
        with trava:
            if res is None:
                falhas += 1          # não grava: tenta de novo na próxima execução
                return
            item = {"chave": chave_cache(tipo, chave, pmid), **res}
            cache[item["chave"]] = item
            gravar_cache(CACHE_LLM, item)

    if n_paralelo == 1 or len(pendentes) < 2:
        for par in tqdm(pendentes, desc="Classificando"):
            guardar(par, classificar_llm(par[2], par[0], artigos[par[3]]))
    else:
        # vários pedidos ao Ollama ao mesmo tempo; cada resposta vai para o
        # cache assim que chega (Ctrl+C não perde as já respondidas)
        print(f"  ({n_paralelo} pedidos simultâneos ao Ollama - [ollama] paralelo)")
        fila = iter(pendentes)
        with ThreadPoolExecutor(max_workers=n_paralelo) as ex, \
                _barra(len(pendentes), "Classificando") as barra:
            em_curso = {}

            def enviar(n):
                for par in fila:
                    em_curso[ex.submit(classificar_llm, par[2], par[0], artigos[par[3]])] = par
                    n -= 1
                    if n == 0:
                        break
            try:
                enviar(n_paralelo * 2)
                while em_curso:
                    prontos, _ = wait(list(em_curso), return_when=FIRST_COMPLETED)
                    for fut in prontos:
                        par = em_curso.pop(fut)
                        try:
                            guardar(par, fut.result())
                        except Exception:  # noqa: BLE001 - um par com problema não para os outros
                            guardar(par, None)
                        barra.update(1)
                    enviar(len(prontos))
            except KeyboardInterrupt:
                for fut in em_curso:
                    fut.cancel()
                raise
    if falhas:
        print(f"  ! {falhas} classificação(ões) falharam (timeout/JSON inválido) - "
              "rode a etapa de novo para completá-las.")
    return {(t, c, p): cache.get(chave_cache(t, c, p)) for t, c, _, p in pares}


# =============================================================================
# 8. Consolidação
# =============================================================================
def formatar(atividades: dict) -> str:
    """{atividade: {pmids}} -> 'a (PMID 1, 2); b (PMID 3)', mais citada primeiro."""
    ordem = sorted(atividades.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return "; ".join(f"{a} (PMID {', '.join(sorted(p, key=int))})" for a, p in ordem)


def formatar_estudos(estudos: dict) -> str | None:
    """{tipo: {pmids}} -> 'in vivo (PMID 3); in vitro (PMID 1, 2)', da
    evidência mais forte para a mais fraca."""
    ordem = [t for t in TIPOS_ESTUDO + [SEM_INFORMACAO] if t in estudos]
    return "; ".join(f"{t} (PMID {', '.join(sorted(estudos[t], key=int))})"
                     for t in ordem) or None


def melhor_evidencia(estudos: dict) -> str | None:
    for t in TIPOS_ESTUDO:
        if t in estudos:
            return t
    return SEM_INFORMACAO if estudos else None


def ler_plantas() -> pd.DataFrame | None:
    if not os.path.exists(ENTRADA_PLANTAS):
        print(f"AVISO: {ENTRADA_PLANTAS} não encontrado - só as plantas com "
              f"compostos ({ENTRADA}) serão pesquisadas.")
        return None
    return pd.read_csv(ENTRADA_PLANTAS, dtype=str)


def carregar_nomes_busca(pl: pd.DataFrame | None) -> dict:
    """{nome_cientifico: [todos os nomes da planta]} a partir de plantas.csv
    (etapa "plantas"). Plantas de gênero ficam só com o próprio nome."""
    if pl is None or "nomes_busca" not in pl.columns:
        return {}
    mapa = {}
    for nome, busca in zip(pl["nome_cientifico"], pl["nomes_busca"]):
        if not isinstance(nome, str):
            continue
        nomes = [nome] + [n.strip() for n in str(busca if isinstance(busca, str) else "").split(";")
                          if n.strip() and n.strip().lower() != nome.lower()]
        # só nomes de espécie (o gênero sozinho traria artigos de outras espécies)
        mapa[nome] = [n for n in dict.fromkeys(nomes) if len(n.split()) >= 2]
    return mapa


def _numero(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def artigos_da_descoberta(nomes_validos) -> dict:
    """{planta: {"pmids": [PMIDs, do mais recente ao mais antigo], "nomes": {nomes
    no artigo}}} - os artigos da descoberta (etapa 2) que citam a planta E um
    termo de atividade. Só os que têm PMID: são os que têm resumo no PubMed.
    Os demais (só DOI ou só OpenAlex) são contados em "sem_pmid"."""
    saida = {}
    if not os.path.exists(ENTRADA_DESCOBERTA):
        return saida
    ev = pd.read_csv(ENTRADA_DESCOBERTA, dtype=str)
    col = ("linha_em_plantas_csv" if "linha_em_plantas_csv" in ev.columns
           else "nome_aceito" if "nome_aceito" in ev.columns else None)
    if col is None or "referencia" not in ev.columns:
        return saida
    ev = ev[ev[col].isin(nomes_validos)]
    if "atividades_no_texto" in ev.columns:
        ev = ev[ev["atividades_no_texto"].fillna("").str.strip().ne("")]
    ev = ev.assign(_ano=pd.to_numeric(ev.get("ano"), errors="coerce")).sort_values("_ano", ascending=False)
    for planta, ref, nome_art in zip(ev[col], ev["referencia"].fillna(""), ev.get("nome_no_artigo", ev[col])):
        r = saida.setdefault(planta, {"pmids": [], "nomes": set(), "sem_pmid": 0})
        m = re.fullmatch(r"(?:PMID\s*)?(\d+)", ref.strip())
        if m:
            if m.group(1) not in r["pmids"]:
                r["pmids"].append(m.group(1))
        else:
            r["sem_pmid"] += 1
        if isinstance(nome_art, str) and nome_art.strip():
            r["nomes"].add(nome_art.strip())
    return saida


def selecionar_plantas(pl: pd.DataFrame | None, df: pd.DataFrame) -> tuple:
    """Decide quais plantas são pesquisadas no PubMed.
    Retorna (lista ordenada a pesquisar, {nome: motivo de não ter pesquisado},
    {nome: nº de compostos}, {plantas sem compostos incluídas por citação em artigos})."""
    n_compostos = (df.assign(_c=chave_composto(df)).groupby("nome_cientifico")["_c"].nunique()
                   .to_dict() if not df.empty else {})
    situacao, ocorrencias, citada = {}, {}, {}
    if pl is not None:
        for _, linha in pl.iterrows():
            nome = linha.get("nome_cientifico")
            if isinstance(nome, str):
                situacao[nome] = str(linha.get("situacao_nome") or "")
                ocorrencias[nome] = _numero(linha.get("n_ocorrencias_na_area"))
                # "clareadora (3 artigos); antioxidante (1 artigo)" -> 3
                ns = [int(x) for x in re.findall(r"\((\d+)\s+artigos?\)", str(linha.get("atividades_artigos") or ""))]
                if ns:
                    citada[nome] = max(ns)
    universo = list(dict.fromkeys(list(situacao) + [n for n in df.get("nome_cientifico", pd.Series(dtype=str)).dropna()]))

    modo = CFG_PUBMED["plantas_pesquisadas"]
    candidatas, fora, por_citacao = [], {}, set()
    for nome in universo:
        if len(nome.split()) < 2:
            fora[nome] = STATUS_SEM_ESPECIE
        elif nome in n_compostos:
            candidatas.append(nome)   # tem compostos: sempre pesquisada
        elif situacao.get(nome) == "não reconhecido" and not CFG_PUBMED["incluir_nao_reconhecidos"]:
            fora[nome] = STATUS_NAO_RECONHECIDO
        elif modo == "com_compostos" and CITADAS_EM_ARTIGOS and citada.get(nome):
            candidatas.append(nome)   # sem compostos, mas citada em artigos com atividade
            por_citacao.add(nome)
        elif modo == "com_compostos":
            fora[nome] = STATUS_SO_COM_COMPOSTOS
        else:
            candidatas.append(nome)
    # com compostos primeiro (mais compostos, mais ocorrências); depois as sem
    # compostos, primeiro as citadas em mais artigos da descoberta
    candidatas.sort(key=lambda n: (-n_compostos.get(n, 0),
                                   0 if n in n_compostos else -citada.get(n, 0),
                                   -ocorrencias.get(n, 0), n))
    limite = CFG_PUBMED["max_plantas"]
    if limite and len(candidatas) > limite:
        print(f"max_plantas = {limite}: pesquisando as {limite} prioritárias de "
              f"{len(candidatas)} (primeiro as com mais compostos, depois as com mais "
              "ocorrências na área).")
        for nome in candidatas[limite:]:
            fora[nome] = STATUS_FORA_LIMITE_PLANTAS
        candidatas = candidatas[:limite]
        por_citacao &= set(candidatas)
    return candidatas, fora, n_compostos, por_citacao


def anexar_chembl(frame: pd.DataFrame, inchikeys: pd.Series) -> pd.DataFrame:
    """Acrescenta as colunas de compostos_chembl.csv (etapa "chembl") pelo InChIKey."""
    if not os.path.exists(ENTRADA_CHEMBL):
        return frame
    chembl = pd.read_csv(ENTRADA_CHEMBL, dtype=str).drop_duplicates("InChIKey")
    for col in [c for c in chembl.columns if c != "InChIKey"]:
        frame[col] = inchikeys.map(dict(zip(chembl["InChIKey"], chembl[col])))
    if "atividades_chembl" in frame:
        motivo = inchikeys.map(lambda k: "não consultado no ChEMBL"
                               if inchikey_valido(k) else "sem InChIKey válido")
        frame["atividades_chembl"] = frame["atividades_chembl"].where(
            frame["atividades_chembl"].notna(), motivo)
    return frame


def apenas_da_regiao(df: pd.DataFrame) -> pd.DataFrame:
    """Esta etapa lê SEMPRE só as plantas e os compostos da região, mesmo com
    [bioativos] escopo = completo. A leitura dos resumos é a fase mais lenta do
    pipeline (um resumo por par entidade x artigo, julgado um a um pelo
    modelo): sobre todas as plantas das bases químicas ela não terminaria em
    tempo útil. Quem quiser a triagem de uma planta de fora da região põe o
    nome dela na lista do input.txt - aí ela passa a ser da região."""
    if "na_regiao" not in df.columns or df.empty:
        return df
    fora = df["na_regiao"].fillna("").str.strip().str.lower() == "não"
    if fora.any():
        print(f"  {fora.sum()} par(es) de plantas de fora da região ficam de fora desta "
              f"etapa ({df.loc[fora, 'nome_cientifico'].nunique()} plantas; "
              "[bioativos] escopo = completo).")
    return df[~fora]


def main():
    if not os.path.exists(ENTRADA):
        sys.exit(f"{ENTRADA} não encontrado. Rode a etapa 'bioativos' primeiro.")
    df = apenas_da_regiao(pd.read_csv(ENTRADA, dtype=str))
    if df.empty and not os.path.exists(ENTRADA_PLANTAS):
        gravar_csv(df.assign(InChIKey=None, atividades_relatadas_composto=None,
                             atividades_relatadas_planta=None), SAIDA)
        print("Entrada vazia - nada a pesquisar.")
        return
    if df.empty:
        print(f"{ENTRADA} está vazio: só as plantas de {ENTRADA_PLANTAS} serão pesquisadas.")

    if PARCIAL:
        print("MODO PARCIAL: planilhas com o que o modelo já leu até agora.\n")
    else:
        verificar_ollama()
    sessao = criar_sessao()
    filtros = filtros_atividade()
    if FOCO:
        print("Busca RESTRITA às atividades de [termos_pubmed]: "
              + "; ".join(f"{r} ({', '.join(t)})" for r, t in FOCO.items()) + "\n")

    # --- compostos ----------------------------------------------------------
    compostos = preparar_compostos(df, sessao)
    limite = CFG_PUBMED["max_compostos"]
    pesquisados = compostos
    if limite and len(compostos) > limite:
        print(f"max_compostos = {limite}: pesquisando os {limite} compostos "
              f"prioritários de {len(compostos)}.")
        pesquisados = compostos.head(limite)
    chaves_pesquisadas = set(pesquisados["_chave"])

    # via InChIKey
    cids = sorted({c for c in pesquisados["cid"] if c})
    print(f"\n{len(cids)} de {len(pesquisados)} composto(s) com CID no PubChem")
    vinculos = vinculos_pubchem(sessao, cids)
    com_vinculo = {c for c, p in vinculos.items() if p}
    todos_vinculados = {p for c in com_vinculo for p in vinculos[c]}
    print(f"{len(com_vinculo)} composto(s) com artigos vinculados no PubChem "
          f"({len(todos_vinculados)} artigo(s) distintos)")
    aprovados = filtrar_por_atividade(sessao, todos_vinculados, filtros) if todos_vinculados else {}

    max_comp = CFG_PUBMED["max_artigos_por_composto"]
    via_inchikey = {}            # entidade -> set(pmids)
    for _, c in pesquisados.iterrows():
        pmids_cid = set(vinculos.get(c["cid"], [])) if c["cid"] else set()
        if not pmids_cid:
            continue
        ent = f"composto|{c['_chave']}"
        for rotulo, _ in filtros:
            escolhidos = sorted(pmids_cid & aprovados.get(rotulo, set()), key=int, reverse=True)
            via_inchikey.setdefault(ent, set()).update(escolhidos[:max_comp])

    # via nome
    modo = CFG_PUBMED["busca_composto_por_nome"]
    if modo == "nunca":
        por_nome = pesquisados.iloc[0:0]
    elif modo == "sempre":
        por_nome = pesquisados[pesquisados["termos"].map(bool).astype(bool)]
    else:  # complemento
        por_nome = pesquisados[pesquisados["termos"].map(bool)
                               & ~pesquisados["cid"].isin(com_vinculo)]
    print(f"Busca por nome ({modo}): {len(por_nome)} composto(s)")


    # --- plantas ------------------------------------------------------------
    pl = ler_plantas()
    nomes_da_planta = carregar_nomes_busca(pl)
    plantas, plantas_fora, n_compostos_planta, por_citacao = selecionar_plantas(pl, df)
    com_comp = sum(1 for p in plantas if p in n_compostos_planta)
    print(f"\n{len(plantas)} planta(s) serão pesquisadas ({com_comp} com compostos, "
          f"{len(plantas) - com_comp} sem compostos conhecidos); "
          f"{len(plantas_fora)} fora da busca")
    if por_citacao:
        print(f"  {len(por_citacao)} das sem compostos entram por serem citadas em artigos da "
              "descoberta com termos de atividade (plantas_pesquisadas = com_compostos).")
    # artigos da descoberta (etapa 2) com termo de atividade: o modelo lê também
    # esses, além dos achados pela busca por nome (até max_artigos_por_planta)
    descoberta = artigos_da_descoberta(set(plantas)) if CITADAS_EM_ARTIGOS else {}
    max_pl = CFG_PUBMED["max_artigos_por_planta"]
    pmids_descoberta = {f"planta|{p}": d["pmids"][:max_pl] for p, d in descoberta.items() if d["pmids"]}
    if descoberta:
        sem_pmid = sum(d["sem_pmid"] for d in descoberta.values())
        print(f"  Artigos da descoberta: {sum(map(len, pmids_descoberta.values()))} par(es) planta x artigo "
              f"do PubMed entram na leitura ({len(pmids_descoberta)} plantas)"
              + (f"; {sem_pmid} só do OpenAlex/DOI, sem resumo no PubMed, ficam de fora" if sem_pmid else ""))
    print(f"{len(por_nome)} composto(s) serão buscados pelo nome")

    buscas = []  # (chave_busca, chave_entidade, query, retmax)
    for p in plantas:
        for rotulo, filtro in filtros:
            buscas.append((f"planta|{p}||{rotulo}", f"planta|{p}",
                           query_planta(nomes_da_planta.get(p, [p]), filtro),
                           CFG_PUBMED["max_artigos_por_planta"]))
    for _, c in por_nome.iterrows():
        for rotulo, filtro in filtros:
            buscas.append((f"composto|{c['_chave']}||{rotulo}", f"composto|{c['_chave']}",
                           query_composto(c["termos"], filtro), max_comp))
    buscas, sem_artigo = pre_checagem(sessao, buscas, filtros)
    por_busca = buscar_pmids(sessao, [(cb, q, rm) for cb, _, q, rm in buscas])
    via_nome = {ent: [] for ent in sem_artigo}   # pré-checagem: nenhum artigo
    # entidades com alguma busca que falhou (rede): não podem ser dadas como
    # "sem artigos" - ficam como pendentes até a próxima execução
    incompletas = {ent for cb, ent, _, _ in buscas if cb not in por_busca}
    for chave_busca, chave_ent, _, _ in buscas:
        if chave_busca in por_busca:
            lista = via_nome.setdefault(chave_ent, [])
            lista.extend(p for p in por_busca[chave_busca] if p not in lista)

    todos_pmids = ({p for lista in via_nome.values() for p in lista}
                   | {p for s in via_inchikey.values() for p in s}
                   | {p for lista in pmids_descoberta.values() for p in lista})
    artigos = baixar_artigos(sessao, todos_pmids)

    # --- pré-filtro e lista de pares para o modelo ---------------------------
    padroes = {f"planta|{p}": ([r for n in nomes_da_planta.get(p, [p]) for r in padroes_planta(n)],
                               p, "planta") for p in plantas}
    for _, c in pesquisados.iterrows():
        padroes[f"composto|{c['_chave']}"] = (padroes_composto(c["termos"]),
                                              c["nome_exibicao"], "composto")
    pares, via_do_par, sem_mencao = [], {}, 0
    # ordem de leitura pelo modelo: primeiro as plantas (na ordem de prioridade
    # da busca), depois os compostos (com atividade no NPASS e em mais plantas
    # primeiro) - assim os resultados mais úteis ficam prontos antes
    # todas as plantas antes dos compostos (as com compostos primeiro; as sem
    # compostos, inclusive as citadas em artigos da descoberta, logo depois):
    # as plantas são poucos pares e os compostos, centenas de milhares
    prioridade = {f"planta|{p}": i for i, p in enumerate(plantas)}
    prioridade.update({f"composto|{c}": len(plantas) + i
                       for i, c in enumerate(pesquisados["_chave"])})
    for ent in sorted(set(via_nome) | set(via_inchikey) | set(pmids_descoberta),
                      key=lambda e: (prioridade.get(e, len(prioridade)), e)):
        regex, nome, tipo = padroes[ent]
        vinc = via_inchikey.get(ent, set())
        desc = pmids_descoberta.get(ent, [])
        for pmid in list(dict.fromkeys(list(via_nome.get(ent, [])) + sorted(vinc, key=int) + desc)):
            art = artigos.get(pmid)
            if not art or not art.get("resumo"):
                continue
            if CFG_PUBMED["excluir_revisoes"] and any("Review" in t for t in art.get("tipos", [])):
                continue
            pelo_nome = pmid in via_nome.get(ent, [])
            # artigo vinculado pelo PubChem já é sobre o composto; artigo da
            # descoberta já foi conferido na etapa 2 (o nome foi extraído do
            # texto, inclusive abreviado); artigo achado só pelo nome precisa
            # citá-lo no título/resumo
            if pmid not in vinc and pmid not in desc and not menciona(art, regex):
                sem_mencao += 1
                continue
            nome_llm = nome
            if tipo == "planta":
                nomes = nomes_da_planta.get(nome, [nome])
                if pmid in desc:   # como a planta aparece nos artigos da descoberta
                    nomes = nomes + sorted(descoberta[nome]["nomes"])
                outros = list(dict.fromkeys(n for n in nomes if n.lower() != nome.lower()))
                if outros:
                    nome_llm = f"{nome} (mesma planta, também citada como: {', '.join(outros)})"
            pares.append((tipo, ent, nome_llm, pmid))
            vias = (["InChIKey"] if pmid in vinc else []) + (["nome"] if pelo_nome else []) \
                + (["descoberta"] if pmid in desc else [])
            via_do_par[(ent, pmid)] = " + ".join(vias) or "nome"
    print(f"{len(pares)} par(es) entidade x artigo para o modelo "
          f"({sem_mencao} descartados por não citarem a entidade)\n")

    classificacoes = classificar_tudo(pares, artigos, so_cache=PARCIAL)
    llm_pendente = {ent for (_, ent, _), res in classificacoes.items() if res is None}

    # --- agregação ----------------------------------------------------------
    resumo, evidencias = {}, []   # resumo: entidade -> atividades/estudos/partes/pmids
    ik_por_chave = dict(zip(compostos["_chave"], compostos["inchikey_final"]))
    cid_por_chave = dict(zip(compostos["_chave"], compostos["cid"]))
    for (tipo, chave_ent, pmid), res in classificacoes.items():
        if not res or not res.get("positivo"):
            continue
        r = resumo.setdefault(chave_ent, {"atividades": {}, "estudos": {},
                                          "partes": {}, "pmids": set()})
        for a in res["atividades"]:
            r["atividades"].setdefault(a, set()).add(pmid)
        estudos = res.get("tipo_estudo") or [SEM_INFORMACAO]
        partes = (res.get("parte_planta") or [SEM_INFORMACAO]) if tipo == "planta" else []
        for t in estudos:
            r["estudos"].setdefault(t, set()).add(pmid)
        for pt in partes:
            r["partes"].setdefault(pt, set()).add(pmid)
        r["pmids"].add(pmid)
        art = artigos[pmid]
        chave = chave_ent.split("|", 1)[1]
        evidencias.append({
            "tipo_entidade": tipo, "entidade": padroes[chave_ent][1],
            "InChIKey": ik_por_chave.get(chave) if tipo == "composto" else None,
            "PMID": pmid, "ano": art.get("ano"), "revista": art.get("revista"),
            "titulo": art.get("titulo"), "DOI": art.get("doi"),
            "atividades": "; ".join(res["atividades"]),
            "tipo_estudo": "; ".join(estudos),
            "parte_planta": "; ".join(partes) or None,
            "justificativa_llm": res.get("justificativa"),
            "via_busca": via_do_par.get((chave_ent, pmid), "nome"),
            "link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"})

    termos_por_chave = dict(zip(compostos["_chave"], compostos["termos"]))
    chaves_por_nome = set(por_nome["_chave"])

    def status_composto(chave):
        ent = f"composto|{chave}"
        if ent in resumo:
            return formatar(resumo[ent]["atividades"])
        if chave not in chaves_pesquisadas:
            return STATUS_FORA_LIMITE
        tem_vinculo = cid_por_chave.get(chave) in com_vinculo
        if not tem_vinculo and (not termos_por_chave.get(chave) or modo == "nunca"):
            return STATUS_SEM_BUSCA
        if ent in llm_pendente:
            return STATUS_LLM_PENDENTE
        if ent in incompletas:
            return STATUS_PENDENTE
        if via_inchikey.get(ent) or via_nome.get(ent):
            return STATUS_SEM_POSITIVO
        if ent not in via_nome and chave in chaves_por_nome:
            return STATUS_PENDENTE
        return STATUS_SEM_ARTIGOS

    def status_planta(nome):
        if not isinstance(nome, str):
            return STATUS_SEM_ESPECIE
        if nome in plantas_fora:
            return plantas_fora[nome]
        ent = f"planta|{nome}"
        if ent in resumo:
            return formatar(resumo[ent]["atividades"])
        if ent in incompletas:
            return STATUS_PENDENTE
        if not via_nome.get(ent) and not pmids_descoberta.get(ent):
            return STATUS_SEM_ARTIGOS if ent in via_nome else STATUS_PENDENTE
        if ent in llm_pendente:
            return STATUS_LLM_PENDENTE
        return STATUS_SEM_POSITIVO

    def campo(prefixo, chave, qual):
        r = resumo.get(f"{prefixo}|{chave}") if isinstance(chave, str) else None
        if not r:
            return 0 if qual == "n" else None
        if qual == "melhor":
            return melhor_evidencia(r["estudos"])
        if qual == "estudos":
            return formatar_estudos(r["estudos"])
        if qual == "partes":
            return formatar(r["partes"]) or None
        return len(r["pmids"])

    # --- saída 1: combinado planta x composto ------------------------------
    chave_linha = chave_composto(df)
    saida = df.copy()
    saida["InChIKey"] = chave_linha.map(ik_por_chave)
    cid_final = chave_linha.map(cid_por_chave)
    saida["pubchem_cid"] = (saida["pubchem_cid"].where(saida["pubchem_cid"].notna(), cid_final)
                            if "pubchem_cid" in saida.columns else cid_final)
    chaves_unicas = list(chave_linha.unique())
    saida["atividades_relatadas_composto"] = chave_linha.map({c: status_composto(c) for c in chaves_unicas})
    saida["melhor_evidencia_composto"] = chave_linha.map({c: campo("composto", c, "melhor") for c in chaves_unicas})
    saida["estudos_composto"] = chave_linha.map({c: campo("composto", c, "estudos") for c in chaves_unicas})
    nomes_unicos = list(saida["nome_cientifico"].unique())
    saida["atividades_relatadas_planta"] = saida["nome_cientifico"].map({n: status_planta(n) for n in nomes_unicos})
    saida["melhor_evidencia_planta"] = saida["nome_cientifico"].map({n: campo("planta", n, "melhor") for n in nomes_unicos})
    saida["estudos_planta"] = saida["nome_cientifico"].map({n: campo("planta", n, "estudos") for n in nomes_unicos})
    saida["partes_planta"] = saida["nome_cientifico"].map({n: campo("planta", n, "partes") for n in nomes_unicos})
    ik_linha = saida["InChIKey"].where(saida["InChIKey"].notna(),
                                       saida["composto_inchikey"].map(inchikey_valido))
    saida = anexar_chembl(saida, ik_linha)
    if not os.path.exists(ENTRADA_CHEMBL):
        print(f"AVISO: {ENTRADA_CHEMBL} não encontrado - rode a etapa 'chembl' para "
              "anexar as atividades medidas no ChEMBL.")
    # --- saída 2: uma linha por composto -------------------------------------
    if not df.empty:
        g = df.assign(_chave=chave_linha).groupby("_chave", sort=False)
        plantas_do_comp = g["nome_cientifico"].agg(lambda s: "; ".join(sorted(set(s.dropna()))))
        n_plantas_comp = g["nome_cientifico"].nunique()
        ids_comp = g["composto_id"].agg(lambda s: "; ".join(dict.fromkeys(s.dropna().astype(str))))
        nome_comp = g["composto_nome"].first()
        # estrutura: o primeiro SMILES registrado para o composto (COCONUT/NPASS)
        smiles_comp = (g["composto_smiles"].agg(
            lambda s: next((v for v in s if isinstance(v, str) and v.strip()), None))
            if "composto_smiles" in df.columns else pd.Series(dtype=object))
        fonte_smiles_comp = (g["fonte_smiles"].agg(
            lambda s: next((v for v in s if isinstance(v, str) and v.strip()), None))
            if "fonte_smiles" in df.columns else pd.Series(dtype=object))
        # estados do composto: união dos estados das plantas em que ocorre
        estados_comp = (g["estados_br"].agg(juntar_estados) if "estados_br" in df.columns
                        else pd.Series(dtype=object))
        # SMILES de cada fonte, lado a lado (vazio = a fonte não tem estrutura)
        smiles_por_fonte = {c: (g[c].agg(lambda s: next((v for v in s if isinstance(v, str)
                                                         and v.strip()), None))
                                if c in df.columns else pd.Series(dtype=object))
                            for c in COLUNAS_SMILES_FONTE}
        # bases químicas e informações complementares (Dr. Duke, LOTUS)
        bases_comp = g["base"].agg(lambda s: "; ".join(sorted({b.strip() for v in s.dropna()
                                                                for b in str(v).split(";") if b.strip()})))
        duke_comp = (g["atividades_duke"].agg(lambda s: next((v for v in s if isinstance(v, str) and v), None))
                     if "atividades_duke" in df.columns else pd.Series(dtype=object))

        def refs_por_planta(grupo):
            if "referencias_lotus" not in grupo:
                return None
            partes = [f"{p}: {r}" for p, r in zip(grupo["nome_cientifico"], grupo["referencias_lotus"])
                      if isinstance(r, str) and r]
            partes = list(dict.fromkeys(partes))
            extra = f" (+{len(partes) - 5} planta(s))" if len(partes) > 5 else ""
            return " | ".join(partes[:5]) + extra if partes else None
        lotus_comp = (pd.Series({chave: refs_por_planta(grupo) for chave, grupo
                                 in df.assign(_chave=chave_linha).groupby("_chave", sort=False)},
                                dtype=object)
                      if "referencias_lotus" in df.columns else pd.Series(dtype=object))
    else:
        plantas_do_comp = n_plantas_comp = ids_comp = nome_comp = pd.Series(dtype=object)
        smiles_comp = fonte_smiles_comp = pd.Series(dtype=object)
        smiles_por_fonte = {c: pd.Series(dtype=object) for c in COLUNAS_SMILES_FONTE}
        estados_comp = pd.Series(dtype=object)
        bases_comp = duke_comp = lotus_comp = pd.Series(dtype=object)
    tab_comp = pd.DataFrame({
        "composto_nome": compostos["_chave"].map(nome_comp).fillna(compostos["nome_exibicao"]),
        "nome_pubchem": compostos["titulo_pubchem"],
        "InChIKey": compostos["inchikey_final"],
        "smiles": compostos["_chave"].map(smiles_comp),
        "fonte_smiles": compostos["_chave"].map(fonte_smiles_comp),
        **{c: compostos["_chave"].map(smiles_por_fonte[c]) for c in COLUNAS_SMILES_FONTE},
        "pubchem_cid": compostos["cid"],
        "composto_ids": compostos["_chave"].map(ids_comp),
        "plantas": compostos["_chave"].map(plantas_do_comp),
        "estados_composto": compostos["_chave"].map(estados_comp).fillna(DESCONHECIDA),
        "n_plantas": compostos["_chave"].map(n_plantas_comp),
        "atividades_relatadas_composto": compostos["_chave"].map(status_composto),
        "melhor_evidencia_composto": compostos["_chave"].map(lambda c: campo("composto", c, "melhor")),
        "estudos_composto": compostos["_chave"].map(lambda c: campo("composto", c, "estudos")),
        "n_artigos_positivos": compostos["_chave"].map(lambda c: campo("composto", c, "n")),
        "bases": compostos["_chave"].map(bases_comp),
    })
    if "atividades_duke" in df.columns:
        tab_comp["atividades_duke"] = compostos["_chave"].map(duke_comp)
    if "referencias_lotus" in df.columns:
        tab_comp["referencias_lotus"] = compostos["_chave"].map(lotus_comp)
    tab_comp = anexar_chembl(tab_comp, tab_comp["InChIKey"])
    tab_comp = tab_comp.sort_values(["n_artigos_positivos", "composto_nome"],
                                    ascending=[False, True], key=lambda s: s.str.lower()
                                    if s.dtype == object else s)
    gravar_csv(tab_comp, SAIDA_COMPOSTOS)
    # --- saída 3: uma linha por planta ---------------------------------------
    compostos_ativos = {}   # planta -> compostos dela com atividade positiva no PubMed
    for planta, chave in zip(df.get("nome_cientifico", []), chave_linha):
        if f"composto|{chave}" in resumo:
            nome_c = padroes.get(f"composto|{chave}", (None, chave))[1]
            compostos_ativos.setdefault(planta, []).append(nome_c)
    if pl is not None:
        base = pl.copy()
        extras = [n for n in df["nome_cientifico"].dropna().unique()
                  if n not in set(base["nome_cientifico"])] if not df.empty else []
        if extras:
            base = pd.concat([base, pd.DataFrame({"nome_cientifico": extras})], ignore_index=True)
    else:
        base = pd.DataFrame({"nome_cientifico": sorted(set(df["nome_cientifico"].dropna()))})
    colunas_pl = [c for c in ["nome_cientifico", "familia", "nome_popular_pt", "situacao_nome",
                              "fonte", "n_ocorrencias_na_area", "estados_br", "dominios_br",
                              "endemismo_br", "origem_br"] if c in base.columns]
    tab_pl = base[colunas_pl].copy()
    n = tab_pl["nome_cientifico"]
    tab_pl["n_compostos"] = n.map(lambda x: n_compostos_planta.get(x, 0))
    # quantos compostos de cada base química (COCONUT, NPASS, DUKE, LOTUS, FOODB)
    por_base = {}
    if not df.empty:
        for planta, chave, bases in zip(df["nome_cientifico"], chave_linha, df["base"]):
            for b in str(bases if isinstance(bases, str) else "").split(";"):
                if b.strip():
                    por_base.setdefault(planta, {}).setdefault(b.strip(), set()).add(chave)
    tab_pl["bases_compostos"] = n.map(lambda x: "; ".join(
        f"{b} {len(c)}" for b, c in sorted(por_base.get(x, {}).items(), key=lambda kv: (-len(kv[1]), kv[0])))
        or None)
    tab_pl["atividades_relatadas_planta"] = n.map(status_planta)
    tab_pl["melhor_evidencia_planta"] = n.map(lambda x: campo("planta", x, "melhor"))
    tab_pl["estudos_planta"] = n.map(lambda x: campo("planta", x, "estudos"))
    tab_pl["partes_planta"] = n.map(lambda x: campo("planta", x, "partes"))
    tab_pl["n_artigos_positivos"] = n.map(lambda x: campo("planta", x, "n"))
    tab_pl["compostos_com_atividade_relatada"] = n.map(
        lambda x: "; ".join(sorted(set(compostos_ativos.get(x, [])), key=str.lower)) or None)
    tab_pl = tab_pl.sort_values(["n_artigos_positivos", "nome_cientifico"],
                                ascending=[False, True], key=lambda s: s.str.lower()
                                if s.dtype == object else s)
    gravar_csv(tab_pl, SAIDA_PLANTAS)
    gravar_csv(pd.DataFrame(evidencias, columns=[
        "tipo_entidade", "entidade", "InChIKey", "PMID", "ano", "revista", "titulo",
        "DOI", "atividades", "tipo_estudo", "parte_planta", "justificativa_llm",
        "via_busca", "link"]).sort_values(["tipo_entidade", "entidade", "PMID"]),
        SAIDA_EVIDENCIAS)
    # por último: é o arquivo que o main.py --retomar usa para saber se a etapa terminou
    gravar_csv(saida, SAIDA)

    n_comp = sum(1 for k in resumo if k.startswith("composto|"))
    n_plan = sum(1 for k in resumo if k.startswith("planta|"))
    print("\nConcluído" + (" (PARCIAL)" if PARCIAL else "") + ":")
    if llm_pendente:
        print(f"  {len(llm_pendente)} planta(s)/composto(s) com artigos ainda não lidos pelo modelo "
              f"('{STATUS_LLM_PENDENTE}')")
    print(f"  {SAIDA_PLANTAS}: {len(tab_pl)} planta(s), {n_plan} com relação causal positiva")
    print(f"  {SAIDA_COMPOSTOS}: {len(tab_comp)} composto(s), {n_comp} com relação causal positiva")
    print(f"  {SAIDA}: {len(saida)} linha(s) planta x composto")
    print(f"  {SAIDA_EVIDENCIAS}: {len(evidencias)} evidência(s) positiva(s)")


if __name__ == "__main__":
    main()
