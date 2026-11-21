"""
montar_lista_plantas.py  -  ETAPA 2 ("plantas")

Monta a lista de plantas, antes de qualquer busca de compostos ou atividades:

  1. Três fontes:
       lista    a SUA lista: config/lista_de_plantas.txt ou, se ele não
                existir, a seção [taxons] do input.txt. Os nomes ficam
                INTACTOS - nenhum é trocado, filtrado ou descartado.
       gbif     plantas com ocorrência na região (especies_gbif.csv, etapa 1)
       artigos  nomes científicos citados em artigos que mencionam a região
                (PubMed + OpenAlex; descoberta_artigos.py)
  2. Conferência taxonômica (taxonomia.py) em quatro bases: Flora e Funga do
     Brasil, WFO, WCVP (Kew) e GBIF. Nenhum nome é trocado: o nome aceito vai
     para a coluna nome_aceito, e todos os nomes conhecidos da planta (o
     original, o aceito, sinônimos e grafias) vão para nomes_busca, usada
     nas buscas de compostos e artigos.
  3. Filtro do que NÃO é planta (só para os nomes do GBIF e dos artigos; a
     sua lista nunca é filtrada):
       a. o gênero precisa existir na Flora, no WFO ou no WCVP - elimina os
          pares de palavras ("This paper", "Esse artigo", "Birth cohort");
       b. o nome precisa ser reconhecido como PLANTA por ao menos uma das
          quatro bases - elimina animais, fungos e microrganismos, inclusive
          em gêneros homônimos (Solenopsis geminata, uma formiga).
  4. Duplicatas: todos os nomes que levam à MESMA espécie aceita (o aceito,
     sinônimos e grafias variantes), venham da sua lista, do GBIF ou dos
     artigos, viram UMA linha, com o nome aceito em nome_cientifico. Os
     outros nomes ficam em nomes_juntados e em nomes_busca (usada nas buscas
     de compostos e artigos): nenhum nome é descartado. Nomes que nenhuma
     base reconhece, ou homônimos ambíguos, ficam em linhas próprias.
  5. Uma linha por ESPÉCIE: nome_cientifico tem só gênero + epíteto;
     variedades e subespécies entram na linha da espécie, e o nome completo
     delas vai para nomes_busca.

Saídas:
  plantas.csv                         lista final (uma linha por planta)
  plantas_conferencia_taxonomica.csv  um nome original por linha, com o
                                      veredito de cada base e a linha em que
                                      ficou
  plantas_artigos_evidencias.csv      planta x artigo da descoberta (com as
                                      atividades do input citadas no texto)
  plantas_descartados.csv             nomes do GBIF e dos artigos que ficaram
                                      fora por não serem plantas, com o motivo
"""

import hashlib
import os

import caminhos as _C
import re
import sys
import time

import pandas as pd
import requests

import distribuicao as DIST
import taxonomia as T
from buscar_especies_gbif import chave_texto, refazer_saida_sem_chaves
from config_pipeline import geometria_da_regiao, gravar_csv, ler_input
from descoberta_artigos import descobrir, formatar_atividades
from literatura import criar_sessao, tqdm

ENTRADA_GBIF = "especies_gbif.csv"
SAIDA = "plantas.csv"
SAIDA_CONFERENCIA = "plantas_conferencia_taxonomica.csv"
SAIDA_EVIDENCIAS = "plantas_artigos_evidencias.csv"
SAIDA_DESCARTADOS = "plantas_descartados.csv"
CACHE_EXTRAS = _C.cache("cache_gbif_extras.jsonl")

COLUNAS = ["speciesKey", "reino", "filo", "classe", "ordem", "familia",
           "nome_cientifico", "nome_aceito", "nome_popular_pt", "categoria_taxonomica",
           "n_ocorrencias_na_area", "estados_br", "dominios_br", "endemismo_br", "origem_br",
           "fonte_distribuicao", "registros_gbif_por_uf", "nomes_juntados", "situacao_nome", "nomes_busca",
           "observacoes_taxonomia", "fonte", "atividades_artigos"]
ORDEM_FONTES = ["lista", "gbif", "artigos"]
MAX_SINONIMOS = 30      # sinônimos das bases acrescentados a nomes_busca, por espécie
PRIORIDADE_FONTE = {f: i for i, f in enumerate(ORDEM_FONTES)}

URL_OCORRENCIAS = "https://api.gbif.org/v1/occurrence/search"
URL_VERNACULAR = "https://api.gbif.org/v1/species/{}/vernacularNames"


# =============================================================================
# Ocorrências na região e nome popular (GBIF), só para nomes fora do
# levantamento da região - informação, não filtro
# =============================================================================

def _primeiro(*valores):
    """Primeiro valor preenchido (ignora None, NaN e texto vazio)."""
    for v in valores:
        if isinstance(v, str) and v.strip():
            return v
        if v is not None and not isinstance(v, str) and pd.notna(v):
            return v
    return None

FALHAS_EXTRAS = {"seguidas": 0, "desligado": False}
MAX_FALHAS_EXTRAS = 8       # GBIF fora do ar: para de consultar (cada falha já inclui 5 novas tentativas)


def extras_gbif(sessao, chave_especie, wkt, cache, paises=()) -> dict:
    ck = f"{chave_especie}|{hashlib.md5(wkt.encode()).hexdigest()[:8]}"
    if paises:
        ck += "|" + ",".join(sorted(paises))
    if ck in cache:
        return cache[ck]
    item = {"chave": ck, "n": None, "popular": ""}
    if FALHAS_EXTRAS["desligado"]:
        return item
    try:
        r = sessao.get(URL_OCORRENCIAS, timeout=60, params={
            "taxonKey": chave_texto(chave_especie), "geometry": wkt, "limit": 0,
            "hasCoordinate": "true", "hasGeospatialIssue": "false",
            "occurrenceStatus": "PRESENT", **({"country": list(paises)} if paises else {})})
        r.raise_for_status()
        item["n"] = int(r.json().get("count", 0))
        r = sessao.get(URL_VERNACULAR.format(chave_texto(chave_especie)), params={"limit": 200}, timeout=30)
        if r.status_code == 200:
            nomes = []
            for v in r.json().get("results", []):
                n = (v.get("vernacularName") or "").strip()
                if v.get("language") in ("por", "pt") and n and n not in nomes:
                    nomes.append(n)
            item["popular"] = "; ".join(nomes)
    except (requests.RequestException, ValueError, TypeError):
        FALHAS_EXTRAS["seguidas"] += 1
        if FALHAS_EXTRAS["seguidas"] >= MAX_FALHAS_EXTRAS:
            FALHAS_EXTRAS["desligado"] = True
            print(f"\nAVISO: GBIF sem resposta em {MAX_FALHAS_EXTRAS} consultas seguidas - "
                  "ocorrências na área e nomes populares das demais plantas da lista ficam "
                  "em branco nesta rodada (são buscados na próxima).")
        return item          # não grava: tenta de novo na próxima execução
    finally:
        time.sleep(0.05)
    FALHAS_EXTRAS["seguidas"] = 0
    cache[ck] = item
    T._gravar_cache(CACHE_EXTRAS, item)
    return item


# =============================================================================
def categoria(nome: str) -> str:
    if T.eh_genero(nome):
        return "GENUS"
    if " var. " in nome:
        return "VARIETY"
    if " subsp. " in nome:
        return "SUBSPECIES"
    if " f. " in nome:
        return "FORM"
    return "SPECIES"


def juntar(valores, sep="; "):
    saida = []
    for v in valores:
        for parte in str(v).split(sep) if isinstance(v, str) else []:
            parte = parte.strip()
            if parte and parte not in saida:
                saida.append(parte)
    return sep.join(saida)


def binomio(nome: str) -> str:
    """Só gênero + epíteto da espécie: 'Erythroxylum coca var. ipadu Plowman'
    -> 'Erythroxylum coca'. O sinal de híbrido é mantido ('Citrus × limon')."""
    a = T.analisar(nome)
    if not a["genero"]:
        return nome.strip()
    if not a["epiteto"]:
        return a["genero"].capitalize()
    # sinal de híbrido: "Citrus × limon", "Citrus x limon" ou "Citrus ×limon" (Flora)
    hibrido = re.match(r"^\S+\s+(?:[×x]\s+|×)\S", nome.strip()) is not None
    return a["genero"].capitalize() + (" × " if hibrido else " ") + a["epiteto"].lower()


def chave_grupo(o) -> str:
    """Nomes com a mesma chave viram UMA linha: a espécie aceita, quando as
    bases a identificam com segurança; senão, o próprio nome."""
    dec = o["decisao"]
    if dec["situacao"] in ("não reconhecido", "homônimo ambíguo"):
        return "nome|" + (T.chave(o["nome"]) or o["nome"].lower())
    return "aceito|" + dec["aceito"].lower()


def eh_o_aceito(m) -> bool:
    """O nome é o próprio nome aceito (não sinônimo nem grafia variante)."""
    return binomio(m["nome"]).lower() == binomio(m["decisao"]["aceito"]).lower()


def representante(membros):
    """O membro cuja decisão taxonômica vale para a linha: o que já é o nome
    aceito; senão o da sua lista, o do GBIF, o do artigo; depois, a ordem
    em que apareceram."""
    return min(membros, key=lambda m: (not eh_o_aceito(m),
                                       min(PRIORIDADE_FONTE[f] for f in m["fontes"]),
                                       m["ordem"]))


def nome_da_linha(membros) -> str:
    """nome_cientifico da linha: o nome ACEITO da espécie (gênero + epíteto)
    quando as bases a identificam; senão, o nome como veio da fonte."""
    r = representante(membros)
    if r["decisao"]["situacao"] in ("não reconhecido", "homônimo ambíguo"):
        return binomio(r["textos"][0] if "lista" not in r["fontes"] else r["nome"])
    return binomio(r["decisao"]["aceito"])


def main():
    dados = ler_input()
    geo = geometria_da_regiao(dados)
    sessao = criar_sessao()
    cfg_art = dados["config"]["artigos"]
    antigas = [k for k in ("incluir_plantas_listadas", "filtro_ocorrencia", "estados",
                           "dominios", "flora_brasil_url", "max_artigos_por_atividade")
               if cfg_art.get(k)]
    if antigas:
        print(f"AVISO: [artigos] {', '.join(antigas)} não são mais usados - ignorados.")
    if cfg_art.get("termos_regiao"):
        print("AVISO: termos_regiao em [artigos] é de uma versão anterior; mova-o para "
              "termos_texto, em [regiao]. Usando por enquanto: "
              + ", ".join(dados["termos_regiao"]))

    # --- 1. fontes ----------------------------------------------------------
    origens = {}            # chave do nome (sem diferenciar maiúsculas) -> dados
    so_genero = []          # registros do GBIF/artigos só de gênero (ficam de fora)

    def registrar(nome, fonte, linha_gbif=None, atividades=None):
        k = T.chave(nome) or nome.strip().lower()
        if not k:
            return
        if fonte != "lista" and T.eh_genero(nome):
            # registro só de gênero (ex.: GBIF "Psychotria"): não é espécie
            so_genero.append({"nome": nome.strip(), "fonte": fonte,
                              "motivo": "só gênero, sem espécie", "n_artigos": 0,
                              "exemplo_referencia": ""})
            return
        o = origens.setdefault(k, {"nome": nome.strip(), "textos": [], "fontes": set(),
                                   "gbif": None, "atividades": {}, "ordem": len(origens)})
        if fonte == "lista" and "lista" not in o["fontes"]:
            o["nome"] = nome.strip()          # o nome da sua lista, exatamente como escrito
        if nome.strip() not in o["textos"]:
            o["textos"].append(nome.strip())
        o["fontes"].add(fonte)
        if linha_gbif is not None and o["gbif"] is None:
            o["gbif"] = linha_gbif
        for rotulo, refs in (atividades or {}).items():
            o["atividades"].setdefault(rotulo, set()).update(refs)

    for nome in dados["taxons"]:
        registrar(nome, "lista")
    print(f"lista: {len(dados['taxons'])} nome(s) de {dados['fonte_taxons']}"
          + (f" ({len(dados['taxons_repetidos'])} repetição(ões) idêntica(s) removida(s))"
             if dados["taxons_repetidos"] else "") + " - mantidos como estão")

    if os.path.exists(ENTRADA_GBIF):
        # especies_gbif.csv da v3 não tem speciesKey: refeito do download local
        refazer_saida_sem_chaves(geo["wkt"], dados.get("paises") or ())
        gbif = pd.read_csv(ENTRADA_GBIF, dtype=str)
        for _, linha in gbif.iterrows():
            if isinstance(linha["nome_cientifico"], str):
                registrar(linha["nome_cientifico"], "gbif", linha_gbif=linha.to_dict())
        print(f"gbif: {len(gbif)} plantas da região ({ENTRADA_GBIF})")
    else:
        print(f"AVISO: {ENTRADA_GBIF} não encontrado - fonte 'gbif' fica de fora "
              "(rode a etapa 'gbif' para incluí-la).")

    print()
    registros, evidencias = descobrir(sessao)
    listas = T.listas_baixadas()
    locais = [lst for b, lst in listas.items() if b in T.LOCAIS]
    descartados = list(so_genero)   # nomes do GBIF/artigos que ficam fora da lista

    def descartar(nome, fonte, motivo, refs=()):
        refs = sorted(refs)
        descartados.append({"nome": nome, "fonte": fonte, "motivo": motivo,
                            "n_artigos": len(refs), "exemplo_referencia": refs[0] if refs else ""})

    # filtro (a): o gênero precisa existir numa lista de plantas. É local e
    # rápido, e elimina os pares de palavras que só PARECEM nomes científicos
    if registros and locais:
        for lst in locais:
            lst._carregar()
        for chave_reg, reg in list(registros.items()):
            if T.chave(reg["nome"]) in origens:      # já está na sua lista ou no GBIF
                continue
            genero = T.analisar(reg["nome"])["genero"]
            if not any(lst.genero_existe(genero) for lst in locais):
                descartar(reg["nome"], "artigos", "não é nome de planta: o gênero não existe na "
                          "Flora e Funga do Brasil, no WFO nem no WCVP", reg["refs"])
                del registros[chave_reg]
        if descartados:
            print(f"artigos: {len(descartados)} nome(s) descartados - o gênero não existe nas "
                  "listas de plantas (pares de palavras, animais, microrganismos)")
    for reg in registros.values():
        registrar(reg["nome"], "artigos", atividades=reg["atividades"])
    print(f"artigos: {len(registros)} nome(s) de gênero vegetal citados nos artigos da região")

    if not origens:
        sys.exit("Nada a fazer: nenhuma planta do GBIF, da lista ou de artigos.")
    print(f"\n{len(origens)} nome(s) distintos para conferir")

    # --- 2. conferência taxonômica (só anota; nenhum nome é trocado) -------
    api_gbif = T.GBIF(sessao) if T.CFG["usar_gbif"] else None
    tem_gbif = api_gbif is not None or any(o["gbif"] is not None for o in origens.values())
    usadas = [b for b, _ in T.BASES if b in listas or (b == "gbif" and tem_gbif)]
    print("Conferência taxonômica (só anotação): " + ", ".join(T.NOME_BASE[b] for b in usadas)
          + " (prioridade nesta ordem)")
    if not usadas:
        print("AVISO: todas as bases desligadas em [taxonomia] - nomes ficam sem conferência.")

    # lê as listas antes da barra de progresso (só se algum nome não estiver em cache)
    # (as listas são lidas sempre: além de conferir os nomes, fornecem os
    # sinônimos de cada espécie para nomes_busca)
    for lista in listas.values():
        lista._carregar()

    pendentes_gbif = 0
    for k, o in tqdm(list(origens.items()), desc="Conferindo nomes"):
        res = {b: lista.conferir(o["nome"]) for b, lista in listas.items()}
        if o["gbif"] is not None:
            # veio do levantamento da região, que só traz o reino Plantae: o
            # GBIF já o reconhece como planta (mesmo com usar_gbif = false)
            g = o["gbif"]
            res["gbif"] = {"status": "genero" if T.eh_genero(o["nome"]) else "aceito",
                           "aceito": T.canonico(o["nome"]), "filo": g.get("filo"),
                           "classe": g.get("classe"), "ordem": g.get("ordem"),
                           "familia": g.get("familia"), "speciesKey": g.get("speciesKey")}
        elif api_gbif:
            res["gbif"] = api_gbif.conferir(o["nome"])
            pendentes_gbif += res["gbif"] is None
        o["res"] = res
        o["decisao"] = T.decidir(o["nome"], res)
    if pendentes_gbif:
        print(f"AVISO: {pendentes_gbif} consulta(s) ao GBIF falharam (rede) - rode a etapa "
              "de novo para completá-las.")

    # filtro (b): nomes do GBIF e dos artigos que nenhuma das bases reconhece
    # como planta saem da lista (ex.: "Solenopsis geminata", uma formiga, num
    # gênero que também existe em plantas). A sua lista nunca é filtrada.
    for k in [k for k, o in origens.items()
              if "lista" not in o["fontes"] and o["decisao"]["situacao"] == "não reconhecido"]:
        o = origens.pop(k)
        reg = registros.get(o["nome"].lower()) or {"refs": set()}
        descartar(o["nome"], "; ".join(f for f in ORDEM_FONTES if f in o["fontes"]),
                  "não reconhecido como planta em nenhuma base: " + o["decisao"]["observacoes"],
                  reg["refs"])
    if descartados:
        print(f"{len(descartados)} nome(s) do GBIF e dos artigos ficaram fora da lista "
              f"(não são plantas) - veja {SAIDA_DESCARTADOS}")

    # --- 3. uma linha por espécie (duplicatas juntadas) ----------------------
    cache_extras = T._carregar_cache(CACHE_EXTRAS)
    grupos = {}
    for o in origens.values():
        grupos.setdefault(chave_grupo(o), []).append(o)
    # todos os nomes da mesma espécie aceita (lista, GBIF e artigos) = uma
    # linha, com o nome aceito; os demais vão para nomes_juntados/nomes_busca
    linhas_membros = list(grupos.values())

    # uma linha por ESPÉCIE (gênero + epíteto): variedades e subespécies
    # entram na linha da espécie, e o nome delas vai para nomes_busca
    # (ex.: "Erythroxylum coca var. ipadu" e "Erythroxylum coca" -> uma linha
    # "Erythroxylum coca", com os dois nomes em nomes_busca)
    por_especie = {}
    for membros in linhas_membros:
        por_especie.setdefault(nome_da_linha(membros).lower(), []).extend(membros)
    linhas_membros = list(por_especie.values())

    linhas, conferencia = [], []
    for membros in tqdm(linhas_membros, desc="Montando a lista"):
        rep = representante(membros)
        nome = nome_da_linha(membros)
        dec = rep["decisao"]
        reconhecido = dec["situacao"] != "não reconhecido"
        situacao = dec["situacao"]
        if reconhecido and eh_o_aceito(rep) and situacao in ("sinônimo", "grafia variante",
                                                            "grafia variante de sinônimo"):
            situacao = "aceito"      # mesmo nome, só outra notação (ex.: sinal de híbrido)
        elif reconhecido and not eh_o_aceito(rep) and situacao != "homônimo ambíguo":
            # nenhuma fonte trouxe o nome aceito, só sinônimos/grafias: a
            # linha recebe o nome aceito das bases, e os originais vão para
            # nomes_juntados
            situacao = "aceito (nas fontes só sinônimo ou grafia variante)"
        if not reconhecido and "lista" in rep["fontes"]:
            # nome da sua lista que nenhuma base conhece (ex.: espécie descrita
            # há pouco): fica, e é pesquisado normalmente nas etapas seguintes
            situacao = "não reconhecido nas bases (mantido: está na sua lista)"
        aceito = binomio(dec["aceito"]) if reconhecido else None
        # taxonomia: linha do levantamento GBIF > resposta da API do GBIF > outras bases
        # com sinônimos juntados, vale a linha do GBIF do próprio nome aceito
        membros_gbif = sorted((m for m in membros if m["gbif"] is not None),
                              key=lambda m: not eh_o_aceito(m))
        linha_gbif = membros_gbif[0]["gbif"] if membros_gbif else None
        res_gbif = next((m["res"].get("gbif") for m in membros
                         if (m["res"].get("gbif") or {}).get("status") in T.RECONHECIDO), None) or {}
        # família: a da base que identificou a espécie (Flora > WFO > GBIF); a
        # classificação do GBIF (filo, classe, ordem, speciesKey) só é usada se
        # o GBIF puser a planta na MESMA família - senão, é quase sempre um
        # homônimo de outro reino (ex.: Pleroma, gênero de plantas e de insetos)
        familia_dec = _primeiro(*(m["decisao"].get("familia") for m in membros
                                  if m["decisao"].get("base") in T.LOCAIS))
        familia_gbif = _primeiro((linha_gbif or {}).get("familia"), res_gbif.get("familia"))
        familia = _primeiro(familia_dec, familia_gbif, *(m["decisao"].get("familia") for m in membros))
        gbif_coerente = (not familia_dec or not familia_gbif
                         or str(familia_dec).strip().lower() == str(familia_gbif).strip().lower())
        especie_key = _primeiro((linha_gbif or {}).get("speciesKey"), res_gbif.get("speciesKey"))
        if not gbif_coerente:
            especie_key = None
        if linha_gbif is not None:
            n_occ = sum(pd.to_numeric(pd.Series([m["gbif"].get("n_ocorrencias_na_area")
                                                 for m in membros if m["gbif"] is not None]),
                                      errors="coerce").fillna(0))
            popular = juntar([m["gbif"].get("nome_popular_pt") for m in membros if m["gbif"] is not None])
        elif api_gbif and especie_key and str(especie_key) not in ("", "nan", "None"):
            ex = extras_gbif(sessao, especie_key, geo["wkt"], cache_extras, dados.get("paises") or ())
            n_occ, popular = ex["n"], ex["popular"]
        else:
            n_occ, popular = None, ""

        fontes = set().union(*(m["fontes"] for m in membros))
        atividades = {}
        for m in membros:
            for r, refs in m["atividades"].items():
                atividades.setdefault(r, set()).update(refs)
        outros = [t for m in membros for t in m["textos"] if t != nome]
        if len(membros) == 1:
            obs = dec["observacoes"]
        else:
            obs = " || ".join(f"[{m['textos'][0]}] {m['decisao']['observacoes']}" for m in membros)
        if not gbif_coerente:
            obs += (f" | AVISO: o GBIF classifica este nome em {familia_gbif} (provável homônimo); "
                    f"usada a família {familia_dec} e ignorados filo/classe/ordem/speciesKey do GBIF")
        # nomes de busca: o nome mostrado primeiro, depois todos os outros
        # sinônimos que as listas taxonômicas conhecem para o(s) nome(s) aceito(s),
        # mesmo que nenhuma fonte os tenha citado (ex.: um composto registrado
        # sob um sinônimo antigo no Dr. Duke ou no COCONUT)
        sinonimos = []
        for m in membros:
            if m["decisao"]["situacao"] in ("não reconhecido", "homônimo ambíguo"):
                continue
            for b in T.LOCAIS:
                if b in listas:
                    sinonimos += listas[b].sinonimos_de(m["decisao"]["aceito"])
        sinonimos = list(dict.fromkeys(sinonimos))[:MAX_SINONIMOS]
        busca = juntar([nome] + ["; ".join(m["decisao"]["nomes_busca"]) for m in membros]
                       + outros + sinonimos)
        linhas.append({
            "speciesKey": especie_key,
            "reino": "Plantae",
            "filo": _primeiro((linha_gbif or {}).get("filo"), res_gbif.get("filo")) if gbif_coerente else None,
            "classe": _primeiro((linha_gbif or {}).get("classe"), res_gbif.get("classe")) if gbif_coerente else None,
            "ordem": _primeiro((linha_gbif or {}).get("ordem"), res_gbif.get("ordem")) if gbif_coerente else None,
            "familia": familia,
            "nome_cientifico": nome,
            "nome_aceito": aceito,
            "nome_popular_pt": popular,
            "categoria_taxonomica": categoria(nome),
            "n_ocorrencias_na_area": n_occ,
            "nomes_juntados": "; ".join(dict.fromkeys(outros)),
            "situacao_nome": situacao,
            "nomes_busca": busca,
            "observacoes_taxonomia": obs,
            "fonte": "; ".join(f for f in ORDEM_FONTES if f in fontes),
            "atividades_artigos": formatar_atividades(atividades) if atividades else "",
        })
        for m in membros:
            sit = m["decisao"]["situacao"]
            m_aceito = m["decisao"]["aceito"]
            conferencia.append({
                "nome": "; ".join(m["textos"]),
                "fonte": "; ".join(f for f in ORDEM_FONTES if f in m["fontes"]),
                "situacao": sit,
                "nome_aceito": m_aceito if sit != "não reconhecido" else "",
                "linha_em_plantas_csv": nome,
                **{f"veredito_{b}": T.descrever(b, m["res"].get(b)) for b in usadas},
                "_grupo": nome.lower(), "_ordem": 0 if m is rep else 1})

    plantas = pd.DataFrame(linhas, columns=COLUNAS)
    plantas["speciesKey"] = plantas["speciesKey"].map(chave_texto).replace("", None)
    # estados brasileiros, domínios, endemismo e origem (Flora e Funga do Brasil)
    print()
    plantas = DIST.anexar(plantas)
    plantas["n_ocorrencias_na_area"] = pd.to_numeric(
        plantas["n_ocorrencias_na_area"], errors="coerce").astype("Int64")
    plantas["_lista"] = plantas["fonte"].str.contains("lista").astype(int)
    plantas = plantas.sort_values(["_lista", "n_ocorrencias_na_area"], ascending=[False, False],
                                  na_position="last").drop(columns="_lista")
    conf = pd.DataFrame(conferencia).sort_values(["_grupo", "_ordem", "nome"])
    gravar_csv(conf.drop(columns=["_grupo", "_ordem"]), SAIDA_CONFERENCIA)

    linha_por_original = {T.chave(t): r["nome_cientifico"] for _, r in plantas.iterrows()
                          for t in [r["nome_cientifico"]] + str(r["nomes_juntados"] or "").split("; ") if t}
    evid = pd.DataFrame(evidencias, columns=["nome_no_artigo", "atividades_no_texto", "base",
                                             "referencia", "ano", "titulo", "doi"])
    evid.insert(1, "linha_em_plantas_csv", evid["nome_no_artigo"].map(lambda n: linha_por_original.get(T.chave(n))))
    evid = evid[evid["linha_em_plantas_csv"].notna()]          # só nomes que ficaram na lista
    gravar_csv(evid.drop_duplicates(["nome_no_artigo", "referencia"]), SAIDA_EVIDENCIAS)
    gravar_csv(pd.DataFrame(descartados, columns=["nome", "fonte", "motivo", "n_artigos",
                                                  "exemplo_referencia"])
               .sort_values("n_artigos", ascending=False), SAIDA_DESCARTADOS)
    gravar_csv(plantas, SAIDA)        # por último: marca a etapa como concluída

    juntadas = int((plantas["nomes_juntados"].fillna("") != "").sum())
    print(f"\nConcluído: {len(plantas)} planta(s) em {SAIDA} (a partir de {len(origens)} "
          f"nome(s); {juntadas} linha(s) juntaram nomes da mesma espécie - veja nomes_juntados)")
    especies = plantas["categoria_taxonomica"] != "GENUS"
    print(f"speciesKey do GBIF preenchido em {plantas.loc[especies, 'speciesKey'].notna().sum()} "
          f"de {especies.sum()} espécie(s)")
    print("\nPor fonte:")
    print(plantas["fonte"].value_counts().to_string())
    print("\nSituação do nome de cada linha (os demais nomes estão em nomes_juntados):")
    print(plantas["situacao_nome"].value_counts().to_string())
    div = sum("DIVERGÊNCIA" in str(o) for o in plantas["observacoes_taxonomia"])
    if div:
        print(f"\n{div} planta(s) com divergência entre bases - veja observacoes_taxonomia")
    print(f"Conferência nome a nome em {SAIDA_CONFERENCIA}")


if __name__ == "__main__":
    main()
