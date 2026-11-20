"""Démarrage du bot : python -m bot_inscription_manager"""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks
from dotenv import load_dotenv

from . import logique as L
from .commandes import COMMANDES, gerer_erreur
from .inscription import BoutonAnnuler, BoutonInscription, BoutonRefuser, BoutonValider, expirer_inscriptions
from .stockage import Stockage

RACINE = Path(__file__).resolve().parent.parent
log = logging.getLogger("inscription_manager")


class BotTournoi(discord.Client):
    def __init__(self, stockage: Stockage, serveur_id: int | None) -> None:
        # Intents par défaut : pas besoin des intents privilégiés.
        super().__init__(intents=discord.Intents.default())
        self.stockage = stockage
        self.serveur_id = serveur_id
        self.tree = app_commands.CommandTree(self)
        self.tree.error(gerer_erreur)
        for commande in COMMANDES:
            self.tree.add_command(commande)

    async def setup_hook(self) -> None:
        # Les boutons des anciennes annonces / anciens MP refonctionnent après un redémarrage.
        self.add_dynamic_items(BoutonInscription, BoutonValider, BoutonRefuser, BoutonAnnuler)

        if self.serveur_id:
            # Sur un seul serveur : les commandes apparaissent tout de suite.
            serveur = discord.Object(id=self.serveur_id)
            self.tree.copy_global_to(guild=serveur)
            commandes = await self.tree.sync(guild=serveur)
        else:
            commandes = await self.tree.sync()
        log.info("Commandes enregistrées : %s", ", ".join(f"/{c.name}" for c in commandes))
        log.info("Délai de confirmation des coéquipiers : %s minutes", L.DELAI_CONFIRMATION_MINUTES)

        self.verifier_delais.start()

    async def on_ready(self) -> None:
        log.info("Connecté en tant que %s", self.user)

    @tasks.loop(minutes=1)
    async def verifier_delais(self) -> None:
        """Chaque minute : désinscrit les équipes qui n'ont pas confirmé à temps.

        Les délais sont dans les JSON : après un redémarrage, les équipes en retard
        sont désinscrites dès la première vérification.
        """
        try:
            await expirer_inscriptions(self)
        except Exception:  # une erreur ne doit jamais arrêter la vérification suivante
            log.exception("Erreur pendant la vérification des délais de confirmation")

    @verifier_delais.before_loop
    async def avant_verifier_delais(self) -> None:
        await self.wait_until_ready()


AIDE_TOKEN = (
    "Le bon token se trouve dans le Discord Developer Portal > ton application > onglet Bot "
    "> bouton « Reset Token ». Il ressemble à MTIz...abc.Gh1jK2.xyz... (3 morceaux séparés par des points)."
)


def probleme_token(token: str) -> str | None:
    """Repère les erreurs de copier-coller fréquentes, sans jamais afficher le token."""
    if not token:
        return "DISCORD_TOKEN manquant : copie .env.example en .env et mets-y le token du bot."
    if token.lower().startswith("bot "):
        return "Enlève « Bot » au début de DISCORD_TOKEN : mets seulement le token."
    if token.isdigit():
        return "DISCORD_TOKEN contient l'Application ID (que des chiffres), pas le token du bot."
    if re.fullmatch(r"[0-9a-fA-F]{64}", token):
        return "DISCORD_TOKEN contient la Public Key (onglet General Information), pas le token du bot."
    if token.count(".") != 2:
        return "DISCORD_TOKEN ne ressemble pas à un token de bot (c'est peut-être le Client Secret de l'onglet OAuth2)."
    return None


def lire_delai_confirmation(valeur: str | None) -> int:
    """DELAI_CONFIRMATION_MINUTES du .env : un nombre entier de minutes (30 si absent ou vide)."""
    valeur = (valeur or "").strip()
    if not valeur:
        return 30
    if not valeur.isdigit() or not 1 <= int(valeur) <= L.DELAI_CONFIRMATION_MAX_MINUTES:
        raise ValueError(
            f"DELAI_CONFIRMATION_MINUTES doit être un nombre entier de minutes entre 1 et "
            f"{L.DELAI_CONFIRMATION_MAX_MINUTES} (ex : DELAI_CONFIRMATION_MINUTES=30), pas « {valeur} ».")
    return int(valeur)


def main() -> None:
    load_dotenv(RACINE / ".env")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    probleme = probleme_token(token)
    if probleme:
        sys.exit(f"❌ {probleme}\n{AIDE_TOKEN}")

    try:
        L.DELAI_CONFIRMATION_MINUTES = lire_delai_confirmation(os.getenv("DELAI_CONFIRMATION_MINUTES"))
    except ValueError as erreur:
        sys.exit(f"❌ {erreur}")

    serveur_id = os.getenv("GUILD_ID", "").strip()
    if serveur_id and not serveur_id.isdigit():
        sys.exit("❌ GUILD_ID doit contenir uniquement des chiffres (clic droit sur le serveur > Copier l'identifiant).")

    bot = BotTournoi(Stockage(RACINE / "data" / "tournois"), int(serveur_id) if serveur_id else None)
    try:
        bot.run(token, root_logger=True)
    except discord.LoginFailure:
        sys.exit(f"❌ Discord a refusé le token (il est faux ou a été régénéré depuis).\n{AIDE_TOKEN}")


if __name__ == "__main__":
    main()
