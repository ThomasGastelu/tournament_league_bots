"""Permissions du bot dans le salon du tournoi."""

import asyncio
import logging
from types import SimpleNamespace

import discord
import pytest

from bot_tournament_manager.deroulement import MessagerieDiscord, permissions_manquantes


def faux_salon(**permissions):
    """Salon dont les permissions du bot sont `permissions`, et dont l'envoi est refusé (403)."""
    async def envoyer(*_args, **_kwargs):
        raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"),
                                {"code": 50013, "message": "Missing Permissions"})
    return SimpleNamespace(
        name="tournois", guild=SimpleNamespace(me=object()), send=envoyer,
        permissions_for=lambda _membre: discord.Permissions(**permissions),
    )


def test_permissions_manquantes():
    assert permissions_manquantes(faux_salon(view_channel=True, send_messages=False, embed_links=False)) == [
        "Envoyer des messages", "Intégrer des liens"]
    assert permissions_manquantes(faux_salon(view_channel=True, send_messages=True, embed_links=True)) == []
    assert permissions_manquantes(None) == []  # salon inconnu : on ne bloque pas


def test_avertissement_nomme_la_permission_manquante(caplog):
    salon = faux_salon(view_channel=True, send_messages=True, embed_links=False)
    client = SimpleNamespace(get_channel=lambda _id: salon, user=SimpleNamespace(name="tournament_manager"))
    etat = {"tournoi_id": "1571169059024928818", "salon_id": "1543205821490528366"}

    with caplog.at_level(logging.WARNING):
        asyncio.run(MessagerieDiscord(client).annonce(etat, texte="test"))

    assert "#tournois" in caplog.text
    assert "il manque au bot : Intégrer des liens" in caplog.text
    assert "tournament_manager" in caplog.text


# --------------------------------------------------------------------------- #
# SALON_ANNONCES : salon choisi dans le .env
# --------------------------------------------------------------------------- #

def test_annonces_dans_le_salon_du_env():
    envois = []

    async def envoyer(texte, **_kwargs):
        envois.append(texte)

    salons = {111: SimpleNamespace(name="annonces", send=envoyer)}
    client = SimpleNamespace(get_channel=salons.get, user=None)
    etat = {"tournoi_id": "1", "salon_id": "222"}  # salon du bot d'inscription

    asyncio.run(MessagerieDiscord(client, salon_annonces=111).annonce(etat, texte="Round 1/3"))
    assert envois == ["Round 1/3"]
    assert MessagerieDiscord(client).salon_id(etat) == 222  # sans SALON_ANNONCES : salon du tournoi


def test_start_refuse_si_salon_du_env_introuvable():
    from bot_tournament_manager.commandes import probleme_salon

    gestionnaire = SimpleNamespace(
        stockage=SimpleNamespace(charger_inscription=lambda _id: {"salon_id": "222"}),
        messagerie=MessagerieDiscord(None, salon_annonces=111),
    )
    interaction = SimpleNamespace(client=SimpleNamespace(gestionnaire=gestionnaire),
                                  guild=SimpleNamespace(get_channel_or_thread=lambda _id: None))
    assert "SALON_ANNONCES=111" in probleme_salon(interaction, "1")


def test_config_salon_annonces(monkeypatch, tmp_path):
    from bot_tournament_manager import config as C

    monkeypatch.setattr(C, "load_dotenv", lambda *_a, **_k: None)
    script = tmp_path / "generer_pp_names.py"
    script.write_text("")
    for nom, valeur in {"DISCORD_TOKEN": "a.b.c", "GUILD_ID": "", "DOSSIER_INSCRIPTIONS": str(tmp_path),
                        "SCRIPT_PP": str(script)}.items():
        monkeypatch.setenv(nom, valeur)

    monkeypatch.setenv("SALON_ANNONCES", "")
    assert C.charger_config().salon_annonces is None
    monkeypatch.setenv("SALON_ANNONCES", " 1543205821490528366 ")
    assert C.charger_config().salon_annonces == 1543205821490528366
    monkeypatch.setenv("SALON_ANNONCES", "#annonces")
    with pytest.raises(C.ErreurConfig, match="SALON_ANNONCES"):
        C.charger_config()
    monkeypatch.setenv("SALON_ANNONCES", "")

    monkeypatch.setenv("SALON_RESULTATS", "")
    assert C.charger_config().salon_resultats is None
    monkeypatch.setenv("SALON_RESULTATS", "1543205821490528999")
    assert C.charger_config().salon_resultats == 1543205821490528999
