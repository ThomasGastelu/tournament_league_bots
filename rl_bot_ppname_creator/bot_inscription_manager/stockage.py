"""Lecture et écriture des tournois : un fichier JSON par tournoi."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from .logique import completer_capitaines


class Stockage:
    def __init__(self, dossier: Path) -> None:
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self._verrous: dict[str, asyncio.Lock] = {}

    def _chemin(self, tournoi_id: str) -> Path:
        # Les IDs sont des nombres Discord : on refuse tout le reste
        # pour ne jamais lire/écrire en dehors du dossier.
        if not str(tournoi_id).isdigit():
            raise ValueError(f"ID de tournoi invalide : {tournoi_id!r}")
        return self.dossier / f"{tournoi_id}.json"

    def verrou(self, tournoi_id: str) -> asyncio.Lock:
        """Un verrou par tournoi : deux clics en même temps ne s'écrasent pas.

        À utiliser autour de chaque « charger → modifier → sauvegarder ».
        """
        return self._verrous.setdefault(str(tournoi_id), asyncio.Lock())

    def charger(self, tournoi_id: str) -> dict | None:
        try:
            chemin = self._chemin(tournoi_id)
        except ValueError:
            return None
        if not chemin.exists():
            return None
        tournoi = json.loads(chemin.read_text(encoding="utf-8"))
        completer_capitaines(tournoi)
        return tournoi

    def sauvegarder(self, tournoi: dict) -> None:
        """Écrit d'abord un fichier temporaire puis le remplace :
        le fichier n'est jamais à moitié écrit, même si le bot plante."""
        chemin = self._chemin(tournoi["id"])
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(json.dumps(tournoi, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporaire, chemin)

    def supprimer(self, tournoi_id: str) -> bool:
        """Efface le fichier du tournoi. Retourne False s'il n'existait pas."""
        try:
            self._chemin(tournoi_id).unlink()
            return True
        except (ValueError, FileNotFoundError):
            return False

    def lister(self, serveur_id: str | None = None) -> list[dict]:
        """Tous les tournois (du plus récent au plus ancien), éventuellement d'un seul serveur."""
        tournois = []
        for chemin in self.dossier.glob("*.json"):
            try:
                tournoi = json.loads(chemin.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            completer_capitaines(tournoi)
            if serveur_id is None or tournoi.get("serveur_id") == serveur_id:
                tournois.append(tournoi)
        return sorted(tournois, key=lambda t: int(t["id"]), reverse=True)
