"""Commandes slash : /tournoi_rl, /tournoi_rl_modify, /tournoi_rl_status, /tournoi_rl_remove_team, /tournoi_rl_remove."""

from __future__ import annotations

import logging

import discord
from discord import app_commands, ui

from . import logique as L
from .embeds import embed_annonce, embeds_status
from .inscription import (apres_annulation, envoyer_mp, maintenant, mettre_a_jour_annonce, prevenir_promues,
                          repondre, stockage, supprimer_annonce, vue_annonce)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Autocomplétion
# --------------------------------------------------------------------------- #

async def autocomplete_tournoi(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[str]]:
    choix = []
    for tournoi in stockage(interaction).lister(str(interaction.guild_id)):
        nom = f"{tournoi['titre']} — {tournoi['date']} ({tournoi['id']})"
        if actuel.lower() in nom.lower():
            choix.append(app_commands.Choice(name=nom[:100], value=tournoi["id"]))
        if len(choix) == 25:
            break
    return choix


async def autocomplete_equipe(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[int]]:
    tournoi_id = getattr(interaction.namespace, "id", None)
    tournoi = stockage(interaction).charger(str(tournoi_id)) if tournoi_id else None
    if tournoi is None:
        return []
    choix = []
    for equipe in sorted(L.equipes_actives(tournoi), key=lambda e: e["id"]):
        etat = "inscrite" if equipe["statut"] == L.INSCRITE else "liste d'attente"
        nom = f"#{equipe['id']} {equipe['nom']} ({etat})"
        if actuel.lower() in nom.lower():
            choix.append(app_commands.Choice(name=nom[:100], value=equipe["id"]))
    return choix[:25]


def tournoi_du_serveur(interaction: discord.Interaction, tournoi_id: str) -> dict | None:
    tournoi = stockage(interaction).charger(tournoi_id.strip())
    if tournoi is None or tournoi["serveur_id"] != str(interaction.guild_id):
        return None
    return tournoi


# --------------------------------------------------------------------------- #
# /tournoi_rl
# --------------------------------------------------------------------------- #

@app_commands.command(name="tournoi_rl", description="Crée l'annonce d'un tournoi Rocket League")
@app_commands.describe(
    titre="Titre du tournoi",
    cashprize="Cashprize (ex : 100€)",
    joueurs_par_equipe="Nombre de joueurs par équipe (1 à 3)",
    equipes_max="Nombre maximum d'équipes",
    date="Date du tournoi (ex : 6 septembre)",
)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def tournoi_rl(
    interaction: discord.Interaction,
    titre: app_commands.Range[str, 1, L.LONGUEUR_MAX_TITRE],
    cashprize: app_commands.Range[str, 1, L.LONGUEUR_MAX_CASHPRIZE],
    joueurs_par_equipe: app_commands.Range[int, 1, 3],
    equipes_max: app_commands.Range[int, 1, L.EQUIPES_MAX_LIMITE],
    date: app_commands.Range[str, 1, 100],
) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    tournoi = L.nouveau_tournoi(
        tournoi_id=str(interaction.id),
        titre=titre, cashprize=cashprize, joueurs_par_equipe=joueurs_par_equipe,
        equipes_max=equipes_max, date=date,
        serveur_id=str(interaction.guild_id), salon_id=str(interaction.channel_id),
        cree_par=str(interaction.user.id), maintenant=maintenant(),
    )
    try:
        message = await interaction.channel.send(  # type: ignore[union-attr]
            embed=embed_annonce(tournoi), view=vue_annonce(tournoi))
    except discord.HTTPException:
        return await repondre(interaction, "❌ Je n'ai pas la permission d'envoyer des messages dans ce salon.")

    tournoi["message_id"] = str(message.id)
    stockage(interaction).sauvegarder(tournoi)
    await repondre(interaction, f"✅ Tournoi **{titre}** créé. ID : `{tournoi['id']}`")


# --------------------------------------------------------------------------- #
# /tournoi_rl_modify
# --------------------------------------------------------------------------- #

LIMITE_LISTE_PROMUES = 1000  # au-delà, on donne seulement le nombre (Discord : 2000 caractères par message)


def texte_modification(tournoi: dict, changements: list, promues: list[dict], annonce_ok: bool) -> str:
    lignes = [f"✅ Tournoi **{tournoi['titre']}** modifié :"]
    for champ, ancienne, nouvelle in changements:
        ligne = f"• {L.CHAMPS_MODIFIABLES[champ]} : {ancienne} → **{nouvelle}**"
        if champ == "equipes_max":
            ligne += f" (liste d'attente max : **{tournoi['liste_attente_max']}**)"
        lignes.append(ligne)
    if promues:
        noms = ", ".join(f"`#{e['id']}` **{e['nom']}**" for e in promues)
        if len(noms) > LIMITE_LISTE_PROMUES:
            noms = f"{len(promues)} équipes (détail dans `/tournoi_rl_status`)"
        lignes.append(f"🎉 Promue(s) depuis la liste d'attente (joueurs prévenus en MP) : {noms}")
    if not annonce_ok:
        lignes.append("⚠️ Modification enregistrée, mais l'annonce n'a pas pu être mise à jour "
                      "(message supprimé ou salon inaccessible).")
    return "\n".join(lignes)


@app_commands.command(name="tournoi_rl_modify",
                      description="Modifie le titre, le cashprize ou le nombre maximum d'équipes d'un tournoi")
@app_commands.rename(tournoi_id="id")
@app_commands.describe(
    tournoi_id="ID du tournoi",
    titre="Nouveau titre (vide = inchangé)",
    cashprize="Nouveau cashprize (vide = inchangé)",
    equipes_max="Nouveau nombre maximum d'équipes (vide = inchangé)",
)
@app_commands.autocomplete(tournoi_id=autocomplete_tournoi)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def tournoi_rl_modify(
    interaction: discord.Interaction,
    tournoi_id: str,
    titre: app_commands.Range[str, 1, L.LONGUEUR_MAX_TITRE] | None = None,
    cashprize: app_commands.Range[str, 1, L.LONGUEUR_MAX_CASHPRIZE] | None = None,
    equipes_max: app_commands.Range[int, 1, L.EQUIPES_MAX_LIMITE] | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    st = stockage(interaction)
    tournoi_id = tournoi_id.strip()
    async with st.verrou(tournoi_id):
        tournoi = tournoi_du_serveur(interaction, tournoi_id)
        if tournoi is None:
            return await repondre(interaction, f"❌ Aucun tournoi avec l'ID `{tournoi_id}` sur ce serveur.")
        try:
            changements, promues = L.modifier_tournoi(
                tournoi, titre=titre, cashprize=cashprize, equipes_max=equipes_max)
        except L.ErreurTournoi as erreur:
            return await repondre(interaction, f"❌ {erreur}")
        if not changements:
            return await repondre(interaction, "ℹ️ Rien à modifier : ces valeurs sont déjà celles du tournoi.")
        st.sauvegarder(tournoi)

    log.info("Tournoi %s modifié par %s : %s", tournoi["id"], interaction.user.id,
             ", ".join(f"{c}: {a!r} -> {n!r}" for c, a, n in changements))
    # Hors du verrou : mettre_a_jour_annonce le reprend (il n'est pas réentrant).
    annonce_ok = await mettre_a_jour_annonce(interaction.client, tournoi["id"])
    await prevenir_promues(interaction.client, tournoi, promues, "De nouvelles places ont été ouvertes")
    await repondre(interaction, texte_modification(tournoi, changements, promues, annonce_ok))


# --------------------------------------------------------------------------- #
# /tournoi_rl_status
# --------------------------------------------------------------------------- #

@app_commands.command(name="tournoi_rl_status", description="Affiche les équipes inscrites et la liste d'attente d'un tournoi")
@app_commands.rename(tournoi_id="id")
@app_commands.describe(tournoi_id="ID du tournoi")
@app_commands.autocomplete(tournoi_id=autocomplete_tournoi)
@app_commands.guild_only()
async def tournoi_rl_status(interaction: discord.Interaction, tournoi_id: str) -> None:
    tournoi = tournoi_du_serveur(interaction, tournoi_id)
    if tournoi is None:
        return await repondre(interaction, f"❌ Aucun tournoi avec l'ID `{tournoi_id}` sur ce serveur.")
    # Un embed par message : Discord limite à 6000 caractères par message.
    for embed in embeds_status(tournoi):
        await repondre(interaction, None, embed=embed)


# --------------------------------------------------------------------------- #
# /tournoi_rl_remove_team
# --------------------------------------------------------------------------- #

@app_commands.command(name="tournoi_rl_remove_team", description="Retire une équipe d'un tournoi et fait avancer la liste d'attente")
@app_commands.rename(tournoi_id="id")
@app_commands.describe(tournoi_id="ID du tournoi", team_id="Numéro de l'équipe (#n dans /tournoi_rl_status)")
@app_commands.autocomplete(tournoi_id=autocomplete_tournoi, team_id=autocomplete_equipe)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def tournoi_rl_remove_team(interaction: discord.Interaction, tournoi_id: str, team_id: int) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    st = stockage(interaction)
    tournoi_id = tournoi_id.strip()
    async with st.verrou(tournoi_id):
        tournoi = tournoi_du_serveur(interaction, tournoi_id)
        if tournoi is None:
            return await repondre(interaction, f"❌ Aucun tournoi avec l'ID `{tournoi_id}` sur ce serveur.")
        try:
            equipe, promues = L.annuler_equipe(
                tournoi, team_id, f"retirée par {interaction.user.display_name}", maintenant())
        except L.ErreurTournoi as erreur:
            return await repondre(interaction, f"❌ {erreur}")
        st.sauvegarder(tournoi)

    await apres_annulation(
        interaction.client, tournoi, equipe, promues,
        f"🚫 Ton équipe **{equipe['nom']}** a été retirée du tournoi **{tournoi['titre']}** par un admin.",
    )
    texte = f"✅ Équipe `#{equipe['id']}` **{equipe['nom']}** retirée du tournoi **{tournoi['titre']}**."
    if promues:
        texte += "\n🎉 Promue(s) depuis la liste d'attente : " + ", ".join(
            f"`#{e['id']}` **{e['nom']}**" for e in promues)
    await repondre(interaction, texte)


# --------------------------------------------------------------------------- #
# /tournoi_rl_remove
# --------------------------------------------------------------------------- #

@app_commands.command(name="tournoi_rl_remove", description="Annule et efface un tournoi (annonce, inscriptions et fichier)")
@app_commands.rename(tournoi_id="id")
@app_commands.describe(tournoi_id="ID du tournoi")
@app_commands.autocomplete(tournoi_id=autocomplete_tournoi)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def tournoi_rl_remove(interaction: discord.Interaction, tournoi_id: str) -> None:
    tournoi = tournoi_du_serveur(interaction, tournoi_id)
    if tournoi is None:
        return await repondre(interaction, f"❌ Aucun tournoi avec l'ID `{tournoi_id}` sur ce serveur.")
    nb_equipes = len(L.equipes_actives(tournoi))
    await repondre(
        interaction,
        f"⚠️ Annuler et **effacer** le tournoi **{tournoi['titre']}** ({tournoi['date']}) ?\n"
        f"L'annonce sera supprimée, les joueurs des {nb_equipes} équipe(s) seront prévenus en MP "
        f"et le fichier du tournoi sera effacé. **C'est définitif.**",
        view=ConfirmationSuppression(tournoi["id"]),
    )


class ConfirmationSuppression(ui.View):
    def __init__(self, tournoi_id: str) -> None:
        super().__init__(timeout=120)
        self.tournoi_id = tournoi_id

    @ui.button(label="Oui, effacer le tournoi", style=discord.ButtonStyle.danger)
    async def confirmer(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        st = stockage(interaction)
        async with st.verrou(self.tournoi_id):
            tournoi = tournoi_du_serveur(interaction, self.tournoi_id)
            if tournoi is None:
                return await interaction.response.edit_message(content="❌ Ce tournoi n'existe déjà plus.", view=None)
            st.supprimer(self.tournoi_id)

        await interaction.response.edit_message(
            content=f"🛑 Tournoi **{tournoi['titre']}** annulé et effacé.", view=None)
        await supprimer_annonce(interaction.client, tournoi)
        for equipe in L.equipes_actives(tournoi):
            for joueur in equipe["joueurs"]:
                await envoyer_mp(
                    interaction.client, joueur["id"],
                    f"🛑 Le tournoi **{tournoi['titre']}** ({tournoi['date']}) a été annulé par un admin. "
                    f"L'inscription de ton équipe **{equipe['nom']}** est annulée.",
                )

    @ui.button(label="Non", style=discord.ButtonStyle.secondary)
    async def garder(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        await interaction.response.edit_message(content="👍 Tournoi conservé.", view=None)


COMMANDES = [tournoi_rl, tournoi_rl_modify, tournoi_rl_status, tournoi_rl_remove_team, tournoi_rl_remove]


async def gerer_erreur(interaction: discord.Interaction, erreur: app_commands.AppCommandError) -> None:
    log.exception("Erreur dans une commande", exc_info=erreur)
    try:
        await repondre(interaction, "❌ Une erreur inattendue est survenue.")
    except discord.HTTPException:
        pass
