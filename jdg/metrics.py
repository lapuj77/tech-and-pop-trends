"""Les mesures du diagnostic d'audience.

Chaque fonction correspond à une question qu'on s'est posée pendant l'analyse
et qu'on veut pouvoir rejouer chaque mois sans refaire le raisonnement.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from .parsers import decoupe_url, section

# Seuil au-delà duquel on parle de « carton ». 300 000 vues correspond au
# décrochage observé dans la distribution : au-dessus, un article porte son mois.
SEUIL_CARTON = 300_000

# Au-delà de deux relances, le rendement mesuré s'effondre (médiane de reprise
# 59 % sur Discover, deux tiers des relances sous la version d'origine).
RELANCES_MAX = 2

_MOTS_VIDES = {
    "voici", "cette", "votre", "pour", "dans", "avec", "vous", "nouvelle",
    "nouveau", "sont", "plus", "tout", "tous", "cest", "quoi", "elle", "bien",
    "fait", "faire", "peut", "mais", "leur", "sans", "deja", "encore", "aussi",
    "comme", "quil", "quel", "quelle", "voir", "avoir", "etre", "les", "des",
}


def _jetons(texte: str) -> set[str]:
    """Mots significatifs d'un titre ou d'un slug, sans accents ni mots vides."""
    plat = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    mots = re.findall(r"[a-z]{4,}", plat.lower())
    return {m for m in mots if m not in _MOTS_VIDES}


def _similarite(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------
# Séries temporelles
# --------------------------------------------------------------------------

def serie_mensuelle(dates: pd.DataFrame) -> pd.DataFrame:
    """Agrège l'onglet « Dates » d'un export par mois."""
    if dates.empty:
        return pd.DataFrame()
    df = dates.copy()
    df["mois"] = df["date"].str[:7]
    groupes = df.groupby("mois", as_index=False).agg(
        clics=("clics", "sum"),
        impressions=("impressions", "sum"),
        jours=("date", "count"),
    )
    groupes["ctr"] = (groupes["clics"] / groupes["impressions"]).fillna(0) * 100
    return groupes.sort_values("mois").reset_index(drop=True)


def evolution_annuelle(mensuel: pd.DataFrame, colonne: str = "clics") -> pd.DataFrame:
    """Compare chaque mois au même mois de l'année précédente."""
    if mensuel.empty:
        return pd.DataFrame()
    valeurs = mensuel.set_index("mois")[colonne].to_dict()
    lignes = []
    for mois, valeur in sorted(valeurs.items()):
        annee, numero = mois.split("-")
        precedent = f"{int(annee) - 1}-{numero}"
        if precedent in valeurs and valeurs[precedent]:
            lignes.append(
                {
                    "mois": mois,
                    "precedent": valeurs[precedent],
                    "actuel": valeur,
                    "evolution_%": 100 * (valeur - valeurs[precedent]) / valeurs[precedent],
                }
            )
    return pd.DataFrame(lignes)


# --------------------------------------------------------------------------
# Stock et flux
# --------------------------------------------------------------------------

def stock_et_flux(pages: pd.DataFrame, mois: str) -> dict:
    """Répartit les clics d'un mois entre production du mois, stock et sections
    sans date.

    Attention : une relance crée une URL portant la date du jour. Elle est donc
    comptée comme « neuf ». La colonne « relances » ci-dessous l'isole.
    """
    if pages.empty or "url" not in pages.columns:
        return {}
    neuf = stock = sans_date = 0.0
    for url, clics in zip(pages["url"], pages["clics"]):
        publie, _ = decoupe_url(url)
        if publie is None:
            sans_date += clics
        elif publie[:7] == mois:
            neuf += clics
        else:
            stock += clics
    total = neuf + stock + sans_date
    if not total:
        return {}
    return {
        "mois": mois,
        "total": total,
        "neuf": neuf,
        "stock": stock,
        "sans_date": sans_date,
        "part_neuf_%": 100 * neuf / total,
        "part_stock_%": 100 * stock / total,
        "part_sans_date_%": 100 * sans_date / total,
    }


def poids_des_sections(pages: pd.DataFrame) -> pd.DataFrame:
    """Répartition des clics par section du site."""
    if pages.empty or "url" not in pages.columns:
        return pd.DataFrame()
    df = pages.copy()
    df["section"] = df["url"].map(section)
    groupes = df.groupby("section", as_index=False)["clics"].sum()
    groupes["part_%"] = 100 * groupes["clics"] / groupes["clics"].sum()
    return groupes.sort_values("clics", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------
# Relances
# --------------------------------------------------------------------------

@dataclass
class Relance:
    """Un sujet publié plusieurs fois, et ce que chaque version a rapporté."""

    slug: str
    versions: list[tuple[str, float, str]]  # (date, clics, url)

    @property
    def nombre(self) -> int:
        return len(self.versions)

    @property
    def cumul(self) -> float:
        return sum(clics for _, clics, _ in self.versions)

    @property
    def meilleure(self) -> float:
        return max(clics for _, clics, _ in self.versions)

    @property
    def taux_reprise(self) -> float | None:
        """Rendement de la dernière version rapporté à la première, en %."""
        origine = self.versions[0][1]
        return 100 * self.versions[-1][1] / origine if origine else None

    @property
    def epuise(self) -> bool:
        return self.nombre > RELANCES_MAX

    @property
    def derniere_date(self) -> str:
        return self.versions[-1][0]


def detecte_relances(pages: pd.DataFrame, seuil_similarite: float = 0.75) -> list[Relance]:
    """Repère les sujets publiés sous plusieurs URLs datées.

    Deux niveaux : slug identique d'abord, puis rapprochement des slugs très
    proches — les relances s'accompagnent souvent d'une réécriture du titre,
    donc d'un changement de slug.

    Limite connue : une relance dont le titre a été entièrement refondu passe
    au travers. Seule la table de redirections du site donne l'historique
    complet.
    """
    if pages.empty or "url" not in pages.columns:
        return []

    entrees: dict[str, list[tuple[str, float, str]]] = {}
    for url, clics in zip(pages["url"], pages["clics"]):
        publie, slug = decoupe_url(url)
        if publie is None or not slug:
            continue
        entrees.setdefault(slug, []).append((publie, float(clics), str(url)))

    # Rapprochement des slugs voisins.
    slugs = list(entrees)
    jetons = {s: _jetons(s.replace("-", " ")) for s in slugs}
    parent = {s: s for s in slugs}

    def racine(s: str) -> str:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for i, a in enumerate(slugs):
        for b in slugs[i + 1:]:
            if _similarite(jetons[a], jetons[b]) >= seuil_similarite:
                parent[racine(b)] = racine(a)

    regroupe: dict[str, list[tuple[str, float, str]]] = {}
    for slug, versions in entrees.items():
        regroupe.setdefault(racine(slug), []).extend(versions)

    relances = [
        Relance(slug=slug, versions=sorted(versions))
        for slug, versions in regroupe.items()
        if len(versions) > 1
    ]
    return sorted(relances, key=lambda r: r.cumul, reverse=True)


def synthese_relances(relances: list[Relance], total_clics: float) -> dict:
    """Chiffres clés sur les relances : poids, rendement, fragmentation."""
    if not relances:
        return {}
    taux = [r.taux_reprise for r in relances if r.taux_reprise is not None]
    cumul = sum(r.cumul for r in relances)
    meilleures = sum(r.meilleure for r in relances)
    return {
        "sujets": len(relances),
        "urls": sum(r.nombre for r in relances),
        "clics": cumul,
        "part_du_trafic_%": 100 * cumul / total_clics if total_clics else 0,
        "taux_reprise_median_%": pd.Series(taux).median() if taux else None,
        "sous_la_version_dorigine": sum(1 for t in taux if t < 100),
        "concentration_meilleure_%": 100 * meilleures / cumul if cumul else 0,
        "sujets_epuises": sum(1 for r in relances if r.epuise),
    }


# --------------------------------------------------------------------------
# Cartons
# --------------------------------------------------------------------------

def profil_cartons(articles: pd.DataFrame, seuil: int = SEUIL_CARTON) -> pd.DataFrame:
    """Volume publié, médiane et nombre de cartons, mois par mois."""
    if articles.empty:
        return pd.DataFrame()
    lignes = []
    for mois, groupe in articles.groupby("mois"):
        vues = groupe["vues"]
        lignes.append(
            {
                "mois": mois,
                "articles": len(groupe),
                "vues": vues.sum(),
                "mediane": vues.median(),
                "cartons": int((vues > seuil).sum()),
                "taux_carton_pour_1000": 1000 * (vues > seuil).sum() / len(groupe),
                "meilleur": vues.max(),
            }
        )
    return pd.DataFrame(lignes).sort_values("mois").reset_index(drop=True)


def concentration(articles: pd.DataFrame, rangs=(3, 10, 50)) -> dict:
    """Part de l'audience concentrée sur les N meilleurs articles."""
    if articles.empty:
        return {}
    vues = articles["vues"].sort_values(ascending=False).to_numpy()
    total = vues.sum()
    if not total:
        return {}
    resultat = {f"top{n}_%": 100 * vues[:n].sum() / total for n in rangs}
    resultat["articles"] = len(vues)
    resultat["mediane"] = float(pd.Series(vues).median())
    return resultat


def compare_sites(a: pd.DataFrame, b: pd.DataFrame, noms=("site A", "site B"),
                  periode: list[str] | None = None) -> pd.DataFrame:
    """Compare deux sites sur une même liste de mois, à périmètre identique."""
    lignes = []
    for nom, articles in zip(noms, (a, b)):
        if articles.empty:
            continue
        sous_ensemble = articles[articles["mois"].isin(periode)] if periode else articles
        if sous_ensemble.empty:
            continue
        vues = sous_ensemble["vues"]
        lignes.append(
            {
                "site": nom,
                "articles": len(sous_ensemble),
                "vues": vues.sum(),
                "mediane": vues.median(),
                "moyenne": vues.mean(),
                "cartons": int((vues > SEUIL_CARTON).sum()),
                "taux_carton_pour_1000": 1000 * (vues > SEUIL_CARTON).sum() / len(sous_ensemble),
                "meilleur": vues.max(),
            }
        )
    return pd.DataFrame(lignes)


def sujets_communs(a: pd.DataFrame, b: pd.DataFrame, seuil: int = 250_000,
                   mots_communs: int = 3) -> pd.DataFrame:
    """Sujets sur lesquels les deux sites ont fait un carton — le duel direct.

    C'est la mesure la plus parlante : à sujet identique, qui l'emporte et de
    combien.
    """
    if a.empty or b.empty:
        return pd.DataFrame()
    gauche = a[a["vues"] > seuil]
    droite = b[b["vues"] > seuil]
    jetons_d = [(_jetons(t), t, v, j) for t, v, j in
                zip(droite["titre"], droite["vues"], droite["jour"])]

    lignes = []
    for titre_g, vues_g, jour_g in zip(gauche["titre"], gauche["vues"], gauche["jour"]):
        jg = _jetons(titre_g)
        for jd, titre_d, vues_d, jour_d in jetons_d:
            commun = jg & jd
            if len(commun) >= mots_communs:
                lignes.append(
                    {
                        "mots_communs": ", ".join(sorted(commun)),
                        "date_A": jour_g,
                        "titre_A": titre_g,
                        "vues_A": vues_g,
                        "date_B": jour_d,
                        "titre_B": titre_d,
                        "vues_B": vues_d,
                        "rapport_B_sur_A": vues_d / vues_g if vues_g else None,
                        "publié_en_premier": "A" if jour_g < jour_d else "B",
                    }
                )
    if not lignes:
        return pd.DataFrame()
    return (
        pd.DataFrame(lignes)
        .sort_values("vues_B", ascending=False)
        .drop_duplicates(subset=["titre_A"])
        .reset_index(drop=True)
    )


# --------------------------------------------------------------------------
# Réservoir de relance
# --------------------------------------------------------------------------

def chaines_de_redirection(redirections: pd.DataFrame | None) -> list[tuple[set[str], int, str]]:
    """Reconstitue l'historique des relances à partir de la table de redirections.

    Chaque redirection ancienne URL -> nouvelle URL est la trace d'une relance.
    En chaînant les sauts, on obtient le nombre de sorties d'un sujet et la
    date de la dernière. C'est la source de vérité : contrairement aux exports
    Search Console, elle n'est pas plafonnée.

    Colonnes attendues : « source » et « cible ».
    """
    if redirections is None or redirections.empty:
        return []
    colonnes = {c.lower(): c for c in redirections.columns}
    source = colonnes.get("source") or list(redirections.columns)[0]
    cible = colonnes.get("cible") or colonnes.get("target") or list(redirections.columns)[1]

    suivant: dict[str, str] = {}
    for depart, arrivee in zip(redirections[source], redirections[cible]):
        d_date, d_slug = decoupe_url(depart)
        a_date, a_slug = decoupe_url(arrivee)
        if d_date and a_date and d_slug:
            suivant[f"{d_date}|{d_slug}"] = f"{a_date}|{a_slug}"

    cibles = set(suivant.values())
    chaines = []
    for depart in suivant:
        if depart in cibles:
            continue  # maillon intermédiaire : on ne part que des origines
        etapes, courant, vus = [depart], depart, {depart}
        while courant in suivant and suivant[courant] not in vus:
            courant = suivant[courant]
            vus.add(courant)
            etapes.append(courant)
        date_origine, slug_origine = etapes[0].split("|", 1)
        date_finale = etapes[-1].split("|", 1)[0]
        chaines.append((_jetons(slug_origine.replace("-", " ")), len(etapes), date_finale))
    return chaines

def reservoir(articles: pd.DataFrame, relances: list[Relance],
              aujourdhui: str, seuil: int = 250_000,
              redirections: pd.DataFrame | None = None) -> pd.DataFrame:
    """Classe l'archive par potentiel de relance.

    Le score privilégie les articles à forte performance prouvée, anciens, et
    peu ou pas relancés. Un sujet déjà relancé plus de RELANCES_MAX fois est
    écarté : les données montrent qu'il ne rend plus.

    `relances` est déduit des URLs présentes dans les exports Search Console,
    qui sont plafonnés — une relance absente du haut de classement passe donc
    inaperçue. Fournir `redirections` (colonnes « source » et « cible »)
    remplace cette estimation par l'historique réel.
    """
    if articles.empty:
        return pd.DataFrame()

    # Rapproche chaque article de l'historique de relances par similarité de titre.
    index = [(_jetons(r.slug.replace("-", " ")), r.nombre, r.derniere_date) for r in relances]
    index += chaines_de_redirection(redirections)

    lignes = []
    reference = pd.Timestamp(aujourdhui)
    for _, article in articles[articles["vues"] > seuil].iterrows():
        jetons_titre = _jetons(article["titre"])
        nb_versions, derniere = 1, article["jour"]
        meilleure_similarite = 0.0
        for jetons_source, versions, date_finale in index:
            score = _similarite(jetons_titre, jetons_source)
            if score >= 0.4 and score > meilleure_similarite:
                meilleure_similarite = score
                nb_versions, derniere = versions, max(date_finale, article["jour"])

        nb_relances = max(nb_versions - 1, 0)
        anciennete = (reference - pd.Timestamp(derniere)).days

        if nb_relances > RELANCES_MAX:
            statut = "épuisé"
        elif nb_relances == 0:
            # Formulation prudente : l'absence de relance dans les exports ne
            # prouve pas l'absence de relance. Seule la table de redirections
            # permet de l'affirmer.
            statut = "aucune relance détectée"
        else:
            statut = f"{nb_relances} relance(s)"

        # Score : performance prouvée, pondérée par le temps écoulé depuis la
        # dernière sortie et pénalisée par le nombre de relances déjà faites.
        score = (
            article["vues"]
            * min(anciennete / 365, 2.0)
            / (1 + nb_relances) ** 2
        )
        if nb_relances > RELANCES_MAX:
            score = 0.0

        lignes.append(
            {
                "titre": article["titre"],
                "auteur": article.get("auteur", ""),
                "publié_le": article["jour"],
                "vues_cumulées": article["vues"],
                "relances_détectées": nb_relances,
                "dernière_sortie": derniere,
                "jours_depuis": anciennete,
                "statut": statut,
                "score": score,
            }
        )
    return (
        pd.DataFrame(lignes)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )
