"""
diagnostico_pubmed.py  -  resumo do andamento da etapa "pubmed"

Lê os caches (cache_*.jsonl) e as saídas das etapas anteriores e grava um
resumo curto em diagnostico_pubmed.txt (alguns KB), para mandar no lugar
dos arquivos de cache, que podem ter centenas de MB.

Não consulta a internet nem altera nada. Uso (na pasta do pipeline):
    python mods/diagnostico_pubmed.py
"""

import datetime
import json
import os
import sys
from collections import Counter
from pathlib import Path

# resultados ficam em resultados/ e caches em cache/ (caminhos.py)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import caminhos as _C  # noqa: E402
os.chdir(_C.RESULTADOS)

SAIDA = "diagnostico_pubmed.txt"
CACHES = ["cache_pubchem.jsonl", "cache_pubchem_cid.jsonl", "cache_pubchem_vinculos.jsonl",
          "cache_pubmed_filtro.jsonl", "cache_pubmed_buscas.jsonl", "cache_pubmed_artigos.jsonl",
          "cache_llm_classificacao.jsonl", "cache_openalex.jsonl", "cache_pubchem_duke.jsonl"]

linhas_saida = []


def p(texto=""):
    print(texto)
    linhas_saida.append(str(texto))


def ler(caminho):
    if caminho.startswith("cache_"):
        caminho = _C.cache(caminho)
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            try:
                yield json.loads(linha)
            except ValueError:
                continue


def quando(caminho):
    t = os.path.getmtime(caminho)
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def main():
    p(f"Diagnóstico gerado em {datetime.datetime.now():%Y-%m-%d %H:%M}")

    # --- configuração ----------------------------------------------------
    p("\n== Configuração ==")
    rotulos = []
    try:
        from config_pipeline import ler_input
        d = ler_input()
        rotulos = list(d["termos_pubmed"]) or ["(geral)"]
        p(f"táxons do usuário: {len(d['taxons'])} (de {d.get('fonte_taxons', '?')})")
        p(f"atividades ({len(rotulos)}): {', '.join(rotulos)}")
        for secao in ("pubmed", "ollama"):
            cfg = {k: v for k, v in d["config"][secao].items() if k not in ("ncbi_api_key", "email")}
            p(f"[{secao}] {cfg}")
        p(f"chave do NCBI preenchida: {'sim' if d['config']['pubmed'].get('ncbi_api_key') or os.environ.get('NCBI_API_KEY') else 'NÃO'}")
    except Exception as e:  # noqa: BLE001
        p(f"(não foi possível ler o input.txt: {e})")

    # --- entradas da etapa -------------------------------------------------
    p("\n== Entradas ==")
    try:
        import pandas as pd
        if os.path.exists("plantas.csv"):
            pl = pd.read_csv("plantas.csv", dtype=str)
            esp = pl["nome_cientifico"].fillna("").str.split().str.len() >= 2
            nao_rec = pl.get("situacao_nome", pd.Series("", index=pl.index)).fillna("") == "não reconhecido"
            p(f"plantas.csv: {len(pl)} linhas; {int((esp & ~nao_rec).sum())} espécies reconhecidas")
        if os.path.exists("especies_com_compostos_bioativos.csv"):
            bio = pd.read_csv("especies_com_compostos_bioativos.csv", dtype=str)
            ik = bio["composto_inchikey"].dropna().nunique()
            p(f"especies_com_compostos_bioativos.csv: {len(bio)} pares; "
              f"{bio['nome_cientifico'].nunique()} plantas com compostos; {ik} InChIKeys distintos")
            p(f"  pares por base: { {k: int(v) for k, v in bio['base'].value_counts().head(8).items()} }")
    except Exception as e:  # noqa: BLE001
        p(f"(erro lendo as entradas: {e})")

    # --- caches: tamanho e última gravação --------------------------------------
    p("\n== Caches (tamanho, linhas, última gravação) ==")
    for c in CACHES:
        if os.path.exists(_C.cache(c)):
            n = sum(1 for _ in open(_C.cache(c), encoding="utf-8", errors="replace"))
            p(f"{c:32} {os.path.getsize(_C.cache(c)) / 1e6:9.1f} MB {n:10d} linhas   {quando(_C.cache(c))}")
        else:
            p(f"{c:32} (não existe)")

    # --- PubChem -------------------------------------------------------------
    p("\n== PubChem ==")
    pc = list(ler("cache_pubchem.jsonl"))
    if pc:
        p(f"compostos consultados: {len(pc)}; com CID: {sum(1 for x in pc if x.get('cid'))}; "
          f"com InChIKey: {sum(1 for x in pc if x.get('inchikey'))}; "
          f"só por nome (sem InChIKey na chave): {sum(1 for x in pc if str(x.get('chave', '')).startswith('nome:'))}")
    cid = list(ler("cache_pubchem_cid.jsonl"))
    if cid:
        p(f"CID por InChIKey (fase 2): {len(cid)} consultados; {sum(1 for x in cid if x.get('cid'))} achados")
    vinc = list(ler("cache_pubchem_vinculos.jsonl"))
    if vinc:
        n_art = [len(x.get("pmids") or []) for x in vinc]
        com = [n for n in n_art if n]
        p(f"vínculos CID -> PubMed: {len(vinc)} CIDs; {len(com)} com artigos; "
          f"{sum(com)} vínculos no total; mediana por CID com artigos: "
          f"{sorted(com)[len(com) // 2] if com else 0}; máximo: {max(com) if com else 0}")
    filt = list(ler("cache_pubmed_filtro.jsonl"))
    if filt:
        p(f"filtro por atividade (lotes): {len(filt)} lotes; "
          f"{sum(len(x.get('verificados') or []) for x in filt)} PMIDs verificados; "
          f"{sum(len(x.get('aprovados') or []) for x in filt)} aprovados")

    # --- buscas no PubMed ------------------------------------------------------
    p("\n== Buscas no PubMed ==")
    buscas = list(ler("cache_pubmed_buscas.jsonl"))
    if buscas:
        por_tipo = Counter(str(b.get("chave", "")).split("|")[0] for b in buscas)
        p(f"buscas feitas: {len(buscas)} -> {dict(por_tipo)}")
        for tipo in ("planta", "composto"):
            bs = [b for b in buscas if str(b.get("chave", "")).startswith(tipo + "|")]
            if not bs:
                continue
            vazias = sum(1 for b in bs if not b.get("pmids"))
            entidades = {b["chave"].split("||")[0] for b in bs}
            n_pmids = [len(b.get("pmids") or []) for b in bs]
            p(f"  {tipo}: {len(entidades)} entidades; {len(bs)} buscas; "
              f"{vazias} ({100 * vazias / len(bs):.0f}%) sem nenhum artigo; "
              f"{sum(n_pmids)} PMIDs ao todo; teto atingido em "
              f"{sum(1 for b in bs if b.get('retmax') and len(b.get('pmids') or []) >= b['retmax'])} buscas")
            por_rotulo = Counter(b["chave"].split("||")[-1] or "(geral)" for b in bs)
            p(f"    por atividade: {dict(por_rotulo)}")
            com_artigos = Counter(b["chave"].split("||")[-1] or "(geral)" for b in bs if b.get("pmids"))
            p(f"    com artigos, por atividade: {dict(com_artigos)}")
        exemplos = [b["query"] for b in buscas if str(b.get("chave", "")).startswith("planta|")][:2]
        for q in exemplos:
            p(f"  exemplo de busca: {q[:300]}")

    # --- modelo -----------------------------------------------------------------
    p("\n== Modelo (Ollama) ==")
    llm = list(ler("cache_llm_classificacao.jsonl"))
    if llm:
        versoes = Counter(str(x.get("chave", "")).split("|")[0] for x in llm)
        tipos = Counter(str(x.get("chave", "")).split("|")[3] if str(x.get("chave", "")).count("|") >= 5 else "?"
                        for x in llm)
        pos = [x for x in llm if x.get("positivo")]
        p(f"pares classificados: {len(llm)} (por versão do prompt: {dict(versoes)}; por tipo: {dict(tipos)})")
        p(f"positivos: {len(pos)} ({100 * len(pos) / len(llm):.1f}%)")
        atv = Counter(a for x in pos for a in (x.get("atividades") or []))
        p(f"atividades nos positivos: {dict(atv.most_common(15))}")
        est = Counter(e for x in pos for e in (x.get("tipo_estudo") or []))
        if est:
            p(f"tipos de estudo nos positivos: {dict(est)}")
    art = os.path.exists(_C.cache("cache_pubmed_artigos.jsonl"))
    if art:
        n = sum(1 for _ in open(_C.cache("cache_pubmed_artigos.jsonl"), encoding="utf-8", errors="replace"))
        p(f"resumos baixados: {n}")

    with open(SAIDA, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas_saida) + "\n")
    print(f"\nResumo gravado em {SAIDA} - mande este arquivo.")


if __name__ == "__main__":
    main()
