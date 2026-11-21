#!/usr/bin/env bash
# =============================================================================
# painel.sh - painel interativo do pipeline (Linux / macOS)
#
#   mods/painel.sh              abre o painel neste terminal (Ctrl+C fecha)
#   mods/painel.sh --abrir      abre sem prender o terminal (o que o ícone faz)
#   mods/painel.sh atalho       cria o ícone "Painel do pipeline" na pasta do
#                               projeto, no menu de aplicativos e na área de trabalho
#   mods/painel.sh --server.port 8502   outra porta (qualquer opção do streamlit run)
#
# Pelo painel também dá para rodar o pipeline, iniciar o Ollama e acompanhar a
# GPU (página "Rodar o pipeline"). Para fechar o painel aberto pelo ícone:
# Configurações -> Fechar o painel.
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

if ! "$PY" -c "import streamlit, sys; v = tuple(int(x) for x in streamlit.__version__.split('.')[:2]); sys.exit(v < (1, 50))" >/dev/null 2>&1; then
    echo "Instalando o streamlit (só na primeira vez; precisa de internet)..."
    if [ "$PY" = ".venv/bin/python" ] || [ "$PY" = ".venv-linux/bin/python" ]; then
        "$PY" -m pip install --quiet --upgrade "streamlit>=1.50"
    else
        "$PY" -m pip install --user --quiet --upgrade "streamlit>=1.50" || {
            echo "ERRO: não foi possível instalar o streamlit. Rode mods/instalar.sh e tente de novo."
            exit 1; }
    fi
fi

export PYTHONUTF8=1
case "${1:-}" in
    atalho)   exec "$PY" mods/abrir_painel.py atalho ;;
    --abrir)  exec "$PY" mods/abrir_painel.py ;;
esac
echo "Abrindo o painel em http://localhost:8501  (Ctrl+C para fechar)"
exec "$PY" -m streamlit run mods/painel.py --browser.gatherUsageStats false "$@"
