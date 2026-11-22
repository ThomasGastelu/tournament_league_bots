"""Règles pures, sans Discord ni réseau : catégories de tickets, nom et sujet des salons,
droits de fermeture, réglages du .env, copie de la conversation.

Testées dans tests/test_logique.py.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

NOM_CATEGORIE_PAR_DEFAUT = "Support"   # catégorie Discord utilisée si CATEGORIE_TICKETS est vide
DELAI_SUPPRESSION = 5                  # secondes entre la fermeture et la suppression du salon
MESSAGES_MAX_TRANSCRIPTION = 1000      # messages recopiés dans le salon de logs à la fermeture
LONGUEUR_MAX_NOM_SALON = 90            # Discord : 100 caractères par nom de salon

# Le sujet de chaque salon de ticket se termine par « ticket:<id auteur>:<catégorie> ».
# Le bot y retrouve l'auteur et la catégorie, même après un redémarrage, sans aucun fichier.
MOTIF_SUJET = re.compile(r"ticket:(\d+):([a-z_]+)")


@dataclass(frozen=True)
class Categorie:
    cle: str            # sert aussi de début au nom du salon (« aide-thomas »)
    nom: str
    emoji: str
    description: str    # affichée sous le nom dans la liste (100 caractères max)
    consigne: str       # affichée dans le salon du ticket : ce que le membre doit écrire


CATEGORIES: tuple[Categorie, ...] = (
    Categorie(
        "recrutement", "Recrutement modérateur", "🛡️",
        "Postuler pour rejoindre l'équipe de modération du serveur.",
        "Présente-toi : ton âge, tes disponibilités, ton expérience de modération "
        "et pourquoi tu veux rejoindre le staff.",
    ),
    Categorie(
        "aide", "Demande d'aide", "👤",
        "Question générale, aide sur le serveur ou problème avec un membre.",
        "Explique ta question ou ton problème le plus précisément possible.",
    ),
    Categorie(
        "technique", "Problème technique", "⚙️",
        "Bug du bot, problème de rôles, accès aux salons ou dysfonctionnement Discord.",
        "Décris le problème : ce que tu faisais, ce qui s'est passé, "
        "et ajoute une capture d'écran si possible.",
    ),
    Categorie(
        "partenariat", "Partenariat", "🤝",
        "Demande de partenariat avec un autre serveur, organisateur ou créateur de contenu.",
        "Présente ton serveur ou ton projet (lien, nombre de membres, ce que tu proposes).",
    ),
    Categorie(
        "suggestion", "Proposition / Suggestion", "📢",
        "Proposer un tournoi, une amélioration du serveur ou une nouvelle fonctionnalité.",
        "Détaille ton idée : ce que tu proposes et ce que ça apporterait au serveur.",
    ),
    Categorie(
        "signalement", "Signalement", "🚨",
        "Signaler un joueur, un membre du staff ou un comportement inapproprié.",
        "Indique qui tu signales, ce qui s'est passé et quand, avec des captures d'écran si possible. "
        "Ce salon n'est visible que par toi et le staff.",
    ),
    Categorie(
        "autre", "Autre", "❓",
        "Si la demande ne correspond à aucune des catégories précédentes.",
        "Explique ta demande, un membre du staff va te répondre.",
    ),
)
CATEGORIES_PAR_CLE: dict[str, Categorie] = {c.cle: c for c in CATEGORIES}


class ErreurReglage(Exception):
    """Une valeur du .env est invalide (le message dit laquelle et comment la corriger)."""


@dataclass(frozen=True)
class Reglages:
    categorie_id: int | None = None
    roles_staff: tuple[int, ...] = field(default_factory=tuple)
    log_channel: int | None = None


def _identifiant(env: Mapping[str, str], cle: str) -> int | None:
    valeur = (env.get(cle) or "").strip()
    if not valeur:
        return None
    if not valeur.isdigit():
        raise ErreurReglage(f"{cle} doit contenir uniquement des chiffres (clic droit > Copier l'identifiant).")
    return int(valeur)


def lire_reglages(env: Mapping[str, str]) -> Reglages:
    roles: list[int] = []
    for morceau in (env.get("ROLES_STAFF") or "").replace(";", ",").split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if not morceau.isdigit():
            raise ErreurReglage(
                f"ROLES_STAFF : « {morceau} » n'est pas un ID de rôle. Mets les ID séparés par des virgules "
                "(Paramètres du serveur > Rôles > clic droit sur le rôle > Copier l'identifiant).")
        roles.append(int(morceau))
    return Reglages(
        categorie_id=_identifiant(env, "CATEGORIE_TICKETS"),
        roles_staff=tuple(dict.fromkeys(roles)),  # sans doublon, dans l'ordre
        log_channel=_identifiant(env, "LOG_CHANNEL"),
    )


def simplifier(texte: str) -> str:
    """« Thömas_RL ⭐ » → « thomas-rl » : ce que Discord accepte dans un nom de salon."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")


def nom_salon(categorie: Categorie, pseudo: str) -> str:
    morceau = simplifier(pseudo) or "membre"
    return f"{categorie.cle}-{morceau}"[:LONGUEUR_MAX_NOM_SALON].rstrip("-")


def sujet_salon(categorie: Categorie, auteur_id: int, auteur_nom: str) -> str:
    return f"{categorie.emoji} {categorie.nom} · ouvert par {auteur_nom} · ticket:{auteur_id}:{categorie.cle}"


def lire_sujet(sujet: str | None) -> tuple[int, Categorie] | None:
    """(id de l'auteur, catégorie) si le salon est un ticket, sinon None."""
    trouve = MOTIF_SUJET.search(sujet or "")
    if not trouve or trouve[2] not in CATEGORIES_PAR_CLE:
        return None
    return int(trouve[1]), CATEGORIES_PAR_CLE[trouve[2]]


def ticket_ouvert(salons: Iterable, auteur_id: int):
    """Le salon de ticket déjà ouvert par ce membre (un seul à la fois), ou None."""
    for salon in salons:
        infos = lire_sujet(getattr(salon, "topic", None))
        if infos and infos[0] == auteur_id:
            return salon
    return None


def peut_fermer(membre_id: int, roles_membre: Iterable[int], gere_les_salons: bool,
                auteur_id: int, roles_staff: Iterable[int]) -> bool:
    """L'auteur du ticket, le staff (ROLES_STAFF) et ceux qui peuvent gérer les salons."""
    return membre_id == auteur_id or gere_les_salons or bool(set(roles_membre) & set(roles_staff))


@dataclass(frozen=True)
class MessageCopie:
    date: str
    auteur: str
    contenu: str
    pieces_jointes: tuple[str, ...] = ()


def texte_transcription(titre: str, messages: Iterable[MessageCopie]) -> str:
    """La conversation du ticket en texte brut, déposée en fichier dans LOG_CHANNEL."""
    lignes = [titre, "=" * len(titre), ""]
    for message in messages:
        lignes.append(f"[{message.date}] {message.auteur} : {message.contenu}".rstrip())
        lignes.extend(f"    📎 {url}" for url in message.pieces_jointes)
    if len(lignes) == 3:
        lignes.append("(aucun message)")
    return "\n".join(lignes) + "\n"


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
