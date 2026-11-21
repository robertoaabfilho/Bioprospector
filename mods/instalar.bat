@echo off
REM ==========================================================================
REM instalar.bat - prepara o pipeline no Windows (rode uma vez)
REM
REM 1. acha o Python 3.10+ (lancador "py" ou "python"; ignora o atalho falso
REM    da Microsoft Store);
REM 2. cria o ambiente virtual e instala os pacotes de requirements.txt;
REM 3. cria config\input.txt e config\credenciais.txt, se faltarem.
REM
REM Ambiente virtual: .venv. Se a pasta for compartilhada com o Linux e a .venv
REM for do Linux, usa .venv-win (cada sistema fica com o seu).
REM ==========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0.."
REM (acima: raiz do projeto - este arquivo fica em mods\)

echo == Python ==
set "PYBASE="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PYBASE=py -3"
if not defined PYBASE (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PYBASE=python"
)
if not defined PYBASE (
    echo ERRO: Python 3.10 ou mais recente nao encontrado.
    echo   Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH".
    echo   Se "python" abre a Microsoft Store: Configuracoes ^> Aplicativos ^> Aliases de
    echo   execucao de aplicativo ^> desligue "python.exe" e "python3.exe".
    exit /b 1
)
%PYBASE% --version

set "VENV=.venv"
if exist ".venv\bin\python" if not exist ".venv\Scripts\python.exe" set "VENV=.venv-win"
if exist ".venv-win\Scripts\python.exe" set "VENV=.venv-win"

echo.
echo == Ambiente virtual (%VENV%) e pacotes ==
if not exist "%VENV%\Scripts\python.exe" (
    %PYBASE% -m venv "%VENV%"
    if errorlevel 1 ( echo ERRO: nao foi possivel criar o ambiente virtual %VENV%. & exit /b 1 )
)
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
"%VENV%\Scripts\python.exe" -m pip install -r mods\requirements.txt
if errorlevel 1 (
    echo ERRO: a instalacao dos pacotes falhou - veja a mensagem acima. Confira a internet
    echo   ^(ou o proxy da rede^) e rode instalar.bat de novo.
    exit /b 1
)
echo pacotes instalados em %VENV% - ok
REM RDKit (recomendado): conferencia de SMILES, recalculo de InChIKey, conflitos
REM de estrutura (etapa normalizacao) e perfil ADMET (etapa banco)
"%VENV%\Scripts\python.exe" -c "import rdkit" >nul 2>nul || "%VENV%\Scripts\python.exe" -m pip install --quiet rdkit
"%VENV%\Scripts\python.exe" -c "import rdkit" >nul 2>nul && (echo RDKit ^(recomendado^) - ok) || (echo AVISO: RDKit nao instalado - sem ele nao ha recalculo de InChIKey, perfil ADMET nem deteccao de conflitos de estrutura.)

if not exist "config\input.txt" if exist "config\input.txt.exemplo" (
    copy "config\input.txt.exemplo" "config\input.txt" >nul
    echo Criado config\input.txt a partir do modelo.
)
if not exist "config\credenciais.txt" (
    "%VENV%\Scripts\python.exe" -c "import sys; sys.path.insert(0, 'mods'); import credenciais; credenciais.criar_modelo()"
    echo Criado config\credenciais.txt - abra e preencha, ou deixe o pipeline perguntar na hora.
)

echo.
echo == Ollama ^(necessario para a etapa pubmed^) ==
where ollama >nul 2>nul && (echo Ollama instalado.) || (echo Ollama nao encontrado: instale em https://ollama.com/download e rode: ollama pull qwen3.5:35b-a3b)

echo.
echo Pronto. Proximos passos:  mods\rodar.bat config   e depois   mods\rodar.bat   ^(ou o painel: mods\painel.bat atalho^)
endlocal
