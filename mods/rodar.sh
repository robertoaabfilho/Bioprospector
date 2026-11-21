#!/usr/bin/env bash
# =============================================================================
# rodar.sh - lançador do pipeline (Linux / macOS)
#
#   mods/rodar.sh                          pipeline completo
#   mods/rodar.sh --a-partir-de pubmed     qualquer opção do mods/main.py
#   mods/rodar.sh --somente gbif --gbif-chave 0021558-...   usa um download do GBIF já feito
#   mods/rodar.sh config                   confere o config/input.txt
#   mods/rodar.sh diagnostico              resumo da etapa pubmed (diagnostico_pubmed.txt)
#   mods/rodar.sh parcial                  planilhas com o que o modelo já leu
#   mods/rodar.sh credenciais              confere/preenche config/credenciais.txt
#   mods/rodar.sh organizar                organiza a pasta (uma vez; ver mods/organizar_pasta.py)
#
# Para ver os resultados: mods/graficos.sh (relatório de gráficos) e mods/painel.sh (ou o ícone)
# (painel interativo no navegador).
#
# O que ele faz antes de chamar o Python:
#   - entra na pasta do projeto (pode ser chamado de qualquer lugar);
#   - usa o ambiente virtual .venv, se existir (criado pelo instalar.sh).
# As credenciais (config/credenciais.txt) são lidas pelo próprio pipeline.
# =============================================================================
set -euo pipefail
export PIPELINE_CWD="$PWD"     # para --input com caminho relativo à pasta de onde foi chamado
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

export PYTHONUNBUFFERED=1     # mostra o progresso na hora, também em logs (nohup/tee)

case "${1:-}" in
    config)       shift; exec "$PY" mods/config_pipeline.py "$@" ;;
    diagnostico)  shift; exec "$PY" mods/diagnostico_pubmed.py "$@" ;;
    parcial)      shift; exec "$PY" mods/consultar_atividades_pubmed.py --parcial "$@" ;;
    credenciais)  shift; exec "$PY" mods/credenciais.py "$@" ;;
    organizar)    shift; exec "$PY" mods/organizar_pasta.py "$@" ;;
    *)            exec "$PY" mods/main.py "$@" ;;
esac
