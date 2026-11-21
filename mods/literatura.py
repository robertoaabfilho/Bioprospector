"""
literatura.py

Módulo compartilhado (não é executado diretamente) com o acesso às bases
de literatura usado pelas etapas "artigos" (descoberta de plantas em
artigos) e "pubmed" (atividades relatadas):

  PubMed (NCBI E-utilities)  esearch, efetch, elink
  PubChem (via E-utilities)  vínculos composto -> artigos do PubMed
  OpenAlex                   busca ampla em títulos e resumos (substituto
                             aberto do Google Scholar, que não tem API)

Tudo o que é baixado fica em arquivos cache_*.jsonl (uma linha por item,
gravada na hora). Uma execução interrompida é retomada sem refazer nada.
"""

import hashlib
import json
import os

import caminhos as _C
import re
import time

import requests
from requests.adapters import HTTPAdapter, Retry

from config_pipeline import carregar_config_artigos, carregar_config_pubmed, ler_input

try:
    from tqdm.auto import tqdm
except ImportError:  # tqdm é opcional
    def tqdm(iteravel, **_):
        return iteravel

CACHE_BUSCAS = _C.cache("cache_pubmed_buscas.jsonl")
CACHE_ARTIGOS = _C.cache("cache_pubmed_artigos.jsonl")
CACHE_OPENALEX = _C.cache("cache_openalex.jsonl")
SO_CACHE = False   # True no modo --parcial da etapa pubmed: nenhuma consulta nova, só o cache

CFG_PUBMED = carregar_config_pubmed()
_INPUT = ler_input()
CFG_ARTIGOS = carregar_config_artigos()

# Atividades-foco opcionais (input.txt, seção [termos_pubmed]):
# {rótulo: [termos de busca]}. Vazio = busca geral por qualquer atividade.
FOCO = _INPUT["termos_pubmed"]
ASSINATURA_FOCO = (hashlib.md5(json.dumps(FOCO, sort_keys=True, ensure_ascii=False)
                               .encode()).hexdigest()[:8] if FOCO else "geral")

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
OPENALEX = "https://api.openalex.org/works"
PAUSA_NCBI = 0.11 if CFG_PUBMED["ncbi_api_key"] else 0.35
PAUSA_OPENALEX = 0.15

FILTRO_ATIVIDADE = ("(activit*[tiab] OR effect*[tiab] OR inhibit*[tiab] OR "
                    "protect*[tiab] OR toxic*[tiab] OR potential[tiab])")
ROTULO_GERAL = "atividade biológica (geral)"


# =============================================================================
# Cache (JSON Lines)
# =============================================================================
def carregar_cache(caminho: str, chave: str) -> dict:
    dados = {}
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                try:
                    item = json.loads(linha)
                    dados[item[chave]] = item
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue  # linha truncada por interrupção
    return dados


def gravar_cache(caminho: str, item: dict):
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def hash_curto(texto: str) -> str:
    return hashlib.md5(texto.encode("utf-8")).hexdigest()[:12]


# =============================================================================
# Sessão HTTP
# =============================================================================
def criar_sessao() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = "Pipeline-Prospeccao-Plantas-Bioativos/2.0"
    retry = Retry(total=5, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def params_ncbi() -> dict:
    p = {"tool": "pipeline_prospeccao_bioativos"}
    if CFG_PUBMED["ncbi_api_key"]:
        p["api_key"] = CFG_PUBMED["ncbi_api_key"]
    if CFG_PUBMED["email"]:
        p["email"] = CFG_PUBMED["email"]
    return p


# =============================================================================
# Montagem das buscas no PubMed
# =============================================================================
def formatar_termo(termo: str) -> str:
    """'larvicidal' -> '"larvicidal"[tiab]'. Termos que já trazem tag do
    PubMed (ex.: "Anti-Bacterial Agents"[mh]) são usados como estão."""
    if re.search(r"\[[a-z ]+\]\s*$", termo, re.I):
        return termo
    return f'"{termo.strip(chr(34))}"[tiab]'


def filtros_atividade() -> list:
    """[(rótulo, filtro)]: uma busca por atividade-foco, ou o filtro geral."""
    if not FOCO:
        return [("", FILTRO_ATIVIDADE)]
    return [(rotulo, "(" + " OR ".join(formatar_termo(t) for t in termos) + ")")
            for rotulo, termos in FOCO.items()]


def rotulo_exibicao(rotulo: str) -> str:
    return rotulo or ROTULO_GERAL


def finalizar(q: str, excluir_revisoes: bool | None = None) -> str:
    if excluir_revisoes is None:
        excluir_revisoes = CFG_PUBMED["excluir_revisoes"]
    return q + (" NOT review[pt]" if excluir_revisoes else "")


def query_planta(nomes, filtro: str = FILTRO_ATIVIDADE) -> str:
    """nomes: um nome ou a lista de nomes da planta (original e aceitos)."""
    nomes = [nomes] if isinstance(nomes, str) else list(nomes)
    alternativa = " OR ".join(f'"{n}"[tiab]' for n in nomes)
    if len(nomes) > 1:
        alternativa = f"({alternativa})"
    return finalizar(f'{alternativa} AND hasabstract AND {filtro}')


# =============================================================================
# PubMed: esearch / efetch
# =============================================================================
def sem_chave(erro) -> str:
    """Mensagem de erro sem a chave do NCBI (ela vai no endereço da consulta)."""
    return re.sub(r"(api_key=)[^&\s']+", r"\1***", str(erro))


class Disjuntor:
    """Evita horas de espera quando o servidor do NCBI está fora do ar ou
    devolvendo erro em série (ex.: HTTP 500): depois de LIMITE falhas
    seguidas, pausa PAUSA segundos e tenta de novo; depois de MAX_PAUSAS
    pausas sem melhora, desiste da fase - o que faltou fica pendente e é
    feito na próxima execução (o já obtido está em cache)."""
    LIMITE, PAUSA, MAX_PAUSAS = 10, 600, 3

    def __init__(self, fase: str):
        self.fase, self.seguidas, self.pausas = fase, 0, 0

    def sucesso(self):
        self.seguidas, self.pausas = 0, 0

    def falha(self) -> bool:
        """Registra uma falha. True = desistir desta fase agora."""
        self.seguidas += 1
        if self.seguidas < self.LIMITE:
            return False
        if self.pausas >= self.MAX_PAUSAS:
            print(f"\n  ! {self.fase}: o servidor continua falhando depois de {self.MAX_PAUSAS} pausas - "
                  "fase interrompida. O que faltou fica para a próxima execução (o resto da "
                  "etapa segue com o que já está em cache).", flush=True)
            return True
        self.pausas += 1
        print(f"\n  ! {self.fase}: {self.seguidas} falhas seguidas (servidor instável ou fora do ar). "
              f"Pausa de {self.PAUSA // 60} min antes de tentar de novo "
              f"({self.pausas}/{self.MAX_PAUSAS})...", flush=True)
        time.sleep(self.PAUSA)
        self.seguidas = 0
        return False


def _idlist(resposta: dict) -> list:
    """PMIDs de uma resposta do esearch. O NCBI às vezes responde 200 com o erro
    dentro do JSON (ex.: "Search Backend failed"): isso não é "nenhum artigo" -
    vira exceção, para não ir para o cache como busca vazia."""
    resultado = resposta["esearchresult"]
    if "ERROR" in resultado or "idlist" not in resultado:
        raise ValueError(str(resultado.get("ERROR", "resposta sem idlist"))[:200])
    return resultado["idlist"]


def esearch(sessao, query: str, retmax: int, ordenar: str = "relevance") -> list | None:
    """Busca simples (GET). Para listas longas de PMIDs use esearch_post."""
    try:
        r = sessao.get(EUTILS + "esearch.fcgi", timeout=30, params={
            **params_ncbi(), "db": "pubmed", "term": query, "retmode": "json",
            "retmax": retmax, "sort": ordenar})
        r.raise_for_status()
        return _idlist(r.json())
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"  ! esearch falhou ({sem_chave(e)}) - será tentado na próxima execução")
        return None
    finally:
        time.sleep(PAUSA_NCBI)


def esearch_post(sessao, query: str, retmax: int) -> list | None:
    """Mesma busca, enviada por POST (aceita consultas longas, como uma
    lista de centenas de PMIDs)."""
    try:
        r = sessao.post(EUTILS + "esearch.fcgi", timeout=120, data={
            **params_ncbi(), "db": "pubmed", "term": query, "retmode": "json",
            "retmax": retmax})
        r.raise_for_status()
        return _idlist(r.json())
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        print(f"  ! esearch (POST) falhou ({sem_chave(e)}) - será tentado na próxima execução")
        return None
    finally:
        time.sleep(PAUSA_NCBI)


def buscar_pmids(sessao, entidades: list, descricao: str = "PubMed esearch") -> dict:
    """entidades: [(chave, query, retmax)] -> {chave: [pmids]}.
    Reaproveita o cache quando a mesma chave já foi buscada com a mesma
    query e o mesmo limite."""
    cache = carregar_cache(CACHE_BUSCAS, "chave")
    resultado, pendentes = {}, []
    for chave, query, retmax in entidades:
        item = cache.get(chave)
        if item and item.get("query") == query and item.get("retmax") == retmax:
            resultado[chave] = item["pmids"]
        else:
            pendentes.append((chave, query, retmax))
    if SO_CACHE:
        pendentes = []
    print(f"PubMed: {len(pendentes)} busca(s) pendente(s) "
          f"({len(entidades) - len(pendentes)} em cache)")
    disjuntor = Disjuntor(descricao)
    for chave, query, retmax in tqdm(pendentes, desc=descricao):
        pmids = esearch(sessao, query, retmax)
        if pmids is None:
            if disjuntor.falha():
                break
            continue
        disjuntor.sucesso()
        resultado[chave] = pmids
        gravar_cache(CACHE_BUSCAS, {"chave": chave, "query": query,
                                    "retmax": retmax, "pmids": pmids})
    return resultado


def _texto(elem) -> str:
    return "".join(elem.itertext()).strip() if elem is not None else ""


def parse_pubmed_xml(xml: str) -> list:
    import xml.etree.ElementTree as ET
    artigos = []
    raiz = ET.fromstring(xml)
    for art in raiz.iter("PubmedArticle"):
        pmid = _texto(art.find(".//MedlineCitation/PMID"))
        partes, italicos = [], []
        titulo_el = art.find(".//ArticleTitle")
        for sec in art.findall(".//Abstract/AbstractText"):
            t = _texto(sec)
            if t:
                rotulo = sec.get("Label")
                partes.append(f"{rotulo}: {t}" if rotulo else t)
        # trechos em itálico (nomes científicos costumam vir assim)
        for el in [titulo_el] + art.findall(".//Abstract/AbstractText"):
            if el is not None:
                italicos += [_texto(i) for i in el.iter("i") if _texto(i)]
        ano = _texto(art.find(".//JournalIssue/PubDate/Year")) or \
            _texto(art.find(".//JournalIssue/PubDate/MedlineDate"))[:4]
        doi = ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _texto(aid)
        tipos = [_texto(t) for t in art.findall(".//PublicationTypeList/PublicationType")]
        artigos.append({"pmid": pmid, "titulo": _texto(titulo_el),
                        "resumo": " ".join(partes), "ano": ano,
                        "revista": _texto(art.find(".//Journal/Title")),
                        "doi": doi, "tipos": tipos, "italicos": italicos})
    return artigos


def baixar_artigos(sessao, pmids: set) -> dict:
    cache = carregar_cache(CACHE_ARTIGOS, "pmid")
    faltando = sorted(p for p in pmids if p not in cache) if not SO_CACHE else []
    print(f"PubMed: {len(faltando)} resumo(s) a baixar ({len(pmids) - len(faltando)} em cache)")
    lotes = [faltando[i:i + 200] for i in range(0, len(faltando), 200)]
    disjuntor = Disjuntor("PubMed efetch")
    for lote in tqdm(lotes, desc="PubMed efetch"):
        try:
            r = sessao.post(EUTILS + "efetch.fcgi", timeout=120, data={
                **params_ncbi(), "db": "pubmed", "id": ",".join(lote),
                "retmode": "xml", "rettype": "abstract"})
            r.raise_for_status()
            for art in parse_pubmed_xml(r.text):
                cache[art["pmid"]] = art
                gravar_cache(CACHE_ARTIGOS, art)
            disjuntor.sucesso()
        except Exception as e:  # inclui XML malformado
            print(f"  ! efetch falhou para um lote ({sem_chave(e)}) - será tentado de novo depois")
            if disjuntor.falha():
                break
        finally:
            time.sleep(PAUSA_NCBI)
    return cache


# =============================================================================
# Menção de planta no texto
# =============================================================================
def padroes_planta(nome: str) -> list:
    partes = nome.split()
    if len(partes) < 2:
        return [re.compile(rf"\b{re.escape(nome)}\b", re.I)]
    genero, epiteto = partes[0], partes[1]
    return [re.compile(rf"\b{re.escape(genero)}\s+{re.escape(epiteto)}\b", re.I),
            re.compile(rf"\b{re.escape(genero[0])}\.\s*{re.escape(epiteto)}\b", re.I)]


def menciona(artigo: dict, padroes: list) -> bool:
    texto = f"{artigo.get('titulo', '')} {artigo.get('resumo', '')}"
    return any(p.search(texto) for p in padroes)


# =============================================================================
# OpenAlex
# =============================================================================
def termo_openalex(termo: str) -> str:
    """Adapta um termo do PubMed para o OpenAlex: remove tags de campo
    ([mh], [tiab]) e truncamento (*), que a busca padrão do OpenAlex não
    usa (ela já considera variações da palavra)."""
    t = re.sub(r"\[[^\]]*\]", "", termo).replace("*", "").strip().strip('"').strip()
    return f'"{t}"' if " " in t else t


def _reconstruir_resumo(indice) -> str:
    if not isinstance(indice, dict):
        return ""
    posicoes = [(p, palavra) for palavra, lista in indice.items() for p in lista]
    return " ".join(palavra for _, palavra in sorted(posicoes))


def buscar_openalex(sessao, consulta: str, maximo: int) -> list | None:
    """Trabalhos do OpenAlex cujo título/resumo atende à consulta (sintaxe
    booleana com AND/OR). Devolve [{id, pmid, doi, titulo, resumo, ano,
    revista}] ou None em caso de falha (ex.: sem cota diária)."""
    chave = f"{hash_curto(consulta)}|{maximo}"
    cache = carregar_cache(CACHE_OPENALEX, "chave")
    if chave in cache and cache[chave].get("consulta") == consulta:
        return cache[chave]["trabalhos"]

    base = {"per_page": 100, "select": "id,ids,doi,title,publication_year,"
            "abstract_inverted_index,primary_location"}
    if CFG_ARTIGOS["openalex_api_key"]:
        base["api_key"] = CFG_ARTIGOS["openalex_api_key"]
    if CFG_ARTIGOS["email"]:
        base["mailto"] = CFG_ARTIGOS["email"]
    # 1ª forma: filtro em título+resumo; se o servidor recusar, busca geral
    formas = [{"filter": f"title_and_abstract.search:{consulta},has_abstract:true",
               "sort": "relevance_score:desc"},
              {"search": consulta, "filter": "has_abstract:true"}]

    for forma in formas:
        trabalhos, cursor, erro = [], "*", None
        while cursor and len(trabalhos) < maximo:
            try:
                r = sessao.get(OPENALEX, timeout=60,
                               params={**base, **forma, "cursor": cursor})
                time.sleep(PAUSA_OPENALEX)
                if r.status_code in (400, 403):
                    erro = f"HTTP {r.status_code}"
                    break
                if r.status_code in (402, 429):
                    print("  ! OpenAlex: cota diária esgotada ou ausente "
                          "(crie uma chave gratuita e preencha openalex_api_key "
                          "em [artigos]). Seguindo sem o OpenAlex.")
                    return None
                r.raise_for_status()
                dados = r.json()
            except (requests.RequestException, ValueError) as e:
                print(f"  ! OpenAlex falhou ({e}) - seguindo sem o OpenAlex.")
                return None
            for w in dados.get("results", []):
                ids = w.get("ids") or {}
                pmid = str(ids.get("pmid") or "").rstrip("/").split("/")[-1]
                fonte = ((w.get("primary_location") or {}).get("source") or {})
                trabalhos.append({
                    "id": str(w.get("id", "")).split("/")[-1],
                    "pmid": pmid if pmid.isdigit() else "",
                    "doi": str(w.get("doi") or "").replace("https://doi.org/", ""),
                    "titulo": w.get("title") or "",
                    "resumo": _reconstruir_resumo(w.get("abstract_inverted_index")),
                    "ano": str(w.get("publication_year") or ""),
                    "revista": fonte.get("display_name") or "",
                })
            cursor = (dados.get("meta") or {}).get("next_cursor")
            if not dados.get("results"):
                break
        if erro is None:
            trabalhos = trabalhos[:maximo]
            gravar_cache(CACHE_OPENALEX, {"chave": chave, "consulta": consulta,
                                          "trabalhos": trabalhos})
            return trabalhos
    print(f"  ! OpenAlex recusou a consulta ({erro}) - seguindo sem o OpenAlex.")
    return None
