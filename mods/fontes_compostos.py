"""
fontes_compostos.py  -  REGISTRO DAS FONTES DE COMPOSTOS (etapa "bioativos")

Ponto de extensão da camada de compostos. Descobre, na pasta mods/, todo
módulo chamado `fonte_<nome>.py` que declare o dicionário FONTE e a função
cruzar(), e os entrega à etapa "bioativos" no mesmo formato das bases que já
vêm no pacote (Dr. Duke, LOTUS e FooDB).

    Para ligar o NPAtlas, o HMDB ou qualquer outra base de pares
    organismo-composto, NÃO é preciso editar nenhum arquivo já existente:
    crie mods/fonte_<nome>.py e ligue [bioativos] usar_<nome> = true.
    Veja a seção 26 do README e o modelo comentado em mods/fonte_exemplo.py.

A INTERFACE de uma fonte
------------------------
FONTE = {
    "nome":    "npatlas",          # vira a chave [bioativos] usar_npatlas
    "rotulo":  "NPAtlas",          # como aparece na tela
    "colunas": ["id_npatlas"],     # colunas extras que a fonte acrescenta
                                   # (podem ser [] se ela não acrescentar nenhuma)
    "padrao":  False,              # ligada quando a chave não está no input.txt
}

def baixar() -> None:
    '''Garante os arquivos da base em dados/bioativos/. Pode não fazer nada
       se a base for consultada por API.'''

def cruzar(casar, especies: dict, generos: dict) -> pandas.DataFrame:
    '''casar(nomes, especies, generos) -> pandas.Series
       Recebe uma Series com os nomes dos organismos da sua base e devolve,
       para cada um, a chave da planta-alvo ou "" quando o organismo não
       entra. É VETORIZADO (uma Series de cada vez, não um nome por chamada),
       e é nele que o pipeline aplica o recorte da região e o filtro de reino.
       Devolve um DataFrame com, no mínimo:
          especie_normalizada   o que casar() devolveu
          base                  sigla da fonte (ex.: "NPATLAS")
          composto_id, composto_nome, composto_inchikey
          atividade_ou_alvo     pode ficar vazio
       mais as colunas declaradas em FONTE["colunas"].'''

Reino dos organismos
--------------------
Uma fonte de organismos que NÃO são plantas (bactérias, fungos, metabólitos
humanos) só entra com [bioativos] reino = qualquer. Com o padrão
reino = vegetal, o filtro de reino descarta esses organismos antes de chegar
à fonte. Ver a seção 15.1 do README.
"""

import importlib
import os
import pkgutil

PREFIXO = "fonte_"
CAMPOS_FONTE = ("nome", "rotulo")


def _modulos() -> list:
    pasta = os.path.dirname(os.path.abspath(__file__))
    return sorted(m.name for m in pkgutil.iter_modules([pasta])
                  if m.name.startswith(PREFIXO))


def descobertas() -> list:
    """Fontes achadas em mods/fonte_*.py, no formato de FONTES_EXTRA:
    (chave_do_input, módulo, rótulo, colunas_extras, nome_da_função, padrão)."""
    achadas = []
    for nome_mod in _modulos():
        try:
            mod = importlib.import_module(nome_mod)
        except Exception as e:
            print(f"  AVISO: fonte de compostos {nome_mod} não pôde ser carregada ({e})")
            continue
        meta = getattr(mod, "FONTE", None)
        if not isinstance(meta, dict) or not callable(getattr(mod, "cruzar", None)):
            continue
        if any(not meta.get(c) for c in CAMPOS_FONTE):
            print(f"  AVISO: {nome_mod}.FONTE sem {' / '.join(CAMPOS_FONTE)} - ignorada")
            continue
        if not callable(getattr(mod, "baixar", None)):
            mod.baixar = lambda: None        # fonte por API: nada a baixar
        achadas.append((f"usar_{meta['nome']}", mod, meta["rotulo"],
                        list(meta.get("colunas") or []), "cruzar",
                        bool(meta.get("padrao", False))))
    return achadas


def resumo() -> str:
    nomes = [f[2] for f in descobertas()]
    return ", ".join(nomes) if nomes else "(nenhuma)"
