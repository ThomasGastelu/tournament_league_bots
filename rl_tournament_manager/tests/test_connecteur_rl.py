"""Vrai observateur (OBSERVATEUR=rl), testé avec un faux Rocket League."""

import asyncio
import json
import random
import socket
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager.config import ErreurConfig, ReglagesRL
from bot_tournament_manager.connecteur_rl import (RAISON_ARRET_URGENCE, RAISON_INTROUVABLE, RAISON_PARTIE_QUITTEE,
                                                  RAISON_RELANCEE, Lecture, ObservateurRL, PiloteRL,
                                                  charger_connecteur, gagnant_depuis_etat, lire_flux)
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.observation import PartieAObserver
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, FausseMessagerie, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"


def etat_rl(bleu: int, orange: int, *, gagnant: str | None = None, guid: str = "GUID1",
            joueurs=(("Cap1RL", 0), ("Cap2RL", 1)), secondes: int = 200) -> dict:
    """Un UpdateState de la Stats API."""
    return {
        "MatchGuid": guid,
        "Players": [{"Name": n, "TeamNum": t, "Score": 100, "Goals": 0} for n, t in joueurs],
        "Game": {"Teams": [{"Name": "Blue", "TeamNum": 0, "Score": bleu},
                           {"Name": "Orange", "TeamNum": 1, "Score": orange}],
                 "TimeSeconds": secondes, "bOvertime": False,
                 "bHasWinner": gagnant is not None, "Winner": gagnant or ""},
    }


def build_result(etat, gagnant):
    """Même chose que rl_match_watcher.build_result (en plus court)."""
    jeu = etat.get("Game", {})
    return {"match_guid": etat.get("MatchGuid"), "winner_team_num": gagnant,
            "teams": [{"team_num": t["TeamNum"], "name": t["Name"], "score": t["Score"]} for t in jeu["Teams"]],
            "players": [{k: p.get(k) for k in ("Name", "TeamNum")} for p in etat.get("Players", [])]}


def partie(nom: str, zone: int = 1) -> PartieAObserver:
    return PartieAObserver(tournoi_id=TID, ronde=1, zone=zone, nom=nom, mot_de_passe=nom,
                           pseudos_bleu=("Cap1RL",), pseudos_orange=("Cap2RL",))


# --------------------------------------------------------------------------- #
# Lecture de la Stats API
# --------------------------------------------------------------------------- #

def lire(*messages, duree: float = 2.0, coupe: int | None = None) -> Lecture:
    jeu, bot = socket.socketpair()
    flux = "".join(json.dumps(m) for m in messages).encode()
    if coupe:  # message coupé en deux morceaux
        jeu.sendall(flux[:coupe])
        jeu.sendall(flux[coupe:])
    else:
        jeu.sendall(flux)
    jeu.close()  # le jeu ferme la connexion après ces messages
    with bot:
        return lire_flux(bot, duree, threading.Event())


def test_lecture_match_en_cours():
    lecture = lire({"Event": "UpdateState", "Data": etat_rl(1, 0)}, {"Event": "UpdateState", "Data": etat_rl(2, 1)},
                   coupe=40)
    assert lecture.rejoint and not lecture.termine
    assert lecture.etat["Game"]["Teams"][0]["Score"] == 2


def test_lecture_match_termine_avec_matchended():
    # La Stats API envoie parfois Data sous forme de texte JSON.
    lecture = lire({"Event": "UpdateState", "Data": json.dumps(etat_rl(3, 1))},
                   {"Event": "MatchEnded", "Data": {"WinnerTeamNum": 0}})
    assert lecture.termine and lecture.gagnant == 0
    assert lecture.evenements == ["UpdateState", "MatchEnded"]


def test_lecture_partie_deja_finie_avec_bhaswinner():
    # Le bot arrive après la fin : les joueurs sont restés sur l'écran de fin.
    lecture = lire({"Event": "UpdateState", "Data": etat_rl(1, 4, gagnant="Orange", secondes=0)})
    assert lecture.termine and lecture.gagnant == 1


def test_lecture_sans_donnees():
    lecture = lire(duree=0.5)
    assert lecture.rejoint and lecture.etat is None and not lecture.termine


def test_gagnant_depuis_etat():
    assert gagnant_depuis_etat(etat_rl(2, 1, gagnant="Blue")) == 0
    assert gagnant_depuis_etat(etat_rl(0, 3)) == 1  # pas de champ Winner : le meilleur score
    assert gagnant_depuis_etat(etat_rl(2, 2)) is None
    assert gagnant_depuis_etat(None) is None


# --------------------------------------------------------------------------- #
# La tournée
# --------------------------------------------------------------------------- #

class FauxPilote:
    """Rejoue, pour chaque partie, une liste de lectures (une par visite)."""

    def __init__(self, scenarios: dict[str, list]) -> None:
        self.scenarios = {nom: list(lectures) for nom, lectures in scenarios.items()}
        self.visites: list[str] = []
        self.stops: list[bool] = []

    def visiter(self, p: PartieAObserver, stop: threading.Event) -> Lecture:
        self.visites.append(p.nom)
        suite = self.scenarios[p.nom]
        lecture = suite.pop(0) if len(suite) > 1 else suite[0]
        if isinstance(lecture, Exception):
            raise lecture
        if callable(lecture):
            return lecture(stop)
        return lecture

    def construire_resultat(self, etat, gagnant):
        return build_result(etat, gagnant) if etat else {"winner_team_num": gagnant, "teams": [], "players": []}

    def verifier(self):
        return []


def vue(bleu, orange, **kwargs) -> Lecture:
    return Lecture(rejoint=True, etat=etat_rl(bleu, orange, **kwargs))


def fin(bleu, orange, gagnant, **kwargs) -> Lecture:
    return Lecture(rejoint=True, etat=etat_rl(bleu, orange, **kwargs), termine=True, gagnant=gagnant)


ECHEC = Lecture(erreur="partie introuvable")


def observer(pilote, *noms, tentatives=3):
    async def scenario():
        obs = ObservateurRL(pilote, tentatives=tentatives)
        return await asyncio.gather(*(obs.observer(partie(nom, zone)) for zone, nom in enumerate(noms, 1)))
    return asyncio.run(scenario())


def test_tournee_passe_dans_les_parties_l_une_apres_l_autre():
    pilote = FauxPilote({
        "pp1": [vue(0, 0), vue(1, 0), fin(2, 0, 0)],
        "pp2": [vue(1, 1), fin(1, 2, 1)],
    })
    r1, r2 = observer(pilote, "pp1", "pp2")
    assert pilote.visites == ["pp1", "pp2", "pp1", "pp2", "pp1"]
    assert r1["statut"] == "terminé" and r1["winner_team_num"] == 0 and r1["partie"] == "pp1" and r1["visites"] == 3
    assert r2["statut"] == "terminé" and r2["winner_team_num"] == 1


def test_partie_jamais_rejointe_abandonnee_apres_les_tentatives():
    pilote = FauxPilote({"pp1": [ECHEC], "pp2": [vue(0, 0), vue(0, 0), fin(1, 0, 0)]})
    r1, r2 = observer(pilote, "pp1", "pp2", tentatives=3)
    assert pilote.visites.count("pp1") == 3
    assert r1["statut"] == RAISON_INTROUVABLE.format(n=3) and r1["winner_team_num"] is None
    assert r2["statut"] == "terminé"


def test_joueurs_partis_avant_que_le_bot_prenne_le_score():
    pilote = FauxPilote({"pp1": [vue(2, 1), ECHEC, vue(3, 1), ECHEC, ECHEC, ECHEC]})
    (r,) = observer(pilote, "pp1", tentatives=3)
    # Les échecs doivent être de suite : celui entre deux visites réussies ne compte plus.
    assert len(pilote.visites) == 6
    assert r["statut"] == RAISON_PARTIE_QUITTEE.format(n=3)
    assert {t["team_num"]: t["score"] for t in r["teams"]} == {0: 3, 1: 1}  # dernier score vu


def test_partie_relancee():
    pilote = FauxPilote({"pp1": [vue(2, 1, guid="A"), vue(0, 0, guid="B")]})
    (r,) = observer(pilote, "pp1")
    assert r["statut"] == RAISON_RELANCEE
    assert {t["team_num"]: t["score"] for t in r["teams"]} == {0: 2, 1: 1}


def test_arret_d_urgence():
    FailSafeException = type("FailSafeException", (Exception,), {})
    pilote = FauxPilote({"pp1": [FailSafeException()], "pp2": [vue(0, 0)]})

    async def scenario():
        obs = ObservateurRL(pilote, tentatives=3)
        resultats = await asyncio.gather(obs.observer(partie("pp1")), obs.observer(partie("pp2", 2)))
        apres = await obs.observer(partie("pp3", 3))  # plus de pilotage : réponse immédiate
        return resultats, apres

    resultats, apres = asyncio.run(scenario())
    assert pilote.visites == ["pp1"]
    assert all(r["statut"] == RAISON_ARRET_URGENCE for r in [*resultats, apres])


def test_annulation_pendant_une_visite_fait_quitter_la_partie():
    commence = threading.Event()

    def longue_visite(stop: threading.Event) -> Lecture:
        commence.set()
        stop.wait(5)  # comme lire_flux : s'arrête dès que stop est levé
        return vue(0, 0)

    pilote = FauxPilote({"pp1": [longue_visite]})

    async def scenario():
        obs = ObservateurRL(pilote, tentatives=3)
        tache = asyncio.create_task(obs.observer(partie("pp1")))
        await asyncio.to_thread(commence.wait, 5)
        tache.cancel()  # ex. : un admin a validé le score à la main
        with pytest.raises(asyncio.CancelledError):
            await tache
        await asyncio.wait_for(obs._tache, 5)  # la tournée s'arrête : plus rien à visiter
        return obs

    obs = asyncio.run(scenario())
    assert obs._stop.is_set() and pilote.visites == ["pp1"]


def test_capitaine_prevenu_au_premier_echec_seulement():
    pilote = FauxPilote({"pp1": [ECHEC, ECHEC, fin(1, 0, 0)], "pp2": [vue(0, 0), ECHEC, fin(2, 0, 0)]})
    prevenus = []

    async def scenario():
        obs = ObservateurRL(pilote, tentatives=3)

        async def prevenir(p):
            prevenus.append(p.nom)
        obs.sur_partie_introuvable = prevenir
        resultats = await asyncio.gather(obs.observer(partie("pp1")), obs.observer(partie("pp2", 2)))
        await asyncio.sleep(0)
        return resultats

    r1, r2 = asyncio.run(scenario())
    assert r1["statut"] == "terminé" and r2["statut"] == "terminé"
    # pp1 : jamais vue → prévenu une fois ; pp2 : déjà vue, l'échec vient d'ailleurs → pas prévenu.
    assert prevenus == ["pp1"]


# --------------------------------------------------------------------------- #
# Tournoi complet avec le vrai observateur (faux Rocket League)
# --------------------------------------------------------------------------- #

def test_tournoi_avec_l_observateur_rl(tmp_path):
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(4, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie()
    # faux_pp nomme les parties tomato_test1 (zone 1) et tomato_test2 (zone 2).
    pilote = FauxPilote({
        "tomato_test1": [vue(0, 0), fin(2, 1, 0)],  # le bot voit la fin du match
        "tomato_test2": [ECHEC],                     # partie introuvable
    })

    async def scenario():
        g = GestionnaireTournois(stockage, ObservateurRL(pilote, tentatives=2), messagerie,
                                 script_pp=Path("inutile.py"), pause_entre_rondes=0,
                                 generer_pp=faux_pp, rng=random.Random(1))
        messagerie.gestionnaire = g  # les capitaines cliquent sur « Partie privée créée »
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        for _ in range(500):
            etat = stockage.charger_etat(TID)
            if etat["rondes"] and all(m["statut"] in (L.MATCH_TERMINE, L.MATCH_A_VALIDER)
                                      for m in etat["rondes"][0]["matchs"]):
                break
            await asyncio.sleep(0.01)
        await g.fermer()
        return stockage.charger_etat(TID)

    etat = asyncio.run(scenario())
    zone1, zone2 = sorted(etat["rondes"][0]["matchs"], key=lambda m: m["zone"])
    assert zone1["statut"] == L.MATCH_TERMINE and zone1["source_resultat"] == L.SOURCE_BOT
    assert zone2["statut"] == L.MATCH_A_VALIDER
    assert zone2["raison_a_valider"] == RAISON_INTROUVABLE.format(n=2)
    assert len(messagerie.alertes) == 1 and len(messagerie.boutons) == 4
    assert any("vous pouvez quitter la partie" in t for _, t in messagerie.mps)
    # Zone 2 : au premier échec, son capitaine a reçu de nouveau le nom et le mot de passe.
    capitaine2 = etat["equipes"][str(zone2["equipe_a"])]["capitaine_id"]
    introuvable = [t for j, t in messagerie.mps if "ne trouve pas ta partie" in t]
    assert len(introuvable) == 1 and zone2["pp"]["nom"] in introuvable[0]
    assert (capitaine2, introuvable[0]) in messagerie.mps


# --------------------------------------------------------------------------- #
# Pilotage du jeu, avec un faux rl_join_bot
# --------------------------------------------------------------------------- #

def reglages(tmp_path: Path, **modifs) -> ReglagesRL:
    positions = tmp_path / "positions.json"
    if not positions.exists():
        etapes = ["play", "private_match", "join_private", "name_field", "password_field", "join_button",
                  "spectate", "leave_match", "confirm_yes"]
        calibration = {e: [0.5, 0.5] for e in etapes}
        calibration["back_to_menu"] = [["click", 0.5, 0.6], ["key", "esc"]]
        positions.write_text(json.dumps({"resolution": [1920, 1200], "positions": calibration}))
    r = ReglagesRL(dossier_connecteur=tmp_path, positions=positions, resolution=None, langue="en",
                   tentatives=3, timeout_rejoindre=5, delai_menus=0, duree_lecture=1,
                   pause_apres_sortie=0)
    return replace(r, **modifs)


class FauxJoinBot:
    """Les fonctions de rl_join_bot utilisées par le bot."""
    LABELS = {"en": {"play": "PLAY"}, "fr": {"play": "JOUER"}}
    gw = None

    def __init__(self, messages=None) -> None:
        self.appels: list[str] = []
        self.messages = messages  # None : partie introuvable
        self.pyautogui = SimpleNamespace(size=lambda: (1920, 1200))
        jb = self

        class Locator:
            def __init__(self, largeur, hauteur, langue, positions, labels, tesseract):
                self.taille, self.positions, self.ocr_ok = (largeur, hauteur), positions, False

            def click_step(self, etape, timeout=15.0, required=True):
                jb.appels.append(f"clic {etape}")
                return True

        self.Locator = Locator

    def focus_game(self):
        self.appels.append("focus")

    def join_private_match(self, loc, nom, mot_de_passe, delai):
        self.appels.append(f"rejoindre {nom}/{mot_de_passe}")

    def wait_for_match(self, hote, port, timeout):
        if self.messages is None:
            return None
        jeu, bot = socket.socketpair()
        jeu.sendall("".join(json.dumps(m) for m in self.messages).encode())
        jeu.close()
        return bot

    def leave_match(self, loc, delai, wait=0):
        self.appels.append("quitter")

    def back_to_main_menu(self, loc, delai):
        self.appels.append("retour menu")


WATCHER = SimpleNamespace(build_result=build_result, parse_data=lambda m: m.get("Data") or {})


def test_visite_complete(tmp_path):
    jb = FauxJoinBot([{"Event": "UpdateState", "Data": etat_rl(1, 0)}, {"Event": "MatchEnded", "Data": {"WinnerTeamNum": 0}}])
    pilote = PiloteRL(reglages(tmp_path), jb, WATCHER)
    pilote.pause_lobby = 0
    lecture = pilote.visiter(partie("pp1"), threading.Event())
    assert lecture.rejoint and lecture.termine and lecture.gagnant == 0
    assert jb.appels == ["focus", "rejoindre pp1/pp1", "clic spectate", "quitter"]
    assert pilote.loc.taille == (1920, 1200)  # résolution de la calibration
    assert pilote.verifier() == []


def test_visite_partie_introuvable_retour_au_menu(tmp_path):
    jb = FauxJoinBot(None)
    pilote = PiloteRL(reglages(tmp_path), jb, WATCHER)
    lecture = pilote.visiter(partie("pp1"), threading.Event())
    assert not lecture.rejoint and "introuvable" in lecture.erreur
    assert jb.appels == ["focus", "rejoindre pp1/pp1", "retour menu"]


def test_calibration_incomplete_refusee(tmp_path):
    positions = tmp_path / "positions.json"
    positions.write_text(json.dumps({"resolution": [1920, 1200], "positions": {"play": [0.1, 0.4]}}))
    with pytest.raises(ErreurConfig, match="private_match, join_private"):
        PiloteRL(reglages(tmp_path), FauxJoinBot(), WATCHER)


def test_avertissements_au_demarrage(tmp_path):
    positions = tmp_path / "positions.json"
    positions.write_text(json.dumps({"resolution": [1920, 1080],
                                     "positions": {e: [0.5, 0.5] for e in ("play", "private_match", "join_private")}}))
    class AncienJoinBot(FauxJoinBot):
        back_to_main_menu = None  # rl_join_bot sans retour au menu

    avertissements = " ".join(PiloteRL(reglages(tmp_path), AncienJoinBot(), WATCHER).verifier())
    assert "spectate" in avertissements and "leave_match" in avertissements
    assert "1920x1080" in avertissements  # l'écran ne fait pas la taille de la calibration
    assert "back_to_main_menu" in avertissements


def test_connecteur_introuvable(tmp_path):
    with pytest.raises(ErreurConfig, match="rl_join_bot.py"):
        charger_connecteur(tmp_path)


def test_retour_menu_recoit_les_reglages_si_la_fonction_les_accepte(tmp_path):
    recu = {}

    class JoinBotAvecOptions(FauxJoinBot):
        def back_to_main_menu(self, loc, delai, host="127.0.0.1", port=49123, escapes=4):
            recu.update(host=host, port=port, escapes=escapes)

    pilote = PiloteRL(reglages(tmp_path, echap_retour_menu=2, port=50000), JoinBotAvecOptions(None), WATCHER)
    pilote.visiter(partie("pp1"), threading.Event())
    assert recu == {"host": "127.0.0.1", "port": 50000, "escapes": 2}


# --------------------------------------------------------------------------- #
# back_to_main_menu de rl_api_pp_connector (clavier et jeu remplacés : aucune touche n'est pressée)
# --------------------------------------------------------------------------- #

DOSSIER_CONNECTEUR = Path(__file__).resolve().parents[2] / "rl_api_pp_connector"


@pytest.fixture
def vrai_join_bot(monkeypatch):
    try:
        jb, _ = charger_connecteur(DOSSIER_CONNECTEUR)
    except ErreurConfig as erreur:
        pytest.skip(f"rl_api_pp_connector pas utilisable ici : {erreur}")
    touches, appels = [], []
    monkeypatch.setattr(jb, "press", touches.append)
    monkeypatch.setattr(jb, "focus_game", lambda: appels.append("focus"))
    monkeypatch.setattr(jb, "leave_match", lambda loc, delay, wait: appels.append("quitter"))
    monkeypatch.setattr(jb.time, "sleep", lambda s: None)
    return jb, touches, appels


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_back_to_main_menu_echap_jusqu_au_menu(vrai_join_bot):
    jb, touches, appels = vrai_join_bot
    loc = SimpleNamespace(ocr_ok=False, labels={"play": "PLAY"})
    jb.back_to_main_menu(loc, 0, port=port_libre())  # personne n'écoute : pas dans un match
    assert touches == ["esc"] * 4 and appels == ["focus"]


def test_back_to_main_menu_s_arrete_quand_jouer_est_visible(vrai_join_bot):
    jb, touches, _ = vrai_join_bot
    vus = iter([None, None, (300, 400)])  # le bouton JOUER apparaît après 2 appuis sur Échap
    loc = SimpleNamespace(ocr_ok=True, labels={"play": "PLAY"}, ocr_find=lambda label: next(vus))
    jb.back_to_main_menu(loc, 0, port=port_libre())
    assert touches == ["esc", "esc"]


def test_back_to_main_menu_quitte_le_match_si_finalement_rejoint(vrai_join_bot):
    jb, touches, appels = vrai_join_bot
    with socket.socket() as stats_api:  # la Stats API répond : le jeu est dans un match
        stats_api.bind(("127.0.0.1", 0))
        stats_api.listen()
        jb.back_to_main_menu(SimpleNamespace(ocr_ok=False, labels={}), 0, port=stats_api.getsockname()[1])
    assert appels == ["focus", "quitter"] and touches == []


def test_avertissement_si_retour_au_menu_pas_calibre(tmp_path):
    positions = tmp_path / "positions.json"
    positions.write_text(json.dumps({"resolution": [1920, 1200],
                                     "positions": {e: [0.5, 0.5] for e in ("play", "private_match", "join_private",
                                                                           "spectate", "leave_match")}}))
    avertissements = PiloteRL(reglages(tmp_path), FauxJoinBot(), WATCHER).verifier()
    assert len(avertissements) == 1 and "--calibrate-back-to-menu" in avertissements[0]


def test_back_to_main_menu_rejoue_les_actions_calibrees(vrai_join_bot, monkeypatch):
    jb, touches, _ = vrai_join_bot
    clics = []
    monkeypatch.setattr(jb, "click", lambda x, y: clics.append((x, y)))
    loc = SimpleNamespace(ocr_ok=False, labels={}, w=1920, h=1200,
                          positions={"back_to_menu": [["click", 0.5, 0.6], ["key", "esc"], ["click", 0.1, 0.9]]})
    jb.back_to_main_menu(loc, 0, port=port_libre(), escapes=4)
    assert clics == [(960, 720), (192, 1080)]
    assert touches == ["esc"]  # seulement l'Échap enregistré, pas les 4 par défaut


def test_calibration_du_retour_au_menu(vrai_join_bot, monkeypatch, tmp_path):
    jb, _, _ = vrai_join_bot
    fichier = tmp_path / "positions.json"
    fichier.write_text(json.dumps({"resolution": [1920, 1200], "positions": {"play": [0.1, 0.4]}}))
    rejoint = []
    monkeypatch.setattr(jb, "join_private_match", lambda loc, nom, mdp, delai: rejoint.append(nom))
    monkeypatch.setattr(jb, "wait_for_match", lambda host, port, timeout: None)  # la partie n'existe pas
    monkeypatch.setattr(jb.pyautogui, "position", lambda: (960, 600))
    reponses = iter(["", "esc", "", "fin"])  # clic, Échap, clic, menu principal atteint
    monkeypatch.setattr("builtins.input", lambda _question: next(reponses))

    jb.calibrate_back_to_menu(str(fichier), SimpleNamespace(), 1920, 1200, 0, 0, "127.0.0.1", 49123)

    assert rejoint and rejoint[0].startswith("inexistante_")
    data = json.loads(fichier.read_text(encoding="utf-8"))
    assert data["positions"]["play"] == [0.1, 0.4]  # le reste de la calibration est gardé
    assert data["positions"]["back_to_menu"] == [["click", 0.5, 0.5], ["key", "esc"], ["click", 0.5, 0.5]]
