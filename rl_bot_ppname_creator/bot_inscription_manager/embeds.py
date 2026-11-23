"""Mise en forme des messages : annonce du tournoi et /tournoi_rl_status."""

from __future__ import annotations

import discord

from . import logique as L

COULEUR = discord.Colour(0xE67E22)  # orange, comme la bordure de l'annonce
LIMITE_DESCRIPTION = 4000  # Discord accepte 4096 caractères par description


def _horodatage(date_iso: str) -> int:
    return int(L.lire_date(date_iso).timestamp())


def _compteur_inscrites(tournoi: dict) -> str:
    # Les places réservées ne sont pas affichées sur l'annonce (seulement dans /tournoi_rl_status).
    return f"{len(L.equipes_inscrites(tournoi))}/{tournoi['equipes_max']}"


def embed_annonce(tournoi: dict) -> discord.Embed:
    if L.est_complet(tournoi):
        description = "🔒 **Complet** (liste d'attente comprise)."
    elif tournoi.get("ouverture_inscriptions"):
        horodatage = _horodatage(tournoi["ouverture_inscriptions"])
        description = (f"🕒 Les inscriptions ouvrent <t:{horodatage}:R> (<t:{horodatage}:t>). "
                       f"Reviens cliquer sur **S'inscrire** à ce moment-là !")
    else:
        description = "Clique sur **S'inscrire** ci-dessous pour engager ton équipe !"

    embed = discord.Embed(title=f"🏆 {tournoi['titre']}", description=description, colour=COULEUR)
    embed.add_field(name="💰 Cashprize", value=tournoi["cashprize"])
    embed.add_field(name="👥 Format", value=L.format_match(tournoi["joueurs_par_equipe"]))
    embed.add_field(
        name="🎟️ Équipes inscrites",
        value=_compteur_inscrites(tournoi),
    )
    embed.add_field(name="📅 Date", value=tournoi["date"])
    embed.add_field(
        name="⏳ Liste d'attente",
        value=f"{len(L.liste_attente(tournoi))}/{tournoi['liste_attente_max']}",
    )
    embed.add_field(name="​", value=f"**ID tournoi : {tournoi['id']}**", inline=False)
    return embed


def pseudo_jeu_affiche(joueur: dict) -> str:
    """Pseudo Rocket League entre `…` : affiché tel quel (les _ et * ne sont pas pris pour du gras/italique)."""
    pseudo_jeu = joueur.get("pseudo_jeu")
    if not pseudo_jeu:
        return "*pseudo jeu inconnu*"
    return f"`{pseudo_jeu.replace('`', 'ˋ')}`"


def _ligne_joueurs(equipe: dict) -> str:
    morceaux = []
    for joueur in equipe["joueurs"]:
        couronne = "👑 " if joueur["id"] == equipe["capitaine_id"] else ""
        if joueur["statut"] == L.CONFIRME:
            morceaux.append(f"{couronne}{joueur['pseudo']} (🎮 {pseudo_jeu_affiche(joueur)}) ✅")
        else:
            morceaux.append(f"{couronne}{joueur['pseudo']} ⏳")
    return ", ".join(morceaux)


def _ligne_equipe(equipe: dict, prefixe: str = "") -> str:
    ligne = f"{prefixe}`#{equipe['id']}` **{equipe['nom']}** — {_ligne_joueurs(equipe)}"
    if equipe.get("confirmer_avant") and not L.equipe_confirmee(equipe):
        horodatage = int(L.lire_date(equipe["confirmer_avant"]).timestamp())
        ligne += f" · ⏰ désinscrite <t:{horodatage}:R> sans confirmation"
    if equipe.get("reservation_id"):
        ligne += " · 🔒 place réservée"
    return ligne


def embeds_status(tournoi: dict) -> list[discord.Embed]:
    inscrites = L.equipes_inscrites(tournoi)
    attente = L.liste_attente(tournoi)

    lignes = [
        f"💰 Cashprize : **{tournoi['cashprize']}**  ·  👥 Format : **{L.format_match(tournoi['joueurs_par_equipe'])}**"
        f"  ·  📅 Date : **{tournoi['date']}**",
        "*✅ = a confirmé · ⏳ = n'a pas encore confirmé · 🎮 = pseudo Rocket League · `#n` = team_id*",
    ]
    if tournoi.get("ouverture_inscriptions"):
        horodatage = _horodatage(tournoi["ouverture_inscriptions"])
        lignes.append(f"🕒 Inscriptions ouvertes <t:{horodatage}:R> (<t:{horodatage}:f>)")
    lignes += [
        "",
        f"**🎟️ Équipes inscrites ({len(inscrites)}/{tournoi['equipes_max']})**",
    ]
    lignes += [_ligne_equipe(e) for e in inscrites] or ["*Aucune équipe pour l'instant.*"]
    reservations = L.reservations_actives(tournoi)
    if reservations:
        lignes += ["", f"**🔒 Places réservées ({len(reservations)})**"]
        lignes += [f"`R{r['id']}` **{r['nom']}** — capitaine {r['capitaine']} · "
                   f"⌛ rendue <t:{_horodatage(r['expire_le'])}:R> si personne ne s'inscrit"
                   for r in reservations]
    lignes += ["", f"**⏳ Liste d'attente ({len(attente)}/{tournoi['liste_attente_max']})**"]
    lignes += [_ligne_equipe(e, f"{i}. ") for i, e in enumerate(attente, start=1)] or ["*Vide.*"]

    # Découpe en plusieurs embeds si la liste est trop longue pour un seul.
    blocs, courant = [], ""
    for ligne in lignes:
        if len(courant) + len(ligne) + 1 > LIMITE_DESCRIPTION:
            blocs.append(courant)
            courant = ""
        courant += ligne + "\n"
    blocs.append(courant)

    embeds = []
    for i, bloc in enumerate(blocs[:10]):  # 10 embeds max par message
        embed = discord.Embed(description=bloc, colour=COULEUR)
        if i == 0:
            embed.title = f"📋 {tournoi['titre']}"
        embeds.append(embed)
    embeds[-1].set_footer(text=f"ID tournoi : {tournoi['id']}")
    return embeds
