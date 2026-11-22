"""Lecture et vérification du fichier .env."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent.parent


class ErreurConfig(Exception):
    """Erreur de configuration : le message est montré tel quel."""


@dataclass(frozen=True)
class Config:
    token: str
    serveur_id: int | None
    salon_annonces: int | None
    dossier_inscriptions: Path
    script_pp: Path
    dossier_donnees: Path
    pause_entre_rondes: float
    log_channel: int | None = None
    rappel_clic_pp: float = 180       # rappel au capitaine qui n'a pas cliqué « Partie privée créée »
    attente_clic_pp_max: float = 600  # sans clic, le délai avant la demande de score démarre quand même
    delai_declaration: float = 360    # après le clic : attente avant le MP « Déclarer le score »
    pp_forcee_zone_2: tuple[str, str] | None = None  # TESTS : (nom, mot de passe) imposés à la zone 2


AIDE_TOKEN = (
    "Le bon token se trouve dans le Discord Developer Portal > ton application > onglet Bot "
    "> bouton « Reset Token ». Il ressemble à MTIz...abc.Gh1jK2.xyz... (3 morceaux séparés par des points)."
)


def probleme_token(token: str) -> str | None:
    """Repère les erreurs de copier-coller fréquentes, sans jamais afficher le token."""
    if not token:
        return "DISCORD_TOKEN manquant : mets le token du bot dans le fichier .env."
    if token.lower().startswith("bot "):
        return "Enlève « Bot » au début de DISCORD_TOKEN : mets seulement le token."
    if token.isdigit():
        return "DISCORD_TOKEN contient l'Application ID (que des chiffres), pas le token du bot."
    if re.fullmatch(r"[0-9a-fA-F]{64}", token):
        return "DISCORD_TOKEN contient la Public Key (onglet General Information), pas le token du bot."
    if token.count(".") != 2:
        return "DISCORD_TOKEN ne ressemble pas à un token de bot (c'est peut-être le Client Secret de l'onglet OAuth2)."
    return None


def _chemin(nom: str, defaut: str) -> Path:
    """Chemin du .env ; un chemin relatif part du dossier rl_tournament_manager."""
    chemin = Path(os.getenv(nom, "").strip() or defaut)
    return chemin if chemin.is_absolute() else (RACINE / chemin).resolve()


def _nombre(nom: str, defaut: float, minimum: float, maximum: float | None = None, entier: bool = False):
    brut = os.getenv(nom, "").strip()
    if not brut:
        return defaut
    try:
        valeur = int(brut) if entier else float(brut.replace(",", "."))
    except ValueError:
        raise ErreurConfig(f"{nom} doit être un nombre (valeur actuelle : {brut!r}).") from None
    if valeur < minimum or (maximum is not None and valeur > maximum):
        limite = f"entre {minimum} et {maximum}" if maximum is not None else f"au moins {minimum}"
        raise ErreurConfig(f"{nom} doit être {limite} (valeur actuelle : {brut}).")
    return valeur


def _id_salon(nom: str) -> int | None:
    brut = os.getenv(nom, "").strip().lstrip("#")
    if brut and not brut.isdigit():
        raise ErreurConfig(f"{nom} doit être l'identifiant du salon, uniquement des chiffres "
                           "(clic droit sur le salon > Copier l'identifiant), ou rester vide.")
    return int(brut) if brut else None


def _pp_forcee(nom: str) -> tuple[str, str] | None:
    """« nom:mot_de_passe » (sans « : », le mot de passe = le nom). Vide : None."""
    brut = os.getenv(nom, "").strip()
    if not brut:
        return None
    nom_pp, separateur, mot_de_passe = brut.partition(":")
    nom_pp, mot_de_passe = nom_pp.strip(), mot_de_passe.strip()
    if not nom_pp:
        raise ErreurConfig(f"{nom} doit ressembler à nom:mot_de_passe (valeur actuelle : {brut!r}).")
    return nom_pp, (mot_de_passe if separateur else nom_pp)


def charger_config() -> Config:
    load_dotenv(RACINE / ".env")

    token = os.getenv("DISCORD_TOKEN", "").strip()
    probleme = probleme_token(token)
    if probleme:
        raise ErreurConfig(f"{probleme}\n{AIDE_TOKEN}")

    serveur_id = os.getenv("GUILD_ID", "").strip()
    if serveur_id and not serveur_id.isdigit():
        raise ErreurConfig("GUILD_ID doit contenir uniquement des chiffres "
                           "(clic droit sur le serveur > Copier l'identifiant).")

    dossier_inscriptions = _chemin("DOSSIER_INSCRIPTIONS", "../rl_bot_ppname_creator/data/tournois")
    if not dossier_inscriptions.is_dir():
        raise ErreurConfig(f"Dossier des inscriptions introuvable : {dossier_inscriptions} "
                           "(DOSSIER_INSCRIPTIONS dans le .env).")
    script_pp = _chemin("SCRIPT_PP", "../rl_bot_ppname_creator/generer_pp_names.py")
    if not script_pp.is_file():
        raise ErreurConfig(f"Script des parties privées introuvable : {script_pp} (SCRIPT_PP dans le .env).")

    return Config(
        token=token,
        serveur_id=int(serveur_id) if serveur_id else None,
        salon_annonces=_id_salon("SALON_ANNONCES"),
        dossier_inscriptions=dossier_inscriptions,
        script_pp=script_pp,
        dossier_donnees=RACINE / "data",
        pause_entre_rondes=_nombre("PAUSE_ENTRE_RONDES", 60.0, 0),
        rappel_clic_pp=_nombre("RAPPEL_CLIC_PP", 180.0, 0),
        attente_clic_pp_max=_nombre("ATTENTE_CLIC_PP_MAX", 600.0, 0),
        delai_declaration=_nombre("DELAI_DECLARATION", 360.0, 0),
        pp_forcee_zone_2=_pp_forcee("PP_FORCEE_ZONE_2"),
        log_channel=_id_salon("LOG_CHANNEL"),
    )
