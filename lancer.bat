@echo off
setlocal
REM Lance le tableau de bord sous Windows. Double-cliquer sur ce fichier suffit :
REM l'environnement est cree au premier lancement, reutilise ensuite.

cd /d "%~dp0"
title Tableau de bord d'audience

REM Le lanceur "py" est installe par python.org et pointe toujours sur un vrai
REM Python. La commande "python", elle, peut renvoyer vers l'alias du Microsoft
REM Store, qui ouvre la boutique au lieu d'executer quoi que ce soit.
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if not defined PY (
  python --version >nul 2>&1 && set PY=python
)

if not defined PY (
  echo.
  echo   Python n'a pas ete trouve.
  echo.
  echo   A installer depuis https://www.python.org/downloads/
  echo   IMPORTANT : cocher "Add Python to PATH" pendant l'installation,
  echo   puis fermer cette fenetre et relancer ce fichier.
  echo.
  pause
  exit /b 1
)

echo   Python detecte : %PY%
%PY% --version

if not exist .venv (
  echo.
  echo   Premiere installation, comptez deux minutes...
  %PY% -m venv .venv
  if errorlevel 1 goto erreur
)

call .venv\Scripts\activate.bat
if errorlevel 1 goto erreur

python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if errorlevel 1 goto erreur

if not exist data mkdir data

echo.
echo   ================================================================
echo     Le tableau de bord s'ouvre dans le navigateur.
echo     LAISSER CETTE FENETRE OUVERTE pendant l'utilisation.
echo     La fermer arrete l'outil.
echo   ================================================================
echo.

python -m streamlit run app.py --server.headless false
if errorlevel 1 goto erreur

endlocal
exit /b 0

:erreur
echo.
echo   ----------------------------------------------------------------
echo     Quelque chose a echoue. Le message d'erreur est juste au-dessus.
echo     Le copier et le transmettre permet de diagnostiquer.
echo   ----------------------------------------------------------------
echo.
pause
exit /b 1
