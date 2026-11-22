# tournament_manager — bot Discord qui fait jouer les tournois Rocket League

Il prend un tournoi créé avec le bot d'inscription (`rl_bot_ppname_creator`), répartit les équipes dans des **zones**, envoie les infos de partie privée en MP, prend les scores et tient le classement.

## Commandes

| Commande | Qui | Ce qu'elle fait |
|---|---|---|
| `/start_tournament_rl id_tournoi nombre_de_matchs [golden_round]` | admins | Lance le tournoi et crée son salon de discussion (voir « Salons »). `nombre_de_matchs` = nombre de matchs joués par chaque équipe (= nombre de rounds). `golden_round` (facultatif, 1 par défaut) = round à partir duquel la victoire en zone haute rapporte +3 (voir « Points »). |
| `/start_tournament_rl_status id_tournoi` | tout le monde | Round en cours, état de chaque zone et classement (réponse visible par toi seul). |
| `/stop_tournament_rl id_tournoi` | admins | Arrête le tournoi (après confirmation) : matchs en cours annulés, joueurs prévenus en MP. |
| `/set_result_tournament_rl id_tournoi zone gagnant score_gagnant score_perdant` | admins | Fixe le score d'un match (score pas pris par le bot, déclarations différentes, match bloqué…). Toujours prioritaire. |
| `/edit_player_tournament_rl id_tournoi joueur [pseudo_jeu] [pseudo] [nom_equipe] [devient_capitaine] [remplace_par]` | admins | Modifie un joueur pendant le tournoi (voir « Modifier un joueur pendant le tournoi »). |
| `/reset_tournament_rl id_tournoi [garder_salon]` | admins | Remet le tournoi à zéro (après confirmation) : efface tout ce que le bot a gardé sur lui pour le relancer de zéro (voir « Remettre un tournoi à zéro »). |

`id_tournoi`, `zone`, `gagnant` et `joueur` sont proposés en autocomplétion.
« Admins » = membres avec la permission **Gérer le serveur**.

Les joueurs n'ont pas de commande à taper, ils ont des boutons dans leurs MP :
- **✅ Partie privée créée** : pour le capitaine qui crée la partie ;
- **📝 Déclarer le score** : quand le bot n'a pas pu prendre un score.

## Déroulement

**Zones** : il y a une zone par match, soit `nombre d'équipes / 2` (8 équipes → 4 zones). La zone 1 est la plus basse, la dernière est la **zone haute ⭐**.

1. **Round 1** : les équipes sont tirées au hasard et placées deux par deux dans les zones.
2. Le bot génère une partie privée par zone avec `generer_pp_names.py -n <nombre de zones>` (le match 1 va en zone 1, etc.).
3. **Tous les matchs se jouent en même temps.** Dès le début du round, pour chaque zone :
   - le capitaine de l'équipe A reçoit : « Vous devez créer la partie privée avec le nom = … et le mot de passe = … », avec le bouton **✅ Partie privée créée** ;
   - les autres joueurs des deux équipes reçoivent le nom et le mot de passe pour la rejoindre ;
   - consigne de couleur : équipe A en 🔵 Bleu, équipe B en 🟠 Orange ;
   - consigne : **« Ne quittez pas et ne relancez pas la partie tant que le bot n'a pas pris le score. »**
4. **Le capitaine clique sur « Partie privée créée »** (voir plus bas) : les autres joueurs sont prévenus, et le bot commence à prendre le score de ce match (avec le vrai connecteur, il passe dans les parties l'une après l'autre : voir plus bas).
5. **Score pris** : chaque joueur reçoit « ✅ Le bot a pris le score : c'est bon, vous pouvez quitter la partie », avec le score, ses points et sa zone au prochain round. Le score et les points sont écrits dans le fichier JSON.
6. **Score pas pris** (partie introuvable, joueurs partis avant le passage du bot, partie relancée…) : voir « Déclaration des scores » plus bas.
7. Quand toutes les zones ont un score : pause (`PAUSE_ENTRE_RONDES`), puis round suivant :
   - le **gagnant monte** d'une zone (le gagnant de la zone haute y reste) ;
   - le **perdant descend** d'une zone (le perdant de la zone 1 y reste).

Le tout recommence `nombre_de_matchs` fois. À la fin, le classement final est posté dans le salon des annonces et chaque joueur reçoit sa place en MP.

**Points** : victoire **+1**, défaite **0**. À partir du **golden round 🌟**, la victoire en zone haute ⭐ rapporte **+3**.

| Round | Victoire en zone haute ⭐ | Victoire ailleurs | Défaite |
|---|---|---|---|
| avant `golden_round` | +1 | +1 | 0 |
| à partir de `golden_round` | **+3** | +1 | 0 |

Sans `golden_round` (ou avec `golden_round: 1`), la zone haute rapporte +3 dès le round 1. `golden_round` doit être entre 1 et `nombre_de_matchs`. Exemple : 8 équipes, 4 rounds, `golden_round: 3` → aux rounds 1 et 2 toutes les victoires valent +1, ce qui laisse aux équipes le temps de monter ; aux rounds 3 et 4 la zone haute vaut +3. L'annonce de chaque round rappelle le golden round et le gain de chaque zone ; `/start_tournament_rl_status` affiche le barème du round en cours. Les tournois lancés avant cette option gardent le +3 dès le round 1.
**Classement** : points, puis victoires, puis différence de buts, puis buts marqués.

**Quelle équipe était en Bleu ?** Le bot compare les pseudos en jeu renvoyés par Rocket League aux `pseudo_jeu` du fichier d'inscription. Il voit donc si les équipes se sont trompées de couleur. S'il ne reconnaît personne, il applique la consigne (équipe A = Bleu).

**Redémarrage** : tout est enregistré au fur et à mesure. Si le bot redémarre, les tournois en cours reprennent où ils en étaient, les joueurs des matchs en cours reçoivent un rappel, et les boutons déjà envoyés marchent toujours (un capitaine qui avait déjà cliqué n'a pas à recliquer).

### Bouton « Partie privée créée »

- Seul le capitaine qui doit créer la partie a ce bouton (un autre joueur qui clique est refusé).
- **Au clic** : les 3 autres joueurs reçoivent « ✅ … a créé la partie privée, tu peux la rejoindre », le bouton devient gris, et le bot commence à prendre le score.
- Seul le premier clic compte. Un clic sur un autre bouton (celui du rappel, ou après un redémarrage) répond juste « Déjà noté ».
- **Clic trop tôt** (partie pas encore créée) : le bot ne la trouve pas et réessaie au passage suivant. Dès le premier échec, le capitaine reçoit de nouveau le nom et le mot de passe.
- **Pas de clic** : rappel au capitaine après `RAPPEL_CLIC_PP` (3 min), puis après `ATTENTE_CLIC_PP_MAX` (10 min) le bot passe quand même dans la partie, avec une alerte dans `LOG_CHANNEL`.
- Le clic est enregistré dans le JSON du match (`pp_creee_le`, `pp_creee_par`).

### Déclaration des scores

Quand le bot n'a pas pu prendre le score d'un match :
- une **alerte** part dans `LOG_CHANNEL` (voir plus bas) ;
- chaque joueur des deux équipes reçoit en MP le bouton **📝 Déclarer le score** : une petite fenêtre demande les buts de son équipe et ceux de l'adversaire.

Ensuite :
- un joueur de chaque équipe déclare ; une nouvelle déclaration remplace la précédente de son équipe ;
- **les deux équipes déclarent le même score** → validé tout seul, MP de fin de match comme d'habitude ;
- **scores différents** → alerte dans `LOG_CHANNEL` (avec les deux déclarations), et MP aux deux équipes « un admin va trancher » (elles peuvent encore corriger) ;
- **score déclaré plus bas que le dernier score vu par le bot** (impossible) → alerte, pas de validation automatique ;
- `/set_result_tournament_rl` reste prioritaire à tout moment.

Le round attend que tous ses matchs aient un score ; les autres zones, elles, continuent normalement.

### Modifier un joueur pendant le tournoi

`/edit_player_tournament_rl` : choisis le tournoi, puis le joueur dans la liste (👑 = capitaine), puis remplis seulement ce qui change. Le changement compte tout de suite, sans redémarrer le bot.

| Option | Effet |
|---|---|
| `pseudo_jeu` | Son pseudo dans Rocket League. Sert à reconnaître la couleur de son équipe, dès le prochain score pris. Refusé s'il est déjà celui d'un autre joueur. |
| `pseudo` | Le pseudo affiché par le bot (MP, alertes). |
| `nom_equipe` | Le nom de son équipe. Refusé si une autre équipe s'appelle déjà comme ça. |
| `devient_capitaine: True` | Il devient capitaine de son équipe. L'ancien capitaine est prévenu en MP. Si son équipe doit encore créer la partie privée du round en cours, le nouveau capitaine reçoit le MP avec le bouton **✅ Partie privée créée**, et le bouton de l'ancien ne marche plus. |
| `remplace_par` | Un membre du serveur prend sa place dans l'équipe (il reprend le rôle de capitaine si le joueur remplacé l'avait). `pseudo` et `pseudo_jeu` s'appliquent alors au remplaçant ; sans `pseudo`, c'est son nom sur le serveur. |

Pour un **remplaçant**, le bot :
- prévient le remplaçant et le joueur remplacé en MP ;
- envoie au remplaçant les infos du match en cours de son équipe (partie privée à rejoindre, ou à créer s'il est le capitaine qui doit la créer), ou le bouton **📝 Déclarer le score** si le match attend les déclarations ;
- lui donne accès au salon de discussion et le retire à l'ancien joueur. Pour ça, il faut au bot **Gérer les rôles** (Discord l'exige pour modifier un salon qui existe déjà). Sans cette permission, la réponse de la commande te dit de l'ajouter à la main ;
- les MP suivants (partie créée, fin de match, classement final) partent au remplaçant ; les anciens boutons du joueur remplacé ne marchent plus.

Chaque modification est notée dans le JSON (`modifications` : qui, quand, avant → après) et dans `LOG_CHANNEL`. On ne peut pas modifier un tournoi terminé ou arrêté, ni ajouter ou retirer une équipe. Le fichier d'inscription n'est pas modifié.

### Remettre un tournoi à zéro

`/reset_tournament_rl` sert à recommencer un tournoi depuis le début (tournoi lancé par erreur, mauvais nombre de rounds, test…). Le bot affiche d'abord ce qu'il va effacer et demande de confirmer avec **Oui, tout effacer**. Ensuite :
- si le tournoi est **en cours**, il s'arrête : matchs en cours annulés, annonce dans le salon des annonces et MP à chaque joueur (« tu peux quitter la partie privée ») ;
- tous ses fichiers dans `data/` sont effacés : état et scores (`data/tournois/<id>.json`), parties privées de chaque round (`data/pp/<id>_ronde_<n>.json`) et anciens lancements archivés (`data/archives/<id>_*.json`) ;
- son **salon de discussion** est supprimé avec ses messages (et ceux des anciens lancements archivés). Avec `garder_salon: True`, il reste : supprime-le à la main quand tu veux. S'il manque **Gérer les salons** au bot, la réponse le dit et le reste est quand même effacé ;
- la remise à zéro est notée dans `LOG_CHANNEL`.

Le fichier d'inscription (`../rl_bot_ppname_creator/data/tournois/<id>.json`) n'est **jamais touché** : équipes et joueurs restent inscrits. Relance le tournoi avec `/start_tournament_rl` (le tournoi est de nouveau proposé dans l'autocomplétion). **On ne peut pas revenir en arrière** : pour garder les résultats, utilise plutôt `/stop_tournament_rl`.

### Salons

**Salon des annonces** (`SALON_ANNONCES`, sinon le salon où le tournoi a été créé) — public :
- les zones au début de chaque round ;
- l'annonce de l'arrêt du tournoi ;
- le classement final.

**Salon de discussion** (un par tournoi, créé par `/start_tournament_rl`) — privé :
- nom `💬-<titre-du-tournoi>`, dans la **même catégorie** que le salon où le tournoi a été créé avec le bot d'inscription (à la racine du serveur si ce salon n'est pas dans une catégorie) ;
- visible seulement par les **joueurs des équipes participantes**, les **admins** (rôles avec « Gérer le serveur » ou « Administrateur »), l'admin qui a lancé le tournoi et le bot. Ils peuvent y écrire et y envoyer des fichiers (captures de score) ;
- le bot y poste un message de bienvenue qui mentionne chaque joueur ; les mots de passe des parties restent en MP ;
- un joueur qui a quitté le serveur n'y a pas accès : le bot le signale dans `LOG_CHANNEL` ;
- son ID est gardé dans le JSON (`salon_discussion_id`). À la fin ou à l'arrêt du tournoi, le salon reste : supprime-le à la main quand tu veux. Un tournoi relancé a un nouveau salon. `/reset_tournament_rl` le supprime (sauf avec `garder_salon: True`).

Il faut au bot **Gérer les salons** et **Joindre des fichiers** (en plus des permissions d'annonce) sur le serveur, et que la catégorie ne les lui retire pas. Sinon `/start_tournament_rl` refuse de lancer le tournoi et dit quoi cocher, et où (rôle du bot sur le serveur, ou catégorie).

**Catégorie en lecture seule** (les membres ne peuvent pas écrire) : elle retire aussi ces permissions au bot, et réinviter le bot n'y change rien. Clic droit sur la catégorie > **Modifier la catégorie** > **Permissions** > rôle du bot > mets en ✅ vert **Gérer les salons**, **Envoyer des messages**, **Intégrer des liens** et **Joindre des fichiers**. Les membres restent bloqués ; seul le bot reçoit ces droits.

**`LOG_CHANNEL`** — à réserver aux admins, car il contient les mots de passe des parties :
- « ✅ Bot démarré » au lancement du bot ;
- les **alertes** (score pas pris, déclarations différentes, déclaration impossible, capitaine qui n'a pas cliqué sur « Partie privée créée »), qui mentionnent l'admin qui a lancé le tournoi et donnent :
  - le nom et le mot de passe de la partie, son créateur et les équipes (pour la rejoindre à la main) ;
  - le dernier score vu par le bot et les déclarations des équipes ;
  - la commande `/set_result_tournament_rl` déjà remplie, avec les numéros d'équipes ;
- les **modifications de joueurs** faites avec `/edit_player_tournament_rl` (sans mentionner personne) ;
- les **problèmes du bot** (avertissements et erreurs de la console : permissions, salon introuvable, calibration…), regroupés pour éviter le spam.

Si `LOG_CHANNEL` est vide, les alertes partent en MP à l'admin qui a lancé le tournoi.

## Fichiers

| Fichier | Contenu |
|---|---|
| `../rl_bot_ppname_creator/data/tournois/<id>.json` | Inscriptions (lues, jamais modifiées). Seules les équipes `inscrite` dont tous les joueurs ont confirmé participent. |
| `data/tournois/<id>.json` | **État et résultats** : équipes (points, victoires, buts, historique), rounds (`rondes`), matchs, scores, déclarations. |
| `data/pp/<id>_ronde_<n>.json` | Parties privées de chaque round (sortie de `generer_pp_names.py`). |
| `data/archives/` | Ancien fichier de résultats quand on relance un tournoi déjà terminé ou arrêté. |

`/reset_tournament_rl` efface les trois fichiers d'un tournoi (`data/tournois/`, `data/pp/`, `data/archives/`), jamais son fichier d'inscription.

### `data/tournois/<id>.json`

```json
{
  "tournoi_id": "1571169059024928818",
  "titre": "cac",
  "statut": "en_cours",
  "salon_discussion_id": "1572600000000000000",
  "nombre_de_rondes": 3,
  "golden_round": 2,
  "nb_zones": 4,
  "lance_par": "1540386073958682779",
  "equipes": {
    "1": {
      "id": 1, "nom": "lecacacdelicieux", "capitaine_id": "1540386073958682779",
      "joueurs": [{ "id": "1540386073958682779", "pseudo": "thomas", "pseudo_jeu": "tomatoKing" }],
      "zone_actuelle": 3,
      "points": 4, "matchs_joues": 2, "victoires": 2, "defaites": 0,
      "buts_pour": 7, "buts_contre": 3,
      "historique": [
        { "ronde": 1, "zone": 3, "adversaire": 2, "score": "3-1", "resultat": "victoire", "points": 1 }
      ]
    }
  },
  "modifications": [
    {
      "le": "2026-11-18T16:05:00", "par": "1540386073958682779", "equipe": 1, "joueur": "296738272648888321",
      "changements": { "pseudo_jeu": ["tomatoKimg", "tomatoKing"] },
      "ancien_joueur": { "id": "296738272648888321", "pseudo": "martino1571", "pseudo_jeu": "tomatoKimg" }
    }
  ],
  "rondes": [
    {
      "numero": 1, "statut": "terminee", "fichier_pp": "1571169059024928818_ronde_1.json",
      "matchs": [
        {
          "zone": 3,
          "pp": { "nom": "tomato_agntyp", "mot_de_passe": "tomato_agntyp" },
          "equipe_a": 1, "equipe_b": 2,
          "statut": "termine",
          "score": { "equipe_a": 3, "equipe_b": 1 },
          "vainqueur": 1, "points_attribues": 1,
          "bleu": 1, "couleurs_detectees_par": "pseudos",
          "source_resultat": "bot",
          "declarations": {},
          "pp_creee_le": "2026-11-18T15:42:10", "pp_creee_par": "1540386073958682779",
          "raison_a_valider": null, "valide_par": null,
          "resultat_observateur": { "...": "résultat brut, format de rl_api_pp_connector" }
        }
      ]
    }
  ]
}
```

| Champ | Valeurs possibles |
|---|---|
| `statut` du tournoi | `en_cours`, `termine`, `arrete` |
| `statut` d'un round | `en_cours`, `terminee` |
| `statut` d'un match | `en_attente`, `en_cours`, `termine`, `a_valider` (score pas pris), `annule` |
| `source_resultat` | `bot`, `declarations` (les deux équipes d'accord), `admin` |
| `declarations` | `{"<id équipe>": {"pour": 3, "contre": 1, "par": "<id Discord>", "le": "…"}}` |

## Observation des matchs

`OBSERVATEUR` dans le `.env` choisit qui prend les scores.

### `OBSERVATEUR=simulation`

Comme en vrai, le simulateur attend le clic du capitaine sur « Partie privée créée » (ou `ATTENTE_CLIC_PP_MAX`). Ensuite, chaque match « dure » entre `SIMULATION_DUREE_MIN` et `SIMULATION_DUREE_MAX` secondes. Pour tester vite sans capitaine, mets par exemple `ATTENTE_CLIC_PP_MAX=30`. Le simulateur renvoie ensuite un score aléatoire **au format exact du connecteur** (`build_result` + `partie` + `statut`), avec les vrais pseudos en jeu des joueurs. On peut ainsi faire tourner un tournoi complet sans jouer.

Deux réglages servent à tester les cas difficiles :
- `SIMULATION_PROBA_COULEURS_INVERSEES` : les équipes se trompent de couleur ;
- `SIMULATION_PROBA_SANS_GAGNANT` : le bot n'a pas le score, les joueurs reçoivent le bouton de déclaration et `LOG_CHANNEL` reçoit l'alerte.

Pour voir un résultat simulé :

Windows (PowerShell) :
```powershell
.venv\Scripts\python -m bot_tournament_manager.simulateur --bleu tomatoKing,cacacaca --orange crazyTomato,gogol
```
Linux / macOS (Bash) :
```bash
.venv/bin/python -m bot_tournament_manager.simulateur --bleu tomatoKing,cacacaca --orange crazyTomato,gogol
```

### `OBSERVATEUR=rl` : le vrai connecteur

Le bot utilise le code de `rl_api_pp_connector` (`rl_join_bot.py`, `rl_match_watcher.py`, `positions.json`) sans le modifier.

**La tournée** : tous les matchs se jouent en même temps, et le bot n'a qu'un Rocket League. Il passe donc dans les parties l'une après l'autre : zone 1 → zone 2 → … → zone 1 → … À chaque passage :
1. il rejoint la partie privée (menus du jeu, nom et mot de passe) ;
2. il passe spectateur ;
3. il lit la Stats API pendant `RL_DUREE_LECTURE` secondes : joueurs, score, temps restant ;
4. il quitte la partie et revient au menu principal.

Il ne reste jamais jusqu'à la fin d'un match. C'est pour ça que les joueurs doivent rester dans la partie après la fin : au passage suivant, le bot voit que le match est fini et prend le score. Une partie entre dans la tournée quand son capitaine clique sur « Partie privée créée » (ou après `ATTENTE_CLIC_PP_MAX` sans clic) : le bot ne perd pas de temps dans les parties pas encore créées.

Le bot abandonne une partie (et demande la déclaration aux joueurs) quand :
- il n'arrive pas à la rejoindre `RL_TENTATIVES` fois de suite (pas créée, nom faux, joueurs partis…) ;
- la partie a été relancée (nouveau match) avant qu'il prenne le score.

**Arrêt d'urgence** : souris dans le coin en haut à gauche de l'écran. Le bot arrête de piloter le jeu, les matchs en cours passent en déclaration par les joueurs. Redémarre le bot pour relancer l'observation.

**Après un échec de connexion**, le bot appelle `back_to_main_menu` de `rl_join_bot.py` : il rejoue le chemin enregistré avec `--calibrate-back-to-menu`, sinon il appuie sur Échap `RL_ECHAP_RETOUR_MENU` fois. Tant que ce chemin n'est pas calibré, il le signale au démarrage.

#### Mise en route

1. Le bot doit tourner **sur le PC où Rocket League est ouvert**, et personne ne doit utiliser ce PC pendant le tournoi (le bot pilote la souris et le clavier).
2. Installe les modules du connecteur dans le venv du bot :

   Windows (PowerShell) :
   ```powershell
   .venv\Scripts\python -m pip install -r ..\rl_api_pp_connector\requirements.txt
   ```
   Linux / macOS (Bash) :
   ```bash
   .venv/bin/python -m pip install -r ../rl_api_pp_connector/requirements.txt
   ```
3. Stats API activée et boutons calibrés : voir le README de `rl_api_pp_connector`. Calibre aussi `spectate`, `leave_match`, et le retour au menu quand la partie n'existe pas (`python rl_join_bot.py --calibrate-back-to-menu --resolution 1920x1200 --language en`).
4. Dans le `.env` : `OBSERVATEUR=rl`, `RL_LANGUE` (langue du jeu), et `LOG_CHANNEL`. Les autres `RL_*` ont des valeurs par défaut.
5. **Essai sans Discord ni tournoi** : Rocket League au menu principal, quelqu'un crée une partie privée, puis :

   Windows (PowerShell) :
   ```powershell
   .venv\Scripts\python -m bot_tournament_manager.essai_rl --nom tomato_abc --mot-de-passe tomato_abc --visites 3
   ```
   Linux / macOS (Bash) :
   ```bash
   .venv/bin/python -m bot_tournament_manager.essai_rl --nom tomato_abc --mot-de-passe tomato_abc --visites 3
   ```
   Le bot fait 3 passages dans la partie et affiche ce qu'il a lu (événements, score, joueurs, match fini ou non), puis le résultat qu'il enregistrerait. Lance-le aussi sur une partie **déjà terminée** dont les joueurs sont restés sur l'écran de fin : il doit afficher « Match terminé : oui ».
6. Lance le bot. Au démarrage, la console (et `LOG_CHANNEL`) signale ce qui cloche : modules manquants, calibration incomplète, écran d'une autre taille que la calibration, Rocket League fermé.

## Installation

### 1. Créer le bot sur Discord
1. https://discord.com/developers/applications > **New Application** (nom : `tournament_manager`). Il faut une **autre application** que le bot d'inscription : deux bots avec le même token écraseraient leurs commandes.
2. Onglet **Bot** > **Reset Token** > copie le token.
3. Invite le bot sur ton serveur (remplace `APPLICATION_ID`) :
   `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot+applications.commands&permissions=117776`
   Dans le salon des annonces et dans `LOG_CHANNEL`, il lui faut **Voir le salon**, **Envoyer des messages** et **Intégrer des liens**.
   Pour créer le salon de discussion de chaque tournoi, il lui faut aussi **Gérer les salons**, **Joindre des fichiers** et **Voir les anciens messages** (déjà dans le lien). Si le bot a été invité avec l'ancien lien (`permissions=84992`), réinvite-le avec celui-ci ou ajoute ces permissions à son rôle.
   Facultatif : **Gérer les rôles**, pour que `/edit_player_tournament_rl` ajoute lui-même un remplaçant au salon de discussion (sinon tu le fais à la main). Le lien ne la contient pas : ajoute-la au rôle du bot si tu veux.

Aucun « Privileged Gateway Intent » n'est nécessaire.

### 2. Configurer
Remplis le fichier `.env` (modèle : `.env.example`) :
- `DISCORD_TOKEN` : le token du bot ;
- `GUILD_ID` : l'ID de ton serveur ;
- `SALON_ANNONCES` (facultatif) : l'ID du salon des annonces ;
- `LOG_CHANNEL` (conseillé) : l'ID du salon privé des alertes.

Pour copier un ID : Paramètres Discord > Avancés > **Mode développeur**, puis clic droit sur le salon > **Copier l'identifiant du salon**.

Les autres réglages ont des valeurs par défaut prêtes à l'emploi.

### 3. Lancer
Windows (PowerShell) :
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
# Seulement avec OBSERVATEUR=rl : modules du connecteur (pyautogui, pillow…).
# Sans eux, le bot s'arrête avec « Module manquant : pip install pyautogui pillow ».
.venv\Scripts\python -m pip install -r ..\rl_api_pp_connector\requirements.txt
.venv\Scripts\python -m bot_tournament_manager
```
Linux / macOS (Bash) :
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# Seulement avec OBSERVATEUR=rl : modules du connecteur (pyautogui, pillow…).
# Sans eux, le bot s'arrête avec « Module manquant : pip install pyautogui pillow ».
.venv/bin/python -m pip install -r ../rl_api_pp_connector/requirements.txt
.venv/bin/python -m bot_tournament_manager
```

### Tests
Windows (PowerShell) :
```powershell
.venv\Scripts\python -m pytest
```
Linux / macOS (Bash) :
```bash
.venv/bin/python -m pytest
```
