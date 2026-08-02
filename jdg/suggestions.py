"""Proposer des formulations de titre à partir des succès passés du site.

Le catalogue de gabarits ci-dessous est écrit à la main, mais **son classement
ne l'est pas** : chaque gabarit est confronté à l'historique du site, et seuls
ceux qui y ont réellement produit des succès sont proposés, dans l'ordre de leur
rendement mesuré. Un gabarit qui ne marche pas ici ne remonte jamais, même s'il
marche partout ailleurs.

Les gabarits sont construits pour être **sûrs grammaticalement** : le sujet est
toujours inséré comme groupe nominal, en tête ou après un deux-points, jamais à
une place qui exigerait de l'accorder ou de le conjuguer. Le résultat reste une
proposition à retravailler, pas un titre publiable tel quel.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from .palettes import MARQUEURS, ProfilSucces, note_sujet


@dataclass(frozen=True)
class Gabarit:
    nom: str
    modele: str           # {sujet} est remplacé par le groupe nominal
    signature: str        # ce qui permet de repérer ce gabarit dans l'historique
    note: str             # à quoi il sert, en une ligne


# Chaque signature décrit une tournure, pas un sujet : c'est elle qui permet de
# mesurer le rendement du gabarit sur les articles déjà publiés.
GABARITS: tuple[Gabarit, ...] = (
    Gabarit(
        "Question puis réponse",
        "{sujet} ? Voici ce que cela veut vraiment dire pour vous",
        r"\?.{0,40}\bvoici\b|\bvoici\b.{0,40}\?",
        "La forme la plus rentable du site : on pose la question du lecteur, on promet la réponse.",
    ),
    Gabarit(
        "Ce que ça change pour vous",
        "{sujet} : voici ce que ça change concrètement pour vous",
        r"\bvoici ce (?:que|qui)\b",
        "Traduit une nouvelle en conséquence pratique. Fonctionne sur le réglementaire.",
    ),
    Gabarit(
        "À vérifier dès maintenant",
        "{sujet} : ce qu'il faut vérifier chez vous dès maintenant",
        r"\bverifier\b|\bfaut savoir\b|\bdes maintenant\b",
        "Ajoute une action immédiate. Utile quand le sujet peut sembler lointain.",
    ),
    Gabarit(
        "Mauvaise nouvelle",
        "Mauvaise nouvelle : {sujet}. Voici ce qui vous attend",
        r"\bmauvaise nouvelle\b",
        "Cadrage négatif, mesuré efficace ici. À réserver aux sujets où c'en est vraiment une.",
    ),
    Gabarit(
        "Bonne nouvelle",
        "Bonne nouvelle : {sujet}, et voici ce que vous pouvez en faire",
        r"\bbonne nouvelle\b",
        "Le pendant positif. Moins fréquent dans les succès du site, mais présent.",
    ),
    Gabarit(
        "Ce que vous ignorez",
        "{sujet} : ce que presque personne ne sait encore, et pourquoi ça vous concerne",
        r"\bpersonne ne\b|\bignor|\bpourquoi vous\b",
        "Curiosité plus implication personnelle. Fonctionne sur l'usage domestique.",
    ),
    Gabarit(
        "Fin de quelque chose",
        "{sujet} : ce qui va disparaître, et par quoi ce sera remplacé",
        r"\bfin d|\bdisparai|\bremplac",
        "La disparition d'un service ou d'une habitude est un déclencheur récurrent ici.",
    ),
    Gabarit(
        "Signification d'un signe",
        "{sujet} : que veut dire ce détail que vous avez sous les yeux tous les jours",
        r"\bque (?:veut|signifie) dire\b",
        "Décoder un objet du quotidien — panneau, icône, symbole. Très rentable ici.",
    ),
    Gabarit(
        "Erreur à éviter",
        "{sujet} : l'erreur que font presque tous les Français, et comment l'éviter",
        r"\berreur\b|\bne (?:le|la|les) faites\b|\beviter\b",
        "Ancrage France plus faute à corriger. Combine deux marqueurs mesurés forts.",
    ),
    Gabarit(
        "Nouvelle règle",
        "{sujet} : la règle change en France, voici ce que vous devez savoir",
        r"\bnouvelle regle\b|\bregle change\b|\bnouvelles? norme",
        "Réglementaire pur. Le filon le plus régulier du site.",
    ),
)


def _plat(texte: str) -> str:
    return unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode().lower()


def rendement_des_gabarits(articles: pd.DataFrame, profil: ProfilSucces,
                           minimum: int = 25) -> pd.DataFrame:
    """Confronte chaque gabarit à l'historique : combien d'articles, combien de
    succès, quel rendement rapporté à la moyenne du site.

    Les gabarits trop peu représentés sont écartés : sous quelques dizaines
    d'articles, un taux n'a pas de sens.
    """
    if articles.empty:
        return pd.DataFrame()
    titres = articles["titre"].map(_plat)
    succes = articles["vues"] > profil.seuil

    lignes = []
    for gabarit in GABARITS:
        masque = titres.str.contains(gabarit.signature, regex=True, na=False)
        n = int(masque.sum())
        if n < minimum:
            continue
        c = int((succes & masque).sum())
        taux = 1000 * c / n
        exemple = articles[masque & succes].nlargest(1, "vues")
        lignes.append({
            "gabarit": gabarit.nom,
            "articles": n,
            "succès": c,
            "taux_pour_1000": taux,
            "rendement": (taux / profil.taux_moyen) if profil.taux_moyen else 0,
            "exemple": exemple["titre"].iloc[0] if not exemple.empty else "",
            "vues_exemple": float(exemple["vues"].iloc[0]) if not exemple.empty else 0.0,
        })
    if not lignes:
        return pd.DataFrame()
    return (pd.DataFrame(lignes)
            .sort_values("taux_pour_1000", ascending=False)
            .reset_index(drop=True))


# Déterminants qu'on peut passer en minuscule sans risque quand le sujet n'est
# plus en tête de phrase. Tout le reste est laissé tel quel : « Google », « SNCF »
# ou « Freebox » doivent garder leur majuscule.
_DETERMINANTS = (
    "le ", "la ", "les ", "un ", "une ", "des ", "du ", "de ", "ce ", "cet ",
    "cette ", "ces ", "mon ", "ma ", "mes ", "votre ", "vos ", "leur ", "leurs ",
)


def _insere(modele: str, sujet: str) -> str:
    """Place le sujet dans le gabarit en respectant la casse de la phrase."""
    if not modele.startswith("{sujet}"):
        # Le sujet arrive en cours de phrase : on abaisse son déterminant, mais
        # jamais un nom propre.
        for det in _DETERMINANTS:
            if sujet.lower().startswith(det):
                sujet = sujet[0].lower() + sujet[1:]
                break
    titre = modele.format(sujet=sujet)
    return titre[0].upper() + titre[1:]


def _nettoie_sujet(sujet: str) -> str:
    """Prépare le sujet pour l'insertion : sans ponctuation finale, sans majuscule
    parasite, tronqué s'il est déjà une phrase entière."""
    sujet = re.sub(r"\s+", " ", str(sujet)).strip().rstrip(".!?;:,")
    # Un titre complet passé en entrée : on ne garde que sa partie utile.
    if " : " in sujet:
        sujet = sujet.split(" : ", 1)[0].strip()
    return sujet


def suggere_titres(sujet: str, articles: pd.DataFrame, profil: ProfilSucces,
                   n: int = 8, longueur_cible: int = 85) -> pd.DataFrame:
    """Propose des formulations pour un sujet, classées par rendement mesuré.

    Chaque proposition indique le gabarit d'origine, le succès passé qui lui sert
    de référence, les procédés qu'elle active et sa longueur. **Ce sont des
    amorces à retravailler** : la grammaire est sûre, la justesse ne l'est pas.
    """
    sujet = _nettoie_sujet(sujet)
    if not sujet:
        return pd.DataFrame()

    rendements = rendement_des_gabarits(articles, profil)
    if rendements.empty:
        return pd.DataFrame()
    ordre = {r["gabarit"]: r for _, r in rendements.iterrows()}

    lignes = []
    for gabarit in GABARITS:
        mesure = ordre.get(gabarit.nom)
        if mesure is None:
            continue        # jamais éprouvé sur ce site : on ne le propose pas
        titre = _insere(gabarit.modele, sujet)
        note = note_sujet(titre, profil)
        procedes = [nom for nom, motif in MARQUEURS.items()
                    if re.search(motif, _plat(titre))
                    and nom in profil.marqueurs
                    and profil.marqueurs[nom][1]
                    and profil.marqueurs[nom][0] / profil.marqueurs[nom][1] >= 1.5]
        lignes.append({
            "titre_proposé": titre,
            "caractères": len(titre),
            "assez_long": len(titre) >= longueur_cible,
            "gabarit": gabarit.nom,
            "rendement_du_gabarit": mesure["rendement"],
            "procédés_activés": " · ".join(procedes) or "—",
            "score": note.score,
            "inspiré_de": mesure["exemple"],
            "vues_de_référence": mesure["vues_exemple"],
            "à_quoi_ça_sert": gabarit.note,
        })
    if not lignes:
        return pd.DataFrame()
    return (pd.DataFrame(lignes)
            .sort_values(["rendement_du_gabarit", "score"], ascending=False)
            .head(n)
            .reset_index(drop=True))
