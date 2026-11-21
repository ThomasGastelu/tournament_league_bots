#!/usr/bin/env python3
"""
rl_join_bot.py - Rejoint automatiquement une partie privée Rocket League
(nom + mot de passe) en pilotant les menus, puis suit le score via la Stats API.

Fonctionne sous Windows, avec Rocket League en "Plein écran fenêtré" (borderless)
et la Stats API activée (PacketSendRate > 0). Place ce fichier dans le même dossier
que rl_match_watcher.py.

Installation :
  pip install pyautogui pytesseract pillow pydirectinput
  + Tesseract-OCR pour Windows : https://github.com/UB-Mannheim/tesseract/wiki
    (cocher la langue "French" pendant l'installation si --language fr)

Exemples :
  # Étape conseillée, une seule fois : enregistrer la position des boutons
  python rl_join_bot.py --calibrate --resolution 1920x1080 --language fr

  # Rejoindre une partie et suivre le score
  python rl_join_bot.py --name MaPartie --password 1234 --resolution 1920x1080 --language fr

  # En spectateur, et quitter le match automatiquement à la fin
  python rl_join_bot.py --name MaPartie --password 1234 --resolution 1920x1080 --language fr --spectate --leave
"""

import argparse
import difflib
import json
import os
import socket
import sys
import threading
import time
import unicodedata

try:
    import pyautogui
except ImportError:
    sys.exit("Module manquant : pip install pyautogui pillow")

try:
    import pydirectinput  # clics mieux reçus par les jeux DirectX
    pydirectinput.PAUSE = 0.05
except ImportError:
    pydirectinput = None

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import pygetwindow as gw  # installé avec pyautogui sous Windows
except ImportError:
    gw = None

from rl_match_watcher import parse_data, score_line, build_result

pyautogui.FAILSAFE = True  # souris dans le coin haut-gauche = arrêt d'urgence

# ---------------------------------------------------------------------------
# Textes des menus par langue (modifiables via --labels fichier.json)
# Si un texte ne correspond pas exactement à ton jeu, corrige-le dans un
# fichier labels.json, ex. : {"fr": {"join_private": "REJOINDRE UNE PARTIE PRIVÉE"}}
# ---------------------------------------------------------------------------
LABELS = {
    "fr": {
        "play": "JOUER",
        "private_match": "MATCH PRIVÉ",
        "join_private": "REJOINDRE UN MATCH PRIVÉ",
        "join_button": "REJOINDRE",
        "spectate": "SPECTATEUR",
        "leave_match": "QUITTER LE MATCH",
        "confirm_yes": "OUI",
    },
    "en": {
        "play": "PLAY",
        "private_match": "PRIVATE MATCH",
        "join_private": "JOIN PRIVATE MATCH",
        "join_button": "JOIN",
        "spectate": "SPECTATE",
        "leave_match": "LEAVE MATCH",
        "confirm_yes": "YES",
    },
}
TESSERACT_LANG = {"fr": "fra", "en": "eng"}

# Étapes de calibration (dans l'ordre où on les rencontre dans le jeu)
CALIBRATION_STEPS = [
    ("play", "le bouton JOUER du menu principal"),
    ("private_match", "le bouton MATCH PRIVÉ"),
    ("join_private", "le bouton REJOINDRE UN MATCH PRIVÉ"),
    ("name_field", "le champ NOM de la fenêtre qui s'ouvre"),
    ("password_field", "le champ MOT DE PASSE"),
    ("join_button", "le bouton REJOINDRE de cette fenêtre"),
    ("spectate", "le bouton pour passer SPECTATEUR dans le lobby (facultatif)"),
    ("leave_match", "le bouton LEAVE MATCH du menu pause (appuie d'abord sur Échap dans le jeu)"),
    ("confirm_yes", "le bouton YES de confirmation (s'il n'y en a pas : 'skip')"),
]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.upper().split())


# ---------------------------------------------------------------------------
# Souris / clavier
# ---------------------------------------------------------------------------
def active_window() -> str:
    """Titre de la fenêtre au premier plan (Windows), pour comprendre les changements de fenêtre."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value or "(sans titre)"
    except Exception:
        return "?"


def log_active_window(moment: str) -> None:
    print(f"  [fenêtre active {moment} : {active_window()}]")


def click(x: int, y: int) -> None:
    avant = active_window()
    _click(x, y)
    apres = active_window()
    if apres != avant:
        print(f"  [!] la fenêtre active a changé pendant le clic en ({x}, {y}) : '{avant}' -> '{apres}'")


def _click(x: int, y: int) -> None:
    if pydirectinput:
        pydirectinput.moveTo(x, y)
        time.sleep(0.1)
        pydirectinput.click()
    else:
        pyautogui.moveTo(x, y, duration=0.15)
        pyautogui.click()


def type_text(text: str) -> None:
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.press("backspace")
    pyautogui.write(text, interval=0.04)


def press(key: str) -> None:
    (pydirectinput or pyautogui).press(key)


# ---------------------------------------------------------------------------
# Recherche des boutons : positions calibrées, sinon lecture de l'écran (OCR)
# ---------------------------------------------------------------------------
class Locator:
    def __init__(self, width, height, language, positions, labels, tesseract_cmd):
        self.w, self.h = width, height
        self.language = language
        self.positions = positions
        self.labels = labels
        self.ocr_ok = False
        if pytesseract:
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            try:
                pytesseract.get_tesseract_version()
                self.ocr_ok = True
            except Exception:
                self.ocr_ok = False

    def calibrated(self, step):
        pos = self.positions.get(step)
        if pos:
            return int(pos[0] * self.w), int(pos[1] * self.h)
        return None

    def ocr_find(self, label: str):
        if not self.ocr_ok:
            return None
        img = pyautogui.screenshot(region=(0, 0, self.w, self.h))
        data = pytesseract.image_to_data(
            img, lang=TESSERACT_LANG[self.language],
            output_type=pytesseract.Output.DICT)

        # Regroupe les mots par ligne de texte
        lines = {}
        for i, word in enumerate(data["text"]):
            if not word.strip() or float(data["conf"][i]) < 0:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines.setdefault(key, []).append(i)

        target = normalize(label)
        best, best_ratio = None, 0.0
        for idxs in lines.values():
            text = normalize(" ".join(data["text"][i] for i in idxs))
            ratio = difflib.SequenceMatcher(None, text, target).ratio()
            if ratio > best_ratio:
                left = min(data["left"][i] for i in idxs)
                top = min(data["top"][i] for i in idxs)
                right = max(data["left"][i] + data["width"][i] for i in idxs)
                bottom = max(data["top"][i] + data["height"][i] for i in idxs)
                best, best_ratio = ((left + right) // 2, (top + bottom) // 2), ratio
        return best if best_ratio >= 0.8 else None

    def find(self, step: str, timeout: float = 15.0):
        pos = self.calibrated(step)
        if pos:
            return pos
        label = self.labels.get(step)
        if not label or not self.ocr_ok:
            return None
        end = time.time() + timeout
        while time.time() < end:
            pos = self.ocr_find(label)
            if pos:
                return pos
            time.sleep(1)
        return None

    def click_step(self, step: str, timeout: float = 15.0, required: bool = True) -> bool:
        pos = self.find(step, timeout)
        if not pos:
            if required:
                raise RuntimeError(
                    f"Introuvable à l'écran : '{step}' ({self.labels.get(step, 'non calibré')}). "
                    f"Fais une calibration (--calibrate) ou corrige le texte avec --labels.")
            return False
        print(f"  -> clic sur '{step}' en {pos}")
        click(*pos)
        return True


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------
def calibrate(path: str, width: int, height: int, countdown: int, only=None) -> None:
    # Conserve les positions déjà enregistrées (utile avec --steps)
    positions = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                positions = json.load(f).get("positions", {})
        except (json.JSONDecodeError, OSError):
            positions = {}

    steps = CALIBRATION_STEPS
    if only:
        known = {s for s, _ in CALIBRATION_STEPS}
        unknown = [s for s in only if s not in known]
        if unknown:
            sys.exit(f"Étape(s) inconnue(s) : {', '.join(unknown)}. "
                     f"Possibles : {', '.join(sorted(known))}")
        steps = [(s, d) for s, d in CALIBRATION_STEPS if s in only]

    print("CALIBRATION")
    if only:
        print(f"Étapes à calibrer : {', '.join(s for s, _ in steps)} "
              f"(les autres positions sont conservées).")
        print("Place le jeu sur l'écran où se trouve le premier élément.")
    else:
        print("Lance Rocket League en plein écran fenêtré et va au menu principal.")
    print("Pour chaque étape :")
    print("  1. Appuie sur ENTRÉE (sans rien taper) dans cette console.")
    print(f"  2. Tu as {countdown} s pour placer la souris sur l'élément dans le jeu, sans cliquer.")
    print("  3. Une fois la position enregistrée, clique toi-même dessus pour aller à l'écran suivant.")
    print("Pour sauter une étape (seulement 'spectate' si tu n'en as pas besoin) : tape 'skip' puis Entrée.\n")

    for step, desc in steps:
        answer = input(f"[{step}] Souris sur {desc}. ENTRÉE = enregistrer, "
                       f"'skip' = sauter : ").strip().lower()
        if answer == "skip":
            print("   étape sautée")
            continue
        for i in range(countdown, 0, -1):
            print(f"   {i}...", end="", flush=True)
            time.sleep(1)
        x, y = pyautogui.position()
        positions[step] = [round(x / width, 4), round(y / height, 4)]
        print(f"   enregistré : ({x}, {y})")

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"resolution": [width, height], "positions": positions}, f, indent=2)
    if positions:
        print(f"\n{len(positions)} position(s) enregistrée(s) dans {path} : {', '.join(positions)}")
    else:
        print(f"\nAucune position enregistrée ! Relance la calibration en appuyant "
              f"simplement sur ENTRÉE à chaque étape.")


# ---------------------------------------------------------------------------
# Rejoindre la partie
# ---------------------------------------------------------------------------
def join_private_match(loc: Locator, name: str, password: str, delay: float) -> None:
    print(f"Rejoindre la partie privée '{name}'...")
    log_active_window("avant de rejoindre")
    loc.click_step("play"); time.sleep(delay)
    loc.click_step("private_match"); time.sleep(delay)
    loc.click_step("join_private"); time.sleep(delay)

    # Champ nom
    pos = loc.calibrated("name_field")
    if pos:
        print(f"  -> clic sur 'name_field' en {pos}")
        click(*pos); time.sleep(0.3)
    type_text(name); time.sleep(0.3)

    # Champ mot de passe
    pos = loc.calibrated("password_field")
    if pos:
        print(f"  -> clic sur 'password_field' en {pos}")
        click(*pos); time.sleep(0.3)
    else:
        press("tab"); time.sleep(0.3)  # sans calibration : on suppose Tab = champ suivant
    type_text(password); time.sleep(0.3)

    if not loc.click_step("join_button", timeout=5, required=False):
        press("enter")
    print("Demande envoyée, attente du chargement du match...")


# Événements que la Stats API n'envoie que pendant un match.
MATCH_EVENTS = {"MatchCreated", "MatchInitialized", "CountdownBegin", "RoundStarted",
                "ClockUpdatedSeconds", "GoalScored", "BallHit", "CrossbarHit", "StatfeedEvent",
                "MatchEnded", "PodiumStart", "ReplayStart", "ReplayEnd"}


def in_match(host: str, port: int, listen: float = 3.0) -> bool:
    """True si le jeu est DANS un match.

    Attention : le port de la Stats API accepte les connexions dès que le jeu tourne,
    même au menu principal. Une connexion réussie ne prouve donc rien : il faut
    recevoir des données de match (UpdateState avec des joueurs ou des équipes,
    ou un événement de match).
    """
    try:
        sock = socket.create_connection((host, port), timeout=2)
    except OSError:
        return False
    decoder = json.JSONDecoder()
    buf = ""
    end = time.time() + listen
    with sock:
        sock.settimeout(0.5)
        while time.time() < end:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return False
            if not chunk:
                return False
            buf += chunk.decode("utf-8", errors="ignore")
            while True:
                buf = buf.lstrip()
                if not buf:
                    break
                try:
                    msg, fin = decoder.raw_decode(buf)
                except json.JSONDecodeError:
                    if len(buf) > 1_000_000:
                        buf = ""  # flux illisible : on repart de zéro
                    break  # message incomplet : on attend la suite
                buf = buf[fin:]
                if not isinstance(msg, dict):
                    continue
                event = msg.get("Event")
                if event in MATCH_EVENTS:
                    return True
                if event == "UpdateState":
                    data = parse_data(msg)
                    if data.get("Players") or (data.get("Game") or {}).get("Teams"):
                        return True
    return False


def wait_for_match(host: str, port: int, timeout: float):
    """Attend d'être vraiment dans le match (données de match reçues), puis renvoie
    une connexion neuve à la Stats API (qui commence au début d'un message)."""
    end = time.time() + timeout
    while time.time() < end:
        if in_match(host, port, listen=min(3.0, max(0.5, end - time.time()))):
            try:
                sock = socket.create_connection((host, port), timeout=3)
                sock.settimeout(None)
                return sock
            except OSError:
                pass
        time.sleep(1)
    return None


QUIT_WORDS = {"quit", "q", "quitter", "leave", "exit", "stop"}


def start_command_listener() -> threading.Event:
    """Lit le terminal en arrière-plan : 'quit' + Entrée demande la sortie du match."""
    quit_event = threading.Event()

    def listen():
        while not quit_event.is_set():
            try:
                line = input().strip().lower()
            except (EOFError, OSError):
                return
            if line in QUIT_WORDS:
                print(">>> Commande reçue : sortie de la partie...")
                quit_event.set()
                return
            if line:
                print("Commande inconnue. Tape 'quit' puis Entrée pour quitter la partie.")

    threading.Thread(target=listen, daemon=True).start()
    return quit_event


def save_score_json(path: str, result: dict) -> None:
    """Ajoute un résultat à la liste contenue dans scores.json."""
    scores = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                scores = json.load(f)
            if not isinstance(scores, list):
                scores = [scores]
        except (json.JSONDecodeError, OSError):
            backup = path + ".bak"
            os.replace(path, backup)
            print(f"Attention : {path} était illisible, sauvegardé sous {backup}.")
            scores = []
    scores.append(result)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # écriture d'un coup : pas de fichier à moitié écrit
    print(f"Score enregistré dans {path} ({len(scores)} match(s) au total)")


def follow_match(sock: socket.socket, output: str, quit_event: threading.Event,
                 match_name: str) -> str:
    """Suit le match. Renvoie 'ended' (fin normale), 'quit' (commande) ou 'closed'."""
    decoder = json.JSONDecoder()
    buf = ""
    last_state, last_printed = None, ""

    def record(status: str, winner):
        if last_state and output:
            result = build_result(last_state, winner)
            result["partie"] = match_name
            result["statut"] = status
            save_score_json(output, result)

    sock.settimeout(0.5)  # permet de vérifier régulièrement la commande 'quit'
    with sock:
        while True:
            if quit_event.is_set():
                if last_state:
                    print("Score au moment de quitter : " + score_line(last_state))
                record("quitté avant la fin", None)
                return "quit"
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                return "closed"
            if not chunk:
                print("Connexion fermée par le jeu.")
                record("connexion perdue", None)
                return "closed"

            buf += chunk.decode("utf-8", errors="ignore")
            while True:
                buf = buf.lstrip()
                if not buf:
                    break
                try:
                    msg, end = decoder.raw_decode(buf)
                except json.JSONDecodeError:
                    break  # message incomplet
                buf = buf[end:]

                event = msg.get("Event")
                data = parse_data(msg)
                if event == "UpdateState":
                    last_state = data
                    line = score_line(data)
                    if line != last_printed:
                        print(line)
                        last_printed = line
                elif event == "GoalScored":
                    print(f"  >>> BUT de {(data.get('Scorer') or {}).get('Name', '?')} !")
                elif event == "MatchEnded":
                    winner = data.get("WinnerTeamNum")
                    print(f"=== FIN DU MATCH - gagnant : "
                          f"{'Bleu' if winner == 0 else 'Orange' if winner == 1 else winner} ===")
                    if last_state:
                        print("Score final : " + score_line(last_state))
                    record("terminé", winner)
                    return "ended"


def focus_game() -> None:
    """Ne fait rien : Rocket League est censé être TOUJOURS au premier plan.

    Le bot ne change plus de fenêtre tout seul. Garde Rocket League devant pendant
    que le bot tourne, sinon les clics et les touches partent dans une autre fenêtre.
    (Fonction gardée car tournament_manager l'appelle.)
    """


def leave_match(loc: Locator, delay: float, wait: float) -> None:
    print("Sortie du match...")
    time.sleep(wait)  # après une fin normale : laisse passer l'écran de fin / podium
    focus_game()
    press("esc"); time.sleep(delay)
    if not loc.click_step("leave_match", timeout=10, required=False):
        print("Bouton 'leave_match' introuvable : calibre-le avec "
              "--calibrate --steps leave_match,confirm_yes")
        return
    time.sleep(delay)
    loc.click_step("confirm_yes", timeout=5, required=False)
    print("Partie quittée.")


def stats_api_ouverte(host: str, port: int) -> bool:
    """True si le jeu est dans un match (le port seul ne suffit pas : voir in_match)."""
    return in_match(host, port, listen=2.0)


# Actions enregistrées par --calibrate-back-to-menu (dans positions.json, avec les autres étapes) :
# [["click", x, y], ["key", "esc"], ...] avec x, y en proportion de l'écran.
BACK_TO_MENU = "back_to_menu"


def back_to_main_menu(loc: Locator, delay: float, host: str = "127.0.0.1", port: int = 49123,
                      escapes: int = 4) -> None:
    """Revient au menu principal après un échec de connexion à une partie privée.

    - Si la connexion a finalement réussi (le jeu est dans un match) : on quitte le
      match normalement (leave_match).
    - Si le retour au menu est calibré (--calibrate-back-to-menu) : on rejoue les
      actions enregistrées (clics sur la fenêtre d'erreur, Échap…).
    - Sinon : Échap jusqu'à `escapes` fois (fenêtre d'erreur, fenêtre de connexion,
      Match privé, Jouer). Avec Tesseract, on s'arrête dès que JOUER est visible.
    """
    print("Retour au menu principal...")
    focus_game()
    if stats_api_ouverte(host, port):
        print("Le jeu est dans un match : on le quitte.")
        leave_match(loc, delay, wait=0)
        return
    actions = (getattr(loc, "positions", None) or {}).get(BACK_TO_MENU)
    if actions:
        for action in actions:
            if action[0] == "click":
                print(f"  -> clic en ({action[1]}, {action[2]})")
                click(int(action[1] * loc.w), int(action[2] * loc.h))
            else:
                press(action[1])
            time.sleep(delay)
    else:
        for _ in range(escapes):
            if loc.ocr_ok and loc.ocr_find(loc.labels.get("play", "")):
                break  # déjà au menu principal
            press("esc")
            time.sleep(delay)
    print("Menu principal.")


def calibrate_back_to_menu(path: str, loc: Locator, width: int, height: int, countdown: int,
                           delay: float, host: str, port: int) -> None:
    """Enregistre comment revenir au menu principal quand la partie privée n'existe pas.

    Le bot essaie lui-même de rejoindre une partie qui n'existe pas, pour afficher
    l'erreur. Ensuite on enregistre, dans l'ordre, chaque action qui ramène au menu
    principal : un clic (position de la souris) ou la touche Échap.
    """
    print("CALIBRATION DU RETOUR AU MENU (quand la partie privée n'existe pas)")
    print("Mets Rocket League au premier plan, sur le menu principal. Dans 5 s, le bot essaie "
          "de rejoindre une partie qui n'existe pas.")
    time.sleep(5)
    nom = "inexistante_" + os.urandom(3).hex()
    join_private_match(loc, nom, nom, delay)
    sock = wait_for_match(host, port, 20)
    if sock:
        sock.close()
        sys.exit(f"La partie '{nom}' a été rejointe : impossible de calibrer l'erreur. Recommence.")

    print("\nLe jeu doit maintenant afficher l'erreur. Enregistre, dans l'ordre, chaque action "
          "qui ramène au menu principal :")
    print(f"  ENTRÉE (sans rien taper) = un clic : tu as {countdown} s pour poser la souris sur le "
          "bouton dans le jeu (sans cliquer), puis clique toi-même dessus ;")
    print("  'esc' = la touche Échap : appuie ensuite toi-même sur Échap dans le jeu ;")
    print("  'fin' = tu es revenu au menu principal.\n")
    actions = []
    while True:
        reponse = input(f"[action {len(actions) + 1}] ENTRÉE = clic, 'esc' = Échap, "
                        f"'fin' = menu principal atteint : ").strip().lower()
        if reponse == "fin":
            break
        if reponse in ("esc", "echap", "échap"):
            actions.append(["key", "esc"])
            print("   enregistré : Échap (appuie maintenant sur Échap dans le jeu)")
            continue
        if reponse:
            print("   réponse inconnue : ENTRÉE, 'esc' ou 'fin'")
            continue
        for i in range(countdown, 0, -1):
            print(f"   {i}...", end="", flush=True)
            time.sleep(1)
        x, y = pyautogui.position()
        actions.append(["click", round(x / width, 4), round(y / height, 4)])
        print(f"   enregistré : clic en ({x}, {y}) (clique maintenant dessus toi-même)")

    if not actions:
        print("Aucune action enregistrée : rien n'est changé.")
        return
    data = {"resolution": [width, height], "positions": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault("positions", {})[BACK_TO_MENU] = actions
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nRetour au menu enregistré dans {path} : "
          + ", ".join("Échap" if a[0] == "key" else "clic" for a in actions))


# ---------------------------------------------------------------------------
def parse_resolution(value: str):
    try:
        w, h = value.lower().replace(" ", "").split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("Format attendu : LARGEURxHAUTEUR, ex. 1920x1080")


def main():
    p = argparse.ArgumentParser(
        description="Rejoint une partie privée Rocket League et suit le score.")
    p.add_argument("--name", help="Nom de la partie privée")
    p.add_argument("--password", default="", help="Mot de passe de la partie privée")
    p.add_argument("--resolution", type=parse_resolution, required=True,
                   help="Résolution de l'écran du jeu, ex. 1920x1080")
    p.add_argument("--language", choices=sorted(LABELS), required=True,
                   help="Langue du jeu (pour lire les menus)")
    p.add_argument("--spectate", action="store_true",
                   help="Passer en spectateur une fois dans le lobby")
    p.add_argument("--leave", action="store_true",
                   help="Quitter le match automatiquement à la fin")
    p.add_argument("--output", default="scores.json",
                   help="Fichier JSON des scores (défaut : scores.json)")
    p.add_argument("--host", default="127.0.0.1", help="Adresse de la Stats API")
    p.add_argument("--port", type=int, default=49123, help="Port de la Stats API")
    p.add_argument("--join-timeout", type=float, default=90,
                   help="Secondes max pour entrer dans le match (défaut : 90)")
    p.add_argument("--delay", type=float, default=1.5,
                   help="Pause entre deux écrans de menu, en secondes (défaut : 1.5)")
    p.add_argument("--positions", default="positions.json",
                   help="Fichier de calibration (défaut : positions.json)")
    p.add_argument("--labels", help="Fichier JSON pour corriger les textes des menus")
    p.add_argument("--tesseract", default=r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                   help="Chemin vers tesseract.exe")
    p.add_argument("--calibrate", action="store_true",
                   help="Enregistre la position des boutons puis quitte")
    p.add_argument("--countdown", type=int, default=5,
                   help="Secondes pour placer la souris pendant la calibration")
    p.add_argument("--quit-delay", type=int, default=5,
                   help="Secondes d'attente après 'quit' avant de bouger la souris (défaut : 5)")
    p.add_argument("--steps",
                   help="Avec --calibrate : ne calibrer que ces étapes, séparées par des "
                        "virgules (ex. leave_match,confirm_yes)")
    p.add_argument("--calibrate-back-to-menu", action="store_true",
                   help="Enregistre comment revenir au menu principal quand la partie privée "
                        "n'existe pas, puis quitte")
    args = p.parse_args()

    width, height = args.resolution
    screen_w, screen_h = pyautogui.size()
    if (screen_w, screen_h) != (width, height):
        print(f"Attention : l'écran fait {screen_w}x{screen_h}, "
              f"mais --resolution vaut {width}x{height}.")

    if args.calibrate:
        only = [s.strip() for s in args.steps.split(",") if s.strip()] if args.steps else None
        calibrate(args.positions, width, height, args.countdown, only)
        return

    if not args.name and not args.calibrate_back_to_menu:
        p.error("--name est obligatoire (sauf avec --calibrate ou --calibrate-back-to-menu)")

    labels = dict(LABELS[args.language])
    if args.labels:
        with open(args.labels, encoding="utf-8") as f:
            labels.update(json.load(f).get(args.language, {}))

    positions = {}
    if os.path.exists(args.positions):
        with open(args.positions, encoding="utf-8") as f:
            positions = json.load(f).get("positions", {})
        print(f"Calibration chargée depuis {args.positions}")
    elif not pytesseract:
        sys.exit("Ni calibration (--calibrate) ni OCR (pip install pytesseract) : "
                 "impossible de trouver les boutons.")

    loc = Locator(width, height, args.language, positions, labels, args.tesseract)

    # Vérifie dès le départ que chaque étape obligatoire peut être trouvée
    required = ["play", "private_match", "join_private"]
    missing = [s for s in required if s not in positions]
    print("Étapes calibrées : " + (", ".join(positions) or "aucune"))
    if missing and not loc.ocr_ok:
        sys.exit(
            "Impossible de continuer : ces étapes ne sont pas dans "
            f"{args.positions} : {', '.join(missing)}\n"
            "et Tesseract (lecture de l'écran) n'est pas installé ou introuvable "
            f"({args.tesseract}).\n"
            "Solution : refais la calibration sans sauter ces étapes "
            "(--calibrate), ou installe Tesseract-OCR.")
    if missing:
        print(f"Étapes non calibrées, lecture de l'écran utilisée : {', '.join(missing)}")

    if args.calibrate_back_to_menu:
        calibrate_back_to_menu(args.positions, loc, width, height, args.countdown, args.delay,
                               args.host, args.port)
        return

    print("Mets Rocket League au premier plan, sur le menu principal. Début dans 5 s...")
    time.sleep(5)

    try:
        join_private_match(loc, args.name, args.password, args.delay)
    except RuntimeError as e:
        back_to_main_menu(loc, args.delay, args.host, args.port)
        sys.exit(f"Échec : {e}")

    sock = wait_for_match(args.host, args.port, args.join_timeout)
    if not sock:
        back_to_main_menu(loc, args.delay, args.host, args.port)
        sys.exit("Le match n'a pas été rejoint (nom/mot de passe faux, partie pleine, "
                 "ou Stats API désactivée).")
    print("Dans le match !")

    if args.spectate:
        time.sleep(3)
        if not loc.click_step("spectate", timeout=10, required=False):
            print("Bouton spectateur introuvable, on reste joueur.")

    quit_event = start_command_listener()
    print("-> Pour quitter la partie à tout moment : tape 'quit' puis Entrée dans ce terminal.")

    outcome = follow_match(sock, args.output, quit_event, args.name)
    if outcome == "quit":
        for i in range(args.quit_delay, 0, -1):
            print(f"Sortie dans {i} s...")
            time.sleep(1)
        leave_match(loc, args.delay, wait=0)
    elif outcome == "ended" and args.leave:
        leave_match(loc, args.delay, wait=8)
    print("Terminé.")


if __name__ == "__main__":
    try:
        main()
    except pyautogui.FailSafeException:
        sys.exit("Arrêt d'urgence (souris dans le coin haut-gauche).")
    except KeyboardInterrupt:
        sys.exit("\nArrêt.")