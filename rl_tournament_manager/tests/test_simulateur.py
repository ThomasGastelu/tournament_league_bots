import asyncio
import random

from bot_tournament_manager.observation import PartieAObserver
from bot_tournament_manager.simulateur import ObservateurSimule, simuler_resultat

# Clés de rl_match_watcher.build_result + celles ajoutées par rl_join_bot.follow_match
CLES_CONNECTEUR = {"date", "match_guid", "arena", "overtime", "winner_team_num", "teams", "players", "partie", "statut"}
CLES_JOUEUR = {"Name", "TeamNum", "Score", "Goals", "Assists", "Saves", "Shots", "Demos"}

PARTIE = PartieAObserver(tournoi_id="1", ronde=1, zone=1, nom="tomato_abc", mot_de_passe="tomato_abc",
                         pseudos_bleu=("tomatoKing", "cacacaca"), pseudos_orange=("crazyTomato", "gogol"))


def test_format_identique_au_connecteur():
    for graine in range(50):
        res = simuler_resultat(PARTIE, random.Random(graine))
        assert CLES_CONNECTEUR <= set(res)
        assert res["partie"] == "tomato_abc" and res["statut"] == "terminé"
        assert all(set(j) == CLES_JOUEUR for j in res["players"])
        scores = {t["team_num"]: t["score"] for t in res["teams"]}
        assert scores[res["winner_team_num"]] > scores[1 - res["winner_team_num"]]
        # Les buts des joueurs font le score de leur équipe.
        for couleur in (0, 1):
            assert sum(j["Goals"] for j in res["players"] if j["TeamNum"] == couleur) == scores[couleur]


def test_utilise_les_pseudos_en_jeu():
    res = simuler_resultat(PARTIE, random.Random(1))
    bleus = {j["Name"] for j in res["players"] if j["TeamNum"] == 0}
    assert bleus == {"tomatoKing", "cacacaca"}


def test_couleurs_inversees():
    res = simuler_resultat(PARTIE, random.Random(1), proba_couleurs_inversees=1)
    bleus = {j["Name"] for j in res["players"] if j["TeamNum"] == 0}
    assert bleus == {"crazyTomato", "gogol"}


def test_sans_gagnant():
    res = simuler_resultat(PARTIE, random.Random(1), proba_sans_gagnant=1)
    assert res["winner_team_num"] is None
    assert res["statut"] in ("quitté avant la fin", "connexion perdue")


def test_observateur_simule_asynchrone():
    observateur = ObservateurSimule(duree_min=0, duree_max=0, rng=random.Random(3))
    res = asyncio.run(observateur.observer(PARTIE))
    assert res["partie"] == "tomato_abc"
