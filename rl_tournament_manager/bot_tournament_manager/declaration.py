"""Boutons des MP. Leur identifiant contient le tournoi, le round, la zone (et l'équipe) :
ils marchent encore après un redémarrage du bot (discord.ui.DynamicItem, enregistrés dans main.py).

- « ✅ Partie privée créée » : envoyé au capitaine qui crée la partie. Son clic prévient
  les autres joueurs, et le bot commence à passer dans la partie.
- « 📝 Déclarer le score » : envoyé aux joueurs quand le bot n'a pas pu prendre le score.
  Il ouvre une petite fenêtre (2 cases : buts de mon équipe, buts de l'adversaire).
- « ✅ Valider ma participation » : envoyé par /start_tournament_init (avec delai_confirmation)
  aux joueurs inscrits ; un clic suffit pour toute l'équipe.
"""

from __future__ import annotations

import logging
import re

import discord
from discord import ui

from . import logique as L

log = logging.getLogger(__name__)

MODELE_ID = r"rlscore:(?P<tournoi>\d+):(?P<ronde>\d+):(?P<zone>\d+):(?P<equipe>\d+)"


def custom_id(tournoi_id: str, numero: int, zone: int, equipe_id: int) -> str:
    return f"rlscore:{tournoi_id}:{numero}:{zone}:{equipe_id}"


def lire_custom_id(identifiant: str) -> tuple[str, int, int, int] | None:
    trouve = re.fullmatch(MODELE_ID, identifiant)
    if not trouve:
        return None
    return trouve["tournoi"], int(trouve["ronde"]), int(trouve["zone"]), int(trouve["equipe"])


class BoutonDeclaration(ui.DynamicItem[ui.Button], template=MODELE_ID):
    def __init__(self, tournoi_id: str, numero: int, zone: int, equipe_id: int) -> None:
        super().__init__(ui.Button(label="Déclarer le score", emoji="📝", style=discord.ButtonStyle.primary,
                                   custom_id=custom_id(tournoi_id, numero, zone, equipe_id)))
        self.tournoi_id, self.numero, self.zone, self.equipe_id = tournoi_id, numero, zone, equipe_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: ui.Button, match: re.Match[str], /):
        return cls(match["tournoi"], int(match["ronde"]), int(match["zone"]), int(match["equipe"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        gestionnaire = interaction.client.gestionnaire  # type: ignore[attr-defined]
        etat = gestionnaire.stockage.charger_etat(self.tournoi_id)
        if etat is None or str(self.equipe_id) not in etat["equipes"]:
            return await interaction.response.send_message("❌ Ce tournoi n'existe plus.", ephemeral=True)
        equipe = L.equipe(etat, self.equipe_id)
        if not any(j["id"] == str(interaction.user.id) for j in equipe["joueurs"]):
            return await interaction.response.send_message(
                f"❌ Seuls les joueurs de **{discord.utils.escape_markdown(equipe['nom'])}** peuvent utiliser ce bouton.",
                ephemeral=True)
        try:
            match = L.trouver_match(L.trouver_ronde(etat, self.numero), self.zone)
        except L.ErreurTournoi as erreur:
            return await interaction.response.send_message(f"❌ {erreur}", ephemeral=True)
        adversaire = L.equipe(etat, L.adversaire(match, self.equipe_id))
        await interaction.response.send_modal(
            FenetreDeclaration(self.tournoi_id, self.numero, self.zone, self.equipe_id, equipe["nom"], adversaire["nom"]))


class FenetreDeclaration(ui.Modal):
    def __init__(self, tournoi_id: str, numero: int, zone: int, equipe_id: int, nom: str, nom_adversaire: str) -> None:
        super().__init__(title=f"Score du round {numero} — zone {zone}"[:45], timeout=600)
        self.tournoi_id, self.numero, self.zone, self.equipe_id = tournoi_id, numero, zone, equipe_id
        self.buts_equipe = ui.TextInput(label=f"Buts de {nom} (ton équipe)"[:45], placeholder="ex. 3",
                                        min_length=1, max_length=2)
        self.buts_adversaire = ui.TextInput(label=f"Buts de {nom_adversaire}"[:45], placeholder="ex. 1",
                                            min_length=1, max_length=2)
        self.add_item(self.buts_equipe)
        self.add_item(self.buts_adversaire)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        brut = (self.buts_equipe.value.strip(), self.buts_adversaire.value.strip())
        if not all(b.isdigit() for b in brut):
            return await interaction.response.send_message(
                "❌ Mets seulement des nombres (ex. 3 et 1). Reclique sur le bouton pour recommencer.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        gestionnaire = interaction.client.gestionnaire  # type: ignore[attr-defined]
        try:
            reponse = await gestionnaire.declarer_score(
                self.tournoi_id, self.numero, self.zone, self.equipe_id, int(brut[0]), int(brut[1]),
                par=str(interaction.user.id))
        except L.ErreurTournoi as erreur:
            reponse = f"❌ {erreur}"
        await interaction.followup.send(reponse, ephemeral=True)


def vue_declaration(tournoi_id: str, numero: int, zone: int, equipe_id: int) -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(BoutonDeclaration(tournoi_id, numero, zone, equipe_id))
    return vue


# --------------------------------------------------------------------------- #
# « Partie privée créée »
# --------------------------------------------------------------------------- #

MODELE_ID_PP = r"rlpp:(?P<tournoi>\d+):(?P<ronde>\d+):(?P<zone>\d+)"


def custom_id_pp(tournoi_id: str, numero: int, zone: int) -> str:
    return f"rlpp:{tournoi_id}:{numero}:{zone}"


class BoutonPartieCreee(ui.DynamicItem[ui.Button], template=MODELE_ID_PP):
    def __init__(self, tournoi_id: str, numero: int, zone: int) -> None:
        super().__init__(ui.Button(label="Partie privée créée", emoji="✅", style=discord.ButtonStyle.success,
                                   custom_id=custom_id_pp(tournoi_id, numero, zone)))
        self.tournoi_id, self.numero, self.zone = tournoi_id, numero, zone

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: ui.Button, match: re.Match[str], /):
        return cls(match["tournoi"], int(match["ronde"]), int(match["zone"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        # Prévenir les autres joueurs prend quelques secondes : on répond à Discord tout de suite.
        await interaction.response.defer()
        gestionnaire = interaction.client.gestionnaire  # type: ignore[attr-defined]
        try:
            reponse = await gestionnaire.signaler_pp_creee(self.tournoi_id, self.numero, self.zone,
                                                          par=str(interaction.user.id))
        except L.ErreurTournoi as erreur:
            return await interaction.followup.send(f"❌ {erreur}", ephemeral=True)
        try:  # bouton grisé : on ne peut plus cliquer dessus
            await interaction.edit_original_response(view=vue_pp_deja_creee())
        except discord.HTTPException as erreur:
            log.info("Bouton « Partie privée créée » pas grisé : %s", erreur)
        await interaction.followup.send(reponse, ephemeral=True)


def vue_pp_creee(tournoi_id: str, numero: int, zone: int) -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(BoutonPartieCreee(tournoi_id, numero, zone))
    return vue


def vue_pp_deja_creee() -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(ui.Button(label="Partie privée créée", emoji="✅", style=discord.ButtonStyle.secondary,
                           custom_id="rlpp:fait", disabled=True))
    return vue


# --------------------------------------------------------------------------- #
# « Valider ma participation » (/start_tournament_init)
# --------------------------------------------------------------------------- #

MODELE_ID_CONFIRMATION = r"rlconf:(?P<tournoi>\d+):(?P<equipe>\d+)"


def custom_id_confirmation(tournoi_id: str, equipe_id: int) -> str:
    return f"rlconf:{tournoi_id}:{equipe_id}"


class BoutonConfirmation(ui.DynamicItem[ui.Button], template=MODELE_ID_CONFIRMATION):
    def __init__(self, tournoi_id: str, equipe_id: int) -> None:
        super().__init__(ui.Button(label="Valider ma participation", emoji="✅", style=discord.ButtonStyle.success,
                                   custom_id=custom_id_confirmation(tournoi_id, equipe_id)))
        self.tournoi_id, self.equipe_id = tournoi_id, equipe_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: ui.Button, match: re.Match[str], /):
        return cls(match["tournoi"], int(match["equipe"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        gestionnaire = interaction.client.gestionnaire  # type: ignore[attr-defined]
        try:
            reponse = await gestionnaire.valider_participation(self.tournoi_id, self.equipe_id,
                                                               par=str(interaction.user.id))
        except L.ErreurTournoi as erreur:
            reponse = f"❌ {erreur}"
        await interaction.followup.send(reponse, ephemeral=True)


def vue_confirmation(tournoi_id: str, equipe_id: int) -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(BoutonConfirmation(tournoi_id, equipe_id))
    return vue
