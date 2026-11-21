"""
espectros_teoricos.py  -  fonte espectral: m/z TEÓRICOS dos adutos (RDKit)

Não usa internet: calcula a massa monoisotópica e os adutos mais comuns a
partir do que o perfil ADMET (quimio.py, RDKit) já computou para cada
composto. Serve de referência para derreplicação e para conferir os
espectros experimentais.

Registrada automaticamente por espectros.py (ver a seção 26 do README).
"""

import quimio as Q

FONTE = {
    "nome": "teoricos",
    "rotulo": "m/z teóricos (RDKit)",
    "rede": False,
    "padrao": True,
    "ordem": 10,          # primeiro: não depende de rede
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def coletar(compostos, contexto: dict) -> list:
    admet = contexto.get("admet")
    if admet is None or admet.empty or "inchikey" not in admet.columns:
        return []
    linhas = []
    for _, r in admet.iterrows():
        ik = r.get("inchikey")
        mono = _num(r.get("massa_monoisotopica_rdkit"))
        if not ik or mono is None:
            continue
        adutos = [("[M] (massa monoisotópica)", mono)]
        # adutos só fazem sentido para a molécula neutra
        if _num(r.get("carga_formal")) == 0:
            adutos += [("[M+H]+", round(mono + Q.MASSA_PROTON, Q.PRECISAO)),
                       ("[M+Na]+", round(mono + Q.MASSA_NA, Q.PRECISAO)),
                       ("[M-H]-", round(mono - Q.MASSA_PROTON, Q.PRECISAO))]
        for rotulo, valor in adutos:
            linhas.append({"inchikey": ik, "origem": "teórico",
                           "tipo": "Mass Spectrometry (m/z teórico)",
                           "subtipo": rotulo, "valor": valor,
                           "descricao": f"{rotulo} = {valor}", "fonte": "RDKit"})
    return linhas
