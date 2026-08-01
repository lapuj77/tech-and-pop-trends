"""Lecture des flux d'actualité qui alimentent la palette chaude.

Rien d'autre que la bibliothèque standard : ces flux sont du RSS, et ajouter une
dépendance pour les lire n'apporterait rien.

⚠️ Ces flux ne sont pas joignables depuis tous les environnements — un réseau
d'entreprise ou un bac à sable peut les bloquer. `collecte` ne lève jamais
d'exception : elle renvoie ce qu'elle a pu lire et la liste des échecs, à
afficher tels quels plutôt que de laisser croire qu'il n'y a pas d'actualité.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

AGENT = "Mozilla/5.0 (compatible; veille-editoriale/1.0)"
DELAI = 12

# Google Trends donne le pouls général ; Google News permet de cibler les
# familles qui rapportent le plus sur le site.
FLUX_PAR_DEFAUT: dict[str, str] = {
    "Tendances France": "https://trends.google.com/trending/rss?geo=FR",
    "Actualités France": "https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:FR",
    "Réglementation": "https://news.google.com/rss/search?q=nouvelle+r%C3%A8gle+OR+r%C3%A9glementation+France&hl=fr&gl=FR&ceid=FR:FR",
    "Arnaques": "https://news.google.com/rss/search?q=arnaque+OR+fraude+OR+d%C3%A9marchage&hl=fr&gl=FR&ceid=FR:FR",
    "Banque et argent": "https://news.google.com/rss/search?q=banque+OR+virement+OR+carte+bancaire&hl=fr&gl=FR&ceid=FR:FR",
    "Sciences": "https://news.google.com/rss/search?q=%C3%A9tude+scientifique+OR+chercheurs+OR+espace&hl=fr&gl=FR&ceid=FR:FR",
}


@dataclass
class Collecte:
    items: list[dict]
    echecs: list[tuple[str, str]]        # (nom du flux, raison)

    @property
    def ok(self) -> bool:
        return bool(self.items)


def _analyse(xml_brut: bytes, source: str) -> list[dict]:
    """Extrait les entrées d'un flux RSS. Les balises varient d'un flux à l'autre."""
    racine = ET.fromstring(xml_brut)
    items = []
    for item in racine.iter():
        if not item.tag.endswith("item"):
            continue
        champs = {}
        for enfant in item:
            nom = enfant.tag.split("}")[-1]
            champs.setdefault(nom, (enfant.text or "").strip())
        titre = champs.get("title", "")
        if not titre:
            continue
        items.append({
            "titre": titre,
            "url": champs.get("link", ""),
            "date": champs.get("pubDate", ""),
            "source": source,
        })
    return items


def lire_flux(url: str, source: str, delai: int = DELAI) -> tuple[list[dict], str | None]:
    """Lit un flux. Renvoie (entrées, message d'erreur éventuel)."""
    requete = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            return _analyse(reponse.read(), source), None
    except urllib.error.HTTPError as err:
        return [], f"HTTP {err.code}"
    except urllib.error.URLError as err:
        return [], f"réseau injoignable ({err.reason})"
    except ET.ParseError:
        return [], "flux illisible (XML invalide)"
    except Exception as err:                        # pragma: no cover - garde-fou
        return [], f"{type(err).__name__}: {err}"


def collecte(flux: dict[str, str] | None = None, delai: int = DELAI) -> Collecte:
    """Lit tous les flux et regroupe les entrées, sans jamais échouer."""
    flux = flux or FLUX_PAR_DEFAUT
    items, echecs, vus = [], [], set()
    for nom, url in flux.items():
        lot, erreur = lire_flux(url, nom, delai)
        if erreur:
            echecs.append((nom, erreur))
            continue
        for item in lot:
            cle = item["titre"].lower()[:90]
            if cle in vus:
                continue                    # un même sujet revient sur plusieurs flux
            vus.add(cle)
            items.append(item)
    return Collecte(items=items, echecs=echecs)


def collecte_hors_ligne(chemin: str | Path) -> Collecte:
    """Lit des flux enregistrés sur disque — pour mettre au point la notation
    sans dépendre du réseau."""
    chemin = Path(chemin)
    fichiers = sorted(chemin.glob("*.xml")) if chemin.is_dir() else [chemin]
    items, echecs = [], []
    for fichier in fichiers:
        try:
            items += _analyse(fichier.read_bytes(), fichier.stem)
        except Exception as err:
            echecs.append((fichier.name, str(err)))
    return Collecte(items=items, echecs=echecs)
