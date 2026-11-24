@echo off
chcp 65001 >nul
cd /d "%~dp0fontes"
echo === DePola Lyrics - ponte Spotify ===
echo.
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  python --version >nul 2>&1 && set PY=python
)
if not defined PY (
  echo [ERRO] Python nao encontrado. Rode primeiro o "Instalar obrigatório".
  pause
  exit /b 1
)
%PY% depola_spotify.py
echo.
echo O programa terminou. Se apareceu algum ERRO acima, leia a mensagem.
pause
