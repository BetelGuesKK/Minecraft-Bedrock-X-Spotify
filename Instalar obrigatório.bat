@echo off
chcp 65001 >nul
cd /d "%~dp0fontes"
echo ==================================================
echo  DePola Lyrics - instalacao (so precisa fazer UMA vez)
echo ==================================================
echo.
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  python --version >nul 2>&1 && set PY=python
)
if not defined PY (
  echo Python nao encontrado. Tentando instalar automaticamente...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Se a instalacao terminou, FECHE esta janela e abra "Instalar obrigatório" de novo.
  echo Se deu erro, instale o Python manualmente em https://www.python.org/downloads/
  echo ^(marque "Add python.exe to PATH"^) e abra este arquivo de novo.
  echo.
  pause
  exit /b 1
)
echo Instalando os pacotes que leem o Spotify do Windows...
%PY% -m pip install winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Storage.Streams
if errorlevel 1 (
  echo.
  echo [ERRO] A instalacao falhou. Veja a mensagem acima.
  pause
  exit /b 1
)
echo.
echo ==================================================
echo  PRONTO! Agora use o "Iniciar Spotify".
echo ==================================================
pause
