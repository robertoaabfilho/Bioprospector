"""
caminhos.py - onde fica cada coisa na pasta do pipeline

    <projeto>/
        Painel do pipeline (Linux).desktop / (Windows).lnk   ícones do painel
        config/       input.txt, lista_de_plantas.txt, credenciais.txt
        mods/         programas (.py), lançadores (.sh/.bat), README.md
        dados/        bases baixadas (bioativos/, chembl/, flora_brasil/,
                      gbif_download/, wcvp/, wfo/) e bases_baixadas.txt
        cache/        caches das consultas (cache_*.jsonl)
        resultados/   planilhas (.csv), banco/, graficos/ e registros (logs/)

Sem efeitos colaterais: só define caminhos. Quem muda a pasta de trabalho
para resultados/ é o config_pipeline.py.
"""
import os
from pathlib import Path

MODS = Path(__file__).resolve().parent
RAIZ = MODS.parent
CONFIG = RAIZ / "config"
DADOS = RAIZ / "dados"
CACHE = RAIZ / "cache"
RESULTADOS = RAIZ / "resultados"
LOGS = RESULTADOS / "logs"

# pastas das bases dentro de dados/ (antes: dados_<nome>/ na raiz)
PASTAS_DADOS = {
    "dados_bioativos": "bioativos",
    "dados_chembl": "chembl",
    "dados_flora_brasil": "flora_brasil",
    "dados_gbif_download": "gbif_download",
    "dados_wcvp": "wcvp",
    "dados_wfo": "wfo",
}


def cache(nome: str) -> str:
    """Caminho de um cache: cache/<nome>."""
    return str(CACHE / nome)


def dados(*partes: str) -> str:
    """Caminho dentro de dados/: dados('bioativos', 'duke_csv.zip')."""
    return str(DADOS.joinpath(*partes))


def layout_antigo() -> list[str]:
    """Arquivos do layout antigo (tudo na raiz) que ainda não foram movidos."""
    if not RAIZ.is_dir():
        return []
    soltos = []
    for nome in os.listdir(RAIZ):
        if ((nome.startswith("cache_") and nome.endswith((".jsonl", ".json")))
                or nome in PASTAS_DADOS or nome in ("plantas.csv", "especies_gbif.csv", "banco")):
            soltos.append(nome)
    return sorted(soltos)


def criar_pastas():
    for p in (DADOS, CACHE, RESULTADOS):
        p.mkdir(parents=True, exist_ok=True)
