"""golden_round : toutes les victoires valent +1, et la zone haute vaut +3 à partir du golden round."""

import asyncio
import random
from pathlib import Path

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, FausseMessagerie, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"


def etat_8_equipes(golden_round: int = 1, rondes: int = 3) -> dict:
    tournoi = tournoi_inscription(8, TID)
    return L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=rondes, lance_par=ADMIN,
                         maintenant="2026-11-18T15:00:00", golden_round=golden_round)


# --------------------------------------------------------------------------- #
# Règles
# --------------------------------------------------------------------------- #

def test_zone_haute_vaut_plus_1_avant_le_golden_round():
    etat = etat_8_equipes(golden_round=3)  # 4 zones : la zone 4 est la zone haute
    assert [L.points_victoire(etat, 4, numero) for numero in (1, 2, 3)] == [1, 1, 3]
    assert [L.points_victoire(etat, 3, numero) for numero in (1, 2, 3)] == [1, 1, 1]


def test_sans_golden_round_la_zone_haute_vaut_plus_3_des_le_debut():
    etat = etat_8_equipes()
    assert etat["golden_round"] == 1
    assert L.points_victoire(etat, 4, 1) == 3 and L.points_victoire(etat, 1, 1) == 1


def test_tournoi_lance_avant_l_option_garde_le_plus_3():
    etat = etat_8_equipes(golden_round=3)
    del etat["golden_round"]  # JSON d'un tournoi lancé avant cette option
    assert L.points_victoire(etat, 4, 1) == 3


@pytest.mark.parametrize("golden_round", [0, 4])
def test_golden_round_hors_du_tournoi_refuse(golden_round):
    with pytest.raises(L.ErreurTournoi, match="entre 1 et 3"):
        etat_8_equipes(golden_round=golden_round, rondes=3)


def test_golden_round_au_dernier_round_accepte():
    assert etat_8_equipes(golden_round=3, rondes=3)["golden_round"] == 3


# --------------------------------------------------------------------------- #
# Textes
# --------------------------------------------------------------------------- #

def test_bareme_affiche():
    sans = etat_8_equipes()
    assert M.regle_points(sans, 1) == "Victoire en zone haute ⭐ : +3 · victoire ailleurs : +1 · défaite : 0"
    assert "golden" not in M.ligne_points(sans)

    avec = etat_8_equipes(golden_round=3)
    assert M.regle_points(avec, 2) == ("Toutes les victoires : +1 · défaite : 0 · "
                                       "🌟 golden round au round 3 : zone haute ⭐ +3")
    assert M.regle_points(avec, 3).endswith("+3 · victoire ailleurs : +1 · défaite : 0 · "
                                            "🌟 golden round depuis le round 3")
    assert "golden round au round 3" in M.ligne_points(avec)


def test_status_avant_le_golden_round():
    etat = etat_8_equipes(golden_round=3)
    L.nouvelle_ronde(etat, [(1, 2), (3, 4), (5, 6), (7, 8)], [{"nom": f"pp{i}", "mot_de_passe": "x"} for i in range(4)],
                     fichier_pp="x.json", maintenant="t")
    texte = M.embeds_status(etat)[0].description
    assert "*Toutes les victoires : +1" in texte


# --------------------------------------------------------------------------- #
# Tournoi complet
# --------------------------------------------------------------------------- #

def gestionnaire(tmp_path: Path):
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(8, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(declaration_auto=True)
    g = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0,
                             delai_declaration=0, generer_pp=faux_pp, rng=random.Random(3))
    messagerie.gestionnaire = g
    return g, stockage, messagerie


def test_tournoi_complet_avec_golden_round(tmp_path):
    async def scenario():
        g, stockage, messagerie = gestionnaire(tmp_path)
        await g.demarrer(TID, 3, serveur_id=SERVEUR, lance_par=ADMIN, golden_round=3)
        await g.attendre(TID)
        return stockage.charger_etat(TID), messagerie

    etat, messagerie = asyncio.run(scenario())

    assert etat["statut"] == L.TERMINE and etat["golden_round"] == 3
    points_par_round = {numero: sum(h["points"] for e in etat["equipes"].values()
                                    for h in e["historique"] if h["ronde"] == numero) for numero in (1, 2, 3)}
    assert points_par_round == {1: 4, 2: 4, 3: 6}  # 4 victoires à +1, puis 3 à +1 et la zone haute à +3
    for ronde in etat["rondes"]:
        zone_haute = next(m for m in ronde["matchs"] if m["zone"] == 4)
        assert zone_haute["points_attribues"] == (3 if ronde["numero"] == 3 else 1)
    assert sum(e["points"] for e in etat["equipes"].values()) == 14

    # Annonces : une par round, puis le classement final.
    annonces = ["\n".join(e.description for e in embeds) for _, embeds in messagerie.annonces[:3]]
    assert "Golden round au round 3" in annonces[0] and "**Zone 4 ⭐** (+1)" in annonces[0]
    assert "Golden round au round 3" in annonces[1]
    assert "**Golden round !**" in annonces[2] and "**Zone 4 ⭐** (+3)" in annonces[2]


def test_golden_round_trop_grand_refuse_au_lancement(tmp_path):
    async def scenario():
        g, stockage, _ = gestionnaire(tmp_path)
        with pytest.raises(L.ErreurTournoi, match="golden round"):
            await g.demarrer(TID, 3, serveur_id=SERVEUR, lance_par=ADMIN, golden_round=5)
        return stockage.charger_etat(TID)

    assert asyncio.run(scenario()) is None  # rien n'est lancé
