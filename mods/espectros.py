"""
espectros.py  -  REGISTRO DAS FONTES DE DADOS ESPECTRAIS (etapa "banco")

Este arquivo é o ponto de extensão da camada espectral do banco. Ele não
conhece nenhuma fonte: descobre sozinho, na pasta mods/, todo módulo chamado
`espectros_<nome>.py` que declare um dicionário FONTE e uma função coletar().

    Para acrescentar o GNPS, o MassBank, o MoNA ou qualquer outra fonte,
    NÃO é preciso editar nenhum arquivo já existente: basta criar o módulo
    mods/espectros_<nome>.py. Veja o guia na seção 26 do README e o modelo
    comentado em mods/espectros_exemplo.py.

Fontes já registradas (cada uma no seu módulo):
    espectros_teoricos.py   m/z teóricos dos adutos (RDKit, sem internet)
    espectros_pubchem.py    espectros experimentais compilados no PubChem
    espectros_exemplo.py    modelo para uma fonte nova (desligado por padrão)

A INTERFACE de uma fonte (o que o módulo precisa expor)
-------------------------------------------------------
FONTE = {
    "nome":   "gnps",            # vira a chave [banco] espectros_gnps
    "rotulo": "GNPS (MS/MS)",    # como aparece na tela
    "rede":   True,              # usa internet?
    "padrao": True,              # ligada quando a chave não está no input.txt
    "ordem":  30,                # ordem de coleta (menor primeiro)
}

def coletar(compostos, contexto) -> list[dict]:
    '''compostos: DataFrame com uma linha por composto (inchikey,
       pubchem_cid, smiles_canonico, formula_molecular...), JÁ recortado
       para a região quando [banco] enriquecer_apenas_regiao = true.
       contexto: dict com
           "admet"      DataFrame do perfil ADMET (massas, carga formal)
           "iks_regiao" set de InChIKeys da região, ou None
           "cfg"        seção [banco] do input.txt
       Devolve uma lista de dicionários com as colunas de dados_espectrais
       (sem id_espectro, que este registro numera).'''

Regras que o registro garante a cada fonte
------------------------------------------
- a fonte só é chamada se a chave [banco] espectros_<nome> estiver ligada;
- uma fonte que levanta exceção não derruba a etapa: vira aviso e as outras
  seguem (mesma regra das bases complementares da etapa "bioativos");
- os identificadores ES0000001... são atribuídos aqui, em ordem estável;
- a coluna `fonte` de cada registro, se a fonte não a preencher, recebe o
  rótulo da fonte.
"""

import importlib
import os
import pkgutil

PREFIXO = "espectros_"
CAMPOS_FONTE = ("nome", "rotulo")


def _modulos() -> list:
    """Módulos mods/espectros_*.py, em ordem alfabética (estável)."""
    pasta = os.path.dirname(os.path.abspath(__file__))
    return sorted(m.name for m in pkgutil.iter_modules([pasta])
                  if m.name.startswith(PREFIXO))


def fontes() -> list:
    """[(FONTE, função coletar)] das fontes válidas, na ordem de coleta."""
    achadas = []
    for nome_mod in _modulos():
        try:
            mod = importlib.import_module(nome_mod)
        except Exception as e:      # módulo quebrado não derruba os outros
            print(f"  AVISO: fonte espectral {nome_mod} não pôde ser carregada ({e})")
            continue
        meta, coletar = getattr(mod, "FONTE", None), getattr(mod, "coletar", None)
        if not isinstance(meta, dict) or not callable(coletar):
            continue                # módulo auxiliar, sem a interface
        if any(not meta.get(c) for c in CAMPOS_FONTE):
            print(f"  AVISO: {nome_mod}.FONTE sem {' / '.join(CAMPOS_FONTE)} - ignorada")
            continue
        achadas.append((meta, coletar))
    return sorted(achadas, key=lambda f: (f[0].get("ordem", 50), f[0]["nome"]))


def ligada(meta: dict, cfg: dict) -> bool:
    """A fonte está ligada no input.txt? Chave: [banco] espectros_<nome>."""
    return bool(cfg.get(f"{PREFIXO}{meta['nome']}", meta.get("padrao", True)))


def coletar_tudo(compostos, contexto: dict) -> list:
    """Chama cada fonte ligada e devolve os registros, já numerados."""
    cfg = contexto.get("cfg") or {}
    linhas, n = [], 0
    for meta, coletar in fontes():
        if not ligada(meta, cfg):
            print(f"  {meta['rotulo']}: desligada ([banco] "
                  f"{PREFIXO}{meta['nome']} = false)")
            continue
        try:
            novas = coletar(compostos, contexto) or []
        except Exception as e:      # fonte indisponível: a etapa segue sem ela
            print(f"  AVISO: {meta['rotulo']} indisponível ({e}) - seguindo sem esta fonte.")
            continue
        for registro in novas:
            n += 1
            registro.setdefault("fonte", meta["rotulo"])
            linhas.append({"id_espectro": f"ES{n:07d}", **registro})
        print(f"  {meta['rotulo']}: {len(novas)} registro(s)")
    return linhas


def resumo() -> str:
    """Uma linha com as fontes descobertas (para a tela e o diagnóstico)."""
    nomes = [m["rotulo"] for m, _ in fontes()]
    return ", ".join(nomes) if nomes else "(nenhuma)"
