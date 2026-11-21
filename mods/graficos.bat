@echo off
REM ==========================================================================
REM graficos.bat - graficos dos resultados do pipeline (Windows)
REM
REM   mods\graficos.bat                          todos os graficos possiveis
REM   mods\graficos.bat --parcial                etapa 5 a partir dos *_parcial.csv
REM   mods\graficos.bat --etapas plantas,pubmed  so algumas etapas
REM   mods\graficos.bat --top 40 --formato svg   rankings maiores; arquivos em SVG
REM
REM Resultado: graficos\relatorio.html (abra no navegador), um arquivo por
REM grafico e graficos\dados\ com a tabela de cada um.
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
set PYTHONUNBUFFERED=1
set PYTHONUTF8=1

"%PY%" -c "import matplotlib" >nul 2>&1
if errorlevel 1 (
    echo Instalando o matplotlib ^(so na primeira vez^)...
    "%PY%" -m pip install --quiet "matplotlib>=3.6"
    if errorlevel 1 (
        echo ERRO: nao foi possivel instalar o matplotlib. Rode instalar.bat e tente de novo.
        exit /b 1
    )
)

"%PY%" mods\graficos.py %*
endlocal
