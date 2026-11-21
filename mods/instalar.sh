#!/usr/bin/env bash
# =============================================================================
# instalar.sh - prepara o pipeline no Linux / macOS (rode uma vez)
#
#   mods/instalar.sh
#
# 1. confere o Python (3.10 ou mais recente);
# 2. cria o ambiente virtual .venv e instala os pacotes de mods/requirements.txt
#    (evita o erro "externally-managed-environment" do Ubuntu/Debian recentes);
# 3. confere o Ollama e o modelo do config/input.txt;
# 4. cria config/credenciais.txt (o mesmo arquivo serve para todos os sistemas).
# =============================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")/.."   # raiz do projeto (este arquivo fica em mods/)

echo "== Python =="
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERRO: python3 não encontrado. Ubuntu/Debian: sudo apt install python3 python3-venv"
    exit 1
fi
python3 - <<'PYEOF'
import sys
if sys.version_info < (3, 10):
    sys.exit(f"ERRO: Python {sys.version.split()[0]} é antigo; o pipeline precisa de 3.10 ou mais recente.")
print(f"Python {sys.version.split()[0]} - ok")
PYEOF

echo
# pasta compartilhada com o Windows: se a .venv for do Windows, usa .venv-linux
VENV=".venv"
if { [ -d ".venv/Scripts" ] && [ ! -x ".venv/bin/python" ]; } || [ -x ".venv-linux/bin/python" ]; then
    VENV=".venv-linux"
fi
echo "== Ambiente virtual (${VENV}) e pacotes =="
if [ ! -x "${VENV}/bin/python" ]; then
    if ! python3 -m venv "${VENV}" 2>/dev/null; then
        echo "ERRO: não foi possível criar o ambiente virtual."
        echo "  Ubuntu/Debian: sudo apt install python3-venv   (depois rode mods/instalar.sh de novo)"
        exit 1
    fi
fi
"${VENV}/bin/python" -m pip install --upgrade pip >/dev/null
"${VENV}/bin/python" -m pip install -r mods/requirements.txt
echo "pacotes instalados em ${VENV} - ok"
# RDKit (recomendado): conferência de SMILES, recálculo de InChIKey, detecção de
# conflitos de estrutura (etapa normalizacao) e perfil ADMET (etapa banco)
if "${VENV}/bin/python" -c "import rdkit" >/dev/null 2>&1 || \
        "${VENV}/bin/python" -m pip install --quiet rdkit; then
    echo "RDKit (recomendado) - ok"
else
    echo "AVISO: RDKit não instalado - sem ele não há recálculo de InChIKey, perfil ADMET"
    echo "       (banco/perfil_admet.csv) nem detecção de conflitos de estrutura."
fi

if [ ! -f config/input.txt ] && [ -f config/input.txt.exemplo ]; then
    cp config/input.txt.exemplo config/input.txt
    echo
    echo "Criado config/input.txt a partir do modelo - ajuste região, lista e atividades."
fi

echo
echo "== Ollama (necessário para a etapa pubmed) =="
MODELO="$("${VENV}/bin/python" - <<'PYEOF' 2>/dev/null || echo "qwen3.5:35b-a3b"
import sys; sys.path.insert(0, "mods")
from config_pipeline import carregar_config_ollama
print(carregar_config_ollama()["modelo"])
PYEOF
)"
if command -v ollama >/dev/null 2>&1; then
    echo "Ollama instalado."
    if ollama list 2>/dev/null | awk '{print $1}' | grep -qx -e "${MODELO}" -e "${MODELO}:latest"; then
        echo "modelo ${MODELO} - ok"
    else
        echo "Modelo ${MODELO} ainda não baixado. Rode:  ollama pull ${MODELO}"
    fi
else
    echo "Ollama não encontrado. Para instalar:"
    echo "  curl -fsSL https://ollama.com/install.sh | sh"
    echo "  ollama pull ${MODELO}"
fi

echo
echo "== Credenciais (config/credenciais.txt) =="
if [ ! -f config/credenciais.txt ]; then
    "${VENV}/bin/python" - <<'PYEOF'
import sys; sys.path.insert(0, "mods")
import credenciais
credenciais.criar_modelo()   # aproveita gbif_credenciais.env/.bat antigos, se houver
PYEOF
    echo "Criado config/credenciais.txt - abra e preencha (ou deixe o pipeline perguntar na hora)."
else
    echo "config/credenciais.txt encontrado - ok"
fi
chmod 600 config/credenciais.txt 2>/dev/null || true


chmod +x mods/*.sh 2>/dev/null || true
echo
echo "Pronto. Próximos passos:"
echo "  mods/rodar.sh config      # confere o config/input.txt"
echo "  mods/rodar.sh             # roda o pipeline"
