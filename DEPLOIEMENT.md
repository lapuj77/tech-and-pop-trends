# Mettre l'outil en service

Trois façons de faire, de la plus simple à la plus lourde. **Commence par la
première** : elle marche en cinq minutes et tes données ne quittent pas ta
machine.

---

## 1. Sur ton ordinateur — recommandé

Rien à configurer, rien à héberger, aucune donnée qui sort.

### Une seule fois

**Installer Python**, s'il ne l'est pas déjà : [python.org/downloads](https://www.python.org/downloads/).
Sous Windows, **cocher « Add Python to PATH »** pendant l'installation — c'est
la case que tout le monde oublie et sans elle rien ne fonctionne.

**Récupérer le dossier du projet** : sur la page GitHub du dépôt, bouton vert
**Code** → **Download ZIP**, puis décompresser où tu veux.

### À chaque fois

- **Mac** : double-clic sur `lancer.command`
- **Windows** : double-clic sur `lancer.bat`

Une fenêtre noire s'ouvre, puis le tableau de bord apparaît dans le navigateur.
Le premier lancement prend deux minutes — il installe ce qu'il faut. Les
suivants sont immédiats.

**Laisse la fenêtre noire ouverte** tant que tu utilises l'outil : la fermer
arrête l'application.

> Si le Mac refuse d'ouvrir le fichier, ouvre le Terminal, tape `chmod +x ` puis
> glisse `lancer.command` dedans et appuie sur Entrée. À faire une seule fois.

### Où mettre les fichiers

Deux possibilités, au choix :

- les **déposer dans la barre latérale** de l'application ;
- les **placer dans le dossier `data/`** à côté de l'application, ils seront
  chargés automatiquement à chaque démarrage. Plus pratique quand ce sont
  toujours les mêmes.

Ce dossier n'est jamais envoyé sur GitHub.

---

## 2. Une adresse web pour l'équipe

Utile si plusieurs personnes doivent y accéder sans rien installer. Gratuit,
hébergé par Streamlit, connecté directement au dépôt GitHub.

1. Aller sur [share.streamlit.io](https://share.streamlit.io) et se connecter
   avec le compte GitHub.
2. **New app** → choisir le dépôt `lapuj77/tech-and-pop-trends`, la branche, et
   `app.py` comme fichier principal.
3. **Deploy**. Trois à quatre minutes.

À chaque fois que le dépôt est mis à jour, l'application se met à jour toute
seule.

> ⚠️ **Vérifie les réglages d'accès avant de partager l'adresse.** Par défaut,
> une application déployée là-bas est joignable par toute personne qui a le
> lien. Le dépôt étant privé, l'accès peut être restreint à des personnes
> invitées — c'est à contrôler dans les paramètres de l'application, pas à
> supposer.
>
> Tes exports ne sont pas dans le dépôt, donc rien ne fuite au déploiement. En
> revanche, les fichiers déposés dans l'interface le sont pendant la session de
> la personne qui les dépose. **Si le doute subsiste sur l'accès, reste sur la
> méthode 1.**

---

## 3. Sur un serveur interne

Pour le pôle technique du groupe, si l'outil doit vivre sur une machine maison.

```bash
docker build -t audience-jdg .
docker run -d -p 8501:8501 -v "$PWD/data:/app/data" --name audience audience-jdg
```

Puis `http://<serveur>:8501`.

Le montage `-v` rend le dossier `data/` du serveur visible par l'application :
déposer les exports dedans suffit à les charger. L'image ne contient jamais de
données, et l'application tourne sous un utilisateur sans privilèges.

*Le `Dockerfile` est fourni mais n'a pas pu être construit ni testé lors de son
écriture — aucun démon Docker n'était disponible. L'installation qu'il décrit,
elle, a été vérifiée : environnement vierge, `requirements.txt`, démarrage de
l'application. Attends-toi éventuellement à un ajustement mineur au premier
build.*

---

## En cas de blocage

**« python n'est pas reconnu »** — Python n'est pas installé, ou la case « Add
Python to PATH » n'a pas été cochée sous Windows. Réinstaller en la cochant.

**La fenêtre s'ouvre et se ferme aussitôt** — une erreur est passée trop vite.
Ouvrir un Terminal (Mac) ou l'invite de commandes (Windows), se placer dans le
dossier, et lancer `bash lancer.command` ou `lancer.bat` : le message d'erreur
reste affiché.

**« Fichier trop volumineux »** — la limite est réglée à 300 Mo dans
`.streamlit/config.toml`. Au-delà, découper l'export par période.

**Un onglet reste vide** — il manque le type de fichier correspondant. Chaque
onglet indique en haut ce dont il a besoin.

**Un canal Marfeel apparaît sous « inconnu »** — le nom du fichier ne permet pas
de deviner le canal. Le renommer selon la convention décrite dans le README
(`jdgdiscover2026.csv`).
