"""Lecture des exports Marfeel filtrés par source d'acquisition.

Marfeel exporte un fichier par canal : un filtre est appliqué avant l'export, et
**le CSV ne contient aucune colonne indiquant lequel**. L'information n'existe
que dans le nom du fichier. C'est fragile, mais c'est tout ce qu'on a — d'où la
convention de nommage ci-dessous, et la possibilité de corriger à la main ce que
la détection automatique aurait mal deviné.

Convention : `<site><canal><année>.csv`, par exemple `jdgdiscover2025.csv` ou
`pc-direct-2026.csv`. Les séparateurs et la casse sont libres.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

import pandas as pd

from .parsers import to_number

# Un canal peut s'écrire de plusieurs façons selon qui a nommé le fichier.
CANAUX: dict[str, tuple[str, ...]] = {
    "Discover": ("discover", "googlediscover"),
    "Search": ("google", "search", "googlesearch", "organic"),
    "direct": ("direct",),
    "Google News": ("news", "googlenews", "actualites"),
    "dark social": ("dark", "darksocial", "social"),
    "Bing": ("bing",),
}

SITES: dict[str, tuple[str, ...]] = {
    "Journal du Geek": ("jdg", "journaldugeek", "geek"),
    "Presse-citron": ("pc", "pressecitron", "presse-citron", "citron"),
}


def _normalise(nom: str) -> str:
    """Nom de fichier réduit à des lettres et des chiffres, sans accent."""
    plat = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    # Les téléversements préfixent le nom d'un identifiant : on le retire.
    plat = re.sub(r"^[0-9a-f]{6,}-", "", plat.lower())
    return re.sub(r"[^a-z0-9]", "", plat)


def devine_origine(chemin: str | Path) -> tuple[str | None, str | None, str | None]:
    """Déduit (site, canal, année) du nom de fichier. `None` si indéterminé."""
    base = _normalise(Path(chemin).name.rsplit(".csv", 1)[0])

    site = next((nom for nom, alias in SITES.items()
                 if any(a in base for a in alias)), None)
    # « googlediscover » contient « google » : on teste les libellés les plus
    # spécifiques en premier.
    canal = None
    for nom, alias in sorted(CANAUX.items(), key=lambda kv: -max(len(a) for a in kv[1])):
        if any(a in base for a in alias):
            canal = nom
            break
    annee = next((a for a in re.findall(r"20\d{2}", base)), None)
    return site, canal, annee


def charger_marfeel(*chemins: str | Path,
                    origines: dict[str, tuple[str, str]] | None = None) -> pd.DataFrame:
    """Charge un ou plusieurs exports Marfeel en une seule table.

    `origines` permet de corriger la détection : `{"monfichier.csv": ("Journal
    du Geek", "Discover")}`.

    Colonnes produites : site, canal, date, semaine, visiteurs, pages_vues,
    engagement_s, pages_par_visiteur.
    """
    origines = origines or {}
    lignes = []
    for chemin in chemins:
        chemin = Path(chemin)
        site, canal, _ = devine_origine(chemin)
        if chemin.name in origines:
            site, canal = origines[chemin.name]
        with open(chemin, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                date = str(r.get("date", "")).strip()
                if not date.startswith("20"):
                    continue          # ignore la ligne « Total » et les en-têtes
                lignes.append({
                    "site": site or "inconnu",
                    "canal": canal or "inconnu",
                    "fichier": chemin.name,
                    "date": date[:10],
                    "visiteurs": to_number(r.get("uniqueUsers")),
                    "pages_vues": to_number(r.get("pageViewsTotal")),
                    "engagement_s": to_number(r.get("averageEngagementTimePerUser")),
                })
    if not lignes:
        return pd.DataFrame()

    df = pd.DataFrame(lignes)
    df["mois"] = df["date"].str[:7]
    df["annee"] = df["date"].str[:4]
    df["pages_par_visiteur"] = (df["pages_vues"] / df["visiteurs"]).where(df["visiteurs"] > 0)

    # Marfeel bascule en semaines dès que la plage dépasse quelques mois. Mélanger
    # les deux granularités additionnerait les mêmes journées plusieurs fois : on
    # marque chaque fichier pour pouvoir les séparer ensuite.
    ecarts = (
        df.assign(_d=pd.to_datetime(df["date"]))
          .sort_values("_d")
          .groupby("fichier")["_d"]
          .apply(lambda s: s.diff().dt.days.median())
    )
    df["granularite"] = df["fichier"].map(
        lambda f: "jour" if (pd.isna(ecarts.get(f)) or ecarts.get(f, 7) <= 2) else "semaine"
    )
    return df.sort_values(["site", "canal", "date"]).reset_index(drop=True)


def granularite_dominante(marfeel: pd.DataFrame) -> str:
    """La granularité qui couvre la plus longue période — celle à privilégier."""
    if marfeel.empty or "granularite" not in marfeel:
        return "semaine"
    couverture = marfeel.groupby("granularite")["date"].nunique()
    return str(couverture.idxmax())


def _filtre(marfeel: pd.DataFrame, granularite: str | None) -> pd.DataFrame:
    """Ne garde qu'une granularité, pour ne jamais compter deux fois les mêmes jours."""
    if marfeel.empty or "granularite" not in marfeel:
        return marfeel
    g = granularite or granularite_dominante(marfeel)
    return marfeel[marfeel["granularite"] == g]


# --------------------------------------------------------------------------
# Mesures
# --------------------------------------------------------------------------

def mix_canaux(marfeel: pd.DataFrame, site: str | None = None,
               debut: str | None = None, fin: str | None = None,
               granularite: str | None = None) -> pd.DataFrame:
    """Répartition du trafic entre canaux sur une période."""
    df = _filtre(marfeel, granularite)
    if site:
        df = df[df["site"] == site]
    if debut:
        df = df[df["date"] >= debut]
    if fin:
        df = df[df["date"] <= fin]
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("canal", as_index=False).agg(
        pages_vues=("pages_vues", "sum"),
        visiteurs=("visiteurs", "sum"),
        engagement_s=("engagement_s", "median"),
    )
    g["part_%"] = 100 * g["pages_vues"] / g["pages_vues"].sum()
    g["pages_par_visiteur"] = g["pages_vues"] / g["visiteurs"]
    return g.sort_values("pages_vues", ascending=False).reset_index(drop=True)


def compare_periodes(marfeel: pd.DataFrame, a: tuple[str, str], b: tuple[str, str],
                     sites: list[str] | None = None,
                     granularite: str | None = None) -> pd.DataFrame:
    """Compare deux périodes, canal par canal, pour un ou plusieurs sites.

    Les bornes sont inclusives. Prendre des périodes de même longueur : un
    trimestre contre un trimestre, sinon la comparaison n'a pas de sens.
    """
    marfeel = _filtre(marfeel, granularite)
    if marfeel.empty:
        return pd.DataFrame()
    sites = sites or sorted(marfeel["site"].unique())
    lignes = []
    for site in sites:
        for canal in sorted(marfeel[marfeel["site"] == site]["canal"].unique()):
            sel = marfeel[(marfeel["site"] == site) & (marfeel["canal"] == canal)]
            pa = sel[(sel["date"] >= a[0]) & (sel["date"] <= a[1])]["pages_vues"].sum()
            pb = sel[(sel["date"] >= b[0]) & (sel["date"] <= b[1])]["pages_vues"].sum()
            if not pa:
                continue
            lignes.append({
                "site": site, "canal": canal,
                "période_A": pa, "période_B": pb,
                "evolution_%": 100 * (pb - pa) / pa,
            })
    return pd.DataFrame(lignes)


def audience_fidele(marfeel: pd.DataFrame, canal: str = "direct",
                    granularite: str | None = None) -> pd.DataFrame:
    """Suivi de l'audience qui revient d'elle-même.

    C'est le seul canal qui mesure un actif plutôt qu'une acquisition : on le
    suit séparément, en visiteurs et en engagement, jamais en pages vues seules.
    """
    df = _filtre(marfeel, granularite)
    df = df[df["canal"] == canal]
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(["site", "annee"], as_index=False).agg(
        visiteurs_par_periode=("visiteurs", "median"),
        pages_vues=("pages_vues", "sum"),
        visiteurs_cumules=("visiteurs", "sum"),
        engagement_s=("engagement_s", "median"),
        periodes=("date", "count"),
    )
    # Les visiteurs uniques ne s'additionnent pas d'une période à l'autre : ce
    # ratio décrit la lecture par période, pas par personne sur l'année.
    g["pages_par_visiteur"] = g["pages_vues"] / g["visiteurs_cumules"]
    return g.sort_values(["site", "annee"]).reset_index(drop=True)


def series_hebdomadaires(marfeel: pd.DataFrame, canal: str = "Discover",
                         granularite: str | None = None) -> pd.DataFrame:
    """Série temporelle d'un canal, un site par colonne — pour la superposition."""
    df = _filtre(marfeel, granularite)
    df = df[df["canal"] == canal]
    if df.empty:
        return pd.DataFrame()
    return (df.pivot_table(index="date", columns="site", values="pages_vues", aggfunc="sum")
              .sort_index()
              .reset_index())
