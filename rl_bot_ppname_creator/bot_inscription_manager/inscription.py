"""Bouton S'inscrire, fiche d'inscription et boutons Valider / Refuser / Annuler.

Les boutons sont des « DynamicItem » : leur custom_id contient l'ID du
tournoi (et de l'équipe), ils continuent donc de marcher après un
redémarrage du bot.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import ui

from . import logique as L
from .embeds import embed_annonce, pseudo_jeu_affiche

if TYPE_CHECKING:
    from .stockage import Stockage

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Petits utilitaires
# --------------------------------------------------------------------------- #

def maintenant() -> str:
    """Heure locale avec le fuseau horaire (ex : 2026-11-18T20:15:00+01:00) : juste même au changement d'heure."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def heure_limite(equipe: dict) -> str:
    """Heure limite de confirmation, affichée par Discord dans le fuseau de chaque joueur."""
    horodatage = int(L.lire_date(equipe["confirmer_avant"]).timestamp())
    return f"<t:{horodatage}:t> (<t:{horodatage}:R>)"


def stockage(interaction: discord.Interaction) -> Stockage:
    return interaction.client.stockage  # type: ignore[attr-defined]


async def repondre(interaction: discord.Interaction, texte: str | None, **kwargs) -> None:
    """Répond en privé (éphémère), que l'interaction ait déjà été différée ou non."""
    if interaction.response.is_done():
        await interaction.followup.send(texte, ephemeral=True, **kwargs)
    else:
        await interaction.response.send_message(texte, ephemeral=True, **kwargs)


async def envoyer_mp(client: discord.Client, utilisateur_id: str | int, texte: str, **kwargs) -> bool:
    """Envoie un message privé. Retourne False si c'est impossible (MP fermés…)."""
    try:
        utilisateur = client.get_user(int(utilisateur_id)) or await client.fetch_user(int(utilisateur_id))
        await utilisateur.send(texte, **kwargs)
        return True
    except discord.HTTPException as erreur:
        log.info("MP impossible pour %s : %s", utilisateur_id, erreur)
        return False


def pseudos(joueurs: list[dict]) -> str:
    return ", ".join(f"**{j['pseudo']}**" for j in joueurs)


def texte_placement(tournoi: dict, equipe: dict) -> str:
    if equipe["statut"] == L.INSCRITE:
        return f"🎟️ Place obtenue : {len(L.equipes_inscrites(tournoi))}/{tournoi['equipes_max']} équipes inscrites."
    position = L.position_attente(tournoi, equipe)
    return (f"⏳ Le tournoi est plein : l'équipe est en **liste d'attente** "
            f"(position {position}/{tournoi['liste_attente_max']}).")


def texte_attente_validation(equipe: dict) -> str:
    restants = L.joueurs_en_attente(equipe)
    if not restants:
        return "🎉 Toute l'équipe a validé !"
    texte = f"En attente de : {pseudos(restants)}"
    if equipe.get("confirmer_avant"):
        texte += (f"\n⏰ Ils doivent confirmer avant {heure_limite(equipe)}, "
                  f"sinon l'équipe sera désinscrite du tournoi.")
    return texte


# --------------------------------------------------------------------------- #
# Annonce du tournoi
# --------------------------------------------------------------------------- #

def vue_annonce(tournoi: dict) -> ui.View:
    vue = ui.View(timeout=None)
    bouton = BoutonInscription(tournoi["id"])
    bouton.item.disabled = L.est_complet(tournoi)
    vue.add_item(bouton)
    return vue


async def mettre_a_jour_annonce(client: discord.Client, tournoi_id: str) -> bool:
    """Remet à jour l'annonce (titre, cashprize, compteurs, bouton) en relisant le JSON.

    Prend le verrou du tournoi : ne jamais l'appeler en tenant déjà ce verrou.
    Retourne False si l'annonce n'a pas pu être modifiée (supprimée, salon inaccessible…).
    """
    st: Stockage = client.stockage  # type: ignore[attr-defined]
    async with st.verrou(tournoi_id):
        tournoi = st.charger(tournoi_id)
        if not tournoi or not tournoi.get("message_id"):
            return False
        try:
            salon = client.get_channel(int(tournoi["salon_id"])) or await client.fetch_channel(int(tournoi["salon_id"]))
            message = salon.get_partial_message(int(tournoi["message_id"]))  # type: ignore[union-attr]
            await message.edit(embed=embed_annonce(tournoi), view=vue_annonce(tournoi))
            return True
        except (discord.HTTPException, AttributeError) as erreur:
            log.warning("Impossible de mettre à jour l'annonce du tournoi %s : %s", tournoi_id, erreur)
            return False


async def supprimer_annonce(client: discord.Client, tournoi: dict) -> None:
    """Supprime le message d'annonce du tournoi (s'il existe encore)."""
    if not tournoi.get("message_id"):
        return
    try:
        salon = client.get_channel(int(tournoi["salon_id"])) or await client.fetch_channel(int(tournoi["salon_id"]))
        await salon.get_partial_message(int(tournoi["message_id"])).delete()  # type: ignore[union-attr]
    except (discord.HTTPException, AttributeError) as erreur:
        log.warning("Impossible de supprimer l'annonce du tournoi %s : %s", tournoi["id"], erreur)


class BoutonInscription(ui.DynamicItem[ui.Button], template=r"rl:inscr:(?P<t>\d+)"):
    def __init__(self, tournoi_id: str) -> None:
        super().__init__(ui.Button(
            label="S'inscrire", emoji="📝", style=discord.ButtonStyle.success,
            custom_id=f"rl:inscr:{tournoi_id}",
        ))
        self.tournoi_id = tournoi_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(match["t"])

    async def callback(self, interaction: discord.Interaction) -> None:
        tournoi = stockage(interaction).charger(self.tournoi_id)
        if tournoi is None:
            return await repondre(interaction, "❌ Ce tournoi n'existe plus.")
        try:
            L.verifier_peut_s_inscrire(tournoi, str(interaction.user.id))
        except L.ErreurTournoi as erreur:
            return await repondre(interaction, f"❌ {erreur}")
        await interaction.response.send_modal(FicheInscription(tournoi))


# --------------------------------------------------------------------------- #
# Fiche d'inscription
# --------------------------------------------------------------------------- #

class FicheInscription(ui.Modal):
    def __init__(self, tournoi: dict) -> None:
        super().__init__(title=f"Inscription — {tournoi['titre']}"[:45], timeout=900)
        self.tournoi_id = tournoi["id"]
        nb = tournoi["joueurs_par_equipe"] - 1

        self.nom = ui.TextInput(placeholder="Ex : Les Tomates", max_length=L.LONGUEUR_MAX_NOM_EQUIPE)
        self.add_item(ui.Label(text="Nom de l'équipe", component=self.nom))

        self.pseudo_jeu = champ_pseudo_jeu()
        self.add_item(ui.Label(
            text="Ton pseudo Rocket League", description=L.AVERTISSEMENT_PSEUDO_JEU, component=self.pseudo_jeu,
        ))

        self.coequipiers: ui.UserSelect | None = None
        if nb > 0:
            self.coequipiers = ui.UserSelect(
                placeholder=f"Choisis {nb} joueur(s) du serveur", min_values=nb, max_values=nb,
                required=True,
            )
            self.add_item(ui.Label(
                text="Joueurs",
                description=f"Tes {nb} coéquipier(s). Tu es automatiquement le capitaine.",
                component=self.coequipiers,
            ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        client = interaction.client
        capitaine = interaction.user

        # 1. Les joueurs choisis doivent être des membres (humains) du serveur.
        membres: list[discord.Member] = []
        for choisi in self.coequipiers.values if self.coequipiers else []:
            if choisi.bot:
                return await repondre(interaction, f"❌ **{choisi.display_name}** est un bot.")
            membre = choisi if isinstance(choisi, discord.Member) else None
            if membre is None and interaction.guild is not None:
                try:
                    membre = await interaction.guild.fetch_member(choisi.id)
                except discord.NotFound:
                    pass
            if membre is None:
                return await repondre(interaction, f"❌ **{choisi.display_name}** n'est pas membre du serveur.")
            membres.append(membre)

        # 2. Enregistrement de l'équipe.
        st = stockage(interaction)
        async with st.verrou(self.tournoi_id):
            tournoi = st.charger(self.tournoi_id)
            if tournoi is None:
                return await repondre(interaction, "❌ Ce tournoi n'existe plus.")
            try:
                equipe = L.inscrire_equipe(
                    tournoi,
                    nom=self.nom.value,
                    capitaine=(str(capitaine.id), capitaine.display_name),
                    pseudo_jeu_capitaine=self.pseudo_jeu.value,
                    coequipiers=[(str(m.id), m.display_name) for m in membres],
                    maintenant=maintenant(),
                )
            except L.ErreurTournoi as erreur:
                return await repondre(interaction, f"❌ {erreur}")
            st.sauvegarder(tournoi)

        await mettre_a_jour_annonce(client, tournoi["id"])

        # 3. Message aux coéquipiers (MP, ou dans le salon si leurs MP sont fermés).
        # En 1v1 il n'y a personne à prévenir (et pas de délai : « confirmer_avant » vaut None).
        invitation = (
            f"👋 **{capitaine.display_name}** t'a inscrit dans l'équipe **{equipe['nom']}** "
            f"pour le tournoi **{tournoi['titre']}** "
            f"({L.format_match(tournoi['joueurs_par_equipe'])}, {tournoi['date']}, cashprize {tournoi['cashprize']}).\n"
            f"Clique sur **Confirmer ma participation** : on te demandera ton pseudo Rocket League, "
            f"**exactement le même que dans le jeu**, sinon on ne pourra pas t'évaluer.\n"
            f"⏰ Tu as **{L.delai_minutes(equipe)} minutes** pour confirmer (avant {heure_limite(equipe)}), "
            f"sinon l'équipe sera désinscrite du tournoi."
        ) if membres else ""
        for membre in membres:
            vue = vue_validation(tournoi["id"], equipe["id"])
            if not await envoyer_mp(client, membre.id, invitation, view=vue) and interaction.channel:
                try:
                    await interaction.channel.send(  # type: ignore[union-attr]
                        f"{membre.mention} (tes MP sont fermés) — {invitation}",
                        view=vue_validation(tournoi["id"], equipe["id"]),
                        allowed_mentions=discord.AllowedMentions(users=[membre]),
                    )
                except discord.HTTPException as erreur:
                    log.warning("Impossible de prévenir %s : %s", membre.id, erreur)

        # 4. Message au capitaine (MP + réponse privée dans le salon).
        texte = (
            f"✅ Tu t'es inscrit au tournoi **{tournoi['titre']}** avec l'équipe **{equipe['nom']}** "
            f"(team_id `#{equipe['id']}`).\n"
            f"🎮 Ton pseudo Rocket League : {pseudo_jeu_affiche(L.joueur_dans_equipe(equipe, str(capitaine.id)))}\n"
            f"{texte_placement(tournoi, equipe)}\n"
            f"{texte_attente_validation(equipe)}"
        )
        await envoyer_mp(client, capitaine.id, texte, view=vue_capitaine(tournoi["id"], equipe["id"]))
        await repondre(interaction, texte, view=vue_capitaine(tournoi["id"], equipe["id"]))


# --------------------------------------------------------------------------- #
# Validation par les coéquipiers
# --------------------------------------------------------------------------- #

def vue_validation(tournoi_id: str, equipe_id: int) -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(BoutonValider(tournoi_id, equipe_id))
    vue.add_item(BoutonRefuser(tournoi_id, equipe_id))
    return vue


class BoutonValider(ui.DynamicItem[ui.Button], template=r"rl:ok:(?P<t>\d+):(?P<e>\d+)"):
    def __init__(self, tournoi_id: str, equipe_id: int) -> None:
        super().__init__(ui.Button(
            label="Confirmer ma participation", emoji="✅", style=discord.ButtonStyle.success,
            custom_id=f"rl:ok:{tournoi_id}:{equipe_id}",
        ))
        self.tournoi_id, self.equipe_id = tournoi_id, int(equipe_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(match["t"], int(match["e"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        tournoi = stockage(interaction).charger(self.tournoi_id)
        if tournoi is None:
            return await repondre(interaction, "❌ Ce tournoi n'existe plus.")
        try:
            L.verifier_peut_confirmer(tournoi, self.equipe_id, str(interaction.user.id), maintenant())
        except L.ErreurTournoi as erreur:
            return await repondre(interaction, f"❌ {erreur}")
        await interaction.response.send_modal(FicheConfirmation(tournoi, self.equipe_id))


def champ_pseudo_jeu() -> ui.TextInput:
    return ui.TextInput(placeholder="Ex : TomatoKing", max_length=L.LONGUEUR_MAX_PSEUDO_JEU)


class FicheConfirmation(ui.Modal):
    """Fiche ouverte par « Confirmer ma participation » : demande le pseudo Rocket League."""

    def __init__(self, tournoi: dict, equipe_id: int) -> None:
        super().__init__(title="Confirmer ma participation", timeout=900)
        self.tournoi_id, self.equipe_id = tournoi["id"], equipe_id
        self.pseudo_jeu = champ_pseudo_jeu()
        self.add_item(ui.Label(
            text="Ton pseudo Rocket League", description=L.AVERTISSEMENT_PSEUDO_JEU, component=self.pseudo_jeu,
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        st = stockage(interaction)
        joueur_id = str(interaction.user.id)
        async with st.verrou(self.tournoi_id):
            tournoi = st.charger(self.tournoi_id)
            if tournoi is None:
                return await repondre(interaction, "❌ Ce tournoi n'existe plus.")
            try:
                equipe = L.confirmer_joueur(tournoi, self.equipe_id, joueur_id, self.pseudo_jeu.value, maintenant())
            except L.ErreurTournoi as erreur:
                return await repondre(interaction, f"❌ {erreur}")
            st.sauvegarder(tournoi)

        joueur = L.joueur_dans_equipe(equipe, joueur_id)
        await interaction.response.edit_message(
            content=(f"✅ **{joueur['pseudo']}** (🎮 {pseudo_jeu_affiche(joueur)}) a confirmé sa participation "
                     f"dans l'équipe **{equipe['nom']}** pour le tournoi **{tournoi['titre']}**.\n"
                     f"{texte_placement(tournoi, equipe)}"),
            view=None,
        )
        await envoyer_mp(
            interaction.client, equipe["capitaine_id"],
            f"✅ **{joueur['pseudo']}** (🎮 {pseudo_jeu_affiche(joueur)}) a confirmé sa participation "
            f"avec **{equipe['nom']}** au tournoi **{tournoi['titre']}**.\n{texte_attente_validation(equipe)}",
        )


class BoutonRefuser(ui.DynamicItem[ui.Button], template=r"rl:non:(?P<t>\d+):(?P<e>\d+)"):
    def __init__(self, tournoi_id: str, equipe_id: int) -> None:
        super().__init__(ui.Button(
            label="Refuser", emoji="❌", style=discord.ButtonStyle.danger,
            custom_id=f"rl:non:{tournoi_id}:{equipe_id}",
        ))
        self.tournoi_id, self.equipe_id = tournoi_id, int(equipe_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(match["t"], int(match["e"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        st = stockage(interaction)
        joueur_id = str(interaction.user.id)
        async with st.verrou(self.tournoi_id):
            tournoi = st.charger(self.tournoi_id)
            if tournoi is None:
                return await repondre(interaction, "❌ Ce tournoi n'existe plus.")
            try:
                equipe, promues = L.refuser_joueur(tournoi, self.equipe_id, joueur_id, maintenant())
            except L.ErreurTournoi as erreur:
                return await repondre(interaction, f"❌ {erreur}")
            st.sauvegarder(tournoi)

        joueur = L.joueur_dans_equipe(equipe, joueur_id)
        await interaction.response.edit_message(
            content=(f"❌ **{joueur['pseudo']}** a refusé : l'inscription de l'équipe **{equipe['nom']}** "
                     f"au tournoi **{tournoi['titre']}** est annulée."),
            view=None,
        )
        await apres_annulation(
            interaction.client, tournoi, equipe, promues,
            f"❌ **{joueur['pseudo']}** a refusé : l'inscription de l'équipe **{equipe['nom']}** "
            f"au tournoi **{tournoi['titre']}** est annulée.",
            sauf=joueur_id,
        )


# --------------------------------------------------------------------------- #
# Annulation par le capitaine
# --------------------------------------------------------------------------- #

def vue_capitaine(tournoi_id: str, equipe_id: int) -> ui.View:
    vue = ui.View(timeout=None)
    vue.add_item(BoutonAnnuler(tournoi_id, equipe_id))
    return vue


class BoutonAnnuler(ui.DynamicItem[ui.Button], template=r"rl:annul:(?P<t>\d+):(?P<e>\d+)"):
    def __init__(self, tournoi_id: str, equipe_id: int) -> None:
        super().__init__(ui.Button(
            label="Annuler l'inscription", emoji="🗑️", style=discord.ButtonStyle.secondary,
            custom_id=f"rl:annul:{tournoi_id}:{equipe_id}",
        ))
        self.tournoi_id, self.equipe_id = tournoi_id, int(equipe_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(match["t"], int(match["e"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        tournoi = stockage(interaction).charger(self.tournoi_id)
        if tournoi is None:
            return await repondre(interaction, "❌ Ce tournoi n'existe plus.")
        try:
            equipe = L.trouver_equipe(tournoi, self.equipe_id)
        except L.ErreurTournoi as erreur:
            return await repondre(interaction, f"❌ {erreur}")
        if equipe["capitaine_id"] != str(interaction.user.id):
            return await repondre(interaction, "❌ Seul le capitaine peut annuler l'inscription.")
        if equipe["statut"] == L.ANNULEE:
            return await repondre(interaction, "❌ Cette inscription est déjà annulée.")
        await repondre(
            interaction,
            f"⚠️ Annuler l'inscription de **{equipe['nom']}** au tournoi **{tournoi['titre']}** ? "
            f"Ta place sera donnée à la liste d'attente.",
            view=ConfirmationAnnulation(self.tournoi_id, self.equipe_id),
        )


class ConfirmationAnnulation(ui.View):
    def __init__(self, tournoi_id: str, equipe_id: int) -> None:
        super().__init__(timeout=120)
        self.tournoi_id, self.equipe_id = tournoi_id, equipe_id

    @ui.button(label="Oui, annuler", style=discord.ButtonStyle.danger)
    async def confirmer(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        st = stockage(interaction)
        async with st.verrou(self.tournoi_id):
            tournoi = st.charger(self.tournoi_id)
            if tournoi is None:
                return await repondre(interaction, "❌ Ce tournoi n'existe plus.")
            try:
                equipe = L.trouver_equipe(tournoi, self.equipe_id)
                if equipe["capitaine_id"] != str(interaction.user.id):
                    raise L.ErreurTournoi("Seul le capitaine peut annuler l'inscription.")
                equipe, promues = L.annuler_equipe(
                    tournoi, self.equipe_id, "annulée par le capitaine", maintenant())
            except L.ErreurTournoi as erreur:
                return await repondre(interaction, f"❌ {erreur}")
            st.sauvegarder(tournoi)

        await interaction.response.edit_message(
            content=f"🗑️ L'inscription de **{equipe['nom']}** au tournoi **{tournoi['titre']}** est annulée.",
            view=None,
        )
        await apres_annulation(
            interaction.client, tournoi, equipe, promues,
            f"🗑️ Le capitaine a annulé l'inscription de l'équipe **{equipe['nom']}** "
            f"au tournoi **{tournoi['titre']}**.",
            sauf=equipe["capitaine_id"],
        )

    @ui.button(label="Non", style=discord.ButtonStyle.secondary)
    async def garder(self, interaction: discord.Interaction, _bouton: ui.Button) -> None:
        await interaction.response.edit_message(content="👍 Inscription conservée.", view=None)


# --------------------------------------------------------------------------- #
# Après une annulation (refus, capitaine ou admin)
# --------------------------------------------------------------------------- #

async def apres_annulation(
    client: discord.Client,
    tournoi: dict,
    equipe: dict,
    promues: list[dict],
    message_joueurs: str,
    sauf: str | None = None,
) -> None:
    """Prévient les joueurs de l'équipe annulée et les équipes promues, puis met à jour l'annonce."""
    for joueur in equipe["joueurs"]:
        if joueur["id"] != sauf and joueur["statut"] != L.REFUSE:
            await envoyer_mp(client, joueur["id"], message_joueurs)

    await prevenir_promues(client, tournoi, promues)
    await mettre_a_jour_annonce(client, tournoi["id"])


async def expirer_inscriptions(client: discord.Client) -> int:
    """Désinscrit les équipes dont les coéquipiers n'ont pas confirmé à temps.

    Appelée chaque minute par le bot. Retourne le nombre d'équipes désinscrites.
    """
    st: Stockage = client.stockage  # type: ignore[attr-defined]
    total = 0
    for resume in st.lister():
        tournoi_id = resume["id"]
        async with st.verrou(tournoi_id):
            tournoi = st.charger(tournoi_id)
            if tournoi is None:
                continue
            expirees, promues = L.expirer_equipes(tournoi, maintenant())
            if not expirees:
                continue
            st.sauvegarder(tournoi)

        total += len(expirees)
        for equipe in expirees:
            log.info("Tournoi %s : équipe #%s %s désinscrite (%s)",
                     tournoi_id, equipe["id"], equipe["nom"], equipe["raison_annulation"])
            retardataires = L.joueurs_en_attente(equipe)
            verbe = "n'a pas confirmé sa" if len(retardataires) == 1 else "n'ont pas confirmé leur"
            texte = (
                f"⏰ L'équipe **{equipe['nom']}** est désinscrite du tournoi **{tournoi['titre']}** : "
                f"{pseudos(retardataires)} {verbe} participation "
                f"dans les {L.delai_minutes(equipe)} minutes.\n"
                f"Vous pouvez vous réinscrire avec le bouton **S'inscrire** de l'annonce s'il reste de la place."
            )
            for joueur in equipe["joueurs"]:
                await envoyer_mp(client, joueur["id"], texte)
        await prevenir_promues(client, tournoi, promues)
        await mettre_a_jour_annonce(client, tournoi_id)
    return total


async def prevenir_promues(
    client: discord.Client, tournoi: dict, promues: list[dict], raison: str = "Une place s'est libérée",
) -> None:
    """MP aux joueurs des équipes qui passent de la liste d'attente aux équipes inscrites."""
    for promue in promues:
        texte = (
            f"🎉 {raison} : l'équipe **{promue['nom']}** passe de la liste d'attente "
            f"aux équipes inscrites du tournoi **{tournoi['titre']}** ({tournoi['date']}) !"
        )
        for joueur in promue["joueurs"]:
            await envoyer_mp(client, joueur["id"], texte)
