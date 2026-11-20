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
class ReglagesRL:
    """Réglages du vrai connecteur (OBSERVATEUR=rl)."""
    dossier_connecteur: Path
    positions: Path
    resolution: tuple[int, int] | None  # None : celle de positions.json (calibration)
    langue: str
    tentatives: int             # échecs de suite avant d'abandonner une partie
    timeout_rejoindre: float    # secondes max pour entrer dans une partie
    delai_menus: float          # pause entre deux écrans de menu
    duree_lecture: float        # secondes passées dans une partie pour lire le score
    pause_apres_sortie: float   # retour au menu principal après avoir quitté une partie
    echap_retour_menu: int = 4  # appuis sur Échap pour revenir au menu après un échec
    hote: str = "127.0.0.1"
    port: int = 49123
    tesseract: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


@dataclass(frozen=True)
class Config:
    token: str
    serveur_id: int | None
    salon_annonces: int | None
    dossier_inscriptions: Path
    script_pp: Path
    dossier_donnees: Path
    pause_entre_rondes: float
    observateur: str
    simulation_duree_min: float
    simulation_duree_max: float
    simulation_proba_sans_gagnant: float
    simulation_proba_couleurs_inversees: float
    log_channel: int | None = None
    rl: ReglagesRL | None = None
    rappel_clic_pp: float = 180       # rappel au capitaine qui n'a pas cliqué « Partie privée créée »
    attente_clic_pp_max: float = 600  # sans clic, le bot passe quand même dans la partie


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


def charger_reglages_rl() -> ReglagesRL:
    """Réglages RL_* du .env (load_dotenv doit déjà avoir été appelé)."""
    dossier = _chemin("RL_DOSSIER_CONNECTEUR", "../rl_api_pp_connector")
    brut = os.getenv("RL_RESOLUTION", "").strip().lower().replace(" ", "")
    resolution = None
    if brut:
        morceaux = brut.split("x")
        if len(morceaux) != 2 or not all(m.isdigit() for m in morceaux):
            raise ErreurConfig(f"RL_RESOLUTION doit ressembler à 1920x1080 (valeur actuelle : {brut!r}).")
        resolution = (int(morceaux[0]), int(morceaux[1]))
    langue = os.getenv("RL_LANGUE", "").strip().lower() or "en"
    if langue not in ("en", "fr"):
        raise ErreurConfig("RL_LANGUE doit valoir « en » ou « fr » (la langue de Rocket League).")
    positions = os.getenv("RL_POSITIONS", "").strip()
    return ReglagesRL(
        dossier_connecteur=dossier,
        positions=_chemin("RL_POSITIONS", "") if positions else dossier / "positions.json",
        resolution=resolution,
        langue=langue,
        tentatives=_nombre("RL_TENTATIVES", 3, 1, entier=True),
        timeout_rejoindre=_nombre("RL_TIMEOUT_REJOINDRE", 45.0, 5),
        delai_menus=_nombre("RL_DELAI_MENUS", 1.5, 0),
        duree_lecture=_nombre("RL_DUREE_LECTURE", 5.0, 1),
        pause_apres_sortie=_nombre("RL_PAUSE_APRES_SORTIE", 8.0, 0),
        echap_retour_menu=_nombre("RL_ECHAP_RETOUR_MENU", 4, 0, 10, entier=True),
    )


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

    observateur = (os.getenv("OBSERVATEUR", "").strip().lower() or "simulation")
    if observateur not in ("simulation", "rl"):
        raise ErreurConfig("OBSERVATEUR doit valoir « simulation » ou « rl ».")

    duree_min = _nombre("SIMULATION_DUREE_MIN", 10.0, 0)
    duree_max = _nombre("SIMULATION_DUREE_MAX", 30.0, 0)
    if duree_max < duree_min:
        raise ErreurConfig("SIMULATION_DUREE_MAX doit être plus grand que SIMULATION_DUREE_MIN.")

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
        observateur=observateur,
        simulation_duree_min=duree_min,
        simulation_duree_max=duree_max,
        simulation_proba_sans_gagnant=_nombre("SIMULATION_PROBA_SANS_GAGNANT", 0.0, 0, 1),
        simulation_proba_couleurs_inversees=_nombre("SIMULATION_PROBA_COULEURS_INVERSEES", 0.2, 0, 1),
        log_channel=_id_salon("LOG_CHANNEL"),
        rl=charger_reglages_rl() if observateur == "rl" else None,
    )
