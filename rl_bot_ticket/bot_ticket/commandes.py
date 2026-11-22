"""Commande /ticket_panel : publie le panneau « Support » avec le bouton Créer un ticket."""

from __future__ import annotations

import logging

import discord
from discord import app_commands

from . import embeds as E
from .tickets import repondre, vue_panneau

log = logging.getLogger(__name__)


@app_commands.command(name="ticket_panel", description="Publie le panneau Support avec le bouton Créer un ticket")
@app_commands.describe(salon="Salon où publier le panneau (par défaut : ce salon)")
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def ticket_panel(interaction: discord.Interaction, salon: discord.TextChannel | None = None) -> None:
    cible = salon or interaction.channel
    try:
        await cible.send(embed=E.embed_panneau(), view=vue_panneau())
    except discord.Forbidden:
        return await repondre(
            interaction,
            f"❌ Le bot ne peut pas écrire dans {cible.mention}. Dans les paramètres du salon > Permissions, "
            "donne à son rôle **Voir le salon**, **Envoyer des messages** et **Intégrer des liens**.")
    log.info("%s publie le panneau Support dans #%s", interaction.user, cible)
    await repondre(interaction, f"✅ Panneau Support publié dans {cible.mention}.")


async def gerer_erreur(interaction: discord.Interaction, erreur: app_commands.AppCommandError) -> None:
    log.exception("Erreur dans une commande", exc_info=erreur)
    try:
        await repondre(interaction, E.TEXTE_ERREUR)
    except discord.HTTPException:
        pass
