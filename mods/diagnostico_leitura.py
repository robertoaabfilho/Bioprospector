"""
diagnostico_leitura.py - o que o modelo da etapa 5 (pubmed) já leu e o que falta

Rode da pasta do projeto:   python3 mods/diagnostico_leitura.py
(ou pelo painel: página 5 · PubMed, aba "Leitura do modelo")

Usa o próprio código da etapa 5 em modo --parcial: monta a mesma lista de pares
entidade x artigo que a etapa monta, SEM internet, SEM ler artigo novo e SEM
gravar nenhuma planilha ou cache. Depois compara a lista com o cache do modelo
(cache_llm_classificacao.jsonl).

Mostra:
  1. a sequência de leitura gravada no cache (blocos planta/composto);
  2. por grupo (plantas com compostos, sem compostos citadas na descoberta,
     compostos): pares lidos e pares que faltam, separando os artigos da
     descoberta (etapa 2) dos achados pela busca por nome;
  3. em que bloco do cache estão os julgamentos de cada grupo (de que rodada são);
  4. as plantas com artigos ainda não lidos, INCLUSIVE as que já têm positivo.
Grava a lista completa em diagnostico_leitura_pendentes.csv.

Com --saida PASTA (usado pelo painel, página "Leitura do modelo"), grava tudo
em CSVs nessa pasta: sequencia.csv, grupos.csv, blocos.csv, pendentes.csv,
sem_pares.csv e meta.json (este por último: indica que o resto está pronto).
"""
import contextlib
import io
import json
import os
import sys

PASTA_MODS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA_MODS)    # a pasta de trabalho (resultados/) é definida pelo config_pipeline
SAIDA = None
if "--saida" in sys.argv:
    SAIDA = os.path.abspath(sys.argv[sys.argv.index("--saida") + 1])
    os.makedirs(SAIDA, exist_ok=True)
INICIO = __import__("time").time()
sys.argv = [sys.argv[0], "--parcial"]          # só o cache: sem internet, sem modelo

import pandas as pd                              # noqa: E402
import consultar_atividades_pubmed as M          # noqa: E402

capturado = {}


class _Parar(Exception):
    pass


_sel, _desc = M.selecionar_plantas, getattr(M, "artigos_da_descoberta", None)


def _selecionar(pl, df):
    r = _sel(pl, df)
    capturado["sel"] = r
    return r


def _descoberta(nomes):
    r = _desc(nomes)
    capturado["desc"] = r
    return r


def _classificar(pares, artigos, so_cache=False):
    capturado["pares"] = pares
    raise _Parar   # para aqui: nada de planilha nem cache gravado


M.selecionar_plantas = _selecionar
if _desc is not None:
    M.artigos_da_descoberta = _descoberta
M.classificar_tudo = _classificar

print("Montando a lista de pares como a etapa 5 (modo parcial, só cache)...")
saida_etapa = io.StringIO()
try:
    with contextlib.redirect_stdout(saida_etapa):
        M.main()
except _Parar:
    pass
if "pares" not in capturado:
    print(saida_etapa.getvalue()[-3000:])
    sys.exit("A etapa 5 parou antes de montar os pares (veja a saída acima).")
resumo_etapa = []
for linha in saida_etapa.getvalue().splitlines():
    if "serão pesquisadas" in linha or "entram" in linha or "par(es) entidade x artigo" in linha \
            or "Artigos da descoberta" in linha:
        print("  " + linha.strip())
        resumo_etapa.append(linha.strip())

pares = capturado["pares"]
sel = capturado["sel"]
plantas, fora, n_comp = sel[0], sel[1], sel[2]
por_citacao = sel[3] if len(sel) > 3 else set()
max_pl = M.CFG_PUBMED["max_artigos_por_planta"]
desc = {p: set(d["pmids"][:max_pl]) for p, d in (capturado.get("desc") or {}).items()}

# --- cache do modelo: chave -> posição (ordem de gravação) -------------------
modelo = M.CFG_OLLAMA["modelo"]


def chave(tipo, ent, pmid, versao=M.VERSAO_PROMPT):
    return f"{versao}|{M.ASSINATURA_FOCO}|{modelo}|{tipo}|{ent}|{pmid}"


posicao, tipos_seq = {}, []
with open(M.CACHE_LLM, encoding="utf-8", errors="replace") as f:
    for linha in f:
        try:
            item = json.loads(linha)
            k = item["chave"]
        except Exception:   # noqa: BLE001 - linha truncada
            continue
        posicao[k] = (len(tipos_seq), item.get("positivo"))
        tipos_seq.append(k.split("|")[3])

# blocos contíguos do mesmo tipo (só os com 50+ julgamentos; os pequenos se juntam ao anterior)
blocos, inicio = [], 0
for i in range(1, len(tipos_seq) + 1):
    if i == len(tipos_seq) or tipos_seq[i] != tipos_seq[inicio]:
        blocos.append([tipos_seq[inicio], inicio, i])
        inicio = i
grandes = []
for b in blocos:
    if grandes and (b[2] - b[1] < 50 or b[0] == grandes[-1][0]):
        grandes[-1][2] = b[2]
    else:
        grandes.append(b)


def bloco_de(pos):
    for n, (_, ini, fim) in enumerate(grandes, 1):
        if ini <= pos < fim:
            return n
    return 0


print("\n1. Sequência de leitura no cache (" + f"{len(tipos_seq):,}".replace(",", ".") + " julgamentos)")
for n, (t, ini, fim) in enumerate(grandes, 1):
    print(f"   bloco {n}: {t:9} " + f"{fim - ini:>8,}".replace(",", "."))


def grupo(tipo, ent):
    if tipo == "composto":
        return "3 compostos"
    nome = ent.split("|", 1)[1]
    if nome in por_citacao:
        return "2 plantas sem compostos citadas na descoberta"
    if n_comp.get(nome, 0) > 0:
        return "1 plantas com compostos"
    return "2b plantas sem compostos (outras)"


linhas = []
for tipo, ent, _, pmid in pares:
    k = chave(tipo, ent, pmid)
    if k in posicao:
        pos, positivo = posicao[k]
        situacao, bl = "lido", bloco_de(pos)
    else:
        antigo = next((posicao[chave(tipo, ent, pmid, v)] for v in M.VERSOES_NEGATIVO_REAPROVEITAVEL
                       if chave(tipo, ent, pmid, v) in posicao), None)
        if antigo and antigo[1] is False:
            situacao, bl, positivo = "lido (negativo da versão anterior do prompt)", bloco_de(antigo[0]), False
        else:
            situacao, bl, positivo = "FALTA LER", None, None
    nome = ent.split("|", 1)[1]
    origem = ("descoberta" if tipo == "planta" and pmid in desc.get(nome, ()) else "busca")
    linhas.append(dict(grupo=grupo(tipo, ent), tipo=tipo, entidade=nome, pmid=pmid, origem=origem,
                       situacao=situacao, bloco=bl, positivo=positivo))
t = pd.DataFrame(linhas)
if t.empty:
    sys.exit("Nenhum par entidade x artigo montado.")
t["lido"] = t["situacao"].ne("FALTA LER")

print("\n2. Pares entidade x artigo por grupo (origem: busca por nome ou artigo da descoberta)")
res = t.groupby(["grupo", "origem"]).agg(pares=("pmid", "size"), lidos=("lido", "sum"))
res["faltam"] = res["pares"] - res["lidos"]
print(res.to_string())

print("\n3. Em que bloco do cache estão os julgamentos (de que rodada são)")
lidos = t[t["bloco"].notna()]
if not lidos.empty:
    print(pd.crosstab([lidos["grupo"], lidos["origem"]], lidos["bloco"].astype(int)
                      .map(lambda b: f"bloco {b} ({grandes[b - 1][0]})" if b else "?")).to_string())

print("\n4. Entidades com artigos ainda não lidos")
pend = (t.groupby(["grupo", "tipo", "entidade"])
        .agg(pares=("pmid", "size"), faltam=("lido", lambda s: int((~s).sum())),
             positivos=("positivo", lambda s: int((s == True).sum())))  # noqa: E712
        .reset_index())
pend = pend[pend["faltam"] > 0].sort_values(["grupo", "faltam"], ascending=[True, False])
if pend.empty:
    print("   nenhuma: tudo o que a etapa 5 monta já foi lido.")
else:
    pend["situacao"] = pend["positivos"].map(lambda n: "já tem positivo (a planilha não mostra a pendência)"
                                             if n else "sem positivo ainda")
    print(pend.groupby(["grupo", "situacao"]).agg(entidades=("entidade", "size"),
                                                  artigos_faltando=("faltam", "sum")).to_string())
    print("\n   exemplos:")
    print(pend.head(15)[["grupo", "entidade", "pares", "faltam", "positivos"]].to_string(index=False))
    if not SAIDA:
        pend.to_csv("diagnostico_leitura_pendentes.csv", index=False, encoding="utf-8-sig")
        print("\n   lista completa: resultados/diagnostico_leitura_pendentes.csv")

sem_pares = [p for p in plantas if not ((t["tipo"] == "planta") & (t["entidade"] == p)).any()]
print("\nPlantas pesquisadas sem nenhum par (sem artigo com resumo, ou busca ainda não feita): "
      + f"{len(sem_pares):,}".replace(",", "."))


# --- saída para o painel ------------------------------------------------------
if SAIDA:
    def gravar(df, nome):
        tmp = os.path.join(SAIDA, nome + ".tmp")
        df.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, os.path.join(SAIDA, nome))

    gravar(pd.DataFrame([{"bloco": n, "tipo": tp, "julgamentos": fim - ini}
                         for n, (tp, ini, fim) in enumerate(grandes, 1)]), "sequencia.csv")
    gravar(res.reset_index(), "grupos.csv")
    gravar(lidos.assign(bloco=lidos["bloco"].astype(int))
           .groupby(["grupo", "origem", "bloco"]).size().rename("pares").reset_index()
           .assign(tipo_bloco=lambda d: d["bloco"].map(lambda b: grandes[b - 1][0] if b else "?")),
           "blocos.csv")
    # pendências por entidade e origem (a planilha da etapa 5 não mostra as das que já têm positivo)
    por_ent = (t.assign(falta=~t["lido"], pos=t["positivo"].eq(True))
               .groupby(["grupo", "tipo", "entidade"])
               .agg(pares=("pmid", "size"), faltam=("falta", "sum"), positivos=("pos", "sum"),
                    faltam_descoberta=("falta", lambda s: int((s & t.loc[s.index, "origem"].eq("descoberta")).sum())))
               .reset_index())
    gravar(por_ent[por_ent["faltam"] > 0], "pendentes.csv")
    gravar(pd.DataFrame({"planta": sem_pares}), "sem_pares.csv")
    meta = {"inicio": INICIO, "fim": __import__("time").time(), "julgamentos_no_cache": len(tipos_seq),
            "pares": int(len(t)), "lidos": int(t["lido"].sum()), "plantas_pesquisadas": len(plantas),
            "plantas_por_citacao": len(por_citacao), "resumo_etapa": resumo_etapa}
    tmp = os.path.join(SAIDA, "meta.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(SAIDA, "meta.json"))
    print(f"\nArquivos do diagnóstico gravados em {SAIDA}")
