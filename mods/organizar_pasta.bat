@echo off
REM ==========================================================================
REM organizar_pasta.bat - organiza a pasta do pipeline (Windows; uma vez)
REM
REM   mods\organizar_pasta.bat             mostra o plano e pergunta antes de mover
REM   mods\organizar_pasta.bat --simular   so mostra o plano
REM
REM caches -> cache\, bases -> dados\, planilhas -> resultados\; o que nao e
REM mais necessario vai para _para_apagar\ (nada e apagado).
REM ==========================================================================
setlocal
cd /d "%~dp0.."
set "PY="
if exist ".venv-win\Scripts\python.exe" set "PY=.venv-win\Scripts\python.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
    if not defined PY set "PY=python"
)
set PYTHONUTF8=1
"%PY%" mods\organizar_pasta.py %*
endlocal
