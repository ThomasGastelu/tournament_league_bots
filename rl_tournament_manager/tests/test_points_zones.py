"""Options zone_1 à zone_4 de /start_tournament_rl : points d'une victoire par zone à partir du golden round."""

import asyncio
import random
from pathlib import Path

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, FausseMessagerie, demarrer, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"
POINTS = {1: 5, 2: 6, 3: 7, 4: 10}


def etat(nb_equipes: int = 8, golden_round: int = 2, rondes: int = 3, points_zones: dict | None = None) -> dict:
    tournoi = tournoi_inscription(nb_equipes, TID)
    return L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=rondes, lance_par=ADMIN,
                         maintenant="2026-11-27T15:00:00", golden_round=golden_round, points_zones=points_zones)


# --------------------------------------------------------------------------- #
# Règles
# --------------------------------------------------------------------------- #

def test_points_choisis_a_partir_du_golden_round():
    e = etat(points_zones=POINTS)
    assert e["points_zones"] == {"1": 5, "2": 6, "3": 7, "4": 10}  # clés texte : format JSON
    assert [L.points_victoire(e, zone, 1) for zone in (1, 2, 3, 4)] == [1, 1, 1, 1]
    for numero in (2, 3):
        assert [L.points_victoire(e, zone, numero) for zone in (1, 2, 3, 4)] == [5, 6, 7, 10]


def test_zone_non_renseignee_garde_le_bareme_normal():
    e = etat(points_zones={1: 2, 2: None, 3: None, 4: None})
    assert e["points_zones"] == {"1": 2}
    assert [L.points_victoire(e, zone, 2) for zone in (1, 2, 3, 4)] == [2, 1, 1, 3]


def test_zero_point_accepte():
    e = etat(points_zones={4: 0})
    assert L.points_victoire(e, 4, 2) == 0 and L.points_victoire(e, 4, 1) == 1


def test_sans_option_rien_ne_change():
    e = etat(points_zones=None)
    assert e["points_zones"] == {}
    assert [L.points_victoire(e, zone, 2) for zone in (1, 2, 3, 4)] == [1, 1, 1, 3]


def test_ancien_tournoi_sans_points_zones():
    e = etat(points_zones=POINTS)
    del e["points_zones"]  # JSON d'un tournoi lancé avant cette option
    assert [L.points_victoire(e, zone, 2) for zone in (1, 2, 3, 4)] == [1, 1, 1, 3]


def test_zone_inexistante_refusee():
    with pytest.raises(L.ErreurTournoi, match="zone_4.*3 zones"):
        etat(nb_equipes=6, points_zones={4: 10})


def test_zones_au_dela_de_4_valent_le_bareme_normal():
    e = etat(nb_equipes=12, points_zones=POINTS)  # 6 zones : la zone 6 est la zone haute
    assert [L.points_victoire(e, zone, 2) for zone in range(1, 7)] == [5, 6, 7, 10, 1, 3]


@pytest.mark.parametrize("points", [-1, 21])
def test_points_hors_limites_refuses(points):
    with pytest.raises(L.ErreurTournoi, match="entre 0 et 20"):
        etat(points_zones={1: points})


# --------------------------------------------------------------------------- #
# Textes
# --------------------------------------------------------------------------- #

def test_bareme_affiche_avec_points_choisis():
    e = etat(points_zones=POINTS)
    assert M.regle_points(e, 1) == ("Toutes les victoires : +1 · défaite : 0 · 🌟 golden round au round 2 : "
                                    "Zone 4 ⭐ +10 · Zone 3 +7 · Zone 2 +6 · Zone 1 +5")
    assert M.regle_points(e, 2) == ("Victoire : Zone 4 ⭐ +10 · Zone 3 +7 · Zone 2 +6 · Zone 1 +5 · défaite : 0 · "
                                    "🌟 golden round depuis le round 2")


def test_bareme_affiche_avec_une_seule_zone_choisie():
    e = etat(golden_round=1, points_zones={1: 4})
    assert M.regle_points(e, 1) == "Victoire : Zone 4 ⭐ +3 · Zone 1 +4 · ailleurs +1 · défaite : 0"


# --------------------------------------------------------------------------- #
# Tournoi complet
# --------------------------------------------------------------------------- #

def gestionnaire(tmp_path: Path, nb_equipes: int = 8):
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(nb_equipes, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(declaration_auto=True)
    g = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0,
                             delai_declaration=0, generer_pp=faux_pp, rng=random.Random(3))
    messagerie.gestionnaire = g
    return g, stockage, messagerie


def test_tournoi_complet_avec_points_par_zone(tmp_path):
    async def scenario():
        g, stockage, messagerie = gestionnaire(tmp_path)
        await demarrer(g, TID, 3, serveur_id=SERVEUR, lance_par=ADMIN, golden_round=2, points_zones=POINTS)
        await g.attendre(TID)
        return stockage.charger_etat(TID), messagerie

    e, messagerie = asyncio.run(scenario())

    assert e["statut"] == L.TERMINE
    for ronde in e["rondes"]:
        for match in ronde["matchs"]:
            attendu = 1 if ronde["numero"] == 1 else POINTS[match["zone"]]
            assert match["points_attribues"] == attendu
    assert sum(eq["points"] for eq in e["equipes"].values()) == 4 + 2 * (5 + 6 + 7 + 10)

    annonces = ["\n".join(x.description for x in embeds) for _, embeds in messagerie.annonces[:3]]
    assert "**Zone 4 ⭐** (+1)" in annonces[0] and "Golden round au round 2" in annonces[0]
    assert "**Golden round !**" in annonces[1] and "Zone 4 ⭐ +10 · Zone 3 +7" in annonces[1]
    assert "**Zone 4 ⭐** (+10)" in annonces[1] and "**Zone 1** (+5)" in annonces[1]


def test_zone_inexistante_refusee_au_lancement(tmp_path):
    async def scenario():
        g, stockage, _ = gestionnaire(tmp_path, nb_equipes=6)
        with pytest.raises(L.ErreurTournoi, match="zone_4"):
            await demarrer(g, TID, 3, serveur_id=SERVEUR, lance_par=ADMIN, points_zones={4: 10})
        return stockage.charger_etat(TID)

    assert asyncio.run(scenario()) is None  # rien n'est lancé
