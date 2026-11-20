# bot_mp — envoyer un MP à tous les membres du serveur

## Commande

| Commande | Qui | Ce qu'elle fait |
|---|---|---|
| `/mp_all` | admins | Ouvre une fiche pour écrire le message, montre un aperçu, puis l'envoie en MP à tous les membres du serveur. |

« Admins » = membres avec la permission **Gérer le serveur** (modifiable dans Paramètres du serveur > Intégrations).

## Fonctionnement

1. Tape `/mp_all` : une fiche s'ouvre. Écris ton message (retours à la ligne et mise en forme Discord acceptés, 4000 caractères max).
2. Un **aperçu** (visible par toi seul) montre le MP tel que les membres le recevront, le nombre de destinataires et la durée estimée.
3. **Envoyer** lance l'envoi, **Annuler** n'envoie rien. Sans clic, l'aperçu expire au bout de 5 minutes.
4. Pendant l'envoi, la progression se met à jour. À la fin, un rapport indique combien de membres ont reçu le message, qui a ses MP fermés et qui n'a pas pu être contacté. Si l'envoi dure plus de 15 minutes, Discord ne permet plus de modifier ce message : le rapport t'est alors envoyé en MP.

Les bots du serveur sont ignorés. Toi aussi, tu reçois le message.

## À savoir

- **Rythme** : un MP par seconde environ (≈ 2 min 30 pour 100 membres). Envoyer plus vite peut faire bloquer le bot par l'anti-spam de Discord. Évite d'utiliser `/mp_all` trop souvent pour la même raison.
- **MP fermés** : les membres qui ont désactivé les MP des membres du serveur (Paramètres de confidentialité) ne reçoivent rien. Ils sont listés dans le rapport.
- **Un seul envoi à la fois** : `/mp_all` est refusé tant qu'un envoi est en cours.
- **Le bot doit rester lancé** jusqu'au rapport final. S'il s'arrête au milieu, l'envoi s'arrête aussi (ce qui a été envoyé reste envoyé).
- Les membres ne peuvent pas répondre au bot : leurs réponses en MP ne sont lues par personne.

## Installation

### 1. Créer le bot sur Discord
1. Va sur https://discord.com/developers/applications > **New Application** (nom : `bot_mp`).
2. Onglet **Bot** > **Reset Token** > copie le token (ne le partage jamais).
   Il ressemble à `MTIz...abc.Gh1jK2.xyz...` (3 morceaux séparés par des points).
   ⚠️ Ce n'est **pas** la *Public Key* ni l'*Application ID* (onglet General Information), ni le *Client Secret* (onglet OAuth2).
3. Toujours dans l'onglet **Bot**, section **Privileged Gateway Intents** : active **Server Members Intent**, puis **Save Changes**.
   Sans ça, le bot ne peut pas voir la liste des membres et refuse de démarrer.
4. Onglet **OAuth2** > note l'**Application ID** (Client ID).
5. Invite le bot sur ton serveur avec ce lien (remplace `APPLICATION_ID`) :
   `https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot+applications.commands&permissions=0`
   (aucune permission de salon n'est nécessaire : le bot n'écrit qu'en MP).

### 2. Configurer
Copie `.env.example` en `.env` et remplis :
- `DISCORD_TOKEN` : le token du bot.
- `GUILD_ID` : l'ID de ton serveur (Paramètres Discord > Avancés > Mode développeur, puis clic droit sur le serveur > **Copier l'identifiant du serveur**). Avec cet ID, la commande apparaît immédiatement.

### 3. Lancer (Windows, PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m bot_mp
```

### Tests
```powershell
.venv\Scripts\python -m pytest
```
