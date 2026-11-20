"""Démarrage du bot : python -m bot_mp"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

from .commandes import gerer_erreur, mp_all
from .logique import probleme_token

RACINE = Path(__file__).resolve().parent.parent
log = logging.getLogger("bot_mp")

AIDE_TOKEN = (
    "Le bon token se trouve dans le Discord Developer Portal > ton application > onglet Bot "
    "> bouton « Reset Token ». Il ressemble à MTIz...abc.Gh1jK2.xyz... (3 morceaux séparés par des points)."
)
AIDE_INTENT = (
    "Active « Server Members Intent » dans le Discord Developer Portal > ton application > onglet Bot "
    "> Privileged Gateway Intents, clique sur Save Changes, puis relance le bot."
)


def aide_invitation(application_id: int | None) -> str:
    lien = ("https://discord.com/oauth2/authorize?client_id="
            f"{application_id or 'APPLICATION_ID'}&scope=bot+applications.commands&permissions=0")
    return (
        "Causes possibles :\n"
        "  1. Le bot n'est pas encore sur ce serveur → invite-le avec ce lien :\n"
        f"     {lien}\n"
        "  2. Il a été invité sans « applications.commands » → réinvite-le avec le même lien (sans l'expulser).\n"
        "  3. GUILD_ID n'est pas l'ID du serveur (clic droit sur le serveur > Copier l'identifiant du serveur)."
    )


class ServeurInaccessible(Exception):
    """Discord refuse d'enregistrer la commande sur le serveur GUILD_ID."""


class BotMP(discord.Client):
    def __init__(self, serveur_id: int | None) -> None:
        intents = discord.Intents.default()
        intents.members = True  # pour connaître la liste de tous les membres du serveur
        super().__init__(intents=intents)
        self.serveur_id = serveur_id
        self.envoi_en_cours = False
        self.tree = app_commands.CommandTree(self)
        self.tree.error(gerer_erreur)
        self.tree.add_command(mp_all)

    async def setup_hook(self) -> None:
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


def main() -> None:
    load_dotenv(RACINE / ".env")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    probleme = probleme_token(token)
    if probleme:
        sys.exit(f"❌ {probleme}\n{AIDE_TOKEN}")

    serveur_id = os.getenv("GUILD_ID", "").strip()
    if serveur_id and not serveur_id.isdigit():
        sys.exit("❌ GUILD_ID doit contenir uniquement des chiffres (clic droit sur le serveur > Copier l'identifiant).")

    bot = BotMP(int(serveur_id) if serveur_id else None)
    try:
        bot.run(token, root_logger=True)
    except discord.LoginFailure:
        sys.exit(f"❌ Discord a refusé le token (il est faux ou a été régénéré depuis).\n{AIDE_TOKEN}")
    except discord.PrivilegedIntentsRequired:
        sys.exit(f"❌ Le bot n'a pas le droit de voir la liste des membres.\n{AIDE_INTENT}")
    except ServeurInaccessible as erreur:
        sys.exit(f"❌ Discord refuse d'ajouter /mp_all sur le serveur {serveur_id} (GUILD_ID du .env).\n{erreur}")


if __name__ == "__main__":
    main()
