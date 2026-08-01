"""Trois viviers de sujets pour la conférence de rédaction.

* **froide** — l'archive prouvée, classée par potentiel de ressortie ;
* **chaude** — l'actualité du moment, filtrée par ce qui réussit sur le site ;
* **nouveaux** — les familles sous-exploitées et les sujets à demande démontrée
  ailleurs mais jamais traités ici.

Les trois partagent un même moteur : un profil de succès calculé sur l'historique
du site, jamais des règles écrites à l'avance. Ce que l'outil considère comme
prometteur est donc toujours ce qui a marché **ici**, pas ce qui marche en
général.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from .metrics import SEUIL_CARTON, RELANCES_MAX, Relance, chaines_de_redirection

# Familles thématiques. Volontairement larges : elles servent à mesurer où part
# la production et ce qu'elle rapporte, pas à ranger chaque article au bon
# endroit.
FAMILLES: dict[str, str] = {
    "signalisation / code de la route": r"panneau|signalisation|rond-point|limitation|radar|permis|autoroute|conducteur|automobiliste|stationnement|amende",
    "banque / argent / paiement": r"banque|bancaire|virement|billet|euro|distributeur|paiement|frais|livret|epargne|impot",
    "arnaques / sécurité du quotidien": r"arnaque|escroquerie|piege|fraude|demarchage|phishing|smishing|pirat",
    "colis / livraison / e-commerce": r"colis|livraison|mondial relay|vinted|leboncoin|amazon prime|point relais",
    "droits / travail / administratif": r"conge|salaire|retraite|allocation|caf\b|prime|smic|heures supp|contrat de travail",
    "énergie / maison / facture": r"electricite|chauffage|facture|edf|solaire|isolation|thermostat|radiateur",
    "météo / saison": r"meteo|canicule|chaleur|froid|neige|temperature|vigilance|orage|inondation",
    "santé / alimentation": r"sante|aliment|rappel produit|listeria|salmonell|medicament",
    "espace / science": r"espace|spatial|nasa|spacex|satellite|astronom|scientifique|chercheur|geolog|ocean|planete",
    "auto / mobilité": r"voiture|electrique|tesla|automobile|moteur|avion|train|constructeur",
    "smartphone / usage pratique": r"smartphone|iphone|android|batterie|wifi|bluetooth|application|whatsapp",
    "intelligence artificielle": r"\bia\b|intelligence artificielle|chatgpt|openai|gemini",
    "tech / produits": r"samsung|apple|google|microsoft|windows|processeur|ordinateur|ecran",
    "streaming / IPTV / piratage": r"iptv|streaming|piratage|telechargement|netflix|canal|abonnement",
    "jeu vidéo / consoles": r"playstation|xbox|nintendo|switch|steam|jeu video|gta|pokemon|console",
    "pop culture / séries / cinéma": r"serie|film|saison|marvel|disney|acteur|realisateur|cinema",
    "LEGO / collection": r"lego|collector|figurine|carte pokemon",
}

# Marqueurs de forme du titre. Contrairement aux familles, ils sont indépendants
# du sujet : ils décrivent la manière de l'aborder.
MARQUEURS: dict[str, str] = {
    "adresse au lecteur": r"\bvous\b|\bvotre\b|\bvos\b",
    "question posée": r"\?",
    "registre pratique (voici, comment)": r"\bvoici\b|\bvoila\b|\bcomment\b",
    "ancrage France": r"\bfrance\b|\bfrancais",
    "cadrage négatif": r"attention|mauvaise nouvelle|fin d|interdi|danger|risque",
    "annonce produit": r"sortie|disponible|annonce|devoile|lance|presente|officialise",
    "chiffre dans le titre": r"\d",
    "structure « sujet : promesse »": r"\s:\s",
}

_MOTS_VIDES = set(
    """voici cette votre pour dans avec vous nouvelle nouveau sont plus tout tous cest quoi
    elle bien fait faire peut mais leur sans deja encore aussi comme les des une par sur que
    qui est etre vont avez alors donc meme autre fois ans jour jours""".split()
)


def _plat(texte: str) -> str:
    return unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode().lower()


def _jetons(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-z]{4,}", _plat(texte)) if m not in _MOTS_VIDES}


# --------------------------------------------------------------------------
# Profil de succès
# --------------------------------------------------------------------------

@dataclass
class ProfilSucces:
    """Ce qui distingue les succès du site, mesuré sur son propre historique."""

    seuil: int
    taux_moyen: float                                   # cartons pour 1000 articles
    familles: dict[str, tuple[float, int, int]] = field(default_factory=dict)   # nom -> (taux, articles, cartons)
    marqueurs: dict[str, tuple[float, float, int]] = field(default_factory=dict)  # nom -> (taux avec, taux sans, n)
    saison: dict[int, float] = field(default_factory=dict)     # mois -> taux
    creneaux: dict[str, float] = field(default_factory=dict)   # plage horaire -> taux
    cartons: list[tuple[str, set[str], float]] = field(default_factory=list)

    def familles_porteuses(self, mini: float = 1.5) -> list[str]:
        """Familles dont le rendement dépasse nettement la moyenne du site."""
        return [n for n, (t, _, _) in self.familles.items()
                if self.taux_moyen and t >= mini * self.taux_moyen]

    def familles_sous_exploitees(self, mini: float = 1.5) -> pd.DataFrame:
        """Fort rendement, faible part de la production : le gisement."""
        total = sum(n for _, (_, n, _) in self.familles.items()) or 1
        lignes = [
            {
                "famille": nom,
                "articles": n,
                "part_production_%": 100 * n / total,
                "cartons": c,
                "taux_pour_1000": t,
                "rendement_vs_moyenne": (t / self.taux_moyen) if self.taux_moyen else 0,
            }
            for nom, (t, n, c) in self.familles.items()
        ]
        df = pd.DataFrame(lignes)
        if df.empty:
            return df
        return df.sort_values("taux_pour_1000", ascending=False).reset_index(drop=True)


_CRENEAUX = [(0, 7, "0h – 7h"), (7, 10, "7h – 10h"), (10, 13, "10h – 13h"),
             (13, 16, "13h – 16h"), (16, 19, "16h – 19h"), (19, 24, "19h – minuit")]


def profil_succes(articles: pd.DataFrame, seuil: int = SEUIL_CARTON,
                  type_article: str = "post") -> ProfilSucces:
    """Calcule le profil de succès à partir de l'export d'articles du CMS."""
    df = articles
    if "type" in df.columns and type_article:
        filtre = df[df["type"] == type_article]
        if len(filtre) > 200:      # on ne filtre que si le type existe vraiment
            df = filtre
    df = df[df["titre"].astype(str).str.len() > 0]
    if df.empty:
        return ProfilSucces(seuil=seuil, taux_moyen=0.0)

    succes = df["vues"] > seuil
    taux_moyen = 1000 * succes.sum() / len(df)
    profil = ProfilSucces(seuil=seuil, taux_moyen=taux_moyen)

    titres_plats = df["titre"].map(_plat)
    for nom, motif in FAMILLES.items():
        masque = titres_plats.str.contains(motif, regex=True, na=False)
        n = int(masque.sum())
        if n < 50:                 # sous ce volume le taux n'a pas de sens
            continue
        c = int((succes & masque).sum())
        profil.familles[nom] = (1000 * c / n, n, c)

    for nom, motif in MARQUEURS.items():
        masque = titres_plats.str.contains(motif, regex=True, na=False)
        avec, sans = int(masque.sum()), int((~masque).sum())
        if avec < 50 or sans < 50:
            continue
        profil.marqueurs[nom] = (
            1000 * int((succes & masque).sum()) / avec,
            1000 * int((succes & ~masque).sum()) / sans,
            avec,
        )

    if "mois" in df.columns:
        mois = df["mois"].astype(str).str[5:7]
        for m in range(1, 13):
            masque = mois == f"{m:02d}"
            n = int(masque.sum())
            if n >= 100:
                profil.saison[m] = 1000 * int((succes & masque).sum()) / n

    if "date" in df.columns:
        heures = pd.to_numeric(df["date"].astype(str).str[11:13], errors="coerce")
        for lo, hi, nom in _CRENEAUX:
            masque = (heures >= lo) & (heures < hi)
            n = int(masque.sum())
            if n >= 100:
                profil.creneaux[nom] = 1000 * int((succes & masque).sum()) / n

    for _, ligne in df[succes].iterrows():
        profil.cartons.append((ligne["titre"], _jetons(ligne["titre"]), float(ligne["vues"])))

    return profil


# --------------------------------------------------------------------------
# Notation d'un sujet
# --------------------------------------------------------------------------

@dataclass
class Note:
    score: float
    famille: str | None
    reference: str | None       # le carton passé le plus proche
    vues_reference: float
    raisons: list[str]
    conseils: list[str]


def note_sujet(titre: str, profil: ProfilSucces) -> Note:
    """Évalue un sujet candidat à l'aune de ce qui a réussi sur le site.

    Le score n'a pas d'unité : il ne sert qu'à ordonner des candidats entre eux.
    """
    plat, jetons = _plat(titre), _jetons(titre)
    raisons: list[str] = []
    conseils: list[str] = []

    # Famille la plus porteuse parmi celles que le titre évoque.
    famille, taux_famille = None, profil.taux_moyen
    for nom, motif in FAMILLES.items():
        if nom in profil.familles and re.search(motif, plat):
            t = profil.familles[nom][0]
            if famille is None or t > taux_famille:
                famille, taux_famille = nom, t
    if famille and profil.taux_moyen:
        rapport = taux_famille / profil.taux_moyen
        if rapport >= 1.5:
            raisons.append(f"famille « {famille} » : {rapport:.1f}× la moyenne du site")
        elif rapport <= 0.5:
            raisons.append(f"famille « {famille} » : rendement faible ici ({rapport:.1f}×)")

    # Ressemblance au meilleur carton passé.
    reference, vues_ref, proximite = None, 0.0, 0.0
    for titre_ref, jetons_ref, vues in profil.cartons:
        if not jetons or not jetons_ref:
            continue
        s = len(jetons & jetons_ref) / len(jetons | jetons_ref)
        if s > proximite:
            proximite, reference, vues_ref = s, titre_ref, vues
    if proximite >= 0.15:
        raisons.append(f"proche d'un succès passé ({vues_ref:,.0f} vues)".replace(",", " "))

    # Marqueurs de forme, avec leur effet réellement mesuré.
    facteur_forme = 1.0
    for nom, (avec, sans, _) in profil.marqueurs.items():
        present = bool(re.search(MARQUEURS[nom], plat))
        if not sans:
            continue
        effet = avec / sans
        if present and effet >= 1.5:
            facteur_forme *= min(effet, 4.0) ** 0.5
            raisons.append(f"{nom} : ×{effet:.1f}")
        elif present and effet <= 0.8:
            facteur_forme *= max(effet, 0.4) ** 0.5
            conseils.append(f"retirer « {nom} » (×{effet:.1f} ici)")
        elif not present and effet >= 2.0:
            conseils.append(f"ajouter « {nom} » (×{effet:.1f} ici)")

    if len(titre) < 85:
        conseils.append(f"allonger le titre : {len(titre)} caractères, viser 85 et plus")

    if profil.creneaux:
        meilleur = max(profil.creneaux, key=profil.creneaux.get)
        conseils.append(f"publier sur le créneau {meilleur}")

    score = (
        (taux_famille or profil.taux_moyen or 1)
        * (1 + 3 * proximite)
        * facteur_forme
    )
    return Note(score, famille, reference, vues_ref, raisons, conseils)


# --------------------------------------------------------------------------
# Palette froide
# --------------------------------------------------------------------------

def palette_froide(articles: pd.DataFrame, profil: ProfilSucces,
                   relances: list[Relance] | None = None,
                   aujourdhui: str | datetime.date | None = None,
                   seuil_vues: int = 200_000, sommeil_min: int = 180,
                   redirections: pd.DataFrame | None = None) -> pd.DataFrame:
    """Sujets de l'archive à ressortir, classés par potentiel.

    Le score récompense une audience prouvée, un long sommeil et une
    correspondance de saison ; il écarte les sujets déjà trop relancés.
    """
    if articles.empty:
        return pd.DataFrame()
    reference = pd.Timestamp(aujourdhui or datetime.date.today())
    index = [(_jetons(r.slug.replace("-", " ")), r.nombre, r.derniere_date)
             for r in (relances or [])]
    index += chaines_de_redirection(redirections)

    mois_prochain = (reference.month % 12) + 1
    lignes = []
    for _, article in articles[articles["vues"] > seuil_vues].iterrows():
        try:
            publie = pd.Timestamp(article["jour"])
        except Exception:
            continue
        sommeil = (reference - publie).days
        if sommeil < sommeil_min:
            continue

        versions, derniere, meilleure = 1, article["jour"], 0.0
        jetons_titre = _jetons(article["titre"])
        for jetons_source, n, date_finale in index:
            if not jetons_titre or not jetons_source:
                continue
            s = len(jetons_titre & jetons_source) / len(jetons_titre | jetons_source)
            if s >= 0.4 and s > meilleure:
                meilleure, versions, derniere = s, n, max(date_finale, article["jour"])
        relances_faites = max(versions - 1, 0)
        if relances_faites > RELANCES_MAX:
            continue                     # épuisé : ne rapporte plus

        depuis = (reference - pd.Timestamp(derniere)).days
        mois_origine = publie.month
        # Un sujet publié à cette période de l'année a plus de chances de
        # redevenir d'actualité.
        saison = 1.6 if mois_origine in (reference.month, mois_prochain) else 1.0
        rendement = profil.saison.get(mois_origine, profil.taux_moyen)
        note = note_sujet(article["titre"], profil)

        lignes.append({
            "titre": article["titre"],
            "auteur": article.get("auteur", ""),
            "publié_le": article["jour"],
            "vues_prouvées": article["vues"],
            "en_sommeil_depuis_j": depuis,
            "relances_détectées": relances_faites,
            "famille": note.famille or "—",
            "période_favorable": "oui" if saison > 1 else "",
            "score": article["vues"] * min(depuis / 365, 2.5) * saison
                     * (0.7 + 0.3 * (rendement / profil.taux_moyen if profil.taux_moyen else 1)),
        })
    if not lignes:
        return pd.DataFrame()
    return pd.DataFrame(lignes).sort_values("score", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# Palette chaude
# --------------------------------------------------------------------------

def palette_chaude(items: list[dict], profil: ProfilSucces,
                   minimum: float = 0.0) -> pd.DataFrame:
    """Classe des sujets d'actualité selon leur ressemblance aux succès du site.

    `items` : liste de dictionnaires `{titre, source, url, date}`, telle que la
    renvoie `jdg.flux.collecte`.
    """
    if not items:
        return pd.DataFrame()
    lignes = []
    for item in items:
        titre = str(item.get("titre", "")).strip()
        if not titre:
            continue
        note = note_sujet(titre, profil)
        if note.score < minimum:
            continue
        lignes.append({
            "sujet": titre,
            "source": item.get("source", ""),
            "famille": note.famille or "—",
            "score": note.score,
            "pourquoi": " · ".join(note.raisons) or "aucun signal fort",
            "référence": note.reference or "",
            "vues_référence": note.vues_reference,
            "à_faire": " · ".join(note.conseils[:3]),
            "url": item.get("url", ""),
        })
    if not lignes:
        return pd.DataFrame()
    return pd.DataFrame(lignes).sort_values("score", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# Vivier de nouveaux
# --------------------------------------------------------------------------

def sujets_orphelins(articles: pd.DataFrame, concurrent: pd.DataFrame,
                     seuil: int = 400_000, proximite_max: float = 0.16) -> pd.DataFrame:
    """Succès d'un concurrent sans aucun équivalent dans notre production.

    Demande démontrée, couverture nulle : le vivier le plus direct.
    """
    if articles.empty or concurrent.empty:
        return pd.DataFrame()
    nos_jetons = [_jetons(t) for t in articles["titre"].astype(str)]
    lignes = []
    for _, leur in concurrent[concurrent["vues"] > seuil].iterrows():
        jl = _jetons(leur["titre"])
        if not jl:
            continue
        proche = max((len(jl & j) / len(jl | j) for j in nos_jetons if j), default=0.0)
        if proche < proximite_max:
            lignes.append({
                "sujet": leur["titre"],
                "leurs_vues": leur["vues"],
                "publié_le": leur["jour"],
                "recouvrement_max": proche,
            })
    if not lignes:
        return pd.DataFrame()
    return pd.DataFrame(lignes).sort_values("leurs_vues", ascending=False).reset_index(drop=True)


def angles_a_retravailler(articles: pd.DataFrame, profil: ProfilSucces,
                          n: int = 25) -> pd.DataFrame:
    """Articles récents d'une famille porteuse, traités sans les marqueurs qui
    fonctionnent — donc à reformuler plutôt qu'à remplacer.

    C'est le vivier qui respecte la ligne éditoriale : mêmes sujets, autre angle.
    """
    if articles.empty or not profil.marqueurs:
        return pd.DataFrame()
    gagnants = [nom for nom, (a, s, _) in profil.marqueurs.items() if s and a / s >= 2.0]
    if not gagnants:
        return pd.DataFrame()

    recents = articles.sort_values("jour", ascending=False).head(1500)
    lignes = []
    for _, article in recents.iterrows():
        plat = _plat(article["titre"])
        manquants = [nom for nom in gagnants if not re.search(MARQUEURS[nom], plat)]
        if len(manquants) < len(gagnants):
            continue                      # l'angle est déjà en partie appliqué
        note = note_sujet(article["titre"], profil)
        if note.famille is None:
            continue
        lignes.append({
            "titre_actuel": article["titre"],
            "publié_le": article["jour"],
            "vues": article["vues"],
            "famille": note.famille,
            "manque": " · ".join(manquants),
            "longueur_titre": len(article["titre"]),
        })
    if not lignes:
        return pd.DataFrame()
    return (pd.DataFrame(lignes)
            .sort_values("vues", ascending=False)
            .head(n)
            .reset_index(drop=True))
