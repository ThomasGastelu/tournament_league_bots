# inscription_manager — bot Discord de tournois Rocket League

## Commandes

| Commande | Qui | Ce qu'elle fait |
|---|---|---|
| `/tournoi_rl titre cashprize joueurs_par_equipe equipes_max date [delay]` | admins | Poste l'annonce avec le bouton **S'inscrire** dans le salon. `delay` = minutes avant l'ouverture des inscriptions (0 par défaut, 10080 max), pour avoir le temps de réserver des places. |
| `/tournoi_rl_modify id [titre] [cashprize] [equipes_max]` | admins | Modifie le titre, le cashprize et/ou le nombre maximum d'équipes (au moins un des trois). L'annonce est mise à jour. |
| `/tournoi_rl_status id` | tout le monde | Équipes inscrites, joueurs qui n'ont pas validé, liste d'attente (réponse visible par toi seul). |
| `/tournoi_rl_status_all id` | admins | Même contenu que `/tournoi_rl_status`, mais posté dans le salon et visible par tout le monde. |
| `/tournoi_rl_reserve id capitaine nom duree` | admins | Réserve une place pour l'équipe de `capitaine` (invités, partenaires) pendant `duree` minutes (30 jours max). Le capitaine est prévenu en MP. |
| `/tournoi_rl_unreserve id reservation` | admins | Annule une place réservée (`Rn` dans `/tournoi_rl_status`) : elle est rendue aux autres équipes. |
| `/tournoi_rl_modify_player id joueur [pseudo_jeu] [pseudo]` | admins | Change le pseudo Rocket League et/ou le pseudo affiché d'un joueur inscrit ou en liste d'attente (au moins un des deux). Le pseudo Rocket League ne se change que pour un joueur qui a déjà confirmé. Le joueur est prévenu en MP. Sans effet sur un tournoi déjà lancé par `tournament_manager`. |
| `/tournoi_rl_modify_member id ancien nouveau pseudo_jeu` | admins | Remplace un joueur d'une équipe (inscrite ou en liste d'attente) par un autre membre du serveur. Le nouveau joueur est directement confirmé avec le pseudo Rocket League donné ; si l'ancien était capitaine, le nouveau le devient. Les deux joueurs sont prévenus en MP. Sans effet sur un tournoi déjà lancé par `tournament_manager`. |
| `/tournoi_rl_remove_team id team_id` | admins | Retire une équipe et fait monter la première équipe de la liste d'attente. |
| `/tournoi_rl_remove id` | admins | Annule et efface le tournoi (après confirmation) : annonce supprimée, joueurs prévenus en MP, fichier JSON effacé. |

Les `id` et `team_id` sont proposés en autocomplétion. Le `team_id` est le `#n` affiché dans `/tournoi_rl_status`.
« Admins » = membres avec la permission **Gérer le serveur** (modifiable dans Paramètres du serveur > Intégrations).

## Fonctionnement d'une inscription

1. Un joueur clique sur **S'inscrire** : une fiche s'ouvre (nom d'équipe, son pseudo Rocket League, choix des coéquipiers parmi les membres du serveur). Il devient capitaine.
2. L'équipe obtient sa place tout de suite (ou une place en liste d'attente si le tournoi est plein). La liste d'attente fait `equipes_max × 4`.
3. Chaque coéquipier reçoit un MP avec **Confirmer ma participation** / **Refuser**. Confirmer ouvre une fiche qui demande son pseudo Rocket League (exactement le même que dans le jeu) (si ses MP sont fermés, le message est posté dans le salon en le mentionnant). Le capitaine reçoit un MP « tu t'es inscrit… en attente de : … » avec un bouton **Annuler l'inscription**.
4. Les coéquipiers ont **30 minutes** (réglable avec `DELAI_CONFIRMATION_MINUTES` dans `.env`) pour confirmer (heure limite affichée dans les MP et dans `/tournoi_rl_status`). Passé ce délai, le bot désinscrit l'équipe automatiquement (vérification chaque minute, même après un redémarrage) et prévient tous ses joueurs en MP. Les équipes inscrites avant l'ajout de ce délai ne sont pas concernées.
5. Si un coéquipier refuse, ne confirme pas à temps, si le capitaine annule ou si un admin retire l'équipe, la place est donnée à la première équipe de la liste d'attente, qui est prévenue en MP.

Les données sont dans `data/tournois/<id>.json` (un fichier par tournoi). Champs ajoutés pour l'ouverture différée et les réservations (absents des anciens fichiers, qui restent valables) :
- `ouverture_inscriptions` : heure d'ouverture, remise à `null` une fois les inscriptions ouvertes ;
- `reservations` : liste de `{id, nom, capitaine_id, capitaine, statut (active / utilisee / expiree / annulee), cree_par, cree_le, expire_le, equipe_id, terminee_le}` ;
- `reservation_id` sur une équipe inscrite grâce à une réservation.

## Ouverture différée et places réservées

- Avec `delay` (ex : `/tournoi_rl … delay: 60`), l'annonce est postée tout de suite mais affiche « 🕒 Les inscriptions ouvrent dans 1 heure ». Avant cette heure, le bouton **S'inscrire** répond l'heure d'ouverture. À l'heure dite, le bot met l'annonce à jour tout seul (vérification chaque minute).
- `/tournoi_rl_reserve` bloque une place libre pour un capitaine précis. Les places réservées sont retirées des places ouvertes à tous : avec `equipes_max = 16` et 2 réservations, seules 14 places partent avant la liste d'attente. L'annonce n'affiche pas les places réservées (compteur `3/16`) : elles sont listées dans `/tournoi_rl_status`.
- Le capitaine réservé s'inscrit avec le bouton **S'inscrire** habituel, **même avant l'ouverture et même si le tournoi est complet** : son équipe prend la place réservée (marquée 🔒 dans `/tournoi_rl_status`). Ses coéquipiers doivent confirmer comme d'habitude, sinon l'équipe est désinscrite et la place va à la liste d'attente.
- Si le capitaine ne s'est pas inscrit avant l'échéance, la place est rendue automatiquement : la première équipe de la liste d'attente monte et le capitaine est prévenu en MP. Même chose avec `/tournoi_rl_unreserve`.
- Une réservation ne retire jamais une équipe déjà inscrite : s'il n'y a plus de place libre, augmente d'abord `equipes_max`.
- Un capitaine ne peut avoir qu'une réservation par tournoi, et pas s'il est déjà dans une équipe.

## Modifier un tournoi (`/tournoi_rl_modify`)

- Seuls les champs remplis changent. La liste d'attente suit toujours : `equipes_max × 4`.
- **Augmenter `equipes_max`** : les premières équipes de la liste d'attente montent sur les nouvelles places et sont prévenues en MP. Si le tournoi était complet, le bouton **S'inscrire** redevient cliquable.
- **Baisser `equipes_max`** : impossible en dessous du nombre d'équipes déjà inscrites plus les places réservées (aucune équipe n'est retirée automatiquement). Retire d'abord des équipes avec `/tournoi_rl_remove_team` ou des réservations avec `/tournoi_rl_unreserve`.
- Changer le titre ou le cashprize n'envoie pas de MP : seule l'annonce est mise à jour (les anciens MP gardent l'ancien texte).
- ⚠️ Une fois le tournoi lancé avec `rl_tournament_manager`, les modifications ne changent plus le tournoi en cours (il a copié le titre et les équipes au lancement). Les équipes promues à ce moment-là ne jouent pas.

## Installation

### 1. Créer le bot sur Discord
1. Va sur https://discord.com/developers/applications > **New Application** (nom : `inscription_manager`).
2. Onglet **Bot** > **Reset Token** > copie le token (ne le partage jamais).
   Il ressemble à `MTIz...abc.Gh1jK2.xyz...` (3 morceaux séparés par des points).
   ⚠️ Ce n'est **pas** la *Public Key* ni l'*Application ID* (onglet General Information), ni le *Client Secret* (onglet OAuth2).
3. Onglet **OAuth2** > note l'**Application ID** (Client ID).
4. Invite le bot sur ton serveur avec ce lien (remplace `APPLICATION_ID`) :
   `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot+applications.commands&permissions=84992`
   (permissions : Voir les salons, Envoyer des messages, Intégrer des liens, Voir l'historique).

Aucun « Privileged Gateway Intent » n'est nécessaire.

### 2. Configurer
Copie `.env.example` en `.env` et remplis :
- `DISCORD_TOKEN` : le token du bot.
- `GUILD_ID` : l'ID de ton serveur (Paramètres Discord > Avancés > Mode développeur, puis clic droit sur le serveur > **Copier l'identifiant du serveur**). Avec cet ID, les commandes apparaissent immédiatement.
- `DELAI_CONFIRMATION_MINUTES` : minutes laissées aux coéquipiers pour confirmer (30 par défaut, de 1 à 10080). Redémarre le bot après un changement. Le nouveau délai ne s'applique qu'aux inscriptions faites après le redémarrage : les équipes déjà inscrites gardent leur heure limite.

### 3. Lancer
Windows (PowerShell) :
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m bot_inscription_manager
```
Linux / macOS (Bash) :
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m bot_inscription_manager
```
Le bot doit rester lancé pour que les boutons fonctionnent. S'il redémarre, les anciens boutons remarchent.

### Tests
Windows (PowerShell) :
```powershell
.venv\Scripts\python -m pytest
```
Linux / macOS (Bash) :
```bash
.venv/bin/python -m pytest
```
