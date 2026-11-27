"""Textes des MP, des annonces (salon des annonces), des alertes (LOG_CHANNEL)
et de /start_tournament_rl_status."""

from __future__ import annotations

import re

import discord
from discord.utils import escape_markdown

from . import logique as L

COULEUR = discord.Colour(0xE67E22)  # orange, comme le bot d'inscription
COULEUR_ALERTE = discord.Colour(0xE74C3C)
LIMITE_DESCRIPTION = 4000           # Discord accepte 4096 caractères par description
MEDAILLES = {1: "🥇", 2: "🥈", 3: "🥉"}


# --------------------------------------------------------------------------- #
# Petits utilitaires
# --------------------------------------------------------------------------- #

def _nom(etat: dict, equipe_id: int) -> str:
    return escape_markdown(L.equipe(etat, equipe_id)["nom"])


def _titre(etat: dict) -> str:
    return escape_markdown(etat["titre"])


def _points(n: int) -> str:
    return f"{n} point{'s' if n > 1 else ''}"


def _rang(n: int) -> str:
    return "1er" if n == 1 else f"{n}e"


def zone_titre(etat: dict, zone: int) -> str:
    return f"Zone {zone} ⭐" if L.est_zone_haute(etat, zone) else f"Zone {zone}"


def _format(etat: dict) -> str:
    n = etat.get("joueurs_par_equipe")
    return f"{n}v{n}" if n else "match"


def _entete_match(etat: dict, numero: int, match: dict) -> str:
    return f"🏆 **{_titre(etat)}** — Round {numero}/{etat['nombre_de_rondes']} · **{zone_titre(etat, match['zone'])}**"


def _bloc_partie(match: dict) -> list[str]:
    return [f"> Nom : `{match['pp']['nom']}`", f"> Mot de passe : `{match['pp']['mot_de_passe']}`"]


def _consigne_couleurs(etat: dict, match: dict) -> str:
    return (f"🔵 **{_nom(etat, match['equipe_a'])}** en **Bleu** · "
            f"🟠 **{_nom(etat, match['equipe_b'])}** en **Orange**")


def _score(etat: dict, match: dict) -> str:
    score = match["score"]
    return (f"**{_nom(etat, match['equipe_a'])}** {score['equipe_a']} - "
            f"{score['equipe_b']} **{_nom(etat, match['equipe_b'])}**")


def _embeds(titre: str, lignes: list[str], pied: str | None = None,
            couleur: discord.Colour = COULEUR) -> list[discord.Embed]:
    """Découpe en plusieurs embeds si le texte est trop long pour un seul."""
    blocs, courant = [], ""
    for ligne in lignes:
        if courant and len(courant) + len(ligne) + 1 > LIMITE_DESCRIPTION:
            blocs.append(courant)
            courant = ""
        courant += ligne + "\n"
    blocs.append(courant or "​")
    embeds = []
    for i, bloc in enumerate(blocs[:10]):  # 10 embeds max par message
        embed = discord.Embed(description=bloc, colour=couleur)
        if i == 0:
            embed.title = titre
        embeds.append(embed)
    if pied:
        embeds[-1].set_footer(text=pied)
    return embeds


# --------------------------------------------------------------------------- #
# MP aux joueurs
# --------------------------------------------------------------------------- #

RAPPEL = "🔁 *Rappel : le bot a redémarré, voici de nouveau les infos de ton match.*"
CONSIGNE_SCORE = (
    "📝 **À la fin du match, le bot vous envoie un MP pour déclarer le score** (bouton **Déclarer le score**). "
    "Un joueur de chaque équipe déclare : le résultat est validé quand les deux équipes déclarent le même score."
)


def mp_creation(etat: dict, numero: int, match: dict, reprise: bool = False) -> str:
    """MP au capitaine de l'équipe A : c'est lui qui crée la partie privée (bouton sous le message)."""
    lignes = [RAPPEL] if reprise else []
    lignes += [
        _entete_match(etat, numero, match),
        f"Ton équipe **{_nom(etat, match['equipe_a'])}** affronte **{_nom(etat, match['equipe_b'])}** "
        f"({_format(etat)}).",
        "",
        "👉 **Vous devez créer la partie privée** avec :",
        *_bloc_partie(match),
        "",
    ]
    if match.get("pp_creee_le"):
        lignes.append(f"✅ Tu as indiqué que la partie est créée ({_heure(match['pp_creee_le'])}).")
    else:
        lignes.append("Une fois la partie créée, clique sur **✅ Partie privée créée** : le bot prévient les "
                      "autres joueurs.")
    lignes += [
        "",
        _consigne_couleurs(etat, match),
        "",
        CONSIGNE_SCORE,
    ]
    return "\n".join(lignes)


def duree(secondes: float) -> str:
    """« 10 min », « 1 min 30 s », « 45 s »."""
    secondes = int(round(secondes))
    minutes, reste = divmod(secondes, 60)
    if not minutes:
        return f"{reste} s"
    return f"{minutes} min" + (f" {reste} s" if reste else "")


def _heure(horodatage: str) -> str:
    """« 15:42 » à partir de « 2026-11-18T15:42:10 »."""
    return horodatage[11:16] if len(horodatage) >= 16 else horodatage


def _pseudo_capitaine(etat: dict, match: dict) -> str:
    equipe_a = L.equipe(etat, match["equipe_a"])
    capitaine = next((j for j in equipe_a["joueurs"] if j["id"] == equipe_a["capitaine_id"]), None)
    return escape_markdown(capitaine["pseudo"]) if capitaine else "Le capitaine"


def mp_pp_creee(etat: dict, numero: int, match: dict, equipe_id: int) -> str:
    """Aux autres joueurs du match, quand le capitaine a cliqué sur « Partie privée créée »."""
    return "\n".join([
        f"✅ **{_pseudo_capitaine(etat, match)}** a créé la partie privée — {_titre(etat)}, round {numero}, "
        f"{zone_titre(etat, match['zone'])} (**{_nom(etat, equipe_id)}** vs "
        f"**{_nom(etat, L.adversaire(match, equipe_id))}**). Tu peux la rejoindre :",
        *_bloc_partie(match),
    ])


def mp_rappel_creation(etat: dict, numero: int, match: dict, duree_restante: str) -> str:
    """Rappel au capitaine qui n'a pas cliqué sur « Partie privée créée »."""
    return "\n".join([
        f"⏰ **Rappel** — {_titre(etat)}, round {numero}, {zone_titre(etat, match['zone'])} : as-tu créé la "
        "partie privée ?",
        *_bloc_partie(match),
        "Quand elle est créée, clique sur **✅ Partie privée créée**. "
        f"Sans clic, le bot considérera que le match a commencé dans {duree_restante}.",
    ])


def reponse_pp_creee(nouveau: bool, match: dict) -> str:
    if nouveau:
        return ("✅ Merci ! Les autres joueurs sont prévenus. Bon match : le bot vous demandera le score "
                "en MP à la fin.")
    return f"✅ Déjà noté : partie créée à {_heure(match['pp_creee_le'])}."


def mp_rejoindre(etat: dict, numero: int, match: dict, equipe_id: int, reprise: bool = False) -> str:
    """MP aux autres joueurs des deux équipes : comment rejoindre la partie."""
    nom_capitaine = _pseudo_capitaine(etat, match)
    lignes = [RAPPEL] if reprise else []
    lignes += [
        _entete_match(etat, numero, match),
        f"Ton équipe **{_nom(etat, equipe_id)}** affronte **{_nom(etat, L.adversaire(match, equipe_id))}** "
        f"({_format(etat)}).",
        "",
        *_ligne_partie(match, f"**{nom_capitaine}** (capitaine de **{_nom(etat, match['equipe_a'])}**)"),
        "",
        _consigne_couleurs(etat, match),
        "",
        CONSIGNE_SCORE,
    ]
    return "\n".join(lignes)


def _ligne_partie(match: dict, capitaine: str) -> list[str]:
    """Pour les joueurs qui rejoignent : le nom et le mot de passe seulement une fois la partie créée.
    Avant le clic du capitaine, ils les reçoivent dans le MP « ✅ … a créé la partie privée »."""
    if match.get("pp_creee_le"):
        return [f"{capitaine} a créé la partie privée. Rejoins-la avec :", *_bloc_partie(match)]
    return [f"{capitaine} crée la partie privée : tu recevras son nom et son mot de passe en MP dès qu'elle "
            "sera prête."]


def secours_infos_match(etat: dict, numero: int, match: dict) -> str:
    """Posté dans le salon (sans le mot de passe) quand un MP est impossible."""
    return (f"je n'arrive pas à t'envoyer de MP pour ton match du tournoi **{_titre(etat)}** "
            f"(round {numero}, {zone_titre(etat, match['zone'])}). Ouvre tes MP pour ce serveur ; "
            "tes coéquipiers ont reçu les infos de la partie privée.")


def mp_fin_match(etat: dict, numero: int, match: dict, equipe_id: int) -> str:
    e = L.equipe(etat, equipe_id)
    gagne = match["vainqueur"] == equipe_id
    source = _source(match)
    lignes = []
    if source == L.SOURCE_BOT:
        lignes.append("✅ **Le bot a pris le score : c'est bon, vous pouvez quitter la partie.**")
    lignes += [
        f"🏁 **Match terminé** — {_titre(etat)}, round {numero}/{etat['nombre_de_rondes']}, "
        f"{zone_titre(etat, match['zone'])}",
        _score(etat, match),
    ]
    if gagne:
        lignes.append(f"✅ Victoire : **+{_points(match['points_attribues'])}** · "
                      f"total de **{_nom(etat, equipe_id)}** : **{_points(e['points'])}**")
    else:
        lignes.append(f"❌ Défaite : **+0 point** · total de **{_nom(etat, equipe_id)}** : **{_points(e['points'])}**")
    if source == L.SOURCE_ADMIN:
        lignes.append("*(résultat validé par un admin)*")
    elif source == L.SOURCE_DECLARATIONS:
        lignes.append("*(score déclaré par les deux équipes)*")
    if numero < etat["nombre_de_rondes"]:
        zone = L.zone_suivante(match["zone"], etat["nb_zones"], gagne)
        sens = "tu montes" if zone > match["zone"] else "tu descends" if zone < match["zone"] else "tu restes"
        lignes.append(f"➡️ Prochain round : **{zone_titre(etat, zone)}** ({sens})")
    else:
        lignes.append("🏆 C'était le dernier round : le classement final arrive dès que tous les matchs sont terminés.")
    return "\n".join(lignes)


def _source(match: dict) -> str:
    """Qui a donné le score (les fichiers d'avant n'ont pas "source_resultat")."""
    return match.get("source_resultat") or (L.SOURCE_ADMIN if match.get("valide_par") else L.SOURCE_BOT)


def mp_declaration(etat: dict, numero: int, match: dict, equipe_id: int) -> str:
    """Délai passé : les joueurs déclarent le score (bouton sous le message)."""
    return "\n".join([
        f"📝 **Déclare le score de ton match** — {_titre(etat)}, round {numero}/{etat['nombre_de_rondes']}, "
        f"{zone_titre(etat, match['zone'])}",
        f"**{_nom(etat, equipe_id)}** vs **{_nom(etat, L.adversaire(match, equipe_id))}**",
        "",
        "Quand le match est fini, clique sur **Déclarer le score** : un joueur de chaque équipe déclare, et "
        "le résultat est validé quand les deux équipes déclarent le même score. Si ce n'est pas le cas, "
        "un admin tranche.",
    ])


def secours_declaration(etat: dict, numero: int, match: dict) -> str:
    """Posté dans le salon des annonces (avec le bouton) quand le MP de déclaration est impossible."""
    return (f"je n'arrive pas à t'envoyer de MP. Il faut déclarer le score de ton match du tournoi "
            f"**{_titre(etat)}** (round {numero}, {zone_titre(etat, match['zone'])}) : déclare-le avec le bouton "
            "ci-dessous quand le match est fini.")


def mp_desaccord(etat: dict, numero: int, match: dict, equipe_id: int) -> str:
    return (f"⚠️ **Les deux équipes n'ont pas déclaré le même score** — {_titre(etat)}, round {numero}, "
            f"{zone_titre(etat, match['zone'])} (**{_nom(etat, equipe_id)}** vs "
            f"**{_nom(etat, L.adversaire(match, equipe_id))}**).\n"
            "Un admin va trancher. Si ton équipe s'est trompée, corrige avec le bouton **Déclarer le score**.")


REPONSES_DECLARATION = {
    L.DECLARATION_EN_ATTENTE: "✅ Score enregistré pour ton équipe. Il sera validé quand l'autre équipe "
                              "aura déclaré le même score.",
    L.DECLARATION_VALIDEE: "✅ Les deux équipes ont déclaré le même score : résultat enregistré.",
    L.DECLARATION_DESACCORD: "⚠️ L'autre équipe a déclaré un score différent : un admin va trancher. "
                             "Si tu t'es trompé, reclique sur le bouton pour corriger.",
}


def mp_fin_tournoi(etat: dict, equipe_id: int) -> str:
    e = L.equipe(etat, equipe_id)
    position = L.rang(etat, equipe_id)
    medaille = MEDAILLES.get(position, "🏁")
    return (f"{medaille} Le tournoi **{_titre(etat)}** est terminé ! Ton équipe **{_nom(etat, equipe_id)}** "
            f"finit **{_rang(position)}** sur {len(etat['equipes'])} avec **{_points(e['points'])}** "
            f"({e['victoires']}V - {e['defaites']}D). Merci d'avoir joué !")


def _infos_pp_finale(etat: dict) -> str:
    pp = etat["match_finale"]["pp"]
    return f"🔑 Nom : `{pp['nom']}` · Mot de passe : `{pp['mot_de_passe']}`"


def texte_journal_finale(etat: dict) -> str:
    """LOG_CHANNEL à la fin des rounds : la finale et la partie privée à créer."""
    finale = etat["match_finale"]
    return (f"🏆 **Finale (BO3)** du tournoi **{_titre(etat)}** : **{_nom(etat, finale['equipe_a'])}** 🆚 "
            f"**{_nom(etat, finale['equipe_b'])}**\n"
            f"Crée la partie privée de la finale :\n{_infos_pp_finale(etat)}")


def mp_finale(etat: dict, equipe_id: int) -> str:
    """MP aux joueurs des deux finalistes : la partie privée à rejoindre."""
    adversaire = L.adversaire(etat["match_finale"], equipe_id)
    return (f"🏆 Ton équipe **{_nom(etat, equipe_id)}** joue la **finale (BO3)** du tournoi **{_titre(etat)}** "
            f"contre **{_nom(etat, adversaire)}** !\n"
            f"Rejoins la partie privée :\n{_infos_pp_finale(etat)}")


def ligne_finale(etat: dict) -> str:
    """Rappel au lancement : finale ou pas."""
    if L.a_une_finale(etat):
        return "🏆 Finale : oui, BO3 entre les 2 premiers à la fin des rounds"
    return "🏆 Finale : non"


def mp_arret(etat: dict, equipe_id: int) -> str:
    e = L.equipe(etat, equipe_id)
    return (f"🛑 Le tournoi **{_titre(etat)}** a été arrêté par un admin. Ton équipe **{_nom(etat, equipe_id)}** "
            f"était **{_rang(L.rang(etat, equipe_id))}** avec **{_points(e['points'])}**.")


# --------------------------------------------------------------------------- #
# Modification d'un joueur pendant le tournoi (/edit_player_tournament_rl)
# --------------------------------------------------------------------------- #

def _code(valeur: str | None) -> str:
    return f"`{valeur.replace('`', chr(39))}`" if valeur else "*(aucun)*"


def _salon_discussion(etat: dict) -> str:
    salon = etat.get("salon_discussion_id")
    return f"\n💬 Salon de discussion du tournoi : <#{salon}>" if salon else ""


def mp_remplacant(etat: dict, equipe_id: int, joueur_id: str, ancien_pseudo: str) -> str:
    """Au membre `joueur_id` qui remplace un joueur."""
    e = L.equipe(etat, equipe_id)
    lignes = [f"🔄 Un admin t'a ajouté au tournoi **{_titre(etat)}** : tu remplaces **{escape_markdown(ancien_pseudo)}** "
              f"dans l'équipe **{_nom(etat, equipe_id)}**."]
    if e["capitaine_id"] == joueur_id:
        lignes.append("👑 Tu es le capitaine : quand ton équipe joue en Bleu, c'est toi qui crées la partie privée.")
    else:
        capitaine = next((j for j in e["joueurs"] if j["id"] == e["capitaine_id"]), None)
        if capitaine:
            lignes.append(f"Capitaine de l'équipe : **{escape_markdown(capitaine['pseudo'])}**.")
    lignes.append("Les infos de tes matchs arrivent ici, en MP." + _salon_discussion(etat))
    return "\n".join(lignes)


def mp_remplace(etat: dict, equipe_id: int, nouveau_pseudo: str) -> str:
    """Au joueur remplacé."""
    return (f"🔄 Un admin t'a remplacé par **{escape_markdown(nouveau_pseudo)}** dans l'équipe "
            f"**{_nom(etat, equipe_id)}** du tournoi **{_titre(etat)}**. Tu ne recevras plus de message pour ce "
            "tournoi, et tes anciens boutons ne marchent plus.")


def mp_nouveau_capitaine(etat: dict, equipe_id: int) -> str:
    return (f"👑 Un admin t'a nommé capitaine de **{_nom(etat, equipe_id)}** dans le tournoi **{_titre(etat)}** : "
            "quand ton équipe joue en Bleu, c'est toi qui crées la partie privée et qui cliques sur "
            "**✅ Partie privée créée**.")


def mp_plus_capitaine(etat: dict, equipe_id: int, nouveau_pseudo: str, partie_a_creer: bool) -> str:
    texte = (f"ℹ️ Tu n'es plus capitaine de **{_nom(etat, equipe_id)}** dans le tournoi **{_titre(etat)}** : "
             f"c'est maintenant **{escape_markdown(nouveau_pseudo)}** qui crée les parties privées.")
    if partie_a_creer:
        texte += (f"\nSi tu as déjà créé la partie privée de ce round, préviens **{escape_markdown(nouveau_pseudo)}** :"
                  " c'est lui qui clique maintenant sur **✅ Partie privée créée**.")
    return texte


def mp_infos_remplacant(etat: dict, numero: int, match: dict, equipe_id: int) -> str:
    """Au remplaçant dont l'équipe a un match en cours (et qui n'a pas à créer la partie)."""
    return "\n".join([
        _entete_match(etat, numero, match),
        f"Ton équipe **{_nom(etat, equipe_id)}** affronte **{_nom(etat, L.adversaire(match, equipe_id))}** "
        f"({_format(etat)}).",
        "",
        *_ligne_partie(match, f"**{_pseudo_capitaine(etat, match)}** (capitaine de **{_nom(etat, match['equipe_a'])}**)"),
        "",
        _consigne_couleurs(etat, match),
        "",
        CONSIGNE_SCORE,
    ])


def lignes_changements(etat: dict, modif: dict) -> list[str]:
    changements = modif["changements"]
    lignes = []
    if "joueur" in changements:
        ancien, nouveau = changements["joueur"]
        lignes.append(f"🔄 Joueur remplacé : <@{ancien}> → <@{nouveau}>")
    if "pseudo" in changements:
        lignes.append("Pseudo : {} → {}".format(*map(_code, changements["pseudo"])))
    if "pseudo_jeu" in changements:
        lignes.append("Pseudo en jeu : {} → {}".format(*map(_code, changements["pseudo_jeu"])))
    if "nom_equipe" in changements:
        lignes.append("Nom d'équipe : {} → {}".format(*map(_code, changements["nom_equipe"])))
    if "capitaine" in changements:
        ancien, nouveau = changements["capitaine"]
        lignes.append(f"👑 Capitaine : <@{ancien}> → <@{nouveau}>")
    return lignes


def texte_journal_modification(etat: dict, modif: dict) -> str:
    """Pour LOG_CHANNEL (sans mention qui notifie)."""
    pseudo = escape_markdown(modif["ancien_joueur"]["pseudo"])
    return "\n".join([
        f"✏️ <@{modif['par']}> a modifié **{pseudo}** (équipe **{_nom(etat, modif['equipe'])}**) dans le tournoi "
        f"**{_titre(etat)}** :",
        *(f"- {ligne}" for ligne in lignes_changements(etat, modif)),
    ])


def reponse_modification(etat: dict, modif: dict, notes: list[str]) -> str:
    """Réponse à l'admin qui a lancé /edit_player_tournament_rl."""
    lignes = [f"✅ Modifié dans le tournoi **{_titre(etat)}** (équipe **{_nom(etat, modif['equipe'])}**) :",
              *(f"- {ligne}" for ligne in lignes_changements(etat, modif))]
    if notes:
        lignes += ["", *notes]
    return "\n".join(lignes)


# --------------------------------------------------------------------------- #
# Messages dans le salon
# --------------------------------------------------------------------------- #

def bareme_golden(etat: dict) -> str:
    """Gain d'une victoire par zone à partir du golden round, ex. « Zone 4 ⭐ +10 · Zone 3 +7 · ailleurs +1 ».
    Sans options zone_1 à zone_4 : « zone haute ⭐ +3 »."""
    if not L.a_points_zones(etat):
        return f"zone haute ⭐ +{L.POINTS_VICTOIRE_ZONE_HAUTE}"
    morceaux, ailleurs = [], False
    for zone in range(etat["nb_zones"], 0, -1):
        gain = L.points_zone_golden(etat, zone)
        if gain == L.POINTS_VICTOIRE and str(zone) not in etat["points_zones"]:
            ailleurs = True
        else:
            morceaux.append(f"{zone_titre(etat, zone)} +{gain}")
    if ailleurs:
        morceaux.append(f"ailleurs +{L.POINTS_VICTOIRE}")
    return " · ".join(morceaux)


def regle_points(etat: dict, numero: int) -> str:
    """Barème des points au round `numero` (golden round compris)."""
    golden = L.golden_round(etat)
    if L.bonus_zone_haute(etat, numero):
        if L.a_points_zones(etat):
            texte = f"Victoire : {bareme_golden(etat)} · défaite : 0"
        else:
            texte = "Victoire en zone haute ⭐ : +3 · victoire ailleurs : +1 · défaite : 0"
        return texte + (f" · 🌟 golden round depuis le round {golden}" if golden > 1 else "")
    return f"Toutes les victoires : +1 · défaite : 0 · 🌟 golden round au round {golden} : {bareme_golden(etat)}"


def ligne_points(etat: dict) -> str:
    """Barème annoncé au lancement du tournoi."""
    return f"🏅 {regle_points(etat, 1)}"


def _annonce_golden_round(etat: dict, numero: int) -> list[str]:
    """Lignes du début de round sur le golden round (rien si le tournoi n'en a pas)."""
    golden = L.golden_round(etat)
    if golden == 1 or numero > golden:
        return []
    if numero == golden:
        if L.a_points_zones(etat):
            return [f"🌟 **Golden round !** À partir de maintenant, une victoire rapporte : **{bareme_golden(etat)}**.", ""]
        return ["🌟 **Golden round !** À partir de maintenant, la victoire en zone haute ⭐ rapporte **+3**.", ""]
    return [f"🌟 Golden round au round {golden} : d'ici là, toutes les victoires rapportent +1.", ""]


def embeds_debut_ronde(etat: dict, ronde: dict) -> list[discord.Embed]:
    lignes = _annonce_golden_round(etat, ronde["numero"])
    for match in sorted(ronde["matchs"], key=lambda m: m["zone"], reverse=True):
        gain = L.points_victoire(etat, match["zone"], ronde["numero"])
        lignes.append(f"**{zone_titre(etat, match['zone'])}** (+{gain}) : "
                      f"**{_nom(etat, match['equipe_a'])}** 🆚 **{_nom(etat, match['equipe_b'])}**")
    return _embeds(
        f"🏆 {etat['titre']} — Round {ronde['numero']}/{etat['nombre_de_rondes']}", lignes,
        f"Infos de partie privée envoyées en MP · ⭐ zone haute · ID : {etat['tournoi_id']}",
    )


def lignes_classement(etat: dict) -> list[str]:
    lignes = []
    for position, e in enumerate(L.classement(etat), start=1):
        diff = e["buts_pour"] - e["buts_contre"]
        lignes.append(f"{MEDAILLES.get(position, f'`{position}.`')} **{escape_markdown(e['nom'])}** — "
                      f"**{_points(e['points'])}** ({e['victoires']}V-{e['defaites']}D, diff {diff:+d})")
    return lignes


def embeds_classement(etat: dict, titre: str) -> list[discord.Embed]:
    return _embeds(titre, lignes_classement(etat), f"ID tournoi : {etat['tournoi_id']}")


# --------------------------------------------------------------------------- #
# Salon de discussion du tournoi (joueurs + admins)
# --------------------------------------------------------------------------- #

LIMITE_MESSAGE = 2000  # caractères par message Discord


def nom_salon_discussion(etat: dict) -> str:
    """« 💬-tournoi-été-1 » pour « Tournoi Été #1 ! » (minuscules, tirets, comme Discord)."""
    nom = re.sub(r"[^\w-]+", "-", etat["titre"].lower())
    nom = re.sub(r"-{2,}", "-", nom).strip("-_") or "tournoi"
    return f"💬-{nom}"[:100]


def sujet_salon_discussion(etat: dict) -> str:
    return (f"Discussion du tournoi {etat['titre']} : joueurs et admins seulement. "
            f"ID : {etat['tournoi_id']}")[:1024]


def decouper(lignes: list[str], limite: int = LIMITE_MESSAGE) -> list[str]:
    """Regroupe des lignes en messages de `limite` caractères maximum."""
    messages, courant = [], ""
    for ligne in lignes:
        ligne = ligne[:limite]
        if courant and len(courant) + 1 + len(ligne) > limite:
            messages.append(courant)
            courant = ""
        courant = f"{courant}\n{ligne}" if courant else ligne
    if courant:
        messages.append(courant)
    return messages


def textes_bienvenue_salon(etat: dict) -> list[str]:
    """Premier message du salon de discussion : mentionne chaque joueur (il voit ainsi le salon)."""
    if "nombre_de_rondes" in etat:
        infos = f"{len(etat['equipes'])} équipes · {etat['nombre_de_rondes']} round(s) · lancé par <@{etat['lance_par']}>."
    else:  # /start_tournament_init : le tournoi n'est pas encore lancé
        infos = f"{len(etat['equipes'])} équipes · salon ouvert par <@{etat['lance_par']}>."
    lignes = [
        f"👋 Bienvenue dans le salon du tournoi **{_titre(etat)}** !",
        infos,
        "Ce salon est réservé aux joueurs du tournoi et aux admins : questions, problèmes, captures de score…",
        "🔒 Le nom et le mot de passe de chaque partie privée arrivent **en MP**.",
        "",
        "**Équipes**",
    ]
    for e in sorted(etat["equipes"].values(), key=lambda e: e["id"]):
        lignes.append(f"**{escape_markdown(e['nom'])}** : " + " ".join(f"<@{j['id']}>" for j in e["joueurs"]))
    return decouper(lignes)


TEXTE_INIT = "@here Le tournoi va bientôt commencer, soyez prêts ! Bonne chance à tous 🍀"


# --------------------------------------------------------------------------- #
# Validation des participations (/start_tournament_init delai_confirmation)
# --------------------------------------------------------------------------- #

def heure_discord(horodatage: str) -> str:
    """« 15:42 (dans 30 minutes) », affiché par Discord à l'heure de chaque joueur."""
    from datetime import datetime
    try:
        secondes = int(datetime.fromisoformat(horodatage).timestamp())
    except ValueError:
        return _heure(horodatage)
    return f"<t:{secondes}:t> (<t:{secondes}:R>)"


def _minutes(n: int) -> str:
    return f"{n} minute{'s' if n > 1 else ''}"


def mp_confirmation(init: dict, equipe_id: int) -> str:
    """Aux joueurs des équipes inscrites : bouton « Valider ma participation »."""
    confirmation = init["confirmation"]
    return (f"📝 **{_titre(init)}** : tu as **{_minutes(confirmation['delai_minutes'])}** "
            f"(jusqu'à {heure_discord(confirmation['fin'])}) pour valider la participation de ton équipe "
            f"**{_nom(init, equipe_id)}**, sinon elle perdra sa place au profit de la liste d'attente.\n"
            "Clique sur le bouton ci-dessous : un seul joueur de l'équipe suffit.")


def mp_liste_attente(init: dict, equipe_id: int, position: int) -> str:
    """Aux joueurs de la liste d'attente, au moment de /start_tournament_init."""
    confirmation = init["confirmation"]
    equipe = next(e for e in confirmation["attente"] if e["id"] == equipe_id)
    lignes = [
        f"⏳ **{_titre(init)}** : ton équipe **{escape_markdown(equipe['nom'])}** est **{_rang(position)}** "
        "sur la liste d'attente. Reste ici !",
        f"Si une équipe ne valide pas sa participation dans les {_minutes(confirmation['delai_minutes'])} "
        f"(jusqu'à {heure_discord(confirmation['fin'])}), tu avanceras dans la liste d'attente.",
    ]
    if position == 1:
        lignes.append("🌟 Tu es premier : si une équipe ne valide pas, **tu participeras au tournoi** "
                      "(tu recevras alors le bouton pour valider ta participation).")
    return "\n".join(lignes)


def mp_validation_equipe(init: dict, equipe_id: int, par: str) -> str:
    """Aux coéquipiers de celui qui a cliqué."""
    return f"✅ <@{par}> a validé la participation de **{_nom(init, equipe_id)}** à **{_titre(init)}**."


def reponse_validation(init: dict, equipe_id: int, nouvelle: bool) -> str:
    if not nouvelle:
        return f"✅ La participation de **{_nom(init, equipe_id)}** est déjà validée."
    return (f"✅ Participation de **{_nom(init, equipe_id)}** validée ! Rendez-vous au lancement du tournoi"
            + (f" : <#{init['salon_discussion_id']}>." if init.get("salon_discussion_id") else "."))


def mp_place_perdue(init: dict, equipe: dict) -> str:
    return (f"❌ **{_titre(init)}** : ton équipe **{escape_markdown(equipe['nom'])}** n'a pas validé sa "
            "participation à temps, elle perd sa place au tournoi.")


def mp_place_gagnee(init: dict, equipe: dict) -> str:
    """Équipe montée de la liste d'attente : elle doit valider à son tour (bouton)."""
    confirmation = init["confirmation"]
    salon = f"\nLe salon du tournoi : <#{init['salon_discussion_id']}>." if init.get("salon_discussion_id") else ""
    return (f"🎉 **{_titre(init)}** : une place s'est libérée, ton équipe **{escape_markdown(equipe['nom'])}** "
            f"**participe au tournoi** !\n📝 Valide ta participation dans les "
            f"**{_minutes(confirmation['delai_minutes'])}** (jusqu'à {heure_discord(confirmation['fin'])}), sinon "
            f"la place passera à l'équipe suivante de la liste d'attente. Un seul joueur de l'équipe suffit.{salon}")


def mp_toujours_en_attente(init: dict, equipe: dict, position: int) -> str:
    """Liste d'attente, quand des équipes en sont montées (aucun MP à la fin des validations)."""
    return (f"⏳ **{_titre(init)}** : la liste d'attente avance, ton équipe **{escape_markdown(equipe['nom'])}** "
            f"est maintenant **{_rang(position)}**. Si une équipe montée ne valide pas sa participation avant "
            f"{heure_discord(init['confirmation']['fin'])}, tu avanceras encore.")


def texte_vague_confirmation(init: dict, perdues: list[dict], promues: list[dict]) -> str:
    """LOG_CHANNEL : des équipes montent de la liste d'attente et doivent valider à leur tour."""
    noms = lambda equipes: ", ".join(f"**{escape_markdown(e['nom'])}**" for e in equipes)  # noqa: E731
    return (f"⏳ **{_titre(init)}** : pas validé à temps : {noms(perdues)}. Montée{'s' if len(promues) > 1 else ''} "
            f"de la liste d'attente : {noms(promues)}, à valider avant {heure_discord(init['confirmation']['fin'])}.")


def texte_fin_confirmation(init: dict, perdues: list[dict], promues: list[dict]) -> str:
    """Salon de discussion et LOG_CHANNEL : bilan à la fin du délai."""
    noms = lambda equipes: ", ".join(f"**{escape_markdown(e['nom'])}**" for e in equipes)  # noqa: E731
    nb = len(init["equipes"])
    lignes = [f"✅ Fin des validations pour **{_titre(init)}** : {nb} équipe{'s' if nb > 1 else ''} participe"
              f"{'nt' if nb > 1 else ''}."]
    if perdues:
        lignes.append(f"❌ Pas validé à temps : {noms(perdues)}.")
    # Toutes les équipes montées de la liste d'attente (au fil des délais) qui ont validé.
    montees = promues + [e for e in sorted(init["equipes"].values(), key=lambda e: e["id"])
                         if e["id"] in init["confirmation"]["promues"] and e not in promues]
    if montees:
        lignes.append(f"🎉 Montée{'s' if len(montees) > 1 else ''} de la liste d'attente : {noms(montees)}.")
    if nb % 2 or nb < 2:
        lignes.append(f"⚠️ {nb} équipe{'s' if nb > 1 else ''} : il en faut un nombre pair (au moins 2) pour "
                      "lancer le tournoi.")
    return "\n".join(lignes)


def mp_pp_modifiee(etat: dict, numero: int, match: dict) -> str:
    """Aux joueurs, quand un admin change la partie privée d'une partie déjà créée."""
    return "\n".join([
        f"🔁 **La partie privée a changé** — {_titre(etat)}, round {numero}, {zone_titre(etat, match['zone'])} "
        f"(**{_nom(etat, match['equipe_a'])}** vs **{_nom(etat, match['equipe_b'])}**). Nouvelle partie :",
        *_bloc_partie(match),
    ])


def texte_journal_pp(etat: dict, numero: int, match: dict, ancienne: dict, par: str) -> str:
    """LOG_CHANNEL : /start_tournament_modify_pp."""
    return (f"🔁 <@{par}> a changé la partie privée de **{_titre(etat)}**, round {numero}, "
            f"{zone_titre(etat, match['zone'])} : `{ancienne['nom']}` / `{ancienne['mot_de_passe']}` → "
            f"`{match['pp']['nom']}` / `{match['pp']['mot_de_passe']}`.")


def texte_arret(etat: dict) -> str:
    return f"🛑 Le tournoi **{_titre(etat)}** a été arrêté par <@{etat['arrete_par']}>."


# --------------------------------------------------------------------------- #
# Remise à zéro (/reset_tournament_rl)
# --------------------------------------------------------------------------- #

def mp_reinitialisation(etat: dict) -> str:
    return (f"🔄 Le tournoi **{_titre(etat)}** a été remis à zéro par un admin : les matchs en cours sont annulés "
            "et les scores effacés. Tu peux quitter la partie privée. Les admins te diront quand il repart.")


def texte_reinitialisation(etat: dict, par: str) -> str:
    return f"🔄 Le tournoi **{_titre(etat)}** a été remis à zéro par <@{par}> : il repartira de zéro."


def _fichiers(n: int) -> str:
    return f"{n} fichier{'s' if n > 1 else ''}"


def confirmation_reinitialisation(etat: dict, nb_fichiers: int, nb_salons: int, garder_salon: bool) -> str:
    """Question posée à l'admin avant /reset_tournament_rl."""
    lignes = [f"⚠️ Remettre à zéro le tournoi **{_titre(etat)}** ?"]
    if etat.get("statut") == L.EN_COURS:
        lignes.append("- il est **en cours** : il s'arrête, les matchs en cours sont annulés et les joueurs "
                      "sont prévenus en MP ;")
    lignes.append(f"- j'efface tout ce que j'ai gardé sur lui ({_fichiers(nb_fichiers)} : état, scores, "
                  "classement, parties privées, anciens lancements archivés) ;")
    if nb_salons:
        salons = "le salon de discussion" if nb_salons == 1 else f"les {nb_salons} salons de discussion"
        if garder_salon:
            lignes.append(f"- {salons} du tournoi reste{'nt' if nb_salons > 1 else ''} (à supprimer à la main) ;")
        else:
            lignes.append(f"- je supprime {salons} du tournoi, avec leurs messages ;")
    lignes.append("- les inscriptions ne bougent pas : relance-le ensuite avec `/start_tournament_rl`.")
    lignes.append("**On ne peut pas revenir en arrière.**")
    return "\n".join(lignes)


def reponse_reinitialisation(bilan: dict) -> str:
    """Réponse à l'admin après /reset_tournament_rl. `bilan` : voir GestionnaireTournois.reinitialiser()."""
    lignes = [f"🔄 Tournoi **{escape_markdown(bilan['titre'])}** remis à zéro : "
              f"{_fichiers(bilan['nb_fichiers'])} effacé{'s' if bilan['nb_fichiers'] > 1 else ''}."]
    if bilan["etait_en_cours"]:
        lignes.append("🛑 Il était en cours : matchs annulés, joueurs prévenus en MP.")
    if bilan["salons_supprimes"]:
        lignes.append(f"🗑️ Salon{'s' if len(bilan['salons_supprimes']) > 1 else ''} de discussion supprimé"
                      f"{'s' if len(bilan['salons_supprimes']) > 1 else ''}.")
    if bilan["salons_gardes"]:
        lignes.append("💬 Salon(s) de discussion gardé(s) : " + " ".join(f"<#{i}>" for i in bilan["salons_gardes"]))
    if bilan["salons_en_echec"]:
        lignes.append("⚠️ Je n'ai pas pu supprimer " + " ".join(f"<#{i}>" for i in bilan["salons_en_echec"])
                      + " : il me faut **Gérer les salons** (rôle du bot ou permissions du salon). "
                        "Supprime-le à la main (clic droit sur le salon > **Supprimer le salon**).")
    lignes.append(f"Pour le relancer : `/start_tournament_rl id_tournoi:{bilan['tournoi_id']}`")
    return "\n".join(lignes)


def texte_erreur(etat: dict) -> str:
    return (f"❌ Erreur inattendue pendant le tournoi **{_titre(etat)}** : il est en pause. "
            "Redémarre le bot pour le reprendre, ou arrête-le avec `/stop_tournament_rl`.")


# --------------------------------------------------------------------------- #
# Alertes (LOG_CHANNEL)
# --------------------------------------------------------------------------- #

ALERTE_DESACCORD = "les deux équipes n'ont pas déclaré le même score"
ALERTE_PAS_DE_CLIC = "le capitaine n'a pas cliqué sur « Partie privée créée » après {duree}"
CONCLUSION_PAS_DE_CLIC = ("Le délai avant la demande de score démarre quand même : les joueurs pourront déclarer "
                          "le score. Si la partie n'existe pas, contacte le capitaine.")


def _ligne_equipe_alerte(etat: dict, match: dict, equipe_id: int) -> str:
    e = L.equipe(etat, equipe_id)
    pastille = "🔵" if equipe_id == match["equipe_a"] else "🟠"
    pseudos = ", ".join(escape_markdown(j.get("pseudo_jeu") or j["pseudo"]) for j in e["joueurs"])
    return f"{pastille} **#{equipe_id} {_nom(etat, equipe_id)}** : {pseudos}"


def texte_alerte(etat: dict) -> str:
    """Contenu du message d'alerte : mentionne l'admin qui a lancé le tournoi."""
    return f"🚨 <@{etat['lance_par']}>"


def embeds_alerte_match(etat: dict, numero: int, match: dict, probleme: str,
                        conclusion: str | None = None) -> list[discord.Embed]:
    """Tout ce qu'il faut pour rejoindre la partie à la main et entrer le score."""
    capitaine = L.equipe(etat, match["equipe_a"])["capitaine_id"]
    a, b = match["equipe_a"], match["equipe_b"]
    lignes = [
        f"**Problème :** {probleme}" + (f" ({match['raison_a_valider']})" if match.get("raison_a_valider")
                                         and match["raison_a_valider"] != L.RAISON_DECLARATION else ""),
        "",
        "**Pour rejoindre la partie à la main**",
        *_bloc_partie(match),
        f"Créée par : <@{capitaine}> (capitaine de **{_nom(etat, a)}**)",
        _ligne_equipe_alerte(etat, match, a),
        _ligne_equipe_alerte(etat, match, b),
    ]
    declarations = match.get("declarations") or {}
    if declarations:
        lignes += ["", "**Déclarations des équipes**"]
        for equipe_id in (a, b):
            if str(equipe_id) in declarations:
                score_a, score_b = L.score_declare(match, equipe_id)
                lignes.append(f"**{_nom(etat, equipe_id)}** (<@{declarations[str(equipe_id)]['par']}>) : "
                              f"{_nom(etat, a)} {score_a} - {score_b} {_nom(etat, b)}")
            else:
                lignes.append(f"**{_nom(etat, equipe_id)}** : pas encore déclaré")
    lignes += [
        "",
        "**Pour entrer le score**",
        f"`/set_result_tournament_rl id_tournoi:{etat['tournoi_id']} zone:{match['zone']} gagnant:<{a} ou {b}> "
        "score_gagnant:… score_perdant:…`",
        f"(gagnant : **{a}** = {_nom(etat, a)}, **{b}** = {_nom(etat, b)})",
        "",
        conclusion or ("Les joueurs peuvent aussi déclarer le score avec le bouton reçu en MP. Le round attend "
                       "ce résultat ; les autres zones continuent."),
    ]
    return _embeds(f"🚨 {etat['titre']} — round {numero} — {zone_titre(etat, match['zone'])}", lignes,
                   f"ID tournoi : {etat['tournoi_id']}", couleur=COULEUR_ALERTE)


# --------------------------------------------------------------------------- #
# /start_tournament_init_status
# --------------------------------------------------------------------------- #

def _ligne_equipe_init(equipe: dict, promues: list[int], position: int | None = None) -> str:
    """« • **Equipe1** ⬆️ : pseudo 👑 (en jeu : …), pseudo2 (en jeu : …) »."""
    joueurs = ", ".join(
        f"{escape_markdown(j['pseudo'])}{' 👑' if j['id'] == equipe.get('capitaine_id') else ''} "
        f"(en jeu : {escape_markdown(j.get('pseudo_jeu') or '?')})"
        for j in equipe["joueurs"]) or "joueurs inconnus"
    debut = f"`{position}.`" if position is not None else "•"
    montee = " ⬆️" if equipe["id"] in promues else ""
    return f"{debut} **{escape_markdown(equipe['nom'])}**{montee} : {joueurs}"


def _qui_a_valide(equipe: dict) -> str:
    pseudo = next((j["pseudo"] for j in equipe["joueurs"] if j["id"] == equipe["validee_par"]), None)
    qui = escape_markdown(pseudo) if pseudo else f"<@{equipe['validee_par']}>"
    return f"   ↳ validé par {qui} à {heure_discord(equipe['validee_le'])}"


def embeds_init_status(init: dict, bilan: dict, etat: dict | None = None) -> list[discord.Embed]:
    """État des équipes entre /start_tournament_init et le lancement : qui a validé sa participation,
    qui doit encore valider, places perdues et liste d'attente."""
    lignes = []
    nb = len(init["equipes"])
    if bilan["avec_validation"]:
        confirmation = init["confirmation"]
        if bilan["en_cours"]:
            lignes.append(f"⏳ Validation en cours jusqu'à {heure_discord(confirmation['fin'])}, "
                          f"délai de {_minutes(confirmation['delai_minutes'])}.")
        else:
            lignes.append("🔒 Validation terminée.")
        lignes.append(f"✅ **{len(bilan['validees'])}/{nb}** équipe{'s' if nb > 1 else ''} "
                      f"{'ont' if len(bilan['validees']) > 1 else 'a'} validé.")
        if bilan["promues"]:
            n = len(bilan["promues"])
            lignes.append(f"⬆️ {n} équipe{'s' if n > 1 else ''} montée{'s' if n > 1 else ''} de la liste d'attente.")
    else:
        lignes.append("ℹ️ Pas de validation des participations pour ce tournoi.")
    if etat is not None:
        statut = STATUTS_TOURNOI.get(etat.get("statut"), etat.get("statut"))
        lignes.append(f"🏁 Tournoi déjà lancé ({statut}) : `/start_tournament_rl_status "
                      f"id_tournoi:{init['tournoi_id']}`")
    promues = bilan["promues"]
    if bilan["avec_validation"]:
        if bilan["validees"]:
            lignes += ["", f"**✅ Ont validé ({len(bilan['validees'])})**"]
            for equipe in bilan["validees"]:
                lignes += [_ligne_equipe_init(equipe, promues), _qui_a_valide(equipe)]
        if bilan["a_valider"]:
            lignes += ["", f"**⏳ Pas encore validé ({len(bilan['a_valider'])})**"]
            lignes += [_ligne_equipe_init(e, promues) for e in bilan["a_valider"]]
        if bilan["perdues"]:
            lignes += ["", f"**❌ Places perdues ({len(bilan['perdues'])})**"]
            lignes += [_ligne_equipe_init(e, promues) for e in bilan["perdues"]]
        lignes += ["", f"**📋 Liste d'attente ({len(bilan['attente'])})**"]
        lignes += [_ligne_equipe_init(e, promues, position)
                   for position, e in enumerate(bilan["attente"], start=1)] or ["Vide."]
    else:
        lignes += ["", f"**Équipes ({nb})**"]
        lignes += [_ligne_equipe_init(e, promues) for e in bilan["a_valider"]]
    return _embeds(f"📋 {init['titre']} : avant le tournoi", lignes,
                   f"👑 capitaine · ⬆️ montée de la liste d'attente · ID : {init['tournoi_id']}")


# --------------------------------------------------------------------------- #
# /start_tournament_rl_status
# --------------------------------------------------------------------------- #

STATUTS_TOURNOI = {L.EN_COURS: "🟢 En cours", L.TERMINE: "🏁 Terminé", L.ARRETE: "🛑 Arrêté"}


def _ligne_match_status(etat: dict, match: dict, mention_declarations: bool = True) -> str:
    duel = f"**{_nom(etat, match['equipe_a'])}** vs **{_nom(etat, match['equipe_b'])}**"
    statut = match["statut"]
    if statut == L.MATCH_TERMINE:
        etat_match = f"✅ {_score(etat, match)}"
        if _source(match) == L.SOURCE_ADMIN:
            etat_match += " *(validé par un admin)*"
        elif _source(match) == L.SOURCE_DECLARATIONS and mention_declarations:
            etat_match += " *(déclaré par les équipes)*"
    elif statut == L.MATCH_EN_COURS:
        etat_match = f"{duel} — " + ("🎮 partie créée, en cours" if match.get("pp_creee_le")
                                      else "⏳ partie pas encore créée")
    elif statut == L.MATCH_A_VALIDER:
        nb = len(match.get("declarations") or {})
        if match.get("raison_a_valider") == L.RAISON_DECLARATION:
            etat_match = f"{duel} — 📝 score à déclarer · déclarations : {nb}/2"
        else:
            etat_match = f"{duel} — ⚠️ à valider ({match['raison_a_valider']}) · déclarations : {nb}/2"
    elif statut == L.MATCH_ANNULE:
        etat_match = f"{duel} — 🚫 annulé"
    else:
        etat_match = f"{duel} — ⏳ en attente"
    return f"**{zone_titre(etat, match['zone'])}** : {etat_match}"


SEPARATEUR = "━━━━━━━━━━━━━━━━━━━━━━"


def texte_lancement_tournoi(etat: dict) -> str:
    """Salon des résultats, au /start_tournament_rl : sépare les tournois les uns des autres."""
    return f"{SEPARATEUR}\n🚀 **Lancement du tournoi {escape_markdown(etat['titre'])}**"


def embeds_resultats_ronde(etat: dict, ronde: dict) -> list[discord.Embed]:
    """Récap d'un round terminé (salon des résultats) : score de chaque zone, puis classement."""
    lignes = [f"**🎯 Round {ronde['numero']}**"]
    lignes += [_ligne_match_status(etat, m, mention_declarations=False)
               for m in sorted(ronde["matchs"], key=lambda m: m["zone"], reverse=True)]
    lignes += ["", "**📊 Classement**", *lignes_classement(etat)]
    return _embeds(f"🏆 {etat['titre']} — Round {ronde['numero']}/{etat['nombre_de_rondes']}", lignes,
                   f"ID tournoi : {etat['tournoi_id']}")


def embeds_status(etat: dict) -> list[discord.Embed]:
    ronde = L.ronde_actuelle(etat)
    lignes = [
        f"{STATUTS_TOURNOI.get(etat['statut'], etat['statut'])} · Round **{len(etat['rondes'])}/"
        f"{etat['nombre_de_rondes']}** · {etat['nb_zones']} zone(s) · {len(etat['equipes'])} équipes",
        f"*{regle_points(etat, ronde['numero'] if ronde else 1)}*",
        "",
    ]
    if ronde:
        lignes.append(f"**🎯 Round {ronde['numero']}**")
        lignes += [_ligne_match_status(etat, m) for m in sorted(ronde["matchs"], key=lambda m: m["zone"], reverse=True)]
        if ronde["statut"] == L.RONDE_TERMINEE and etat["statut"] == L.EN_COURS:
            lignes.append("⏸️ *Pause avant le round suivant.*")
    else:
        lignes.append("⏳ *Le premier round se prépare.*")
    lignes += ["", "**📊 Classement**", *lignes_classement(etat)]
    return _embeds(f"📋 {etat['titre']}", lignes, f"ID tournoi : {etat['tournoi_id']}")
