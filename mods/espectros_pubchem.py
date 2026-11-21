"""
espectros_pubchem.py  -  fonte espectral: espectros EXPERIMENTAIS do PubChem

O PubChem compila, por composto (CID), os espectros depositados por terceiros
(MassBank, HMDB, SpectraBase, NIST...): MS, MS/MS, GC-MS, LC-MS, RMN, IV e UV.
Esta fonte guarda os METADADOS de cada registro (tipo, subtipo, descrição,
depositante, identificador e link), não o espectro em si - o que mantém o
banco leve e consultável.

Um pedido por composto, com cache em cache_pubchem_espectros.jsonl: na
segunda rodada não consulta nada de novo.

Registrada automaticamente por espectros.py (ver a seção 26 do README).
"""

import caminhos as _C
import quimio as Q

FONTE = {
    "nome": "pubchem",
    "rotulo": "PubChem (espectros experimentais)",
    "rede": True,
    "padrao": True,
    "ordem": 20,
}

CACHE = _C.cache("cache_pubchem_espectros.jsonl")


def coletar(compostos, contexto: dict) -> list:
    if compostos is None or compostos.empty or "pubchem_cid" not in compostos.columns:
        return []
    com_cid = compostos.dropna(subset=["pubchem_cid"])
    if com_cid.empty:
        return []

    cache = Q.Cache(CACHE)
    faltam = [c for c in dict.fromkeys(com_cid["pubchem_cid"]) if f"e|{c}" not in cache]
    if faltam:
        print(f"  PubChem (espectros): {len(faltam)} CID(s) a consultar")
        cli = Q.Cliente("PubChem (espectros)", intervalo=0.25)
        for i, cid in enumerate(faltam, 1):
            res = Q.pubchem_espectros(cli, cid)
            if res is None:
                if cli.desistiu:     # servidor fora do ar: para e usa o cache
                    break
                continue
            cache.gravar(f"e|{cid}", res)
            if i % 200 == 0:
                print(f"  ... {i}/{len(faltam)}")
    cache.fechar()

    linhas = []
    for _, c in com_cid.iterrows():
        for s in cache.get(f"e|{c['pubchem_cid']}") or []:
            linhas.append({"inchikey": c["inchikey"], "origem": "experimental",
                           "tipo": s.get("tipo"), "subtipo": s.get("subtipo"),
                           "descricao": s.get("descricao"), "fonte": s.get("fonte"),
                           "id_fonte": s.get("id_fonte"), "url": s.get("url")})
    return linhas
