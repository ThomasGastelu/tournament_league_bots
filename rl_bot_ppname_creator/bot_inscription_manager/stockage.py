"""Stockage des tournois dans des fichiers JSON (un par tournoi), sans base de données.

C'est le stockage utilisé quand `API_URL` est vide dans le `.env`. Avec `API_URL`,
le bot utilise `StockageAPI` (stockage_api.py), qui a exactement les mêmes méthodes
asynchrones : le reste du bot ne sait pas lequel des deux il utilise.

Chaque opération (inscrire, confirmer, annuler…) fait « charger → modifier → sauvegarder »
sous le verrou du tournoi, avec les règles de logique.py.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from . import logique as L
from .logique import completer_capitaines


class StockageFichiers:
    def __init__(self, dossier: Path) -> None:
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self._verrous: dict[str, asyncio.Lock] = {}

    # ----------------------------------------------------------------------- #
    # Fichiers
    # ----------------------------------------------------------------------- #

    def _chemin(self, tournoi_id: str) -> Path:
        # Les IDs sont des nombres Discord : on refuse tout le reste
        # pour ne jamais lire/écrire en dehors du dossier.
        if not str(tournoi_id).isdigit():
            raise ValueError(f"ID de tournoi invalide : {tournoi_id!r}")
        return self.dossier / f"{tournoi_id}.json"

    def verrou(self, tournoi_id: str) -> asyncio.Lock:
        """Un verrou par tournoi : deux clics en même temps ne s'écrasent pas."""
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

    def effacer(self, tournoi_id: str) -> bool:
        """Efface le fichier du tournoi. Retourne False s'il n'existait pas."""
        try:
            self._chemin(tournoi_id).unlink()
            return True
        except (ValueError, FileNotFoundError):
            return False

    def tous(self, serveur_id: str | None = None) -> list[dict]:
        """Tous les tournois complets (du plus récent au plus ancien), éventuellement d'un seul serveur."""
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

    def _exiger(self, tournoi_id: str) -> dict:
        tournoi = self.charger(tournoi_id)
        if tournoi is None:
            raise L.ErreurTournoi("Ce tournoi n'existe plus.")
        return tournoi

    # ----------------------------------------------------------------------- #
    # Opérations utilisées par le bot (mêmes signatures que StockageAPI)
    # ----------------------------------------------------------------------- #

    async def fermer(self) -> None:
        """Rien à fermer pour des fichiers (StockageAPI ferme sa connexion HTTP)."""

    async def lister(self, serveur_id: str) -> list[dict]:
        """Résumé des tournois d'un serveur : id, titre, date."""
        return [{"id": t["id"], "titre": t["titre"], "date": t["date"]} for t in self.tous(serveur_id)]

    async def lire(self, tournoi_id: str) -> dict | None:
        return self.charger(tournoi_id)

    async def creer(self, tournoi: dict) -> dict:
        async with self.verrou(tournoi["id"]):
            if self.charger(tournoi["id"]) is not None:
                raise L.ErreurTournoi("Ce tournoi existe déjà.")
            self.sauvegarder(tournoi)
        return tournoi

    async def supprimer(self, tournoi_id: str) -> dict | None:
        """Efface le tournoi et le renvoie tel qu'il était (None s'il n'existait pas)."""
        async with self.verrou(tournoi_id):
            tournoi = self.charger(tournoi_id)
            if tournoi is not None:
                self.effacer(tournoi_id)
        return tournoi

    async def modifier(
        self, tournoi_id: str, *, titre: str | None = None, cashprize: str | None = None,
        equipes_max: int | None = None,
    ) -> tuple[dict, list[tuple[str, object, object]], list[dict]]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            changements, promues = L.modifier_tournoi(
                tournoi, titre=titre, cashprize=cashprize, equipes_max=equipes_max)
            if changements:
                self.sauvegarder(tournoi)
        return tournoi, changements, promues

    async def inscrire(
        self, tournoi_id: str, *, nom: str, capitaine: tuple[str, str], pseudo_jeu_capitaine: str,
        coequipiers: list[tuple[str, str]], maintenant: str,
    ) -> tuple[dict, dict]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            equipe = L.inscrire_equipe(
                tournoi, nom=nom, capitaine=capitaine, pseudo_jeu_capitaine=pseudo_jeu_capitaine,
                coequipiers=coequipiers, maintenant=maintenant)
            self.sauvegarder(tournoi)
        return tournoi, equipe

    async def confirmer(
        self, tournoi_id: str, equipe_id: int, joueur_id: str, pseudo_jeu: str, maintenant: str,
    ) -> tuple[dict, dict]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            equipe = L.confirmer_joueur(tournoi, equipe_id, joueur_id, pseudo_jeu, maintenant)
            self.sauvegarder(tournoi)
        return tournoi, equipe

    async def refuser(
        self, tournoi_id: str, equipe_id: int, joueur_id: str, maintenant: str,
    ) -> tuple[dict, dict, list[dict]]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            equipe, promues = L.refuser_joueur(tournoi, equipe_id, joueur_id, maintenant)
            self.sauvegarder(tournoi)
        return tournoi, equipe, promues

    async def annuler_equipe(
        self, tournoi_id: str, equipe_id: int, raison: str, maintenant: str,
    ) -> tuple[dict, dict, list[dict]]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            equipe, promues = L.annuler_equipe(tournoi, equipe_id, raison, maintenant)
            self.sauvegarder(tournoi)
        return tournoi, equipe, promues

    async def reserver(
        self, tournoi_id: str, *, nom: str, capitaine: tuple[str, str], duree_minutes: int, cree_par: str,
        maintenant: str,
    ) -> tuple[dict, dict]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            reservation = L.reserver_place(
                tournoi, nom=nom, capitaine=capitaine, duree_minutes=duree_minutes, cree_par=cree_par,
                maintenant=maintenant)
            self.sauvegarder(tournoi)
        return tournoi, reservation

    async def annuler_reservation(
        self, tournoi_id: str, reservation_id: int, maintenant: str,
    ) -> tuple[dict, dict, list[dict]]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            reservation, promues = L.annuler_reservation(tournoi, reservation_id, maintenant)
            self.sauvegarder(tournoi)
        return tournoi, reservation, promues

    async def modifier_joueur(
        self, tournoi_id: str, joueur_id: str, *, pseudo: str | None = None, pseudo_jeu: str | None = None,
    ) -> tuple[dict, dict, dict, list[tuple[str, object, object]]]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            equipe, joueur, changements = L.modifier_joueur(
                tournoi, joueur_id, pseudo=pseudo, pseudo_jeu=pseudo_jeu)
            if changements:
                self.sauvegarder(tournoi)
        return tournoi, equipe, joueur, changements

    async def remplacer_joueur(
        self, tournoi_id: str, ancien_id: str, nouveau: tuple[str, str], pseudo_jeu: str,
    ) -> tuple[dict, dict, dict, dict]:
        async with self.verrou(tournoi_id):
            tournoi = self._exiger(tournoi_id)
            equipe, ancien, remplacant = L.remplacer_joueur(tournoi, ancien_id, nouveau, pseudo_jeu)
            self.sauvegarder(tournoi)
        return tournoi, equipe, ancien, remplacant

    async def echeances(self, maintenant: str) -> list[dict]:
        """Désinscrit les équipes hors délai, rend les réservations échues et ouvre les inscriptions.

        Retourne un élément par tournoi modifié, au même format que POST /api/bot/maintenance/tick :
        {tournoi, equipes_expirees: [{equipe, retardataires}], reservations_expirees, promues,
        inscriptions_ouvertes}.
        """
        resultats = []
        for resume in self.tous():
            async with self.verrou(resume["id"]):
                tournoi = self.charger(resume["id"])
                if tournoi is None:
                    continue
                expirees, promues = L.expirer_equipes(tournoi, maintenant)
                reservations_expirees, promues_reservations = L.expirer_reservations(tournoi, maintenant)
                ouverture = L.ouvrir_inscriptions(tournoi, maintenant)
                if not (expirees or reservations_expirees or ouverture):
                    continue
                self.sauvegarder(tournoi)
            resultats.append({
                "tournoi": tournoi,
                "equipes_expirees": [{"equipe": e, "retardataires": L.joueurs_en_attente(e)} for e in expirees],
                "reservations_expirees": reservations_expirees,
                "promues": promues + promues_reservations,
                "inscriptions_ouvertes": ouverture,
            })
        return resultats


# Ancien nom, gardé pour les tests et le code existant.
Stockage = StockageFichiers
