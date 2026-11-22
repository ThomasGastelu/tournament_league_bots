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


def test_chrono_de_declaration_part_du_clic_ou_de_maintenant():
    etat = etat_de(2)
    match = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")["matchs"][0]
    assert L.demarrer_chrono_declaration(match, "2026-11-18T15:52:00") == "2026-11-18T15:52:00"  # sans clic
    # Déjà noté (reprise après un redémarrage) : on garde le départ.
    assert L.demarrer_chrono_declaration(match, "2026-11-18T16:00:00") == "2026-11-18T15:52:00"

    match = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")["matchs"][0]
    match["pp_creee_le"] = "2026-11-18T15:42:00"
    assert L.demarrer_chrono_declaration(match, "2026-11-18T15:45:00") == "2026-11-18T15:42:00"  # le clic


def test_ouvrir_declarations():
    etat = etat_de(2)
    match = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")["matchs"][0]
    match["statut"] = L.MATCH_EN_COURS
    L.ouvrir_declarations(match)
    assert match["statut"] == L.MATCH_A_VALIDER and match["raison_a_valider"] == L.RAISON_DECLARATION
    assert L.declarer_score(etat, 1, match, 1, 3, 1, par="a", maintenant="t") == L.DECLARATION_EN_ATTENTE


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

def match_a_valider():
    """Match équipe 1 (A) vs équipe 2 (B) dont les équipes doivent déclarer le score."""
    etat = etat_de(2)
    ronde = L.nouvelle_ronde(etat, [(1, 2)], parties(1), fichier_pp="x", maintenant="t")
    match = ronde["matchs"][0]
    match.update(statut=L.MATCH_A_VALIDER, raison_a_valider=L.RAISON_DECLARATION)
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


@pytest.mark.parametrize("statut, buts, erreur", [
    (L.MATCH_EN_COURS, (3, 1), "pas encore fini"),
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
