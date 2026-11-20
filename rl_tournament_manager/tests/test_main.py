import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot_tournament_manager.config import Config, ErreurConfig
from bot_tournament_manager.main import BotTournoi


def config(tmp_path) -> Config:
    return Config(
        token="a.b.c", serveur_id=1540386765054148639, salon_annonces=None, dossier_inscriptions=tmp_path,
        script_pp=tmp_path / "generer_pp_names.py", dossier_donnees=tmp_path / "data",
        pause_entre_rondes=0, observateur="simulation",
        simulation_duree_min=0, simulation_duree_max=0,
        simulation_proba_sans_gagnant=0, simulation_proba_couleurs_inversees=0,
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
            "&scope=bot+applications.commands&permissions=117776") in message
