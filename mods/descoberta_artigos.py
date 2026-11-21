"""
descoberta_artigos.py

Módulo compartilhado (usado pela etapa "plantas"): descobre plantas citadas
em ARTIGOS sobre a região que tratam das atividades do input.txt.

Bases (seção [artigos] do input.txt):
  PubMed    via E-utilities do NCBI
  OpenAlex  índice aberto com revistas brasileiras e SciELO (substitui o
            Google Scholar, que não tem API e bloqueia acesso automatizado)

Busca: artigos que citam a REGIÃO (termos_texto, em [regiao]) e, se
contexto_vegetal = true em [artigos] (padrão: false), um termo de contexto
vegetal (plant, extract, leaves, bark, seeds...). As atividades de [termos_pubmed]
NÃO restringem a busca: servem só para anotar, em cada planta, quais
atividades do input aparecem nos artigos que a citam.
Revisões entram (costumam listar muitas plantas). Os nomes científicos do
título/resumo são extraídos (inclusive em itálico e na forma abreviada,
"E. oleracea"); palavras que só parecem binômios ("The extract",
"Tyrosinase inhibition") são descartadas. A conferência taxonômica dos
nomes é feita depois, na etapa "plantas" (taxonomia.py).

As atividades registradas indicam apenas que o artigo trata do tema; o
julgamento de causa e efeito é feito na etapa "pubmed", pelo modelo.
"""

import re
import time
import unicodedata

import requests

from literatura import (CFG_ARTIGOS, EUTILS, FILTRO_ATIVIDADE, FOCO, PAUSA_NCBI, baixar_artigos,
                        buscar_openalex, buscar_pmids, finalizar, formatar_termo,
                        params_ncbi, rotulo_exibicao, termo_openalex)

# Contexto vegetal exigido na descoberta (evita "Amazon" como empresa etc.)
CONTEXTO_PLANTA_PUBMED = (
    "(plant*[tiab] OR extract*[tiab] OR \"essential oil\"[tiab] OR medicinal[tiab] "
    "OR leaf[tiab] OR leaves[tiab] OR bark[tiab] OR seed*[tiab] OR fruit*[tiab] "
    "OR root*[tiab] OR flower*[tiab] OR species[tiab])")
CONTEXTO_PLANTA_OPENALEX = ("(plant OR plants OR extract OR \"essential oil\" OR "
                            "medicinal OR leaves OR bark OR seeds OR fruit)")
# termos do filtro geral de atividade (literatura.FILTRO_ATIVIDADE), usados
# para anotar as plantas quando [termos_pubmed] está vazio
TERMOS_ATIVIDADE_GERAL = re.findall(r"([\w*-]+)\[tiab\]", FILTRO_ATIVIDADE)
LIMITE_ESEARCH = 10000   # o PubMed só devolve os 10 mil primeiros resultados de uma busca

# Palavras capitalizadas que nunca são gênero e palavras comuns que nunca
# são epíteto: evitam milhares de consultas inúteis ao GBIF.
NAO_GENERO = set("""
The This These Those That There Their Our We In On Of For From With Without
By At As An And Or But Not No All Both Each Such Some Most Many More Less
Here Results Methods Background Conclusion Conclusions Objective Objectives
Aim Aims Introduction Discussion Abstract Purpose Study Studies Data Table
Figure Fig However Moreover Furthermore Therefore Thus Also Among Between
Amazon Amazonian Amazonia Brazil Brazilian Peru Colombia Bolivia Ecuador
Venezuela Guiana French South North America American Latin Para Manaus
Rio Acre Amapa Roraima Rondonia Tocantins Maranhao Mato Grosso State Federal
University National Institute Department Ministry Brasil Sao Paulo Janeiro
After Before During Under Over Using Based Compared Total Two Three One
High Low New Old Recent Several Various Different Other Its It They He She
When While Where Which What Who How Why Although Despite Due Since Until
Antioxidant Anti Skin Human Cell Cells Extract Extracts Oil Oils Fruit Fruits
Leaf Leaves Seed Seeds Bark Root Roots Plant Plants Species Natural Total
""".split())
NAO_EPITETO = set("""
extract extracts extraction oil oils seed seeds leaf leaves fruit fruits
bark root roots stem stems flower flowers pulp peel juice resin latex
was were is are be been has have had and or of the to in on for from with
by as at an a that this these those which who than then also not but
study studies species plants plant samples sample showed shows show
activity activities effect effects potential compounds compound content
results data cells cell skin collagen elastase tyrosinase aging ageing
ethanol ethanolic methanol methanolic aqueous hydroalcoholic essential
fraction fractions treatment treated using used use both total high low
group groups rats mice model models assay assays test tests method methods
river basin region forest state federal university nut nuts tree trees
""".split())
RE_BINOMIO = re.compile(r"\b([A-Z][a-z]{2,})\s+([a-z][a-z\-]{2,})\b")
RE_ABREVIADO = re.compile(r"\b([A-Z])\.\s*([a-z][a-z\-]{2,})\b")


# =============================================================================
# Extração e validação de nomes científicos
# =============================================================================
# Terminações de palavras inglesas/técnicas que nomes latinos não têm
# (ex.: "Tyrosinase inhibition", "Antioxidant activity", "Cells treated").
RE_NAO_LATIM_GENERO = re.compile(r"(ase|ases|tion|tions|sion|ity|ment|ness|ing|ics|ogy|"
                                 r"ive|ous|ful|less|ated|ized|ised)$")
RE_NAO_LATIM_EPITETO = re.compile(r"(tion|tions|sion|ity|ities|ment|ments|ness|ing|ed|ly|"
                                  r"ase|ases|ive|ful|less|ism|ists?|ogy)$")


def _valido(genero: str, epiteto: str) -> bool:
    return (genero not in NAO_GENERO and epiteto not in NAO_EPITETO
            and not epiteto.endswith("-")
            and not RE_NAO_LATIM_GENERO.search(genero.lower())
            and not RE_NAO_LATIM_EPITETO.search(epiteto))


def candidatos(artigo: dict) -> set:
    """Binômios citados no título/resumo, inclusive em itálico e na forma
    abreviada ('E. oleracea' quando 'Euterpe' aparece no mesmo texto)."""
    texto = f"{artigo.get('titulo', '')}. {artigo.get('resumo', '')}"
    achados = set()
    for trecho in artigo.get("italicos") or []:
        partes = trecho.split()
        if len(partes) >= 2 and re.fullmatch(r"[A-Z][a-z]{2,}", partes[0]) \
                and re.fullmatch(r"[a-z][a-z\-]{2,}", partes[1]) \
                and _valido(partes[0], partes[1]):
            achados.add(f"{partes[0]} {partes[1]}")
    for genero, epiteto in RE_BINOMIO.findall(texto):
        if _valido(genero, epiteto):
            achados.add(f"{genero} {epiteto}")
    generos = {}
    for nome in achados:
        generos.setdefault(nome[0], set()).add(nome.split()[0])
    for inicial, epiteto in RE_ABREVIADO.findall(texto):
        possiveis = generos.get(inicial, set())
        if len(possiveis) == 1 and epiteto not in NAO_EPITETO:
            achados.add(f"{next(iter(possiveis))} {epiteto}")
    return achados


# =============================================================================
# Artigos
# =============================================================================
def referencia(art: dict) -> str:
    if art.get("pmid"):
        return f"PMID {art['pmid']}"
    if art.get("doi"):
        return f"DOI {art['doi']}"
    return f"OpenAlex {art.get('id', '?')}"


def _contar_pubmed(sessao, consulta: str) -> int | None:
    try:
        r = sessao.get(EUTILS + "esearch.fcgi", timeout=30, params={
            **params_ncbi(), "db": "pubmed", "term": consulta, "retmode": "json",
            "rettype": "count"})
        r.raise_for_status()
        return int(r.json()["esearchresult"]["count"])
    except (requests.RequestException, ValueError, KeyError):
        return None
    finally:
        time.sleep(PAUSA_NCBI)


def _maximo() -> int:
    m = CFG_ARTIGOS["max_artigos"]
    return m if m > 0 else 10 ** 9


def _fatias_por_ano(sessao, consulta: str, ini: int, fim: int) -> list | None:
    """Divide a busca em intervalos de anos de publicação até cada um ter
    menos de 10 mil resultados (limite do PubMed por busca)."""
    n = _contar_pubmed(sessao, f"({consulta}) AND {ini}:{fim}[dp]")
    if n is None:
        return None
    if n == 0:
        return []
    if n < LIMITE_ESEARCH or ini == fim:
        return [(ini, fim)]
    meio = (ini + fim) // 2
    a = _fatias_por_ano(sessao, consulta, ini, meio)
    b = _fatias_por_ano(sessao, consulta, meio + 1, fim)
    return None if a is None or b is None else a + b


def descoberta_pubmed(sessao, regiao: str) -> list:
    """Artigos do PubMed que citam a região (e o contexto vegetal, se ligado)."""
    contexto = f" AND {CONTEXTO_PLANTA_PUBMED}" if CFG_ARTIGOS["contexto_vegetal"] else ""
    consulta = finalizar(f"{regiao}{contexto} AND hasabstract", excluir_revisoes=False)
    total = _contar_pubmed(sessao, consulta)
    maximo = _maximo()
    if total is not None:
        print(f"  PubMed: {total} artigo(s) citam a região"
              + (f"; serão lidos {maximo} (max_artigos)" if total > maximo else ""))
    if total is not None and total > LIMITE_ESEARCH and maximo > LIMITE_ESEARCH:
        # mais de 10 mil: busca fatiada por ano de publicação
        fatias = _fatias_por_ano(sessao, consulta, 1800, time.localtime().tm_year + 1)
        if fatias is None:
            print("  ! PubMed: falha ao dividir a busca por ano - será tentado na próxima execução")
            return []
        buscas = [(f"descoberta|regiao|{a}:{b}", f"({consulta}) AND {a}:{b}[dp]",
                   LIMITE_ESEARCH - 1) for a, b in fatias]
        res = buscar_pmids(sessao, buscas, descricao="PubMed (descoberta, por ano)")
        pmids = list(dict.fromkeys(p for chave, _, _ in reversed(buscas)
                                   for p in res.get(chave, [])))[:maximo]
    else:
        pmids = buscar_pmids(sessao, [("descoberta|regiao", consulta, min(maximo, LIMITE_ESEARCH - 1))],
                             descricao="PubMed (descoberta)").get("descoberta|regiao", [])
    artigos = baixar_artigos(sessao, set(pmids))
    lista = [dict(artigos[p], base="PubMed") for p in pmids if p in artigos]
    print(f"  PubMed: {len(lista)} artigo(s) lidos")
    return lista


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn").lower()


def regex_termo(termo: str):
    """Termo no estilo PubMed -> regex com o MESMO sentido: palavra inteira,
    '*' = truncamento, sem acentos, hífen ou espaço entre palavras.
    'melanin*' casa melanin/melanogenesis; 'aging' casa só aging."""
    t = _sem_acento(re.sub(r"\[[^\]]*\]", "", termo).strip().strip('"').strip())
    if not t:
        return None
    # espaço entre palavras -> espaço ou hífen; hífen -> hífen, espaço ou nada
    # ("anti-aging" casa anti-aging, anti aging e antiaging)
    pedacos = re.split(r"(\s+|-)", t)
    regex = ""
    for p in pedacos:
        if not p:
            continue
        if p == "-":
            regex += r"[\s\-]*"
        elif p.isspace():
            regex += r"[\s\-]+"
        else:
            regex += re.escape(p).replace(r"\*", r"\w*")
    return re.compile(r"(?<![\w])" + regex + r"(?![\w])")


def _confere_texto(trabalho: dict, padroes: list) -> bool:
    texto = _sem_acento(f"{trabalho.get('titulo', '')} {trabalho.get('resumo', '')}")
    return any(p.search(texto) for p in padroes)


def descoberta_openalex(sessao) -> list:
    """Trabalhos do OpenAlex que citam a região (e o contexto vegetal).
    A busca do OpenAlex reduz as palavras ao radical e traz trabalhos que não
    citam a região; por isso cada trabalho é CONFERIDO no texto (título +
    resumo) e só fica se citar um dos termos da região, com o mesmo sentido
    que teriam no PubMed."""
    termos_regiao = CFG_ARTIGOS["termos_regiao"]
    regiao = " OR ".join(termo_openalex(t) for t in termos_regiao)
    contexto = f" AND {CONTEXTO_PLANTA_OPENALEX}" if CFG_ARTIGOS["contexto_vegetal"] else ""
    consulta = f"({regiao}){contexto}".replace(",", " ")
    trabalhos = buscar_openalex(sessao, consulta, _maximo())
    if trabalhos is None:
        return []  # sem cota/conexão: segue só com o PubMed
    padroes_regiao = [p for p in map(regex_termo, termos_regiao) if p]
    confirmados = [t for t in trabalhos if _confere_texto(t, padroes_regiao)]
    print(f"  OpenAlex: {len(trabalhos)} trabalho(s) retornados, "
          f"{len(confirmados)} citam de fato a região")
    return [dict(t, base="OpenAlex") for t in confirmados]


def formatar_atividades(atividades: dict) -> str:
    ordem = sorted(atividades.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return "; ".join(f"{rotulo_exibicao(r)} ({len(refs)} artigo{'s' if len(refs) > 1 else ''})"
                     for r, refs in ordem)



def atividades_no_texto(artigo: dict, padroes_foco: dict) -> list:
    """Rótulos de [termos_pubmed] cujos termos aparecem no título/resumo."""
    return [r for r, padroes in padroes_foco.items() if _confere_texto(artigo, padroes)]


def descobrir(sessao) -> tuple[dict, list]:
    """Devolve ({nome_em_minúsculas: {"nome", "atividades": {rótulo: refs},
    "refs"}}, [evidências]) com os nomes científicos citados nos artigos da
    região (ainda sem filtro: o que não é planta é retirado na etapa
    "plantas", pelas bases taxonômicas)."""
    if not CFG_ARTIGOS["ativar"]:
        print("[artigos] ativar = false - descoberta em artigos desligada.")
        return {}, []
    if not (CFG_ARTIGOS["usar_pubmed"] or CFG_ARTIGOS["usar_openalex"]):
        print("[artigos]: usar_pubmed e usar_openalex estão ambos false - descoberta pulada.")
        return {}, []
    termos = CFG_ARTIGOS["termos_regiao"]
    print(f"Descoberta em artigos: região ({', '.join(termos)})"
          + (" + contexto vegetal" if CFG_ARTIGOS["contexto_vegetal"] else ""))
    if FOCO:
        print("  As atividades de [termos_pubmed] não restringem a busca; só são "
              "anotadas quando aparecem no texto.")

    artigos = []
    if CFG_ARTIGOS["usar_pubmed"]:
        regiao = "(" + " OR ".join(formatar_termo(t) for t in termos) + ")"
        artigos += descoberta_pubmed(sessao, regiao)
    if CFG_ARTIGOS["usar_openalex"]:
        artigos += descoberta_openalex(sessao)

    # sem [termos_pubmed], anota a atividade biológica em geral (os mesmos
    # termos do filtro geral da etapa "pubmed"); antes, a coluna
    # atividades_artigos de plantas.csv saía vazia nesse caso
    foco = FOCO or {"": TERMOS_ATIVIDADE_GERAL}
    padroes_foco = {r: [p for p in map(regex_termo, t) if p] for r, t in foco.items()}
    registros, evidencias, vistos = {}, [], set()
    n_artigos = 0
    for art in artigos:
        ids = {art.get("pmid") or None, (art.get("doi") or "").lower() or None}
        ids.discard(None)
        if ids & vistos:        # mesmo artigo vindo do PubMed e do OpenAlex
            continue
        vistos |= ids
        n_artigos += 1
        ref = referencia(art)
        rotulos = atividades_no_texto(art, padroes_foco)
        for nome in candidatos(art):
            reg = registros.setdefault(nome.lower(), {"nome": nome, "atividades": {},
                                                      "refs": set()})
            for r in rotulos:
                reg["atividades"].setdefault(r, set()).add(ref)
            reg["refs"].add(ref)
            evidencias.append({"nome_no_artigo": nome,
                               "atividades_no_texto": "; ".join(rotulo_exibicao(r) for r in rotulos),
                               "base": art.get("base"), "referencia": ref,
                               "ano": art.get("ano"), "titulo": art.get("titulo"),
                               "doi": art.get("doi")})
    print(f"  {n_artigos} artigo(s) distintos; {len(registros)} nome(s) científico(s) citados")
    return registros, evidencias
