import random

import pytest

from bot_tournament_manager import logique as L

from .outils import ADMIN, tournoi_inscription


def etat_de(nb_equipes: int) -> dict:
    tournoi = tournoi_inscription(nb_equipes)
    return L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=3,
                         lance_par=ADMIN, maintenant="2026-11-14T15:00:00")


def parties(n: int) -> list[dict]:
    return [{"match": i, "nom": f"pp{i}", "mot_de_passe": f"pp{i}"} for i in range(1, n + 1)]


def resultat(bleu: list[str], orange: list[str], score_bleu: int, score_orange: int,
             gagnant: int | None = None, statut: str = "terminé") -> dict:
    if gagnant is None and statut == "terminé":
        gagnant = 0 if score_bleu > score_orange else 1
    return {
        "winner_team_num": gagnant,
        "teams": [{"team_num": 0, "name": "Blue", "score": score_bleu},
                  {"team_num": 1, "name": "Orange", "score": score_orange}],
        "players": [{"Name": n, "TeamNum": 0} for n in bleu] + [{"Name": n, "TeamNum": 1} for n in orange],
        "partie": "pp1",
        "statut": statut,
    }


# --------------------------------------------------------------------------- #
# Lancement
# --------------------------------------------------------------------------- #

def test_equipes_participantes_refuse_nombre_impair():
    with pytest.raises(L.ErreurTournoi, match="pair"):
        L.equipes_participantes(tournoi_inscription(3))


def test_equipes_participantes_refuse_une_seule_equipe():
    with pytest.raises(L.ErreurTournoi, match="au moins 2"):
        L.equipes_participantes(tournoi_inscription(1))


def test_equipes_participantes_ignore_les_equipes_non_inscrites():
    tournoi = tournoi_inscription(5)
    tournoi["equipes"][4]["statut"] = "liste_attente"
    assert [e["id"] for e in L.equipes_participantes(tournoi)] == [1, 2, 3, 4]


def test_equipes_participantes_refuse_un_joueur_non_confirme():
    tournoi = tournoi_inscription(2)
    tournoi["equipes"][1]["joueurs"][1]["statut"] = "en_attente"
    with pytest.raises(L.ErreurTournoi, match="Equipe2"):
        L.equipes_participantes(tournoi)


def test_nouvel_etat_une_zone_par_match():
    etat = etat_de(8)
    assert etat["nb_zones"] == 4
    assert set(etat["equipes"]) == {str(i) for i in range(1, 9)}
    assert etat["equipes"]["1"]["joueurs"][0]["pseudo_jeu"] == "Cap1RL"


def test_premier_tirage_place_chaque_equipe_une_fois():
    affectations = L.premier_tirage(list(range(1, 9)), random.Random(4))
    assert len(affectations) == 4
    assert sorted(i for paire in affectations for i in paire) == list(range(1, 9))


# --------------------------------------------------------------------------- #
# Rotation des zones
# --------------------------------------------------------------------------- #

def jouer_ronde(etat: dict, affectations, gagnants_a: set[int]) -> dict:
    """Crée une ronde et la termine : dans les zones de `gagnants_a`, l'équipe A gagne."""
    ronde = L.nouvelle_ronde(etat, affectations, parties(len(affectations)), fichier_pp="x.json", maintenant="t")
    for match in ronde["matchs"]:
        gagnant = match["equipe_a"] if match["zone"] in gagnants_a else match["equipe_b"]
        L.valider_manuellement(etat, ronde["numero"], match, gagnant, 2, 1, par=ADMIN, maintenant="t")
    L.terminer_ronde(ronde, "t")
    return ronde


def test_rotation_gagnant_monte_perdant_descend():
    etat = etat_de(8)
    # Zone 1 : 1 vs 2, zone 2 : 3 vs 4, zone 3 : 5 vs 6, zone 4 : 7 vs 8 ; l'équipe A gagne partout.
    ronde = jouer_ronde(etat, [(1, 2), (3, 4), (5, 6), (7, 8)], gagnants_a={1, 2, 3, 4})
    assert L.affectations_suivantes(ronde, 4) == [
        (2, 4),  # zone 1 : perdant zone 1 (reste) vs perdant zone 2 (descend)
        (1, 6),  # zone 2 : gagnant zone 1 (monte) vs perdant zone 3 (descend)
        (3, 8),  # zone 3 : gagnant zone 2 (monte) vs perdant zone 4 (descend)
        (5, 7),  # zone 4 : gagnant zone 3 (monte) vs gagnant zone 4 (reste)
    ]


def test_rotation_avec_une_seule_zone():
    etat = etat_de(2)
    ronde = jouer_ronde(etat, [(1, 2)], gagnants_a=set())
    assert L.affectations_suivantes(ronde, 1) == [(1, 2)]


def test_rotation_refuse_une_ronde_pas_terminee():
    etat = etat_de(4)
    ronde = L.nouvelle_ronde(etat, [(1, 2), (3, 4)], parties(2), fichier_pp="x", maintenant="t")
    with pytest.raises(L.ErreurTournoi):
        L.affectations_suivantes(ronde, 2)


def test_zone_suivante():
    assert L.zone_suivante(4, 4, a_gagne=True) == 4
    assert L.zone_suivante(4, 4, a_gagne=False) == 3
    assert L.zone_suivante(1, 4, a_gagne=False) == 1
    assert L.zone_suivante(2, 4, a_gagne=True) == 3


# --------------------------------------------------------------------------- #
# Points et résultats
# --------------------------------------------------------------------------- #

def test_points_zone_haute_3_ailleurs_1_defaite_0():
    etat = etat_de(8)
    jouer_ronde(etat, [(1, 2), (3, 4), (5, 6), (7, 8)], gagnants_a={1, 2, 3, 4})
    points = {e["id"]: e["points"] for e in etat["equipes"].values()}
    assert points == {1: 1, 3: 1, 5: 1, 7: 3, 2: 0, 4: 0, 6: 0, 8: 0}
    assert etat["equipes"]["7"]["historique"] == [
        {"ronde": 1, "zone": 4, "adversaire": 8, "score": "2-1", "resultat": "victoire", "points": 3}]


def test_resultat_lu_avec_les_pseudos_meme_si_couleurs_inversees():
    etat = etat_de(2)
    ronde = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")
    match = ronde["matchs"][0]
    # L'équipe A (1) s'est mise en Orange et gagne 3-1.
    termine = L.appliquer_resultat(etat, 1, match, resultat(["Cap2RL", "Mate2RL"], ["cap1rl ", "Mate1RL"], 1, 3), "t")
    assert termine
    assert match["vainqueur"] == 1
    assert match["score"] == {"equipe_a": 3, "equipe_b": 1}
    assert match["bleu"] == 2 and match["couleurs_detectees_par"] == "pseudos"
    assert etat["equipes"]["1"]["points"] == 3  # une seule zone = zone haute


def test_pseudos_inconnus_on_applique_la_consigne():
    etat = etat_de(2)
    ronde = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")
    match = ronde["matchs"][0]
    L.appliquer_resultat(etat, 1, match, resultat(["inconnu"], ["autre"], 2, 0), "t")
    assert match["vainqueur"] == 1 and match["couleurs_detectees_par"] == "consigne"


@pytest.mark.parametrize("res, raison", [
    (resultat(["Cap1RL"], ["Cap2RL"], 2, 2, gagnant=None, statut="quitté avant la fin"), "quitté avant la fin"),
    (resultat(["Cap1RL"], ["Cap2RL"], 1, 1, gagnant=None, statut="connexion perdue"), "connexion perdue"),
    ({"statut": "terminé", "winner_team_num": 0, "teams": [], "players": []}, "score illisible"),
    (resultat(["Cap1RL"], ["Cap2RL"], 1, 3, gagnant=0), "le score ne correspond pas au vainqueur annoncé"),
])
def test_match_sans_vainqueur_passe_a_valider(res, raison):
    etat = etat_de(2)
    ronde = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")
    match = ronde["matchs"][0]
    assert not L.appliquer_resultat(etat, 1, match, res, "t")
    assert match["statut"] == L.MATCH_A_VALIDER
    assert match["raison_a_valider"] == raison
    assert etat["equipes"]["1"]["matchs_joues"] == 0


def test_validation_manuelle():
    etat = etat_de(2)
    ronde = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")
    match = ronde["matchs"][0]
    with pytest.raises(L.ErreurTournoi, match="plus grand"):
        L.valider_manuellement(etat, 1, match, 2, 1, 1, par=ADMIN, maintenant="t")
    with pytest.raises(L.ErreurTournoi, match="ne joue pas"):
        L.valider_manuellement(etat, 1, match, 7, 2, 1, par=ADMIN, maintenant="t")
    L.valider_manuellement(etat, 1, match, 2, 4, 2, par=ADMIN, maintenant="t")
    assert match["score"] == {"equipe_a": 2, "equipe_b": 4}
    assert match["valide_par"] == ADMIN
    with pytest.raises(L.ErreurTournoi, match="déjà terminé"):
        L.valider_manuellement(etat, 1, match, 1, 2, 1, par=ADMIN, maintenant="t")


# --------------------------------------------------------------------------- #
# Déclaration du score par les équipes
# --------------------------------------------------------------------------- #

def match_a_valider(score_vu=None, couleurs="pseudos"):
    """Match équipe 1 (A) vs équipe 2 (B) dont le bot n'a pas le score."""
    etat = etat_de(2)
    ronde = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")
    match = ronde["matchs"][0]
    match.update(statut=L.MATCH_A_VALIDER, raison_a_valider="partie introuvable", score=score_vu,
                 couleurs_detectees_par=couleurs)
    return etat, match


def test_declarations_identiques_validees():
    etat, match = match_a_valider()
    assert L.declarer_score(etat, 1, match, 1, 3, 1, par="a", maintenant="t") == L.DECLARATION_EN_ATTENTE
    assert match["statut"] == L.MATCH_A_VALIDER
    # L'équipe B déclare de son point de vue : 1 pour elle, 3 pour l'adversaire.
    assert L.declarer_score(etat, 1, match, 2, 1, 3, par="b", maintenant="t") == L.DECLARATION_VALIDEE
    assert match["statut"] == L.MATCH_TERMINE and match["source_resultat"] == L.SOURCE_DECLARATIONS
    assert match["score"] == {"equipe_a": 3, "equipe_b": 1} and match["vainqueur"] == 1
    assert etat["equipes"]["1"]["points"] == 3 and etat["equipes"]["2"]["defaites"] == 1
    with pytest.raises(L.ErreurTournoi, match="déjà enregistré"):
        L.declarer_score(etat, 1, match, 1, 3, 1, par="a", maintenant="t")


def test_declarations_differentes_puis_correction():
    etat, match = match_a_valider()
    L.declarer_score(etat, 1, match, 1, 3, 1, par="a", maintenant="t")
    assert L.declarer_score(etat, 1, match, 2, 3, 1, par="b", maintenant="t") == L.DECLARATION_DESACCORD
    assert match["statut"] == L.MATCH_A_VALIDER
    # L'équipe B s'était trompée et corrige : sa nouvelle déclaration remplace l'ancienne.
    assert L.declarer_score(etat, 1, match, 2, 1, 3, par="b", maintenant="t") == L.DECLARATION_VALIDEE


def test_declaration_plus_basse_que_le_score_vu_par_le_bot():
    etat, match = match_a_valider(score_vu={"equipe_a": 2, "equipe_b": 2})
    assert L.declarer_score(etat, 1, match, 1, 1, 0, par="a", maintenant="t") == L.DECLARATION_INCOHERENTE
    assert L.declarer_score(etat, 1, match, 1, 3, 2, par="a", maintenant="t") == L.DECLARATION_EN_ATTENTE


def test_score_vu_ignore_si_couleurs_pas_reconnues():
    # Couleurs devinées avec la consigne : le score vu peut être inversé, on ne s'en sert pas.
    etat, match = match_a_valider(score_vu={"equipe_a": 2, "equipe_b": 2}, couleurs="consigne")
    assert L.declarer_score(etat, 1, match, 1, 1, 0, par="a", maintenant="t") == L.DECLARATION_EN_ATTENTE


@pytest.mark.parametrize("statut, buts, erreur", [
    (L.MATCH_EN_COURS, (3, 1), "s'occupe encore"),
    (L.MATCH_ANNULE, (3, 1), "annulé"),
    (L.MATCH_A_VALIDER, (2, 2), "pas d'égalité"),
    (L.MATCH_A_VALIDER, (-1, 2), "négatif"),
])
def test_declaration_refusee(statut, buts, erreur):
    etat, match = match_a_valider()
    match["statut"] = statut
    with pytest.raises(L.ErreurTournoi, match=erreur):
        L.declarer_score(etat, 1, match, 1, *buts, par="a", maintenant="t")


def test_marquer_partie_creee():
    etat = etat_de(2)
    match = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")["matchs"][0]
    match["statut"] = L.MATCH_EN_COURS
    assert L.marquer_pp_creee(match, par="cap", maintenant="2026-11-18T15:42:00") is True
    assert L.marquer_pp_creee(match, par="cap", maintenant="2026-11-18T15:50:00") is False  # déjà noté
    assert match["pp_creee_le"] == "2026-11-18T15:42:00" and match["pp_creee_par"] == "cap"
    match["statut"] = L.MATCH_A_VALIDER
    with pytest.raises(L.ErreurTournoi, match="Déclarer le score"):
        L.marquer_pp_creee(match, par="cap", maintenant="t")


def test_classement_points_puis_victoires_puis_difference():
    etat = etat_de(4)
    e = etat["equipes"]
    e["1"].update(points=3, victoires=1, buts_pour=3, buts_contre=2)
    e["2"].update(points=3, victoires=3, buts_pour=3, buts_contre=2)
    e["3"].update(points=3, victoires=3, buts_pour=9, buts_contre=2)
    e["4"].update(points=5, victoires=1)
    assert [x["id"] for x in L.classement(etat)] == [4, 3, 2, 1]


def test_arret_annule_les_matchs_pas_finis():
    etat = etat_de(4)
    ronde = L.nouvelle_ronde(etat, [(1, 2), (3, 4)], parties(2), fichier_pp="x", maintenant="t")
    L.valider_manuellement(etat, 1, ronde["matchs"][0], 1, 1, 0, par=ADMIN, maintenant="t")
    L.arreter(etat, par=ADMIN, maintenant="t")
    assert etat["statut"] == L.ARRETE
    assert [m["statut"] for m in ronde["matchs"]] == [L.MATCH_TERMINE, L.MATCH_ANNULE]
