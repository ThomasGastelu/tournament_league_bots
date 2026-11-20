"""Fonctions sans réseau : choix des destinataires, textes affichés à l'admin, MP envoyé.

Testées dans tests/test_logique.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import discord
from discord.utils import escape_markdown

COULEUR = discord.Colour(0xE67E22)  # orange, comme les autres bots
LONGUEUR_MAX_MESSAGE = 4000         # Discord accepte 4096 caractères dans un embed
PAUSE_ENTRE_MP = 1.0                # secondes entre deux MP : Discord bloque les bots qui envoient trop vite
SECONDES_PAR_MP = 1.5               # pause + temps d'envoi, pour estimer la durée
LONGUEUR_MAX_LISTE = 600            # noms affichés dans le rapport (Discord : 2000 caractères par message)


@dataclass
class Rapport:
    total: int
    recus: int = 0
    mp_fermes: list[str] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)

    @property
    def traites(self) -> int:
        return self.recus + len(self.mp_fermes) + len(self.erreurs)


def destinataires(membres) -> list:
    """Les membres humains du serveur (les bots ne peuvent pas recevoir de MP), sans doublon."""
    vus: set[int] = set()
    resultat = []
    for membre in membres:
        if membre.bot or membre.id in vus:
            continue
        vus.add(membre.id)
        resultat.append(membre)
    return resultat


def duree_estimee(nombre: int) -> str:
    secondes = nombre * SECONDES_PAR_MP
    if secondes < 60:
        return "moins d'une minute"
    minutes = int(-(-secondes // 60))  # arrondi au-dessus
    if minutes < 60:
        return f"environ {minutes} min"
    heures, minutes = divmod(minutes, 60)
    return f"environ {heures} h {minutes:02d}"


def liste_noms(noms: list[str], limite: int = LONGUEUR_MAX_LISTE) -> str:
    """« a, b, c… et 12 autres » : jamais plus long que `limite` (+ la fin « et N autres »)."""
    texte, inclus = "", 0
    for nom in noms:
        morceau = escape_markdown(nom)
        suivant = f"{texte}, {morceau}" if texte else morceau
        if len(suivant) > limite:
            break
        texte, inclus = suivant, inclus + 1
    reste = len(noms) - inclus
    if reste:
        texte += f"{', ' if texte else ''}… et {reste} autre{'s' if reste > 1 else ''}"
    return texte


def embed_mp(texte: str, nom_serveur: str, icone_url: str | None = None) -> discord.Embed:
    """Le MP reçu par chaque membre."""
    embed = discord.Embed(description=texte, colour=COULEUR)
    embed.set_author(name=nom_serveur, icon_url=icone_url)
    embed.set_footer(text=f"Message envoyé à tous les membres de {nom_serveur}")
    return embed


def texte_apercu(nombre: int) -> str:
    if nombre == 0:
        return "❌ Aucun membre à qui envoyer ce message."
    return (
        "👀 **Aperçu** : voici le MP tel que les membres le recevront.\n"
        f"Il sera envoyé à **{nombre}** membre{'s' if nombre > 1 else ''} (les bots sont ignorés), "
        f"durée : {duree_estimee(nombre)}.\n"
        "Clique sur **Envoyer** pour confirmer (l'aperçu expire dans 5 minutes)."
    )


def texte_progression(rapport: Rapport) -> str:
    restants = rapport.total - rapport.traites
    return (
        f"📨 Envoi en cours : **{rapport.traites}/{rapport.total}** "
        f"(reçus : {rapport.recus}, MP fermés : {len(rapport.mp_fermes)}, erreurs : {len(rapport.erreurs)}).\n"
        f"Temps restant : {duree_estimee(restants)}. Le bot doit rester lancé jusqu'à la fin."
    )


def texte_rapport(rapport: Rapport) -> str:
    lignes = [f"✅ Envoi terminé : **{rapport.recus}/{rapport.total}** membres ont reçu le message."]
    if rapport.mp_fermes:
        lignes.append(f"🔒 MP fermés ({len(rapport.mp_fermes)}) : {liste_noms(rapport.mp_fermes)}")
    if rapport.erreurs:
        lignes.append(f"⚠️ Erreur d'envoi ({len(rapport.erreurs)}) : {liste_noms(rapport.erreurs)}")
    return "\n".join(lignes)


def probleme_token(token: str) -> str | None:
    """Repère les erreurs de copier-coller fréquentes, sans jamais afficher le token."""
    if not token:
        return "DISCORD_TOKEN manquant : copie .env.example en .env et mets-y le token du bot."
    if token.lower().startswith("bot "):
        return "Enlève « Bot » au début de DISCORD_TOKEN : mets seulement le token."
    if token.isdigit():
        return "DISCORD_TOKEN contient l'Application ID (que des chiffres), pas le token du bot."
    if re.fullmatch(r"[0-9a-fA-F]{64}", token):
        return "DISCORD_TOKEN contient la Public Key (onglet General Information), pas le token du bot."
    if token.count(".") != 2:
        return "DISCORD_TOKEN ne ressemble pas à un token de bot (c'est peut-être le Client Secret de l'onglet OAuth2)."
    return None
