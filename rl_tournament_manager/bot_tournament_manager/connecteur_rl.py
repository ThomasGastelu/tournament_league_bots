"""Vrai observateur (OBSERVATEUR=rl) : utilise le code de rl_api_pp_connector.

Tous les matchs d'un round se jouent en même temps. Une partie entre dans la tournée
quand son capitaine clique sur « Partie privée créée » (ou, sans clic, après
ATTENTE_CLIC_PP_MAX : voir deroulement.py). Le bot n'a qu'un Rocket League : il passe
donc dans les parties l'une après l'autre (la « tournée »), dans l'ordre d'arrivée :

    zone 1 → zone 2 → … → dernière zone → zone 1 → …

À chaque passage (une « visite ») :
  1. il rejoint la partie privée (rl_join_bot.join_private_match + wait_for_match) ;
  2. il passe spectateur ;
  3. il lit la Stats API pendant RL_DUREE_LECTURE secondes (score, temps, joueurs) ;
  4. il quitte la partie (rl_join_bot.leave_match) et attend le retour au menu.

Si le match est fini (événement MatchEnded, ou bHasWinner dans l'état), le bot a le
score : le match sort de la tournée et les joueurs reçoivent « vous pouvez quitter ».
Au premier échec dans une partie jamais vue, le capitaine reçoit de nouveau le nom et le
mot de passe (sur_partie_introuvable). Après RL_TENTATIVES échecs de suite (partie
introuvable, joueurs partis…), le match sort de la tournée, sans score : les joueurs le
déclarent (voir deroulement.py).

Après un échec, le jeu doit revenir au menu principal. Si rl_join_bot.py contient
une fonction back_to_main_menu(loc, delay), le bot l'appelle.

Le code du connecteur est bloquant (souris, clavier, socket) : chaque visite tourne
dans un thread (asyncio.to_thread) pour que le bot Discord continue de répondre.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import socket
import sys
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .observation import PartieAObserver

if TYPE_CHECKING:
    from .config import Config, ReglagesRL

log = logging.getLogger(__name__)

ETAPES_OBLIGATOIRES = ("play", "private_match", "join_private")
ETAPES_CONSEILLEES = ("spectate", "leave_match")

RAISON_INTROUVABLE = "le bot n'a pas pu rejoindre la partie après {n} essais"
RAISON_PARTIE_QUITTEE = "le bot n'a pas pu revenir dans la partie après {n} essais (joueurs partis ?)"
RAISON_RELANCEE = "la partie a été relancée avant que le bot prenne le score"
RAISON_ARRET_URGENCE = "arrêt d'urgence de l'observateur (souris dans le coin en haut à gauche)"


# --------------------------------------------------------------------------- #
# Lecture de la Stats API
# --------------------------------------------------------------------------- #

@dataclass
class Lecture:
    """Ce que le bot a vu pendant une visite."""
    rejoint: bool = False
    etat: dict | None = None        # dernier UpdateState (Data)
    termine: bool = False
    gagnant: int | None = None      # 0 = Bleu, 1 = Orange
    erreur: str | None = None
    evenements: list[str] = field(default_factory=list)


def _parse_data(msg: dict) -> dict:
    data = msg.get("Data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    return data or {}


def gagnant_depuis_etat(etat: dict | None) -> int | None:
    """Équipe gagnante d'après un UpdateState : champ Winner, sinon le meilleur score."""
    jeu = (etat or {}).get("Game") or {}
    equipes = jeu.get("Teams") or []
    vainqueur = jeu.get("Winner")
    for equipe in equipes:
        if vainqueur and equipe.get("Name") == vainqueur and equipe.get("TeamNum") in (0, 1):
            return equipe["TeamNum"]
    scores = {e.get("TeamNum"): e.get("Score") for e in equipes}
    if isinstance(scores.get(0), int) and isinstance(scores.get(1), int) and scores[0] != scores[1]:
        return 0 if scores[0] > scores[1] else 1
    return None


def lire_flux(sock: socket.socket, duree: float, stop: threading.Event,
              parse_data: Callable[[dict], dict] = _parse_data) -> Lecture:
    """Lit la Stats API pendant `duree` secondes (moins si le match est fini ou si `stop`)."""
    lecture = Lecture(rejoint=True)
    decodeur = json.JSONDecoder()
    tampon = ""
    limite = time.monotonic() + duree
    sock.settimeout(0.5)
    while time.monotonic() < limite and not stop.is_set():
        if lecture.termine and lecture.etat is not None:
            break
        try:
            morceau = sock.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            break
        if not morceau:
            break  # le jeu a fermé la connexion
        tampon += morceau.decode("utf-8", errors="ignore")
        while True:
            tampon = tampon.lstrip()
            if not tampon:
                break
            try:
                msg, fin = decodeur.raw_decode(tampon)
            except json.JSONDecodeError:
                break  # message incomplet : on attend la suite
            tampon = tampon[fin:]
            evenement = msg.get("Event")
            data = parse_data(msg)
            if evenement and evenement not in lecture.evenements:
                lecture.evenements.append(evenement)
            if evenement == "UpdateState":
                lecture.etat = data
                if (data.get("Game") or {}).get("bHasWinner"):
                    lecture.termine = True
                    lecture.gagnant = lecture.gagnant if lecture.gagnant in (0, 1) else gagnant_depuis_etat(data)
            elif evenement == "MatchEnded":
                lecture.termine = True
                if data.get("WinnerTeamNum") in (0, 1):
                    lecture.gagnant = data["WinnerTeamNum"]
    if lecture.termine and lecture.gagnant not in (0, 1):
        lecture.gagnant = gagnant_depuis_etat(lecture.etat)
    return lecture


def resume(etat: dict | None) -> str:
    """« Bleu 2 - 1 Orange, 3:12 restantes » pour la console."""
    if not etat:
        return "aucune donnée"
    jeu = etat.get("Game") or {}
    scores = {e.get("TeamNum"): e.get("Score", 0) for e in jeu.get("Teams") or []}
    secondes = int(jeu.get("TimeSeconds") or 0)
    temps = f"prolongation +{secondes // 60}:{secondes % 60:02d}" if jeu.get("bOvertime") \
        else f"{secondes // 60}:{secondes % 60:02d} restantes"
    return f"Bleu {scores.get(0, '?')} - {scores.get(1, '?')} Orange, {temps}"


# --------------------------------------------------------------------------- #
# Pilotage du jeu (bloquant : appelé dans un thread)
# --------------------------------------------------------------------------- #

def charger_connecteur(dossier: Path):
    """Importe rl_join_bot et rl_match_watcher depuis le dossier de rl_api_pp_connector."""
    from .config import ErreurConfig

    if not (dossier / "rl_join_bot.py").is_file():
        raise ErreurConfig(f"rl_api_pp_connector introuvable : pas de rl_join_bot.py dans {dossier} "
                           "(RL_DOSSIER_CONNECTEUR dans le .env).")
    if str(dossier) not in sys.path:
        sys.path.insert(0, str(dossier))
    installer = f"pip install -r \"{dossier / 'requirements.txt'}\""
    try:
        import rl_join_bot
        import rl_match_watcher
    except SystemExit as erreur:  # rl_join_bot fait sys.exit() si pyautogui manque
        raise ErreurConfig(f"Le connecteur ne peut pas démarrer : {erreur}\nInstalle ses modules dans le venv du "
                           f"bot : .venv\\Scripts\\python -m {installer}") from None
    except ImportError as erreur:
        raise ErreurConfig(f"Le connecteur ne peut pas démarrer : {erreur}\nInstalle ses modules dans le venv du "
                           f"bot : .venv\\Scripts\\python -m {installer}") from None
    return rl_join_bot, rl_match_watcher


class PiloteRL:
    """Fait une visite dans une partie avec les fonctions de rl_join_bot."""

    pause_lobby = 3.0  # secondes avant de cliquer sur « spectateur »

    def __init__(self, reglages: ReglagesRL, rl_join_bot=None, rl_match_watcher=None) -> None:
        from .config import ErreurConfig

        if rl_join_bot is None or rl_match_watcher is None:
            rl_join_bot, rl_match_watcher = charger_connecteur(reglages.dossier_connecteur)
        self.r = reglages
        self.jb = rl_join_bot
        self.watcher = rl_match_watcher
        self.avertissements: list[str] = []

        calibration: dict = {}
        if reglages.positions.is_file():
            try:
                calibration = json.loads(reglages.positions.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as erreur:
                raise ErreurConfig(f"Calibration illisible ({reglages.positions}) : {erreur}") from None
        positions = calibration.get("positions", {})
        resolution = reglages.resolution or tuple(calibration.get("resolution") or ()) or None
        if resolution is None:
            resolution = tuple(self.jb.pyautogui.size())
        self.largeur, self.hauteur = int(resolution[0]), int(resolution[1])

        self.loc = self.jb.Locator(self.largeur, self.hauteur, reglages.langue, positions,
                                   dict(self.jb.LABELS[reglages.langue]), reglages.tesseract)
        manquantes = [e for e in ETAPES_OBLIGATOIRES if e not in positions]
        if manquantes and not self.loc.ocr_ok:
            raise ErreurConfig(
                f"Calibration incomplète ({reglages.positions}) : il manque {', '.join(manquantes)}, et Tesseract "
                f"(lecture de l'écran) n'est pas installé. Calibre les boutons : dans {reglages.dossier_connecteur}, "
                f"python rl_join_bot.py --calibrate --resolution {self.largeur}x{self.hauteur} --language "
                f"{reglages.langue}")
        for etape in ETAPES_CONSEILLEES:
            if etape not in positions:
                self.avertissements.append(f"Calibration : l'étape « {etape} » n'est pas calibrée "
                                           f"(python rl_join_bot.py --calibrate --steps {etape} …).")
        try:
            ecran = tuple(self.jb.pyautogui.size())
            if ecran != (self.largeur, self.hauteur):
                self.avertissements.append(f"L'écran fait {ecran[0]}x{ecran[1]} mais la calibration est en "
                                           f"{self.largeur}x{self.hauteur} : le bot risque de cliquer à côté.")
        except Exception:  # pas d'écran (tests, session distante…)
            pass
        if getattr(self.jb, "back_to_main_menu", None) is None:
            self.avertissements.append("rl_join_bot.py n'a pas de fonction back_to_main_menu(loc, delay) : après "
                                       "un échec de connexion, le jeu doit revenir seul au menu principal.")
        elif "back_to_menu" not in positions:
            self.avertissements.append(
                f"Retour au menu après un échec de connexion pas calibré : le bot appuiera sur Échap "
                f"{reglages.echap_retour_menu} fois. Pour le calibrer, dans {reglages.dossier_connecteur} : "
                f"python rl_join_bot.py --calibrate-back-to-menu --resolution {self.largeur}x{self.hauteur} "
                f"--language {reglages.langue}")

    def verifier(self) -> list[str]:
        """Avertissements à afficher au démarrage (+ fenêtre Rocket League ouverte ?)."""
        avertissements = list(self.avertissements)
        gw = getattr(self.jb, "gw", None)
        try:
            if gw is not None and not [w for w in gw.getWindowsWithTitle("Rocket League") if w.title.strip()]:
                avertissements.append("Fenêtre Rocket League introuvable : lance le jeu et laisse-le au menu "
                                      "principal avant le premier round.")
        except Exception:
            pass
        return avertissements

    def construire_resultat(self, etat: dict | None, gagnant: int | None) -> dict:
        """Résultat au format de scores.json (rl_match_watcher.build_result)."""
        if etat:
            return self.watcher.build_result(etat, gagnant)
        return {"date": datetime.now().isoformat(timespec="seconds"), "match_guid": None, "arena": None,
                "overtime": None, "winner_team_num": gagnant, "teams": [], "players": []}

    def _retour_menu(self) -> None:
        retour = getattr(self.jb, "back_to_main_menu", None)
        if retour is None:
            return
        # Réglages passés seulement si la fonction les accepte (une version plus simple reste utilisable).
        options = {"host": self.r.hote, "port": self.r.port, "escapes": self.r.echap_retour_menu}
        try:
            parametres = inspect.signature(retour).parameters
            if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametres.values()):
                options = {nom: valeur for nom, valeur in options.items() if nom in parametres}
        except (TypeError, ValueError):
            options = {}
        try:
            retour(self.loc, self.r.delai_menus, **options)
        except Exception as erreur:
            if type(erreur).__name__ == "FailSafeException":
                raise
            log.warning("[rl] back_to_main_menu a échoué : %s", erreur)

    def visiter(self, partie: PartieAObserver, stop: threading.Event) -> Lecture:
        """Rejoint la partie, lit le score, quitte. Bloquant (plusieurs dizaines de secondes)."""
        self.jb.focus_game()
        try:
            self.jb.join_private_match(self.loc, partie.nom, partie.mot_de_passe, self.r.delai_menus)
        except RuntimeError as erreur:  # bouton introuvable à l'écran
            self._retour_menu()
            return Lecture(erreur=str(erreur))
        sock = self.jb.wait_for_match(self.r.hote, self.r.port, self.r.timeout_rejoindre)
        if sock is None:
            self._retour_menu()
            return Lecture(erreur="partie introuvable (pas encore créée, fermée, ou nom/mot de passe faux)")
        try:
            time.sleep(self.pause_lobby)  # comme rl_join_bot : laisser le lobby s'afficher
            if not self.loc.click_step("spectate", timeout=10, required=False):
                log.warning("[rl] %s : bouton spectateur introuvable, le bot reste joueur dans la partie", partie.nom)
            return lire_flux(sock, self.r.duree_lecture, stop, self.watcher.parse_data)
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self.jb.leave_match(self.loc, self.r.delai_menus, wait=0)
            time.sleep(self.r.pause_apres_sortie)


# --------------------------------------------------------------------------- #
# La tournée
# --------------------------------------------------------------------------- #

@dataclass
class _Visite:
    partie: PartieAObserver
    futur: asyncio.Future
    echecs: int = 0               # échecs de suite
    visites: int = 0
    dernier_etat: dict | None = None
    guid: str | None = None


class ObservateurRL:
    """Une seule tournée pour toutes les parties en cours (tous tournois confondus)."""

    def __init__(self, pilote, *, tentatives: int = 3) -> None:
        self.pilote = pilote
        self.tentatives = tentatives
        # Branché par le gestionnaire : prévient le capitaine quand sa partie est introuvable.
        self.sur_partie_introuvable: Callable[[PartieAObserver], Awaitable[None]] | None = None
        self._annexes: set[asyncio.Task] = set()
        self._file: deque[_Visite] = deque()
        self._tache: asyncio.Task | None = None
        self._en_cours: _Visite | None = None
        self._stop = threading.Event()
        self._pause: str | None = None

    @classmethod
    def depuis_config(cls, config: Config) -> ObservateurRL:
        r = config.rl
        return cls(PiloteRL(r), tentatives=r.tentatives)

    def verifier(self) -> list[str]:
        return self.pilote.verifier()

    async def observer(self, partie: PartieAObserver) -> dict:
        if self._pause:
            return self._resultat_echec(partie, None, self._pause)
        visite = _Visite(partie, asyncio.get_running_loop().create_future())
        self._file.append(visite)
        if self._tache is None or self._tache.done():
            self._tache = asyncio.create_task(self._tournee(), name="tournee-rl")
        try:
            return await visite.futur
        except asyncio.CancelledError:
            # /stop_tournament_rl, score validé à la main, arrêt du bot : on quitte la partie au plus vite.
            if self._en_cours is visite:
                self._stop.set()
            raise

    async def _tournee(self) -> None:
        while (visite := self._prochaine()) is not None:
            self._en_cours = visite
            self._stop.clear()
            try:
                lecture = await asyncio.to_thread(self.pilote.visiter, visite.partie, self._stop)
            except Exception as erreur:
                if type(erreur).__name__ == "FailSafeException":
                    self._file.appendleft(visite)  # pour qu'elle aussi reçoive son résultat
                    self._arret_urgence()
                    return
                log.exception("[rl] %s : erreur pendant la visite", self._nom(visite))
                lecture = Lecture(erreur=f"erreur : {erreur}")
            finally:
                self._en_cours = None
            if not visite.futur.done():
                self._traiter(visite, lecture)
            if not visite.futur.done():
                self._file.append(visite)  # repassera au prochain tour

    def _prochaine(self) -> _Visite | None:
        """Prochaine partie de la tournée (dans l'ordre), ou None s'il n'y en a plus."""
        while self._file:
            visite = self._file.popleft()
            if not visite.futur.done():  # sinon : annulée (score validé à la main, tournoi arrêté…)
                return visite
        return None

    def _traiter(self, visite: _Visite, lecture: Lecture) -> None:
        visite.visites += 1
        nom = self._nom(visite)
        if not lecture.rejoint or lecture.etat is None:
            visite.echecs += 1
            log.info("[rl] %s : échec %s/%s (%s)", nom, visite.echecs, self.tentatives,
                     lecture.erreur or "aucune donnée de la Stats API")
            if visite.echecs == 1 and visite.dernier_etat is None and visite.echecs < self.tentatives:
                self._prevenir_partie_introuvable(visite.partie)
            if visite.echecs >= self.tentatives:
                modele = RAISON_PARTIE_QUITTEE if visite.dernier_etat else RAISON_INTROUVABLE
                visite.futur.set_result(self._resultat_echec(visite.partie, visite.dernier_etat,
                                                             modele.format(n=visite.echecs)))
            return

        visite.echecs = 0
        guid = lecture.etat.get("MatchGuid")
        if visite.guid and guid and guid != visite.guid:
            log.warning("[rl] %s : la partie a été relancée (nouveau match)", nom)
            visite.futur.set_result(self._resultat_echec(visite.partie, visite.dernier_etat, RAISON_RELANCEE))
            return
        visite.guid = visite.guid or guid
        visite.dernier_etat = lecture.etat
        if lecture.termine:
            log.info("[rl] %s : match terminé, score pris (%s)", nom, resume(lecture.etat))
            resultat = self.pilote.construire_resultat(lecture.etat, lecture.gagnant)
            resultat.update({"partie": visite.partie.nom, "statut": "terminé", "visites": visite.visites})
            visite.futur.set_result(resultat)
        else:
            log.info("[rl] %s : %s", nom, resume(lecture.etat))

    def _prevenir_partie_introuvable(self, partie: PartieAObserver) -> None:
        if self.sur_partie_introuvable is None:
            return

        async def prevenir() -> None:
            try:
                await self.sur_partie_introuvable(partie)  # type: ignore[misc]
            except Exception:
                log.exception("[rl] Impossible de prévenir le capitaine (partie %s)", partie.nom)

        tache = asyncio.create_task(prevenir())
        self._annexes.add(tache)
        tache.add_done_callback(self._annexes.discard)

    def _resultat_echec(self, partie: PartieAObserver, etat: dict | None, raison: str) -> dict:
        resultat = self.pilote.construire_resultat(etat, None)
        resultat.update({"partie": partie.nom, "statut": raison})
        return resultat

    def _arret_urgence(self) -> None:
        self._pause = RAISON_ARRET_URGENCE
        log.error("[rl] Arrêt d'urgence : le bot ne pilote plus Rocket League. Les matchs en cours passent en "
                  "déclaration par les joueurs. Redémarre le bot pour relancer l'observation.")
        while self._file:
            visite = self._file.popleft()
            if not visite.futur.done():
                visite.futur.set_result(self._resultat_echec(visite.partie, visite.dernier_etat, self._pause))

    @staticmethod
    def _nom(visite: _Visite) -> str:
        p = visite.partie
        return f"tournoi {p.tournoi_id} round {p.ronde} zone {p.zone} « {p.nom} »"
