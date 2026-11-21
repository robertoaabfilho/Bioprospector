"""
normalizar_compostos.py  -  ETAPA "normalizacao" (v3.17)

O que esta etapa faz:
  - normaliza os identificadores de todos os compostos achados nas bases
    (COCONUT, NPASS, Dr. Duke, LOTUS, FooDB) pelo PubChem e os classifica
    estruturalmente pelo ClassyFire;
  - deduplica pelo InChIKey (identificador canônico), guardando TODAS as
    ocorrências de cada composto em cada base, e detecta e registra os
    conflitos entre as bases.

Entrada
  ocorrencias_compostos_bruto.csv   (etapa "bioativos"): um registro de cada
                                    base x planta, com o que a base informa
  (se faltar - rodada da v3.16 ou anterior - usa especies_com_compostos_bioativos.csv,
   com rastreabilidade reduzida)

Como o InChIKey canônico de cada ocorrência é escolhido
  1. InChIKey declarado pela base, se existe no PubChem;
  2. senão, o InChIKey calculado (RDKit) do SMILES da própria base, se existe
     no PubChem;
  3. senão, o declarado; 4. senão, o calculado. Sem nenhum: "sem estrutura"
     (fica nas ocorrências, fora da tabela de compostos).

Saídas
  normalizacao_ocorrencias.csv   cada registro de base x planta com o InChIKey
                                 canônico, o declarado, o calculado e o método
  normalizacao_mapa_inchikey.csv InChIKey de origem -> InChIKey canônico
  normalizacao_sinonimos.csv     sinônimos (PubChem + nomes nas bases)
  normalizacao_conflitos.csv     conflitos detectados entre as bases
  compostos_normalizados.csv     um composto por InChIKey (arquivo principal,
                                 gravado por último)

Caches: cache_pubchem_normalizacao.jsonl, cache_classyfire.jsonl
"""

import os

import caminhos as _C
import re
import sys
import time
from collections import Counter, defaultdict

import pandas as pd

import quimio as Q
from config_pipeline import carregar_config_banco, gravar_csv

ENTRADA = "ocorrencias_compostos_bruto.csv"
ENTRADA_ANTIGA = "especies_com_compostos_bioativos.csv"
CACHE_CID_PUBMED = _C.cache("cache_pubchem_cid.jsonl")        # gravado pela etapa "pubmed"
CACHE_PUBCHEM = _C.cache("cache_pubchem_normalizacao.jsonl")
CACHE_CLASSYFIRE = _C.cache("cache_classyfire.jsonl")

SAIDA_OCORRENCIAS = "normalizacao_ocorrencias.csv"
SAIDA_MAPA = "normalizacao_mapa_inchikey.csv"
SAIDA_SINONIMOS = "normalizacao_sinonimos.csv"
SAIDA_CONFLITOS = "normalizacao_conflitos.csv"
SAIDA = "compostos_normalizados.csv"

LOTE = 200
# ordem de preferência das bases para a estrutura e o nome de um composto
PRIORIDADE_BASE = ["NPASS", "COCONUT", "LOTUS", "FOODB", "DUKE"]

CFG = carregar_config_banco()


def prioridade(base) -> int:
    return PRIORIDADE_BASE.index(base) if base in PRIORIDADE_BASE else len(PRIORIDADE_BASE)


def cid_texto(v) -> str | None:
    m = re.search(r"(?<![\w.])(\d{1,10})(?:\.0+)?(?![\w.])", str(v or ""))
    return m.group(1) if m and int(m.group(1)) > 0 else None


def chave_nome(nome) -> str:
    """Nome de composto comparável: minúsculas, sem espaços, hífens e pontuação."""
    return re.sub(r"[^a-z0-9α-ω]", "", str(nome or "").lower())


def parece_nome_sistematico(nome) -> bool:
    n = str(nome or "")
    return len(n) > 45 or bool(re.search(r"\d+,\d+|\(\d*[RS]\)|\[\d", n))


# ---------------------------------------------------------------------------
# 1. Ocorrências
# ---------------------------------------------------------------------------
def ler_ocorrencias() -> pd.DataFrame:
    if os.path.exists(ENTRADA):
        df = pd.read_csv(ENTRADA, dtype=str, keep_default_na=False, na_values=[""])
        print(f"{len(df)} registro(s) de base x planta em {ENTRADA}")
        return df
    if not os.path.exists(ENTRADA_ANTIGA):
        sys.exit(f"{ENTRADA} não encontrado. Rode a etapa 'bioativos' primeiro.")
    print(f"AVISO: {ENTRADA} não existe (etapa 'bioativos' de versão anterior à 3.17). Usando "
          f"{ENTRADA_ANTIGA}, com rastreabilidade reduzida: rode a etapa 'bioativos' de novo "
          "para ter o registro de cada base.")
    ant = pd.read_csv(ENTRADA_ANTIGA, dtype=str)
    linhas = []
    for _, r in ant.iterrows():
        bases = [b.strip() for b in str(r.get("base") or "").split(";") if b.strip()]
        ids = [i.strip() for i in str(r.get("composto_id") or "").split(";") if i.strip()]
        for b in bases or ["?"]:
            id_b = next((i for i in ids if (b == "COCONUT" and i.startswith("CNP"))
                         or (b == "NPASS" and i.startswith("NPC"))
                         or i.upper().startswith(b + ":")), None)
            smi = r.get(f"smiles_{b.lower()}") if f"smiles_{b.lower()}" in ant.columns else None
            linhas.append({"base": b, "id_na_base": id_b, "nome_na_base": r.get("composto_nome"),
                           "inchikey_declarado": r.get("composto_inchikey"),
                           "smiles_na_base": smi if Q.texto(smi) else None,
                           "pubchem_cid_na_base": r.get("pubchem_cid"),
                           "organismo_na_base": r.get("especie_normalizada"),
                           "nome_cientifico": r.get("nome_cientifico"),
                           "familia": r.get("familia"), "reino": r.get("reino"),
                           **{c: r.get(c) for c in ant.columns if c in (
                               "atividade_ou_alvo", "parte_planta_duke", "teor_ppm_duke",
                               "atividades_duke", "referencias_lotus", "alimento_foodb",
                               "teor_foodb", "molecular_formula", "chemical_class",
                               "np_classifier_pathway", "np_classifier_superclass",
                               "np_classifier_class", "qed_drug_likeliness", "np_likeness")}})
    return pd.DataFrame(linhas)


def iks_para_enriquecer(df: pd.DataFrame) -> set | None:
    """InChIKeys que recebem o enriquecimento CARO por composto (sinônimos e
    ClassyFire pela API, e, na etapa "banco", vias e espectros): os que ocorrem
    em pelo menos uma planta da região.

    Com [bioativos] escopo = completo as bases químicas entram inteiras, e são
    centenas de milhares de compostos - um pedido por composto não termina em
    tempo útil. Os de fora da região ficam com o que vem de graça nos próprios
    arquivos (identificadores do PubChem em lote e a classificação do COCONUT).
    None = sem restrição."""
    if not CFG.get("enriquecer_apenas_regiao", True) or "na_regiao" not in df.columns:
        return None
    dentro = df["na_regiao"].fillna("").str.strip().str.lower() != "não"
    if dentro.all():
        return None
    iks = set(df.loc[dentro, "inchikey"].dropna())
    print(f"  [banco] enriquecer_apenas_regiao = true: sinônimos e ClassyFire só para os "
          f"{len(iks)} compostos da região\n  (dos {df['inchikey'].nunique()} do banco); "
          "os de fora ficam com o PubChem em lote e a classificação do COCONUT.")
    return iks


def analisar_estruturas(df: pd.DataFrame) -> pd.DataFrame:
    """InChIKey declarado válido e, com o RDKit, o calculado do SMILES da base."""
    df["inchikey_declarado_valido"] = df["inchikey_declarado"].map(Q.inchikey_valido)
    if not Q.TEM_RDKIT:
        print("  AVISO: RDKit não instalado - o InChIKey não é recalculado a partir do SMILES, "
              "e os conflitos de estrutura não são detectados. Instale: pip install rdkit")
    memo = {}
    for smi in df["smiles_na_base"].dropna().unique():
        memo[smi] = Q.estrutura(smi)
    est = df["smiles_na_base"].map(lambda s: memo.get(s, {}) if isinstance(s, str) else {})
    df["smiles_valido"] = est.map(lambda e: e.get("valido"))
    df["inchikey_calculado"] = est.map(lambda e: e.get("inchikey_calculado"))
    df["inchikey_parental"] = est.map(lambda e: e.get("inchikey_parental"))
    df["formula_calculada"] = est.map(lambda e: e.get("formula"))
    df["smiles_canonico_rdkit"] = est.map(lambda e: e.get("smiles_canonico"))
    n_smi = df["smiles_na_base"].notna().sum()
    n_inv = (df["smiles_valido"] == False).sum()  # noqa: E712
    print(f"  {n_smi} registro(s) com SMILES da base; {n_inv} inválido(s) para o RDKit")
    return df


# ---------------------------------------------------------------------------
# 2. PubChem
# ---------------------------------------------------------------------------
def cids_do_pubmed() -> dict:
    """{InChIKey: CID} já resolvidos pela etapa 'pubmed' (atalho)."""
    if not os.path.exists(CACHE_CID_PUBMED):
        return {}
    import json
    saida = {}
    with open(CACHE_CID_PUBMED, encoding="utf-8") as f:
        for linha in f:
            try:
                item = json.loads(linha)
                cid = cid_texto(item.get("cid"))
                ik = Q.inchikey_valido(item.get("inchikey"))
                if cid and ik:
                    saida[ik] = cid
            except (ValueError, AttributeError):
                continue
    return saida


def propriedades_em_lote(cli, cache, cids):
    faltam = [c for c in dict.fromkeys(cids) if f"cid|{c}" not in cache]
    if not faltam:
        return
    print(f"  PubChem: propriedades de {len(faltam)} CID(s), em lotes de {LOTE}")
    for i in range(0, len(faltam), LOTE):
        lote = faltam[i:i + LOTE]
        res = Q.pubchem_propriedades(cli, lote)
        if res is None:
            if cli.desistiu:
                return
            continue
        for c in lote:
            cache.gravar(f"cid|{c}", res.get(str(c), {}))
        if (i // LOTE) % 25 == 24:
            print(f"  ... {i + len(lote)}/{len(faltam)}")


def resolver_pubchem(df: pd.DataFrame, cache: Q.Cache) -> dict:
    """{InChIKey candidato: CID (str) ou ""}. "" = não está no PubChem;
    ausente do dicionário = não consultado (sem rede ou desligado)."""
    candidatos = sorted(set(df["inchikey_declarado_valido"].dropna())
                        | set(df["inchikey_calculado"].dropna()))
    resolvido = {}
    for ik in candidatos:
        v = cache.get(f"ik|{ik}")
        if v is not None:
            resolvido[ik] = str(v[0]) if v else ""
    if not CFG["pubchem"]:
        print("  [banco] pubchem = false: identificadores NÃO normalizados pelo PubChem "
              "(só o que já estiver em cache)")
        return resolvido
    cli = Q.Cliente("PubChem", intervalo=0.22)

    # a) CIDs que as bases (e a etapa pubmed) já trazem: lote, conferindo o InChIKey
    cids_base = set(df["pubchem_cid_na_base"].map(cid_texto).dropna())
    pubmed = cids_do_pubmed()
    cids_base |= {pubmed[ik] for ik in candidatos if ik in pubmed}
    propriedades_em_lote(cli, cache, sorted(cids_base, key=int))
    for c in cids_base:
        ik = Q.inchikey_valido((cache.get(f"cid|{c}") or {}).get("InChIKey"))
        if ik and ik in candidatos and ik not in resolvido:
            resolvido[ik] = c
            cache.gravar(f"ik|{ik}", [int(c)])

    # b) o restante, um a um pelo InChIKey
    faltam = [ik for ik in candidatos if ik not in resolvido]
    if faltam:
        print(f"  PubChem: {len(faltam)} InChIKey(s) consultados um a um "
              f"(≈ {max(1, round(len(faltam) * 0.3 / 60))} min na 1ª vez; depois, cache)")
    for n, ik in enumerate(faltam, 1):
        cids = Q.pubchem_cids_por_inchikey(cli, ik)
        if cids is None:
            if cli.desistiu:
                break
            continue
        cache.gravar(f"ik|{ik}", cids)
        resolvido[ik] = str(min(cids)) if cids else ""
        if n % 500 == 0:
            print(f"  ... {n}/{len(faltam)}")
    propriedades_em_lote(cli, cache, [c for c in resolvido.values() if c])
    n_pc = sum(1 for v in resolvido.values() if v)
    print(f"  PubChem: {n_pc} de {len(candidatos)} InChIKey(s) encontrados; "
          f"{sum(1 for v in resolvido.values() if v == '')} ausentes; "
          f"{len(candidatos) - len(resolvido)} não consultados (falha de rede: rode de novo)")
    return resolvido


def sinonimos_pubchem(cache: Q.Cache, cids: list) -> dict:
    if CFG["max_sinonimos"] <= 0:
        return {}
    faltam = [c for c in cids if f"sin|{c}" not in cache]
    if faltam and CFG["pubchem"]:
        cli = Q.Cliente("PubChem (sinônimos)", intervalo=0.22)
        print(f"  PubChem: sinônimos de {len(faltam)} CID(s)")
        for i in range(0, len(faltam), LOTE):
            lote = faltam[i:i + LOTE]
            res = Q.pubchem_sinonimos(cli, lote)
            if res is None:
                if cli.desistiu:
                    break
                continue
            for c in lote:
                cache.gravar(f"sin|{c}", (res.get(str(c)) or [])[:100])
    return {c: (cache.get(f"sin|{c}") or [])[:CFG["max_sinonimos"]] for c in cids}


# ---------------------------------------------------------------------------
# 3. Canônico
# ---------------------------------------------------------------------------
def escolher_canonico(df: pd.DataFrame, pubchem: dict) -> pd.DataFrame:
    consultado = bool(pubchem)

    def escolher(r):
        dec, calc = r["inchikey_declarado_valido"], r["inchikey_calculado"]
        dec = dec if isinstance(dec, str) else None
        calc = calc if isinstance(calc, str) else None

        # Quando o InChIKey declarado contradiz o SMILES da própria base
        # (blocos de conectividade diferentes), a ESTRUTURA manda: o SMILES é o
        # que é usado em todo o resto (ADMET, espectros, classificação). Assim o
        # ID fica coerente com a estrutura e não se herda a atividade do composto
        # errado. O conflito 'inchikey_declarado_x_smiles' registra o caso.
        if dec and calc and dec[:14] != calc[:14]:
            if pubchem.get(calc) or not consultado:
                return calc, ("calculado do SMILES da base (RDKit); o InChIKey declarado "
                              "contradiz a estrutura" + ("" if pubchem.get(calc)
                                                         else "; PubChem não consultado"))
            if pubchem.get(dec):
                # a estrutura não existe no PubChem, mas o declarado sim: mantém o
                # declarado, sinalizando que o SMILES da base diverge
                return dec, "declarado pela base; confirmado no PubChem (o SMILES da base diverge)"
            # nenhum dos dois confirmado e eles se contradizem: deixa para revisão
            return None, "sem InChIKey confiável (declarado contradiz o SMILES; nenhum no PubChem)"

        if dec and pubchem.get(dec):
            return dec, "declarado pela base; confirmado no PubChem"
        if calc and pubchem.get(calc):
            return calc, "calculado do SMILES da base (RDKit); confirmado no PubChem"
        sufixo = "ausente no PubChem" if consultado else "PubChem não consultado"
        if dec:
            return dec, f"declarado pela base; {sufixo}"
        if calc:
            return calc, f"calculado do SMILES da base (RDKit); {sufixo}"
        return None, "sem estrutura (nem InChIKey nem SMILES válido)"
    res = df.apply(escolher, axis=1, result_type="expand")
    df["inchikey"], df["metodo_identificacao"] = res[0], res[1]
    return df


# ---------------------------------------------------------------------------
# 4. ClassyFire
# ---------------------------------------------------------------------------
def classificar(iks_smiles: dict, coconut: dict, cache: Q.Cache,
                apenas: set | None = None) -> dict:
    """{InChIKey: {kingdom.., fonte}}. Modo [banco] classyfire:
    faltantes = consulta o ClassyFire só para os sem classificação do COCONUT;
    todos = consulta todos (e registra divergências com o COCONUT); nao = só COCONUT.
    `apenas` limita a CONSULTA À API a esses InChIKeys (ver iks_para_enriquecer);
    a classificação que vem do COCONUT continua valendo para todos."""
    modo = CFG["classyfire"]
    alvo = [ik for ik in iks_smiles
            if (apenas is None or ik in apenas)
            and (modo == "todos" or (modo == "faltantes" and ik not in coconut))]
    if modo == "nao":
        alvo = []
    novos = [ik for ik in alvo if ik not in cache]
    if novos:
        print(f"  ClassyFire: {len(novos)} InChIKey(s) a consultar (≈ "
              f"{max(1, round(len(novos) * 1.1 / 60))} min na 1ª vez; depois, cache)")
        cli = Q.Cliente("ClassyFire", intervalo=1.0, max_falhas=10, timeout=(10, 40))
        for n, ik in enumerate(novos, 1):
            res = Q.classyfire_por_inchikey(cli, ik)
            if res is None:
                if cli.desistiu:
                    break
                continue
            cache.gravar(ik, res)
            if n % 250 == 0:
                print(f"  ... {n}/{len(novos)}")
        if CFG["classyfire_submeter"] and not cli.desistiu:
            submeter_classyfire(cli, cache, {ik: iks_smiles[ik] for ik in alvo
                                             if cache.get(ik) == {} and iks_smiles.get(ik)})
    saida = {}
    for ik in iks_smiles:
        api = cache.get(ik) or {}
        if api.get("kingdom"):
            saida[ik] = {**api, "fonte": "ClassyFire (API)"}
        elif ik in coconut:
            saida[ik] = {**coconut[ik], "fonte": "COCONUT (ClassyFire)"}
    n_api = sum(1 for v in saida.values() if v["fonte"].startswith("ClassyFire"))
    print(f"  ClassyFire: {len(saida)} de {len(iks_smiles)} compostos classificados "
          f"({n_api} pela API, {len(saida) - n_api} pelo COCONUT)")
    return saida


def submeter_classyfire(cli, cache, pendentes: dict):
    """Envia ao ClassyFire as estruturas que ele ainda não classificou e espera
    até ~10 min. O que não terminar é recolhido na próxima rodada."""
    consultas = [k[2:] for k in cache.dados if k.startswith("q|") and cache.get(k)]
    novos = [ik for ik in pendentes if not any(ik in (cache.get(f"q|{q}") or []) for q in consultas)]
    for i in range(0, len(novos), 100):
        lote = novos[i:i + 100]
        qid = Q.classyfire_submeter(cli, [(ik, pendentes[ik]) for ik in lote])
        if qid:
            cache.gravar(f"q|{qid}", lote)
            consultas.append(str(qid))
        time.sleep(5)          # o ClassyFire limita o envio de consultas
    if not consultas:
        return
    print(f"  ClassyFire: {len(consultas)} consulta(s) enviada(s); aguardando resultados...")
    limite = time.time() + 600
    abertas = list(consultas)
    while abertas and time.time() < limite:
        for qid in list(abertas):
            feito, res = Q.classyfire_resultado(cli, qid)
            for ik, cls in res.items():
                cache.gravar(ik, cls)
            if feito:
                cache.gravar(f"q|{qid}", [])
                abertas.remove(qid)
        if abertas:
            time.sleep(30)
    if abertas:
        print(f"  ClassyFire: {len(abertas)} consulta(s) ainda em processamento - "
              "recolhidas na próxima rodada")


# ---------------------------------------------------------------------------
# 5. Conflitos
# ---------------------------------------------------------------------------
class Conflitos:
    def __init__(self):
        self.linhas = []
        self.n = 0

    def add(self, iks, tipo, severidade, campo, bases, valores, ocorrencias, resolucao):
        self.n += 1
        cid = f"CF{self.n:06d}"
        for ik in ([iks] if isinstance(iks, str) or iks is None else iks):
            self.linhas.append({
                "id_conflito": cid, "inchikey": ik, "tipo_conflito": tipo,
                "severidade": severidade, "campo": campo,
                "bases_envolvidas": "; ".join(sorted(set(b for b in bases if b))),
                "valores": valores, "ids_ocorrencias": "; ".join(ocorrencias[:50]),
                "resolucao": resolucao})


def mesma_conectividade(a, b) -> bool:
    return bool(a and b and a[:14] == b[:14])


def formula_normal(f) -> str:
    return re.sub(r"\s+", "", str(f or "")).rstrip("+-")


def detectar_conflitos(df: pd.DataFrame, props: dict, classes: dict,
                       coconut_cls: dict, cid_props: dict) -> Conflitos:
    cf = Conflitos()
    com_ik = df[df["inchikey"].notna()]

    # (1) InChIKey declarado x InChIKey do SMILES da mesma base
    dif = com_ik[com_ik["inchikey_declarado_valido"].notna() & com_ik["inchikey_calculado"].notna()
                 & (com_ik["inchikey_declarado_valido"] != com_ik["inchikey_calculado"])]
    for (ik, base, dec, calc), g in dif.groupby(["inchikey", "base", "inchikey_declarado_valido",
                                                 "inchikey_calculado"]):
        alta = not mesma_conectividade(dec, calc)
        cf.add(ik, "inchikey_declarado_x_smiles", "alta" if alta else "média", "inchikey", [base],
               f"declarado {dec} | do SMILES {calc}", g["id_ocorrencia"].tolist(),
               f"adotado {ik} ({g['metodo_identificacao'].iloc[0]})"
               + ("" if alta else "; diferença só de estereoquímica/protonação"))

    # (2) SMILES inválido
    inv = df[df["smiles_valido"] == False]  # noqa: E712
    for (base, smi), g in inv.groupby(["base", "smiles_na_base"]):
        cf.add(g["inchikey"].dropna().unique().tolist() or [None], "smiles_invalido", "média",
               "smiles", [base], str(smi)[:300], g["id_ocorrencia"].tolist(),
               "SMILES desta base ignorado; estrutura de outra fonte")

    # (3) estruturas diferentes entre bases para o mesmo InChIKey canônico
    for ik, g in com_ik[com_ik["inchikey_calculado"].notna()].groupby("inchikey"):
        por_calc = g.groupby("inchikey_calculado")["base"].agg(lambda b: "/".join(sorted(set(b))))
        if len(por_calc) > 1:
            calcs = list(por_calc.index)
            alta = len({c[:14] for c in calcs}) > 1
            cf.add(ik, "estrutura_entre_bases", "alta" if alta else "média", "smiles",
                   g["base"].tolist(), " | ".join(f"{b}: {c}" for c, b in por_calc.items()),
                   g["id_ocorrencia"].tolist(),
                   f"mantido {ik}; conferir à mão as estruturas"
                   + ("" if alta else " (diferem só na estereoquímica)"))

    # (4) fórmula da base (COCONUT) x PubChem
    if "molecular_formula" in com_ik.columns:
        for ik, g in com_ik[com_ik["molecular_formula"].notna()].groupby("inchikey"):
            f_pc = formula_normal((props.get(ik) or {}).get("MolecularFormula"))
            if not f_pc:
                continue
            for (base, f), gg in g.groupby(["base", "molecular_formula"]):
                if formula_normal(f) != f_pc:
                    cf.add(ik, "formula_entre_bases", "média", "formula", [base, "PubChem"],
                           f"{base}: {f} | PubChem: {f_pc}", gg["id_ocorrencia"].tolist(),
                           "adotada a fórmula do PubChem")

    # (5) CID da base aponta para outro composto
    for (ik, base, cid), g in com_ik.assign(_cid=com_ik["pubchem_cid_na_base"].map(cid_texto)) \
            .dropna(subset=["_cid"]).groupby(["inchikey", "base", "_cid"]):
        cid_canon = (props.get(ik) or {}).get("CID")
        if not cid_canon or str(cid_canon) == cid:
            continue
        ik_do_cid = Q.inchikey_valido((cid_props.get(cid) or {}).get("InChIKey"))
        alta = bool(ik_do_cid) and not mesma_conectividade(ik_do_cid, ik)
        cf.add(ik, "cid_entre_bases", "alta" if alta else "média", "pubchem_cid", [base, "PubChem"],
               f"{base}: CID {cid}" + (f" ({ik_do_cid})" if ik_do_cid else "")
               + f" | PubChem pelo InChIKey: CID {cid_canon}", g["id_ocorrencia"].tolist(),
               f"adotado o CID {cid_canon} (o do InChIKey canônico)")

    # (6) classificação ClassyFire: COCONUT x API
    for ik, c in classes.items():
        coco = coconut_cls.get(ik)
        if not coco or not c.get("fonte", "").startswith("ClassyFire"):
            continue
        for nivel in ("superclass", "class"):
            a, b = coco.get(nivel), c.get(nivel)
            if a and b and a.strip().lower() != b.strip().lower():
                cf.add(ik, "classificacao_classyfire", "baixa", f"classyfire_{nivel}",
                       ["COCONUT", "ClassyFire"], f"COCONUT: {a} | ClassyFire: {b}", [],
                       "adotada a classificação da API do ClassyFire (versão mais recente da ChemOnt)")
                break

    # (7) mesmo identificador da base -> estruturas diferentes
    ids = com_ik.dropna(subset=["id_na_base"])
    for (base, idb), g in ids.groupby(["base", "id_na_base"]):
        iks = sorted(set(g["inchikey"]))
        if len(iks) > 1:
            cf.add(iks, "id_x_estrutura", "alta", "id_na_base", [base],
                   f"{base} {idb}: " + " | ".join(iks), g["id_ocorrencia"].tolist(),
                   "cada InChIKey mantido como composto próprio; conferir o registro na base")

    # (8) mesmo nome -> conectividades diferentes em bases diferentes
    nomes = com_ik.dropna(subset=["nome_na_base"])
    nomes = nomes[~nomes["nome_na_base"].map(parece_nome_sistematico)]
    nomes = nomes.assign(_n=nomes["nome_na_base"].map(chave_nome))
    nomes = nomes[nomes["_n"].str.len() >= 4]
    for _, g in nomes.groupby("_n"):
        conect = g.groupby(g["inchikey"].str[:14])
        if conect.ngroups > 1 and g["base"].nunique() > 1:
            iks = sorted(set(g["inchikey"]))
            valores = " | ".join(f"{'/'.join(sorted(set(gg['base'])))}: {k}"
                                 for k, gg in g.groupby("inchikey"))
            cf.add(iks, "nome_x_estrutura", "média", "nome", g["base"].tolist(),
                   f"'{g['nome_na_base'].iloc[0]}' -> {valores}", g["id_ocorrencia"].tolist(),
                   "compostos mantidos separados (InChIKeys diferentes); o nome é ambíguo")

    # (9) variantes de estereoquímica (mesma conectividade, InChIKeys diferentes)
    iks_unicos = pd.Series(sorted(set(com_ik["inchikey"])))
    for bloco, g in iks_unicos.groupby(iks_unicos.str[:14]):
        if len(g) > 1:
            cf.add(g.tolist(), "variantes_estereo", "informativa", "inchikey", [],
                   " | ".join(g), [],
                   "mantidos separados (estereoisômeros ou formas de protonação); "
                   "podem ser o mesmo composto com estereoquímica incompleta numa das bases")

    # (10) sal / forma carregada
    sal = com_ik[com_ik["inchikey_parental"].notna()
                 & (com_ik["inchikey_parental"] != com_ik["inchikey_calculado"])]
    for (ik, par), g in sal.groupby(["inchikey", "inchikey_parental"]):
        cf.add(ik, "sal_ou_forma_carregada", "informativa", "inchikey", g["base"].tolist(),
               f"{ik} -> forma parental {par}", g["id_ocorrencia"].tolist(),
               "mantida a forma registrada; a parental fica em compostos.inchikey_parental")
    return cf


# ---------------------------------------------------------------------------
# 6. Tabela de compostos
# ---------------------------------------------------------------------------
NP_COLS = ["np_classifier_pathway", "np_classifier_superclass", "np_classifier_class"]


def coconut_classyfire(df: pd.DataFrame) -> dict:
    """{InChIKey: {kingdom.., direct_parent}} da classificação do COCONUT."""
    mapa = {"superclass": "chemical_super_class", "class": "chemical_class",
            "subclass": "chemical_sub_class", "direct_parent": "direct_parent_classification"}
    if not any(c in df.columns for c in mapa.values()):
        return {}
    coco = df[(df["base"] == "COCONUT") & df["inchikey"].notna()]
    saida = {}
    for ik, g in coco.groupby("inchikey"):
        reg = {nivel: next((v for v in g[c].dropna() if Q.texto(v)), None) if c in g else None
               for nivel, c in mapa.items()}
        if any(reg.values()):
            reg["kingdom"] = "Organic compounds" if reg.get("superclass") else None
            saida[ik] = reg
    return saida


def montar_compostos(df, props, classes, sinonimos, conflitos: Conflitos) -> pd.DataFrame:
    com = df[df["inchikey"].notna()].copy()
    com["_p"] = com["base"].map(prioridade)
    com = com.sort_values("_p")
    n_conf = Counter(l["inchikey"] for l in conflitos.linhas if l["inchikey"])
    tipos_conf = defaultdict(set)
    for l in conflitos.linhas:
        if l["inchikey"]:
            tipos_conf[l["inchikey"]].add(l["tipo_conflito"])
    linhas = []
    for ik, g in com.groupby("inchikey", sort=True):
        p = props.get(ik) or {}
        validos = g[g["smiles_valido"] != False]  # noqa: E712
        smi_base = next((s for s in validos["smiles_na_base"] if Q.texto(s)), None)
        base_smi = validos.loc[validos["smiles_na_base"].notna(), "base"].iloc[0] \
            if smi_base else None
        smiles = p.get("SMILES") or smi_base
        nomes_base = [n for n in g["nome_na_base"].dropna() if Q.texto(n)]
        comuns = [n for n in nomes_base if not parece_nome_sistematico(n)]
        nome = p.get("Title") or (Counter(comuns).most_common(1)[0][0] if comuns else
                                  (nomes_base[0] if nomes_base else None))
        est = Q.estrutura(smiles) if smiles else {}
        cls = classes.get(ik) or {}
        ids = "; ".join(f"{b}: {', '.join(sorted(set(gg['id_na_base'].dropna())))}"
                        for b, gg in g.groupby("base") if gg["id_na_base"].notna().any())
        status_pc = ("confirmado" if p else
                     "ausente no PubChem" if "ausente" in g["metodo_identificacao"].iloc[0]
                     else "PubChem não consultado")
        linha = {
            "inchikey": ik,
            "inchikey_conectividade": ik[:14],
            "nome_preferido": nome,
            "nome_iupac": p.get("IUPACName"),
            "pubchem_cid": p.get("CID"),
            "status_pubchem": status_pc,
            "inchi": p.get("InChI"),
            "smiles_isomerico": smiles,
            "smiles_canonico": est.get("smiles_canonico"),
            "smiles_conectividade": p.get("ConnectivitySMILES"),
            "fonte_estrutura": "PubChem" if p.get("SMILES") else base_smi,
            "formula_molecular": p.get("MolecularFormula") or est.get("formula"),
            "massa_molecular": p.get("MolecularWeight"),
            "massa_exata": p.get("ExactMass") or p.get("MonoisotopicMass"),
            "carga": p.get("Charge"),
            "xlogp_pubchem": p.get("XLogP"),
            "tpsa_pubchem": p.get("TPSA"),
            "complexidade_pubchem": p.get("Complexity"),
            "inchikey_parental": est.get("inchikey_parental"),
            "forma_parental_diferente": (bool(est.get("inchikey_parental"))
                                         and est.get("inchikey_parental") != ik) if est else None,
            **{f"classyfire_{n}": cls.get(n) for n in Q.NIVEIS_CLASSYFIRE},
            "classyfire_framework": cls.get("molecular_framework"),
            "classyfire_fonte": cls.get("fonte"),
            **{c: next((v for v in g[c].dropna() if Q.texto(v)), None) if c in g else None
               for c in NP_COLS},
            "bases": "; ".join(sorted(set(g["base"]))),
            "n_bases": g["base"].nunique(),
            "ids_nas_bases": ids or None,
            "n_ocorrencias": len(g),
            "n_plantas": g["nome_cientifico"].nunique(),
            "n_sinonimos": len(sinonimos.get(ik, [])),
            "n_conflitos": n_conf.get(ik, 0),
            "tipos_conflito": "; ".join(sorted(tipos_conf.get(ik, []))) or None,
        }
        linhas.append(linha)
    return pd.DataFrame(linhas)


def main():
    df = ler_ocorrencias()
    if df.empty:
        gravar_csv(pd.DataFrame(columns=["inchikey"]), SAIDA)
        print("Nenhum registro de composto: nada a normalizar.")
        return
    df.insert(0, "id_ocorrencia", [f"OC{i:07d}" for i in range(1, len(df) + 1)])

    print("\n1. Estruturas (RDKit)")
    df = analisar_estruturas(df)

    print("\n2. Identificadores no PubChem")
    cache = Q.Cache(CACHE_PUBCHEM)
    pubchem = resolver_pubchem(df, cache)
    df = escolher_canonico(df, pubchem)

    cid_props = {k[4:]: v for k, v in cache.dados.items() if k.startswith("cid|")}
    props = {}
    for ik in df["inchikey"].dropna().unique():
        cid = pubchem.get(ik)
        if cid and cid_props.get(cid):
            props[ik] = cid_props[cid]
    print(f"  {df['inchikey'].nunique()} InChIKey(s) canônicos para {len(df)} registros; "
          f"{df['inchikey'].isna().sum()} registro(s) sem estrutura")

    print("\n3. Sinônimos")
    enriquecer = iks_para_enriquecer(df)
    cids_canon = sorted({str(p["CID"]) for ik, p in props.items() if p.get("CID")
                         and (enriquecer is None or ik in enriquecer)}, key=int)
    sin_cid = sinonimos_pubchem(cache, cids_canon)
    cache.fechar()
    sinonimos = defaultdict(list)
    linhas_sin = []
    for ik, p in props.items():
        for s in sin_cid.get(str(p.get("CID")), []):
            linhas_sin.append({"inchikey": ik, "sinonimo": s, "fonte": "PubChem",
                               "tipo": "sinônimo"})
            sinonimos[ik].append(s)
        if p.get("IUPACName"):
            linhas_sin.append({"inchikey": ik, "sinonimo": p["IUPACName"], "fonte": "PubChem",
                               "tipo": "nome IUPAC"})
    for (ik, base, nome), _ in df.dropna(subset=["inchikey", "nome_na_base"]) \
            .groupby(["inchikey", "base", "nome_na_base"]):
        linhas_sin.append({"inchikey": ik, "sinonimo": nome, "fonte": base, "tipo": "nome na base"})
        sinonimos[ik].append(nome)
    tab_sin = pd.DataFrame(linhas_sin, columns=["inchikey", "sinonimo", "fonte", "tipo"])
    tab_sin = tab_sin.assign(_k=tab_sin["sinonimo"].str.lower()) \
        .drop_duplicates(["inchikey", "_k", "fonte"]).drop(columns="_k")

    print("\n4. Classificação estrutural (ClassyFire)")
    iks_smiles = {}
    for ik, g in df.dropna(subset=["inchikey"]).groupby("inchikey"):
        iks_smiles[ik] = (props.get(ik) or {}).get("SMILES") or next(
            (s for s in g["smiles_na_base"].dropna() if Q.texto(s)), None)
    coconut_cls = coconut_classyfire(df)
    cache_cf = Q.Cache(CACHE_CLASSYFIRE)
    classes = classificar(iks_smiles, coconut_cls, cache_cf, apenas=enriquecer)
    cache_cf.fechar()

    print("\n5. Deduplicação e conflitos")
    conflitos = detectar_conflitos(df, props, classes, coconut_cls, cid_props)
    tab_conf = pd.DataFrame(conflitos.linhas, columns=[
        "id_conflito", "inchikey", "tipo_conflito", "severidade", "campo", "bases_envolvidas",
        "valores", "ids_ocorrencias", "resolucao"])
    if not tab_conf.empty:
        resumo = tab_conf.drop_duplicates("id_conflito").groupby(["tipo_conflito", "severidade"]).size()
        print("  Conflitos registrados (por tipo e severidade):")
        print("    " + resumo.to_string().replace("\n", "\n    "))
    compostos = montar_compostos(df, props, classes, sinonimos, conflitos)

    mapa = pd.concat([
        df.dropna(subset=["inchikey_declarado_valido", "inchikey"])
          .assign(origem="declarado pela base")
          .rename(columns={"inchikey_declarado_valido": "inchikey_origem"}),
        df.dropna(subset=["inchikey_calculado", "inchikey"])
          .assign(origem="calculado do SMILES da base")
          .rename(columns={"inchikey_calculado": "inchikey_origem"}),
    ])[["inchikey_origem", "inchikey", "origem", "base"]]
    mapa = (mapa.groupby(["inchikey_origem", "inchikey", "origem"])
            .agg(bases=("base", lambda b: "; ".join(sorted(set(b)))),
                 n_ocorrencias=("base", "size")).reset_index()
            .rename(columns={"inchikey": "inchikey_canonico"}))
    mapa["mudou"] = mapa["inchikey_origem"] != mapa["inchikey_canonico"]

    gravar_csv(df, SAIDA_OCORRENCIAS)
    gravar_csv(mapa, SAIDA_MAPA)
    gravar_csv(tab_sin, SAIDA_SINONIMOS)
    gravar_csv(tab_conf, SAIDA_CONFLITOS)
    gravar_csv(compostos, SAIDA)        # por último: marca a etapa como concluída

    n_multi = (compostos["n_bases"] > 1).sum() if not compostos.empty else 0
    print(f"\nConcluído: {len(compostos)} compostos únicos (InChIKey) a partir de {len(df)} registros")
    print(f"  {n_multi} composto(s) em 2+ bases; {(compostos['status_pubchem'] == 'confirmado').sum()} "
          "confirmados no PubChem")
    if not compostos.empty:
        print(f"  {compostos['classyfire_superclass'].notna().sum()} com superclasse ClassyFire")
    print(f"  {tab_conf['id_conflito'].nunique()} conflito(s) em {SAIDA_CONFLITOS}; "
          f"{int(mapa['mudou'].sum())} InChIKey(s) de origem trocados pelo canônico")


if __name__ == "__main__":
    main()
