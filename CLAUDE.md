# CLAUDE.md

Ce fichier guide Claude (et tout contributeur) dans ce dépôt.

## Le projet

`tournament_league_bots` regroupe tous les bots Discord de **tomato_league** pour organiser des tournois Rocket League (préfixe `rl_`) : inscriptions, déroulement des matchs en parties privées, déclaration des scores et classement. Chaque bot est une application Discord séparée (son propre token), dans son propre dossier, avec son venv, ses dépendances, son `.env` et ses tests. Le connecteur Rocket League (`rl_api_pp_connector`) n'est pas un bot Discord : ce sont des scripts indépendants, que `tournament_manager` n'utilise plus. Il n'y a pas de paquet partagé : les bots communiquent **par fichiers**.

| Dossier | Paquet (`python -m …`) | Rôle |
|---|---|---|
| `rl_bot_ppname_creator/` | `bot_inscription_manager` | Inscriptions aux tournois (`/tournoi_rl*`), liste d'attente, confirmations des coéquipiers. Contient aussi le script `generer_pp_names.py` (noms / mots de passe des parties privées). |
| `rl_tournament_manager/` | `bot_tournament_manager` | Fait jouer un tournoi inscrit : zones, rounds, MP avec les parties privées, demande des scores aux joueurs (`DELAI_DECLARATION` après le clic « Partie privée créée »), déclarations, classement (`/start_tournament_rl`, `/stop_…`, `/reset_…`, `/set_result_…`, `/edit_player_…`). |
| `rl_bot_mp/` | `bot_mp` | `/mp_all` : envoie un MP à tous les membres du serveur (admins). Indépendant des deux autres. |
| `rl_bot_ticket/` | `bot_ticket` | Tickets de support : `/ticket_panel` publie le panneau « Support » ; le bouton « 🎫 Créer un ticket » ouvre un salon privé (auteur + `ROLES_STAFF`) selon la catégorie choisie. Indépendant des autres, sans fichier `data/`. |
| `rl_api_pp_connector/` | scripts (`python rl_join_bot.py …`) | Connecteur Rocket League : `rl_join_bot.py` rejoint une partie privée en pilotant les menus (pyautogui / pydirectinput, positions calibrées dans `positions.json`, OCR Tesseract facultatif) ; `rl_match_watcher.py` lit le score via la **Stats API** locale (`127.0.0.1:49123`). Utilisé seul : `tournament_manager` ne l'importe plus. |

Dépôt Git : `ThomasGastelu/tournament_league_bots`, branche `main`. L'utilisateur travaille sous **Windows** (PowerShell). Chaque bot a un `README.md` détaillé en français : le lire avant de modifier un bot.

## Liens entre les bots

```
bot_inscription_manager  ──écrit──▶  rl_bot_ppname_creator/data/tournois/<id>.json
                                                   │ (lu, jamais modifié)
bot_tournament_manager   ──lit─────────────────────┘
                         ──appelle──▶ rl_bot_ppname_creator/generer_pp_names.py -n <zones>
                         ──écrit────▶ rl_tournament_manager/data/{tournois,pp,archives}/
```

- Les chemins sont réglés dans le `.env` de `tournament_manager` (`DOSSIER_INSCRIPTIONS`, `SCRIPT_PP`), relatifs à `rl_tournament_manager/`.
- Changer le format du JSON d'inscription ou la sortie de `generer_pp_names.py` impacte `tournament_manager` : vérifier `stockage.py`, `pp.py` et leurs tests des deux côtés.
- Une fois lancé, `tournament_manager` a copié titre et équipes : les modifications d'inscription ne s'appliquent plus au tournoi en cours.
- `/reset_tournament_rl` (remise à zéro) efface uniquement les fichiers de `rl_tournament_manager/data/` du tournoi (`Stockage.fichiers_du_tournoi` : état, pp, archives) et supprime ses salons de discussion ; il ne touche jamais au JSON d'inscription.

## Stack

- Python 3 (testé jusqu'à 3.14), `discord.py >= 2.6` : commandes slash (`app_commands`, autocomplétion), modals et boutons (`discord.ui`), `DynamicItem` pour des boutons persistants.
- `python-dotenv` pour la configuration, `pytest >= 8` pour les tests.
- Persistance : fichiers JSON (un par tournoi), pas de base de données.
- `rl_api_pp_connector` : `pyautogui`, `pydirectinput`, `pygetwindow`, `pillow`, `pytesseract` (facultatif, nécessite Tesseract-OCR). Windows uniquement, Rocket League en plein écran fenêtré, Stats API activée (`PacketSendRate > 0` dans `DefaultStatsAPI.ini` et `TAStatsAPI.ini`).

## Lancer et tester

Toutes les commandes se lancent **depuis le dossier du bot** (`rl_bot_mp/`, `rl_bot_ticket/`, `rl_bot_ppname_creator/` ou `rl_tournament_manager/`) :

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # puis remplir (au minimum DISCORD_TOKEN et GUILD_ID)
.venv\Scripts\python -m <paquet>          # bot_mp, bot_ticket, bot_inscription_manager ou bot_tournament_manager
.venv\Scripts\python -m pytest
```

Connecteur Rocket League (depuis `rl_api_pp_connector/`, sur le PC où tourne le jeu) :

```powershell
python rl_join_bot.py --calibrate --resolution 1920x1200 --language en              # calibration des boutons (une fois)
python rl_join_bot.py --calibrate --resolution 1920x1200 --language en --steps leave_match,confirm_yes   # recalibrer seulement certaines étapes
python rl_join_bot.py --calibrate-back-to-menu --resolution 1920x1200 --language en # retour au menu si la partie n'existe pas
python rl_join_bot.py --name 111 --password 111 --resolution 1920x1200 --language en
python rl_match_watcher.py --output resultats.jsonl                                 # lecture seule du score, partie rejointe à la main
```

Pour tester un tournoi complet sans jouer : `DELAI_DECLARATION=5` et `ATTENTE_CLIC_PP_MAX=30` dans le `.env` de `tournament_manager`, puis déclarer les scores avec les boutons (ou `/set_result_tournament_rl`).

`PP_FORCEE_ZONE_2` (`.env` de `tournament_manager`, **tests uniquement**) impose le nom et le mot de passe de la partie privée de la zone 2 (`nom:mot_de_passe`, ou `nom` seul si les deux sont identiques), par exemple pour tester sur une partie déjà créée. Le bot logge un avertissement à chaque round. À laisser vide pour un vrai tournoi.

## rl_api_pp_connector

- Scripts indépendants : `tournament_manager` ne les utilise plus (le score est déclaré par les joueurs). Les modifier n'impacte aucun bot.
- Format d'un résultat (voir `score.example.json`) : `date`, `match_guid`, `arena`, `overtime`, `winner_team_num` (`0` = Bleu, `1` = Orange, `null`), `teams`, `players` (clés Stats API en anglais : `Name`, `TeamNum`, `Goals`…), `partie`, `statut` (`terminé`, `quitté avant la fin`, `connexion perdue`).
- Fichiers propres à chaque PC, ignorés par Git : `positions.json`, `scores.json` (+ `.tmp`/`.bak`), `resultats.jsonl`, `labels.json`. Ne pas les committer.
- Pas de tests automatisés ici (le code pilote le vrai jeu) : tester le pilotage à la main.
- **Rocket League doit rester au premier plan** pendant tout le pilotage : `focus_game()` ne fait plus rien (gardée vide). Le bot ne change plus de fenêtre tout seul ; si une autre fenêtre passe devant, clics et touches partent ailleurs. `click()` affiche dans la console la fenêtre active et signale si elle change pendant un clic (`[!] la fenêtre active a changé…`), utile pour diagnostiquer. En mode script, après `quit`, il faut recliquer soi-même sur le jeu pendant les 5 s d'attente.
- **Résolution** : les positions de `positions.json` sont liées à la résolution de la calibration (actuellement `1920x1200`). Utiliser la même valeur partout (`--resolution`, `RL_RESOLUTION`, plein écran fenêtré) ; si elle change, recalibrer. `--steps` permet de ne recalibrer que certaines étapes.
- Arrêt d'urgence : souris dans le coin haut-gauche (failsafe pyautogui). Ne jamais lancer ce code pour « essayer » : il prend le contrôle de la souris et du clavier.
- Exception de nommage : les fonctions de ce dossier sont en anglais (`join_private_match`, `follow_match`) avec docstrings et messages en français. Garder le style du fichier modifié.

## Structure commune d'un bot

Les trois bots suivent le même découpage. Respecter cette séparation :

- `main.py` : démarrage (`discord.Client` + `CommandTree`), lecture du `.env`, synchro des commandes (sur `GUILD_ID` si défini), enregistrement des `DynamicItem`, messages d'erreur clairs au lieu de traces (token invalide, intent manquant, bot absent du serveur).
- `commandes.py` : commandes slash, autocomplétions, confirmations, gestionnaire d'erreurs.
- `logique.py` : **règles pures, sans Discord ni réseau**, sur le dictionnaire du tournoi (le contenu du JSON). C'est là qu'on met tout ce qui se teste.
- `stockage.py` : lecture / écriture JSON, un fichier par tournoi, écriture atomique (`.json.tmp` puis `os.replace`), un `asyncio.Lock` par tournoi (`verrou(tournoi_id)`).
- Textes et embeds séparés de la logique (`embeds.py`, `messages.py`).

Spécifique à `bot_ticket` : `tickets.py` (boutons « Créer un ticket » et « Fermer le ticket » en `DynamicItem`, liste des catégories, création / fermeture des salons). Pas de `stockage.py` : l'auteur et la catégorie d'un ticket sont dans le sujet du salon (`ticket:<id>:<catégorie>`). Embeds en bleu `0x5865F2` pour ressembler au modèle du panneau Support.

Spécifique à `bot_inscription_manager` : `inscription.py` (bouton S'inscrire, fiches, boutons Valider / Refuser / Annuler en `DynamicItem`, expiration des inscriptions vérifiée chaque minute).

Spécifique à `bot_tournament_manager` :
- `config.py` : lecture et validation du `.env` (`Config`).
- `deroulement.py` : `GestionnaireTournois`, une tâche asyncio par tournoi ; l'état est relu et réécrit à chaque étape, `reprendre()` relance les tournois au redémarrage. Après le clic « Partie privée créée » (ou `ATTENTE_CLIC_PP_MAX` sans clic), le match attend `DELAI_DECLARATION` (360 s) puis passe `a_valider` et les joueurs reçoivent le bouton « Déclarer le score » ; le départ est noté dans `chrono_declaration` pour reprendre le temps restant après un redémarrage. `Messagerie` abstrait l'envoi (`MessagerieDiscord` en vrai, `FausseMessagerie` en test).
- `declaration.py` : boutons « ✅ Partie privée créée » et « 📝 Déclarer le score » (`DynamicItem`, custom_id = tournoi/round/zone/équipe).
- `journal.py` : recopie avertissements et erreurs dans `LOG_CHANNEL` (regroupés ; `extra=HORS_JOURNAL` pour ne pas boucler).
- `pp.py` : appelle `generer_pp_names.py`.

## Tests

- Tous les tests tournent **sans token ni serveur** : faux objets Discord (`FauxMembre`, `FausseInteraction`…) et, pour `tournament_manager`, les outils de `tests/outils.py` (`tournoi_inscription`, `FausseMessagerie`, `faux_pp`, `attendre_que`).
- Pauses mises à 0 dans les fixtures (ex. `PAUSE_ENTRE_MP`).
- Ne jamais déclencher de vrai envoi de MP ni piloter Rocket League pour tester.
- `rl_api_pp_connector/` n'a pas de tests.
- `rl_bot_ppname_creator/` n'a pas de `pytest.ini` (les deux autres en ont un, avec `testpaths = tests` et le filtre du `DeprecationWarning` de `discord.utils`).

## Règles métier à ne pas casser

- **Inscriptions** : liste d'attente = `equipes_max × 4` ; délai de confirmation `DELAI_CONFIRMATION_MINUTES` (30 par défaut), appliqué aux inscriptions faites après redémarrage ; une place libérée va à la première équipe en attente, prévenue en MP ; baisser `equipes_max` sous le nombre d'inscrits est refusé.
- **Tournoi** : une zone par match (`nb_equipes / 2`), zone 1 = basse, dernière = zone haute ⭐ ; gagnant monte, perdant descend ; victoire +1, défaite 0, +3 en zone haute à partir du `golden_round` ; classement : points, victoires, différence de buts, buts marqués.
- Seules les équipes `inscrite` dont tous les joueurs ont confirmé participent.
- Score : `source_resultat` = `declarations` (deux équipes d'accord) ou `admin` (`bot` dans les anciens fichiers, quand l'observateur existait) ; `/set_result_tournament_rl` est toujours prioritaire.
- Statuts JSON : tournoi `en_cours`/`termine`/`arrete`, round `en_cours`/`terminee`, match `en_attente`/`en_cours`/`termine`/`a_valider`/`annule`. Tout changement de format doit rester compatible avec les fichiers existants (ex. les tournois lancés avant `golden_round` gardent +3 dès le round 1).
- `/reset_tournament_rl id_tournoi [garder_salon]` (après confirmation « Oui, tout effacer ») : arrête le tournoi s'il tourne (joueurs prévenus), efface `data/tournois/<id>.json`, `data/pp/<id>_ronde_*.json` et `data/archives/<id>_*.json`, supprime le salon de discussion (sauf `garder_salon: True`) et note la remise à zéro dans `LOG_CHANNEL`. Irréversible ; le tournoi redevient proposé à `/start_tournament_rl`. Pour garder les résultats, c'est `/stop_tournament_rl`.
- Tout doit survivre à un redémarrage : état dans le JSON, boutons en `DynamicItem`.
- Limites Discord : 2000 caractères par message, 4096 par description d'embed, édition d'une interaction impossible après 15 min (repli en MP), ~1 MP/seconde pour `/mp_all`.

## Conventions

- Fins de ligne : plusieurs fichiers sont commités en CRLF mais modifiés en LF, donc `git diff` les montre entièrement changés. Utiliser `git diff -w` pour voir les vrais changements, et ne pas changer les fins de ligne d'un fichier sans raison.
- **Tout en français** (sauf les noms de fonctions de `rl_api_pp_connector`, voir plus haut) : modules, fonctions, variables, classes (`envoyer_a_tous`, `GestionnaireTournois`, `ronde`, `equipe_a`), clés JSON, docstrings, commentaires, logs et textes affichés. Garder cette convention.
- Docstring de module qui explique le rôle du fichier.
- Textes Discord : tutoiement, phrases courtes, emoji en tête (✅ ❌ ⏳ 📨 📝 🔒 ⚠️ 👀 ⭐ 🌟), pluriels gérés. Réponses aux admins en éphémère.
- « Admins » = permission **Gérer le serveur** (`@app_commands.default_permissions(manage_guild=True)`).
- `from __future__ import annotations` et annotations de type sur les signatures. `logique` souvent importé sous l'alias `L`.
- Couleur des embeds : orange `0xE67E22`, commune aux bots (sauf `bot_ticket`, en bleu `0x5865F2`).
- Erreurs : attraper `discord.Forbidden` / `discord.HTTPException` au plus près, logger, et toujours donner un message compréhensible (jamais une trace). Une erreur sur un joueur ou une zone ne doit pas arrêter les autres.
- Quand une permission Discord manque, dire quoi cocher et où.
- Tests nommés en français, décrivant le comportement (`test_annuler_n_envoie_rien`). Chaque nouveau comportement s'accompagne d'un test.
- Mettre à jour le `README.md` du bot concerné (commandes, réglages, format JSON) à chaque changement visible.

## Nouveau bot

Reprendre la structure existante : dossier `rl_<nom>/` avec un paquet lancé par `python -m <paquet>`, `requirements.txt`, `.env.example` commenté, `.gitignore` (`.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `data/`), `pytest.ini`, `tests/`, `README.md`. Une nouvelle application Discord par bot (deux bots avec le même token écraseraient leurs commandes).

## Sécurité

- Ne jamais lire, afficher ni committer un `.env`, un token Discord ou le contenu de `data/` (ignorés par Git).
- `rl_api_pp_connector` automatise clavier et souris dans Rocket League (zone grise des CGU) : le README conseille un compte secondaire.
- `LOG_CHANNEL` et les fichiers `data/pp/` contiennent les mots de passe des parties : ne pas les exposer dans un salon public.
