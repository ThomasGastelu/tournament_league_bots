"""Boutons et salons des tickets.

- « 🎫 Créer un ticket » (panneau Support) → liste des catégories (visible par le membre seul)
  → salon privé dans la catégorie des tickets, visible par l'auteur et le staff.
- « ✅ Problème résolu » (dans le salon, pour l'auteur) → fermeture directe.
- « 🔒 Fermer le ticket » (dans le salon, auteur ou staff) → confirmation → fermeture.
- Fermeture automatique : toutes les 10 minutes, les tickets où le staff a parlé en dernier
  depuis FERMETURE_AUTO_HEURES sont fermés (rien à retenir : tout est relu dans le salon).
Fermer = copie de la conversation dans LOG_CHANNEL puis suppression du salon.

Les boutons sont des « DynamicItem » : ils marchent encore après un redémarrage du bot.
L'auteur et la catégorie d'un ticket sont lus dans le sujet du salon (voir logique.lire_sujet).
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import datetime, timezone

import discord
from discord import ui

from . import embeds as E
from . import logique as L

log = logging.getLogger(__name__)

DUREE_CHOIX_SECONDES = 300
_verrous: dict[int, asyncio.Lock] = {}  # un par membre : deux clics rapides n'ouvrent pas deux tickets
_en_fermeture: set[int] = set()         # salons en cours de fermeture : jamais fermés deux fois


def verrou(membre_id: int) -> asyncio.Lock:
    return _verrous.setdefault(membre_id, asyncio.Lock())


async def repondre(interaction: discord.Interaction, texte: str, **kwargs) -> None:
    """Répond en privé (éphémère), que l'interaction ait déjà été différée ou non."""
    if interaction.response.is_done():
        await interaction.followup.send(texte, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(texte, ephemeral=True, **kwargs)


def reglages(interaction: discord.Interaction) -> L.Reglages:
    return interaction.client.reglages  # type: ignore[attr-defined]


async def noter(client: discord.Client, texte: str, **kwargs) -> None:
    """Écrit dans LOG_CHANNEL s'il est réglé. Une erreur ici n'empêche jamais le reste."""
    salon_id = client.reglages.log_channel  # type: ignore[attr-defined]
    if not salon_id:
        return
    salon = client.get_channel(salon_id)
    if salon is None:
        log.warning("LOG_CHANNEL %s introuvable : vérifie l'ID et que le bot voit ce salon", salon_id)
        return
    try:
        await salon.send(texte, allowed_mentions=discord.AllowedMentions.none(), **kwargs)
    except discord.HTTPException as erreur:
        log.warning("Impossible d'écrire dans LOG_CHANNEL : %s", erreur)


# --------------------------------------------------------------------------- #
# Panneau Support
# --------------------------------------------------------------------------- #

class BoutonCreerTicket(ui.DynamicItem[ui.Button], template=r"tk:creer"):
    def __init__(self) -> None:
        super().__init__(ui.Button(
            label="Créer un ticket", emoji="🎫", style=discord.ButtonStyle.success, custom_id="tk:creer",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(E.TEXTE_CHOIX, view=ChoixCategorie(), ephemeral=True)


def vue_panneau() -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(BoutonCreerTicket())
    return vue


class ChoixCategorie(ui.View):
    """Liste déroulante des catégories, visible seulement par le membre qui a cliqué."""

    def __init__(self) -> None:
        super().__init__(timeout=DUREE_CHOIX_SECONDES)
        self.liste = ui.Select(
            placeholder="Choisis une catégorie",
            options=[discord.SelectOption(label=c.nom, value=c.cle, emoji=c.emoji, description=c.description)
                     for c in L.CATEGORIES],
        )
        self.liste.callback = self.choisir
        self.add_item(self.liste)

    async def choisir(self, interaction: discord.Interaction) -> None:
        self.stop()
        categorie = L.CATEGORIES_PAR_CLE[self.liste.values[0]]
        await interaction.response.edit_message(content=f"⏳ Ouverture du ticket **{categorie.nom}**…", view=None)
        texte = await creer_ticket(interaction, categorie)
        try:
            await interaction.edit_original_response(content=texte)
        except discord.HTTPException:
            await repondre(interaction, texte)


# --------------------------------------------------------------------------- #
# Création
# --------------------------------------------------------------------------- #

def trouver_categorie(serveur: discord.Guild, regl: L.Reglages):
    """La catégorie Discord des tickets si elle existe : CATEGORIE_TICKETS, sinon « Support »."""
    if regl.categorie_id:
        salon = serveur.get_channel(regl.categorie_id)
        return salon if isinstance(salon, discord.CategoryChannel) else None
    for categorie in serveur.categories:
        if categorie.name.lower() == L.NOM_CATEGORIE_PAR_DEFAUT.lower():
            return categorie
    return None


async def categorie_des_tickets(serveur: discord.Guild, regl: L.Reglages):
    """La catégorie Discord des tickets : CATEGORIE_TICKETS, sinon « Support » (créée au besoin)."""
    trouvee = trouver_categorie(serveur, regl)
    if trouvee is not None or regl.categorie_id:
        return trouvee
    droits = {
        serveur.default_role: discord.PermissionOverwrite(view_channel=False),
        serveur.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
    }
    for role in roles_staff(serveur, regl):
        droits[role] = discord.PermissionOverwrite(view_channel=True)
    log.info("Création de la catégorie « %s » sur « %s »", L.NOM_CATEGORIE_PAR_DEFAUT, serveur)
    return await serveur.create_category(L.NOM_CATEGORIE_PAR_DEFAUT, overwrites=droits,
                                         reason="Catégorie des tickets")


def roles_staff(serveur: discord.Guild, regl: L.Reglages) -> list[discord.Role]:
    roles = []
    for role_id in regl.roles_staff:
        role = serveur.get_role(role_id)
        if role is None:
            log.warning("Rôle staff %s introuvable sur « %s » (ROLES_STAFF du .env)", role_id, serveur)
        else:
            roles.append(role)
    return roles


async def creer_ticket(interaction: discord.Interaction, categorie: L.Categorie) -> str:
    """Ouvre le salon du ticket et retourne le texte à montrer au membre."""
    serveur, membre, regl = interaction.guild, interaction.user, reglages(interaction)
    async with verrou(membre.id):
        try:
            dossier = await categorie_des_tickets(serveur, regl)
        except discord.Forbidden:
            return E.TEXTE_PERMISSION
        if dossier is None:
            log.error("CATEGORIE_TICKETS %s n'est pas une catégorie de « %s »", regl.categorie_id, serveur)
            return "❌ La catégorie des tickets est introuvable. Préviens le staff (CATEGORIE_TICKETS du .env)."

        deja = L.ticket_ouvert(dossier.text_channels, membre.id)
        if deja is not None:
            return E.texte_deja_ouvert(deja.mention)

        acces = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                            attach_files=True, embed_links=True)
        staff = roles_staff(serveur, regl)
        droits = {serveur.default_role: discord.PermissionOverwrite(view_channel=False), serveur.me: acces,
                  membre: acces}
        for role in staff:
            droits[role] = acces
        try:
            salon = await serveur.create_text_channel(
                L.nom_salon(categorie, membre.display_name),
                category=dossier,
                overwrites=droits,
                topic=L.sujet_salon(categorie, membre.id, membre.display_name),
                reason=f"Ticket {categorie.nom} de {membre}",
            )
        except discord.Forbidden:
            return E.TEXTE_PERMISSION
        except discord.HTTPException as erreur:  # ex. catégorie pleine (50 salons max)
            log.warning("Création du ticket de %s impossible : %s", membre, erreur)
            return "❌ Impossible de créer le salon pour l'instant. Réessaie plus tard ou préviens le staff."

    log.info("Ticket %s ouvert par %s : #%s", categorie.cle, membre, salon.name)
    mentions = " ".join([membre.mention, *(role.mention for role in staff)])
    try:
        await salon.send(mentions, embed=E.embed_ticket(categorie, membre.mention, regl.fermeture_auto_heures), view=vue_ticket(),
                         allowed_mentions=discord.AllowedMentions(users=True, roles=True))
    except discord.HTTPException as erreur:
        log.warning("Message d'accueil impossible dans #%s : %s", salon.name, erreur)
    await noter(interaction.client, E.texte_log_ouverture(categorie, membre.mention, salon.mention))
    return E.texte_ticket_cree(salon.mention)


# --------------------------------------------------------------------------- #
# Fermeture
# --------------------------------------------------------------------------- #

class BoutonProblemeResolu(ui.DynamicItem[ui.Button], template=r"tk:resolu"):
    def __init__(self) -> None:
        super().__init__(ui.Button(
            label="Problème résolu", emoji="✅", style=discord.ButtonStyle.success, custom_id="tk:resolu",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        infos = L.lire_sujet(getattr(interaction.channel, "topic", None))
        if infos is None:
            return await repondre(interaction, E.TEXTE_PAS_UN_TICKET)
        if not L.est_auteur(interaction.user.id, infos[0]):
            return await repondre(interaction, E.TEXTE_RESOLU_RESERVE)
        await interaction.response.defer()  # le clic vaut confirmation : pas de deuxième question
        await fermer_salon(interaction.client, interaction.channel,
                           E.texte_resolu_par(interaction.user.display_name),
                           "résolu, confirmé par son auteur", par=interaction.user)


class BoutonFermerTicket(ui.DynamicItem[ui.Button], template=r"tk:fermer"):
    def __init__(self) -> None:
        super().__init__(ui.Button(
            label="Fermer le ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="tk:fermer",
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        infos = L.lire_sujet(getattr(interaction.channel, "topic", None))
        if infos is None:
            return await repondre(interaction, E.TEXTE_PAS_UN_TICKET)
        if not peut_fermer(interaction, infos[0]):
            return await repondre(interaction, E.TEXTE_PAS_LE_DROIT)
        await repondre(interaction, E.texte_confirmation_fermeture(), view=ConfirmationFermeture())


def vue_ticket() -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(BoutonProblemeResolu())
    vue.add_item(BoutonFermerTicket())
    return vue


def peut_fermer(interaction: discord.Interaction, auteur_id: int) -> bool:
    membre = interaction.user
    roles = [role.id for role in getattr(membre, "roles", [])]
    permissions = getattr(membre, "guild_permissions", None)
    return L.peut_fermer(membre.id, roles, bool(permissions and permissions.manage_channels),
                         auteur_id, reglages(interaction).roles_staff)


class ConfirmationFermeture(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=60)

    @ui.button(label="Oui, fermer", style=discord.ButtonStyle.danger, emoji="🔒")
    async def oui(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="⏳ Fermeture du ticket…", view=None)
        await fermer_salon(interaction.client, interaction.channel,
                           E.texte_ferme_par(interaction.user.display_name),
                           f"fermé par {interaction.user.mention}", par=interaction.user)

    @ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def non(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content=E.TEXTE_FERMETURE_ANNULEE, view=None)


async def copie_conversation(salon) -> str:
    messages = []
    async for message in salon.history(limit=L.MESSAGES_MAX_TRANSCRIPTION, oldest_first=True):
        contenu = message.content or "".join(f"[embed] {e.title or ''} {e.description or ''}".strip()
                                             for e in message.embeds)
        messages.append(L.MessageCopie(
            date=message.created_at.strftime("%d/%m/%Y %H:%M"),
            auteur=message.author.display_name,
            contenu=contenu,
            pieces_jointes=tuple(p.url for p in message.attachments),
        ))
    return L.texte_transcription(f"Ticket #{salon.name} — {salon.topic or ''}", messages)


async def fermer_salon(client: discord.Client, salon, annonce: str, comment: str, par=None) -> bool:
    """Annonce la fermeture dans le salon, copie la conversation dans LOG_CHANNEL, puis supprime le salon.
    `comment` complète la ligne de LOG_CHANNEL. False si le salon n'est pas un ticket ou déjà en fermeture."""
    infos = L.lire_sujet(getattr(salon, "topic", None))
    if infos is None or salon.id in _en_fermeture:
        return False
    _en_fermeture.add(salon.id)
    try:
        auteur_id, categorie = infos
        try:
            await salon.send(annonce)
        except discord.HTTPException:
            pass

        if client.reglages.log_channel:  # type: ignore[attr-defined]
            try:
                texte = await copie_conversation(salon)
                fichier = discord.File(io.BytesIO(texte.encode("utf-8")), filename=f"{salon.name}.txt")
                await noter(client, E.texte_log_fermeture(categorie.nom, salon.name, f"<@{auteur_id}>", comment),
                            file=fichier)
            except discord.HTTPException as erreur:  # la copie est un bonus : le ticket se ferme quand même
                log.warning("Copie du ticket #%s impossible : %s", salon.name, erreur)

        await asyncio.sleep(L.DELAI_SUPPRESSION)
        try:
            await salon.delete(reason=f"Ticket {comment}"[:500])
            log.info("Ticket #%s %s", salon.name, comment if par is None else f"fermé par {par}")
        except discord.Forbidden:
            log.error("Le bot n'a pas le droit de supprimer #%s : coche « Gérer les salons » pour son rôle",
                      salon.name)
            try:
                await salon.send("❌ Le bot n'a pas le droit de supprimer ce salon : coche **Gérer les salons** "
                                 "pour son rôle (Paramètres du serveur > Rôles).")
            except discord.HTTPException:
                pass
            return False
        except discord.NotFound:
            pass  # déjà supprimé à la main
        return True
    finally:
        _en_fermeture.discard(salon.id)


# --------------------------------------------------------------------------- #
# Fermeture automatique
# --------------------------------------------------------------------------- #

async def ticket_inactif(salon, auteur_id: int, heures: float, maintenant: datetime) -> bool:
    messages = [
        L.MessageVu(message.author.id, message.author.bot, message.created_at)
        async for message in salon.history(limit=L.MESSAGES_LUS_VERIFICATION)
    ]
    return L.doit_fermer_auto(messages, auteur_id, maintenant, heures)


async def fermer_tickets_inactifs(client: discord.Client, maintenant: datetime | None = None) -> int:
    """Ferme les tickets où le staff a répondu et où l'auteur n'a plus rien écrit depuis
    FERMETURE_AUTO_HEURES. Retourne le nombre de tickets fermés. Un ticket en erreur n'arrête pas les autres."""
    regl: L.Reglages = client.reglages  # type: ignore[attr-defined]
    if regl.fermeture_auto_heures <= 0:
        return 0
    maintenant = maintenant or datetime.now(timezone.utc)
    fermes = 0
    for serveur in client.guilds:
        dossier = trouver_categorie(serveur, regl)
        if dossier is None:
            continue
        for salon in list(dossier.text_channels):
            infos = L.lire_sujet(getattr(salon, "topic", None))
            if infos is None:
                continue
            try:
                if await ticket_inactif(salon, infos[0], regl.fermeture_auto_heures, maintenant):
                    if await fermer_salon(client, salon, E.texte_ferme_auto(regl.fermeture_auto_heures),
                                          f"fermé automatiquement (pas de réponse depuis "
                                          f"{L.texte_heures(regl.fermeture_auto_heures)})"):
                        fermes += 1
            except discord.HTTPException as erreur:
                log.warning("Vérification du ticket #%s impossible : %s", salon.name, erreur)
    return fermes


async def boucle_fermeture_auto(client: discord.Client) -> None:
    """Tourne tant que le bot est lancé : vérifie les tickets toutes les VERIFICATION_AUTO_MINUTES."""
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            fermes = await fermer_tickets_inactifs(client)
            if fermes:
                log.info("%d ticket%s fermé%s automatiquement", fermes, "s" * (fermes > 1), "s" * (fermes > 1))
        except Exception:  # la boucle ne doit jamais s'arrêter sur une erreur
            log.exception("Erreur pendant la fermeture automatique des tickets")
        await asyncio.sleep(L.VERIFICATION_AUTO_MINUTES * 60)
