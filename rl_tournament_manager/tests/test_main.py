import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot_tournament_manager.config import Config, ErreurConfig
from bot_tournament_manager.main import BotTournoi


def config(tmp_path) -> Config:
    return Config(
        token="a.b.c", serveur_id=1540386765054148639, salon_annonces=None, dossier_inscriptions=tmp_path,
        dossier_donnees=tmp_path / "data",
        pause_entre_rondes=0,
    )


def test_bot_pas_invite_sur_le_serveur_donne_le_lien(tmp_path):
    """403 Missing Access à l'enregistrement des commandes → message clair avec le lien d'invitation."""
    async def scenario():
        bot = BotTournoi(config(tmp_path))
        bot._connection.application_id = 123456789  # normalement rempli par Discord à la connexion

        async def refus(**_):
            reponse = SimpleNamespace(status=403, reason="Forbidden")
            raise discord.Forbidden(reponse, {"code": 50001, "message": "Missing Access"})

        bot.tree.sync = refus
        with pytest.raises(ErreurConfig) as erreur:
            await bot.setup_hook()
        return str(erreur.value)

    message = asyncio.run(scenario())
    assert "1540386765054148639" in message
    assert ("https://discord.com/oauth2/authorize?client_id=123456789"
            "&scope=bot+applications.commands&permissions=268553232") in message


class AppelsSync:
    """Remplace tree.sync : note ce qui serait envoyé à Discord, sans réseau."""

    def __init__(self, tree):
        self.tree = tree
        self.appels: list[tuple[int | None, list[str]]] = []

    async def __call__(self, *, guild=None):
        commandes = self.tree.get_commands(guild=guild)
        self.appels.append((guild.id if guild else None, [c.name for c in commandes]))
        return commandes


def test_avec_guild_id_les_anciennes_commandes_globales_sont_supprimees(tmp_path):
    """Sinon Discord montre chaque commande deux fois : version du serveur + ancienne version globale."""
    async def scenario():
        bot = BotTournoi(config(tmp_path))
        bot.tree.sync = sync = AppelsSync(bot.tree)
        await bot.setup_hook()
        await bot.gestionnaire.fermer()
        return sync.appels

    serveur, globales = asyncio.run(scenario())
    assert serveur[0] == 1540386765054148639 and "start_tournament_rl" in serveur[1]
    assert globales == (None, [])
