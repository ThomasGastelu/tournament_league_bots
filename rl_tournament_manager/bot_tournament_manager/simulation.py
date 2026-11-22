"""Mode simulation (SIMULATION=1 dans le .env) : un tournoi se joue tout seul, sans joueurs.

Pour chaque match :
  1. le capitaine « clique » sur « Partie privée créée » après `delai_clic` secondes ;
  2. le bot attend DELAI_DECLARATION comme en vrai, puis envoie les MP de déclaration ;
  3. chaque équipe déclare un score tiré au hasard après `delai_declaration` secondes.
     Les deux équipes déclarent le même score (match validé tout seul), sauf avec
     `proba_desaccord` : elles déclarent alors des scores différents, et un admin
     doit trancher avec /set_result_tournament_rl.

La simulation passe par les mêmes fonctions que les boutons Discord
(signaler_pp_creee, declarer_score) : tout le reste du tournoi se déroule comme en vrai.
Les vrais MP partent quand même aux joueurs inscrits : à utiliser sur un tournoi de test.

Pour voir un score simulé sans Discord :
    python -m bot_tournament_manager.simulation
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
from collections.abc import Coroutine
from typing import TYPE_CHECKING

from . import logique as L

if TYPE_CHECKING:
    from .deroulement import GestionnaireTournois

log = logging.getLogger(__name__)

PAR_SIMULATION = "simulation"  # « par » des clics et déclarations faits par la simulation (si pas de joueur)


def score_au_hasard(rng: random.Random) -> tuple[int, int]:
    """Score (équipe A, équipe B) d'un match simulé : jamais d'égalité, comme en Rocket League."""
    gagnant = rng.randint(1, 5)
    perdant = rng.randint(0, gagnant - 1)
    return (gagnant, perdant) if rng.random() < 0.5 else (perdant, gagnant)


def score_different(score: tuple[int, int], rng: random.Random) -> tuple[int, int]:
    """Un autre score (A, B), sans égalité : ce que déclare l'équipe B en cas de désaccord."""
    while True:
        autre = score_au_hasard(rng)
        if autre != score:
            return autre


class Simulation:
    def __init__(self, *, delai_clic: float = 5, delai_declaration: float = 5, proba_desaccord: float = 0,
                 rng: random.Random | None = None) -> None:
        self.delai_clic = delai_clic
        self.delai_declaration = delai_declaration
        self.proba_desaccord = proba_desaccord
        self.rng = rng or random.Random()
        self.gestionnaire: GestionnaireTournois | None = None
        self._taches: set[asyncio.Task] = set()

    def brancher(self, gestionnaire: GestionnaireTournois) -> None:
        self.gestionnaire = gestionnaire

    # Appelés par le gestionnaire (sans attendre : la simulation tourne dans ses propres tâches).

    def match_lance(self, etat: dict, numero: int, match: dict) -> None:
        """MP du match envoyés : le capitaine va « cliquer » sur « Partie privée créée »."""
        if match.get("pp_creee_le"):
            return
        capitaine = L.equipe(etat, match["equipe_a"])["capitaine_id"]
        self._lancer(self._cliquer(etat["tournoi_id"], numero, match["zone"], capitaine))

    def confirmations_demandees(self, init: dict) -> None:
        """/start_tournament_init : le capitaine de chaque équipe va « valider » sa participation."""
        for equipe in init["equipes"].values():
            self._lancer(self._valider(init["tournoi_id"], equipe["id"], equipe["capitaine_id"]))

    def declarations_demandees(self, etat: dict, numero: int, match: dict) -> None:
        """MP de déclaration envoyés : les deux équipes vont déclarer un score."""
        score_a = score_au_hasard(self.rng)
        desaccord = self.rng.random() < self.proba_desaccord
        score_b = score_different(score_a, self.rng) if desaccord else score_a
        log.info("[simulation] Tournoi %s, round %s, zone %s : déclarations %s-%s / %s-%s%s", etat["tournoi_id"],
                 numero, match["zone"], *score_a, *score_b, " (désaccord)" if desaccord else "")
        for equipe_id, (a, b) in ((match["equipe_a"], score_a), (match["equipe_b"], score_b)):
            pour, contre = (a, b) if equipe_id == match["equipe_a"] else (b, a)
            joueurs = L.equipe(etat, equipe_id)["joueurs"]
            par = joueurs[0]["id"] if joueurs else PAR_SIMULATION
            self._lancer(self._declarer(etat["tournoi_id"], numero, match["zone"], equipe_id, pour, contre, par))

    async def fermer(self) -> None:
        taches = list(self._taches)
        for tache in taches:
            tache.cancel()
        await asyncio.gather(*taches, return_exceptions=True)

    # ------------------------------------------------------------------- #

    def _lancer(self, coro: Coroutine) -> None:
        tache = asyncio.create_task(coro)
        self._taches.add(tache)
        tache.add_done_callback(self._taches.discard)

    async def _cliquer(self, tournoi_id: str, numero: int, zone: int, capitaine: str) -> None:
        await asyncio.sleep(self.delai_clic)
        try:
            await self.gestionnaire.signaler_pp_creee(tournoi_id, numero, zone, par=capitaine)
        except L.ErreurTournoi as erreur:  # tournoi arrêté, match validé par un admin…
            log.info("[simulation] Tournoi %s, round %s, zone %s : clic ignoré (%s)", tournoi_id, numero, zone, erreur)
        except Exception:
            log.exception("[simulation] Tournoi %s, round %s, zone %s : erreur au clic", tournoi_id, numero, zone)

    async def _valider(self, tournoi_id: str, equipe_id: int, capitaine: str) -> None:
        await asyncio.sleep(self.delai_clic)
        try:
            await self.gestionnaire.valider_participation(tournoi_id, equipe_id, par=capitaine)
        except L.ErreurTournoi as erreur:
            log.info("[simulation] Tournoi %s, équipe %s : validation ignorée (%s)", tournoi_id, equipe_id, erreur)
        except Exception:
            log.exception("[simulation] Tournoi %s, équipe %s : erreur à la validation", tournoi_id, equipe_id)

    async def _declarer(self, tournoi_id: str, numero: int, zone: int, equipe_id: int, pour: int, contre: int,
                        par: str) -> None:
        await asyncio.sleep(self.delai_declaration)
        try:
            await self.gestionnaire.declarer_score(tournoi_id, numero, zone, equipe_id, pour, contre, par=par)
        except L.ErreurTournoi as erreur:
            log.info("[simulation] Tournoi %s, round %s, zone %s : déclaration ignorée (%s)",
                     tournoi_id, numero, zone, erreur)
        except Exception:
            log.exception("[simulation] Tournoi %s, round %s, zone %s : erreur à la déclaration",
                          tournoi_id, numero, zone)


def main() -> None:
    parser = argparse.ArgumentParser(description="Affiche des scores simulés (équipe A - équipe B).")
    parser.add_argument("--matchs", type=int, default=5, help="nombre de scores à tirer")
    parser.add_argument("--graine", type=int, default=None, help="graine du hasard (pour rejouer les mêmes scores)")
    args = parser.parse_args()
    rng = random.Random(args.graine)
    for i in range(1, args.matchs + 1):
        a, b = score_au_hasard(rng)
        print(f"Match {i} : équipe A {a} - {b} équipe B")


if __name__ == "__main__":
    main()
