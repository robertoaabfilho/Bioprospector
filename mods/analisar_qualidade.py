"""
analisar_qualidade.py  -  ETAPA "qualidade" (v3.20)

Análise de qualidade e cobertura do banco:
  - completude de campos, no total e por base de origem;
  - distribuição do espaço químico (ClassyFire e NPClassifier) e projeção
    UMAP dos fingerprints Morgan, para ver a diversidade estrutural;
  - cobertura taxonômica dos organismos produtores;
  - sobreposição entre as bases (exclusivos e compartilhados, índice de Jaccard);
  - sinais de viés de curadoria (concentração por base/família/classe, lacunas
    sistemáticas de estrutura, bioatividade e distribuição).

Entrada: a pasta banco/ (etapa "banco").
Saída:   banco/qualidade/  - um CSV por análise e RELATORIO_QUALIDADE.md.
         (não depende de rede; só lê os CSVs já gravados)
"""

import os
import sys

import pandas as pd

import esquema_banco as E
from config_pipeline import carregar_config_banco, gravar_csv

CFG = carregar_config_banco()
# esta etapa grava dentro de banco/, então segue o mesmo idioma dele
E.IDIOMA = CFG.get("idioma_banco", "en")

BANCO = "banco"
PASTA = os.path.join(BANCO, "qualidade")


PLANTAS = "plantas.csv"   # universo de espécies-alvo (etapa 'plantas'), na raiz


def gravar(df, arquivo: str) -> None:
    """Grava uma tabela de banco/qualidade/ com o nome do arquivo e os
    cabeçalhos no idioma do banco ([banco] idioma_banco)."""
    gravar_csv(E.traduzir_qualidade(df), os.path.join(PASTA, E.nome_qualidade(arquivo)))


def ler(nome) -> pd.DataFrame:
    """Lê uma tabela de banco/ por qualquer um dos dois nomes (o banco sai em
    inglês por padrão) e devolve as colunas em português, que é como esta etapa
    trabalha."""
    for arquivo in dict.fromkeys([f"{E.TABELAS_EN.get(nome, nome)}.csv", f"{nome}.csv"]):
        caminho = os.path.join(BANCO, arquivo)
        if os.path.exists(caminho):
            df = pd.read_csv(caminho, dtype=str, keep_default_na=False, na_values=[""])
            return E.destraduzir(df, nome)
    return pd.DataFrame()


def cobertura_vs_universo(organismos: pd.DataFrame) -> dict:
    """Fração das espécies-alvo (plantas.csv) com ao menos um composto no banco,
    no total e por família. Dá o denominador que faltava: quantas das plantas
    levantadas têm química conhecida."""
    if not os.path.exists(PLANTAS):
        return {}
    plantas = pd.read_csv(PLANTAS, dtype=str, keep_default_na=False, na_values=[""])
    if plantas.empty or "nome_cientifico" not in plantas.columns:
        return {}
    com_comp = set(organismos["nome_cientifico"].dropna()) if not organismos.empty else set()
    plantas = plantas.drop_duplicates("nome_cientifico")
    plantas["_tem"] = plantas["nome_cientifico"].isin(com_comp)
    universo, com = len(plantas), int(plantas["_tem"].sum())
    resumo = pd.DataFrame([{"especies_alvo": universo, "com_composto": com,
                            "cobertura_pct": pct(com, universo),
                            "sem_composto": universo - com}])
    saida = {"cobertura_universo_resumo": resumo}
    if "familia" in plantas.columns:
        g = plantas.groupby("familia").agg(
            especies_alvo=("nome_cientifico", "nunique"),
            com_composto=("_tem", "sum")).reset_index()
        g["cobertura_pct"] = g.apply(lambda r: pct(r["com_composto"], r["especies_alvo"]), axis=1)
        g = g.sort_values("especies_alvo", ascending=False)
        saida["cobertura_universo_por_familia"] = g
    return saida


def pct(a, b) -> float:
    return round(100 * a / b, 1) if b else 0.0


# ---------------------------------------------------------------------------
# 1. completude de campos
# ---------------------------------------------------------------------------
def completude(tabelas: dict) -> pd.DataFrame:
    linhas = []
    for nome, df in tabelas.items():
        if df.empty:
            continue
        for col in df.columns:
            preenchidos = df[col].notna().sum()
            linhas.append({"tabela": nome, "coluna": col, "n_linhas": len(df),
                           "preenchidos": int(preenchidos),
                           "completude_pct": pct(preenchidos, len(df))})
    return pd.DataFrame(linhas)


def completude_por_base(compostos: pd.DataFrame, fontes: pd.DataFrame) -> pd.DataFrame:
    """Completude do que CADA BASE realmente fornece, medida nas colunas da
    tabela de fontes (o registro de cada base), não no composto já consolidado.
    Assim, p.ex., o Dr. Duke, que não traz SMILES, aparece com 0% de SMILES."""
    if fontes.empty:
        return pd.DataFrame()
    # campos vindos da própria base (não os enriquecidos pelo pipeline)
    campos = [("nome_na_base", "nome"), ("inchikey_declarado", "InChIKey declarado"),
              ("smiles_na_base", "SMILES"), ("pubchem_cid_na_base", "CID"),
              ("organismo_na_base", "organismo"), ("atividade_na_base", "atividade/alvo"),
              ("parte_planta", "parte da planta"), ("teor", "teor"),
              ("referencia", "referência")]
    campos = [(c, E.rotulo_campo(r)) for c, r in campos if c in fontes.columns]
    linhas = []
    for base, g in fontes.groupby("base"):
        linha = {"base": base, "n_registros": len(g),
                 "n_compostos": g["inchikey"].nunique() if "inchikey" in g else 0}
        for c, rot in campos:
            linha[f"{rot}_pct"] = pct(g[c].notna().sum(), len(g))
        # quanto a base dá de estrutura utilizável (SMILES que o RDKit leu)
        if "smiles_valido" in g.columns:
            val = g["smiles_valido"].astype(str).str.lower().isin(["true", "1", "sim"])
            linha[f"{E.rotulo_campo('SMILES válido')}_pct"] = pct(val.sum(), len(g))
        linhas.append(linha)
    total = {"base": "TODAS", "n_registros": len(fontes),
             "n_compostos": fontes["inchikey"].nunique() if "inchikey" in fontes else 0}
    for c, rot in campos:
        total[f"{rot}_pct"] = pct(fontes[c].notna().sum(), len(fontes))
    return pd.DataFrame(linhas + [total])


# ---------------------------------------------------------------------------
# 2. espaço químico
# ---------------------------------------------------------------------------
def espaco_quimico(compostos: pd.DataFrame) -> dict:
    saida = {}
    for col, rotulo in [("classyfire_superclass", "classyfire_superclasse"),
                        ("classyfire_class", "classyfire_classe"),
                        ("np_classifier_pathway", "npclassifier_via"),
                        ("np_classifier_superclass", "npclassifier_superclasse")]:
        if col in compostos.columns and compostos[col].notna().any():
            cont = compostos[col].value_counts(dropna=True)
            df = cont.rename_axis(rotulo).reset_index(name="n_compostos")
            df["pct"] = df["n_compostos"].map(lambda x: pct(x, len(compostos)))
            saida[rotulo] = df
    return saida


def projecao_umap(compostos: pd.DataFrame):
    """Projeção UMAP dos fingerprints Morgan (raio 2, 2048 bits), para
    visualizar a diversidade estrutural do banco: cada ponto é um composto, e
    a distância entre eles aproxima a dissimilaridade de Tanimoto.

    Devolve (DataFrame com as coordenadas, mensagem). O DataFrame é vazio
    quando a projeção não pôde ser feita, e a mensagem diz por quê - a etapa
    nunca falha por causa disto.

    [banco] umap = false desliga. [banco] umap_max limita quantos compostos
    entram (amostra aleatória com semente fixa): a projeção é O(n log n) mas
    cara, e acima de algumas dezenas de milhares de compostos ela passa a
    dominar o tempo da etapa.
    """
    vazio = pd.DataFrame()
    if not CFG.get("umap", True):
        return vazio, "desligada em [banco] umap"
    col = next((c for c in ("smiles_canonico", "smiles_isomerico")
                if c in compostos.columns), None)
    if col is None:
        return vazio, "o banco não tem coluna de SMILES"
    com = compostos.dropna(subset=[col])
    if len(com) < 5:
        return vazio, f"poucos compostos com SMILES ({len(com)}; mínimo 5)"
    try:
        import numpy as np
        from rdkit import Chem, RDLogger
        from rdkit.Chem import rdFingerprintGenerator
    except Exception as e:
        return vazio, f"RDKit indisponível ({e})"
    try:
        import warnings
        with warnings.catch_warnings():
            # avisos esperados das escolhas feitas aqui: a métrica de Jaccard não
            # tem inverse_transform (não usamos), e a semente fixa desliga o
            # paralelismo (queremos a figura reproduzível)
            warnings.filterwarnings("ignore", category=UserWarning, module="umap")
            import umap
    except Exception:
        return vazio, ("umap-learn não instalado - instale com "
                       "'pip install umap-learn' (opcional)")

    limite = int(CFG.get("umap_max", 50000) or 0)
    if limite and len(com) > limite:
        com = com.sample(limite, random_state=42)
        print(f"  UMAP: amostra de {limite} compostos (de {len(compostos)}; "
              "[banco] umap_max)")

    RDLogger.DisableLog("rdApp.*")
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    fps, iks = [], []
    for ik, smi in zip(com["inchikey"], com[col]):
        m = Chem.MolFromSmiles(smi)
        if m is None:
            continue
        fps.append(np.frombuffer(gen.GetFingerprintAsNumPy(m).tobytes(), dtype=np.uint8))
        iks.append(ik)
    RDLogger.EnableLog("rdApp.*")
    if len(fps) < 5:
        return vazio, f"poucos SMILES válidos ({len(fps)}; mínimo 5)"

    # métrica de Jaccard = 1 - Tanimoto, que é a distância usual entre
    # fingerprints binários. random_state fixo torna a figura reproduzível
    # (ao custo de rodar em um só núcleo).
    print(f"  UMAP: projetando {len(fps)} fingerprints Morgan (pode levar "
          "alguns minutos)")
    try:
        import warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning)
            red = umap.UMAP(n_neighbors=min(15, len(fps) - 1), min_dist=0.1,
                            metric="jaccard", random_state=42, n_components=2)
            xy = red.fit_transform(np.vstack(fps))
    except Exception as e:
        return vazio, f"a projeção falhou ({e})"

    saida = pd.DataFrame({"inchikey": iks, "umap_x": xy[:, 0], "umap_y": xy[:, 1]})
    extras = [c for c in ("classyfire_superclass", "classyfire_class",
                          "np_classifier_pathway", "nome_preferido") if c in com.columns]
    if extras:
        saida = saida.merge(com[["inchikey"] + extras].drop_duplicates("inchikey"),
                            on="inchikey", how="left")
    return saida, f"{len(saida)} compostos projetados"


# ---------------------------------------------------------------------------
# 3. cobertura taxonômica
# ---------------------------------------------------------------------------
def cobertura_taxonomica(organismos: pd.DataFrame, origem: pd.DataFrame) -> dict:
    saida = {}
    if organismos.empty:
        return saida
    for col, rotulo in [("familia", "familia"), ("ordem", "ordem"),
                        ("classe", "classe"), ("reino", "reino")]:
        if col in organismos.columns and organismos[col].notna().any():
            g = organismos.groupby(col).agg(
                n_organismos=("nome_cientifico", "nunique")).reset_index()
            if not origem.empty and "inchikey" in origem.columns:
                mapa_tax = organismos.set_index("nome_cientifico")[col]
                comp_por = origem[["nome_cientifico", "inchikey"]].copy()
                comp_por["_tax"] = comp_por["nome_cientifico"].map(mapa_tax)
                n_comp = comp_por.groupby("_tax")["inchikey"].nunique()
                g["n_compostos"] = g[col].map(n_comp).fillna(0).astype(int)
            g = g.sort_values("n_organismos", ascending=False)
            saida[f"taxonomia_{rotulo}"] = g
    # resumo
    resumo = pd.DataFrame([{
        "organismos_com_composto": len(organismos),
        "familias": organismos["familia"].nunique() if "familia" in organismos else 0,
        "ordens": organismos["ordem"].nunique() if "ordem" in organismos else 0,
        "com_distribuicao_conhecida": (organismos["estados_br"].notna().sum()
                                       if "estados_br" in organismos else 0),
        "nativas_br": (organismos["origem_br"].astype(str).str.contains("nativa", case=False).sum()
                       if "origem_br" in organismos else 0),
        "endemicas_br": (organismos["endemismo_br"].astype(str).str.contains("endêmica", case=False,
                         na=False).sum() if "endemismo_br" in organismos else 0)}])
    saida["taxonomia_resumo"] = resumo
    return saida


# ---------------------------------------------------------------------------
# 4. sobreposição entre bases
# ---------------------------------------------------------------------------
def sobreposicao(fontes: pd.DataFrame) -> dict:
    if fontes.empty or "inchikey" not in fontes.columns:
        return {}
    f = fontes.dropna(subset=["inchikey"])
    por_base = {b: set(g["inchikey"]) for b, g in f.groupby("base")}
    bases = sorted(por_base)

    # exclusivos x compartilhados
    conta = f.groupby("inchikey")["base"].nunique()
    linhas = []
    for b in bases:
        iks = por_base[b]
        exclusivos = sum(1 for ik in iks if conta.get(ik, 0) == 1)
        linhas.append({"base": b, "compostos": len(iks), "exclusivos": exclusivos,
                       "exclusivos_pct": pct(exclusivos, len(iks)),
                       "compartilhados": len(iks) - exclusivos})
    resumo = pd.DataFrame(linhas)

    # matriz de Jaccard entre pares de bases
    mat = []
    for a in bases:
        linha = {"base": a}
        for c in bases:
            inter = len(por_base[a] & por_base[c])
            uniao = len(por_base[a] | por_base[c])
            linha[c] = round(inter / uniao, 3) if uniao else 0.0
        mat.append(linha)
    matriz = pd.DataFrame(mat)

    # distribuição do nº de bases por composto
    dist = conta.value_counts().sort_index().rename_axis("n_bases").reset_index(name="n_compostos")
    return {"sobreposicao_bases": resumo, "sobreposicao_jaccard": matriz,
            "compostos_por_n_bases": dist}


# ---------------------------------------------------------------------------
# 5b. viés de curadoria: teste inferencial (base x classe química)
# ---------------------------------------------------------------------------
def vieses_inferencial(compostos: pd.DataFrame, fontes: pd.DataFrame) -> dict:
    """Testa se a distribuição de classes químicas (ClassyFire superclasse)
    depende da base — ou seja, se cada base está enviesada para certos tipos de
    composto. Qui-quadrado de independência (base x superclasse) e resíduos
    padronizados de Pearson, que apontam as classes super/sub-representadas em
    cada base. Precisa de scipy para o p-valor; sem ele, dá só a tabela e os
    resíduos."""
    if compostos.empty or fontes.empty or "classyfire_superclass" not in compostos.columns:
        return {}
    classe = compostos.set_index("inchikey")["classyfire_superclass"].dropna()
    if classe.empty:
        return {}
    f = fontes.dropna(subset=["inchikey"])[["inchikey", "base"]].drop_duplicates()
    f = f[f["inchikey"].isin(classe.index)]
    f["superclasse"] = f["inchikey"].map(classe)
    if f.empty:
        return {}
    cont = pd.crosstab(f["base"], f["superclasse"])
    # agrupa classes raras (col total < 5) em "outras" para o teste ficar válido
    raras = cont.columns[cont.sum(axis=0) < 5]
    if len(raras):
        cont["(outras)"] = cont[raras].sum(axis=1)
        cont = cont.drop(columns=raras)
    if cont.shape[0] < 2 or cont.shape[1] < 2:
        return {}
    total = cont.values.sum()
    esp = pd.DataFrame(
        (cont.sum(axis=1).values[:, None] * cont.sum(axis=0).values[None, :]) / total,
        index=cont.index, columns=cont.columns)
    residuos = (cont - esp) / esp.pow(0.5)
    saida = {"vies_base_classe_contingencia": cont.reset_index(),
             "vies_base_classe_residuos": residuos.round(2).reset_index()}
    try:
        from scipy.stats import chi2_contingency
        chi2, p, dof, _ = chi2_contingency(cont.values)
        n = cont.values.sum()
        v_cramer = (chi2 / (n * (min(cont.shape) - 1))) ** 0.5
        saida["vies_base_classe_teste"] = pd.DataFrame([{
            "teste": "qui-quadrado de independência (base × superclasse ClassyFire)",
            "chi2": round(chi2, 2), "graus_liberdade": dof,
            "p_valor": f"{p:.2e}", "V_de_Cramer": round(v_cramer, 3),
            "interpretacao": ("distribuição de classes difere entre as bases (há viés)"
                              if p < 0.05 else "sem diferença significativa entre as bases"),
            "nota": "resíduos > 2 ou < -2 em vies_base_classe_residuos apontam as classes "
                    "super/sub-representadas em cada base"}])
    except Exception:
        saida["vies_base_classe_teste"] = pd.DataFrame([{
            "teste": "qui-quadrado (base × superclasse)",
            "nota": "instale scipy para o p-valor; os resíduos de Pearson já estão calculados"}])
    return saida


# ---------------------------------------------------------------------------
# 5. vieses de curadoria
# ---------------------------------------------------------------------------
def vieses(compostos, fontes, organismos, origem, bioat) -> pd.DataFrame:
    alertas = []

    def add(dim, descricao, metrica, valor):
        alertas.append({"dimensao": dim, "observacao": descricao,
                        "metrica": metrica, "valor": valor})

    n = len(compostos)
    # concentração por base
    if not fontes.empty:
        base_cont = fontes.dropna(subset=["inchikey"]).groupby("base")["inchikey"].nunique()
        if not base_cont.empty:
            dom = base_cont.idxmax()
            add("fonte", f"base que mais contribui: {dom}", "fração dos compostos",
                f"{pct(base_cont.max(), n)}%")
            so_uma = (fontes.dropna(subset=['inchikey']).groupby('inchikey')['base'].nunique() == 1).sum()
            add("fonte", "compostos registrados em uma única base", "fração",
                f"{pct(so_uma, n)}%")

    # lacunas de estrutura / identificadores
    for col, rotulo in [("smiles_isomerico", "sem SMILES"),
                        ("pubchem_cid", "sem PubChem CID"),
                        ("classyfire_superclass", "sem classe ClassyFire")]:
        if col in compostos.columns:
            falta = compostos[col].isna().sum()
            add("completude", f"compostos {rotulo}", "fração", f"{pct(falta, n)}%")

    # concentração do espaço químico
    if "classyfire_superclass" in compostos.columns and compostos["classyfire_superclass"].notna().any():
        top = compostos["classyfire_superclass"].value_counts(normalize=True)
        add("espaço químico", f"superclasse ClassyFire mais frequente: {top.index[0]}",
            "fração dos classificados", f"{round(100 * top.iloc[0], 1)}%")

    # concentração taxonômica
    if not organismos.empty and "familia" in organismos.columns and organismos["familia"].notna().any():
        topf = organismos["familia"].value_counts(normalize=True)
        add("taxonomia", f"família com mais organismos: {topf.index[0]}",
            "fração dos organismos", f"{round(100 * topf.iloc[0], 1)}%")
    if not origem.empty:
        por_org = origem.groupby("nome_cientifico")["inchikey"].nunique()
        if not por_org.empty:
            add("taxonomia", f"organismo com mais compostos: {por_org.idxmax()}",
                "compostos", str(int(por_org.max())))

    # lacuna de bioatividade e de distribuição
    if not bioat.empty:
        com_bio = bioat["inchikey"].nunique()
        add("bioatividade", "compostos sem nenhum registro de bioatividade", "fração",
            f"{pct(n - com_bio, n)}%")
        quant = bioat[bioat["natureza"] == "quantitativa"]["inchikey"].nunique()
        add("bioatividade", "compostos com bioatividade quantitativa", "fração",
            f"{pct(quant, n)}%")
    else:
        add("bioatividade", "nenhum registro de bioatividade no banco", "fração", "100% sem")
    if not organismos.empty and "estados_br" in organismos.columns:
        sem_dist = organismos["estados_br"].isna().sum()
        add("distribuição", "organismos sem distribuição por UF conhecida", "fração",
            f"{pct(sem_dist, len(organismos))}%")

    return pd.DataFrame(alertas)


# ---------------------------------------------------------------------------
# 6. gráficos da etapa de qualidade
# ---------------------------------------------------------------------------
def gerar_graficos(comp_base, espaco, sobrep, cobertura, taxon, umap_df=None) -> list:
    """PNGs da qualidade em banco/qualidade/. Devolve [(titulo, arquivo)].
    Degrada sem erro se o matplotlib não estiver instalado."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        print("  AVISO: matplotlib não instalado - gráficos da qualidade pulados.")
        return []
    feitos = []
    AZUL = "#2f6fb3"
    # paleta de Okabe-Ito: distinguível por quem tem daltonismo
    PALETA = ["#0072b2", "#d55e00", "#009e73", "#cc79a7",
              "#e69f00", "#56b4e9", "#f0e442", "#000000"]

    def salvar(fig, nome, titulo):
        nome = E.nome_qualidade(nome)
        cam = os.path.join(PASTA, nome)
        fig.tight_layout()
        fig.savefig(cam, dpi=130, bbox_inches="tight")
        plt.close(fig)
        feitos.append((titulo, nome))

    # (a) mapa de calor de completude por base
    if comp_base is not None and not comp_base.empty:
        m = comp_base[comp_base["base"] != "TODAS"].set_index("base")
        cols = [c for c in m.columns if c.endswith("_pct")]
        if cols and len(m):
            dados = m[cols].astype(float)
            fig, ax = plt.subplots(figsize=(1.1 * len(cols) + 2, 0.5 * len(m) + 1.5))
            im = ax.imshow(dados.values, cmap="YlGnBu", vmin=0, vmax=100, aspect="auto")
            ax.set_xticks(range(len(cols)))
            ax.set_xticklabels([c[:-4] for c in cols], rotation=40, ha="right", fontsize=8)
            ax.set_yticks(range(len(m))); ax.set_yticklabels(m.index, fontsize=9)
            for i in range(len(m)):
                for j in range(len(cols)):
                    ax.text(j, i, f"{dados.values[i, j]:.0f}", ha="center", va="center",
                            fontsize=7, color="black" if dados.values[i, j] < 60 else "white")
            fig.colorbar(im, ax=ax, label="% preenchido")
            ax.set_title("Completude do que cada base fornece", fontsize=11, weight="bold")
            salvar(fig, "g_completude_por_base.png", "Completude por base")

    # (a2) projeção UMAP dos fingerprints Morgan
    if umap_df is not None and not umap_df.empty:
        cor_col = next((c for c in ("classyfire_superclass", "np_classifier_pathway")
                        if c in umap_df.columns and umap_df[c].notna().any()), None)
        fig, ax = plt.subplots(figsize=(7.5, 6.5))
        if cor_col:
            top = umap_df[cor_col].value_counts().head(len(PALETA) - 1).index.tolist()
            grupos = [(g, umap_df[umap_df[cor_col] == g]) for g in top]
            resto = umap_df[~umap_df[cor_col].isin(top)]
            if not resto.empty:
                grupos.append(("outras / sem classificação", resto))
            for i, (rotulo, g) in enumerate(grupos):
                ax.scatter(g["umap_x"], g["umap_y"], s=6, alpha=0.6, linewidths=0,
                           color=PALETA[i % len(PALETA)],
                           label=f"{rotulo[:38]} ({len(g)})")
            ax.legend(fontsize=7, markerscale=2.2, loc="best", framealpha=0.9)
        else:
            ax.scatter(umap_df["umap_x"], umap_df["umap_y"], s=6, alpha=0.6,
                       linewidths=0, color=AZUL)
        ax.set_xlabel("UMAP 1", fontsize=9)
        ax.set_ylabel("UMAP 2", fontsize=9)
        ax.set_title(f"Espaço químico: projeção UMAP de {len(umap_df)} compostos\n"
                     "(fingerprints Morgan raio 2, 2048 bits; distância de Jaccard)",
                     fontsize=11, weight="bold")
        ax.tick_params(labelsize=8)
        salvar(fig, "g_espaco_quimico_umap.png", "Espaço químico (UMAP)")

    # (b) espaço químico (superclasse ClassyFire, top 15)
    chave = next((k for k in espaco if "superclasse" in k and "classyfire" in k), None) \
        or next(iter(espaco), None)
    if chave:
        d = espaco[chave].head(15).iloc[::-1]
        rot = d.columns[0]
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(d[rot].astype(str), d["n_compostos"].astype(int), color=AZUL)
        ax.set_xlabel("compostos"); ax.set_title(f"Espaço químico: {chave} (top 15)",
                                                 fontsize=11, weight="bold")
        salvar(fig, "g_espaco_quimico.png", "Espaço químico")

    # (c) sobreposição: exclusivos x compartilhados por base
    if "sobreposicao_bases" in sobrep and not sobrep["sobreposicao_bases"].empty:
        d = sobrep["sobreposicao_bases"]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.bar(d["base"], d["exclusivos"].astype(int), color=AZUL, label="exclusivos")
        ax.bar(d["base"], d["compartilhados"].astype(int),
               bottom=d["exclusivos"].astype(int), color="#9ecae1", label="compartilhados")
        ax.set_ylabel("compostos"); ax.legend()
        ax.set_title("Compostos exclusivos × compartilhados por base", fontsize=11, weight="bold")
        salvar(fig, "g_sobreposicao_bases.png", "Sobreposição entre bases")

    # (d) cobertura taxonômica vs universo (top 15 famílias por nº de espécies-alvo)
    if "cobertura_universo_por_familia" in cobertura:
        d = cobertura["cobertura_universo_por_familia"].head(15).iloc[::-1]
        fig, ax = plt.subplots(figsize=(8, 5.5))
        ax.barh(d["familia"].astype(str), d["cobertura_pct"].astype(float), color=AZUL)
        ax.set_xlabel("% das espécies-alvo com ≥1 composto"); ax.set_xlim(0, 100)
        ax.set_title("Cobertura química por família (top 15 famílias)", fontsize=11, weight="bold")
        salvar(fig, "g_cobertura_familias.png", "Cobertura por família")

    if feitos:
        print(f"  {len(feitos)} gráfico(s) gerado(s) em banco/qualidade/")
    return feitos


# ---------------------------------------------------------------------------
# relatório
# ---------------------------------------------------------------------------
def relatorio_md(contagens, comp_base, espaco, taxon, sobrep, viesc,
                 cobertura=None, vies_inf=None, graficos=None, umap=None) -> str:
    cobertura = cobertura or {}
    vies_inf = vies_inf or {}
    out = ["# Relatório de qualidade e cobertura do banco", "",
           "Análise automática das tabelas de `banco/` (etapa `qualidade`). "
           "As tabelas completas estão nos CSVs desta pasta.", "",
           "## Tamanho das tabelas", "", "| Tabela | Linhas |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in contagens.items()]

    if graficos:
        out += ["", "## Gráficos", ""]
        out += [f"![{t}]({a})" for t, a in graficos]

    if "cobertura_universo_resumo" in cobertura:
        out += ["", "## Cobertura química das espécies-alvo", "",
                "Fração das plantas levantadas (`plantas.csv`) com ao menos um composto "
                "no banco — o denominador que diz quanto do universo tem química conhecida.", "",
                tabela_md(cobertura["cobertura_universo_resumo"])]
        if "cobertura_universo_por_familia" in cobertura:
            out += ["", "### Por família (top 20 por nº de espécies-alvo)", "",
                    tabela_md(cobertura["cobertura_universo_por_familia"].head(20))]

    if "vies_base_classe_teste" in vies_inf:
        out += ["", "## Viés de curadoria: teste inferencial", "",
                "Teste de independência entre a **base** e a **superclasse química** "
                "(ClassyFire): se a distribuição de classes difere entre as bases, há viés "
                "de cobertura química.", "", tabela_md(vies_inf["vies_base_classe_teste"])]
        if "vies_base_classe_residuos" in vies_inf:
            out += ["", "Resíduos de Pearson (valores > 2 = classe super-representada na base; "
                    "< −2 = sub-representada):", "",
                    tabela_md(vies_inf["vies_base_classe_residuos"])]

    if not viesc.empty:
        out += ["", "## Sinais de viés de curadoria (descritivo)", "",
                "| Dimensão | Observação | Métrica | Valor |", "|---|---|---|---|"]
        out += [f"| {r['dimensao']} | {r['observacao']} | {r['metrica']} | {r['valor']} |"
                for _, r in viesc.iterrows()]

    if comp_base is not None and not comp_base.empty:
        out += ["", "## Completude por base (campos da identidade química)", "",
                "Percentual de compostos de cada base com o campo preenchido.", ""]
        out += [tabela_md(comp_base)]

    if "sobreposicao_bases" in sobrep:
        out += ["", "## Sobreposição entre as bases", "",
                "Compostos exclusivos de cada base e compartilhados com outras.", "",
                tabela_md(sobrep["sobreposicao_bases"]), "",
                "Índice de Jaccard entre pares de bases (interseção / união de InChIKeys):", "",
                tabela_md(sobrep["sobreposicao_jaccard"])]

    for rotulo, df in espaco.items():
        out += ["", f"## Espaço químico: {rotulo} (top 15)", "",
                tabela_md(df.head(15))]

    umap_df, umap_msg = umap if umap else (None, None)
    if umap_df is not None:
        out += ["", "## Espaço químico: projeção UMAP", ""]
        if umap_df.empty:
            out += [f"Projeção não feita: {umap_msg}.", "",
                    "A projeção UMAP dos fingerprints Morgan precisa do RDKit e do "
                    "pacote `umap-learn` (`pip install umap-learn`), e é ligada em "
                    "`[banco] umap`."]
        else:
            cor = next((c for c in ("classyfire_superclass", "np_classifier_pathway")
                        if c in umap_df.columns and umap_df[c].notna().any()), None)
            csv_umap = E.nome_qualidade("espaco_quimico_umap.csv")
            png_umap = E.nome_qualidade("g_espaco_quimico_umap.png")
            out += [f"{len(umap_df)} compostos projetados em 2 dimensões a partir dos "
                    "fingerprints Morgan (raio 2, 2048 bits), com distância de Jaccard "
                    f"(= 1 − Tanimoto). Coordenadas em `{csv_umap}`; "
                    f"figura em `{png_umap}`.", "",
                    "Como ler: **proximidade** aproxima semelhança estrutural, e grupos "
                    "separados indicam famílias químicas distintas. As **distâncias "
                    "absolutas e a orientação dos eixos não têm significado** — o UMAP "
                    "preserva vizinhança, não escala. A figura é reproduzível "
                    "(semente fixa)."]
            if cor:
                n_grupos = umap_df[cor].nunique()
                out += ["", f"Pontos coloridos por `{cor}` ({n_grupos} valor(es) "
                        "distinto(s) no conjunto projetado)."]

    if "taxonomia_resumo" in taxon:
        out += ["", "## Cobertura taxonômica", "", tabela_md(taxon["taxonomia_resumo"])]
        if "taxonomia_familia" in taxon:
            out += ["", "### Famílias com mais organismos (top 15)", "",
                    tabela_md(taxon["taxonomia_familia"].head(15))]
    return "\n".join(out) + "\n"


def tabela_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    linhas = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        linhas.append("| " + " | ".join("" if pd.isna(r[c]) else str(r[c]) for c in cols) + " |")
    return "\n".join(linhas)


def main():
    if not os.path.isdir(BANCO):
        sys.exit(f"Pasta {BANCO}/ não encontrada. Rode a etapa 'banco' primeiro.")
    nomes = list(E.TABELAS)
    tabelas = {n: ler(n) for n in nomes}
    compostos = tabelas["compostos"]
    os.makedirs(PASTA, exist_ok=True)
    if compostos.empty:
        # banco vazio: grava um relatório mínimo e o marcador, sem falhar a etapa
        gravar(completude(tabelas), "completude_campos.csv")
        with open(os.path.join(PASTA, E.nome_meta("RELATORIO_QUALIDADE.md")), "w",
                  encoding="utf-8") as f:
            f.write("# Relatório de qualidade\n\nO banco não tem compostos: nada a analisar.\n")
        print("Banco vazio: nada a analisar.")
        return
    fontes = tabelas["fontes"]
    organismos = tabelas["organismos"]
    origem = tabelas["origem_biologica"]
    bioat = tabelas["bioatividade"]
    print(f"Analisando banco/ ({len(compostos)} compostos, {len(fontes)} registros de fonte)")

    os.makedirs(PASTA, exist_ok=True)
    contagens = {n: len(df) for n, df in tabelas.items()}

    print("1. Completude de campos")
    comp_geral = completude(tabelas)
    comp_base = completude_por_base(compostos, fontes)

    print("2. Espaço químico")
    espaco = espaco_quimico(compostos)
    umap_df, umap_msg = projecao_umap(compostos)
    print(f"  UMAP: {umap_msg}")

    print("3. Cobertura taxonômica")
    taxon = cobertura_taxonomica(organismos, origem)
    cobertura = cobertura_vs_universo(organismos)   # denominador: plantas.csv

    print("4. Sobreposição entre bases")
    sobrep = sobreposicao(fontes)

    print("5. Vieses de curadoria (descritivo + inferencial)")
    viesc = vieses(compostos, fontes, organismos, origem, bioat)
    vies_inf = vieses_inferencial(compostos, fontes)

    print("6. Gráficos da qualidade")
    graficos = gerar_graficos(comp_base, espaco, sobrep, cobertura, taxon, umap_df)

    gravar(comp_geral, "completude_campos.csv")
    if comp_base is not None and not comp_base.empty:
        gravar(comp_base, "completude_por_base.csv")
    for rotulo, df in espaco.items():
        gravar(df, f"espaco_quimico_{rotulo}.csv")
    if not umap_df.empty:
        gravar(umap_df, "espaco_quimico_umap.csv")
    for rotulo, df in list(taxon.items()) + list(cobertura.items()):
        gravar(df, f"{rotulo}.csv")
    for rotulo, df in sobrep.items():
        gravar(df, f"{rotulo}.csv")
    gravar(viesc, "vieses_curadoria.csv")
    for rotulo, df in vies_inf.items():
        gravar(df, f"{rotulo}.csv")

    with open(os.path.join(PASTA, E.nome_meta("RELATORIO_QUALIDADE.md")), "w",
              encoding="utf-8") as f:
        f.write(relatorio_md(contagens, comp_base, espaco, taxon, sobrep, viesc,
                             cobertura, vies_inf, graficos, (umap_df, umap_msg)))

    extras = (len(espaco) + len(taxon) + len(cobertura) + len(sobrep) + len(vies_inf)
              + 3 + (0 if umap_df.empty else 1))
    print(f"\nConcluído: banco/qualidade/ com {extras} planilha(s), "
          f"{len(graficos)} gráfico(s) e {E.nome_meta('RELATORIO_QUALIDADE.md')}")
    if not viesc.empty:
        print("  Sinais de viés (resumo):")
        for _, r in viesc.iterrows():
            print(f"    [{r['dimensao']}] {r['observacao']}: {r['valor']}")


if __name__ == "__main__":
    main()
