"""Outillage d'analyse d'audience éditoriale.

`parsers` lit les exports (Search Console, CMS), `metrics` calcule les mesures
du diagnostic. L'interface Streamlit se trouve dans `app.py`, à la racine.
"""

from .parsers import (
    ExportGSC,
    charger_articles,
    charger_dossier_gsc,
    charger_gsc,
    charger_redirections,
    decoupe_url,
    section,
    to_number,
)
from .metrics import (
    RELANCES_MAX,
    SEUIL_CARTON,
    Relance,
    chaines_de_redirection,
    compare_sites,
    concentration,
    detecte_relances,
    evolution_annuelle,
    poids_des_sections,
    profil_cartons,
    reservoir,
    serie_mensuelle,
    stock_et_flux,
    sujets_communs,
    synthese_relances,
)

__all__ = [
    "ExportGSC",
    "RELANCES_MAX",
    "Relance",
    "SEUIL_CARTON",
    "charger_articles",
    "charger_dossier_gsc",
    "chaines_de_redirection",
    "charger_gsc",
    "charger_redirections",
    "compare_sites",
    "concentration",
    "decoupe_url",
    "detecte_relances",
    "evolution_annuelle",
    "poids_des_sections",
    "profil_cartons",
    "reservoir",
    "section",
    "serie_mensuelle",
    "stock_et_flux",
    "sujets_communs",
    "synthese_relances",
    "to_number",
]
