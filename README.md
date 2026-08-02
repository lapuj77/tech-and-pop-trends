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

## Démarrer

**Sans rien connaître à Python** : double-clic sur `lancer.command` (Mac) ou
`lancer.bat` (Windows). Le premier lancement installe ce qu'il faut, les
suivants sont immédiats. Voir **[DEPLOIEMENT.md](DEPLOIEMENT.md)** pour la mise
en service sur une adresse web ou un serveur interne.

**En ligne de commande** :

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Alimenter l'outil

Les fichiers se déposent dans l'interface, ou se posent simplement **dans le
dossier de l'application** — à la racine, à côté de `app.py`, ou dans un
sous-dossier `data/`. Les deux emplacements sont lus au démarrage, et ni l'un
ni l'autre n'est envoyé sur GitHub.

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

### Marfeel, un fichier par canal

Marfeel applique un **filtre** avant l'export : dans l'écran de rapport, filtre
*Traffic source*, **une seule case cochée à la fois**, plage de dates la plus
large possible, puis export. Au-delà de quelques mois, Marfeel bascule
automatiquement en semaines — c'est le bon grain pour une tendance annuelle.

⚠️ **Le CSV ne contient aucune colonne indiquant le canal filtré.**
L'information n'existe que dans le nom du fichier. Nomme-les donc selon la
convention `<site><canal><année>.csv` :

```
jdgdiscover2026.csv    pcdirect2025.csv    jdg-dark-social-2026.csv
```

Sites reconnus : `jdg`, `pc`. Canaux reconnus : `discover`, `google` ou
`search`, `direct`, `news`, `dark`, `bing`. Séparateurs et casse libres. Un
fichier non reconnu est rangé sous « inconnu » et l'application le signale.

Ne mélange pas les granularités sans y penser : un export quotidien d'un mois
et un export hebdomadaire de l'année couvrent les mêmes journées. L'application
détecte la granularité de chaque fichier et n'en retient qu'une pour les
totaux — celle qui couvre la plus longue période.

### Table de redirections — optionnel mais décisif

Chaque relance d'article laisse une redirection de l'ancienne URL vers la
nouvelle. Cette table est donc le journal complet des relances.

Sans elle, l'outil reconstitue cet historique depuis les URLs présentes dans
les exports Search Console — qui sont **plafonnés à quelques centaines de
lignes**. Une relance absente du haut de classement passe alors inaperçue, et
l'article apparaît à tort comme jamais ressorti. Deux colonnes suffisent :
l'URL de départ et l'URL d'arrivée.

## L'onglet Canaux

C'est le seul endroit qui voit le trafic **hors Google** — direct, réseaux
sociaux, referrers. Quatre lectures :

- **D'où vient le trafic**, site par site, avec les pages par visiteur et
  l'engagement. Ce ratio sépare l'acquisition de la fidélité : au-dessus de 5 on
  lit un lectorat qui revient, autour de 1,5 du trafic de passage.
- **Comparer deux périodes** de même longueur, canal par canal.
- **Un canal, les sites superposés** — la courbe qui montre le mieux un écart
  qui se creuse ou se referme entre deux sites.
- **L'audience qui revient d'elle-même**, suivie en visiteurs et en engagement,
  jamais en pages vues seules : un seul gros succès suffirait à les faire varier
  sans qu'un seul lecteur fidèle de plus soit arrivé.

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

Un quatrième onglet, **Formuler**, part d'un sujet et propose des titres. Les
tournures viennent d'un catalogue écrit à la main, mais **leur classement est
mesuré** : chaque gabarit est confronté à l'historique du site, et ceux qui n'y
ont jamais rien produit ne sont pas proposés. Chaque suggestion affiche le
succès passé dont elle s'inspire, les procédés qu'elle active et sa longueur.

Les gabarits sont construits pour être sûrs grammaticalement — le sujet est
inséré comme groupe nominal, jamais à une place qui demanderait de l'accorder.
Le résultat reste **une amorce à retravailler**, pas un titre publiable en
l'état.

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
| `jdg/marfeel.py` | exports par canal, mix, comparaison de périodes, audience fidèle |
| `jdg/palettes.py` | profil de succès, notation d'un sujet, les trois viviers |
| `jdg/suggestions.py` | gabarits de titre, rendement mesuré, propositions |
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
- Les canaux hors Google ne sont visibles que par les exports Marfeel, dont le
  canal se déduit du nom de fichier. Une erreur de nommage se voit dans les
  répartitions, pas dans les données elles-mêmes.
- Les visiteurs uniques ne s'additionnent pas d'une période à l'autre : une
  personne venue trois semaines de suite compte une fois par semaine et une
  seule sur le mois. Les totaux de période affichés par Marfeel sont
  dédoublonnés, la somme des lignes ne l'est pas.
- Les deux sites d'une comparaison tournent en général sur des infrastructures
  distinctes : les niveaux absolus se comparent avec prudence, les évolutions
  dans le temps — chaque site comparé à lui-même — sont fiables.
- Pas de détection en temps réel : la Search Console est décalée de deux à
  trois jours et les exports Marfeel sont manuels. Repérer un article qui
  décolle le jour même demande une source d'audience en direct — API Marfeel,
  GA4 ou logs serveur.
