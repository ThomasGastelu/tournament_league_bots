"""Lecture des fichiers d'inscription et lecture/écriture de l'état des tournois.

- Fichiers d'inscription (lecture seule) : rl_bot_ppname_creator/data/tournois/<id>.json
- État + résultats d'un tournoi lancé  : data/tournois/<id>.json
- Parties privées de chaque round       : data/pp/<id>_ronde_<n>.json
- Anciens tournois relancés             : data/archives/<id>_<date>.json

/reset_tournament_rl efface tous ces fichiers d'un tournoi (supprimer_tournoi), jamais
le fichier d'inscription.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path


def _verifier_id(tournoi_id: str) -> str:
    # Les IDs sont des nombres Discord : on refuse tout le reste
    # pour ne jamais lire/écrire en dehors des dossiers.
    tournoi_id = str(tournoi_id).strip()
    if not tournoi_id.isdigit():
        raise ValueError(f"ID de tournoi invalide : {tournoi_id!r}")
    return tournoi_id


def _lire(chemin: Path) -> dict | None:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


class Stockage:
    def __init__(self, dossier_inscriptions: Path, dossier_donnees: Path) -> None:
        self.dossier_inscriptions = Path(dossier_inscriptions)
        self.dossier_donnees = Path(dossier_donnees)
        self.dossier_etats = self.dossier_donnees / "tournois"
        self.dossier_pp = self.dossier_donnees / "pp"
        self.dossier_archives = self.dossier_donnees / "archives"
        self.dossier_salons = self.dossier_donnees / "salons"  # /start_tournament_init : salon créé avant le lancement
        for dossier in (self.dossier_etats, self.dossier_pp, self.dossier_archives, self.dossier_salons):
            dossier.mkdir(parents=True, exist_ok=True)
        self._verrous: dict[str, asyncio.Lock] = {}

    def verrou(self, tournoi_id: str) -> asyncio.Lock:
        """Un verrou par tournoi, à utiliser autour de chaque « charger → modifier → sauvegarder »."""
        return self._verrous.setdefault(str(tournoi_id).strip(), asyncio.Lock())

    # --- Fichiers d'inscription (lecture seule) --------------------------- #

    def charger_inscription(self, tournoi_id: str) -> dict | None:
        try:
            return _lire(self.dossier_inscriptions / f"{_verifier_id(tournoi_id)}.json")
        except ValueError:
            return None

    def lister_inscriptions(self, serveur_id: str | None = None) -> list[dict]:
        return self._lister(self.dossier_inscriptions, "id", serveur_id)

    # --- État des tournois lancés ---------------------------------------- #

    def charger_etat(self, tournoi_id: str) -> dict | None:
        try:
            return _lire(self.dossier_etats / f"{_verifier_id(tournoi_id)}.json")
        except ValueError:
            return None

    def sauvegarder_etat(self, etat: dict) -> None:
        """Écrit d'abord un fichier temporaire puis le remplace :
        le fichier n'est jamais à moitié écrit, même si le bot plante."""
        chemin = self.dossier_etats / f"{_verifier_id(etat['tournoi_id'])}.json"
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(json.dumps(etat, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporaire, chemin)

    def lister_etats(self, serveur_id: str | None = None) -> list[dict]:
        return self._lister(self.dossier_etats, "tournoi_id", serveur_id)

    def archiver_etat(self, tournoi_id: str, suffixe: str) -> Path | None:
        """Déplace l'état d'un ancien tournoi dans data/archives (avant de le relancer)."""
        source = self.dossier_etats / f"{_verifier_id(tournoi_id)}.json"
        if not source.exists():
            return None
        suffixe = "".join(c if c.isalnum() else "-" for c in suffixe)
        destination = self.dossier_archives / f"{source.stem}_{suffixe}.json"
        os.replace(source, destination)
        return destination

    def charger_archives(self, tournoi_id: str) -> list[dict]:
        """États archivés d'un tournoi (anciens lancements), du plus récent au plus ancien."""
        archives = []
        for chemin in sorted(self.dossier_archives.glob(f"{_verifier_id(tournoi_id)}_*.json"), reverse=True):
            try:
                donnees = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(donnees, dict):
                archives.append(donnees)
        return archives

    # --- Parties privées -------------------------------------------------- #

    def charger_init(self, tournoi_id: str) -> dict | None:
        """Ce que /start_tournament_init a créé (salon de discussion), ou None."""
        try:
            return _lire(self.dossier_salons / f"{_verifier_id(tournoi_id)}.json")
        except ValueError:
            return None

    def sauvegarder_init(self, init: dict) -> None:
        chemin = self.dossier_salons / f"{_verifier_id(init['tournoi_id'])}.json"
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(json.dumps(init, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporaire, chemin)

    def chemin_pp(self, tournoi_id: str, numero_ronde: int) -> Path:
        return self.dossier_pp / f"{_verifier_id(tournoi_id)}_ronde_{int(numero_ronde)}.json"

    # --- Remise à zéro (/reset_tournament_rl) ----------------------------- #

    def fichiers_du_tournoi(self, tournoi_id: str) -> list[Path]:
        """Tous les fichiers que ce bot a écrits pour un tournoi : état (et son .tmp),
        parties privées de chaque round, archives, salon de /start_tournament_init.
        Jamais le fichier d'inscription."""
        tournoi_id = _verifier_id(tournoi_id)
        # « <id>_ » : un autre tournoi dont l'ID commence pareil (ex. 12 et 123) n'est pas pris.
        fichiers = [self.dossier_etats / f"{tournoi_id}.json", self.dossier_etats / f"{tournoi_id}.json.tmp"]
        fichiers += self.dossier_pp.glob(f"{tournoi_id}_*")
        fichiers += self.dossier_archives.glob(f"{tournoi_id}_*")
        fichiers += [self.dossier_salons / f"{tournoi_id}.json", self.dossier_salons / f"{tournoi_id}.json.tmp"]
        return sorted(f for f in fichiers if f.is_file())

    def supprimer_tournoi(self, tournoi_id: str) -> list[Path]:
        """Efface les fichiers de fichiers_du_tournoi() et renvoie ceux qui ont été effacés."""
        supprimes = []
        for chemin in self.fichiers_du_tournoi(tournoi_id):
            try:
                chemin.unlink()
            except FileNotFoundError:
                continue
            supprimes.append(chemin)
        return supprimes

    # --------------------------------------------------------------------- #

    @staticmethod
    def _lister(dossier: Path, cle_id: str, serveur_id: str | None) -> list[dict]:
        """Tous les fichiers du dossier (du plus récent au plus ancien), éventuellement d'un seul serveur."""
        resultats = []
        for chemin in dossier.glob("*.json"):
            try:
                donnees = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(donnees, dict) or not str(donnees.get(cle_id, "")).isdigit():
                continue
            if serveur_id is None or donnees.get("serveur_id") == serveur_id:
                resultats.append(donnees)
        return sorted(resultats, key=lambda d: int(d[cle_id]), reverse=True)
