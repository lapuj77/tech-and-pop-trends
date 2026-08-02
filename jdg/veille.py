"""Faire chercher l'actualité par Claude, la faire classer par les données du site.

Le partage des rôles est volontaire et vaut d'être compris avant de lire le code :

* **Claude cherche et cadre.** Il interroge le web en direct, repère ce qui bouge,
  et propose un sujet et une amorce de titre. C'est le seul endroit de l'outil où
  une information vient de l'extérieur.
* **Les données du site classent.** Chaque proposition qui revient est repassée
  par `note_sujet`, exactement comme les sujets du vivier chaud : la famille, les
  procédés de titre et la ressemblance aux cartons passés sont mesurés sur
  l'historique du CMS. L'ordre affiché est donc celui du site, pas celui du modèle.

Autrement dit, le modèle n'a pas le droit de décider seul qu'un sujet est bon. Il
apporte de la matière ; le classement reste adossé à ce qui a réellement marché.

Le module ne dépend pas du reste de l'application pour fonctionner, mais il a
besoin du paquet `anthropic` et d'une clé d'API. Les deux absences sont traitées
comme des erreurs explicites, jamais comme un résultat vide.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field

import pandas as pd

from .palettes import FAMILLES, ProfilSucces, _jetons, note_sujet

MODELE_PAR_DEFAUT = "claude-sonnet-5"

# Version de l'outil de recherche avec filtrage dynamique : le modèle filtre les
# résultats avant qu'ils n'entrent dans le contexte. Rien d'autre à déclarer.
OUTIL_RECHERCHE_WEB = "web_search_20260209"

NOM_OUTIL_DEPOT = "deposer_propositions"


class VeilleIndisponible(RuntimeError):
    """Le module ne peut pas fonctionner : paquet absent, clé absente, appel refusé."""


# --------------------------------------------------------------------------
# Coût
# --------------------------------------------------------------------------

# Tarifs Claude Sonnet 5, en dollars par million de jetons. Le tarif de
# lancement court jusqu'au 31 août 2026 inclus.
_TARIF_LANCEMENT = (2.00, 10.00)
_TARIF_COURANT = (3.00, 15.00)
_FIN_LANCEMENT = datetime.date(2026, 8, 31)
PRIX_RECHERCHE = 0.01           # 10 $ pour 1 000 recherches


def _tarif(jour: datetime.date | None = None) -> tuple[float, float]:
    return _TARIF_LANCEMENT if (jour or datetime.date.today()) <= _FIN_LANCEMENT else _TARIF_COURANT


# --------------------------------------------------------------------------
# Le brief : ce que le modèle doit savoir du site
# --------------------------------------------------------------------------

def brief_editorial(profil: ProfilSucces, articles: pd.DataFrame,
                    n_cartons: int = 30, n_recents: int = 60) -> str:
    """Décrit la ligne éditoriale **en chiffres mesurés**, pas en adjectifs.

    C'est la seule chose que le modèle connaîtra du site : ni charte, ni
    intentions, seulement ce que l'historique démontre. Les titres récents
    servent à deux choses — montrer le ton réel, et éviter qu'on propose un sujet
    déjà traité la semaine dernière.
    """
    lignes: list[str] = []

    lignes.append(
        f"Seuil de succès mesuré sur ce site : {profil.seuil:,} vues. "
        f"Moyenne du site : {profil.taux_moyen:.2f} succès pour 1 000 articles."
        .replace(",", " ")
    )

    porteuses = sorted(
        ((nom, t, n, c) for nom, (t, n, c) in profil.familles.items()),
        key=lambda x: x[1], reverse=True,
    )
    if porteuses:
        lignes.append("\nRendement mesuré par famille (succès pour 1 000 articles) :")
        for nom, taux, n, c in porteuses:
            rapport = (taux / profil.taux_moyen) if profil.taux_moyen else 0
            lignes.append(
                f"- {nom} : {taux:.2f} ‰ ({rapport:.1f}× la moyenne), "
                f"{n} articles, {c} succès"
            )

    if profil.marqueurs:
        lignes.append("\nEffet mesuré des procédés de titre (taux avec / taux sans) :")
        for nom, (avec, sans, n) in sorted(
            profil.marqueurs.items(),
            key=lambda kv: (kv[1][0] / kv[1][1]) if kv[1][1] else 0, reverse=True,
        ):
            effet = (avec / sans) if sans else 0
            lignes.append(f"- {nom} : ×{effet:.1f} (sur {n} articles)")

    if profil.cartons:
        lignes.append(f"\nLes {n_cartons} plus gros succès du site, tels qu'ils ont été titrés :")
        for titre, _, vues in sorted(profil.cartons, key=lambda c: c[2], reverse=True)[:n_cartons]:
            lignes.append(f"- {titre} — {vues:,.0f} vues".replace(",", " "))

    if not articles.empty and "jour" in articles.columns:
        recents = articles.sort_values("jour", ascending=False).head(n_recents)
        lignes.append(
            f"\nLes {len(recents)} derniers articles publiés — à ne pas proposer à nouveau, "
            "et bon indicateur du ton courant :"
        )
        for titre in recents["titre"].astype(str):
            lignes.append(f"- {titre}")

    return "\n".join(lignes)


# --------------------------------------------------------------------------
# L'outil de dépôt
# --------------------------------------------------------------------------

def _outil_depot(familles_connues: list[str]) -> dict:
    """Outil local par lequel le modèle rend ses propositions.

    Passer par un outil plutôt que par du texte libre évite d'avoir à extraire du
    JSON d'une réponse rédigée : l'API renvoie déjà un dictionnaire.
    """
    return {
        "name": NOM_OUTIL_DEPOT,
        "description": (
            "Déposer les sujets retenus. À n'appeler qu'une seule fois, à la fin, "
            "après avoir cherché sur le web. Chaque proposition doit reposer sur "
            "une actualité vérifiée et datée, avec au moins une source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "propositions": {
                    "type": "array",
                    "description": "Les sujets retenus, du plus prometteur au moins prometteur.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sujet": {
                                "type": "string",
                                "description": "Le sujet en une phrase factuelle : ce qui s'est passé.",
                            },
                            "titre": {
                                "type": "string",
                                "description": (
                                    "Une amorce de titre en français, dans les tournures qui "
                                    "fonctionnent sur ce site. Viser 85 caractères ou plus."
                                ),
                            },
                            "pourquoi_maintenant": {
                                "type": "string",
                                "description": "L'événement daté qui rend le sujet chaud aujourd'hui.",
                            },
                            "famille": {
                                "type": "string",
                                "description": "La famille du site à laquelle le sujet appartient.",
                                "enum": familles_connues + ["autre"],
                            },
                            "angle": {
                                "type": "string",
                                "description": "L'angle concret à donner, en une phrase.",
                            },
                            "fraicheur": {
                                "type": "string",
                                "enum": ["moins de 24 h", "cette semaine", "ce mois-ci", "marronnier"],
                            },
                            "sources": {
                                "type": "array",
                                "description": "URLs consultées pour ce sujet.",
                                "items": {"type": "string"},
                            },
                            "risque": {
                                "type": "string",
                                "description": (
                                    "Ce qui peut faire rater le sujet : information non confirmée, "
                                    "concurrence déjà passée dessus, audience trop étroite…"
                                ),
                            },
                        },
                        "required": ["sujet", "titre", "pourquoi_maintenant", "famille",
                                     "angle", "fraicheur", "sources", "risque"],
                    },
                },
                "remarque": {
                    "type": "string",
                    "description": "Une observation générale sur l'actualité du jour, si utile.",
                },
            },
            "required": ["propositions"],
        },
    }


# --------------------------------------------------------------------------
# L'appel
# --------------------------------------------------------------------------

_SYSTEME = """Tu assistes la rédaction en chef d'un média français de tech et de \
pop culture. Ton travail : trouver dans l'actualité du jour les sujets qui ont le \
plus de chances de marcher SUR CE SITE, d'après ce que son historique démontre.

Méthode imposée :
1. Cherche sur le web l'actualité récente, en français en priorité, dans les \
domaines couverts par le site.
2. Vérifie chaque information : une rumeur non confirmée se signale comme telle \
dans le champ « risque », elle ne se présente jamais comme un fait.
3. Ne retiens que ce qui recoupe le profil de succès mesuré fourni. Une actualité \
importante mais étrangère à ce site n'a rien à faire dans la liste.
4. Écarte tout sujet déjà couvert par les articles récents fournis.
5. Appelle l'outil de dépôt une seule fois, à la fin.

Deux règles fermes. Le cœur d'audience est la tech et la pop culture : tout \
s'y rattache, même les sujets pratiques. Et tu n'inventes jamais une source — \
seules les URLs réellement consultées sont listées."""


@dataclass
class Propositions:
    """Le résultat d'une veille, avec ce qu'elle a coûté."""

    table: pd.DataFrame
    remarque: str = ""
    recherches: int = 0
    jetons_entree: int = 0
    jetons_sortie: int = 0
    modele: str = MODELE_PAR_DEFAUT
    sources: list[str] = field(default_factory=list)

    @property
    def cout(self) -> float:
        """Coût estimé de l'appel, en dollars."""
        entree, sortie = _tarif()
        return (self.jetons_entree * entree / 1e6
                + self.jetons_sortie * sortie / 1e6
                + self.recherches * PRIX_RECHERCHE)


def _client(cle: str | None):
    try:
        import anthropic
    except ImportError as erreur:      # noqa: F841
        raise VeilleIndisponible(
            "Le paquet `anthropic` n'est pas installé. "
            "Installer avec : pip install anthropic"
        ) from erreur
    cle = cle or os.environ.get("ANTHROPIC_API_KEY")
    if not cle:
        raise VeilleIndisponible(
            "Aucune clé d'API. La renseigner dans la barre latérale, ou définir "
            "la variable d'environnement ANTHROPIC_API_KEY."
        )
    return anthropic.Anthropic(api_key=cle)


def cherche_sujets(profil: ProfilSucces, articles: pd.DataFrame,
                   cle_api: str | None = None, n: int = 12,
                   consigne: str = "", modele: str = MODELE_PAR_DEFAUT,
                   max_recherches: int = 12, tours_max: int = 8) -> Propositions:
    """Demande à Claude de chercher l'actualité, puis classe ce qu'il rapporte.

    Le classement final n'est pas celui du modèle : chaque proposition est notée
    par `note_sujet` sur l'historique du site, et la table est triée là-dessus.
    """
    client = _client(cle_api)

    familles_connues = [nom for nom in FAMILLES if nom in profil.familles] or list(FAMILLES)
    aujourdhui = datetime.date.today()

    invite = (
        f"Nous sommes le {aujourdhui:%d/%m/%Y}. Trouve {n} sujets d'actualité à "
        "traiter dans les prochains jours.\n\n"
        "=== PROFIL MESURÉ DU SITE ===\n"
        + brief_editorial(profil, articles)
        + ("\n\n=== CONSIGNE DE LA RÉDACTION EN CHEF ===\n" + consigne.strip()
           if consigne.strip() else "")
    )

    outils = [
        {
            "type": OUTIL_RECHERCHE_WEB,
            "name": "web_search",
            "max_uses": max_recherches,
            # Le site est français et son audience l'est aussi : sans cela, la
            # recherche remonte massivement des sources américaines.
            "user_location": {
                "type": "approximate",
                "country": "FR",
                "timezone": "Europe/Paris",
            },
        },
        _outil_depot(familles_connues),
    ]

    messages: list[dict] = [{"role": "user", "content": invite}]
    depot: dict | None = None
    recherches = jetons_entree = jetons_sortie = 0
    sources: list[str] = []

    for _ in range(tours_max):
        with client.messages.stream(
            model=modele,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=_SYSTEME,
            tools=outils,
            messages=messages,
        ) as flux:
            reponse = flux.get_final_message()

        usage = reponse.usage
        jetons_entree += getattr(usage, "input_tokens", 0) or 0
        jetons_sortie += getattr(usage, "output_tokens", 0) or 0
        outil_serveur = getattr(usage, "server_tool_use", None)
        if outil_serveur is not None:
            recherches += getattr(outil_serveur, "web_search_requests", 0) or 0
        sources += _urls_consultees(reponse.content)

        if reponse.stop_reason == "refusal":
            raise VeilleIndisponible(
                "Le modèle a refusé de répondre. Reformuler la consigne."
            )

        # Boucle serveur interrompue : on renvoie le tour tel quel, sans rien ajouter.
        if reponse.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": reponse.content})
            continue

        appels = [b for b in reponse.content if getattr(b, "type", None) == "tool_use"]
        if not appels:
            break

        messages.append({"role": "assistant", "content": reponse.content})
        resultats = []
        for appel in appels:
            if appel.name == NOM_OUTIL_DEPOT:
                depot = dict(appel.input)
                resultats.append({
                    "type": "tool_result", "tool_use_id": appel.id,
                    "content": "Propositions enregistrées.",
                })
            else:
                resultats.append({
                    "type": "tool_result", "tool_use_id": appel.id,
                    "content": f"Outil inconnu : {appel.name}.", "is_error": True,
                })
        if depot is not None:
            break
        messages.append({"role": "user", "content": resultats})

    if depot is None:
        raise VeilleIndisponible(
            "Le modèle n'a rien déposé. C'est en général une recherche web "
            "infructueuse ou une consigne trop restrictive — réessayer en "
            "élargissant."
        )

    table = _classe(depot.get("propositions") or [], profil, articles)
    return Propositions(
        table=table,
        remarque=str(depot.get("remarque") or ""),
        recherches=recherches,
        jetons_entree=jetons_entree,
        jetons_sortie=jetons_sortie,
        modele=modele,
        sources=sorted(set(sources)),
    )


def _urls_consultees(contenu) -> list[str]:
    """Relève les URLs réellement rapportées par l'outil de recherche.

    Elles servent de contrôle : une source citée par le modèle mais absente d'ici
    n'a pas été consultée.
    """
    urls: list[str] = []
    for bloc in contenu:
        if getattr(bloc, "type", None) != "web_search_tool_result":
            continue
        resultats = getattr(bloc, "content", None)
        if not isinstance(resultats, list):
            continue                     # bloc d'erreur : pas de résultat
        for resultat in resultats:
            url = getattr(resultat, "url", None)
            if url:
                urls.append(str(url))
    return urls


# --------------------------------------------------------------------------
# Classement par les données du site
# --------------------------------------------------------------------------

def _classe(propositions: list[dict], profil: ProfilSucces,
            articles: pd.DataFrame) -> pd.DataFrame:
    """Note chaque proposition sur l'historique du site et signale les doublons."""
    if not propositions:
        return pd.DataFrame()

    nos_jetons = ([_jetons(t) for t in articles["titre"].astype(str)]
                  if not articles.empty else [])

    lignes = []
    for brut in propositions:
        titre = str(brut.get("titre", "")).strip()
        sujet = str(brut.get("sujet", "")).strip()
        if not titre and not sujet:
            continue
        note = note_sujet(titre or sujet, profil)

        jetons = _jetons(f"{titre} {sujet}")
        recouvrement = max(
            (len(jetons & j) / len(jetons | j) for j in nos_jetons if j and jetons),
            default=0.0,
        )

        sources = brut.get("sources") or []
        lignes.append({
            "score": note.score,
            "titre_proposé": titre,
            "sujet": sujet,
            "fraîcheur": str(brut.get("fraicheur", "")),
            "famille_annoncée": str(brut.get("famille", "")),
            "famille_mesurée": note.famille or "—",
            "pourquoi_maintenant": str(brut.get("pourquoi_maintenant", "")),
            "angle": str(brut.get("angle", "")),
            "déjà_traité": recouvrement,
            "pourquoi_ça_peut_marcher": " · ".join(note.raisons) or "aucun signal fort",
            "à_corriger": " · ".join(note.conseils[:3]),
            "caractères": len(titre),
            "risque": str(brut.get("risque", "")),
            "sources": " ".join(str(u) for u in sources),
        })
    if not lignes:
        return pd.DataFrame()
    return (pd.DataFrame(lignes)
            .sort_values("score", ascending=False)
            .reset_index(drop=True))
