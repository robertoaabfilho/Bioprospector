#!/usr/bin/env bash
# =============================================================================
# organizar_pasta.sh - organiza a pasta do pipeline (Linux / macOS; uma vez)
#
#   mods/organizar_pasta.sh             mostra o plano e pergunta antes de mover
#   mods/organizar_pasta.sh --simular   só mostra o plano
#
# caches -> cache/, bases -> dados/, planilhas -> resultados/; o que não é
# mais necessário vai para _para_apagar/ (nada é apagado). Detalhes em
# mods/organizar_pasta.py.
# =============================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/.."   # raiz do projeto

if [ -x ".venv-linux/bin/python" ]; then
    PY=".venv-linux/bin/python"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    PY="python"
fi
exec "$PY" mods/organizar_pasta.py "$@"
