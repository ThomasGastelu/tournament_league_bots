import json

from bot_tournament_manager.commandes import COMMANDES
from bot_tournament_manager.pp import generer_parties, lettres


def test_parties_tomato_une_lettre_par_zone(tmp_path):
    sortie = tmp_path / "pp" / "1_ronde_1.json"
    parties = generer_parties(4, sortie)
    assert parties == [{"match": i, "nom": f"tomato_{l}", "mot_de_passe": f"tomato_{l}"}
                       for i, l in enumerate("ABCD", start=1)]
    assert json.loads(sortie.read_text(encoding="utf-8"))["parties"] == parties


def test_lettres_apres_z():
    assert [lettres(n) for n in (1, 2, 26, 27, 28, 52, 53)] == ["A", "B", "Z", "AA", "AB", "AZ", "BA"]


def test_noms_des_commandes():
    assert [c.name for c in COMMANDES] == [
        "start_tournament_rl", "start_tournament_rl_status", "stop_tournament_rl", "set_result_tournament_rl",
        "edit_player_tournament_rl", "reset_tournament_rl", "start_tournament_init", "start_tournament_modify_pp"]
    start = COMMANDES[0]
    assert [p.name for p in start.parameters] == ["id_tournoi", "nombre_de_matchs", "golden_round"]
    assert [p.required for p in start.parameters] == [True, True, False]
    assert start.get_parameter("golden_round").default == 1
    edit = COMMANDES[4]
    assert [p.name for p in edit.parameters] == [
        "id_tournoi", "joueur", "pseudo_jeu", "pseudo", "nom_equipe", "devient_capitaine", "remplace_par"]
    assert [p.required for p in edit.parameters] == [True, True, False, False, False, False, False]
    assert edit.get_parameter("pseudo_jeu").max_value == 32  # longueur max d'un texte
    reset = COMMANDES[5]
    assert [p.name for p in reset.parameters] == ["id_tournoi", "garder_salon"]
    assert reset.get_parameter("garder_salon").default is False
    assert reset.default_permissions.manage_guild  # admins seulement
