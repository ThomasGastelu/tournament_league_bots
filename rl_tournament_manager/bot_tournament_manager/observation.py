"""Ce que le bot attend d'un « observateur » : prendre le score d'un match joué
dans une partie privée.

Tous les matchs d'un round se jouent en même temps : observer() est appelé pour
chaque zone en même temps, et chaque appel attend le score de son match.

Deux observateurs (choisis avec OBSERVATEUR dans le .env) :
  - simulation : simulateur.py   — résultats aléatoires, pour tester sans jouer ;
  - rl         : connecteur_rl.py — le vrai rl_api_pp_connector : le bot passe dans
                 les parties l'une après l'autre.

Format du résultat : exactement ce que rl_api_pp_connector écrit dans scores.json
(rl_match_watcher.build_result + "partie" + "statut"), par exemple :

    {
      "date": "2026-11-14T15:08:42",
      "match_guid": "85548C1E11F1DF4E1BC4ECAB9017E0E9",
      "arena": "Stadium_P",
      "overtime": false,
      "winner_team_num": 0,                    # 0 = Bleu, 1 = Orange, null = pas de vainqueur
      "teams": [{"team_num": 0, "name": "Blue", "score": 3},
                {"team_num": 1, "name": "Orange", "score": 1}],
      "players": [{"Name": "tomatoKing", "TeamNum": 0, "Score": 640, "Goals": 2,
                   "Assists": 1, "Saves": 2, "Shots": 5, "Demos": 1}, ...],
      "partie": "tomato_agntyp",
      "statut": "terminé"                      # sinon : la raison pour laquelle le bot n'a pas le score
    }

Si "statut" n'est pas "terminé" (ou s'il n'y a pas de vainqueur), le match passe
« à valider » : les joueurs déclarent le score, ou un admin le fixe.

Le bot retrouve quelle équipe était en Bleu grâce aux pseudos en jeu ("Name"
comparé aux "pseudo_jeu" du fichier d'inscription). S'il n'y arrive pas, il
applique la consigne envoyée aux joueurs : équipe A en Bleu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .config import Config


@dataclass(frozen=True)
class PartieAObserver:
    tournoi_id: str
    ronde: int
    zone: int
    nom: str
    mot_de_passe: str
    pseudos_bleu: tuple[str, ...]    # pseudos en jeu de l'équipe A (consigne : Bleu)
    pseudos_orange: tuple[str, ...]  # pseudos en jeu de l'équipe B (consigne : Orange)


class Observateur(Protocol):
    async def observer(self, partie: PartieAObserver) -> dict:
        """Prend le score du match de la partie privée et renvoie le résultat (format ci-dessus).

        Peut être annulé (asyncio.CancelledError) si le tournoi est arrêté
        ou si un admin valide le résultat à la main.
        """
        ...


def creer_observateur(config: Config) -> Observateur:
    from .config import ErreurConfig

    if config.observateur == "simulation":
        from .simulateur import ObservateurSimule
        return ObservateurSimule(
            duree_min=config.simulation_duree_min,
            duree_max=config.simulation_duree_max,
            proba_sans_gagnant=config.simulation_proba_sans_gagnant,
            proba_couleurs_inversees=config.simulation_proba_couleurs_inversees,
        )

    if config.rl is None:
        raise ErreurConfig("OBSERVATEUR=rl : réglages RL_* manquants.")
    from .connecteur_rl import ObservateurRL
    return ObservateurRL.depuis_config(config)
