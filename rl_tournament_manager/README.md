# tournament_manager — bot Discord qui fait jouer les tournois Rocket League

Il prend un tournoi créé avec le bot d'inscription (`rl_bot_ppname_creator`), répartit les équipes dans des **zones**, envoie les infos de partie privée en MP, demande les scores aux joueurs et tient le classement.

## Commandes

| Commande | Qui | Ce qu'elle fait |
|---|---|---|
| `/start_tournament_init id_tournoi delai_confirmation` | admins | **Obligatoire** avant le lancement : crée le salon de discussion du tournoi (voir « Salons »), y poste « @here Le tournoi va bientôt commencer, soyez prêts ! Bonne chance à tous 🍀 », et demande aux équipes de **valider leur participation** dans les `delai_confirmation` minutes (1 à 1440), sinon la liste d'attente prend leur place (voir « Validation des participations »). |
| `/start_tournament_init_status id_tournoi` | admins | Entre `/start_tournament_init` et le lancement : où en sont les équipes (réponse visible par toi seul). Délai restant, nombre d'équipes qui ont validé, puis **✅ Ont validé** (qui a cliqué et à quelle heure), **⏳ Pas encore validé**, **❌ Places perdues** et **📋 Liste d'attente** (avec la position), chaque équipe avec ses joueurs (👑 capitaine, pseudo en jeu). ⬆️ marque les équipes montées de la liste d'attente. Ne modifie rien. |
| `/start_tournament_rl id_tournoi nombre_de_matchs [golden_round] [zone_1] [zone_2] [zone_3] [zone_4]` | admins | Lance le tournoi avec les équipes qui ont validé leur participation (montées de la liste d'attente comprises), dans le salon créé par `/start_tournament_init`. **Refusé** (message d'erreur, rien n'est lancé) si `/start_tournament_init` n'a pas été fait, ou si le délai de validation n'est pas fini. `nombre_de_matchs` = nombre de matchs joués par chaque équipe (= nombre de rounds). `golden_round` (facultatif, 1 par défaut) = round à partir duquel la victoire en zone haute rapporte +3 (voir « Points »). `zone_1` à `zone_4` (facultatifs, 0 à 20) = points d'une victoire dans cette zone à partir du golden round ; **refusé** si le tournoi n'a pas cette zone (ex. `zone_4` avec 6 équipes). |
| `/start_tournament_rl_status id_tournoi` | tout le monde | Round en cours, état de chaque zone et classement (réponse visible par toi seul). |
| `/stop_tournament_rl id_tournoi` | admins | Arrête le tournoi (après confirmation) : matchs en cours annulés, joueurs prévenus en MP. |
| `/start_tournament_modify_pp id_tournoi zone nom [mot_de_passe]` | admins | Change le nom et le mot de passe de la partie privée d'une zone du round en cours (`mot_de_passe` vide = le même que le nom). Partie déjà créée : tous les joueurs du match reçoivent la nouvelle en MP. Sinon : le capitaine reçoit la nouvelle partie à créer, et les autres la recevront à son clic. Noté dans `LOG_CHANNEL`. |
| `/set_result_tournament_rl id_tournoi zone gagnant score_gagnant score_perdant` | admins | Fixe le score d'un match (déclarations différentes ou manquantes, match bloqué…). Toujours prioritaire. |
| `/edit_player_tournament_rl id_tournoi joueur [pseudo_jeu] [pseudo] [nom_equipe] [devient_capitaine] [remplace_par]` | admins | Modifie un joueur pendant le tournoi (voir « Modifier un joueur pendant le tournoi »). |
| `/reset_tournament_rl id_tournoi [garder_salon]` | admins | Remet le tournoi à zéro (après confirmation) : efface tout ce que le bot a gardé sur lui pour le relancer de zéro (voir « Remettre un tournoi à zéro »). |

`id_tournoi`, `zone`, `gagnant` et `joueur` sont proposés en autocomplétion.
« Admins » = membres avec la permission **Gérer le serveur**.

Les joueurs n'ont pas de commande à taper, ils ont des boutons dans leurs MP :
- **✅ Partie privée créée** : pour le capitaine qui crée la partie ;
- **📝 Déclarer le score** : envoyé 6 minutes après la création de la partie (`DELAI_DECLARATION`).

## Validation des participations

`/start_tournament_init id_tournoi delai_confirmation` envoie, en plus du salon :
- à **chaque joueur des équipes inscrites** : « tu as `delai_confirmation` minutes (jusqu'à HH:MM) pour valider la participation de ton équipe, sinon elle perdra sa place », avec le bouton **✅ Valider ma participation**. **Un seul joueur de l'équipe suffit** ; ses coéquipiers sont prévenus en MP. L'heure s'affiche à l'heure de chaque joueur ;
- à **chaque joueur de la liste d'attente** (ordre du bot d'inscription, seulement les équipes dont tous les joueurs ont confirmé) : sa position, « reste ici : si une équipe ne valide pas sa participation dans les `delai_confirmation` minutes, tu avanceras dans la liste d'attente ». L'équipe **1re** de la liste lit en plus « si une équipe ne valide pas, tu participeras au tournoi » (elle recevra alors le bouton pour valider).

À la fin du délai (ou dès que toutes les équipes ont validé) :
- les équipes qui n'ont pas validé **perdent leur place** (MP) et leur accès au salon de discussion ;
- les premières équipes de la liste d'attente **prennent ces places**, dans l'ordre : MP « 🎉 ton équipe participe au tournoi » avec le **même bouton ✅ Valider ma participation** et un **nouveau délai** de `delai_confirmation` minutes, et accès au salon (il faut au bot **Gérer les rôles**, sinon `LOG_CHANNEL` dit qui ajouter à la main) ;
- les équipes qui restent en liste d'attente reçoivent leur nouvelle position (seulement quand la liste avance : pas de MP à la fin des validations) ;
- une équipe montée qui ne valide pas à temps perd la place à son tour, et l'équipe suivante de la liste d'attente monte (même délai). Ça continue jusqu'à ce que toutes les équipes aient validé ou que la liste d'attente soit vide ; `LOG_CHANNEL` note chaque étape ;
- à la toute fin, le bilan est posté dans le salon de discussion et dans `LOG_CHANNEL`, et `/start_tournament_rl` peut être lancé.

Pour suivre les validations pendant le délai : `/start_tournament_init_status id_tournoi`.

Un bouton cliqué après le délai répond « le délai est passé ». Le délai survit à un redémarrage du bot (heure de fin gardée dans `data/salons/<id>.json`). Si le nombre d'équipes final est impair (pas assez d'équipes en liste d'attente), `/start_tournament_rl` le refuse : remets le tournoi à zéro (`/reset_tournament_rl`) et refais `/start_tournament_init`. Le fichier d'inscription n'est jamais modifié.

## Déroulement

**Zones** : il y a une zone par match, soit `nombre d'équipes / 2` (8 équipes → 4 zones). La zone 1 est la plus basse, la dernière est la **zone haute ⭐**.

1. **Round 1** : les équipes sont tirées au hasard et placées deux par deux dans les zones.
2. Le bot donne une partie privée par zone, nommée `tomato_` + numéro du round + numéro de la zone : au round 1, **tomato_11** en zone 1, **tomato_12** en zone 2, **tomato_13** en zone 3, etc. ; au round 2, **tomato_21**, **tomato_22**… ; au round 12, **tomato_121**… Le mot de passe est le même que le nom. À partir de 10 zones, la zone s'écrit sur 2 chiffres pour tout le tournoi (round 1 : tomato_101 … tomato_112), pour éviter les doublons.
3. **Tous les matchs se jouent en même temps.** Dès le début du round, pour chaque zone :
   - le capitaine de l'équipe A reçoit : « Vous devez créer la partie privée avec le nom = … et le mot de passe = … », avec le bouton **✅ Partie privée créée** ;
   - les autres joueurs des deux équipes reçoivent leur match, **sans le nom ni le mot de passe** : ils les reçoivent seulement quand le capitaine a créé la partie (MP « ✅ … a créé la partie privée ») ;
   - consigne de couleur : équipe A en 🔵 Bleu, équipe B en 🟠 Orange ;
   - consigne : à la fin du match, le bot leur envoie un MP pour déclarer le score.
4. **Le capitaine clique sur « Partie privée créée »** (voir plus bas) : les autres joueurs sont prévenus, et le délai `DELAI_DECLARATION` (**6 min** par défaut) démarre.
5. **6 minutes après le clic**, chaque joueur des deux équipes reçoit le MP « 📝 Déclare le score de ton match » avec le bouton **Déclarer le score** : voir « Déclaration des scores » plus bas. Le bot ne lit plus le score dans Rocket League.
6. **Score validé** : chaque joueur reçoit le score, ses points et sa zone au prochain round. Le score et les points sont écrits dans le fichier JSON.
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

**Points par zone** (`zone_1` à `zone_4`, facultatifs) : chaque option donne les points d'une victoire dans cette zone **à partir du golden round** (avant, toutes les victoires restent à +1 ; une défaite vaut toujours 0). Une zone non renseignée garde le barème ci-dessus (+3 si c'est la zone haute, +1 sinon), comme les zones 5 et plus. Une option pour une zone que le tournoi n'a pas (ex. `zone_4` avec 6 équipes, donc 3 zones) fait **refuser** le lancement. Exemple : 8 équipes, 3 rounds, `golden_round: 2 zone_1: 5 zone_2: 6 zone_3: 7 zone_4: 10` → au round 1 toutes les victoires valent +1, aux rounds 2 et 3 elles valent +5, +6, +7 et +10 selon la zone. Les points choisis sont gardés dans le JSON (`points_zones`), et affichés au lancement, dans l'annonce de chaque round et dans `/start_tournament_rl_status`.
**Classement** : points, puis victoires, puis différence de buts, puis buts marqués.

**Redémarrage** : tout est enregistré au fur et à mesure. Si le bot redémarre, les tournois en cours reprennent où ils en étaient, les joueurs des matchs en cours reçoivent un rappel, et les boutons déjà envoyés marchent toujours (un capitaine qui avait déjà cliqué n'a pas à recliquer). Le départ du délai avant la demande de score est noté dans le JSON (`chrono_declaration`) : après un redémarrage, le bot attend seulement le temps qui reste (et demande le score tout de suite si le délai est déjà passé).

### Bouton « Partie privée créée »

- Seul le capitaine qui doit créer la partie a ce bouton (un autre joueur qui clique est refusé).
- **Au clic** : les autres joueurs reçoivent « ✅ … a créé la partie privée, tu peux la rejoindre » avec le nom et le mot de passe, le bouton devient gris, et le délai de 6 min avant la demande de score démarre.
- Seul le premier clic compte. Un clic sur un autre bouton (celui du rappel, ou après un redémarrage) répond juste « Déjà noté ».
- **Pas de clic** : rappel au capitaine après `RAPPEL_CLIC_PP` (3 min), puis après `ATTENTE_CLIC_PP_MAX` (10 min) le délai de 6 min démarre quand même, avec une alerte dans `LOG_CHANNEL`.
- Le clic est enregistré dans le JSON du match (`pp_creee_le`, `pp_creee_par`).

### Déclaration des scores

`DELAI_DECLARATION` secondes (360 = 6 min par défaut) après le clic « Partie privée créée », chaque joueur des deux équipes reçoit en MP le bouton **📝 Déclarer le score** : une petite fenêtre demande les buts de son équipe et ceux de l'adversaire. C'est le cas normal : pas d'alerte dans `LOG_CHANNEL`. Avant la fin du délai, le bouton n'existe pas encore.

Ensuite :
- un joueur de chaque équipe déclare ; une nouvelle déclaration remplace la précédente de son équipe ;
- **les deux équipes déclarent le même score** → validé tout seul, MP de fin de match comme d'habitude ;
- **scores différents** → alerte dans `LOG_CHANNEL` (avec les deux déclarations), et MP aux deux équipes « un admin va trancher » (elles peuvent encore corriger) ;
- `/set_result_tournament_rl` reste prioritaire à tout moment.

Le round attend que tous ses matchs aient un score ; les autres zones, elles, continuent normalement.

### Modifier un joueur pendant le tournoi

`/edit_player_tournament_rl` : choisis le tournoi, puis le joueur dans la liste (👑 = capitaine), puis remplis seulement ce qui change. Le changement compte tout de suite, sans redémarrer le bot.

| Option | Effet |
|---|---|
| `pseudo_jeu` | Son pseudo dans Rocket League (affiché aux admins dans les alertes). Refusé s'il est déjà celui d'un autre joueur. |
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

**Salon des résultats** (`SALON_RESULTATS`, par exemple `#resultat-match` ; sinon le salon des annonces) — public. Au `/start_tournament_rl`, le bot y poste un séparateur et le lancement du tournoi ; à la fin de chaque round, le récap :
```
━━━━━━━━━━━━━━━━━━━━━━
🚀 Lancement du tournoi test

🎯 Round 3
Zone 1 ⭐ : ✅ caca 1 - 2 tomatoTown

📊 Classement
🥇 tomatoTown — 6 points (2V-1D, diff +2)
🥈 caca — 3 points (1V-2D, diff -2)
```

**Salon de discussion** (un par tournoi, créé par `/start_tournament_init`) — privé :
- nom `💬-<titre-du-tournoi>`, dans la **même catégorie** que le salon où le tournoi a été créé avec le bot d'inscription (à la racine du serveur si ce salon n'est pas dans une catégorie) ;
- visible seulement par les **joueurs des équipes participantes**, les **admins** (rôles avec « Gérer le serveur » ou « Administrateur »), l'admin qui a lancé le tournoi et le bot. Ils peuvent y écrire et y envoyer des fichiers (captures de score) ;
- le bot y poste un message de bienvenue qui mentionne chaque joueur, puis « @here Le tournoi va bientôt commencer, soyez prêts ! Bonne chance à tous 🍀 » ; les mots de passe des parties restent en MP. Pour que le @here notifie, il faut au bot **Mentionner @everyone, @here et tous les rôles** (sinon la console le signale) ;
- un joueur qui a quitté le serveur n'y a pas accès : le bot le signale dans `LOG_CHANNEL` ;
- son ID est gardé dans `data/salons/<id>.json`, puis dans le JSON du tournoi (`salon_discussion_id`) au `/start_tournament_rl`. Sans `/start_tournament_init` avant, `/start_tournament_rl` refuse de lancer le tournoi. `/start_tournament_init` refuse de créer un deuxième salon tant que le premier existe ;
- à la fin ou à l'arrêt du tournoi, le salon reste : supprime-le à la main quand tu veux. Un tournoi relancé garde le même salon. `/reset_tournament_rl` le supprime (sauf avec `garder_salon: True`).

Il faut au bot **Gérer les salons**, **Gérer les rôles** (pour donner l'accès au salon aux équipes montées de la liste d'attente et aux remplaçants, et le retirer aux équipes qui perdent leur place) et **Joindre des fichiers** (en plus des permissions d'annonce) sur le serveur, et que la catégorie ne les lui retire pas. Sinon `/start_tournament_init` refuse de créer le salon et dit quoi cocher, et où (rôle du bot sur le serveur, ou catégorie).

**Catégorie en lecture seule** (les membres ne peuvent pas écrire) : elle retire aussi ces permissions au bot, et réinviter le bot n'y change rien. Clic droit sur la catégorie > **Modifier la catégorie** > **Permissions** > rôle du bot > mets en ✅ vert **Gérer les salons**, **Envoyer des messages**, **Intégrer des liens** et **Joindre des fichiers**. Les membres restent bloqués ; seul le bot reçoit ces droits.

**`LOG_CHANNEL`** — à réserver aux admins, car il contient les mots de passe des parties :
- « ✅ Bot démarré » au lancement du bot ;
- les **alertes** (déclarations différentes, capitaine qui n'a pas cliqué sur « Partie privée créée »), qui mentionnent l'admin qui a lancé le tournoi et donnent :
  - le nom et le mot de passe de la partie, son créateur et les équipes (pour la rejoindre à la main) ;
  - les déclarations des équipes ;
  - la commande `/set_result_tournament_rl` déjà remplie, avec les numéros d'équipes ;
- les **modifications de joueurs** faites avec `/edit_player_tournament_rl` (sans mentionner personne) ;
- les **problèmes du bot** (avertissements et erreurs de la console : permissions, salon introuvable…), regroupés pour éviter le spam.

Si `LOG_CHANNEL` est vide, les alertes partent en MP à l'admin qui a lancé le tournoi.

## Fichiers

| Fichier | Contenu |
|---|---|
| `../rl_bot_ppname_creator/data/tournois/<id>.json` | Inscriptions (lues, jamais modifiées). Seules les équipes `inscrite` dont tous les joueurs ont confirmé participent. |
| `data/tournois/<id>.json` | **État et résultats** : équipes (points, victoires, buts, historique), rounds (`rondes`), matchs, scores, déclarations. |
| `data/pp/<id>_ronde_<n>.json` | Parties privées de chaque round (tomato_11, tomato_12… au round 1). |
| `data/archives/` | Ancien fichier de résultats quand on relance un tournoi déjà terminé ou arrêté. |
| `data/salons/<id>.json` | `/start_tournament_init` : salon de discussion, équipes retenues (`equipes`) et validation des participations (`confirmation` : `delai_minutes`, `fin`, `terminee`, `validees`, `attente`, `perdues`, `promues`). |

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
  "points_zones": {"1": 5, "4": 10},
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
          "pp": { "nom": "tomato_C", "mot_de_passe": "tomato_C" },
          "equipe_a": 1, "equipe_b": 2,
          "statut": "termine",
          "score": { "equipe_a": 3, "equipe_b": 1 },
          "vainqueur": 1, "points_attribues": 1,
          "source_resultat": "declarations",
          "declarations": {
            "1": { "pour": 3, "contre": 1, "par": "1540386073958682779", "le": "2026-11-18T15:49:30" },
            "2": { "pour": 1, "contre": 3, "par": "296738272648888321", "le": "2026-11-18T15:50:02" }
          },
          "pp_creee_le": "2026-11-18T15:42:10", "pp_creee_par": "1540386073958682779",
          "chrono_declaration": "2026-11-18T15:42:10",
          "raison_a_valider": "score à déclarer par les équipes", "valide_par": null
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
| `statut` d'un match | `en_attente`, `en_cours` (partie à créer ou délai en cours), `termine`, `a_valider` (score à déclarer par les équipes), `annule` |
| `source_resultat` | `declarations` (les deux équipes d'accord), `admin` ; `bot` pour les tournois joués avec l'ancien observateur |
| `chrono_declaration` | départ du délai avant la demande de score : le clic du capitaine, ou la fin de `ATTENTE_CLIC_PP_MAX` sans clic |
| `declarations` | `{"<id équipe>": {"pour": 3, "contre": 1, "par": "<id Discord>", "le": "…"}}` |

## Réglages du déroulement

Dans le `.env` (valeurs en secondes) :

| Réglage | Par défaut | Rôle |
|---|---|---|
| `PAUSE_ENTRE_RONDES` | 60 | Pause entre deux rounds. |
| `RAPPEL_CLIC_PP` | 180 | Rappel au capitaine qui n'a pas cliqué sur « Partie privée créée ». |
| `ATTENTE_CLIC_PP_MAX` | 600 | Sans clic, le délai avant la demande de score démarre quand même (avec une alerte). |
| `DELAI_DECLARATION` | 360 | Attente après le clic avant le MP « Déclarer le score » (6 min). |

Pour tester un tournoi sans jouer : `DELAI_DECLARATION=5` et `ATTENTE_CLIC_PP_MAX=30`, puis déclare les scores toi-même avec les boutons (ou `/set_result_tournament_rl`), ou active le mode simulation ci-dessous.

### Mode simulation (`SIMULATION=1`)

Le tournoi se joue tout seul, sans joueurs (code : `simulation.py`) :
0. après `/start_tournament_init`, le capitaine de chaque équipe « clique » sur **Valider ma participation** après `SIMULATION_DELAI_CLIC` secondes (sauf avec `AUTO_VALIDATION=0` : personne ne valide tout seul, pour tester les places perdues et la liste d'attente) ;
1. le capitaine « clique » sur **Partie privée créée** après `SIMULATION_DELAI_CLIC` secondes ;
2. le bot attend `DELAI_DECLARATION` comme en vrai (mets-le à 5 pour aller vite), puis envoie les MP de déclaration ;
3. chaque équipe déclare un score tiré au hasard (jamais d'égalité) après `SIMULATION_DELAI_DECLARATION` secondes. Les deux équipes déclarent le même score : le match est validé tout seul.

| Réglage | Par défaut | Rôle |
|---|---|---|
| `SIMULATION` | 0 | 1 pour activer le mode simulation. |
| `SIMULATION_DELAI_CLIC` | 5 | Secondes avant le clic automatique « Partie privée créée ». |
| `SIMULATION_DELAI_DECLARATION` | 5 | Secondes entre le MP de déclaration et les déclarations automatiques. |
| `AUTO_VALIDATION` | 1 | En simulation, 1 : chaque équipe valide sa participation toute seule. 0 : aucune validation automatique (les vrais joueurs peuvent cliquer), les équipes qui ne valident pas perdent leur place comme en vrai. Sans effet si `SIMULATION=0`. |
| `SIMULATION_PROBA_DESACCORD` | 0 | Probabilité (0 à 1) que les deux équipes déclarent des scores différents : alerte dans `LOG_CHANNEL`, et un admin tranche avec `/set_result_tournament_rl`. |

⚠️ Les vrais MP partent quand même aux joueurs inscrits : utilise-le sur un tournoi de test, et remets `SIMULATION=0` avant un vrai tournoi. Au démarrage, la console et `LOG_CHANNEL` le rappellent.

Pour voir des scores simulés sans Discord :
```powershell
.venv\Scripts\python -m bot_tournament_manager.simulation --matchs 5
```
```bash
.venv/bin/python -m bot_tournament_manager.simulation --matchs 5
```

Le bot n'utilise plus `rl_api_pp_connector` : les anciens réglages `OBSERVATEUR`, `RL_*`, `SIMULATION_DUREE_MIN`, `SIMULATION_DUREE_MAX`, `SIMULATION_PROBA_SANS_GAGNANT` et `SIMULATION_PROBA_COULEURS_INVERSEES` du `.env` sont ignorés et peuvent être effacés.

## Installation

### 1. Créer le bot sur Discord
1. https://discord.com/developers/applications > **New Application** (nom : `tournament_manager`). Il faut une **autre application** que le bot d'inscription : deux bots avec le même token écraseraient leurs commandes.
2. Onglet **Bot** > **Reset Token** > copie le token.
3. Invite le bot sur ton serveur (remplace `APPLICATION_ID`) :
   `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot+applications.commands&permissions=268553232`
   Dans le salon des annonces, le salon des résultats et `LOG_CHANNEL`, il lui faut **Voir le salon**, **Envoyer des messages** et **Intégrer des liens**.
   Pour créer le salon de discussion de chaque tournoi, il lui faut aussi **Gérer les salons**, **Gérer les rôles**, **Joindre des fichiers** et **Voir les anciens messages** (déjà dans le lien). Si le bot a été invité avec un ancien lien (`permissions=84992` ou `117776`), réinvite-le avec celui-ci ou ajoute ces permissions à son rôle (Paramètres du serveur > Rôles > rôle du bot).
   Facultatif : **Gérer les rôles**, pour que `/edit_player_tournament_rl` ajoute lui-même un remplaçant au salon de discussion (sinon tu le fais à la main). Le lien ne la contient pas : ajoute-la au rôle du bot si tu veux.

Aucun « Privileged Gateway Intent » n'est nécessaire.

### 2. Configurer
Remplis le fichier `.env` (modèle : `.env.example`) :
- `DISCORD_TOKEN` : le token du bot ;
- `GUILD_ID` : l'ID de ton serveur ;
- `SALON_ANNONCES` (facultatif) : l'ID du salon des annonces ;
- `SALON_RESULTATS` (facultatif) : l'ID du salon où le bot poste le récap de chaque round (ex. `#resultat-match`) ;
- `LOG_CHANNEL` (conseillé) : l'ID du salon privé des alertes.

Pour copier un ID : Paramètres Discord > Avancés > **Mode développeur**, puis clic droit sur le salon > **Copier l'identifiant du salon**.

Les autres réglages ont des valeurs par défaut prêtes à l'emploi.

### 3. Lancer
Windows (PowerShell) :
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m bot_tournament_manager
```
Linux / macOS (Bash) :
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
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
