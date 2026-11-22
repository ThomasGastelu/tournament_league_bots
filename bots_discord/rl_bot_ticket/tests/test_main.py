"""Démarrage : messages clairs au lieu d'une trace d'erreur."""

import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot_ticket import logique as L
from bot_ticket import main as M


def test_bot_absent_du_serveur_donne_le_lien_d_invitation():
    async def scenario():
        bot = M.BotTicket(1540386765054148639, L.Reglages())
        bot._connection.application_id = 42

        async def sync_refuse(**kwargs):
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"),
                                    {"code": 50001, "message": "Missing Access"})

        bot.tree.sync = sync_refuse
        with pytest.raises(M.ServeurInaccessible) as erreur:
            await bot.setup_hook()
        return str(erreur.value)

    texte = asyncio.run(scenario())
    assert f"client_id=42&scope=bot+applications.commands&permissions={M.PERMISSIONS_INVITATION}" in texte
    assert "GUILD_ID" in texte


def test_main_refuse_un_role_staff_invalide(monkeypatch):
    monkeypatch.setattr(M, "load_dotenv", lambda *a, **k: None)  # ne lit pas le vrai .env
    monkeypatch.setenv("DISCORD_TOKEN", "MTIz.Gh1jK2.xyz")
    monkeypatch.setenv("GUILD_ID", "123")
    monkeypatch.setenv("ROLES_STAFF", "Modérateurs")
    with pytest.raises(SystemExit) as sortie:
        M.main()
    assert "ROLES_STAFF" in str(sortie.value)


def test_main_affiche_le_message_et_quitte(monkeypatch):
    monkeypatch.setattr(M, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("DISCORD_TOKEN", "MTIz.Gh1jK2.xyz")
    monkeypatch.setenv("GUILD_ID", "123")
    monkeypatch.delenv("ROLES_STAFF", raising=False)

    def run_refuse(self, *a, **k):
        raise M.ServeurInaccessible(M.aide_invitation(42))

    monkeypatch.setattr(M.BotTicket, "run", run_refuse)
    with pytest.raises(SystemExit) as sortie:
        M.main()
    assert "serveur 123" in str(sortie.value) and "client_id=42" in str(sortie.value)
