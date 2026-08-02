@echo off
REM Lance le tableau de bord sous Windows. Double-cliquer sur ce fichier suffit :
REM l'environnement est cree au premier lancement, reutilise ensuite.

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python n'est pas installe.
  echo   A telecharger sur https://www.python.org/downloads/
  echo   Cocher "Add Python to PATH" pendant l'installation, puis relancer.
  echo.
  pause
  exit /b 1
)

if not exist .venv (
  echo   Premiere installation, comptez deux minutes...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if not exist data mkdir data
echo.
echo   Le tableau de bord s'ouvre dans le navigateur.
echo   Laisser cette fenetre ouverte tant qu'on s'en sert ; la fermer arrete l'outil.
echo.
streamlit run app.py --server.headless false
pause
