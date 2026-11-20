"""Commande /mp_all : fiche de saisie du message → aperçu → envoi à tous les membres."""

from __future__ import annotations

import logging

import discord
from discord import app_commands, ui

from . import logique as L
from .envoi import envoyer_a_tous

log = logging.getLogger(__name__)

TEXTE_DEJA_EN_COURS = "⏳ Un envoi est déjà en cours : attends le rapport de fin avant d'en lancer un autre."
DUREE_APERCU_SECONDES = 300


async def repondre(interaction: discord.Interaction, texte: str, **kwargs) -> None:
    """Répond en privé (éphémère), que l'interaction ait déjà été différée ou non."""
    if interaction.response.is_done():
        await interaction.followup.send(texte, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(texte, ephemeral=True, **kwargs)


async def modifier(interaction: discord.Interaction, texte: str) -> bool:
    """Met à jour le message de l'admin. False si Discord refuse (plus de 15 minutes après le clic)."""
    try:
        await interaction.edit_original_response(content=texte)
        return True
    except discord.HTTPException:
        return False


async def membres_du_serveur(serveur: discord.Guild) -> list:
    if not serveur.chunked:  # liste des membres pas encore chargée (normalement faite au démarrage)
        await serveur.chunk()
    return L.destinataires(serveur.members)


class FicheMessage(ui.Modal, title="Message à tous les membres"):
    texte = ui.TextInput(
        label="Message",
        style=discord.TextStyle.paragraph,
        placeholder="Le message que chaque membre recevra en MP",
        max_length=L.LONGUEUR_MAX_MESSAGE,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        serveur = interaction.guild
        nombre = len(await membres_du_serveur(serveur))
        if nombre == 0:
            return await repondre(interaction, L.texte_apercu(0))
        embed = L.embed_mp(self.texte.value, serveur.name, serveur.icon.url if serveur.icon else None)
        vue = Apercu(embed)
        vue.message = await interaction.followup.send(
            L.texte_apercu(nombre), embed=embed, view=vue, ephemeral=True, wait=True)

    async def on_error(self, interaction: discord.Interaction, erreur: Exception) -> None:
        log.exception("Erreur dans la fiche /mp_all", exc_info=erreur)
        try:
            await repondre(interaction, "❌ Une erreur inattendue est survenue : aucun MP envoyé.")
        except discord.HTTPException:
            pass


class Apercu(ui.View):
    """Aperçu du MP avec les boutons Envoyer / Annuler (visible seulement par l'admin)."""

    def __init__(self, embed: discord.Embed) -> None:
        super().__init__(timeout=DUREE_APERCU_SECONDES)
        self.embed = embed
        self.message: discord.WebhookMessage | None = None

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(content="⌛ Aperçu expiré : aucun MP envoyé. Relance `/mp_all`.",
                                        embed=None, view=None)
            except discord.HTTPException:
                pass

    @ui.button(label="Envoyer", style=discord.ButtonStyle.danger, emoji="📨")
    async def envoyer(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        self.stop()
        client = interaction.client
        if client.envoi_en_cours:  # type: ignore[attr-defined]
            return await interaction.response.edit_message(content=TEXTE_DEJA_EN_COURS, embed=None, view=None)

        client.envoi_en_cours = True  # type: ignore[attr-defined]
        try:
            await interaction.response.edit_message(content="⏳ Préparation de l'envoi…", view=None)
            membres = await membres_du_serveur(interaction.guild)
            log.info("%s lance /mp_all sur « %s » : %d membres", interaction.user, interaction.guild, len(membres))
            await modifier(interaction, L.texte_progression(L.Rapport(total=len(membres))))
            rapport = await envoyer_a_tous(
                membres, self.embed, progression=lambda r: modifier(interaction, L.texte_progression(r)))
        finally:
            client.envoi_en_cours = False  # type: ignore[attr-defined]

        texte = L.texte_rapport(rapport)
        log.info("/mp_all terminé : %d reçus, %d MP fermés, %d erreurs",
                 rapport.recus, len(rapport.mp_fermes), len(rapport.erreurs))
        if not await modifier(interaction, texte):
            # Au-delà de 15 minutes, Discord ne laisse plus modifier ce message : le rapport part en MP.
            try:
                await interaction.user.send(texte)
            except discord.HTTPException:
                log.warning("Rapport de /mp_all impossible à envoyer à %s", interaction.user)

    @ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def annuler(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="❌ Envoi annulé : aucun MP envoyé.", embed=None, view=None)


@app_commands.command(name="mp_all", description="Envoie un message privé à tous les membres du serveur")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def mp_all(interaction: discord.Interaction) -> None:
    if interaction.client.envoi_en_cours:  # type: ignore[attr-defined]
        return await repondre(interaction, TEXTE_DEJA_EN_COURS)
    await interaction.response.send_modal(FicheMessage())


async def gerer_erreur(interaction: discord.Interaction, erreur: app_commands.AppCommandError) -> None:
    log.exception("Erreur dans une commande", exc_info=erreur)
    try:
        await repondre(interaction, "❌ Une erreur inattendue est survenue.")
    except discord.HTTPException:
        pass
