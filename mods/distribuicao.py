"""
distribuicao.py

Módulo compartilhado: distribuição das plantas por ESTADO BRASILEIRO, a
partir da Flora e Funga do Brasil (o mesmo arquivo baixado para a conferência
taxonômica, dados/flora_brasil/flora_brasil_dwca.zip; nada é consultado na
internet).

Para cada linha de plantas.csv procura, nesta ordem, o nome da linha, o
nome aceito e os outros nomes de nomes_busca (sinônimos), e usa o primeiro
que a Flora reconhece:
  - nome aceito na Flora -> a distribuição dele (somando variedades e
    subespécies da mesma espécie);
  - sinônimo na Flora    -> a distribuição do nome aceito correspondente
    (sinônimo que aponta para mais de uma espécie é ignorado: ambíguo);
  - linha de gênero      -> a união das espécies do gênero.
Sem nada na Flora: "distribuição desconhecida".

Colunas acrescentadas a plantas.csv:
  estados_br          siglas das UFs, em ordem alfabética ("AM; PA; RR")
  dominios_br         domínios fitogeográficos (Amazônia, Cerrado...)
  endemismo_br        "endêmica do Brasil" / "não endêmica"
  origem_br           "nativa", "exótica" (cultivada/naturalizada)
  fonte_distribuicao  de onde veio (e por qual nome, se não foi o da linha)
  registros_gbif_por_uf  só quando o estado veio do GBIF: registros por UF
                         (ex.: "AM 12; PA 3"), para pesar a confiança

2ª camada, só para as plantas que ficaram sem estado na Flora: o GBIF
(especies_gbif_estados.csv, da etapa "gbif"): estados com registros
georreferenciados da espécie no Brasil, pela speciesKey ou pelo nome.
"""

import json
import os

import caminhos as _C
import re
import zipfile

import pandas as pd

ARQUIVO_FLORA = os.path.join(_C.dados("flora_brasil"), "flora_brasil_dwca.zip")
DESCONHECIDA = "distribuição desconhecida"
# plantas de fora da região (escopo "completo" da etapa bioativos): a
# distribuição por estado só é levantada para a região do input.txt
FORA_DA_REGIAO = "fora da região"
COLUNAS = ["estados_br", "dominios_br", "endemismo_br", "origem_br", "fonte_distribuicao",
           "registros_gbif_por_uf"]
ARQUIVO_GBIF = "especies_gbif_estados.csv"
FONTE_GBIF = "GBIF (registros georreferenciados no Brasil)"
FONTE = "Flora e Funga do Brasil"


def _ler(z: zipfile.ZipFile, prefixo: str, colunas: list) -> pd.DataFrame:
    nome = next((n for n in z.namelist() if os.path.basename(n).lower().startswith(prefixo)), None)
    if not nome:
        raise FileNotFoundError(f"{prefixo}.txt não encontrado em {ARQUIVO_FLORA}")
    with z.open(nome) as f:
        cab = pd.read_csv(f, sep="\t", nrows=0, quoting=3).columns
    usar = [c for c in colunas if c in cab]
    with z.open(nome) as f:
        return pd.read_csv(f, sep="\t", dtype=str, quoting=3, usecols=usar,
                           encoding="utf-8", encoding_errors="replace")


def _binomio(genero, epiteto) -> str:
    g = str(genero or "").strip().lower()
    e = str(epiteto or "").strip().lower().lstrip("×").strip()     # híbrido: "×limon"
    return f"{g} {e}" if g and e and g != "nan" and e != "nan" else ""


def chave_nome(nome) -> str:
    """'Citrus × limon L.' -> 'citrus limon'; 'Copaifera' -> 'copaifera'."""
    if not isinstance(nome, str):
        return ""
    partes = [p for p in re.sub(r"[×]", " ", nome).replace(" x ", " ").split() if p]
    if not partes:
        return ""
    if len(partes) == 1 or not partes[1][:1].islower():
        return partes[0].lower()
    return f"{partes[0].lower()} {partes[1].lower()}"


class Distribuicao:
    def __init__(self, caminho: str = ARQUIVO_FLORA):
        with zipfile.ZipFile(caminho) as z:
            tx = _ler(z, "taxon", ["id", "acceptedNameUsageID", "kingdom", "genus",
                                   "specificEpithet", "taxonRank", "taxonomicStatus"])
            di = _ler(z, "distribution", ["id", "locationID", "establishmentMeans",
                                          "occurrenceRemarks"])
        tx = tx[tx["kingdom"].fillna("Plantae") == "Plantae"].copy()
        tx["_b"] = [_binomio(g, e) for g, e in zip(tx["genus"], tx["specificEpithet"])]

        # distribuição de cada táxon aceito
        di["uf"] = di["locationID"].fillna("").str.extract(r"BR-([A-Z]{2})")[0]
        self.por_id = {}
        for tid, g in di.groupby("id"):
            dominios, endem = set(), set()
            for obs in g["occurrenceRemarks"].dropna():
                try:
                    o = json.loads(obs)
                except ValueError:
                    continue
                dominios.update(o.get("phytogeographicDomain") or [])
                if o.get("endemism"):
                    endem.add(o["endemism"])
            self.por_id[tid] = {"ufs": set(g["uf"].dropna()), "dominios": dominios,
                                "endemismo": endem,
                                "origem": set(g["establishmentMeans"].dropna())}

        aceitos = tx[tx["taxonomicStatus"] == "NOME_ACEITO"]
        rank = aceitos["taxonRank"].fillna("")
        # espécie aceita -> ids dela e das variedades/subespécies aceitas
        infra = aceitos[rank.isin(["ESPECIE", "VARIEDADE", "SUB_ESPECIE", "FORMA"]) & aceitos["_b"].ne("")]
        self.ids_aceito = infra.groupby("_b")["id"].apply(list).to_dict()
        especies = aceitos[rank.eq("ESPECIE") & aceitos["_b"].ne("")]
        self.ids_genero = (especies.assign(_g=especies["genus"].str.lower())
                           .groupby("_g")["id"].apply(list).to_dict())
        # sinônimo -> espécie(s) aceita(s): só vale se for uma espécie só
        sin = tx[(tx["taxonomicStatus"] == "SINONIMO") & tx["_b"].ne("")
                 & tx["acceptedNameUsageID"].notna()]
        b_aceito = dict(zip(aceitos["id"], aceitos["_b"]))
        destino = sin.assign(_d=sin["acceptedNameUsageID"].map(b_aceito)).dropna(subset=["_d"])
        destinos = destino.groupby("_b")["_d"].apply(lambda s: sorted(set(s)))
        self.sinonimo = {b: d[0] for b, d in destinos.items() if len(d) == 1}

    def _juntar(self, ids) -> dict | None:
        regs = [self.por_id[i] for i in ids if i in self.por_id]
        if not regs:
            return None
        ufs = set().union(*(r["ufs"] for r in regs))
        # a Flora às vezes só diz "Brasil", sem os estados: os estados ficam
        # desconhecidos, mas domínio, endemismo e origem continuam valendo
        endem = set().union(*(r["endemismo"] for r in regs))
        origem = set().union(*(r["origem"] for r in regs))
        return {
            "estados_br": "; ".join(sorted(ufs)) if ufs else DESCONHECIDA,
            "dominios_br": "; ".join(sorted(set().union(*(r["dominios"] for r in regs)))) or None,
            "endemismo_br": ("endêmica do Brasil" if endem == {"Endemica"} else
                             "não endêmica" if "Não endemica" in endem else None),
            "origem_br": "; ".join(sorted({"nativa" if o == "Nativa" else "exótica"
                                           for o in origem})) or None,
        }

    def de_nome(self, nome) -> tuple[dict | None, str]:
        """(distribuição, como foi achada) para um nome."""
        k = chave_nome(nome)
        if not k:
            return None, ""
        if " " not in k:
            return self._juntar(self.ids_genero.get(k, [])), "gênero: união das espécies"
        if k in self.ids_aceito:
            return self._juntar(self.ids_aceito[k]), ""
        if k in self.sinonimo:
            return self._juntar(self.ids_aceito.get(self.sinonimo[k], [])), "sinônimo"
        return None, ""

    def da_linha(self, linha) -> dict:
        nome = linha.get("nome_cientifico")
        candidatos = [nome, linha.get("nome_aceito")]
        candidatos += [n.strip() for n in str(linha.get("nomes_busca") or "").split(";")]
        vistos, sem_estado = set(), None
        for c in candidatos:
            k = chave_nome(c)
            if not k or k in vistos:
                continue
            vistos.add(k)
            dist, como = self.de_nome(c)
            if dist and dist["estados_br"] == DESCONHECIDA:
                # a Flora conhece o nome, mas sem estados: guarda e tenta os outros nomes
                sem_estado = sem_estado or {**dist, "fonte_distribuicao":
                                            f"{FONTE} (sem estado informado)"}
                continue
            if dist:
                if k == chave_nome(nome) and not como:
                    fonte = FONTE
                elif como == "gênero: união das espécies":
                    fonte = f"{FONTE} ({como})"
                else:
                    fonte = f"{FONTE}, pelo nome {c.strip()}"
                return {**dist, "fonte_distribuicao": fonte}
        return sem_estado or {"estados_br": DESCONHECIDA, "dominios_br": None, "endemismo_br": None,
                              "origem_br": None, "fonte_distribuicao": None}


class EstadosGBIF:
    """Estados com registros da espécie no GBIF (especies_gbif_estados.csv)."""

    def __init__(self, caminho: str = ARQUIVO_GBIF):
        df = pd.read_csv(caminho, dtype=str)
        df["n"] = pd.to_numeric(df["n_registros"], errors="coerce").fillna(0).astype(int)
        df = df[df["n"] > 0]

        def resumo(g):
            g = g.sort_values("uf")
            return ("; ".join(g["uf"]), "; ".join(f"{u} {n}" for u, n in zip(g["uf"], g["n"])))
        self.por_chave = {k: resumo(g) for k, g in df.groupby("speciesKey")}
        df["_k"] = df["especie"].map(chave_nome)
        self.por_nome = {k: resumo(g.groupby("uf", as_index=False)["n"].sum())
                         for k, g in df[df["_k"].ne("")].groupby("_k")}

    def da_linha(self, linha) -> tuple | None:
        k = str(linha.get("speciesKey") or "").strip()
        if k and k in self.por_chave:
            return (*self.por_chave[k], "")
        nome = linha.get("nome_cientifico")
        candidatos = [nome, linha.get("nome_aceito")]
        candidatos += [n.strip() for n in str(linha.get("nomes_busca") or "").split(";")]
        for c in candidatos:
            ck = chave_nome(c)
            if " " in ck and ck in self.por_nome:
                return (*self.por_nome[ck], "" if ck == chave_nome(nome) else c.strip())
        return None


def anexar(plantas: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta as colunas de distribuição a plantas.csv."""
    registros = plantas.to_dict("records")
    vazio = {"estados_br": DESCONHECIDA, "dominios_br": None, "endemismo_br": None,
             "origem_br": None, "fonte_distribuicao": None}
    if os.path.exists(ARQUIVO_FLORA):
        print("Distribuição por estado (Flora e Funga do Brasil)...")
        d = Distribuicao()
        linhas = [d.da_linha(r) for r in registros]
    else:
        print(f"AVISO: {ARQUIVO_FLORA} não encontrado - distribuição sem a Flora e Funga do "
              "Brasil (ligue usar_flora_brasil em [taxonomia] para baixá-la).")
        linhas = [dict(vazio) for _ in registros]
    n_flora = sum(x["estados_br"] != DESCONHECIDA for x in linhas)
    # 2ª camada: GBIF, só para quem ficou sem estado
    n_gbif = 0
    if os.path.exists(ARQUIVO_GBIF):
        g = EstadosGBIF()
        for x, r in zip(linhas, registros):
            if x["estados_br"] != DESCONHECIDA:
                continue
            achado = g.da_linha(r)
            if achado:
                ufs, por_uf, via = achado
                x["estados_br"], x["registros_gbif_por_uf"] = ufs, por_uf
                x["fonte_distribuicao"] = FONTE_GBIF + (f", pelo nome {via}" if via else "")
                n_gbif += 1
    else:
        print(f"  ({ARQUIVO_GBIF} não encontrado: só a Flora. Para acrescentar os estados do "
              "GBIF, rode a etapa 'gbif'.)")
    for c in COLUNAS:
        plantas[c] = [x.get(c) for x in linhas]
    conhecida = plantas["estados_br"] != DESCONHECIDA
    print(f"  {int(conhecida.sum())} de {len(plantas)} plantas com estado(s): {n_flora} pela Flora"
          + (f", {n_gbif} pelo GBIF" if n_gbif else "")
          + f"; {int((~conhecida).sum())} com '{DESCONHECIDA}'")
    return plantas


def juntar_estados(valores) -> str:
    """União dos estados de várias plantas (ex.: as que têm um composto).
    "fora da região" não é estado: entra na união apenas como ausência."""
    ufs = set()
    for v in valores:
        if isinstance(v, str) and v and v not in (DESCONHECIDA, FORA_DA_REGIAO):
            ufs.update(p.strip() for p in v.split(";") if p.strip())
    return "; ".join(sorted(ufs)) if ufs else DESCONHECIDA
