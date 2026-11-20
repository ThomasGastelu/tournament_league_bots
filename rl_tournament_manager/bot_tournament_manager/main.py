"""Démarrage du bot : python -m bot_tournament_manager"""

from __future__ import annotations

import asyncio
import logging
import sys

import discord
from discord import app_commands

from . import logique as L
from .commandes import COMMANDES, gerer_erreur
from .config import Config, ErreurConfig, charger_config
from .declaration import BoutonDeclaration, BoutonPartieCreee
from .deroulement import GestionnaireTournois, MessagerieDiscord, permissions_manquantes
from .journal import HORS_JOURNAL, JournalDiscord
from .observation import creer_observateur
from .stockage import Stockage

log = logging.getLogger("tournament_manager")

# Voir les salons, Envoyer des messages, Intégrer des liens, Voir l'historique,
# Gérer les salons et Joindre des fichiers (salon de discussion de chaque tournoi).
PERMISSIONS = 117776
# Loggers dont les avertissements et erreurs sont copiés dans LOG_CHANNEL.
LOGGERS_JOURNAL = ("bot_tournament_manager", "tournament_manager")


class BotTournoi(discord.Client):
    def __init__(self, config: Config) -> None:
        # Intents par défaut : pas besoin des intents privilégiés.
        # Les noms d'équipes ne peuvent pas faire de @everyone / @rôle.
        super().__init__(intents=discord.Intents.default(),
                         allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))
        self.config = config
        self.messagerie = MessagerieDiscord(self, config.salon_annonces, config.log_channel)
        self.gestionnaire = GestionnaireTournois(
            Stockage(config.dossier_inscriptions, config.dossier_donnees),
            creer_observateur(config),
            self.messagerie,
            script_pp=config.script_pp,
            pause_entre_rondes=config.pause_entre_rondes,
            rappel_clic_pp=config.rappel_clic_pp,
            attente_clic_pp_max=config.attente_clic_pp_max,
        )
        self.journal = JournalDiscord(self.messagerie.journal) if config.log_channel else None
        self._demarrage_annonce = False
        self.tree = app_commands.CommandTree(self)
        self.tree.error(gerer_erreur)
        for commande in COMMANDES:
            self.tree.add_command(commande)

    def lien_invitation(self) -> str:
        return (f"https://discord.com/oauth2/authorize?client_id={self.application_id}"
                f"&scope=bot+applications.commands&permissions={PERMISSIONS}")

    def brancher_journal(self) -> None:
        """Copie les avertissements et erreurs du bot dans LOG_CHANNEL."""
        if self.journal:
            for nom in LOGGERS_JOURNAL:
                logging.getLogger(nom).addHandler(self.journal)

    async def setup_hook(self) -> None:
        if self.journal:
            self.journal.demarrer(asyncio.get_running_loop())
        # Boutons des MP (« Partie privée créée », « Déclarer le score ») : ils marchent encore après un redémarrage.
        self.add_dynamic_items(BoutonPartieCreee, BoutonDeclaration)

        if self.config.serveur_id:
            # Sur un seul serveur : les commandes apparaissent tout de suite.
            serveur = discord.Object(id=self.config.serveur_id)
            self.tree.copy_global_to(guild=serveur)
            try:
                commandes = await self.tree.sync(guild=serveur)
            except discord.Forbidden as erreur:
                raise ErreurConfig(
                    f"Discord refuse d'enregistrer les commandes sur le serveur {self.config.serveur_id} "
                    f"({erreur.status} {erreur.text or 'Missing Access'}).\n"
                    "Le bot n'est pas sur ce serveur, ou il a été invité sans « applications.commands », "
                    "ou GUILD_ID n'est pas le bon.\n"
                    f"Invite le bot avec ce lien (puis relance-le) :\n{self.lien_invitation()}"
                ) from erreur
        else:
            commandes = await self.tree.sync()
        log.info("Commandes enregistrées : %s", ", ".join(f"/{c.name}" for c in commandes))

        repris = self.gestionnaire.reprendre()
        if repris:
            log.info("Tournoi(s) repris après redémarrage : %s", ", ".join(repris))

    async def on_ready(self) -> None:
        log.info("Connecté en tant que %s (observateur : %s)", self.user, self.config.observateur)
        if self._demarrage_annonce:
            return  # on_ready revient après chaque reconnexion
        self._demarrage_annonce = True

        annonces = self.verifier_salon("SALON_ANNONCES", self.config.salon_annonces, "les annonces")
        if not self.config.log_channel:
            log.info("LOG_CHANNEL est vide dans le .env : les alertes partent en MP à l'admin qui a lancé le tournoi.")
        elif self.verifier_salon("LOG_CHANNEL", self.config.log_channel, "les alertes et les problèmes du bot"):
            await self.messagerie.journal(
                f"✅ Bot démarré (observateur : **{self.config.observateur}**). "
                f"Annonces : {f'<#{annonces}>' if annonces else 'salon de chaque tournoi'}.")
        verifier = getattr(self.gestionnaire.observateur, "verifier", None)
        for avertissement in (verifier() if verifier else []):
            log.warning("[rl] %s", avertissement)

        if not any(e.get("statut") == L.EN_COURS for e in self.gestionnaire.stockage.lister_etats()):
            log.info("Prêt. Aucun tournoi en cours : lance-en un en tapant /start_tournament_rl "
                     "dans ton serveur Discord.")

    def verifier_salon(self, variable: str, salon_id: int | None, usage: str) -> int | None:
        """Dit dans la console où partent les messages, et prévient tout de suite si ça ne marchera pas.
        Renvoie l'ID du salon s'il est utilisable."""
        if not salon_id:
            if variable == "SALON_ANNONCES":
                log.info("Annonces : dans le salon de chaque tournoi (SALON_ANNONCES est vide dans le .env).")
            return None
        # Les problèmes de LOG_CHANNEL ne peuvent pas être signalés dans LOG_CHANNEL.
        extra = HORS_JOURNAL if variable == "LOG_CHANNEL" else {}
        salon = self.get_channel(salon_id)
        if salon is None:
            log.warning("%s=%s : ce salon n'existe pas sur les serveurs du bot. Copie le bon identifiant "
                        "(clic droit sur le salon > Copier l'identifiant) dans le .env.", variable, salon_id,
                        extra=extra)
            return None
        serveur = getattr(salon, "guild", None)
        if self.config.serveur_id and serveur is not None and serveur.id != self.config.serveur_id:
            log.warning("%s : le salon #%s est sur le serveur « %s », pas sur celui de GUILD_ID.",
                        variable, getattr(salon, "name", salon_id), serveur.name, extra=extra)
        manquantes = permissions_manquantes(salon)
        if manquantes:
            log.warning("%s : le bot ne peut pas poster dans #%s, il lui manque : %s. Dans Discord : "
                        "clic droit sur le salon > Modifier le salon > Permissions > ajoute le rôle « %s ».",
                        variable, getattr(salon, "name", salon_id), ", ".join(manquantes),
                        self.user.name if self.user else "du bot", extra=extra)
            return None
        log.info("%s : dans le salon #%s.", usage[0].upper() + usage[1:], getattr(salon, "name", salon_id))
        return salon_id

    async def close(self) -> None:
        await self.gestionnaire.fermer()
        if self.journal:
            for nom in LOGGERS_JOURNAL:
                logging.getLogger(nom).removeHandler(self.journal)
        await super().close()


def main() -> None:
    try:
        config = charger_config()
        bot = BotTournoi(config)
    except ErreurConfig as erreur:
        sys.exit(f"❌ {erreur}")
    bot.brancher_journal()
    try:
        bot.run(config.token, root_logger=True)
    except ErreurConfig as erreur:
        sys.exit(f"❌ {erreur}")
    except discord.LoginFailure:
        sys.exit("❌ Discord a refusé le token (il est faux ou a été régénéré depuis). "
                 "Mets le bon token dans DISCORD_TOKEN du fichier .env.")


if __name__ == "__main__":
    main()
