"""Lecture des exports Search Console et des exports d'articles du CMS.

Trois formats sont acceptés :

* l'archive ZIP telle que la Search Console la produit (« Exporter » -> CSV) ;
* un dossier contenant les CSV décompressés ;
* un CSV isolé.

Les nombres français (espaces insécables, virgule décimale) et l'encodage
UTF-8 avec BOM sont gérés ici, une bonne fois pour toutes.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Espace, espace insécable, espace insécable étroit.
_ESPACES = dict.fromkeys(map(ord, " \xa0 "), None)


def to_number(value) -> float:
    """Convertit « 1 084 872 » ou « 7,33% » en nombre. Renvoie 0 si illisible."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    texte = str(value).translate(_ESPACES).replace("%", "").replace(",", ".")
    try:
        return float(texte)
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------
# Search Console
# --------------------------------------------------------------------------

# Les intitulés varient selon la langue de l'interface et le type de rapport.
_ONGLETS = {
    "dates": ("graphique", "dates", "date"),
    "pages": ("pages",),
    "requetes": ("requêtes", "requetes", "queries"),
    "pays": ("pays", "countries"),
    "appareils": ("appareils", "appareil", "devices"),
    "filtres": ("filtres", "filtre", "filters"),
}


@dataclass
class ExportGSC:
    """Un export Search Console : les onglets utiles plus le filtre appliqué."""

    source: str
    dates: pd.DataFrame = field(default_factory=pd.DataFrame)
    pages: pd.DataFrame = field(default_factory=pd.DataFrame)
    requetes: pd.DataFrame = field(default_factory=pd.DataFrame)
    filtres: dict[str, str] = field(default_factory=dict)

    @property
    def canal(self) -> str:
        """« Discover », « Web », « Google Actualités »… d'après l'onglet Filtres."""
        for cle, valeur in self.filtres.items():
            if "recherche" in cle.lower() or "search type" in cle.lower():
                brut = valeur.strip()
                # La Search Console française écrit « Découvrir » pour Discover.
                return "Discover" if brut.lower().startswith("découvrir") else brut
        return "inconnu"

    @property
    def periode(self) -> tuple[str, str] | None:
        if self.dates.empty:
            return None
        return self.dates["date"].min(), self.dates["date"].max()

    @property
    def mois(self) -> str | None:
        """Mois couvert, au format AAAA-MM, si l'export tient dans un seul mois."""
        bornes = self.periode
        if bornes is None:
            return None
        debut, fin = bornes
        return debut[:7] if debut[:7] == fin[:7] else None


def _normalise_colonnes(df: pd.DataFrame) -> pd.DataFrame:
    """Renomme les colonnes en noms courts et convertit les valeurs numériques."""
    renommage = {}
    for colonne in df.columns:
        cle = str(colonne).strip().lower()
        if cle.startswith("date"):
            renommage[colonne] = "date"
        elif cle.startswith("clic") or cle.startswith("click"):
            renommage[colonne] = "clics"
        elif cle.startswith("impression"):
            renommage[colonne] = "impressions"
        elif cle.startswith("ctr"):
            renommage[colonne] = "ctr"
        elif cle.startswith("position"):
            renommage[colonne] = "position"
        elif cle.startswith("page") or cle.startswith("url"):
            renommage[colonne] = "url"
        elif cle.startswith("requête") or cle.startswith("requete") or cle.startswith("quer"):
            renommage[colonne] = "requete"
        else:
            renommage[colonne] = cle
    df = df.rename(columns=renommage)

    for colonne in ("clics", "impressions", "position", "ctr"):
        if colonne in df.columns:
            df[colonne] = df[colonne].map(to_number)
    if "date" in df.columns:
        df["date"] = df["date"].astype(str).str.strip().str[:10]
    return df


def _lire_csv(contenu: bytes) -> pd.DataFrame:
    texte = contenu.decode("utf-8-sig", errors="replace")
    # La Search Console exporte en virgules ; le CMS en points-virgules.
    dialecte = csv.Sniffer()
    try:
        separateur = dialecte.sniff(texte[:2000], delimiters=",;\t").delimiter
    except csv.Error:
        separateur = ","
    return pd.read_csv(io.StringIO(texte), sep=separateur, dtype=str, keep_default_na=False)


def _classe_onglet(nom: str) -> str | None:
    base = Path(nom).stem.strip().lower()
    for cle, prefixes in _ONGLETS.items():
        if any(base.startswith(p) for p in prefixes):
            return cle
    return None


def charger_gsc(chemin: str | Path) -> ExportGSC:
    """Charge un export Search Console (ZIP, dossier ou CSV isolé)."""
    chemin = Path(chemin)
    export = ExportGSC(source=chemin.name)

    if chemin.suffix.lower() == ".zip":
        with zipfile.ZipFile(chemin) as archive:
            fichiers = [
                (nom, archive.read(nom))
                for nom in archive.namelist()
                if nom.lower().endswith(".csv")
            ]
    elif chemin.is_dir():
        fichiers = [(f.name, f.read_bytes()) for f in sorted(chemin.glob("*.csv"))]
    else:
        fichiers = [(chemin.name, chemin.read_bytes())]

    for nom, contenu in fichiers:
        onglet = _classe_onglet(nom)
        if onglet is None:
            continue
        df = _lire_csv(contenu)
        if df.empty:
            continue
        if onglet == "filtres":
            colonnes = list(df.columns)
            if len(colonnes) >= 2:
                export.filtres = dict(
                    zip(df[colonnes[0]].astype(str), df[colonnes[1]].astype(str))
                )
            continue
        df = _normalise_colonnes(df)
        if onglet == "dates" and "date" in df.columns:
            export.dates = df[df["date"].str.match(r"\d{4}-\d{2}-\d{2}", na=False)]
        elif onglet == "pages":
            export.pages = df
        elif onglet == "requetes":
            export.requetes = df

    # Un CSV isolé n'a pas de nom d'onglet exploitable : on devine au contenu.
    if export.dates.empty and export.pages.empty and export.requetes.empty and fichiers:
        df = _normalise_colonnes(_lire_csv(fichiers[0][1]))
        if "date" in df.columns:
            export.dates = df[df["date"].str.match(r"\d{4}-\d{2}-\d{2}", na=False)]
        elif "url" in df.columns:
            export.pages = df
        elif "requete" in df.columns:
            export.requetes = df

    return export


def charger_dossier_gsc(dossier: str | Path) -> list[ExportGSC]:
    """Charge tous les exports Search Console d'un dossier (ZIP et sous-dossiers)."""
    dossier = Path(dossier)
    exports = []
    for element in sorted(dossier.iterdir()):
        if element.suffix.lower() == ".zip" or element.is_dir():
            export = charger_gsc(element)
            if not (export.dates.empty and export.pages.empty):
                exports.append(export)
    return exports


# --------------------------------------------------------------------------
# Export d'articles du CMS
# --------------------------------------------------------------------------

def charger_articles(*chemins: str | Path) -> pd.DataFrame:
    """Charge un ou plusieurs exports « Auteur_Tous » du CMS.

    Colonnes produites : titre, type, auteur, mots, vues, date, mois, annee.
    """
    morceaux = []
    for chemin in chemins:
        chemin = Path(chemin)
        df = pd.read_csv(chemin, sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)
        df.columns = [str(c).strip().lower() for c in df.columns]
        renommage = {}
        for colonne in df.columns:
            if colonne.startswith("titre") or colonne.startswith("title"):
                renommage[colonne] = "titre"
            elif colonne.startswith("type"):
                renommage[colonne] = "type"
            elif colonne.startswith("réd") or colonne.startswith("red") or colonne.startswith("auteur"):
                renommage[colonne] = "auteur"
            elif colonne.startswith("mot") or colonne.startswith("word"):
                renommage[colonne] = "mots"
            elif colonne.startswith("vue") or colonne.startswith("view"):
                renommage[colonne] = "vues"
            elif colonne.startswith("date"):
                renommage[colonne] = "date"
            elif colonne.startswith("modif"):
                renommage[colonne] = "modifie_le"
        df = df.rename(columns=renommage)
        morceaux.append(df)

    if not morceaux:
        return pd.DataFrame()

    articles = pd.concat(morceaux, ignore_index=True)
    articles["vues"] = articles.get("vues", 0).map(to_number)
    articles["mots"] = articles.get("mots", 0).map(to_number)
    articles["date"] = articles["date"].astype(str).str.strip()
    articles = articles[articles["date"].str.len() >= 7].copy()
    articles["jour"] = articles["date"].str[:10]
    articles["mois"] = articles["date"].str[:7]
    articles["annee"] = articles["date"].str[:4]
    for colonne in ("titre", "auteur", "type"):
        if colonne in articles.columns:
            articles[colonne] = articles[colonne].astype(str).str.strip()
    return articles.sort_values("vues", ascending=False).reset_index(drop=True)


def charger_redirections(chemin: str | Path) -> pd.DataFrame:
    """Charge une table de redirections (export de plugin ou du serveur).

    Les deux premières colonnes ressemblant à des URLs sont retenues et
    renommées « source » et « cible », quels que soient leurs intitulés
    d'origine — ils varient d'un plugin à l'autre.
    """
    chemin = Path(chemin)
    df = _lire_csv(chemin.read_bytes())
    if df.empty:
        return pd.DataFrame()

    candidates = [
        colonne for colonne in df.columns
        if df[colonne].astype(str).str.contains(r"^/|https?://", regex=True, na=False).mean() > 0.5
    ]
    if len(candidates) < 2:
        candidates = list(df.columns)[:2]
    df = df[candidates[:2]].copy()
    df.columns = ["source", "cible"]
    return df[(df["source"].astype(str).str.len() > 1) & (df["cible"].astype(str).str.len() > 1)]


# --------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------

MOTIF_URL_DATEE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/([^/?#]+)")


def decoupe_url(url: str) -> tuple[str | None, str | None]:
    """Renvoie (date de publication AAAA-MM-JJ, slug) pour une URL datée.

    Les URLs sans date — sections /vpn/, /dossier/, /telecharger/… — renvoient
    (None, dernier segment).
    """
    correspondance = MOTIF_URL_DATEE.search(str(url))
    if correspondance:
        annee, mois, jour, slug = correspondance.groups()
        return f"{annee}-{mois}-{jour}", slug
    segments = [s for s in str(url).split("?")[0].rstrip("/").split("/") if s]
    return None, (segments[-1] if segments else None)


def section(url: str) -> str:
    """Section éditoriale d'une URL : « articles datés », « vpn », « dossier »…"""
    date, _ = decoupe_url(url)
    if date:
        return "articles datés"
    correspondance = re.search(r"journaldugeek\.com/([a-z0-9\-]+)/", str(url))
    return correspondance.group(1) if correspondance else "accueil"
