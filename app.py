"""Tableau de bord d'audience éditoriale — Journal du Geek.

Rejoue chaque mois le diagnostic construit à partir des exports Search Console
et des exports d'articles du CMS : d'où vient le trafic, ce que rapportent les
relances, et quels articles de l'archive méritent d'être ressortis.

Lancement :  streamlit run app.py
Les fichiers peuvent être déposés dans l'interface ou placés dans ./data.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from jdg import (
    RELANCES_MAX,
    SEUIL_CARTON,
    charger_articles,
    charger_gsc,
    charger_redirections,
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

st.set_page_config(page_title="Audience — Journal du Geek", layout="wide")

DOSSIER_DONNEES = Path("data")
COULEUR = {"Discover": "#e4572e", "Web": "#2e86ab", "Google Actualités": "#8a6fb0"}


# --------------------------------------------------------------------------
# Chargement
# --------------------------------------------------------------------------

def _fichier_temporaire(televerse) -> Path:
    """Écrit un fichier téléversé sur disque pour que les parseurs le lisent."""
    suffixe = Path(televerse.name).suffix
    cible = Path(tempfile.mkdtemp()) / f"upload{suffixe}"
    cible.write_bytes(televerse.getbuffer())
    return cible


@st.cache_data(show_spinner=False)
def _charge_gsc(chemins: tuple[str, ...]):
    exports = []
    for chemin in chemins:
        export = charger_gsc(chemin)
        if not (export.dates.empty and export.pages.empty):
            exports.append(export)
    return exports


@st.cache_data(show_spinner=False)
def _charge_articles(chemins: tuple[str, ...]) -> pd.DataFrame:
    return charger_articles(*chemins) if chemins else pd.DataFrame()


def _depuis_dossier(motifs: list[str]) -> list[str]:
    if not DOSSIER_DONNEES.exists():
        return []
    trouves: list[str] = []
    for motif in motifs:
        trouves += [str(p) for p in sorted(DOSSIER_DONNEES.glob(motif))]
    return trouves


st.sidebar.title("Données")
st.sidebar.caption(
    "Dépose les exports ici, ou place-les dans le dossier `data/` "
    "à côté de l'application."
)

depots_gsc = st.sidebar.file_uploader(
    "Exports Search Console (.zip)",
    type=["zip"],
    accept_multiple_files=True,
    help="Performances → Résultats de recherche ou Discover → Exporter → CSV",
)
depots_articles = st.sidebar.file_uploader(
    "Articles du site (.csv)",
    type=["csv"],
    accept_multiple_files=True,
    help="Export « Auteur_Tous » du CMS",
)
depots_concurrent = st.sidebar.file_uploader(
    "Articles d'un concurrent (.csv)",
    type=["csv"],
    accept_multiple_files=True,
)
depot_redirections = st.sidebar.file_uploader(
    "Table de redirections (.csv) — optionnel",
    type=["csv"],
    help="Sans elle, l'historique des relances reste une estimation.",
)

chemins_gsc = tuple(
    [str(_fichier_temporaire(f)) for f in depots_gsc] or _depuis_dossier(["*.zip"])
)
chemins_articles = tuple(
    [str(_fichier_temporaire(f)) for f in depots_articles]
    or _depuis_dossier(["Auteur_Tous*.csv", "articles*.csv"])
)
chemins_concurrent = tuple(
    str(_fichier_temporaire(f)) for f in depots_concurrent
) or tuple(_depuis_dossier(["concurrent*.csv"]))

exports = _charge_gsc(chemins_gsc)
articles = _charge_articles(chemins_articles)
concurrent = _charge_articles(chemins_concurrent)
redirections = (
    charger_redirections(_fichier_temporaire(depot_redirections))
    if depot_redirections
    else pd.DataFrame()
)

st.title("Audience éditoriale")

if not exports and articles.empty:
    st.info(
        "Dépose au moins un export pour commencer.\n\n"
        "**Search Console** — Performances → *Résultats de recherche* puis "
        "*Discover*, plage de 16 mois, bouton Exporter, format CSV. "
        "Un export par mois donne une lecture bien plus fine.\n\n"
        "**Articles** — l'export « Auteur_Tous » du CMS, un fichier par année."
    )
    st.stop()

# Un export par canal : on garde le plus large quand il y a des doublons.
par_canal: dict[str, list] = {}
for export in exports:
    par_canal.setdefault(export.canal, []).append(export)

onglets = st.tabs(
    ["Vue d'ensemble", "Cartons", "Relances", "Réservoir", "Concurrent", "Méthode"]
)


# --------------------------------------------------------------------------
# Vue d'ensemble
# --------------------------------------------------------------------------

with onglets[0]:
    if not exports:
        st.info("Cet onglet a besoin des exports Search Console.")
    else:
        series = []
        for canal, groupe in par_canal.items():
            plus_large = max(groupe, key=lambda e: len(e.dates))
            mensuel = serie_mensuelle(plus_large.dates)
            if mensuel.empty:
                continue
            mensuel["canal"] = canal
            series.append(mensuel)

        if series:
            tout = pd.concat(series, ignore_index=True)

            st.subheader("Clics par canal et par mois")
            st.caption(
                "Le premier et le dernier mois sont souvent incomplets : "
                "la Search Console couvre 16 mois glissants."
            )
            graphe = (
                alt.Chart(tout)
                .mark_line(point=True, strokeWidth=2.5)
                .encode(
                    x=alt.X("mois:O", title=None),
                    y=alt.Y("clics:Q", title="clics", axis=alt.Axis(format="~s")),
                    color=alt.Color(
                        "canal:N",
                        title="canal",
                        scale=alt.Scale(
                            domain=list(COULEUR), range=list(COULEUR.values())
                        ),
                    ),
                    tooltip=["mois", "canal", alt.Tooltip("clics:Q", format=",.0f")],
                )
                .properties(height=340)
            )
            st.altair_chart(graphe, width="stretch")

            colonnes = st.columns(len(par_canal) or 1)
            for colonne, (canal, groupe) in zip(colonnes, par_canal.items()):
                mensuel = tout[tout["canal"] == canal].sort_values("mois")
                if len(mensuel) < 2:
                    continue
                # On compare les deux derniers mois complets.
                dernier, avant = mensuel.iloc[-1], mensuel.iloc[-2]
                variation = (
                    100 * (dernier["clics"] - avant["clics"]) / avant["clics"]
                    if avant["clics"]
                    else 0
                )
                colonne.metric(
                    f"{canal} — {dernier['mois']}",
                    f"{dernier['clics']:,.0f}".replace(",", " "),
                    f"{variation:+.1f} % vs mois précédent",
                )

            st.subheader("Évolution par rapport à l'année précédente")
            st.caption(
                "La comparaison d'une année sur l'autre neutralise la "
                "saisonnalité — c'est elle qui dit s'il se passe quelque chose."
            )
            for canal in par_canal:
                mensuel = tout[tout["canal"] == canal]
                annuel = evolution_annuelle(mensuel)
                if annuel.empty:
                    continue
                st.markdown(f"**{canal}**")
                st.dataframe(
                    annuel.assign(
                        precedent=lambda d: d["precedent"].map("{:,.0f}".format),
                        actuel=lambda d: d["actuel"].map("{:,.0f}".format),
                        **{"evolution_%": lambda d: d["evolution_%"].map("{:+.1f} %".format)},
                    ),
                    width="stretch",
                    hide_index=True,
                )

        # Stock et flux, pour les exports mensuels.
        mensuels = [e for e in exports if e.mois and not e.pages.empty]
        if mensuels:
            st.subheader("Production du mois, stock et sections sans date")
            st.caption(
                "Une relance porte la date du jour : elle est donc comptée dans "
                "« production du mois », pas dans le stock. L'onglet Relances "
                "l'isole."
            )
            lignes = [
                stock_et_flux(export.pages, export.mois) for export in sorted(mensuels, key=lambda e: e.mois)
            ]
            repartition = pd.DataFrame([ligne for ligne in lignes if ligne])
            if not repartition.empty:
                st.dataframe(
                    repartition[
                        ["mois", "total", "part_neuf_%", "part_stock_%", "part_sans_date_%"]
                    ].style.format(
                        {
                            "total": "{:,.0f}",
                            "part_neuf_%": "{:.1f} %",
                            "part_stock_%": "{:.1f} %",
                            "part_sans_date_%": "{:.1f} %",
                        }
                    ),
                    width="stretch",
                    hide_index=True,
                )

        # Poids des sections, sur l'export le plus large.
        avec_pages = [e for e in exports if not e.pages.empty]
        if avec_pages:
            plus_large = max(avec_pages, key=lambda e: len(e.pages))
            st.subheader(f"Poids des sections — {plus_large.canal}")
            st.dataframe(
                poids_des_sections(plus_large.pages).style.format(
                    {"clics": "{:,.0f}", "part_%": "{:.1f} %"}
                ),
                width="stretch",
                hide_index=True,
            )


# --------------------------------------------------------------------------
# Cartons
# --------------------------------------------------------------------------

with onglets[1]:
    if articles.empty:
        st.info("Cet onglet a besoin de l'export d'articles du CMS.")
    else:
        seuil = st.slider(
            "Seuil du carton (vues)", 100_000, 1_000_000, SEUIL_CARTON, 50_000
        )
        profil = profil_cartons(articles, seuil)

        st.subheader("Le socle tient-il, ou est-ce le sommet qui bouge ?")
        st.caption(
            "La médiane décrit l'article ordinaire, le nombre de cartons décrit "
            "les succès. Les deux bougent rarement ensemble — et c'est celui qui "
            "bouge qui désigne le problème."
        )

        gauche, droite = st.columns(2)
        with gauche:
            st.altair_chart(
                alt.Chart(profil)
                .mark_bar(color="#e4572e")
                .encode(
                    x=alt.X("mois:O", title=None),
                    y=alt.Y("cartons:Q", title=f"articles > {seuil:,.0f} vues".replace(",", " ")),
                    tooltip=["mois", "cartons", alt.Tooltip("meilleur:Q", format=",.0f")],
                )
                .properties(height=280, title="Cartons par mois"),
                width="stretch",
            )
        with droite:
            st.altair_chart(
                alt.Chart(profil)
                .mark_line(point=True, color="#2e86ab", strokeWidth=2.5)
                .encode(
                    x=alt.X("mois:O", title=None),
                    y=alt.Y("mediane:Q", title="vues"),
                    tooltip=["mois", alt.Tooltip("mediane:Q", format=",.0f"), "articles"],
                )
                .properties(height=280, title="Médiane de l'article ordinaire"),
                width="stretch",
            )

        st.dataframe(
            profil.style.format(
                {
                    "vues": "{:,.0f}",
                    "mediane": "{:,.0f}",
                    "meilleur": "{:,.0f}",
                    "taux_carton_pour_1000": "{:.2f}",
                }
            ),
            width="stretch",
            hide_index=True,
        )

        st.subheader("Qui signe les cartons")
        succes = articles[articles["vues"] > seuil]
        if succes.empty:
            st.write("Aucun article au-dessus du seuil sur la période.")
        else:
            par_auteur = (
                succes.groupby("auteur")
                .agg(cartons=("vues", "size"), vues=("vues", "sum"))
                .sort_values("cartons", ascending=False)
                .reset_index()
            )
            st.dataframe(
                par_auteur.style.format({"vues": "{:,.0f}"}),
                width="stretch",
                hide_index=True,
            )
            st.markdown("**Les cartons, du plus récent au plus ancien**")
            st.dataframe(
                succes.sort_values("jour", ascending=False)[
                    ["jour", "vues", "auteur", "titre"]
                ].style.format({"vues": "{:,.0f}"}),
                width="stretch",
                hide_index=True,
            )


# --------------------------------------------------------------------------
# Relances
# --------------------------------------------------------------------------

with onglets[2]:
    avec_pages = [e for e in exports if not e.pages.empty]
    if not avec_pages:
        st.info("Cet onglet a besoin d'un export Search Console contenant l'onglet Pages.")
    else:
        choix = st.selectbox(
            "Export analysé",
            options=range(len(avec_pages)),
            format_func=lambda i: f"{avec_pages[i].canal} — {avec_pages[i].source}",
        )
        export = avec_pages[choix]
        relances = detecte_relances(export.pages)
        resume = synthese_relances(relances, export.pages["clics"].sum())

        if not resume:
            st.write("Aucune relance détectée dans cet export.")
        else:
            a, b, c, d = st.columns(4)
            a.metric("Sujets relancés", resume["sujets"])
            b.metric("Part du trafic", f"{resume['part_du_trafic_%']:.1f} %")
            mediane = resume["taux_reprise_median_%"]
            c.metric(
                "Reprise médiane",
                f"{mediane:.0f} %" if mediane is not None else "—",
                help="Rendement de la dernière version rapporté à la première.",
            )
            d.metric(
                "Sujets épuisés",
                resume["sujets_epuises"],
                help=f"Plus de {RELANCES_MAX} relances : le rendement s'effondre.",
            )

            st.caption(
                f"Les {resume['sujets']} sujets relancés occupent "
                f"{resume['urls']} URLs distinctes. La meilleure version de chaque "
                f"sujet capte {resume['concentration_meilleure_%']:.0f} % des clics "
                "cumulés : le reste est dispersé sur les autres versions."
            )

            epuises = [r for r in relances if r.epuise]
            if epuises:
                st.warning(
                    f"**{len(epuises)} sujets ont dépassé {RELANCES_MAX} relances.** "
                    "Les données montrent qu'au-delà le rendement s'effondre — "
                    "à retirer de la rotation : "
                    + ", ".join(r.slug[:40] for r in epuises[:6])
                    + ("…" if len(epuises) > 6 else "")
                )

            st.subheader("Historique par sujet")
            lignes = []
            for relance in relances:
                lignes.append(
                    {
                        "sujet": relance.slug[:70],
                        "versions": relance.nombre,
                        "cumul": relance.cumul,
                        "meilleure": relance.meilleure,
                        "reprise_%": relance.taux_reprise,
                        "dernière": relance.derniere_date,
                        "statut": "épuisé" if relance.epuise else "en rotation",
                    }
                )
            st.dataframe(
                pd.DataFrame(lignes).style.format(
                    {
                        "cumul": "{:,.0f}",
                        "meilleure": "{:,.0f}",
                        "reprise_%": "{:.0f} %",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

            st.subheader("Détail d'un sujet")
            index = st.selectbox(
                "Sujet",
                options=range(len(relances)),
                format_func=lambda i: relances[i].slug[:80],
            )
            detail = pd.DataFrame(
                [
                    {"date": date, "clics": clics, "url": url}
                    for date, clics, url in relances[index].versions
                ]
            )
            st.altair_chart(
                alt.Chart(detail)
                .mark_bar(color="#e4572e")
                .encode(
                    x=alt.X("date:O", title=None),
                    y=alt.Y("clics:Q", axis=alt.Axis(format="~s")),
                    tooltip=["date", alt.Tooltip("clics:Q", format=",.0f"), "url"],
                )
                .properties(height=240),
                width="stretch",
            )
            st.dataframe(
                detail.style.format({"clics": "{:,.0f}"}),
                width="stretch",
                hide_index=True,
            )


# --------------------------------------------------------------------------
# Réservoir
# --------------------------------------------------------------------------

with onglets[3]:
    avec_pages = [e for e in exports if not e.pages.empty]
    if articles.empty or not avec_pages:
        st.info("Cet onglet a besoin de l'export d'articles et d'un export Search Console.")
    else:
        st.subheader("Que ressortir cette semaine")
        st.caption(
            "Classement des articles à performance prouvée, par potentiel de "
            "relance : forte audience passée, sortie ancienne, peu de relances "
            "déjà faites."
        )
        if redirections.empty:
            st.warning(
                "**Sans table de redirections, l'historique des relances est une "
                "estimation.** Il est reconstitué depuis les URLs présentes dans "
                "les exports Search Console, qui sont plafonnés à quelques "
                "centaines de lignes — une relance absente du haut de classement "
                "passe inaperçue, et l'article apparaît alors à tort comme jamais "
                "ressorti. Dépose la table de redirections dans la barre latérale "
                "pour fiabiliser cette page."
            )

        plus_large = max(avec_pages, key=lambda e: len(e.pages))
        relances = detecte_relances(plus_large.pages)
        seuil_reservoir = st.slider(
            "Audience minimale de l'article d'origine", 50_000, 1_000_000, 250_000, 25_000
        )
        aujourdhui = st.date_input("Date de référence", value=pd.Timestamp.today())

        classement = reservoir(
            articles,
            relances,
            str(aujourdhui),
            seuil_reservoir,
            redirections if not redirections.empty else None,
        )
        if classement.empty:
            st.write("Aucun article au-dessus du seuil.")
        else:
            masquer = st.checkbox("Masquer les sujets épuisés", value=True)
            affichage = classement[classement["statut"] != "épuisé"] if masquer else classement
            st.dataframe(
                affichage.style.format(
                    {"vues_cumulées": "{:,.0f}", "score": "{:,.0f}"}
                ),
                width="stretch",
                hide_index=True,
            )
            st.download_button(
                "Télécharger le classement (CSV)",
                affichage.to_csv(index=False).encode("utf-8-sig"),
                file_name="reservoir_relances.csv",
                mime="text/csv",
            )


# --------------------------------------------------------------------------
# Concurrent
# --------------------------------------------------------------------------

with onglets[4]:
    if articles.empty or concurrent.empty:
        st.info(
            "Dépose l'export d'articles d'un concurrent dans la barre latérale "
            "pour activer la comparaison."
        )
    else:
        mois_communs = sorted(set(articles["mois"]) & set(concurrent["mois"]))
        selection = st.multiselect(
            "Mois comparés (périmètre identique des deux côtés)",
            options=mois_communs,
            default=mois_communs,
        )
        if selection:
            st.subheader("À périmètre identique")
            comparaison = compare_sites(
                articles, concurrent, ("Mon site", "Concurrent"), selection
            )
            st.dataframe(
                comparaison.style.format(
                    {
                        "vues": "{:,.0f}",
                        "mediane": "{:,.0f}",
                        "moyenne": "{:,.0f}",
                        "meilleur": "{:,.0f}",
                        "taux_carton_pour_1000": "{:.2f}",
                    }
                ),
                width="stretch",
                hide_index=True,
            )
            st.caption(
                "Deux lectures à distinguer : la **médiane** dit qui écrit le "
                "mieux au quotidien, le **taux de carton** dit qui déclenche le "
                "plus de succès. Ce sont deux problèmes différents."
            )

            gauche, droite = st.columns(2)
            for colonne, (nom, jeu) in zip(
                (gauche, droite), (("Mon site", articles), ("Concurrent", concurrent))
            ):
                sous_ensemble = jeu[jeu["mois"].isin(selection)]
                chiffres = concentration(sous_ensemble)
                if chiffres:
                    colonne.markdown(f"**{nom}** — concentration de l'audience")
                    colonne.write(
                        {
                            "top 3": f"{chiffres['top3_%']:.1f} %",
                            "top 10": f"{chiffres['top10_%']:.1f} %",
                            "top 50": f"{chiffres['top50_%']:.1f} %",
                        }
                    )

        st.subheader("Duels : mêmes sujets, deux sites")
        st.caption(
            "Les sujets sur lesquels les deux rédactions ont fait un succès. "
            "C'est la comparaison la plus honnête qui soit : mêmes lecteurs, "
            "même actualité, même semaine."
        )
        duels = sujets_communs(articles, concurrent)
        if duels.empty:
            st.write("Aucun sujet commun détecté au-dessus du seuil.")
        else:
            st.dataframe(
                duels.style.format(
                    {
                        "vues_A": "{:,.0f}",
                        "vues_B": "{:,.0f}",
                        "rapport_B_sur_A": "×{:.2f}",
                    }
                ),
                width="stretch",
                hide_index=True,
            )


# --------------------------------------------------------------------------
# Méthode
# --------------------------------------------------------------------------

with onglets[5]:
    st.markdown(
        f"""
### Ce que mesure chaque page

**Vue d'ensemble** — répartition des clics entre Discover, Search et Google
Actualités, et comparaison d'une année sur l'autre. Un canal qui monte pendant
qu'un autre s'effondre ne se voit pas dans un total.

**Cartons** — un article au-dessus de {SEUIL_CARTON:,.0f} vues porte son mois à
lui seul. On suit séparément la médiane, qui décrit la production ordinaire, et
le nombre de cartons. Quand la médiane tient et que les cartons disparaissent,
le problème n'est ni le volume ni la qualité d'écriture.

**Relances** — un sujet republié sous une nouvelle date. Le rendement décroît
vite : au-delà de {RELANCES_MAX} relances, l'expérience montre que le sujet ne
rapporte plus. L'onglet signale les sujets épuisés et mesure la dispersion, la
meilleure version d'un sujet ne captant qu'une partie des clics cumulés.

**Réservoir** — les articles anciens à forte audience prouvée, classés par
potentiel de ressortie.

**Concurrent** — comparaison à périmètre identique, et surtout les duels sur
sujets communs, qui isolent l'effet du site de celui du sujet.

### Limites à garder en tête

- Les exports de l'interface Search Console sont **plafonnés** à quelques
  centaines de lignes par onglet. L'onglet Dates, lui, est complet.
- Une relance crée une URL portant la date du jour : elle compte donc comme
  production nouvelle dans le calcul stock/flux.
- La détection des relances repose sur la ressemblance des adresses. Une
  refonte de titre change l'adresse et peut passer au travers — **seule la
  table de redirections donne l'historique réel**.
- Les vues du CMS sont **cumulées depuis la publication**. Un article récent
  est donc mécaniquement sous-estimé face à un article ancien, et les
  comparaisons d'une année sur l'autre exagèrent la baisse. Les données Search
  Console, bornées dans le temps, ne souffrent pas de ce biais.

### Ce que l'outil ne fait pas

Il ne mesure pas les canaux hors Google — direct, réseaux sociaux, referrals.
Il ne détecte pas non plus en temps réel qu'un article décolle : la Search
Console est décalée de deux à trois jours. Cette partie demande une source
d'audience temps réel.
"""
    )
