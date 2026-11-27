import json

from bot_tournament_manager.commandes import COMMANDES
from bot_tournament_manager.pp import generer_parties, nom_partie


def test_parties_tomato_round_puis_zone(tmp_path):
    sortie = tmp_path / "pp" / "1_ronde_1.json"
    parties = generer_parties(4, sortie, 1)
    assert parties == [{"match": i, "nom": f"tomato_1{i}", "mot_de_passe": f"tomato_1{i}"} for i in range(1, 5)]
    assert json.loads(sortie.read_text(encoding="utf-8"))["parties"] == parties


def test_noms_rounds_suivants(tmp_path):
    assert [p["nom"] for p in generer_parties(4, tmp_path / "r2.json", 2)] == [
        "tomato_21", "tomato_22", "tomato_23", "tomato_24"]
    assert [p["nom"] for p in generer_parties(4, tmp_path / "r12.json", 12)] == [
        "tomato_121", "tomato_122", "tomato_123", "tomato_124"]


def test_zone_sur_deux_chiffres_a_partir_de_10_zones():
    assert [nom_partie(1, z, 12) for z in (1, 9, 10, 12)] == ["tomato_101", "tomato_109", "tomato_110", "tomato_112"]
    assert nom_partie(11, 1, 12) == "tomato_1101"
    for nb_zones in (4, 9, 10, 12, 99, 100):
        noms = [nom_partie(r, z, nb_zones) for r in range(1, 51) for z in range(1, nb_zones + 1)]
        assert len(noms) == len(set(noms))  # aucun doublon sur tout un tournoi (50 rounds max)


def test_noms_des_commandes():
    assert [c.name for c in COMMANDES] == [
        "start_tournament_rl", "start_tournament_rl_status", "stop_tournament_rl", "set_result_tournament_rl",
        "edit_player_tournament_rl", "reset_tournament_rl", "start_tournament_init", "start_tournament_modify_pp",
        "start_tournament_init_status"]
    start = COMMANDES[0]
    assert [p.name for p in start.parameters] == ["id_tournoi", "nombre_de_matchs", "golden_round",
                                                  "zone_1", "zone_2", "zone_3", "zone_4"]
    assert [p.required for p in start.parameters] == [True, True, False, False, False, False, False]
    assert start.get_parameter("golden_round").default == 1
    for nom in ("zone_1", "zone_2", "zone_3", "zone_4"):
        zone = start.get_parameter(nom)
        assert zone.default is None and (zone.min_value, zone.max_value) == (0, 20)
        assert len(zone.description) <= 100
    edit = COMMANDES[4]
    assert [p.name for p in edit.parameters] == [
        "id_tournoi", "joueur", "pseudo_jeu", "pseudo", "nom_equipe", "devient_capitaine", "remplace_par"]
    assert [p.required for p in edit.parameters] == [True, True, False, False, False, False, False]
    assert edit.get_parameter("pseudo_jeu").max_value == 32  # longueur max d'un texte
    reset = COMMANDES[5]
    assert [p.name for p in reset.parameters] == ["id_tournoi", "garder_salon"]
    assert reset.get_parameter("garder_salon").default is False
    assert reset.default_permissions.manage_guild  # admins seulement
    init = COMMANDES[6]
    assert [p.name for p in init.parameters] == ["id_tournoi", "delai_confirmation"]
    assert [p.required for p in init.parameters] == [True, True]
    assert (init.get_parameter("delai_confirmation").min_value,
            init.get_parameter("delai_confirmation").max_value) == (1, 1440)
    status_init = COMMANDES[8]
    assert [p.name for p in status_init.parameters] == ["id_tournoi"]
    assert status_init.default_permissions.manage_guild  # admins seulement
