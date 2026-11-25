"""Mode API (StockageAPI) : tournois enregistrés en base via l'API du site.

La requête HTTP est remplacée par une fausse API en mémoire (`FausseAPI`), qui suit les routes
décrites pour le backend : inscriptions (`GET /tournaments…`, `POST …/teams/<n>/cancel`),
lancement (`GET/PUT/DELETE …/run`, `GET /runs`), init (`GET/PUT …/launch-init`, `GET /launch-inits`)
et remise à zéro (`DELETE …/run-data`).
"""

import asyncio
import copy
import json
import logging
import random

import aiohttp
import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager.config import ErreurConfig
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.stockage_api import (MESSAGE_API_INJOIGNABLE, RAISON_PLACE_PERDUE, StockageAPI,
                                                 verifier_parametres)

from .outils import ADMIN, SERVEUR, FausseMessagerie, attendre_que, faux_pp, tournoi_inscription
from .test_simulation import _config_env

TID = "1571169059024928818"
CLE = "k" * 40


class FausseAPI:
    """Fausse API en mémoire. `panne = True` : connexion impossible (comme une API éteinte)."""

    def __init__(self, *tournois: dict) -> None:
        self.tournois = {t["id"]: copy.deepcopy(t) for t in tournois}
        self.runs: dict[str, dict] = {}   # tournoi → {"etat", "version"}
        self.inits: dict[str, dict] = {}
        self.requetes: list[tuple[str, str, dict | None]] = []
        self.panne = False

    def repondre(self, methode: str, chemin: str, corps, params) -> tuple[int, object]:
        if self.panne:
            raise aiohttp.ClientConnectionError("API éteinte")
        self.requetes.append((methode, chemin, copy.deepcopy(corps)))
        morceaux = chemin.strip("/").split("/")
        if chemin == "/tournaments":
            return 200, [{"id": t["id"], "titre": t["titre"], "date": "2026-12-06", "start_time": "20:30"}
                         for t in self.tournois.values() if t["serveur_id"] == params["serveur_id"]]
        if chemin == "/runs":
            return 200, [dict(r, etat=copy.deepcopy(r["etat"])) for r in self.runs.values()
                         if params.get("serveur_id") in (None, r["etat"]["serveur_id"])
                         and params.get("statut") in (None, r["etat"]["statut"])]
        if chemin == "/launch-inits":
            return 200, [dict(i, etat=copy.deepcopy(i["etat"])) for i in self.inits.values()
                         if i["etat"]["serveur_id"] == params["serveur_id"]]
        tid = morceaux[1]
        tournoi = self.tournois.get(tid)
        if tournoi is None:
            return 404, {"error": "Tournament not found"}
        if len(morceaux) == 2 and methode == "GET":
            return 200, copy.deepcopy(tournoi)
        if morceaux[2] == "teams" and morceaux[-1] == "cancel":
            equipe = next((e for e in tournoi["equipes"] if e["id"] == int(morceaux[3])), None)
            if equipe is None:
                return 404, {"error": "Team not found"}
            if equipe["statut"] == "annulee":
                return 409, {"error": "Team already cancelled"}
            equipe["statut"], equipe["raison_annulation"] = "annulee", corps["raison"]
            return 200, {"tournoi": copy.deepcopy(tournoi), "equipe": equipe, "promues": []}
        if morceaux[2] == "run-data" and methode == "DELETE":
            return 200, {"run": self.runs.pop(tid, None) is not None,
                         "launch_init": self.inits.pop(tid, None) is not None}
        table, nom = (self.runs, "Run") if morceaux[2] == "run" else (self.inits, "Launch init")
        actuel = table.get(tid)
        if methode == "GET":
            return (200, copy.deepcopy(actuel)) if actuel else (404, {"error": f"{nom} not found"})
        if methode == "DELETE":
            if actuel is None:
                return 404, {"error": f"{nom} not found"}
            del table[tid]
            return 200, {"supprime": True}
        # PUT
        if corps["etat"]["tournoi_id"] != tid:
            return 400, {"error": "Validation failed", "details": [{"path": "etat.tournoi_id"}]}
        if corps["version"] is None and actuel is not None:
            return 409, {"error": f"{nom} already exists" if nom == "Run" else f"{nom} version conflict"}
        if corps["version"] is not None and (actuel is None or actuel["version"] != corps["version"]):
            return 409, {"error": f"{nom} version conflict"}
        version = 1 if actuel is None else actuel["version"] + 1
        table[tid] = {"etat": copy.deepcopy(corps["etat"]), "version": version}
        return (201 if actuel is None else 200), {"etat": copy.deepcopy(corps["etat"]), "version": version}

    def chemins(self, methode: str | None = None) -> list[str]:
        return [f"{m} {c}" for m, c, _ in self.requetes if methode in (None, m)]


class StockageFausseAPI(StockageAPI):
    def __init__(self, api: FausseAPI, dossier) -> None:
        super().__init__("http://api.test", CLE, dossier, delais_reessai=(0.01,))
        self.api = api

    async def _requete(self, methode, chemin, corps=None, params=None):
        await asyncio.sleep(0)
        return self.api.repondre(methode, chemin, corps, params or {})


def creer(tmp_path, api: FausseAPI, *, delai_declaration: float = 0):
    stockage = StockageFausseAPI(api, tmp_path / "data")
    messagerie = FausseMessagerie(declaration_auto=True)
    g = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0, delai_declaration=delai_declaration,
                             generer_pp=faux_pp, rng=random.Random(1))
    messagerie.gestionnaire = g
    return g, stockage, messagerie


async def init_sans_validation(g, stockage) -> None:
    """Comme outils.demarrer : un init sans validation des participations avant le lancement."""
    await stockage.rafraichir_inscription(TID)
    stockage.sauvegarder_init(L.etat_init(stockage.charger_inscription(TID), [], par=ADMIN,
                                          maintenant="2026-11-14T15:00:00"))


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def test_config_api_url_sans_dossier_d_inscriptions(monkeypatch, tmp_path):
    config = _config_env(monkeypatch, tmp_path, API_URL="http://localhost/", BOT_API_KEY=CLE,
                         DOSSIER_INSCRIPTIONS=str(tmp_path / "absent"))
    assert config.api_url == "http://localhost" and config.bot_api_key == CLE
    assert config.dossier_inscriptions is None
    assert CLE not in repr(config)  # la clé n'apparaît jamais dans les logs


def test_config_api_mal_remplie(monkeypatch, tmp_path):
    with pytest.raises(ErreurConfig, match="BOT_API_KEY"):
        _config_env(monkeypatch, tmp_path, API_URL="http://localhost", BOT_API_KEY="courte")
    with pytest.raises(ErreurConfig, match="http://"):
        _config_env(monkeypatch, tmp_path, API_URL="localhost", BOT_API_KEY=CLE)


def test_config_sans_api_url_mode_fichiers(monkeypatch, tmp_path):
    monkeypatch.delenv("API_URL", raising=False)
    config = _config_env(monkeypatch, tmp_path)
    assert config.api_url is None and config.dossier_inscriptions == tmp_path / "inscriptions"
    assert verifier_parametres("", CLE) is None


# --------------------------------------------------------------------------- #
# Tournoi complet
# --------------------------------------------------------------------------- #

def test_tournoi_complet_enregistre_dans_l_api(tmp_path):
    api = FausseAPI(tournoi_inscription(4, TID))

    async def scenario():
        g, stockage, _ = creer(tmp_path, api)
        await init_sans_validation(g, stockage)
        await g.demarrer(TID, 2, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await stockage.attendre_envois()
        return stockage.charger_etat(TID)

    etat = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert api.runs[TID]["etat"] == etat  # l'API a exactement la copie locale
    assert api.runs[TID]["version"] > 1
    assert api.inits[TID]["etat"]["tournoi_id"] == TID
    assert f"GET /tournaments/{TID}" in api.chemins()  # inscription lue dans l'API
    assert not (tmp_path / "data" / "synchro" / f"{TID}.json").read_text(encoding="utf-8").count('"etat"')


def test_inscription_inconnue_de_l_api(tmp_path):
    api = FausseAPI()

    async def scenario():
        g, _, _ = creer(tmp_path, api)
        with pytest.raises(L.ErreurTournoi, match="Aucun tournoi"):
            await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)

    asyncio.run(scenario())


def test_api_injoignable_au_lancement_message_clair(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))
    api.panne = True

    async def scenario():
        g, _, _ = creer(tmp_path, api)
        with pytest.raises(L.ErreurTournoi, match=MESSAGE_API_INJOIGNABLE):
            await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)

    asyncio.run(scenario())


def test_api_en_panne_pendant_le_tournoi_tout_est_rattrape(tmp_path, caplog):
    api = FausseAPI(tournoi_inscription(4, TID))

    async def scenario():
        g, stockage, _ = creer(tmp_path, api)
        await init_sans_validation(g, stockage)
        await stockage.rafraichir_inscription(TID)
        api.panne = True  # l'API tombe juste après la lecture de l'inscription
        stockage.rafraichir_inscription = lambda _id: asyncio.sleep(0)
        await g.demarrer(TID, 2, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)  # le tournoi se joue quand même
        synchro = json.loads((tmp_path / "data" / "synchro" / f"{TID}.json").read_text(encoding="utf-8"))
        api.panne = False
        await stockage.attendre_envois()
        return stockage.charger_etat(TID), synchro

    with caplog.at_level(logging.WARNING):
        etat, synchro = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert synchro["a_envoyer"]  # noté pendant la panne
    assert api.runs[TID]["etat"] == etat
    assert "envoi à l'API impossible" in caplog.text and "répond de nouveau" in caplog.text


def test_refus_de_l_api_jamais_de_mot_de_passe_dans_les_logs(tmp_path, caplog):
    api = FausseAPI(tournoi_inscription(2, TID))

    async def scenario():
        g, stockage, _ = creer(tmp_path, api)
        await init_sans_validation(g, stockage)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await stockage.attendre_envois()
        etat = stockage.charger_etat(TID)
        etat["tournoi_id"] = "123456789012345678"  # refusé (400) par la fausse API
        stockage.dossier_etats.joinpath(f"{TID}.json").write_text(json.dumps(etat), encoding="utf-8")
        stockage._planifier(TID, "etat")
        await stockage.attendre_envois()

    with caplog.at_level(logging.DEBUG):
        asyncio.run(scenario())
    assert "refuse l'envoi" in caplog.text
    assert "tomato_test" not in caplog.text  # mots de passe des parties privées


def test_conflit_de_version_la_copie_locale_gagne(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))

    async def scenario():
        g, stockage, _ = creer(tmp_path, api)
        await init_sans_validation(g, stockage)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await stockage.attendre_envois()
        api.runs[TID]["version"] += 5  # écrit ailleurs entre-temps
        etat = stockage.charger_etat(TID)
        etat["titre"] = "Nouveau titre"
        stockage.sauvegarder_etat(etat)
        await stockage.attendre_envois()
        return etat

    etat = asyncio.run(scenario())
    assert api.runs[TID]["etat"] == etat
    assert api.chemins("GET")[-1] == f"GET /tournaments/{TID}/run"


# --------------------------------------------------------------------------- #
# Relance, remise à zéro
# --------------------------------------------------------------------------- #

def test_relancer_efface_l_ancien_lancement_sans_archive(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))

    async def scenario():
        g, stockage, _ = creer(tmp_path, api)
        await init_sans_validation(g, stockage)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await stockage.attendre_envois()
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await stockage.attendre_envois()

    asyncio.run(scenario())
    assert not list((tmp_path / "data" / "archives").iterdir())
    run = f"/tournaments/{TID}/run"
    ordre = [(m, c[2]["version"] if c[2] else None) for c in api.requetes for m in [c[0]] if c[1] == run]
    suppression = ordre.index(("DELETE", None))
    assert ordre[0] == ("PUT", None)  # premier lancement : création
    assert ordre[suppression + 1] == ("PUT", None)  # après l'effacement : nouveau lancement
    assert api.runs[TID]["etat"]["statut"] == L.TERMINE


def test_reset_efface_le_lancement_et_l_init_dans_l_api(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))

    async def scenario():
        g, stockage, _ = creer(tmp_path, api)
        await init_sans_validation(g, stockage)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await g.reinitialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        await stockage.attendre_envois()
        return stockage

    stockage = asyncio.run(scenario())
    assert TID not in api.runs and TID not in api.inits
    assert TID in api.tournois  # l'inscription n'est jamais touchée
    assert f"DELETE /tournaments/{TID}/run-data" in api.chemins()
    assert stockage.charger_etat(TID) is None and stockage.charger_init(TID) is None
    assert not (tmp_path / "data" / "synchro" / f"{TID}.json").exists()


# --------------------------------------------------------------------------- #
# Démarrage du bot
# --------------------------------------------------------------------------- #

def test_demarrage_recupere_les_tournois_de_l_api(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))
    etat = L.nouvel_etat(tournoi_inscription(2, TID), tournoi_inscription(2, TID)["equipes"], nombre_de_rondes=1,
                         lance_par=ADMIN, maintenant="2026-11-14T15:00:00")
    api.runs[TID] = {"etat": etat, "version": 7}

    async def scenario():
        _, stockage, _ = creer(tmp_path, api)  # dossier data/ vide (autre PC…)
        await stockage.synchroniser(SERVEUR)
        await stockage.attendre_envois()
        return stockage

    stockage = asyncio.run(scenario())
    assert stockage.charger_etat(TID) == etat
    assert stockage._lire_synchro(TID)["version_etat"] == 7
    assert api.chemins("PUT") == []  # rien renvoyé : c'est la version de l'API


def test_demarrage_renvoie_ce_qui_n_etait_pas_parti(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))
    tournoi = tournoi_inscription(2, TID)

    # Bot arrêté pendant une panne : sauvegarde locale faite, envoi noté mais pas parti.
    hors_ligne = StockageFausseAPI(api, tmp_path / "data")
    hors_ligne.sauvegarder_init(L.etat_init(tournoi, [], par=ADMIN, maintenant="2026-11-14T15:00:00"))
    assert api.requetes == []

    async def scenario():
        stockage = StockageFausseAPI(api, tmp_path / "data")
        await stockage.synchroniser(SERVEUR)
        await stockage.attendre_envois()

    asyncio.run(scenario())
    assert api.inits[TID]["etat"]["tournoi_id"] == TID


def test_import_des_anciens_fichiers(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))
    tournoi = tournoi_inscription(2, TID)
    # Fichiers écrits avant API_URL (mode fichiers) : pas de data/synchro.
    from bot_tournament_manager.stockage import Stockage
    ancien = Stockage(None, tmp_path / "data")
    ancien.sauvegarder_etat(L.nouvel_etat(tournoi, tournoi["equipes"], nombre_de_rondes=1, lance_par=ADMIN,
                                          maintenant="2026-11-14T15:00:00"))
    ancien.sauvegarder_init(L.etat_init(tournoi, [], par=ADMIN, maintenant="2026-11-14T15:00:00"))

    deja_en_base = {"etat": {"tournoi_id": TID, "titre": "déjà là"}, "version": 3}
    api.inits[TID] = copy.deepcopy(deja_en_base)

    async def scenario():
        stockage = StockageFausseAPI(api, tmp_path / "data")
        return await stockage.importer(), await stockage.importer()

    premier, deuxieme = asyncio.run(scenario())
    assert premier == {"importe": 1, "deja": 1, "erreur": 0}
    assert deuxieme == {"importe": 0, "deja": 2, "erreur": 0}
    assert api.runs[TID]["version"] == 1
    assert api.inits[TID] == deja_en_base  # jamais écrasé


# --------------------------------------------------------------------------- #
# Validation des participations
# --------------------------------------------------------------------------- #

def test_places_perdues_annulees_dans_l_inscription(tmp_path):
    tournoi = tournoi_inscription(4, TID, equipes_max=2)
    for equipe in tournoi["equipes"][2:]:
        equipe["statut"] = "liste_attente"
    api = FausseAPI(tournoi)

    async def scenario():
        g, stockage, _ = creer(tmp_path, api)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=0.02)
        await g.valider_participation(TID, 1, par="1010")  # l'équipe 2 ne valide pas : la 3 monte
        await attendre_que(lambda: stockage.charger_init(TID)["confirmation"]["promues"] == [3])
        await g.valider_participation(TID, 3, par="1030")
        await asyncio.wait_for(g.attendre_confirmation(TID), 2)
        await stockage.attendre_envois()

    asyncio.run(scenario())
    statuts = {e["id"]: (e["statut"], e.get("raison_annulation")) for e in api.tournois[TID]["equipes"]}
    assert statuts[2] == ("annulee", RAISON_PLACE_PERDUE)
    assert statuts[1][0] != "annulee" and statuts[3][0] != "annulee"  # la promotion, c'est l'API qui la fait
    assert api.inits[TID]["etat"]["confirmation"]["perdues"] == [2]


# --------------------------------------------------------------------------- #
# Autocomplétion
# --------------------------------------------------------------------------- #

def test_liste_des_tournois_relue_au_plus_toutes_les_30_secondes(tmp_path):
    api = FausseAPI(tournoi_inscription(2, TID))

    async def scenario():
        _, stockage, _ = creer(tmp_path, api)
        await stockage.rafraichir_inscriptions(SERVEUR)
        await stockage.rafraichir_inscriptions(SERVEUR)
        return stockage.lister_inscriptions(SERVEUR), stockage.lister_inscriptions("1")

    tournois, autre_serveur = asyncio.run(scenario())
    assert [t["id"] for t in tournois] == [TID] and "equipes" not in tournois[0]
    assert autre_serveur == []
    assert api.chemins().count("GET /tournaments") == 1
