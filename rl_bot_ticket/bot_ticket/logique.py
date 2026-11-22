"""Règles pures, sans Discord ni réseau : catégories de tickets, nom et sujet des salons,
droits de fermeture, fermeture automatique, réglages du .env, copie de la conversation.

Testées dans tests/test_logique.py.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

NOM_CATEGORIE_PAR_DEFAUT = "Support"   # catégorie Discord utilisée si CATEGORIE_TICKETS est vide
DELAI_SUPPRESSION = 5                  # secondes entre la fermeture et la suppression du salon
MESSAGES_MAX_TRANSCRIPTION = 1000      # messages recopiés dans le salon de logs à la fermeture
LONGUEUR_MAX_NOM_SALON = 90            # Discord : 100 caractères par nom de salon
FERMETURE_AUTO_HEURES = 72.0           # par défaut : sans réponse du membre 72 h après le staff, le ticket se ferme
VERIFICATION_AUTO_MINUTES = 10         # les tickets inactifs sont cherchés toutes les 10 minutes
MESSAGES_LUS_VERIFICATION = 50         # derniers messages lus pour savoir qui a parlé en dernier

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
    fermeture_auto_heures: float = FERMETURE_AUTO_HEURES  # 0 = jamais de fermeture automatique


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
    texte_heures = (env.get("FERMETURE_AUTO_HEURES") or "").strip().replace(",", ".")
    try:
        heures = float(texte_heures) if texte_heures else FERMETURE_AUTO_HEURES
    except ValueError:
        heures = -1.0
    if not heures >= 0:  # refuse aussi « nan »
        raise ErreurReglage("FERMETURE_AUTO_HEURES doit être un nombre d'heures (ex. 72, ou 0 pour ne jamais "
                            "fermer les tickets automatiquement).")
    return Reglages(
        fermeture_auto_heures=heures,
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


def est_auteur(membre_id: int, auteur_id: int) -> bool:
    """Seul l'auteur du ticket peut confirmer que son problème est résolu."""
    return membre_id == auteur_id


@dataclass(frozen=True)
class MessageVu:
    """Ce qu'il faut savoir d'un message pour la fermeture automatique."""
    auteur_id: int
    est_bot: bool
    date: datetime


def doit_fermer_auto(messages: Iterable[MessageVu], auteur_id: int, maintenant: datetime,
                     heures: float) -> bool:
    """True si le dernier message écrit par un humain vient du staff (pas de l'auteur du ticket)
    et date d'au moins `heures`. Les messages du bot ne comptent pas. 0 heure = jamais."""
    if heures <= 0:
        return False
    humains = [m for m in messages if not m.est_bot]
    if not humains:
        return False
    dernier = max(humains, key=lambda m: m.date)
    return dernier.auteur_id != auteur_id and maintenant - dernier.date >= timedelta(hours=heures)


def texte_heures(heures: float) -> str:
    """24 → « 24 h », 1.5 → « 1 h 30 », 0.5 → « 30 min »."""
    minutes = round(heures * 60)
    h, m = divmod(minutes, 60)
    if not h:
        return f"{m} min"
    return f"{h} h {m:02d}" if m else f"{h} h"


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
