"""Démarrage du bot : python -m bot_ticket"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

from . import logique as L
from .commandes import gerer_erreur, ticket_panel
from .tickets import BoutonCreerTicket, BoutonFermerTicket

RACINE = Path(__file__).resolve().parent.parent
log = logging.getLogger("bot_ticket")

AIDE_TOKEN = (
    "Le bon token se trouve dans le Discord Developer Portal > ton application > onglet Bot "
    "> bouton « Reset Token ». Il ressemble à MTIz...abc.Gh1jK2.xyz... (3 morceaux séparés par des points)."
)
# Gérer les salons (16) + Voir les salons (1024) + Envoyer des messages (2048)
# + Intégrer des liens (16384) + Joindre des fichiers (32768) + Voir l'historique (65536)
PERMISSIONS_INVITATION = 16 + 1024 + 2048 + 16384 + 32768 + 65536


def aide_invitation(application_id: int | None) -> str:
    lien = ("https://discord.com/oauth2/authorize?client_id="
            f"{application_id or 'APPLICATION_ID'}&scope=bot+applications.commands"
            f"&permissions={PERMISSIONS_INVITATION}")
    return (
        "Causes possibles :\n"
        "  1. Le bot n'est pas encore sur ce serveur → invite-le avec ce lien :\n"
        f"     {lien}\n"
        "  2. Il a été invité sans « applications.commands » → réinvite-le avec le même lien (sans l'expulser).\n"
        "  3. GUILD_ID n'est pas l'ID du serveur (clic droit sur le serveur > Copier l'identifiant du serveur)."
    )


class ServeurInaccessible(Exception):
    """Discord refuse d'enregistrer la commande sur le serveur GUILD_ID."""


class BotTicket(discord.Client):
    def __init__(self, serveur_id: int | None, reglages: L.Reglages) -> None:
        super().__init__(intents=discord.Intents.default())
        self.serveur_id = serveur_id
        self.reglages = reglages
        self.tree = app_commands.CommandTree(self)
        self.tree.error(gerer_erreur)
        self.tree.add_command(ticket_panel)

    async def setup_hook(self) -> None:
        # Boutons persistants : ils marchent sur les anciens messages, même après un redémarrage.
        self.add_dynamic_items(BoutonCreerTicket, BoutonFermerTicket)
        if self.serveur_id:
            # Sur un seul serveur : la commande apparaît tout de suite.
            serveur = discord.Object(id=self.serveur_id)
            self.tree.copy_global_to(guild=serveur)
            try:
                commandes = await self.tree.sync(guild=serveur)
            except discord.Forbidden as erreur:  # 50001 Missing Access
                raise ServeurInaccessible(aide_invitation(self.application_id)) from erreur
        else:
            commandes = await self.tree.sync()
        log.info("Commandes enregistrées : %s", ", ".join(f"/{c.name}" for c in commandes))

    async def on_ready(self) -> None:
        log.info("Connecté en tant que %s", self.user)
        if not self.reglages.roles_staff:
            log.warning("ROLES_STAFF est vide : seuls les membres qui peuvent gérer les salons verront les tickets.")


def main() -> None:
    load_dotenv(RACINE / ".env")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    probleme = L.probleme_token(token)
    if probleme:
        sys.exit(f"❌ {probleme}\n{AIDE_TOKEN}")

    serveur_id = os.getenv("GUILD_ID", "").strip()
    if serveur_id and not serveur_id.isdigit():
        sys.exit("❌ GUILD_ID doit contenir uniquement des chiffres (clic droit sur le serveur > Copier l'identifiant).")
    try:
        reglages = L.lire_reglages(os.environ)
    except L.ErreurReglage as erreur:
        sys.exit(f"❌ {erreur}")

    bot = BotTicket(int(serveur_id) if serveur_id else None, reglages)
    try:
        bot.run(token, root_logger=True)
    except discord.LoginFailure:
        sys.exit(f"❌ Discord a refusé le token (il est faux ou a été régénéré depuis).\n{AIDE_TOKEN}")
    except ServeurInaccessible as erreur:
        sys.exit(f"❌ Discord refuse d'ajouter /ticket_panel sur le serveur {serveur_id} (GUILD_ID du .env).\n{erreur}")


if __name__ == "__main__":
    main()
