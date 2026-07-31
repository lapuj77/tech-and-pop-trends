# Tableau de bord d'audience éditoriale

Outil de diagnostic pour une rédaction dont l'audience dépend de Google
Discover. Il répond à trois questions qu'un total mensuel ne permet jamais de
trancher :

- **quel canal bouge** — Discover, Search et Google Actualités ne se comportent
  pas pareil et peuvent aller en sens inverse ;
- **est-ce le socle ou le sommet** — la production ordinaire et les articles à
  fort succès obéissent à des logiques différentes, et l'un peut s'effondrer
  pendant que l'autre se porte bien ;
- **que ressortir de l'archive** — quels articles anciens ont encore du
  rendement, et lesquels sont épuisés.

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Alimenter l'outil

Les fichiers se déposent dans l'interface, ou se placent dans un dossier
`data/` à la racine (ignoré par git : ce sont des données internes).

### Search Console

Search Console → **Performances** → *Résultats de recherche*, puis à nouveau
pour *Discover* et *Google Actualités* → plage de **16 mois** → **Exporter** →
CSV. Déposer les `.zip` tels quels.

Un export **par mois** en plus de l'export global rend l'analyse nettement plus
fine : c'est le seul moyen de suivre la répartition entre production du mois et
stock. L'outil lit le filtre de date à l'intérieur du fichier, les noms de
fichiers n'ont donc pas d'importance.

### Articles du CMS

L'export « Auteur_Tous », un fichier par année. Colonnes attendues :
`Titre;Type;Rédacteur;Mots;Vues;Date`.

Le même format sert pour un site concurrent, dans l'emplacement dédié.

### Table de redirections — optionnel mais décisif

Chaque relance d'article laisse une redirection de l'ancienne URL vers la
nouvelle. Cette table est donc le journal complet des relances.

Sans elle, l'outil reconstitue cet historique depuis les URLs présentes dans
les exports Search Console — qui sont **plafonnés à quelques centaines de
lignes**. Une relance absente du haut de classement passe alors inaperçue, et
l'article apparaît à tort comme jamais ressorti. Deux colonnes suffisent :
l'URL de départ et l'URL d'arrivée.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `app.py` | interface Streamlit |
| `jdg/parsers.py` | lecture des exports, nombres au format français, URLs |
| `jdg/metrics.py` | mesures : séries, stock/flux, relances, cartons, réservoir |

Les fonctions de `jdg/metrics.py` s'utilisent aussi seules, dans un notebook ou
un script :

```python
from jdg import charger_gsc, detecte_relances, synthese_relances

export = charger_gsc("data/discover.zip")
relances = detecte_relances(export.pages)
print(synthese_relances(relances, export.pages["clics"].sum()))
```

## Deux seuils, et d'où ils viennent

- **300 000 vues** définit le « carton ». C'est le décrochage observé dans la
  distribution : au-dessus, un seul article porte son mois.
- **2 relances** est le maximum recommandé. Au-delà, le rendement mesuré
  s'effondre — reprise médiane de 59 % sur Discover, deux tiers des relances
  en dessous de la version d'origine, et des séquences nettement décroissantes
  au troisième passage.

Tous deux se règlent dans l'interface ou en tête de `jdg/metrics.py`.

## Limites

- Les exports de l'interface Search Console sont plafonnés à quelques centaines
  de lignes par onglet. L'onglet des dates, lui, est complet.
- Une relance porte la date du jour : elle est donc comptée comme production
  nouvelle dans le calcul stock/flux. L'onglet Relances l'isole.
- La détection des relances repose sur la ressemblance des adresses. Une
  refonte complète de titre change l'adresse et peut échapper à la détection —
  d'où l'intérêt de la table de redirections.
- Les vues du CMS sont cumulées depuis la publication. Un article récent est
  donc mécaniquement sous-estimé face à un article ancien, et les comparaisons
  d'une année sur l'autre exagèrent les baisses. Les données Search Console,
  bornées dans le temps, ne souffrent pas de ce biais.
- Aucune visibilité sur les canaux hors Google : direct, réseaux sociaux,
  referrals.
- Pas de détection en temps réel : la Search Console est décalée de deux à
  trois jours. Repérer un article qui décolle le jour même demande une source
  d'audience temps réel — API Marfeel, GA4 ou logs serveur.
