@echo off
REM ==========================================================================
REM rodar.bat - lancador do pipeline (Windows, Prompt de Comando)
REM
REM   mods\rodar.bat                          pipeline completo
REM   mods\rodar.bat --a-partir-de pubmed     qualquer opcao do mods\main.py
REM   mods\rodar.bat --somente gbif --gbif-chave 0021558-...   usa um download do GBIF ja feito
REM   mods\rodar.bat config                   confere o config\input.txt
REM   mods\rodar.bat diagnostico              resumo da etapa pubmed
REM   mods\rodar.bat parcial                  planilhas com o que o modelo ja leu
REM   mods\rodar.bat credenciais              confere/preenche config\credenciais.txt
REM
REM Para ver os resultados: graficos.bat (relatorio de graficos) e painel.bat
REM (painel interativo no navegador).
REM
REM Usa o ambiente .venv, se existir. As credenciais (config\credenciais.txt)
REM sao lidas pelo proprio pipeline.
REM ==========================================================================
setlocal
set "PIPELINE_CWD=%CD%"
cd /d "%~dp0.."
REM (acima: raiz do projeto - este arquivo fica em mods\)
REM ambiente do Windows: .venv-win (pasta compartilhada com o Linux) ou .venv
set "PY="
if exist ".venv-win\Scripts\python.exe" set "PY=.venv-win\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    echo AVISO: ambiente virtual nao encontrado - rode instalar.bat. Usando o Python do sistema.
    where py >nul 2>nul && set "PY=py"
    if not defined PY set "PY=python"
)
set PYTHONUNBUFFERED=1
set PYTHONUTF8=1
set "SUB="
if /i "%~1"=="config" set "SUB=mods\config_pipeline.py"
if /i "%~1"=="diagnostico" set "SUB=mods\diagnostico_pubmed.py"
if /i "%~1"=="parcial" set "SUB=mods\consultar_atividades_pubmed.py --parcial"
if /i "%~1"=="credenciais" set "SUB=mods\credenciais.py"
if /i "%~1"=="organizar" set "SUB=mods\organizar_pasta.py"
if not defined SUB (
    "%PY%" mods\main.py %*
    goto :fim
)
REM subcomando: repassa os argumentos que vierem depois dele
set "RESTO="
shift
:junta
if "%~1"=="" goto :roda
set RESTO=%RESTO% %1
shift
goto :junta
:roda
"%PY%" %SUB% %RESTO%
:fim
endlocal
