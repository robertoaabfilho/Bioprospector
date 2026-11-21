@echo off
REM ==========================================================================
REM painel.bat - painel interativo do pipeline (Windows)
REM
REM   mods\painel.bat                     abre o painel neste prompt (Ctrl+C fecha)
REM   mods\painel.bat --abrir             abre sem prender o prompt (o que o icone faz)
REM   mods\painel.bat atalho              cria o atalho "Painel do pipeline" na pasta
REM                                       do projeto e na area de trabalho
REM   mods\painel.bat --server.port 8502  outra porta (qualquer opcao do streamlit run)
REM
REM Pelo painel tambem da para rodar o pipeline, iniciar o Ollama e acompanhar
REM a GPU (pagina "Rodar o pipeline"). Para fechar o painel aberto pelo atalho:
REM Configuracoes -> Fechar o painel.
REM ==========================================================================
setlocal
cd /d "%~dp0.."
REM (acima: raiz do projeto - este arquivo fica em mods\)
REM ambiente do Windows: .venv-win (pasta compartilhada com o Linux) ou .venv
set "PY="
if exist ".venv-win\Scripts\python.exe" set "PY=.venv-win\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
    if not defined PY set "PY=python"
)
set PYTHONUTF8=1

"%PY%" -c "import streamlit, sys; v = tuple(int(x) for x in streamlit.__version__.split('.')[:2]); sys.exit(v < (1, 50))" >nul 2>&1
if errorlevel 1 (
    echo Instalando o streamlit ^(so na primeira vez; precisa de internet^)...
    "%PY%" -m pip install --quiet --upgrade "streamlit>=1.50"
    if errorlevel 1 (
        echo ERRO: nao foi possivel instalar o streamlit. Rode mods\instalar.bat e tente de novo.
        exit /b 1
    )
)

if /i "%~1"=="atalho" (
    "%PY%" mods\abrir_painel.py atalho
    goto :fim
)
if /i "%~1"=="--abrir" (
    "%PY%" mods\abrir_painel.py
    goto :fim
)
echo Abrindo o painel em http://localhost:8501  (Ctrl+C para fechar)
"%PY%" -m streamlit run mods\painel.py --browser.gatherUsageStats false %*
:fim
endlocal
