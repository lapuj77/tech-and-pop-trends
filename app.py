"""Tableau de bord d'audience éditoriale — Journal du Geek.

Rejoue chaque mois le diagnostic construit à partir des exports Search Console
et des exports d'articles du CMS : d'où vient le trafic, ce que rapportent les
relances, et quels articles de l'archive méritent d'être ressortis.

Lancement :  streamlit run app.py
Les fichiers se déposent dans l'interface, dans ./data, ou simplement
à côté de l'application.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from jdg import (
    FLUX_PAR_DEFAUT,
    MODELE_PAR_DEFAUT,
    VeilleIndisponible,
    audience_fidele,
    RELANCES_MAX,
    SEUIL_CARTON,
    angles_a_retravailler,
    charger_articles,
    charger_gsc,
    charger_marfeel,
    charger_redirections,
    cherche_sujets,
    collecte,
    compare_periodes,
    compare_sites,
    concentration,
    detecte_relances,
    evolution_annuelle,
    granularite_dominante,
    mix_canaux,
    palette_chaude,
    palette_froide,
    poids_des_sections,
    profil_cartons,
    profil_succes,
    rendement_des_gabarits,
    reservoir,
    serie_mensuelle,
    series_hebdomadaires,
    stock_et_flux,
    suggere_titres,
    sujets_communs,
    sujets_orphelins,
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
def _charge_marfeel(chemins: tuple[str, ...]) -> pd.DataFrame:
    return charger_marfeel(*chemins) if chemins else pd.DataFrame()


@st.cache_data(show_spinner=False)
def _charge_articles(chemins: tuple[str, ...]) -> pd.DataFrame:
    return charger_articles(*chemins) if chemins else pd.DataFrame()


# On cherche les exports dans `data/` et, à défaut, à côté de l'application :
# déposer les fichiers directement dans le dossier décompressé est le réflexe
# naturel, et rien ne justifie de le sanctionner.
DOSSIERS_CHERCHES = (DOSSIER_DONNEES, Path("."))


def _depuis_dossier(motifs: list[str]) -> list[str]:
    trouves: list[str] = []
    vus: set[str] = set()
    for dossier in DOSSIERS_CHERCHES:
        if not dossier.exists():
            continue
        for motif in motifs:
            for chemin in sorted(dossier.glob(motif)):
                cle = chemin.name.lower()
                if cle in vus:
                    continue     # même fichier rangé aux deux endroits
                vus.add(cle)
                trouves.append(str(chemin))
    return trouves


st.sidebar.title("Données")
st.sidebar.caption(
    "Dépose les exports ici, ou pose-les dans le dossier de l'application — "
    "à la racine ou dans `data/`, les deux sont lus au démarrage."
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
depots_marfeel = st.sidebar.file_uploader(
    "Exports Marfeel par canal (.csv)",
    type=["csv"],
    accept_multiple_files=True,
    help="Un fichier par canal. Le canal se lit dans le NOM du fichier "
         "— nomme-les jdgdiscover2026.csv, pcdirect2025.csv…",
)
depot_redirections = st.sidebar.file_uploader(
    "Table de redirections (.csv) — optionnel",
    type=["csv"],
    help="Sans elle, l'historique des relances reste une estimation.",
)

st.sidebar.divider()
st.sidebar.subheader("Veille par l'API Claude")
st.sidebar.caption(
    "Nécessaire au seul onglet **Viviers → Veille**. Tout le reste de l'outil "
    "fonctionne sans. La clé n'est pas enregistrée : elle vit le temps de la "
    "session, et rien de tes données d'audience n'est envoyé — seuls les titres "
    "et le profil de succès partent dans la requête."
)
cle_api = st.sidebar.text_input(
    "Clé d'API Anthropic",
    type="password",
    placeholder="sk-ant-…",
    help="À créer sur console.anthropic.com. Facturée à l'usage, "
         "quelques centimes par relevé.",
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

chemins_marfeel = tuple(
    [str(_fichier_temporaire(f)) for f in depots_marfeel]
    or _depuis_dossier(["*discover*.csv", "*direct*.csv", "*dark*.csv",
                        "*google*.csv", "*news*.csv"])
)

exports = _charge_gsc(chemins_gsc)
articles = _charge_articles(chemins_articles)
concurrent = _charge_articles(chemins_concurrent)
marfeel = _charge_marfeel(chemins_marfeel)
redirections = (
    charger_redirections(_fichier_temporaire(depot_redirections))
    if depot_redirections
    else pd.DataFrame()
)

st.title("Audience éditoriale")

if not exports and articles.empty and marfeel.empty:
    st.info(
        "Dépose au moins un export pour commencer.\n\n"
        "**Search Console** — Performances → *Résultats de recherche* puis "
        "*Discover*, plage de 16 mois, bouton Exporter, format CSV. "
        "Un export par mois donne une lecture bien plus fine.\n\n"
        "**Articles** — l'export « Auteur_Tous » du CMS, un fichier par année.\n\n"
        "**Marfeel** — un export par source d'acquisition, le canal étant "
        "déduit du nom du fichier."
    )
    st.stop()

# Un export par canal : on garde le plus large quand il y a des doublons.
par_canal: dict[str, list] = {}
for export in exports:
    par_canal.setdefault(export.canal, []).append(export)

onglets = st.tabs(
    ["Vue d'ensemble", "Canaux", "Cartons", "Relances", "Réservoir",
     "Concurrent", "Viviers", "Méthode"]
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
# Canaux d'acquisition
# --------------------------------------------------------------------------

with onglets[1]:
    if marfeel.empty:
        st.info(
            "Cet onglet a besoin des exports Marfeel filtrés par source.\n\n"
            "Dans Marfeel : filtre **Traffic source**, une seule case cochée à la "
            "fois, plage la plus large possible, puis export. Le canal n'apparaît "
            "nulle part dans le CSV — **il est déduit du nom du fichier**, alors "
            "nomme-les `jdgdiscover2026.csv`, `pcdirect2025.csv`, etc."
        )
    else:
        grain = granularite_dominante(marfeel)
        sites = sorted(marfeel["site"].unique())
        st.caption(
            f"{marfeel['fichier'].nunique()} fichiers · "
            f"{', '.join(sites)} · granularité retenue : **{grain}**. "
            "Les fichiers d'une autre granularité sont écartés des totaux — les "
            "additionner compterait les mêmes journées deux fois."
        )
        if "inconnu" in sites or "inconnu" in marfeel["canal"].unique():
            st.warning(
                "Certains fichiers n'ont pas pu être rattachés à un site ou à un "
                "canal d'après leur nom. Renomme-les selon la convention "
                "`<site><canal><année>.csv` — sinon leurs données sont regroupées "
                "sous « inconnu » et faussent les répartitions."
            )

        st.subheader("D'où vient le trafic")
        colonnes = st.columns(len(sites))
        for colonne, site in zip(colonnes, sites):
            mix = mix_canaux(marfeel, site)
            if mix.empty:
                continue
            colonne.markdown(f"**{site}**")
            colonne.dataframe(
                mix[["canal", "pages_vues", "part_%", "pages_par_visiteur", "engagement_s"]]
                .style.format({
                    "pages_vues": "{:,.0f}", "part_%": "{:.1f} %",
                    "pages_par_visiteur": "{:.2f}", "engagement_s": "{:.0f} s",
                }),
                width="stretch", hide_index=True,
            )
        st.caption(
            "Le nombre de pages par visiteur sépare l'acquisition de la fidélité : "
            "au-dessus de 5, on lit un lectorat qui revient ; autour de 1,5, on lit "
            "du trafic de passage."
        )

        st.subheader("Comparer deux périodes")
        st.caption(
            "Prends deux périodes de même longueur, sinon la comparaison n'a pas "
            "de sens. Par défaut : les sept premiers mois de chaque année."
        )
        dates = sorted(marfeel["date"].unique())
        c1, c2, c3, c4 = st.columns(4)
        a1 = c1.text_input("Période A, début", dates[0])
        a2 = c2.text_input("Période A, fin", min(d for d in dates if d >= dates[0][:4] + "-07-21")
                           if any(d >= dates[0][:4] + "-07-21" for d in dates) else dates[len(dates)//2])
        b1 = c3.text_input("Période B, début", dates[len(dates)//2])
        b2 = c4.text_input("Période B, fin", dates[-1])
        comparaison = compare_periodes(marfeel, (a1, a2), (b1, b2))
        if comparaison.empty:
            st.write("Aucune donnée sur ces périodes.")
        else:
            for site in sites:
                sous = comparaison[comparaison["site"] == site]
                if sous.empty:
                    continue
                st.markdown(f"**{site}**")
                st.dataframe(
                    sous[["canal", "période_A", "période_B", "evolution_%"]]
                    .sort_values("evolution_%", ascending=False)
                    .style.format({
                        "période_A": "{:,.0f}", "période_B": "{:,.0f}",
                        "evolution_%": "{:+.0f} %",
                    }),
                    width="stretch", hide_index=True,
                )

        st.subheader("Un canal, les sites superposés")
        canaux = sorted(c for c in marfeel["canal"].unique() if c != "inconnu")
        choix = st.selectbox("Canal", canaux,
                             index=canaux.index("Discover") if "Discover" in canaux else 0)
        serie = series_hebdomadaires(marfeel, choix)
        if not serie.empty:
            long = serie.melt("date", var_name="site", value_name="pages_vues").dropna()
            st.altair_chart(
                alt.Chart(long)
                .mark_line(strokeWidth=2)
                .encode(
                    x=alt.X("date:T", title=None),
                    y=alt.Y("pages_vues:Q", title="pages vues", axis=alt.Axis(format="~s")),
                    color=alt.Color("site:N", title=None),
                    tooltip=["date:T", "site:N", alt.Tooltip("pages_vues:Q", format=",.0f")],
                )
                .properties(height=380),
                width="stretch",
            )

        st.subheader("L'audience qui revient d'elle-même")
        st.caption(
            "Le canal direct est le seul qui mesure un actif plutôt qu'une "
            "acquisition. On le suit en visiteurs et en engagement — jamais en "
            "pages vues seules, qu'un seul gros succès suffit à faire varier."
        )
        fidele = audience_fidele(marfeel)
        if fidele.empty:
            st.write("Aucun fichier « direct » chargé.")
        else:
            st.dataframe(
                fidele[["site", "annee", "visiteurs_par_periode", "engagement_s", "periodes"]]
                .style.format({
                    "visiteurs_par_periode": "{:,.0f}", "engagement_s": "{:.0f} s",
                }),
                width="stretch", hide_index=True,
            )


# --------------------------------------------------------------------------
# Cartons
# --------------------------------------------------------------------------

with onglets[2]:
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

with onglets[3]:
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

with onglets[4]:
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

with onglets[5]:
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
# Viviers de sujets
# --------------------------------------------------------------------------

with onglets[6]:
    if articles.empty:
        st.info("Cet onglet a besoin de l'export d'articles du CMS.")
    else:
        profil = profil_succes(articles)

        st.caption(
            f"Profil calculé sur {len(articles):,} articles — ".replace(",", " ")
            + f"moyenne du site : {profil.taux_moyen:.2f} carton pour 1 000 articles. "
            "Tout ce qui suit est mesuré ici, sur ce site, et non repris de bonnes "
            "pratiques générales."
        )

        froide, chaude, veille, neufs, formuler = st.tabs(
            ["Froid — l'archive", "Chaud — l'actualité", "Veille — par Claude",
             "Nouveaux — les écarts", "Formuler — les titres"]
        )

        # ---- froid ----
        with froide:
            st.subheader("Que ressortir")
            st.caption(
                "Sujets à audience prouvée, endormis depuis assez longtemps pour "
                "reprendre, et écartés dès qu'ils ont épuisé leurs relances."
            )
            avec_pages = [e for e in exports if not e.pages.empty]
            relances = detecte_relances(
                max(avec_pages, key=lambda e: len(e.pages)).pages
            ) if avec_pages else []
            if redirections.empty:
                st.warning(
                    "Sans table de redirections, les relances déjà faites sont "
                    "estimées depuis les exports Search Console, qui sont plafonnés. "
                    "Un sujet peut donc apparaître comme jamais ressorti alors qu'il "
                    "est épuisé — vérifie avant de le programmer."
                )
            gauche, droite = st.columns(2)
            seuil_froid = gauche.slider("Audience minimale d'origine", 50_000, 1_000_000, 200_000, 25_000)
            sommeil = droite.slider("Sommeil minimal (jours)", 30, 730, 180, 30)
            froid = palette_froide(
                articles, profil, relances, pd.Timestamp.today(),
                seuil_froid, sommeil, redirections if not redirections.empty else None,
            )
            if froid.empty:
                st.write("Aucun sujet ne remplit ces conditions.")
            else:
                st.dataframe(
                    froid.head(40).style.format(
                        {"vues_prouvées": "{:,.0f}", "score": "{:,.0f}"}
                    ),
                    width="stretch", hide_index=True,
                )
                st.download_button(
                    "Télécharger (CSV)", froid.to_csv(index=False).encode("utf-8-sig"),
                    "vivier_froid.csv", "text/csv",
                )

        # ---- chaud ----
        with chaude:
            st.subheader("Ce qui bouge maintenant, filtré par ton profil")
            st.caption(
                "Chaque sujet d'actualité est noté selon sa ressemblance aux succès "
                "passés du site, la famille à laquelle il appartient et la forme de "
                "son titre. L'ordre n'est pas celui de l'actualité, c'est celui du "
                "potentiel ici."
            )
            if st.button("Relever les flux"):
                with st.spinner("Lecture des flux…"):
                    st.session_state["collecte"] = collecte()

            releve = st.session_state.get("collecte")
            if releve is None:
                st.info(
                    "Clique sur « Relever les flux » pour interroger Google Trends "
                    "et Google Actualités.\n\n"
                    "Flux interrogés : " + ", ".join(FLUX_PAR_DEFAUT)
                )
            else:
                if releve.echecs:
                    st.error(
                        "Flux injoignables — souvent une restriction réseau, pas une "
                        "absence d'actualité :\n"
                        + "\n".join(f"- **{nom}** : {raison}" for nom, raison in releve.echecs)
                    )
                if releve.items:
                    chaud = palette_chaude(releve.items, profil)
                    st.caption(f"{len(releve.items)} sujets relevés, classés par potentiel.")
                    st.dataframe(
                        chaud.head(40)[
                            ["score", "sujet", "famille", "pourquoi", "à_faire", "source"]
                        ].style.format({"score": "{:,.0f}"}),
                        width="stretch", hide_index=True,
                    )

        # ---- veille par l'API ----
        with veille:
            st.subheader("Claude cherche, tes données classent")
            st.caption(
                "Claude interroge le web en direct et rapporte des sujets. "
                "Chacun est ensuite repassé par le **même profil de succès** que "
                "les autres viviers : la famille, les procédés de titre et la "
                "ressemblance aux cartons passés sont mesurés sur ton historique. "
                "L'ordre affiché est donc celui du site, pas celui du modèle."
            )

            # Le rendement mesuré seul conduit le modèle vers ce qui rapporte le
            # plus par article, qui n'est pas forcément ce que le site est. Ce
            # filtre est le garde-fou éditorial.
            rendements_familles = {
                nom: (taux / profil.taux_moyen if profil.taux_moyen else 0)
                for nom, (taux, _, _) in profil.familles.items()
            }
            choisies = st.multiselect(
                "Restreindre à certaines familles (vide = toutes)",
                options=list(rendements_familles),
                format_func=lambda f: f"{f}  —  ×{rendements_familles[f]:.1f}",
                help="Le chiffre est le rendement mesuré de la famille par "
                     "rapport à la moyenne du site.",
            )
            steriles = [f for f in choisies if rendements_familles[f] == 0]
            if steriles:
                st.warning(
                    "Familles sans aucun carton mesuré : **"
                    + "**, **".join(steriles)
                    + "**. Le relevé fonctionne, mais le classement à "
                    "l'intérieur ne repose plus que sur la forme du titre et la "
                    "ressemblance aux succès d'autres familles — pas sur un "
                    "rendement de famille, puisqu'il est nul."
                )

            reglages, action = st.columns([3, 2])
            consigne = reglages.text_area(
                "Consigne du jour (facultatif)",
                placeholder="Priorité aux sorties de jeux et aux annonces "
                            "matériel. Éviter l'IA cette semaine, déjà trois "
                            "articles.",
                height=110,
            )
            combien = action.slider("Nombre de sujets", 5, 25, 10)
            recherches_max = action.slider("Recherches web maximum", 3, 20, 8)
            action.caption(
                "Compter quelques dizaines de centimes et plusieurs minutes "
                "par relevé. Le coût réel s'affiche après l'appel."
            )

            if st.button("Lancer la veille", type="primary"):
                if not cle_api:
                    st.error(
                        "Renseigne la clé d'API dans la barre latérale — "
                        "section « Veille par l'API Claude »."
                    )
                else:
                    with st.spinner(
                        "Claude cherche sur le web… compter plusieurs minutes, "
                        "et ne pas fermer la fenêtre."
                    ):
                        try:
                            st.session_state["veille"] = cherche_sujets(
                                profil, articles, cle_api=cle_api, n=combien,
                                consigne=consigne, max_recherches=recherches_max,
                                familles=choisies,
                            )
                            st.session_state.pop("veille_erreur", None)
                        except VeilleIndisponible as erreur:
                            st.session_state["veille_erreur"] = str(erreur)
                        except Exception as erreur:      # réseau, quota, clé invalide
                            st.session_state["veille_erreur"] = (
                                f"{type(erreur).__name__} : {erreur}"
                            )

            if st.session_state.get("veille_erreur"):
                st.error(st.session_state["veille_erreur"])

            resultat = st.session_state.get("veille")
            if resultat is None:
                st.info(
                    "Rien de relevé pour l'instant.\n\n"
                    f"Modèle utilisé : `{MODELE_PAR_DEFAUT}`, avec la recherche web "
                    "localisée en France. Ce qui part dans la requête : le profil "
                    "de succès mesuré, les plus gros titres du site et les derniers "
                    "publiés. **Aucun chiffre d'audience détaillé, aucune donnée "
                    "du concurrent.**"
                )
            elif resultat.table.empty:
                st.warning("Le relevé n'a produit aucune proposition exploitable.")
            else:
                if resultat.remarque:
                    st.info(resultat.remarque)
                st.caption(
                    f"{len(resultat.table)} sujets · {resultat.recherches} recherches web · "
                    f"{resultat.tours} allers-retours · {resultat.jetons:,} jetons "
                    f"(dont {resultat.jetons_cache_lecture:,} relus en cache) · "
                    f"coût estimé {resultat.cout:.2f} $".replace(",", " ")
                )

                for _, ligne in resultat.table.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**{ligne['titre_proposé']}**")
                        st.write(ligne["sujet"])
                        alerte = ""
                        if ligne["déjà_traité"] >= 0.3:
                            alerte = (f"  ·  ⚠️ ressemble à {ligne['déjà_traité']:.0%} "
                                      "à un article déjà publié")
                        st.caption(
                            f"{ligne['fraîcheur']}  ·  famille mesurée : "
                            f"{ligne['famille_mesurée']}  ·  "
                            f"{ligne['caractères']} caractères{alerte}"
                        )
                        st.caption(f"**Pourquoi maintenant** — {ligne['pourquoi_maintenant']}")
                        st.caption(f"**Angle** — {ligne['angle']}")
                        st.caption(f"**Ce que dit ton historique** — {ligne['pourquoi_ça_peut_marcher']}")
                        if ligne["à_corriger"]:
                            st.caption(f"**À corriger sur le titre** — {ligne['à_corriger']}")
                        if ligne["risque"]:
                            st.caption(f"**Risque** — {ligne['risque']}")
                        if ligne["sources"]:
                            st.caption("Sources : " + "  ·  ".join(
                                f"[{i + 1}]({u})"
                                for i, u in enumerate(ligne["sources"].split())
                            ))

                st.download_button(
                    "Télécharger le relevé (CSV)",
                    resultat.table.to_csv(index=False).encode("utf-8-sig"),
                    "veille_claude.csv", "text/csv",
                )
                if resultat.sources:
                    with st.expander(f"Les {len(resultat.sources)} pages réellement ouvertes"):
                        st.caption(
                            "Relevé depuis les résultats de recherche, pas depuis ce "
                            "que le modèle affirme avoir lu. Une source citée plus haut "
                            "et absente d'ici n'a pas été ouverte."
                        )
                        for url in resultat.sources:
                            st.write(url)
                else:
                    st.caption(
                        "Aucune page relevée dans les résultats de recherche : "
                        "les sources affichées ci-dessus sont celles que le "
                        "modèle déclare, sans contre-vérification possible."
                    )

        # ---- nouveaux ----
        with neufs:
            st.subheader("Où va la production, et ce qu'elle rapporte")
            st.caption(
                "Un rendement faible ne condamne pas une famille : elle peut servir "
                "l'identité du site ou son audience fidèle. Ce tableau dit seulement "
                "d'où viennent les cartons, et d'où ils ne viennent pas."
            )
            repartition = profil.familles_sous_exploitees()
            if not repartition.empty:
                st.dataframe(
                    repartition.style.format({
                        "part_production_%": "{:.1f} %",
                        "taux_pour_1000": "{:.2f} ‰",
                        "rendement_vs_moyenne": "×{:.1f}",
                    }),
                    width="stretch", hide_index=True,
                )

            st.subheader("Sujets à demande prouvée, jamais traités ici")
            if concurrent.empty:
                st.info(
                    "Dépose l'export d'articles d'un concurrent dans la barre "
                    "latérale pour activer cette liste."
                )
            else:
                orphelins = sujets_orphelins(articles, concurrent)
                if orphelins.empty:
                    st.write("Aucun sujet orphelin détecté au-dessus du seuil.")
                else:
                    st.dataframe(
                        orphelins.style.format({
                            "leurs_vues": "{:,.0f}", "recouvrement_max": "{:.0%}",
                        }),
                        width="stretch", hide_index=True,
                    )

            st.subheader("Sujets récents à reformuler")
            st.caption(
                "Mêmes sujets, autre angle : ces articles appartiennent à une famille "
                "identifiée mais n'emploient aucun des procédés qui fonctionnent ici."
            )
            a_reprendre = angles_a_retravailler(articles, profil)
            if a_reprendre.empty:
                st.write("Rien à signaler.")
            else:
                st.dataframe(
                    a_reprendre.style.format({"vues": "{:,.0f}"}),
                    width="stretch", hide_index=True,
                )


        # ---- formuler ----
        with formuler:
            st.subheader("Écrire le titre")
            st.caption(
                "À partir d'un sujet, l'outil propose des formulations bâties sur "
                "les tournures qui ont réellement produit des succès ici. Ce sont "
                "des amorces : la grammaire est sûre, la justesse ne l'est pas — "
                "c'est au rédacteur de trancher."
            )

            # De quoi remplir le champ sans le retaper : les sujets déjà repérés.
            propositions = [""]
            if not articles.empty:
                recents = articles.nlargest(15, "vues")["titre"].tolist()
                propositions += recents
            depart = st.selectbox(
                "Partir d'un sujet déjà identifié (facultatif)",
                propositions,
                format_func=lambda t: "— saisir librement —" if not t else t[:90],
            )
            sujet = st.text_input(
                "Sujet",
                value=depart,
                placeholder="Les nouveaux panneaux de signalisation arrivent sur les routes",
            )

            if not sujet.strip():
                st.info("Saisis un sujet, ou choisis-en un dans la liste au-dessus.")
            else:
                cible = st.slider("Longueur de titre visée", 60, 130, 85, 5)
                st.caption(
                    "Mesuré ici : sous 70 caractères le rendement tombe à la "
                    "moitié de la moyenne, entre 85 et 100 il double, entre 100 "
                    "et 125 il fait ×2,4. Aucun succès du site ne dépasse "
                    "124 caractères."
                )
                propositions = suggere_titres(sujet, articles, profil, n=10,
                                              longueur_cible=cible)
                if propositions.empty:
                    st.write("Aucun gabarit n'a assez d'historique ici pour être proposé.")
                else:
                    for _, ligne in propositions.iterrows():
                        with st.container(border=True):
                            st.markdown(f"**{ligne['titre_proposé']}**")
                            if ligne["trop_long"]:
                                marque = "  ·  ⚠️ au-delà de tout succès mesuré"
                            elif not ligne["assez_long"]:
                                marque = "  ·  ⚠️ sous la cible"
                            else:
                                marque = ""
                            st.caption(
                                f"{ligne['caractères']} caractères{marque}  ·  "
                                f"gabarit « {ligne['gabarit']} », "
                                f"{ligne['rendement_du_gabarit']:.1f}× la moyenne du site  ·  "
                                f"{ligne['procédés_activés']}"
                            )
                            st.caption(
                                f"↳ inspiré de : *{ligne['inspiré_de']}* "
                                f"({ligne['vues_de_référence']:,.0f} vues)".replace(",", " ")
                            )
                    st.download_button(
                        "Télécharger les propositions (CSV)",
                        propositions.to_csv(index=False).encode("utf-8-sig"),
                        "titres_proposes.csv", "text/csv",
                    )

            st.subheader("Ce que valent ces tournures, ici")
            st.caption(
                "Chaque gabarit est confronté à l'historique du site. Ceux qui n'y "
                "ont jamais rien produit ne sont pas proposés, même s'ils "
                "fonctionnent ailleurs."
            )
            rendements = rendement_des_gabarits(articles, profil)
            if rendements.empty:
                st.write("Pas assez d'articles pour mesurer les gabarits.")
            else:
                st.dataframe(
                    rendements[["gabarit", "articles", "succès", "taux_pour_1000",
                                "rendement", "exemple", "vues_exemple"]]
                    .style.format({
                        "taux_pour_1000": "{:.2f} ‰", "rendement": "×{:.1f}",
                        "vues_exemple": "{:,.0f}",
                    }),
                    width="stretch", hide_index=True,
                )


# --------------------------------------------------------------------------
# Méthode
# --------------------------------------------------------------------------

with onglets[7]:
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

**Viviers → Veille** — le seul endroit où une information vient de l'extérieur.
Claude cherche sur le web, mais ne classe rien : chaque sujet rapporté est noté
par le même profil de succès que les autres viviers, et l'outil relève à part
les pages réellement consultées. Un modèle de langage peut se tromper sur un
fait ou mal dater une annonce — le champ « risque » et la liste des sources
servent à vérifier, pas à dispenser de vérifier.

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
