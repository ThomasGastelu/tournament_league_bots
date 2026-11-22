"""Textes et embeds affichés par le bot : panneau « Support », accueil du ticket, messages."""

from __future__ import annotations

import discord

from .logique import DELAI_SUPPRESSION, Categorie, texte_heures

# Bleu Discord, comme sur le modèle du panneau Support (les autres bots sont en orange 0xE67E22).
COULEUR = discord.Colour(0x5865F2)

TEXTE_CHOIX = "📩 Choisis la catégorie de ta demande :"
TEXTE_CHOIX_EXPIRE = "⌛ Choix expiré : clique à nouveau sur **Créer un ticket**."
TEXTE_PAS_LE_DROIT = "❌ Seuls l'auteur du ticket et le staff peuvent le fermer."
TEXTE_RESOLU_RESERVE = ("❌ Seul l'auteur du ticket peut confirmer que son problème est résolu. "
                        "Le staff peut utiliser **Fermer le ticket**.")
TEXTE_PAS_UN_TICKET = "❌ Ce salon n'est pas un ticket (son sujet a peut-être été modifié)."
TEXTE_FERMETURE_ANNULEE = "👍 Le ticket reste ouvert."
TEXTE_PERMISSION = (
    "❌ Le bot n'a pas le droit de créer le salon. Dans Paramètres du serveur > Rôles > rôle du bot, "
    "coche **Gérer les salons**, et vérifie qu'il voit la catégorie des tickets."
)
TEXTE_ERREUR = "❌ Une erreur inattendue est survenue."


def embed_panneau() -> discord.Embed:
    """Le message permanent avec le bouton « Créer un ticket »."""
    return discord.Embed(
        title="Support",
        description=(
            "Besoin d'aide ? Clique sur le bouton ci-dessous pour ouvrir un ticket.\n\n"
            "Un membre du staff te répondra dès que possible dans la catégorie support."
        ),
        colour=COULEUR,
    )


def embed_ticket(categorie: Categorie, auteur_mention: str, fermeture_auto_heures: float = 0) -> discord.Embed:
    """Premier message du salon du ticket."""
    description = (
        f"Bienvenue {auteur_mention} !\n\n"
        f"{categorie.consigne}\n\n"
        "Un membre du staff te répondra dès que possible. "
        "Quand ta demande est réglée, clique sur **✅ Problème résolu**."
    )
    if fermeture_auto_heures > 0:
        description += (f"\n\n⌛ Si tu ne réponds plus pendant {texte_heures(fermeture_auto_heures)} "
                        "après une réponse du staff, le ticket se ferme tout seul.")
    embed = discord.Embed(title=f"{categorie.emoji} {categorie.nom}", description=description, colour=COULEUR)
    embed.set_footer(text=categorie.description)
    return embed


def texte_ticket_cree(salon_mention: str) -> str:
    return f"✅ Ton ticket est ouvert : {salon_mention}"


def texte_deja_ouvert(salon_mention: str) -> str:
    return f"📩 Tu as déjà un ticket ouvert : {salon_mention}. Ferme-le avant d'en ouvrir un autre."


def texte_confirmation_fermeture() -> str:
    return "🔒 Fermer ce ticket ? Le salon sera supprimé et la conversation ne sera plus visible."


def texte_ferme_par(nom: str) -> str:
    return f"🔒 Ticket fermé par **{discord.utils.escape_markdown(nom)}**. Suppression du salon dans {DELAI_SUPPRESSION} secondes."


def texte_log_ouverture(categorie: Categorie, auteur_mention: str, salon_mention: str) -> str:
    return f"📩 {auteur_mention} a ouvert un ticket **{categorie.nom}** : {salon_mention}"


def texte_resolu_par(nom: str) -> str:
    return (f"✅ **{discord.utils.escape_markdown(nom)}** a confirmé que le problème est résolu. "
            f"Suppression du salon dans {DELAI_SUPPRESSION} secondes.")


def texte_ferme_auto(heures: float) -> str:
    return (f"⌛ Pas de réponse depuis {texte_heures(heures)} après la réponse du staff : ticket fermé "
            f"automatiquement. Suppression du salon dans {DELAI_SUPPRESSION} secondes.")


def texte_log_fermeture(categorie_nom: str, salon_nom: str, auteur_mention: str, comment: str) -> str:
    """`comment` : « fermé par @Modo », « résolu (confirmé par l'auteur) », « fermé automatiquement… »."""
    return (f"🔒 Ticket **{categorie_nom}** `#{salon_nom}` de {auteur_mention} {comment}. "
            "Copie de la conversation ci-jointe.")
