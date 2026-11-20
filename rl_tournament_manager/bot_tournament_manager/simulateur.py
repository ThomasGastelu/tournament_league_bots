"""Simulateur de rl_api_pp_connector : produit un faux résultat de match.

Il remplace le vrai connecteur (OBSERVATEUR=simulation). Il attend une durée
aléatoire (le « match »), puis renvoie un résultat au format exact du connecteur
(voir observation.py), avec les vrais pseudos en jeu des joueurs. Tous les
matchs du round se « jouent » en même temps.

Pour tester le bot, il peut aussi :
  - inverser les couleurs (l'équipe A en Orange) : le bot doit s'en rendre compte
    grâce aux pseudos (SIMULATION_PROBA_COULEURS_INVERSEES) ;
  - ne pas avoir le score (« quitté avant la fin », « connexion perdue ») : le match
    passe « à valider », les joueurs reçoivent le bouton pour déclarer le score
    (SIMULATION_PROBA_SANS_GAGNANT).

Essai à la main :
    python -m bot_tournament_manager.simulateur --nom tomato_abc123 --bleu tomatoKing,cacacaca --orange crazyTomato,gogol
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import uuid
from datetime import datetime

from .observation import PartieAObserver

log = logging.getLogger(__name__)

ARENES = ["Stadium_P", "DFHStadium", "UF_Night_P", "EuroStadium_P", "Park_P", "TrainStation_P",
          "Utopia_Dusk_P", "Wasteland_P", "NeoTokyo_Standard_P", "beach_P"]
STATUTS_SANS_GAGNANT = ["quitté avant la fin", "connexion perdue"]


def simuler_resultat(partie: PartieAObserver, rng: random.Random, *,
                     proba_sans_gagnant: float = 0.0, proba_couleurs_inversees: float = 0.0) -> dict:
    """Faux résultat de match, au format de rl_api_pp_connector."""
    pseudos = [list(partie.pseudos_bleu), list(partie.pseudos_orange)]
    if rng.random() < proba_couleurs_inversees:
        pseudos.reverse()  # les équipes ne respectent pas la consigne de couleur

    buts = [rng.randint(0, 5), rng.randint(0, 5)]
    sans_gagnant = rng.random() < proba_sans_gagnant
    prolongation = False
    if not sans_gagnant and buts[0] == buts[1]:
        prolongation = True  # en Rocket League une égalité se termine en prolongation
        buts[rng.randint(0, 1)] += 1
    gagnant = None if sans_gagnant else (0 if buts[0] > buts[1] else 1)

    joueurs = []
    for couleur in (0, 1):
        noms = pseudos[couleur] or [f"Joueur{couleur}"]
        repartition = [0] * len(noms)
        for _ in range(buts[couleur]):
            repartition[rng.randrange(len(noms))] += 1
        for nom, nb_buts in zip(noms, repartition):
            passes, arrets, demos = rng.randint(0, 2), rng.randint(0, 4), rng.randint(0, 2)
            joueurs.append({
                "Name": nom,
                "TeamNum": couleur,
                "Score": nb_buts * 100 + passes * 50 + arrets * 50 + rng.randint(30, 200),
                "Goals": nb_buts,
                "Assists": passes,
                "Saves": arrets,
                "Shots": nb_buts + rng.randint(0, 4),
                "Demos": demos,
            })

    return {
        "date": datetime.now().isoformat(timespec="seconds"),
        "match_guid": uuid.UUID(int=rng.getrandbits(128)).hex.upper(),
        "arena": rng.choice(ARENES),
        "overtime": prolongation,
        "winner_team_num": gagnant,
        "teams": [
            {"team_num": 0, "name": "Blue", "score": buts[0]},
            {"team_num": 1, "name": "Orange", "score": buts[1]},
        ],
        "players": joueurs,
        "partie": partie.nom,
        "statut": rng.choice(STATUTS_SANS_GAGNANT) if sans_gagnant else "terminé",
        "simulation": True,
    }


class ObservateurSimule:
    """Observateur de simulation : se branche à la place du vrai connecteur."""

    def __init__(self, *, duree_min: float = 10, duree_max: float = 30, proba_sans_gagnant: float = 0.0,
                 proba_couleurs_inversees: float = 0.2, rng: random.Random | None = None) -> None:
        self.duree_min = duree_min
        self.duree_max = max(duree_min, duree_max)
        self.proba_sans_gagnant = proba_sans_gagnant
        self.proba_couleurs_inversees = proba_couleurs_inversees
        self.rng = rng or random.Random()

    async def observer(self, partie: PartieAObserver) -> dict:
        duree = self.rng.uniform(self.duree_min, self.duree_max)
        log.info("[simulation] Round %s zone %s : partie « %s » rejointe, fin du match dans %.0f s",
                 partie.ronde, partie.zone, partie.nom, duree)
        await asyncio.sleep(duree)
        resultat = simuler_resultat(partie, self.rng, proba_sans_gagnant=self.proba_sans_gagnant,
                                    proba_couleurs_inversees=self.proba_couleurs_inversees)
        scores = {t["team_num"]: t["score"] for t in resultat["teams"]}
        log.info("[simulation] Round %s zone %s : Bleu %s - %s Orange (%s)",
                 partie.ronde, partie.zone, scores[0], scores[1], resultat["statut"])
        return resultat


def main() -> None:
    parser = argparse.ArgumentParser(description="Simule un match Rocket League et affiche le résultat JSON.")
    parser.add_argument("--nom", default="tomato_test", help="nom de la partie privée")
    parser.add_argument("--bleu", default="Bleu1,Bleu2", help="pseudos en jeu de l'équipe Bleue (séparés par des virgules)")
    parser.add_argument("--orange", default="Orange1,Orange2", help="pseudos en jeu de l'équipe Orange")
    parser.add_argument("--duree", type=float, default=0, help="durée simulée du match en secondes (défaut : 0)")
    parser.add_argument("--sans-gagnant", type=float, default=0.0, help="probabilité d'un match sans vainqueur (0 à 1)")
    args = parser.parse_args()

    partie = PartieAObserver(
        tournoi_id="0", ronde=1, zone=1, nom=args.nom, mot_de_passe=args.nom,
        pseudos_bleu=tuple(p.strip() for p in args.bleu.split(",") if p.strip()),
        pseudos_orange=tuple(p.strip() for p in args.orange.split(",") if p.strip()),
    )
    observateur = ObservateurSimule(duree_min=args.duree, duree_max=args.duree,
                                    proba_sans_gagnant=args.sans_gagnant, proba_couleurs_inversees=0)
    print(json.dumps(asyncio.run(observateur.observer(partie)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
