#!/usr/bin/env bash
# Lance le tableau de bord sur un Mac. Double-cliquer sur ce fichier suffit :
# l'environnement est créé au premier lancement, réutilisé ensuite.
#
# Si macOS refuse de l'ouvrir, exécuter une fois dans le Terminal :
#   chmod +x lancer.command

set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo
  echo "  Python 3 n'est pas installé."
  echo "  À télécharger sur https://www.python.org/downloads/ puis relancer."
  echo
  read -r -p "  Appuyer sur Entrée pour fermer." _
  exit 1
fi

if [ ! -d .venv ]; then
  echo "  Première installation, comptez deux minutes…"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

mkdir -p data
echo
echo "  Le tableau de bord s'ouvre dans le navigateur."
echo "  Laisser cette fenêtre ouverte tant qu'on s'en sert ; la fermer arrête l'outil."
echo
exec streamlit run app.py --server.headless false
