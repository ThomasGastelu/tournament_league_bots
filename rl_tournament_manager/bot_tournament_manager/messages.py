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
    "⚠️ **Ne quittez pas et ne relancez pas la partie tant que le bot n'a pas pris le score.** "
    "Le bot passe en spectateur dans chaque partie, à tour de rôle : à la fin du match, restez dans "
    "la partie jusqu'à son message « vous pouvez quitter la partie »."
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
                      "autres joueurs et commence à passer dans ta partie.")
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
        f"Sans clic, le bot passera quand même dans ta partie dans {duree_restante}.",
    ])


def mp_partie_introuvable(etat: dict, numero: int, match: dict) -> str:
    """Au capitaine, quand le bot ne trouve pas la partie qu'il a dite créée."""
    return "\n".join([
        f"⚠️ **Le bot ne trouve pas ta partie privée** — {_titre(etat)}, round {numero}, "
        f"{zone_titre(etat, match['zone'])}.",
        "Vérifie qu'elle existe avec **exactement** ce nom et ce mot de passe :",
        *_bloc_partie(match),
        "Le bot réessaie à son prochain passage.",
    ])


def reponse_pp_creee(nouveau: bool, match: dict) -> str:
    if nouveau:
        return ("✅ Merci ! Les autres joueurs sont prévenus, et le bot va passer dans ta partie. "
                "Ne la quittez pas avant son message « vous pouvez quitter la partie ».")
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
        f"**{nom_capitaine}** (capitaine de **{_nom(etat, match['equipe_a'])}**) "
        + ("a créé la partie privée. Rejoins-la avec :" if match.get("pp_creee_le")
           else "crée la partie privée (tu recevras un MP quand elle sera prête). Rejoins-la avec :"),
        *_bloc_partie(match),
        "",
        _consigne_couleurs(etat, match),
        "",
        CONSIGNE_SCORE,
    ]
    return "\n".join(lignes)


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
    """Le bot n'a pas pu prendre le score : les joueurs le déclarent (bouton sous le message)."""
    return "\n".join([
        f"📝 **Déclare le score de ton match** — {_titre(etat)}, round {numero}/{etat['nombre_de_rondes']}, "
        f"{zone_titre(etat, match['zone'])}",
        f"**{_nom(etat, equipe_id)}** vs **{_nom(etat, L.adversaire(match, equipe_id))}**",
        f"Le bot n'a pas pu prendre le score ({match['raison_a_valider']}).",
        "",
        "Quand le match est fini, clique sur **Déclarer le score** : un joueur de chaque équipe déclare, et "
        "le résultat est validé quand les deux équipes déclarent le même score. Si ce n'est pas le cas, "
        "un admin tranche.",
    ])


def secours_declaration(etat: dict, numero: int, match: dict) -> str:
    """Posté dans le salon des annonces (avec le bouton) quand le MP de déclaration est impossible."""
    return (f"je n'arrive pas à t'envoyer de MP. Le bot n'a pas pu prendre le score de ton match du tournoi "
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
    L.DECLARATION_INCOHERENTE: "⚠️ Ce score est plus bas que le dernier score vu par le bot : un admin va vérifier. "
                               "Si tu t'es trompé, reclique sur le bouton pour corriger.",
}


def mp_fin_tournoi(etat: dict, equipe_id: int) -> str:
    e = L.equipe(etat, equipe_id)
    position = L.rang(etat, equipe_id)
    medaille = MEDAILLES.get(position, "🏁")
    return (f"{medaille} Le tournoi **{_titre(etat)}** est terminé ! Ton équipe **{_nom(etat, equipe_id)}** "
            f"finit **{_rang(position)}** sur {len(etat['equipes'])} avec **{_points(e['points'])}** "
            f"({e['victoires']}V - {e['defaites']}D). Merci d'avoir joué !")


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
    if match.get("pp_creee_le"):
        qui = "La partie privée est déjà créée. Rejoins-la avec :"
    else:
        qui = (f"**{_pseudo_capitaine(etat, match)}** (capitaine de **{_nom(etat, match['equipe_a'])}**) crée la "
               "partie privée (tu recevras un MP quand elle sera prête). Rejoins-la avec :")
    return "\n".join([
        _entete_match(etat, numero, match),
        f"Ton équipe **{_nom(etat, equipe_id)}** affronte **{_nom(etat, L.adversaire(match, equipe_id))}** "
        f"({_format(etat)}).",
        "",
        qui,
        *_bloc_partie(match),
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

def regle_points(etat: dict, numero: int) -> str:
    """Barème des points au round `numero` (golden round compris)."""
    golden = L.golden_round(etat)
    if L.bonus_zone_haute(etat, numero):
        texte = "Victoire en zone haute ⭐ : +3 · victoire ailleurs : +1 · défaite : 0"
        return texte + (f" · 🌟 golden round depuis le round {golden}" if golden > 1 else "")
    return f"Toutes les victoires : +1 · défaite : 0 · 🌟 golden round au round {golden} : zone haute ⭐ +3"


def ligne_points(etat: dict) -> str:
    """Barème annoncé au lancement du tournoi."""
    return f"🏅 {regle_points(etat, 1)}"


def _annonce_golden_round(etat: dict, numero: int) -> list[str]:
    """Lignes du début de round sur le golden round (rien si le tournoi n'en a pas)."""
    golden = L.golden_round(etat)
    if golden == 1 or numero > golden:
        return []
    if numero == golden:
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
    lignes = [
        f"👋 Bienvenue dans le salon du tournoi **{_titre(etat)}** !",
        f"{len(etat['equipes'])} équipes · {etat['nombre_de_rondes']} round(s) · lancé par <@{etat['lance_par']}>.",
        "Ce salon est réservé aux joueurs du tournoi et aux admins : questions, problèmes, captures de score…",
        "🔒 Le nom et le mot de passe de chaque partie privée arrivent **en MP**.",
        "",
        "**Équipes**",
    ]
    for e in sorted(etat["equipes"].values(), key=lambda e: e["id"]):
        lignes.append(f"**{escape_markdown(e['nom'])}** : " + " ".join(f"<@{j['id']}>" for j in e["joueurs"]))
    return decouper(lignes)


def texte_arret(etat: dict) -> str:
    return f"🛑 Le tournoi **{_titre(etat)}** a été arrêté par <@{etat['arrete_par']}>."


def texte_erreur(etat: dict) -> str:
    return (f"❌ Erreur inattendue pendant le tournoi **{_titre(etat)}** : il est en pause. "
            "Redémarre le bot pour le reprendre, ou arrête-le avec `/stop_tournament_rl`.")


# --------------------------------------------------------------------------- #
# Alertes (LOG_CHANNEL)
# --------------------------------------------------------------------------- #

ALERTE_SCORE_NON_PRIS = "le bot n'a pas pu prendre le score"
ALERTE_DESACCORD = "les deux équipes n'ont pas déclaré le même score"
ALERTE_INCOHERENTE = "score déclaré plus bas que le dernier score vu par le bot"
ALERTE_PAS_DE_CLIC = "le capitaine n'a pas cliqué sur « Partie privée créée » après {duree}"
CONCLUSION_PAS_DE_CLIC = ("Le bot passe quand même dans la partie. Si elle n'existe pas, contacte le capitaine ; "
                          "si le bot ne la trouve pas, les joueurs pourront déclarer le score.")


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
        f"**Problème :** {probleme}" + (f" ({match['raison_a_valider']})" if match.get("raison_a_valider") else ""),
        "",
        "**Pour rejoindre la partie à la main**",
        *_bloc_partie(match),
        f"Créée par : <@{capitaine}> (capitaine de **{_nom(etat, a)}**)",
        _ligne_equipe_alerte(etat, match, a),
        _ligne_equipe_alerte(etat, match, b),
    ]
    if match.get("score") and match["statut"] != L.MATCH_TERMINE:
        fiable = match.get("couleurs_detectees_par") == "pseudos"
        lignes += ["", f"**Dernier score vu par le bot :** {_score(etat, match)}"
                   + ("" if fiable else " *(couleurs pas reconnues : peut-être inversé)*")]
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
# /start_tournament_rl_status
# --------------------------------------------------------------------------- #

STATUTS_TOURNOI = {L.EN_COURS: "🟢 En cours", L.TERMINE: "🏁 Terminé", L.ARRETE: "🛑 Arrêté"}


def _ligne_match_status(etat: dict, match: dict) -> str:
    duel = f"**{_nom(etat, match['equipe_a'])}** vs **{_nom(etat, match['equipe_b'])}**"
    statut = match["statut"]
    if statut == L.MATCH_TERMINE:
        etat_match = f"✅ {_score(etat, match)}"
        if _source(match) == L.SOURCE_ADMIN:
            etat_match += " *(validé par un admin)*"
        elif _source(match) == L.SOURCE_DECLARATIONS:
            etat_match += " *(déclaré par les équipes)*"
    elif statut == L.MATCH_EN_COURS:
        etat_match = f"{duel} — " + ("🎮 partie créée, en cours" if match.get("pp_creee_le")
                                      else "⏳ partie pas encore créée")
    elif statut == L.MATCH_A_VALIDER:
        nb = len(match.get("declarations") or {})
        etat_match = f"{duel} — ⚠️ à valider ({match['raison_a_valider']}) · déclarations : {nb}/2"
    elif statut == L.MATCH_ANNULE:
        etat_match = f"{duel} — 🚫 annulé"
    else:
        etat_match = f"{duel} — ⏳ en attente"
    return f"**{zone_titre(etat, match['zone'])}** : {etat_match}"


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
