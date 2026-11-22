# Rocket League – Bot de suivi de parties privées

Bot qui **rejoint automatiquement une partie privée Rocket League** (nom + mot de passe), suit le **score en direct** grâce à la **Stats API officielle** de Psyonix, puis enregistre les résultats dans `scores.json`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `rl_join_bot.py` | Le bot : rejoint la partie, suit le score, quitte la partie, enregistre les résultats |
| `rl_match_watcher.py` | Lecture de la Stats API (utilisé par le bot, ou seul pour suivre un match rejoint à la main) |
| `requirements.txt` | Dépendances Python |
| `score.example.json` | Exemple du fichier `scores.json` produit |

## Comment ça marche

1. Le bot pilote la souris et le clavier pour naviguer dans les menus : **Play → Private Match → Join Private Match**, puis tape le nom et le mot de passe.
2. Une fois dans le match, Rocket League diffuse le score sur un port local (`127.0.0.1:49123`) via la **Stats API**. Le bot s'y connecte.
3. À la fin du match (ou quand tu tapes `quit`), le score est ajouté à `scores.json`.

> Le bot ne communique jamais avec les serveurs de Psyonix : il lit uniquement ce que **ton jeu** envoie sur ton PC.

## Prérequis

- Windows, Rocket League (Steam ou Epic) en **Plein écran fenêtré**
- Python 3.10+
- Le PC qui lance le bot doit être celui qui fait tourner le jeu

## Installation

Windows (PowerShell) :
```powershell
python -m pip install -r requirements.txt
```
Linux / macOS (Bash) :
```bash
python3 -m pip install -r requirements.txt
```

`pytesseract` est facultatif : il ne sert que pour les boutons non calibrés et nécessite [Tesseract-OCR](https://github.com/UB-Mannheim/tesseract/wiki). Avec une calibration complète, il n'est pas nécessaire.

## 1. Activer la Stats API (une seule fois)

Jeu **fermé**, modifie le fichier `.ini` dans le dossier du jeu :

- Steam : `C:\Program Files (x86)\Steam\steamapps\common\rocketleague\TAGame\Config\`
- Epic : `C:\Program Files\Epic Games\rocketleague\TAGame\Config\`

Dans **`DefaultStatsAPI.ini` ET `TAStatsAPI.ini`** (en administrateur), mets :

```ini
[TAGame.MatchStatsExporter_TA]
PacketSendRate=30
Port=49123
WebPort=49124
```

> ⚠️ `PacketSendRate=0` désactive l'API (valeur par défaut). Une mise à jour du jeu peut remettre cette valeur à 0.

Vérifier que ça marche (jeu lancé, **dans un match**) :

Windows (PowerShell) :
```powershell
Test-NetConnection localhost -Port 49123   # TcpTestSucceeded : True
```
Linux / macOS (Bash) :
```bash
nc -zv localhost 49123   # « succeeded » / « open » = OK
```

## 2. Calibrer les boutons (une seule fois)

Le bot doit connaître la position des boutons à l'écran.

Windows (PowerShell) :
```powershell
python rl_join_bot.py --calibrate --resolution 1920x1200 --language en
```
Linux / macOS (Bash) :
```bash
python3 rl_join_bot.py --calibrate --resolution 1920x1200 --language en
```

Pour chaque étape : **Entrée** dans la console → 5 s pour poser la souris sur l'élément dans le jeu (sans cliquer) → une fois « enregistré », clique toi-même pour passer à l'écran suivant. Tape `skip` pour sauter une étape facultative.

Étapes : `play`, `private_match`, `join_private`, `name_field`, `password_field`, `join_button`, `spectate` *(facultatif)*, `leave_match`, `confirm_yes`.

Pour recalibrer seulement certaines étapes (les autres sont conservées) :

Windows (PowerShell) :
```powershell
python rl_join_bot.py --calibrate --resolution 1920x1200 --language en --steps leave_match,confirm_yes
```
Linux / macOS (Bash) :
```bash
python3 rl_join_bot.py --calibrate --resolution 1920x1200 --language en --steps leave_match,confirm_yes
```

Les positions sont stockées dans `positions.json`.

### Calibrer le retour au menu (partie inexistante)

Quand la partie privée n'existe pas, le jeu affiche une erreur. Pour que le bot sache revenir au menu principal, enregistre le chemin une fois :

Windows (PowerShell) :
```powershell
python rl_join_bot.py --calibrate-back-to-menu --resolution 1920x1200 --language en
```
Linux / macOS (Bash) :
```bash
python3 rl_join_bot.py --calibrate-back-to-menu --resolution 1920x1200 --language en
```

1. Rocket League au **menu principal** : 5 s plus tard, le bot essaie de rejoindre une partie qui n'existe pas, et l'erreur s'affiche.
2. Enregistre ensuite, **dans l'ordre**, chaque action qui ramène au menu principal :
   - **Entrée** (sans rien taper) = un clic : 5 s pour poser la souris sur le bouton (ex. **OK** de l'erreur), puis clique toi-même dessus ;
   - **`esc`** = la touche Échap : appuie ensuite toi-même sur Échap dans le jeu ;
   - **`fin`** = tu es revenu au menu principal.

Les actions sont ajoutées à `positions.json` (étape `back_to_menu`) sans toucher aux autres boutons. Sans cette calibration, le bot appuie sur Échap jusqu'à 4 fois.

## 3. Lancer le bot

Rocket League au **menu principal**, puis :

Windows (PowerShell) :
```powershell
python rl_join_bot.py --name 111 --password 111 --resolution 1920x1200 --language en
```
Linux / macOS (Bash) :
```bash
python3 rl_join_bot.py --name 111 --password 111 --resolution 1920x1200 --language en
```

Le bot démarre 5 s plus tard (laisse le jeu au premier plan).

### Quitter la partie

Tape **`quit`** puis Entrée dans le terminal (`q`, `quitter`, `leave`, `exit`, `stop` marchent aussi). Le bot enregistre le score, attend 5 s et quitte la partie : **pendant ces 5 s, reclique sur Rocket League** (le bot ne remet plus le jeu au premier plan tout seul).

### Si la connexion échoue

Le bot revient au menu principal (`back_to_main_menu`) : il rejoue les actions enregistrées avec `--calibrate-back-to-menu` (voir la calibration). Sans elles, il appuie sur **Échap** jusqu'à 4 fois (fenêtre d'erreur, fenêtre de connexion, Match privé, Jouer) ; avec Tesseract, il s'arrête dès que le bouton JOUER est visible. Si le match a finalement été rejoint juste après le délai, il le quitte normalement.

### Arrêt d'urgence

Envoie la souris dans le **coin haut-gauche** de l'écran.

## Paramètres

| Paramètre | Défaut | Description |
|---|---|---|
| `--name` | *(obligatoire)* | Nom de la partie privée |
| `--password` | `""` | Mot de passe de la partie |
| `--resolution` | *(obligatoire)* | Résolution de l'écran, ex. `1920x1200` |
| `--language` | *(obligatoire)* | Langue du jeu : `en` ou `fr` |
| `--spectate` | non | Passer spectateur dans le lobby |
| `--leave` | non | Quitter automatiquement à la fin du match |
| `--output` | `scores.json` | Fichier des scores |
| `--quit-delay` | `5` | Secondes d'attente après `quit` avant de bouger la souris |
| `--delay` | `1.5` | Pause entre deux écrans de menu (augmenter si PC lent) |
| `--join-timeout` | `90` | Secondes max pour entrer dans le match |
| `--host` / `--port` | `127.0.0.1` / `49123` | Adresse de la Stats API |
| `--positions` | `positions.json` | Fichier de calibration |
| `--labels` | — | JSON pour corriger les textes des menus (OCR) |
| `--tesseract` | `C:\Program Files\Tesseract-OCR\tesseract.exe` | Chemin de Tesseract |
| `--calibrate` | — | Mode calibration |
| `--steps` | — | Avec `--calibrate` : étapes à recalibrer, séparées par des virgules |
| `--calibrate-back-to-menu` | — | Calibre le retour au menu quand la partie n'existe pas |
| `--countdown` | `5` | Secondes pour placer la souris en calibration |

## Format de `scores.json`

Une liste, un objet par match (voir `score.example.json`) :

- `partie` : nom de la partie privée
- `statut` : `terminé`, `quitté avant la fin` ou `connexion perdue`
- `winner_team_num` : `0` = Bleu, `1` = Orange, `null` si pas de vainqueur
- `teams` : nom et score de chaque équipe
- `players` : stats de chaque joueur (score, buts, passes, arrêts, tirs, démolitions)

## Utiliser seulement le watcher (sans bot)

Si tu rejoins la partie toi-même :

Windows (PowerShell) :
```powershell
python rl_match_watcher.py --output resultats.jsonl
```
Linux / macOS (Bash) :
```bash
python3 rl_match_watcher.py --output resultats.jsonl
```

## Dépannage

| Problème | Solution |
|---|---|
| `WinError 10061` / `TcpTestSucceeded : False` | `PacketSendRate` vaut 0, ou le jeu n'a pas été redémarré, ou tu n'es pas dans un match |
| `Étapes calibrées : aucune` | Refaire la calibration en appuyant sur **Entrée** (pas `s`) |
| Le bot clique à côté | Mauvaise `--resolution`, ou jeu pas en plein écran fenêtré → recalibrer |
| Les menus défilent trop vite | Augmenter `--delay` |
| `quit` ne quitte pas | Calibrer `leave_match` et `confirm_yes` avec `--steps` |

## Avertissement

Projet non officiel, non affilié à Psyonix / Epic Games. L'automatisation des entrées clavier/souris est une zone grise des conditions d'utilisation : utilise de préférence un **compte secondaire**.
