import asyncio

import discord
import pytest

from bot_inscription_manager.main import BotTournoi, lire_delai_confirmation, probleme_token


@pytest.mark.parametrize("token, attendu", [
    ("", "manquant"),
    ("Bot abc.def.ghi", "Enlève « Bot »"),
    ("1544015944353976341", "Application ID"),
    ("a3" * 32, "Public Key"),
    ("AbCdEfGhIjKlMnOpQrStUvWxYz012345", "Client Secret"),
])
def test_erreurs_de_copier_coller(token, attendu):
    assert attendu in probleme_token(token)


def test_token_de_bot_valide():
    # Faux token au format « partie1.partie2.partie3 » (pas un vrai token, pour ne pas déclencher le secret scanning de GitHub).
    assert probleme_token("faux-id-de-bot.horodatage.signature-de-test") is None


@pytest.mark.parametrize("valeur, attendu", [(None, 30), ("", 30), (" 45 ", 45), ("1", 1), ("10080", 10080)])
def test_delai_confirmation_valide(valeur, attendu):
    assert lire_delai_confirmation(valeur) == attendu


@pytest.mark.parametrize("valeur", ["0", "-5", "30min", "1.5", "abc", "10081"])
def test_delai_confirmation_invalide(valeur):
    with pytest.raises(ValueError, match="DELAI_CONFIRMATION_MINUTES doit être un nombre entier"):
        lire_delai_confirmation(valeur)


# --- Commandes en double sur Discord (ancienne version globale + version du serveur) ---


class AppelsSync:
    """Remplace tree.sync : note ce qui serait envoyé à Discord, sans réseau."""

    def __init__(self, tree):
        self.tree = tree
        self.appels: list[tuple[int | None, list[str]]] = []

    async def __call__(self, *, guild=None):
        commandes = self.tree.get_commands(guild=guild)
        self.appels.append((guild.id if guild else None, [c.name for c in commandes]))
        return commandes


class StockageFactice:
    async def fermer(self):
        pass


def test_avec_guild_id_les_anciennes_commandes_globales_sont_supprimees():
    async def scenario():
        bot = BotTournoi(StockageFactice(), 42)
        bot.tree.sync = sync = AppelsSync(bot.tree)
        bot.verifier_delais.start = lambda: None
        await bot.setup_hook()
        return sync.appels

    appels = asyncio.run(scenario())
    serveur, globales = appels
    assert serveur[0] == 42 and "tournoi_rl" in serveur[1]
    assert globales == (None, [])  # plus de /tournoi_rl global en double


def test_sans_guild_id_les_anciennes_commandes_du_serveur_sont_supprimees(monkeypatch):
    async def scenario():
        bot = BotTournoi(StockageFactice(), None)
        bot.tree.sync = sync = AppelsSync(bot.tree)
        bot.verifier_delais.start = lambda: None
        await bot.setup_hook()
        serveurs = [discord.Object(id=7), discord.Object(id=8)]
        monkeypatch.setattr(BotTournoi, "guilds", property(lambda self: serveurs))
        await bot.on_ready()
        await bot.on_ready()  # reconnexion : pas de second nettoyage
        return sync.appels

    appels = asyncio.run(scenario())
    assert appels[0][0] is None and "tournoi_rl" in appels[0][1]
    assert appels[1:] == [(7, []), (8, [])]
