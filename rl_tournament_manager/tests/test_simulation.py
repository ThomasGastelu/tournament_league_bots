"""Mode simulation (SIMULATION=1) : clics et déclarations automatiques."""

import asyncio
import random
from pathlib import Path

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager.config import charger_config, ErreurConfig
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.simulation import Simulation, score_au_hasard, score_different
from bot_tournament_manager.stockage import Stockage

from .outils import demarrer
from .outils import ADMIN, SERVEUR, FausseMessagerie, attendre_que, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"


def creer(tmp_path: Path, nb_equipes: int, *, simulation: Simulation | None, delai: float = 0):
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(nb_equipes, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(clic_auto=False)  # aucun clic ni déclaration de la fausse messagerie
    g = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0,
                             rappel_clic_pp=60, attente_clic_pp_max=120, delai_declaration=delai,
                             generer_pp=faux_pp, rng=random.Random(1), simulation=simulation)
    messagerie.gestionnaire = g
    return g, stockage, messagerie


def test_score_au_hasard_jamais_d_egalite():
    rng = random.Random(4)
    for _ in range(500):
        a, b = score_au_hasard(rng)
        assert a != b and 0 <= min(a, b) and max(a, b) <= 5
        autre = score_different((a, b), rng)
        assert autre != (a, b) and autre[0] != autre[1]


def test_tournoi_simule_va_jusqu_au_bout_tout_seul(tmp_path):
    async def scenario():
        simulation = Simulation(delai_clic=0, delai_declaration=0, rng=random.Random(2))
        g, stockage, messagerie = creer(tmp_path, 8, simulation=simulation)
        await demarrer(g, TID, 3, serveur_id=SERVEUR, lance_par=ADMIN)
        await asyncio.wait_for(g.attendre(TID), 10)
        return stockage.charger_etat(TID), messagerie

    etat, messagerie = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE and len(etat["rondes"]) == 3
    matchs = [m for r in etat["rondes"] for m in r["matchs"]]
    assert all(m["source_resultat"] == L.SOURCE_DECLARATIONS for m in matchs)
    # Le capitaine de l'équipe A a « cliqué » ; un joueur de chaque équipe a déclaré.
    assert all(m["pp_creee_par"] == etat["equipes"][str(m["equipe_a"])]["capitaine_id"] for m in matchs)
    assert all(set(m["declarations"]) == {str(m["equipe_a"]), str(m["equipe_b"])} for m in matchs)
    assert sum(e["points"] for e in etat["equipes"].values()) == 3 * (3 + 3)
    assert messagerie.alertes == []
    # Le déroulement normal a lieu : les joueurs reçoivent bien leurs MP de déclaration.
    assert len(messagerie.boutons) == 3 * 4 * 4  # 3 rounds × 4 matchs × 4 joueurs


def test_simulation_attend_le_delai_avant_de_declarer(tmp_path):
    async def scenario():
        simulation = Simulation(delai_clic=0, delai_declaration=0, rng=random.Random(2))
        g, stockage, messagerie = creer(tmp_path, 2, simulation=simulation, delai=1.5)
        await demarrer(g, TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"])
                           and bool(stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["pp_creee_le"]))
        await asyncio.sleep(0.1)
        pendant = stockage.charger_etat(TID)["rondes"][0]["matchs"][0]
        await asyncio.wait_for(g.attendre(TID), 5)
        return pendant, stockage.charger_etat(TID)

    pendant, etat = asyncio.run(scenario())
    assert pendant["statut"] == L.MATCH_EN_COURS and pendant["declarations"] == {}
    assert etat["statut"] == L.TERMINE


def test_desaccord_simule_attend_un_admin(tmp_path):
    async def scenario():
        simulation = Simulation(delai_clic=0, delai_declaration=0, proba_desaccord=1, rng=random.Random(2))
        g, stockage, messagerie = creer(tmp_path, 2, simulation=simulation)
        await demarrer(g, TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"])
                           and len(stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["declarations"]) == 2)
        await asyncio.sleep(0.05)
        assert g.est_actif(TID)  # le round attend l'admin
        await g.valider_resultat(TID, 1, 1, 3, 0, serveur_id=SERVEUR, par=ADMIN)
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_etat(TID), messagerie

    etat, messagerie = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert etat["rondes"][0]["matchs"][0]["source_resultat"] == L.SOURCE_ADMIN
    assert any("pas déclaré le même score" in a for a in messagerie.titres_alertes())


def test_sans_simulation_rien_n_est_automatique(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2, simulation=None)
        await demarrer(g, TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(messagerie.boutons_pp))
        await asyncio.sleep(0.2)
        match = stockage.charger_etat(TID)["rondes"][0]["matchs"][0]
        await g.fermer()
        return match

    match = asyncio.run(scenario())
    assert match["statut"] == L.MATCH_EN_COURS and match["pp_creee_le"] is None and match["declarations"] == {}


def _config_env(monkeypatch, tmp_path, **variables):
    monkeypatch.setattr("bot_tournament_manager.config.load_dotenv", lambda *_a, **_k: None)
    (tmp_path / "inscriptions").mkdir(exist_ok=True)
    (tmp_path / "generer_pp_names.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("DISCORD_TOKEN", "a.b.c")
    monkeypatch.setenv("DOSSIER_INSCRIPTIONS", str(tmp_path / "inscriptions"))
    monkeypatch.setenv("SCRIPT_PP", str(tmp_path / "generer_pp_names.py"))
    for nom, valeur in variables.items():
        monkeypatch.setenv(nom, valeur)
    return charger_config()


def test_config_simulation(monkeypatch, tmp_path):
    for nom in ("SIMULATION", "SIMULATION_DELAI_CLIC", "SIMULATION_DELAI_DECLARATION", "SIMULATION_PROBA_DESACCORD"):
        monkeypatch.delenv(nom, raising=False)
    config = _config_env(monkeypatch, tmp_path)
    assert config.simulation is False
    config = _config_env(monkeypatch, tmp_path, SIMULATION="1", SIMULATION_DELAI_CLIC="2",
                         SIMULATION_PROBA_DESACCORD="0,3")
    assert config.simulation is True and config.simulation_delai_clic == 2
    assert config.simulation_delai_declaration == 5 and config.simulation_proba_desaccord == 0.3
    with pytest.raises(ErreurConfig, match="SIMULATION doit valoir"):
        _config_env(monkeypatch, tmp_path, SIMULATION="peut-être")
