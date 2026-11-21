"""
taxonomia.py

Módulo compartilhado (não é executado diretamente): confere nomes de
plantas em três bases e decide o nome ACEITO de cada um.

  1. Flora e Funga do Brasil (JBRJ)  lista oficial do Brasil   (download)
  2. World Flora Online (WFO)        lista mundial (vasculares e briófitas)
  3. WCVP (Kew)                      lista mundial de plantas vasculares
  4. GBIF Backbone                   API species/match; também fornece
                                     filo, classe, ordem e família

As três listas são baixadas uma vez (dados/flora_brasil/, dados/wfo/,
dados/wcvp/) e consultadas localmente; o GBIF é consultado pela internet,
um nome por vez.
Tudo fica em cache (cache_taxonomia_*.jsonl), então uma execução
interrompida não refaz o que já foi conferido.

Prioridade quando as bases discordam: Flora e Funga do Brasil > WFO > WCVP > GBIF.
"""

import difflib
import hashlib
import io
import json
import os

import caminhos as _C
import re
import time
import zipfile

import pandas as pd
import requests

from config_pipeline import carregar_config_taxonomia, trocar

CFG = carregar_config_taxonomia()
HEADERS = {"User-Agent": "Pipeline-Prospeccao-Plantas-Bioativos/2.0"}

# Alguns servidores (o IPT do JBRJ, por exemplo) recusam com 403 programas que
# não se identificam como navegador; os downloads das listas usam este.
UA_NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

URL_FLORA = "https://ipt.jbrj.gov.br/jbrj/archive.do?r=lista_especies_flora_brasil"
# WFO: a lista completa (Darwin Core, com classification.csv) é publicada a cada
# seis meses no Zenodo ("World Flora Online Plant List"). Ordem de tentativa:
#   1. versão mais recente no Zenodo (descoberta pela API)
#   2. versão de junho/2026 no Zenodo (endereço fixo)
#   3. servidor antigo do WFO
ZENODO_WFO_REGISTRO = "20782718"   # WFO Plant List June 2026
ZENODO_WFO_ARQUIVO = "_DwC_backbone_R.zip"
URL_WFO_ZENODO_FIXO = (f"https://zenodo.org/records/{ZENODO_WFO_REGISTRO}/files/"
                       f"{ZENODO_WFO_ARQUIVO}?download=1")
URL_WFO_ANTIGO = ("https://files.worldfloraonline.org/files/WFO_Backbone/"
                  "_WFOCompleteBackbone/WFO_Backbone.zip")


def url_wfo_zenodo_recente() -> str | None:
    """Endereço do backbone na versão mais recente da WFO Plant List no Zenodo."""
    try:
        r = requests.get(f"https://zenodo.org/api/records/{ZENODO_WFO_REGISTRO}/versions/latest",
                         headers={"User-Agent": UA_NAVEGADOR}, timeout=60)
        r.raise_for_status()
        dados = r.json()
        for f in dados.get("files", []):
            if f.get("key") == ZENODO_WFO_ARQUIVO:
                print(f"World Flora Online: versão mais recente no Zenodo = "
                      f"{dados.get('metadata', {}).get('title', dados.get('id'))}")
                return f["links"]["self"]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


URL_WFO = [url_wfo_zenodo_recente, URL_WFO_ZENODO_FIXO, URL_WFO_ANTIGO]
# WCVP (World Checklist of Vascular Plants, Kew): versão mais recente, CSV
# separado por "|" dentro do zip (wcvp_names.csv)
URL_WCVP = "https://sftp.kew.org/pub/data-repositories/WCVP/wcvp.zip"
URL_GBIF_MATCH = "https://api.gbif.org/v1/species/match"

BASES = [("flora", "Flora e Funga do Brasil"), ("wfo", "WFO"), ("wcvp", "WCVP"), ("gbif", "GBIF")]
LOCAIS = ("flora", "wfo", "wcvp")   # listas baixadas, consultadas no próprio computador
NOME_BASE = dict(BASES)
ORDEM_BASE = {b: i for i, (b, _) in enumerate(BASES)}

RECONHECIDO = {"aceito", "sinonimo", "grafia", "genero", "nao_verificado", "ambiguo"}
# Qualidade de cada tipo de resposta, usada para decidir entre as bases: uma
# resposta EXATA de qualquer base vale mais que uma correção de grafia ou um
# nome sem status confirmado de uma base de prioridade maior.
NIVEL = {"aceito": 0, "sinonimo": 0, "genero": 0, "grafia": 1, "nao_verificado": 2, "ambiguo": 2}
# versão das regras de conferência: muda quando as regras mudam, para que os
# caches antigos (feitos com regras anteriores) não sejam reaproveitados
VERSAO_REGRAS = "v2"
RANKS_INFRA = {"var": "var.", "variety": "var.", "variedade": "var.",
               "subsp": "subsp.", "ssp": "subsp.", "subspecies": "subsp.",
               "sub_especie": "subsp.", "subespecie": "subsp.",
               "f": "f.", "forma": "f.", "form": "f."}
SIMILARIDADE_PREFILTRO = 0.80   # só pré-seleciona candidatos; quem decide é grafia_segura()
# terminações latinas que mudam com o gênero gramatical ou a forma do epíteto
# (ex.: guianensis/guianense, minutus/minuta/minutum, glaziovii/glaziovi)
TERMINACOES = sorted(["ensis", "ense", "iana", "ianus", "ianum", "ii", "ae", "ius", "ia", "ium",
                      "us", "um", "a", "is", "e", "i", "er", "ra", "rum", "os", "on", "es"],
                     key=len, reverse=True)


# =============================================================================
# Nomes
# =============================================================================
def _canonico(genero, epiteto=None, rank_infra=None, infra=None) -> str:
    if not isinstance(genero, str) or not genero.strip():
        return ""
    nome = genero.strip().capitalize()
    if isinstance(epiteto, str) and epiteto.strip():
        nome += " " + epiteto.strip().lower()
        if isinstance(infra, str) and infra.strip():
            marca = RANKS_INFRA.get(str(rank_infra or "").strip(".").lower(), "var.")
            nome += f" {marca} {infra.strip().lower()}"
    return nome


def analisar(nome: str) -> dict:
    """Separa um nome livre (do usuário ou de artigo) em partes, sem autoria.
    'Erythroxylum coca var. ipadu' -> gênero, epíteto, var., ipadu.
    'Acmella sp.' e 'Copaifera' -> só gênero."""
    partes = [p for p in re.sub(r"[×()\[\],;]", " ", str(nome)).split()
              if p.lower() not in {"x", "cf.", "aff.", "cf", "aff"}]
    if not partes:
        return {"genero": "", "epiteto": None, "rank": None, "infra": None}
    genero = partes[0]
    if len(partes) < 2 or not partes[1][:1].islower() or partes[1].lower().strip(".") in {"sp", "spp"}:
        return {"genero": genero, "epiteto": None, "rank": None, "infra": None}
    epiteto, rank, infra = partes[1], None, None
    for i in range(2, len(partes) - 1):
        marca = partes[i].lower().strip(".")
        if marca in RANKS_INFRA and partes[i + 1][:1].islower() \
                and partes[i + 1].lower() not in {"ex", "et", "in", "&"}:
            rank, infra = marca, partes[i + 1]
            break
    return {"genero": genero, "epiteto": epiteto, "rank": rank, "infra": infra}


def canonico(nome: str) -> str:
    a = analisar(nome)
    return _canonico(a["genero"], a["epiteto"], a["rank"], a["infra"])


def chave(nome: str) -> str:
    return canonico(nome).lower()


def eh_genero(nome: str) -> bool:
    return analisar(nome)["epiteto"] is None


def chave_cache(nome: str) -> str:
    return f"{chave(nome)}|{int(CFG['corrigir_grafia'])}|{VERSAO_REGRAS}"


# =============================================================================
# Correção de grafia SEGURA
# =============================================================================
# Uma correção de grafia só é aceita quando a diferença é do tipo que um erro
# de digitação ou de concordância produz - nunca quando o "nome parecido" é
# outra espécie. Comparar o nome inteiro (gênero + epíteto) é enganoso,
# porque o gênero igual infla a semelhança: "Solenopsis geminata" (formiga) e
# "Solenopsis minuta" (planta) são 86% parecidos. Por isso só os EPÍTETOS são
# comparados, e a diferença tolerada é mínima:
#   - mesma raiz, terminação diferente (minutus/minuta, guianensis/guianense);
#   - uma única letra trocada, a mais ou a menos, em epítetos com 5+ letras
#     (speciosas -> speciosa, guyanensis -> guianensis).
# "Linum bahiense" -> "Linum bahamense" (2 letras) e "Eucalyptus branches" ->
# "Eucalyptus burgessiana" são recusados.
def _radical(epiteto: str) -> str:
    for t in TERMINACOES:
        if epiteto.endswith(t) and len(epiteto) - len(t) >= 4:
            return epiteto[:-len(t)]
    return epiteto


def _distancia(a: str, b: str) -> int:
    """Distância de edição entre duas palavras curtas: letra trocada, a mais,
    a menos ou duas letras vizinhas invertidas (aspiliodies/aspilioides)
    contam 1 cada."""
    if abs(len(a) - len(b)) > 2:
        return 3
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _normalizar_epiteto(e: str) -> str:
    """Variantes ortográficas que o Código de Nomenclatura trata como o MESMO
    nome: hífen (flavo-virens/flavovirens), "ae" de ligação antes de -folius,
    -formis, -florus (artemisiaefolia/artemisiifolia), i duplo (glaziovii/
    glaziovi), u/v (glazioui/glaziovii)."""
    e = e.lower().replace("-", "")
    e = re.sub(r"ae(?=(fol|form|flor))", "i", e)
    e = e.replace("v", "u")
    return re.sub(r"i+", "i", e)


def _epitetos_compativeis(x: str, y: str) -> bool:
    x, y = x.lower(), y.lower()
    if x == y:
        return True
    x, y = _normalizar_epiteto(x), _normalizar_epiteto(y)
    if x == y:
        return True
    if _radical(x) == _radical(y) and len(_radical(x)) >= 4:
        return True
    return min(len(x), len(y)) >= 5 and _distancia(x, y) == 1


def grafia_segura(original: str, candidato: str) -> bool:
    """True se `candidato` pode ser tomado como a grafia correta de `original`
    (mesmo gênero; epítetos diferindo só por terminação ou por uma letra)."""
    a, b = analisar(original), analisar(candidato)
    if not a["epiteto"] or not b["epiteto"] or a["genero"].lower() != b["genero"].lower():
        return False
    if bool(a["infra"]) != bool(b["infra"]):
        return False
    pares = [(a["epiteto"], b["epiteto"])] + ([(a["infra"], b["infra"])] if a["infra"] else [])
    diferentes = [(x, y) for x, y in pares if x.lower() != y.lower()]
    return len(diferentes) == 1 and _epitetos_compativeis(*diferentes[0])


def _epiteto(nome: str) -> str:
    return (analisar(nome)["epiteto"] or "").lower()


# =============================================================================
# Cache
# =============================================================================
def _carregar_cache(caminho):
    dados = {}
    if os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                try:
                    item = json.loads(linha)
                    dados[item["chave"]] = item
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
    return dados


def _gravar_cache(caminho, item):
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


_TRUSTSTORE_ATIVO = False


def _usar_certificados_do_sistema() -> bool:
    """Passa a validar HTTPS com o repositório de certificados do sistema
    operacional (pacote truststore). Resolve 'CERTIFICATE_VERIFY_FAILED /
    unable to get local issuer certificate' em servidores que não enviam a
    cadeia completa - o navegador completa a cadeia, o Python não. A
    verificação continua ligada."""
    global _TRUSTSTORE_ATIVO
    if _TRUSTSTORE_ATIVO:
        return False
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    _TRUSTSTORE_ATIVO = True
    return True


def _baixar_um(url, tmp):
    with requests.get(url, headers={"User-Agent": UA_NAVEGADOR}, stream=True,
                      timeout=900) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloco in r.iter_content(chunk_size=1 << 20):
                f.write(bloco)
    if not zipfile.is_zipfile(tmp):
        raise requests.RequestException("o servidor não devolveu um arquivo .zip "
                                        "(provavelmente uma página de erro ou bloqueio)")


def _baixar(urls, destino, rotulo):
    """Baixa a lista para `destino`, tentando cada endereço de `urls` (texto,
    função que devolve o endereço, ou lista desses) até um funcionar."""
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return
    candidatos = urls if isinstance(urls, (list, tuple)) else [urls]
    tmp = destino + ".parcial"
    erros, primeiro_url = [], None
    for candidato in candidatos:
        url = candidato() if callable(candidato) else candidato
        if not url:
            continue
        primeiro_url = primeiro_url or url
        print(f"{rotulo}: baixando a lista ({url}) - só na primeira vez...")
        for _ in range(2):
            try:
                _baixar_um(url, tmp)
                trocar(tmp, destino)
                return
            except requests.exceptions.SSLError as e:
                if _usar_certificados_do_sistema():
                    print("  certificado não verificado pelo Python - tentando de novo "
                          "com os certificados do sistema (truststore)...")
                    continue
                dica = ("" if _TRUSTSTORE_ATIVO else
                        " [instale o pacote truststore: pip install truststore]")
                erros.append(f"{url}: {e}{dica}")
            except requests.RequestException as e:
                erros.append(f"{url}: {e}")
            break
        if os.path.exists(tmp):
            os.remove(tmp)
        if candidato is not candidatos[-1]:
            print("  falhou - tentando o próximo endereço...")
    raise RuntimeError(
        f"{rotulo}: não foi possível baixar a lista.\n  " + "\n  ".join(erros)
        + f"\n  Alternativa: baixe pelo navegador ({primeiro_url or '?'}) e salve o "
        f"arquivo como {os.path.abspath(destino)}")


# =============================================================================
# Listas baixadas (Flora e Funga do Brasil, WFO)
# =============================================================================
def _col(df, *nomes):
    mapa = {c.lower(): c for c in df.columns}
    for n in nomes:
        if n.lower() in mapa:
            return mapa[n.lower()]
    return None


def _ler_tabela(zip_path, prefixos, usar=None):
    with zipfile.ZipFile(zip_path) as z:
        for prefixo in prefixos:
            for n in z.namelist():
                base = os.path.basename(n).lower()
                if base.startswith(prefixo) and base.endswith((".txt", ".csv", ".tsv")):
                    with z.open(n) as f:
                        texto = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                        cab = pd.read_csv(texto, sep="\t", nrows=0, quoting=3).columns
                    colunas = [c for c in cab if usar is None or c.lower() in usar]
                    with z.open(n) as f:
                        texto = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                        return pd.read_csv(texto, sep="\t", dtype=str, quoting=3,
                                           usecols=colunas, on_bad_lines="skip")
    raise RuntimeError(f"Tabela {prefixos} não encontrada em {zip_path}. Apague o "
                       "arquivo e rode de novo para baixá-lo outra vez.")


class ListaBaixada:
    """Consulta exata (e, opcionalmente, por grafia parecida) numa lista
    taxonômica no formato Darwin Core."""

    COLUNAS = {"id", "taxonid", "acceptednameusageid", "scientificname", "kingdom",
               "family", "genus", "specificepithet", "infraspecificepithet",
               "taxonrank", "verbatimtaxonrank", "taxonomicstatus"}

    def __init__(self, base, rotulo, url, zip_path, prefixos):
        self.base, self.rotulo = base, rotulo
        self.url, self.zip_path, self.prefixos = url, zip_path, prefixos
        self.df = None
        self.cache_path = _C.cache(f"cache_taxonomia_{base}.jsonl")
        self.cache = _carregar_cache(self.cache_path)

    def _carregar(self):
        if self.df is not None:
            return
        _baixar(self.url, self.zip_path, self.rotulo)
        print(f"{self.rotulo}: lendo a lista...")
        df = self._ler_bruto()
        c = lambda *n: _col(df, *n)  # noqa: E731
        reino = c("kingdom")
        if reino:
            df = df[df[reino].fillna("Plantae").str.lower().str.startswith("plant")]
        rank_infra = c("verbatimTaxonRank") or c("taxonRank")
        tab = pd.DataFrame({
            "id": df[c("taxonID") or c("id")],
            "aceito_id": df[c("acceptedNameUsageID")] if c("acceptedNameUsageID") else None,
            "nome_lista": df[c("scientificName")],
            "familia": df[c("family")] if c("family") else None,
            "genero": df[c("genus")].fillna(""),
            "epiteto": df[c("specificEpithet")].fillna("") if c("specificEpithet") else "",
            "infra": df[c("infraspecificEpithet")].fillna("") if c("infraspecificEpithet") else "",
            "rank_infra": df[rank_infra].fillna("") if rank_infra else "",
            "status": df[c("taxonomicStatus")].fillna("").str.lower() if c("taxonomicStatus") else "",
        })
        # gênero vazio (algumas linhas só têm scientificName): extrai do nome
        sem = tab["genero"] == ""
        if sem.any():
            partes = tab.loc[sem, "nome_lista"].map(analisar)
            tab.loc[sem, "genero"] = partes.map(lambda a: a["genero"])
            tab.loc[sem, "epiteto"] = partes.map(lambda a: a["epiteto"] or "")
        tab["canonico"] = [
            _canonico(g, e or None, r if i else None, i or None)
            for g, e, r, i in zip(tab["genero"], tab["epiteto"], tab["rank_infra"], tab["infra"])]
        tab["chave"] = tab["canonico"].str.lower()
        tab["genero_l"] = tab["genero"].str.lower()
        self.df = tab[tab["chave"] != ""].reset_index(drop=True)
        self.generos = set(self.df["genero_l"])
        self.por_genero = self.df.groupby("genero_l")["chave"].agg(lambda s: sorted(set(s)))
        self.canonico_por_id = dict(zip(self.df["id"], self.df["canonico"]))
        self.indice = self.df.groupby("chave").indices
        tipos = self.df["status"].map(self._tipo_status)
        aceitos = self.df[tipos == "aceito"]
        self.familia_por_canonico = dict(zip(aceitos["canonico"], aceitos["familia"]))
        # sinônimos de cada nome aceito (para nomes_busca). Ficam de fora os
        # AMBÍGUOS: nomes que apontam para mais de uma espécie (homônimos, ex.:
        # Schedonorus arundinaceus) ou que também são nome aceito de outra
        sin = pd.DataFrame({"sinonimo": self.df.loc[tipos == "sinonimo", "canonico"],
                            "aceito": self.df.loc[tipos == "sinonimo", "aceito_id"].map(self.canonico_por_id)})
        sin = sin.dropna()
        sin = sin[sin["sinonimo"].str.lower() != sin["aceito"].str.lower()].drop_duplicates()
        n_alvos = sin.groupby(sin["sinonimo"].str.lower())["aceito"].transform(
            lambda a: a.str.lower().nunique())
        nomes_aceitos = set(aceitos["chave"])
        sin = sin[(n_alvos == 1) & ~sin["sinonimo"].str.lower().isin(nomes_aceitos)]
        self.sinonimos = sin.groupby(sin["aceito"].str.lower())["sinonimo"].agg(list).to_dict()
        print(f"{self.rotulo}: {len(self.df)} nomes de plantas carregados")

    def _ler_bruto(self) -> pd.DataFrame:
        """Tabela no formato Darwin Core (taxonID, scientificName, ...)."""
        return _ler_tabela(self.zip_path, self.prefixos, self.COLUNAS)

    @staticmethod
    def _tipo_status(status: str) -> str:
        if "misappl" in status:      # nome mal aplicado: não é sinônimo do outro táxon
            return "nao_verificado"
        if "sinon" in status or "synonym" in status or "orthograph" in status:
            return "sinonimo"
        if "aceit" in status or "accepted" in status or "correto" in status:
            return "aceito"
        return "nao_verificado"

    def _resolver_exato(self, k):
        """Resolve um nome presente na lista. Trata HOMÔNIMOS: o mesmo nome,
        de autores diferentes, pode ser sinônimo de espécies diferentes (ex.:
        "Schedonorus arundinaceus" é sinônimo de Lolium arundinaceum, mas um
        homônimo é sinônimo de Scolochloa festucacea). Sem o autor, não dá
        para escolher com segurança:
          - se alguma linha é nome ACEITO, vale ela;
          - se todas são sinônimos de UM só nome, vale esse nome;
          - se apontam para nomes diferentes, vale o de MESMO epíteto (a
            combinação nova do mesmo nome); se não houver um só assim, o nome
            NÃO é corrigido (status "ambiguo") e as opções vão para a observação."""
        if k not in self.indice:
            return None
        linhas = self.df.iloc[self.indice[k]]
        linhas = linhas.assign(_t=linhas["status"].map(self._tipo_status))
        aceitas = linhas[linhas["_t"] == "aceito"]
        if not aceitas.empty:
            linha = aceitas.iloc[0]
            res = {"status": "aceito", "aceito": linha["canonico"], "familia": linha["familia"],
                   "nome_lista": linha["nome_lista"], "status_lista": linha["status"]}
            outros = sorted({self.canonico_por_id.get(a) for a in linhas.loc[linhas["_t"] == "sinonimo", "aceito_id"]}
                            - {None, linha["canonico"]})
            if outros:
                res["obs"] = "homônimo: também consta como sinônimo de " + ", ".join(outros)
            return res
        sinonimos = linhas[linhas["_t"] == "sinonimo"]
        alvos = []
        for a in sinonimos["aceito_id"]:
            alvo = self.canonico_por_id.get(a)
            if alvo and alvo not in alvos:
                alvos.append(alvo)
        if len(alvos) == 1:
            return {"status": "sinonimo", "aceito": alvos[0],
                    "familia": self.familia_por_canonico.get(alvos[0], sinonimos["familia"].iloc[0]),
                    "nome_lista": sinonimos["nome_lista"].iloc[0], "status_lista": "sinonimo"}
        if len(alvos) > 1:
            ep = _radical(_epiteto(k))
            mesmo = [a for a in alvos if _radical(_epiteto(a)) == ep]
            if len(mesmo) == 1:
                return {"status": "sinonimo", "aceito": mesmo[0],
                        "familia": self.familia_por_canonico.get(mesmo[0]),
                        "nome_lista": sinonimos["nome_lista"].iloc[0], "status_lista": "sinonimo",
                        "obs": "homônimo: conforme o autor, também é sinônimo de "
                               + ", ".join(a for a in alvos if a != mesmo[0])
                               + f" (escolhido {mesmo[0]}, de mesmo epíteto)"}
            return {"status": "ambiguo", "aceito": linhas["canonico"].iloc[0], "familia": None,
                    "nome_lista": sinonimos["nome_lista"].iloc[0], "status_lista": "sinonimo",
                    "obs": "homônimo: conforme o autor, é sinônimo de " + " ou de ".join(alvos)
                           + " - nome mantido como está"}
        linha = linhas.iloc[0]
        return {"status": "nao_verificado", "aceito": linha["canonico"], "familia": linha["familia"],
                "nome_lista": linha["nome_lista"], "status_lista": linha["status"]}

    def sinonimos_de(self, aceito: str) -> list:
        """Sinônimos (não ambíguos) de um nome aceito, segundo esta lista."""
        self._carregar()
        return self.sinonimos.get(canonico(aceito).lower(), [])

    def genero_existe(self, genero: str) -> bool:
        self._carregar()
        return genero.lower() in self.generos

    def conferir(self, nome: str) -> dict:
        k = chave(nome)
        ck = chave_cache(nome)
        if ck in self.cache:
            return self.cache[ck]["resultado"]
        self._carregar()
        a = analisar(nome)
        if a["epiteto"] is None:
            g = a["genero"].lower()
            res = ({"status": "genero", "aceito": a["genero"].capitalize()}
                   if g in self.generos else {"status": "nao_encontrado"})
        else:
            res = self._resolver_exato(k)
            if res is None and a["genero"].lower() in self.por_genero.index:
                res = self._corrigir_grafia(nome, k, a["genero"].lower())
            res = res or {"status": "nao_encontrado"}
        self.cache[ck] = {"chave": ck, "resultado": res}
        _gravar_cache(self.cache_path, self.cache[ck])
        return res

    def _corrigir_grafia(self, nome, k, genero) -> dict | None:
        """Procura a grafia correta no mesmo gênero. Só corrige se houver UM
        candidato que passe em grafia_segura(); senão, só sugere (observação)."""
        parecidos = difflib.get_close_matches(k, self.por_genero[genero], n=6,
                                              cutoff=SIMILARIDADE_PREFILTRO)
        if not parecidos:
            return None
        canon = {p: self.df.iloc[self.indice[p][0]]["canonico"] for p in parecidos}
        seguros = [p for p in parecidos if grafia_segura(nome, canon[p])]
        if CFG["corrigir_grafia"] and len(seguros) == 1:
            res = self._resolver_exato(seguros[0])
            if res and res["status"] != "ambiguo":
                res["grafia_lista"] = canon[seguros[0]]
                res["status_original"] = res["status"]
                res["status"] = "grafia"
                return res
        if len(seguros) > 1:
            obs = "grafia parecida com mais de um nome (" + ", ".join(canon[p] for p in seguros) + ") - não corrigido"
        else:
            obs = f"nome parecido: {canon[(seguros or parecidos)[0]]} (não corrigido; confira)"
        return {"status": "nao_encontrado", "obs": obs}


# =============================================================================
# GBIF (API)
# =============================================================================
class GBIF:
    def __init__(self, sessao=None):
        self.sessao = sessao or requests.Session()
        self.cache_path = _C.cache("cache_taxonomia_gbif.jsonl")
        self.cache = _carregar_cache(self.cache_path)
        self.falhas_seguidas, self.desligado = 0, False

    def conferir(self, nome: str) -> dict | None:
        """None = falha de rede (tenta de novo na próxima execução)."""
        ck = chave_cache(nome)
        if ck in self.cache:
            return self.cache[ck]["resultado"]
        # cache das regras anteriores: só as respostas por grafia aproximada
        # (FUZZY) precisam ser refeitas; as demais continuam valendo
        antigo = self.cache.get(f"{chave(nome)}|{int(CFG['corrigir_grafia'])}")
        if antigo and (antigo["resultado"] or {}).get("status") != "grafia":
            return antigo["resultado"]
        if self.desligado:
            return None
        try:
            r = self.sessao.get(URL_GBIF_MATCH, headers=HEADERS, timeout=(10, 30), params={
                "name": canonico(nome), "kingdom": "Plantae", "verbose": "false",
                "strict": "false" if CFG["corrigir_grafia"] else "true"})
            r.raise_for_status()
            m = r.json()
        except (requests.RequestException, ValueError):
            self.falhas_seguidas += 1
            if self.falhas_seguidas >= 8:     # cada falha já inclui as novas tentativas da sessão
                # GBIF fora do ar: não espera por milhares de nomes; os que
                # faltarem são conferidos na próxima execução
                self.desligado = True
                print("\nAVISO: GBIF sem resposta em 8 consultas seguidas - a conferência "
                      "no GBIF fica para a próxima execução (as outras bases seguem).")
            return None
        finally:
            time.sleep(0.05)
        self.falhas_seguidas = 0
        res = self._interpretar(nome, m)
        self.cache[ck] = {"chave": ck, "resultado": res}
        _gravar_cache(self.cache_path, self.cache[ck])
        return res

    @staticmethod
    def _interpretar(nome, m) -> dict:
        tipo_match, rank = m.get("matchType", "NONE"), m.get("rank")
        taxo = {"filo": m.get("phylum"), "classe": m.get("class"), "ordem": m.get("order"),
                "familia": m.get("family"), "speciesKey": m.get("speciesKey") or m.get("usageKey")}
        a = analisar(nome)
        if tipo_match in ("NONE", "HIGHERRANK") or not m.get("usageKey"):
            if a["epiteto"] is None and rank == "GENUS":
                return {"status": "genero", "aceito": m.get("genus") or a["genero"], **taxo}
            return {"status": "nao_encontrado"}
        if m.get("kingdom") and m["kingdom"] != "Plantae":
            return {"status": "nao_encontrado", "obs": f"no GBIF é do reino {m['kingdom']}"}
        if a["epiteto"] is None:
            return {"status": "genero", "aceito": m.get("genus") or a["genero"], **taxo}
        if tipo_match == "FUZZY":
            achado = canonico(m.get("canonicalName") or "")
            if not CFG["corrigir_grafia"] or not grafia_segura(nome, achado):
                return {"status": "nao_encontrado",
                        "obs": f"o GBIF sugere {achado} (não corrigido; confira)" if achado else ""}
        status = (m.get("status") or "").upper()
        if status == "SYNONYM":
            aceito = m.get("species") or m.get("canonicalName")
            tipo = "sinonimo"
        else:
            aceito = m.get("canonicalName") or m.get("species")
            tipo = "aceito" if status == "ACCEPTED" else "nao_verificado"
        res = {"status": tipo, "aceito": canonico(aceito), "status_lista": status.lower(), **taxo}
        if tipo_match == "FUZZY":
            res.update({"status_original": tipo, "status": "grafia",
                        "grafia_lista": canonico(m.get("canonicalName") or aceito)})
        return res


# =============================================================================
# Decisão (prioridade Flora > WFO > GBIF)
# =============================================================================
def descrever(base, res) -> str:
    texto = _descrever(base, res)
    if res and res.get("obs") and res.get("status") in RECONHECIDO - {"ambiguo"}:
        texto += f" ({res['obs']})"
    return texto


def _descrever(base, res) -> str:
    rot = NOME_BASE[base]
    if res is None:
        return f"{rot}: consulta pendente"
    st = res.get("status")
    if st == "aceito":
        return f"{rot}: nome aceito"
    if st == "genero":
        return f"{rot}: gênero reconhecido"
    if st == "sinonimo":
        return f"{rot}: sinônimo de {res['aceito']}"
    if st == "grafia":
        extra = (f" (sinônimo de {res['aceito']})"
                 if res.get("status_original") == "sinonimo" else "")
        return f"{rot}: grafia variante de {res.get('grafia_lista') or res['aceito']}{extra}"
    if st == "nao_verificado":
        return f"{rot}: encontrado, sem status confirmado ({res.get('status_lista') or '?'})"
    if st == "ambiguo":
        return f"{rot}: {res.get('obs') or 'homônimo ambíguo'}"
    obs = f" ({res['obs']})" if res.get("obs") else ""
    return f"{rot}: não encontrado{obs}"


def decidir(nome_original: str, resultados: dict) -> dict:
    """resultados: {"flora": res|None, "wfo": ..., "gbif": ...} (só bases usadas).
    Devolve nome aceito, situação, observações e nomes de busca. O nome
    original não é trocado por ninguém: o nome aceito é só anotado."""
    original = canonico(nome_original) or nome_original.strip()
    reconhecidas = [(b, resultados[b]) for b, _ in BASES
                    if resultados.get(b) and resultados[b].get("status") in RECONHECIDO]
    # a resposta mais confiável decide (exata > grafia > sem status/ambígua);
    # entre respostas do mesmo nível, vale a prioridade Flora > WFO > GBIF
    reconhecidas.sort(key=lambda br: NIVEL[br[1]["status"]])
    observacoes = [descrever(b, resultados.get(b)) for b, _ in BASES if b in resultados]

    if not reconhecidas:
        return {"aceito": original, "situacao": "não reconhecido",
                "observacoes": " | ".join(["AVISO: nome não reconhecido em nenhuma base"]
                                          + observacoes),
                "nomes_busca": [original], "base_decisao": ""}

    base, res = reconhecidas[0]
    aceito = res["aceito"]
    st = res["status"]
    # o nome NÃO é trocado: a situação descreve o nome como ele está, e o
    # nome aceito vai para uma coluna própria
    situacao = {"aceito": "aceito", "genero": "gênero", "nao_verificado": "aceito (sem status confirmado)",
                "sinonimo": "sinônimo", "ambiguo": "homônimo ambíguo",
                "grafia": "grafia variante"}[st]
    if st == "grafia" and res.get("status_original") == "sinonimo":
        situacao = "grafia variante de sinônimo"

    aceitos = {}
    for b, r in reconhecidas:
        aceitos.setdefault(r["aceito"].lower(), []).append(NOME_BASE[b])
    if len(aceitos) > 1:
        detalhes = "; ".join(f"{', '.join(bs)}: {n.capitalize()}" for n, bs in aceitos.items())
        observacoes.append(f"DIVERGÊNCIA entre bases ({detalhes}) - usado o da {NOME_BASE[base]}")
    familias = {str(r.get("familia")).strip().lower(): NOME_BASE[b] for b, r in reconhecidas
                if r.get("familia") and str(r.get("familia")).strip() not in ("", "nan")}
    if len(familias) > 1:
        observacoes.append("DIVERGÊNCIA de família (" + "; ".join(
            f"{bs}: {f.capitalize()}" for f, bs in familias.items()) + ")")

    nomes = [original] + [r["aceito"] for _, r in reconhecidas] + \
        [r["grafia_lista"] for _, r in reconhecidas if r.get("grafia_lista")]
    busca = []
    for n in nomes:
        if n and n.lower() not in {x.lower() for x in busca}:
            busca.append(n)
    # família: a da base que decidiu; se ela não tiver, a de outra base que
    # concorde com o nome aceito (Flora > WFO > GBIF)
    familia = res.get("familia") if str(res.get("familia") or "").strip() not in ("", "nan") else None
    if not familia:
        familia = next((r.get("familia") for _, r in sorted(reconhecidas, key=lambda br: ORDEM_BASE[br[0]])
                        if r.get("aceito", "").lower() == aceito.lower()
                        and str(r.get("familia") or "").strip() not in ("", "nan")), None)
    return {"aceito": aceito, "situacao": situacao, "observacoes": " | ".join(observacoes),
            "nomes_busca": busca, "base_decisao": NOME_BASE[base], "base": base,
            "familia": familia}


def assinatura_cfg() -> str:
    return hashlib.md5(json.dumps(CFG, sort_keys=True).encode()).hexdigest()[:8]


class ListaWCVP(ListaBaixada):
    """WCVP (Kew): wcvp_names.csv, separado por "|", com colunas próprias,
    convertidas aqui para os nomes Darwin Core usados pelas outras listas."""

    MAPA = {"plant_name_id": "taxonID", "accepted_plant_name_id": "acceptedNameUsageID",
            "taxon_name": "scientificName", "family": "family", "genus": "genus",
            "species": "specificEpithet", "infraspecies": "infraspecificEpithet",
            "infraspecific_rank": "verbatimTaxonRank", "taxon_status": "taxonomicStatus"}

    def _ler_bruto(self) -> pd.DataFrame:
        with zipfile.ZipFile(self.zip_path) as z:
            nome = next((n for n in z.namelist() if os.path.basename(n).lower() == "wcvp_names.csv"), None)
            if not nome:
                raise RuntimeError(f"wcvp_names.csv não encontrado em {self.zip_path}. Apague o "
                                   "arquivo e rode de novo para baixá-lo outra vez.")
            with z.open(nome) as f:
                df = pd.read_csv(f, sep="|", dtype=str, quoting=3, usecols=list(self.MAPA),
                                 encoding="utf-8", encoding_errors="replace", on_bad_lines="skip")
        df = df.rename(columns=self.MAPA)
        df["kingdom"] = "Plantae"
        return df


def listas_baixadas():
    listas = {}
    if CFG["usar_flora_brasil"]:
        listas["flora"] = ListaBaixada("flora", "Flora e Funga do Brasil",
                                       CFG["flora_brasil_url"] or URL_FLORA,
                                       os.path.join(_C.dados("flora_brasil"), "flora_brasil_dwca.zip"),
                                       ["taxon"])
    if CFG["usar_wfo"]:
        listas["wfo"] = ListaBaixada("wfo", "World Flora Online", CFG["wfo_url"] or URL_WFO,
                                     os.path.join(_C.dados("wfo"), "WFO_Backbone.zip"),
                                     ["classification", "taxon"])
    if CFG.get("usar_wcvp", True):
        listas["wcvp"] = ListaWCVP("wcvp", "WCVP (Kew)", CFG.get("wcvp_url") or URL_WCVP,
                                   os.path.join(_C.dados("wcvp"), "wcvp.zip"), [])
    return listas
