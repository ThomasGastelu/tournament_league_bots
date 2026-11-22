# bot_ticket — tickets de support

Un panneau **Support** avec un bouton **🎫 Créer un ticket**. Le membre choisit une catégorie et le bot lui ouvre un salon privé, visible seulement par lui et le staff.

## Commande

| Commande | Qui | Ce qu'elle fait |
|---|---|---|
| `/ticket_panel [salon]` | admins | Publie le panneau Support (embed + bouton « Créer un ticket ») dans le salon choisi, ou dans le salon actuel. |

« Admins » = membres avec la permission **Gérer le serveur** (modifiable dans Paramètres du serveur > Intégrations).

## Fonctionnement

1. Un admin tape `/ticket_panel` dans le salon d'accueil du support. Le panneau reste en place : inutile de le republier après un redémarrage du bot.
2. Un membre clique sur **🎫 Créer un ticket** : une liste (visible par lui seul) propose les catégories.
3. Il choisit une catégorie : le bot crée un salon `catégorie-pseudo` (ex. `aide-thomas`) dans la catégorie des tickets, mentionne le membre et les rôles du staff, et affiche ce qu'il faut écrire.
4. Sous le message d'accueil (tout en haut du salon), deux boutons permettent de fermer le ticket :
   - **✅ Problème résolu** : réservé au membre qui a ouvert le ticket. Un clic suffit, sans confirmation.
   - **🔒 Fermer le ticket** : pour le membre ou le staff, avec la confirmation **Oui, fermer**.
5. **Fermeture automatique** : si le staff a écrit le dernier message et que le membre ne répond plus pendant 72 h (`FERMETURE_AUTO_HEURES`), le bot ferme le ticket tout seul. Le membre en est prévenu dans le message d'accueil.

À chaque fermeture, si `LOG_CHANNEL` est réglé, la conversation y est copiée en fichier `.txt` avec la raison (fermé par…, résolu, fermé automatiquement), puis le salon est supprimé 5 secondes plus tard.

| Catégorie | Pour quoi |
|---|---|
| 🛡️ Recrutement modérateur | Postuler pour rejoindre l'équipe de modération du serveur. |
| 👤 Demande d'aide | Question générale, aide sur le serveur ou problème avec un membre. |
| ⚙️ Problème technique | Bug du bot, problème de rôles, accès aux salons ou dysfonctionnement Discord. |
| 🤝 Partenariat | Demande de partenariat avec un autre serveur, organisateur ou créateur de contenu. |
| 📢 Proposition / Suggestion | Proposer un tournoi, une amélioration du serveur ou une nouvelle fonctionnalité. |
| 🚨 Signalement | Signaler un joueur, un membre du staff ou un comportement inapproprié. |
| ❓ Autre | Si la demande ne correspond à aucune des catégories précédentes. |

Les catégories, leurs emojis et les consignes affichées dans le salon sont dans `bot_ticket/logique.py` (`CATEGORIES`).

## À savoir

- **Un ticket ouvert par membre** : s'il en a déjà un, le bot lui donne le lien au lieu d'en créer un autre.
- **Qui voit un ticket** : son auteur, les rôles de `ROLES_STAFF` et les admins Discord. Les autres membres ne le voient pas.
- **Qui peut le fermer** : l'auteur, le staff (`ROLES_STAFF`) et les membres qui peuvent gérer les salons. **Problème résolu** est réservé à l'auteur.
- **Fermeture automatique** : vérifiée toutes les 10 minutes, en relisant les derniers messages de chaque ticket (les messages du bot ne comptent pas). Rien n'est stocké : elle continue après un redémarrage. Elle ne se déclenche jamais si personne du staff n'a encore répondu, ni si le membre a écrit en dernier.
- **Aucun fichier** : le bot retrouve l'auteur et la catégorie d'un ticket dans le **sujet du salon** (`… · ticket:<id>:<catégorie>`). Ne modifie pas la fin du sujet, sinon le bouton Fermer ne reconnaît plus le ticket (supprime alors le salon à la main).
- Une catégorie Discord contient au plus 50 salons : ferme les vieux tickets.
- `LOG_CHANNEL` reçoit les copies des conversations (signalements compris) : garde-le réservé au staff.

## Installation

### 1. Créer le bot sur Discord
1. Va sur https://discord.com/developers/applications > **New Application** (nom : `ticket`). Une application à part : ne réutilise pas le token d'un autre bot.
2. Onglet **Bot** > **Reset Token** > copie le token (ne le partage jamais).
   Il ressemble à `MTIz...abc.Gh1jK2.xyz...` (3 morceaux séparés par des points).
   ⚠️ Ce n'est **pas** la *Public Key* ni l'*Application ID* (onglet General Information), ni le *Client Secret* (onglet OAuth2).
   Aucun « Privileged Gateway Intent » n'est nécessaire.
3. Onglet **OAuth2** > note l'**Application ID** (Client ID).
4. Invite le bot sur ton serveur avec ce lien (remplace `APPLICATION_ID`) :
   `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot+applications.commands&permissions=117776`
   (Gérer les salons, Voir les salons, Envoyer des messages, Intégrer des liens, Joindre des fichiers, Voir l'historique).

### 2. Configurer
Copie `.env.example` en `.env` et remplis :
- `DISCORD_TOKEN` : le token du bot.
- `GUILD_ID` : l'ID de ton serveur (Paramètres Discord > Avancés > Mode développeur, puis clic droit sur le serveur > **Copier l'identifiant du serveur**). Avec cet ID, la commande apparaît immédiatement.
- `ROLES_STAFF` : les ID des rôles du staff, séparés par des virgules (Paramètres du serveur > Rôles > clic droit sur le rôle > **Copier l'identifiant**).
- `CATEGORIE_TICKETS` (facultatif) : l'ID de la catégorie où créer les tickets. Vide : le bot utilise la catégorie **Support**, et la crée (cachée à `@everyone`) si elle n'existe pas. Si tu donnes ta propre catégorie, vérifie que le bot la voit.
- `FERMETURE_AUTO_HEURES` (facultatif) : délai sans réponse du membre après celle du staff avant la fermeture automatique. Vide : 72. `0` : jamais.
- `LOG_CHANNEL` (facultatif) : l'ID d'un salon réservé au staff, pour l'historique des ouvertures / fermetures et les copies des conversations.

### 3. Lancer
Windows (PowerShell) :
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m bot_ticket
```
Linux / macOS (Bash) :
```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m bot_ticket
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
