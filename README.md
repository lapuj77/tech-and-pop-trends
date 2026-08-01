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

## Les trois viviers de sujets

L'onglet **Viviers** alimente la conférence de rédaction. Les trois listes
reposent sur un même profil de succès, recalculé à chaque chargement depuis
l'historique du site — jamais sur des bonnes pratiques générales. Ce que
l'outil juge prometteur est toujours ce qui a fonctionné **ici**.

- **Froid** — l'archive prouvée : sujets à forte audience passée, endormis
  depuis assez longtemps pour reprendre, écartés dès qu'ils ont épuisé leurs
  relances, remontés en priorité quand leur saison approche.
- **Chaud** — l'actualité du moment relevée sur Google Trends et Google
  Actualités, puis **classée par ressemblance aux succès du site** plutôt que
  par fraîcheur. Chaque ligne indique pourquoi elle est là, à quel succès passé
  elle ressemble, et ce qu'il manque au titre.
- **Nouveaux** — les écarts : familles à fort rendement mais faible part de la
  production, sujets à demande démontrée chez un concurrent et jamais traités
  ici, et articles récents à reformuler.

Un rendement faible ne condamne pas une famille : elle peut servir l'identité
du site ou son audience fidèle. Le tableau dit d'où viennent les cartons, pas
ce qu'il faut cesser d'écrire.

Le vivier chaud a besoin d'un accès réseau à `trends.google.com` et
`news.google.com`. Quand ils sont bloqués, l'onglet affiche l'échec au lieu de
laisser croire qu'il n'y a pas d'actualité — `jdg.flux.collecte_hors_ligne`
permet de travailler sur des flux enregistrés.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `app.py` | interface Streamlit |
| `jdg/parsers.py` | lecture des exports, nombres au format français, URLs |
| `jdg/metrics.py` | mesures : séries, stock/flux, relances, cartons, réservoir |
| `jdg/palettes.py` | profil de succès, notation d'un sujet, les trois viviers |
| `jdg/flux.py` | lecture des flux RSS d'actualité (bibliothèque standard seule) |

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
