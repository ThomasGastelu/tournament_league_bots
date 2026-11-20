from pathlib import Path

import pytest

from bot_tournament_manager.commandes import COMMANDES
from bot_tournament_manager.pp import generer_parties

SCRIPT = Path(__file__).resolve().parents[2] / "rl_bot_ppname_creator" / "generer_pp_names.py"


@pytest.mark.skipif(not SCRIPT.exists(), reason="rl_bot_ppname_creator absent")
def test_vrai_script_generer_pp_names(tmp_path):
    sortie = tmp_path / "pp" / "1_ronde_1.json"
    parties = generer_parties(SCRIPT, 4, sortie)
    assert [p["match"] for p in parties] == [1, 2, 3, 4]
    assert all(p["nom"].startswith("tomato_") and p["nom"] == p["mot_de_passe"] for p in parties)
    assert len({p["nom"] for p in parties}) == 4
    assert sortie.exists()


def test_noms_des_commandes():
    assert [c.name for c in COMMANDES] == [
        "start_tournament_rl", "start_tournament_rl_status", "stop_tournament_rl", "set_result_tournament_rl",
        "edit_player_tournament_rl"]
    start = COMMANDES[0]
    assert [p.name for p in start.parameters] == ["id_tournoi", "nombre_de_matchs", "golden_round"]
    assert [p.required for p in start.parameters] == [True, True, False]
    assert start.get_parameter("golden_round").default == 1
    edit = COMMANDES[4]
    assert [p.name for p in edit.parameters] == [
        "id_tournoi", "joueur", "pseudo_jeu", "pseudo", "nom_equipe", "devient_capitaine", "remplace_par"]
    assert [p.required for p in edit.parameters] == [True, True, False, False, False, False, False]
    assert edit.get_parameter("pseudo_jeu").max_value == 32  # longueur max d'un texte
