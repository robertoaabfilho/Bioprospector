#!/usr/bin/env bash
# =============================================================================
# graficos.sh - gráficos dos resultados do pipeline (Linux / macOS)
#
#   mods/graficos.sh                         todos os gráficos possíveis
#   mods/graficos.sh --parcial               etapa 5 a partir dos *_parcial.csv
#   mods/graficos.sh --etapas plantas,pubmed só algumas etapas
#   mods/graficos.sh --top 40 --formato svg  rankings maiores; arquivos em SVG
#
# Resultado: resultados/graficos/relatorio.html (abra no navegador), um arquivo por
# gráfico e resultados/graficos/dados/ com a tabela de cada um.
# Não altera nada do pipeline e não acessa a internet (só para instalar o
# matplotlib no .venv, na primeira vez).
# =============================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/.."   # raiz do projeto (este arquivo fica em mods/)

# ambiente do Linux: .venv-linux (pasta compartilhada com o Windows) ou .venv
if [ -x ".venv-linux/bin/python" ]; then
    PY=".venv-linux/bin/python"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    PY="python"
fi

if ! "$PY" -c "import matplotlib" >/dev/null 2>&1; then
    echo "Instalando o matplotlib (só na primeira vez)..."
    if [ "$PY" = ".venv/bin/python" ] || [ "$PY" = ".venv-linux/bin/python" ]; then
        "$PY" -m pip install --quiet "matplotlib>=3.6"
    else
        echo "AVISO: sem o .venv do pipeline; tentando instalar para o usuário."
        "$PY" -m pip install --user --quiet "matplotlib>=3.6" || {
            echo "ERRO: não foi possível instalar o matplotlib. Rode mods/instalar.sh e tente de novo."
            exit 1; }
    fi
fi

export PYTHONUNBUFFERED=1
exec "$PY" mods/graficos.py "$@"
