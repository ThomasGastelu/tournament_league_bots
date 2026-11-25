"""Commandes slash : /start_tournament_init, /start_tournament_init_status, /start_tournament_rl,
/start_tournament_rl_status, /start_tournament_modify_pp, /stop_tournament_rl, /reset_tournament_rl, /set_result_tournament_rl
et /edit_player_tournament_rl."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands, ui

from . import logique as L
from . import messages as M
from .deroulement import (PERMISSIONS_SALON, categorie_du_tournoi, manques_discussion, permissions_manquantes,
                          qui_retire)
from .messages import STATUTS_TOURNOI, embeds_status

if TYPE_CHECKING:
    from .deroulement import GestionnaireTournois

log = logging.getLogger(__name__)


def gestionnaire(interaction: discord.Interaction) -> GestionnaireTournois:
    return interaction.client.gestionnaire  # type: ignore[attr-defined]


async def repondre(interaction: discord.Interaction, texte: str | None, **kwargs) -> None:
    """Répond en privé (éphémère), que l'interaction ait déjà été différée ou non."""
    if interaction.response.is_done():
        await interaction.followup.send(texte, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(texte, ephemeral=True, **kwargs)


# --------------------------------------------------------------------------- #
# Autocomplétion
# --------------------------------------------------------------------------- #

def _filtrer(choix: list[app_commands.Choice], actuel: str) -> list[app_commands.Choice]:
    return [c for c in choix if actuel.lower() in c.name.lower()][:25]


async def autocomplete_inscription(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[str]]:
    """Tournois d'inscription du serveur qui ne sont pas déjà en cours."""
    g = gestionnaire(interaction)
    try:
        await g.stockage.rafraichir_inscriptions(str(interaction.guild_id))  # mode API : relit la liste
    except L.ErreurTournoi as erreur:
        log.warning("Autocomplétion : liste des tournois indisponible (%s)", erreur)
        return []
    choix = []
    for tournoi in g.stockage.lister_inscriptions(str(interaction.guild_id))[:100]:
        etat = g.stockage.charger_etat(tournoi["id"])
        if etat and etat["statut"] == L.EN_COURS:
            continue
        if "equipes" in tournoi:
            nb = sum(1 for e in tournoi["equipes"] if e.get("statut") == L.INSCRITE)
            nom = f"{tournoi['titre']} — {tournoi.get('date', '?')} — {nb} équipes ({tournoi['id']})"
        else:  # mode API : la liste ne donne pas les équipes
            nom = f"{tournoi['titre']} — {tournoi.get('date') or '?'} ({tournoi['id']})"
        choix.append(app_commands.Choice(name=nom[:100], value=tournoi["id"]))
    return _filtrer(choix, actuel)


async def _choix_etats(interaction: discord.Interaction, actuel: str, en_cours_seulement: bool):
    choix = []
    for etat in gestionnaire(interaction).stockage.lister_etats(str(interaction.guild_id)):
        if en_cours_seulement and etat["statut"] != L.EN_COURS:
            continue
        nom = f"{etat['titre']} — {STATUTS_TOURNOI.get(etat['statut'], etat['statut'])} ({etat['tournoi_id']})"
        choix.append(app_commands.Choice(name=nom[:100], value=etat["tournoi_id"]))
    return _filtrer(choix, actuel)


async def autocomplete_etat(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[str]]:
    return await _choix_etats(interaction, actuel, en_cours_seulement=False)


async def autocomplete_etat_en_cours(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[str]]:
    return await _choix_etats(interaction, actuel, en_cours_seulement=True)


def _ronde_en_cours(interaction: discord.Interaction) -> tuple[dict, dict] | tuple[None, None]:
    tournoi_id = getattr(interaction.namespace, "id_tournoi", None)
    etat = gestionnaire(interaction).stockage.charger_etat(str(tournoi_id)) if tournoi_id else None
    if etat is None or etat.get("serveur_id") != str(interaction.guild_id):
        return None, None
    ronde = L.ronde_actuelle(etat)
    if ronde is None or ronde["statut"] != L.RONDE_EN_COURS:
        return None, None
    return etat, ronde


async def autocomplete_zone(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[int]]:
    etat, ronde = _ronde_en_cours(interaction)
    if etat is None:
        return []
    noms_statut = {L.MATCH_A_VALIDER: "⚠️ à valider", L.MATCH_EN_COURS: "en cours", L.MATCH_EN_ATTENTE: "en attente"}
    choix = []
    for match in sorted(ronde["matchs"], key=lambda m: m["zone"]):
        if match["statut"] in noms_statut:
            nom = (f"Zone {match['zone']} — {L.equipe(etat, match['equipe_a'])['nom']} vs "
                   f"{L.equipe(etat, match['equipe_b'])['nom']} ({noms_statut[match['statut']]})")
            choix.append(app_commands.Choice(name=nom[:100], value=match["zone"]))
    return _filtrer(choix, actuel)


async def autocomplete_joueur(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[str]]:
    """Joueurs du tournoi choisi : « Équipe — pseudo 👑 (en jeu : …) »."""
    tournoi_id = getattr(interaction.namespace, "id_tournoi", None)
    etat = gestionnaire(interaction).stockage.charger_etat(str(tournoi_id).strip()) if tournoi_id else None
    if etat is None or etat.get("serveur_id") != str(interaction.guild_id):
        return []
    choix = []
    for e, joueur in L.joueurs(etat):
        capitaine = " 👑" if joueur["id"] == e["capitaine_id"] else ""
        nom = f"{e['nom']} — {joueur['pseudo']}{capitaine} (en jeu : {joueur.get('pseudo_jeu') or '?'})"
        choix.append(app_commands.Choice(name=nom[:100], value=joueur["id"]))
    return _filtrer(choix, actuel)


async def autocomplete_gagnant(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[int]]:
    etat, ronde = _ronde_en_cours(interaction)
    zone = getattr(interaction.namespace, "zone", None)
    if etat is None or zone is None:
        return []
    try:
        match = L.trouver_match(ronde, int(zone))
    except (L.ErreurTournoi, ValueError):
        return []
    choix = [app_commands.Choice(name=f"#{i} {L.equipe(etat, i)['nom']}"[:100], value=i)
             for i in (match["equipe_a"], match["equipe_b"])]
    return _filtrer(choix, actuel)


# --------------------------------------------------------------------------- #
# /start_tournament_rl
# --------------------------------------------------------------------------- #

async def relire_inscription(interaction: discord.Interaction, tournoi_id: str) -> str | None:
    """Mode API : relit l'inscription du tournoi dans l'API (rien en mode fichiers).
    Renvoie le message d'erreur à montrer si l'API ne répond pas."""
    try:
        await gestionnaire(interaction).stockage.rafraichir_inscription(str(tournoi_id).strip())
    except L.ErreurTournoi as erreur:
        log.warning("Inscription du tournoi %s illisible dans l'API : %s", tournoi_id, erreur)
        return f"❌ {erreur}"
    return None


def probleme_salon(interaction: discord.Interaction, tournoi_id: str) -> str | None:
    """Message d'erreur si le bot ne peut pas poster les annonces du tournoi
    (dans SALON_ANNONCES, ou à défaut dans le salon du tournoi)."""
    g = gestionnaire(interaction)
    tournoi = g.stockage.charger_inscription(tournoi_id)
    if interaction.guild is None or tournoi is None:
        return None  # demarrer() explique le problème
    try:
        salon_id = g.messagerie.salon_id(tournoi)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    salon = interaction.guild.get_channel_or_thread(salon_id)
    if salon is None:
        if getattr(g.messagerie, "salon_annonces", None):
            return (f"❌ Le salon des annonces (`SALON_ANNONCES={salon_id}` dans le `.env`) n'existe pas sur ce "
                    "serveur. Copie le bon identifiant (clic droit sur le salon > **Copier l'identifiant**), "
                    "mets-le dans le `.env`, puis relance le bot.")
        return None
    manquantes = permissions_manquantes(salon)
    if not manquantes:
        return None
    return (f"❌ Je ne peux pas poster les annonces du tournoi dans {salon.mention} : "  # type: ignore[union-attr]
            f"il me manque **{', '.join(manquantes)}**.\n"
            f"Clic droit sur le salon > **Modifier le salon** > **Permissions** > ajoute le rôle "
            f"**{interaction.client.user.name}** et autorise : {', '.join(PERMISSIONS_SALON.values())}. "
            "Puis relance la commande.")


def probleme_salon_discussion(interaction: discord.Interaction, tournoi_id: str) -> str | None:
    """Message d'erreur si le bot ne peut pas créer le salon de discussion du tournoi
    (dans la catégorie du salon où le tournoi a été créé)."""
    tournoi = gestionnaire(interaction).stockage.charger_inscription(tournoi_id)
    serveur = interaction.guild
    if serveur is None or tournoi is None:
        return None  # demarrer() explique le problème
    categorie = categorie_du_tournoi(serveur, tournoi)
    absentes, retirees = manques_discussion(serveur, categorie)
    if not absentes and not retirees:
        return None
    nom_bot = interaction.client.user.name
    lignes = []
    if absentes:  # le rôle du bot ne les a pas sur le serveur
        lignes += [
            f"❌ Je ne peux pas créer le salon de discussion du tournoi : sur le serveur, mon rôle n'a pas "
            f"**{', '.join(absentes)}**.",
            f"Paramètres du serveur > **Rôles** > **{nom_bot}** : autorise {', '.join(absentes)}.",
        ]
        lien = getattr(interaction.client, "lien_invitation", None)
        if callable(lien):
            lignes.append(f"Ou réinvite le bot avec ce lien, qui contient toutes ses permissions : <{lien()}>")
    if retirees:  # le serveur les donne, mais la catégorie les enlève
        par = qui_retire(categorie, serveur.me, retirees)
        debut = "Et " if absentes else "❌ Je ne peux pas créer le salon de discussion du tournoi : "
        lignes += [
            f"{debut}la catégorie **{categorie.name}** me retire **{', '.join(retirees)}**"
            + (f" (elle les refuse à {', '.join(f'« {p} »' for p in par)})" if par else "") + ".",
            f"Clic droit sur la catégorie > **Modifier la catégorie** > **Permissions** > rôle **{nom_bot}** "
            f"(ajoute-le avec ➕ s'il n'est pas dans la liste) > mets en ✅ vert : {', '.join(retirees)} > "
            "**Enregistrer les modifications**.",
            "Seul le bot reçoit ces droits : les autres membres restent bloqués dans cette catégorie.",
        ]
    lignes.append("Puis relance la commande.")
    return "\n".join(lignes)


@app_commands.command(name="start_tournament_init",
                      description="Crée le salon du tournoi (joueurs + admins) et prévient les joueurs avant le lancement")
@app_commands.describe(
    id_tournoi="ID du tournoi (fichier d'inscription)",
    delai_confirmation="Minutes laissées aux équipes pour valider leur participation (sinon la liste d'attente prend leur place)",
)
@app_commands.autocomplete(id_tournoi=autocomplete_inscription)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def start_tournament_init(interaction: discord.Interaction, id_tournoi: str,
                                delai_confirmation: app_commands.Range[int, 1, 1440]) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    probleme = await relire_inscription(interaction, id_tournoi) or probleme_salon_discussion(interaction, id_tournoi)
    if probleme:
        log.info("/start_tournament_init %s refusé (demandé par %s) : permissions du bot", id_tournoi,
                 interaction.user)
        return await repondre(interaction, probleme)
    try:
        init = await gestionnaire(interaction).initialiser(
            id_tournoi, serveur_id=str(interaction.guild_id), par=str(interaction.user.id),
            delai_confirmation=delai_confirmation)
    except L.ErreurTournoi as erreur:
        log.info("/start_tournament_init %s refusé (demandé par %s) : %s", id_tournoi, interaction.user, erreur)
        return await repondre(interaction, f"❌ {erreur}")
    await repondre(
        interaction,
        f"✅ Salon du tournoi **{discord.utils.escape_markdown(init['titre'])}** créé : "
        f"<#{init['salon_discussion_id']}> ({len(init['equipes'])} équipes + les admins). Les joueurs y sont "
        f"prévenus que le tournoi va bientôt commencer.\n"
        f"📝 Les joueurs ont reçu en MP le bouton « Valider ma participation » : ils ont "
        f"**{delai_confirmation} min** (jusqu'à {M.heure_discord(init['confirmation']['fin'])}). "
        f"{len(init['confirmation']['attente'])} équipe(s) en liste d'attente prévenue(s) en MP.\n"
        f"Après le délai, lance le tournoi : `/start_tournament_rl id_tournoi:{init['tournoi_id']} nombre_de_matchs:…`",
    )


@app_commands.command(name="start_tournament_rl", description="Lance un tournoi Rocket League (zones qui montent/descendent)")
@app_commands.describe(
    id_tournoi="ID du tournoi (fichier d'inscription)",
    nombre_de_matchs="Nombre de matchs joués par chaque équipe (= nombre de rounds)",
    golden_round="Round à partir duquel la victoire en zone haute rapporte +3, avant : +1 (par défaut : 1)",
)
@app_commands.autocomplete(id_tournoi=autocomplete_inscription)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def start_tournament_rl(interaction: discord.Interaction, id_tournoi: str,
                              nombre_de_matchs: app_commands.Range[int, 1, 50],
                              golden_round: app_commands.Range[int, 1, 50] = 1) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    probleme = await relire_inscription(interaction, id_tournoi) or probleme_salon(interaction, id_tournoi)
    if probleme:
        log.info("/start_tournament_rl %s refusé (demandé par %s) : permissions du bot", id_tournoi, interaction.user)
        return await repondre(interaction, probleme)
    try:
        etat = await gestionnaire(interaction).demarrer(
            id_tournoi, nombre_de_matchs, serveur_id=str(interaction.guild_id), lance_par=str(interaction.user.id),
            golden_round=golden_round)
    except L.ErreurTournoi as erreur:
        log.info("/start_tournament_rl %s refusé (demandé par %s) : %s", id_tournoi, interaction.user, erreur)
        return await repondre(interaction, f"❌ {erreur}")
    log.info("Tournoi %s « %s » lancé par %s : %s équipes, %s zone(s), %s round(s)", etat["tournoi_id"],
             etat["titre"], interaction.user, len(etat["equipes"]), etat["nb_zones"], etat["nombre_de_rondes"])
    if etat.get("salon_discussion_id"):
        discussion = f"💬 Salon de discussion (joueurs + admins) : <#{etat['salon_discussion_id']}>\n"
    else:
        discussion = ""
    await repondre(
        interaction,
        f"✅ Tournoi **{discord.utils.escape_markdown(etat['titre'])}** lancé : {len(etat['equipes'])} équipes, "
        f"{etat['nb_zones']} zone(s), {etat['nombre_de_rondes']} round(s).\n"
        f"{M.ligne_points(etat)}\n"
        f"Les capitaines reçoivent les infos de partie privée en MP, les annonces sont postées dans "
        f"<#{gestionnaire(interaction).messagerie.salon_id(etat)}>.\n"
        f"{discussion}"
        f"Suivi : `/start_tournament_rl_status id_tournoi:{etat['tournoi_id']}`",
    )


# --------------------------------------------------------------------------- #
# /start_tournament_init_status
# --------------------------------------------------------------------------- #

async def autocomplete_init(interaction: discord.Interaction, actuel: str) -> list[app_commands.Choice[str]]:
    """Tournois du serveur qui ont eu un /start_tournament_init."""
    choix = []
    for init in gestionnaire(interaction).stockage.lister_inits(str(interaction.guild_id)):
        if L.confirmation_en_cours(init):
            statut = "validation en cours"
        elif init.get("confirmation"):
            statut = "validation terminée"
        else:
            statut = "sans validation"
        nom = f"{init['titre']} — {statut} ({init['tournoi_id']})"
        choix.append(app_commands.Choice(name=nom[:100], value=init["tournoi_id"]))
    return _filtrer(choix, actuel)


@app_commands.command(name="start_tournament_init_status",
                      description="Affiche les équipes avant le tournoi : validations, liste d'attente, places perdues")
@app_commands.describe(id_tournoi="ID du tournoi")
@app_commands.autocomplete(id_tournoi=autocomplete_init)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def start_tournament_init_status(interaction: discord.Interaction, id_tournoi: str) -> None:
    g = gestionnaire(interaction)
    tournoi_id = id_tournoi.strip()
    init = g.stockage.charger_init(tournoi_id)
    if init is None or init.get("serveur_id") != str(interaction.guild_id):
        return await repondre(interaction, f"❌ Pas de `/start_tournament_init` pour le tournoi `{tournoi_id}` "
                                           "sur ce serveur.")
    await relire_inscription(interaction, tournoi_id)  # sans l'API, le bilan se fait sans l'inscription
    bilan = L.bilan_validations(init, g.stockage.charger_inscription(tournoi_id))
    await repondre(interaction, None, embeds=M.embeds_init_status(init, bilan, g.stockage.charger_etat(tournoi_id)))


# --------------------------------------------------------------------------- #
# /start_tournament_rl_status
# --------------------------------------------------------------------------- #

@app_commands.command(name="start_tournament_rl_status", description="Affiche les zones, les scores et le classement d'un tournoi")
@app_commands.describe(id_tournoi="ID du tournoi")
@app_commands.autocomplete(id_tournoi=autocomplete_etat)
@app_commands.guild_only()
async def start_tournament_rl_status(interaction: discord.Interaction, id_tournoi: str) -> None:
    etat = gestionnaire(interaction).stockage.charger_etat(id_tournoi.strip())
    if etat is None or etat.get("serveur_id") != str(interaction.guild_id):
        return await repondre(interaction, f"❌ Aucun tournoi lancé avec l'ID `{id_tournoi}` sur ce serveur.")
    await repondre(interaction, None, embeds=embeds_status(etat))


# --------------------------------------------------------------------------- #
# /stop_tournament_rl
# --------------------------------------------------------------------------- #

@app_commands.command(name="stop_tournament_rl", description="Arrête un tournoi en cours")
@app_commands.describe(id_tournoi="ID du tournoi")
@app_commands.autocomplete(id_tournoi=autocomplete_etat_en_cours)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def stop_tournament_rl(interaction: discord.Interaction, id_tournoi: str) -> None:
    etat = gestionnaire(interaction).stockage.charger_etat(id_tournoi.strip())
    if etat is None or etat.get("serveur_id") != str(interaction.guild_id) or etat["statut"] != L.EN_COURS:
        return await repondre(interaction, f"❌ Aucun tournoi en cours avec l'ID `{id_tournoi}` sur ce serveur.")
    await repondre(
        interaction,
        f"⚠️ Arrêter le tournoi **{discord.utils.escape_markdown(etat['titre'])}** ? "
        f"Les matchs en cours sont annulés et les joueurs sont prévenus en MP. "
        f"Les résultats déjà joués restent dans le fichier. **On ne peut pas le reprendre ensuite.**",
        view=ConfirmationArret(etat["tournoi_id"]),
    )


class ConfirmationArret(ui.View):
    def __init__(self, tournoi_id: str) -> None:
        super().__init__(timeout=120)
        self.tournoi_id = tournoi_id

    @ui.button(label="Oui, arrêter le tournoi", style=discord.ButtonStyle.danger)
    async def confirmer(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        await interaction.response.edit_message(content="⏳ Arrêt du tournoi…", view=None)
        try:
            etat = await gestionnaire(interaction).arreter(
                self.tournoi_id, serveur_id=str(interaction.guild_id), par=str(interaction.user.id))
        except L.ErreurTournoi as erreur:
            return await interaction.edit_original_response(content=f"❌ {erreur}")
        await interaction.edit_original_response(
            content=f"🛑 Tournoi **{discord.utils.escape_markdown(etat['titre'])}** arrêté.")

    @ui.button(label="Non", style=discord.ButtonStyle.secondary)
    async def garder(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        await interaction.response.edit_message(content="👍 Le tournoi continue.", view=None)


# --------------------------------------------------------------------------- #
# /reset_tournament_rl
# --------------------------------------------------------------------------- #

@app_commands.command(name="reset_tournament_rl",
                      description="Remet un tournoi à zéro : efface ses scores et son état pour le relancer")
@app_commands.describe(
    id_tournoi="ID du tournoi",
    garder_salon="True : garde le salon de discussion (par défaut il est supprimé)",
)
@app_commands.autocomplete(id_tournoi=autocomplete_etat)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def reset_tournament_rl(interaction: discord.Interaction, id_tournoi: str, garder_salon: bool = False) -> None:
    tournoi_id = id_tournoi.strip()
    try:
        etat, salons, fichiers = gestionnaire(interaction).a_reinitialiser(tournoi_id, str(interaction.guild_id))
    except L.ErreurTournoi as erreur:
        return await repondre(interaction, f"❌ {erreur}")
    await repondre(interaction, M.confirmation_reinitialisation(etat, len(fichiers), len(salons), garder_salon),
                   view=ConfirmationReinitialisation(tournoi_id, garder_salon))


class ConfirmationReinitialisation(ui.View):
    def __init__(self, tournoi_id: str, garder_salon: bool) -> None:
        super().__init__(timeout=120)
        self.tournoi_id = tournoi_id
        self.garder_salon = garder_salon

    @ui.button(label="Oui, tout effacer", style=discord.ButtonStyle.danger)
    async def confirmer(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        await interaction.response.edit_message(content="⏳ Remise à zéro du tournoi…", view=None)
        try:
            bilan = await gestionnaire(interaction).reinitialiser(
                self.tournoi_id, serveur_id=str(interaction.guild_id), par=str(interaction.user.id),
                garder_salon=self.garder_salon)
        except L.ErreurTournoi as erreur:
            return await interaction.edit_original_response(content=f"❌ {erreur}")
        log.info("/reset_tournament_rl %s fait par %s", self.tournoi_id, interaction.user)
        texte = M.reponse_reinitialisation(bilan)
        try:
            await interaction.edit_original_response(content=texte)
        except discord.HTTPException:  # commande tapée dans le salon qui vient d'être supprimé
            await interaction.followup.send(texte, ephemeral=True)

    @ui.button(label="Non", style=discord.ButtonStyle.secondary)
    async def garder(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        await interaction.response.edit_message(content="👍 Rien n'a été effacé.", view=None)


# --------------------------------------------------------------------------- #
# /set_result_tournament_rl
# --------------------------------------------------------------------------- #

@app_commands.command(name="start_tournament_modify_pp",
                      description="Change le nom et le mot de passe de la partie privée d'une zone (round en cours)")
@app_commands.describe(
    id_tournoi="ID du tournoi",
    zone="Zone du match (round en cours)",
    nom="Nouveau nom de la partie privée",
    mot_de_passe="Nouveau mot de passe (vide : le même que le nom)",
)
@app_commands.autocomplete(id_tournoi=autocomplete_etat_en_cours, zone=autocomplete_zone)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def start_tournament_modify_pp(interaction: discord.Interaction, id_tournoi: str, zone: int,
                                     nom: app_commands.Range[str, 1, L.LONGUEUR_MAX_PP],
                                     mot_de_passe: app_commands.Range[str, 1, L.LONGUEUR_MAX_PP] | None = None
                                     ) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        etat, match = await gestionnaire(interaction).modifier_pp(
            id_tournoi, zone, nom, mot_de_passe, serveur_id=str(interaction.guild_id), par=str(interaction.user.id))
    except L.ErreurTournoi as erreur:
        return await repondre(interaction, f"❌ {erreur}")
    if match.get("pp_creee_le"):
        qui = "Tous les joueurs du match ont reçu la nouvelle partie en MP."
    else:
        qui = ("Le capitaine a reçu la nouvelle partie à créer ; les autres joueurs la recevront quand il aura "
               "cliqué sur « Partie privée créée ».")
    await repondre(interaction, f"✅ Zone {match['zone']} : nouvelle partie privée `{match['pp']['nom']}` "
                                f"(mot de passe `{match['pp']['mot_de_passe']}`). {qui}")


@app_commands.command(name="set_result_tournament_rl", description="Valide à la main le résultat d'un match (match sans vainqueur, bloqué…)")
@app_commands.describe(
    id_tournoi="ID du tournoi",
    zone="Zone du match (round en cours)",
    gagnant="Équipe gagnante",
    score_gagnant="Buts de l'équipe gagnante",
    score_perdant="Buts de l'équipe perdante",
)
@app_commands.autocomplete(id_tournoi=autocomplete_etat_en_cours, zone=autocomplete_zone, gagnant=autocomplete_gagnant)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def set_result_tournament_rl(interaction: discord.Interaction, id_tournoi: str, zone: int, gagnant: int,
                                   score_gagnant: app_commands.Range[int, 0, 99],
                                   score_perdant: app_commands.Range[int, 0, 99]) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        etat, match = await gestionnaire(interaction).valider_resultat(
            id_tournoi, zone, gagnant, score_gagnant, score_perdant,
            serveur_id=str(interaction.guild_id), par=str(interaction.user.id))
    except L.ErreurTournoi as erreur:
        return await repondre(interaction, f"❌ {erreur}")
    nom_gagnant = discord.utils.escape_markdown(L.equipe(etat, gagnant)["nom"])
    await repondre(interaction, f"✅ Zone {match['zone']} : victoire de **{nom_gagnant}** "
                                f"{score_gagnant}-{score_perdant} enregistrée (+{match['points_attribues']}).")


# --------------------------------------------------------------------------- #
# /edit_player_tournament_rl
# --------------------------------------------------------------------------- #

@app_commands.command(name="edit_player_tournament_rl",
                      description="Modifie un joueur pendant un tournoi : pseudo en jeu, capitaine, remplaçant…")
@app_commands.describe(
    id_tournoi="ID du tournoi (en cours)",
    joueur="Joueur à modifier",
    pseudo_jeu="Son pseudo dans Rocket League",
    pseudo="Son pseudo affiché par le bot",
    nom_equipe="Nouveau nom de son équipe",
    devient_capitaine="True : il devient capitaine de son équipe (c'est lui qui crée les parties privées)",
    remplace_par="Membre du serveur qui prend sa place dans l'équipe",
)
@app_commands.autocomplete(id_tournoi=autocomplete_etat_en_cours, joueur=autocomplete_joueur)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
async def edit_player_tournament_rl(
    interaction: discord.Interaction,
    id_tournoi: str,
    joueur: str,
    pseudo_jeu: app_commands.Range[str, 1, L.LONGUEUR_MAX_PSEUDO_JEU] | None = None,
    pseudo: app_commands.Range[str, 1, L.LONGUEUR_MAX_PSEUDO] | None = None,
    nom_equipe: app_commands.Range[str, 1, L.LONGUEUR_MAX_NOM_EQUIPE] | None = None,
    devient_capitaine: bool | None = None,
    remplace_par: discord.Member | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True, thinking=True)
    if remplace_par is not None and remplace_par.bot:
        return await repondre(interaction, "❌ Un bot ne peut pas jouer dans un tournoi.")
    remplacant = (str(remplace_par.id), remplace_par.display_name) if remplace_par is not None else None
    try:
        etat, modif, notes = await gestionnaire(interaction).modifier_joueur(
            id_tournoi, joueur.strip(), serveur_id=str(interaction.guild_id), par=str(interaction.user.id),
            pseudo_jeu=pseudo_jeu, pseudo=pseudo, nom_equipe=nom_equipe,
            devient_capitaine=devient_capitaine, remplacant=remplacant)
    except L.ErreurTournoi as erreur:
        log.info("/edit_player_tournament_rl %s refusé (demandé par %s) : %s", id_tournoi, interaction.user, erreur)
        return await repondre(interaction, f"❌ {erreur}")
    await repondre(interaction, M.reponse_modification(etat, modif, notes))


COMMANDES = [start_tournament_rl, start_tournament_rl_status, stop_tournament_rl, set_result_tournament_rl,
             edit_player_tournament_rl, reset_tournament_rl, start_tournament_init, start_tournament_modify_pp,
             start_tournament_init_status]


async def gerer_erreur(interaction: discord.Interaction, erreur: app_commands.AppCommandError) -> None:
    log.exception("Erreur dans une commande", exc_info=erreur)
    try:
        await repondre(interaction, "❌ Une erreur inattendue est survenue.")
    except discord.HTTPException:
        pass
