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
from .stockage import StockageFichiers
from .stockage_api import StockageAPI

RACINE = Path(__file__).resolve().parent.parent
log = logging.getLogger("inscription_manager")


class BotTournoi(discord.Client):
    def __init__(self, stockage: StockageFichiers | StockageAPI, serveur_id: int | None) -> None:
        # Intents par défaut : pas besoin des intents privilégiés.
        super().__init__(intents=discord.Intents.default())
        self.stockage = stockage
        self.serveur_id = serveur_id
        self._doublons_nettoyes = False
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
            await vider_commandes_globales(self.tree)
        else:
            commandes = await self.tree.sync()
        log.info("Commandes enregistrées : %s", ", ".join(f"/{c.name}" for c in commandes))
        log.info("Délai de confirmation des coéquipiers : %s minutes", L.DELAI_CONFIRMATION_MINUTES)

        if self.serveur_id and isinstance(self.stockage, StockageAPI):
            # tournament_manager lit les copies JSON : on les remet à jour depuis la base au démarrage.
            try:
                nombre = await self.stockage.rafraichir_copies(str(self.serveur_id))
                log.info("Copies JSON de %s tournoi(s) mises à jour depuis la base", nombre)
            except L.ErreurTournoi as erreur:
                log.warning("Copies JSON non mises à jour au démarrage : %s", erreur)

        self.verifier_delais.start()

    async def close(self) -> None:
        await self.stockage.fermer()
        await super().close()

    async def on_ready(self) -> None:
        log.info("Connecté en tant que %s", self.user)
        if not self.serveur_id and not self._doublons_nettoyes:
            self._doublons_nettoyes = True  # on_ready revient après chaque reconnexion
            await vider_commandes_des_serveurs(self.tree, self.guilds)

    @tasks.loop(minutes=1)
    async def verifier_delais(self) -> None:
        """Chaque minute : désinscrit les équipes qui n'ont pas confirmé à temps.

        Les délais sont enregistrés (base de données ou JSON) : après un redémarrage,
        les équipes en retard sont désinscrites dès la première vérification.
        """
        try:
            await expirer_inscriptions(self)
        except Exception:  # une erreur ne doit jamais arrêter la vérification suivante
            log.exception("Erreur pendant la vérification des délais de confirmation")

    @verifier_delais.before_loop
    async def avant_verifier_delais(self) -> None:
        await self.wait_until_ready()


async def vider_commandes_globales(tree: app_commands.CommandTree) -> None:
    """Avec GUILD_ID : supprime les anciennes commandes globales (enregistrées un jour sans GUILD_ID).

    Sinon Discord affiche chaque commande en double sur le serveur : la version du serveur
    et l'ancienne version globale, qui n'a pas les nouvelles options.
    """
    tree.clear_commands(guild=None)
    try:
        await tree.sync()
    except discord.HTTPException as erreur:
        log.warning("Anciennes commandes globales non supprimées (%s) : des commandes peuvent "
                    "apparaître en double sur Discord.", erreur)


async def vider_commandes_des_serveurs(tree: app_commands.CommandTree, serveurs) -> None:
    """Sans GUILD_ID : supprime les anciennes commandes enregistrées serveur par serveur
    (quand GUILD_ID était rempli), qui feraient doublon avec les commandes globales."""
    for serveur in serveurs:
        tree.clear_commands(guild=serveur)
        try:
            await tree.sync(guild=serveur)
        except discord.HTTPException as erreur:
            log.warning("Anciennes commandes du serveur %s non supprimées (%s).", serveur.id, erreur)


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


LONGUEUR_MIN_CLE_API = 32  # comme l'API, qui refuse une BOT_API_KEY plus courte


def choisir_stockage(url: str | None, cle: str | None, dossier: Path) -> StockageFichiers | StockageAPI:
    """API_URL rempli : la base de données via l'API (avec copie JSON pour tournament_manager).
    API_URL vide : les fichiers JSON seuls, comme avant."""
    url, cle = (url or "").strip(), (cle or "").strip()
    if not url:
        return StockageFichiers(dossier)
    if not re.match(r"https?://[^\s/]+", url):
        raise ValueError(f"API_URL doit commencer par http:// ou https:// (ex : API_URL=http://localhost), pas « {url} ».")
    if len(cle) < LONGUEUR_MIN_CLE_API:
        raise ValueError(
            f"BOT_API_KEY manquante ou trop courte ({LONGUEUR_MIN_CLE_API} caractères minimum) : "
            f"mets la même clé que dans le .env de l'API.")
    return StockageAPI(url, cle, dossier_miroir=dossier)


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

    try:
        stockage = choisir_stockage(os.getenv("API_URL"), os.getenv("BOT_API_KEY"), RACINE / "data" / "tournois")
    except ValueError as erreur:
        sys.exit(f"❌ {erreur}")
    if isinstance(stockage, StockageAPI):
        log.info("Tournois enregistrés dans la base de données via %s", stockage.url)
    else:
        log.info("Tournois enregistrés dans les fichiers JSON (API_URL vide)")

    bot = BotTournoi(stockage, int(serveur_id) if serveur_id else None)
    try:
        bot.run(token, root_logger=True)
    except discord.LoginFailure:
        sys.exit(f"❌ Discord a refusé le token (il est faux ou a été régénéré depuis).\n{AIDE_TOKEN}")


if __name__ == "__main__":
    main()
