#!/usr/bin/env python3
"""
rl_match_watcher.py - Suit un match Rocket League en direct via la Stats API officielle.

Prérequis :
  - Rocket League lancé sur CE PC, avec la Stats API activée (voir --setup-ini).
  - Ce PC doit être dans le match (joueur ou spectateur).

Exemples :
  # 1) Activer la Stats API une fois (puis redémarrer Rocket League)
  python rl_match_watcher.py --setup-ini "C:/Program Files/Epic Games/rocketleague/TAGame/Config/TAStatsAPI.ini"

  # 2) Suivre le match et enregistrer les résultats
  python rl_match_watcher.py --port 49123 --output resultats.jsonl
"""

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime

SECTION = "[TAGame.MatchStatsExporter_TA]"


# ---------------------------------------------------------------------------
# Configuration du fichier .ini
# ---------------------------------------------------------------------------
def setup_ini(path: str, rate: int, port: int, web_port: int) -> None:
    """Écrit (ou remplace) la section Stats API dans le fichier .ini."""
    if port == web_port:
        sys.exit("Erreur : --port et --web-port doivent être différents.")

    lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()

    # Retire l'ancienne section si elle existe
    out, skip = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            skip = stripped == SECTION
        if not skip:
            out.append(line)

    out += [
        "",
        SECTION,
        f"PacketSendRate={rate}",
        f"Port={port}",
        f"WebPort={web_port}",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).strip() + "\n")

    print(f"Fichier mis à jour : {path}")
    print("Redémarre Rocket League pour que les changements soient pris en compte.")


# ---------------------------------------------------------------------------
# Lecture du flux TCP (objets JSON collés les uns aux autres)
# ---------------------------------------------------------------------------
def iter_messages(sock: socket.socket):
    decoder = json.JSONDecoder()
    buf = ""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return  # connexion fermée (jeu fermé)
        buf += chunk.decode("utf-8", errors="ignore")
        while True:
            buf = buf.lstrip()
            if not buf:
                break
            try:
                obj, end = decoder.raw_decode(buf)
            except json.JSONDecodeError:
                break  # message incomplet, on attend la suite
            buf = buf[end:]
            yield obj


def parse_data(msg: dict) -> dict:
    """Le champ Data peut être un objet ou une chaîne JSON selon les versions."""
    data = msg.get("Data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    return data or {}


# ---------------------------------------------------------------------------
# Affichage / sauvegarde
# ---------------------------------------------------------------------------
def score_line(state: dict) -> str:
    game = state.get("Game", {})
    teams = {t.get("TeamNum"): t for t in game.get("Teams", [])}
    blue, orange = teams.get(0, {}), teams.get(1, {})
    secs = int(game.get("TimeSeconds", 0))
    clock = f"{'+' if game.get('bOvertime') else ''}{secs // 60}:{secs % 60:02d}"
    return (f"{blue.get('Name', 'Bleu')} {blue.get('Score', 0)} - "
            f"{orange.get('Score', 0)} {orange.get('Name', 'Orange')}  [{clock}]")


def build_result(state: dict, winner_team_num) -> dict:
    game = state.get("Game", {})
    return {
        "date": datetime.now().isoformat(timespec="seconds"),
        "match_guid": state.get("MatchGuid"),
        "arena": game.get("Arena"),
        "overtime": game.get("bOvertime"),
        "winner_team_num": winner_team_num,
        "teams": [
            {"team_num": t.get("TeamNum"), "name": t.get("Name"), "score": t.get("Score")}
            for t in game.get("Teams", [])
        ],
        "players": [
            {k: p.get(k) for k in ("Name", "TeamNum", "Score", "Goals",
                                   "Assists", "Saves", "Shots", "Demos")}
            for p in state.get("Players", [])
        ],
    }


def save_result(path: str, result: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------
def watch(host: str, port: int, output: str, retry: float, verbose: bool) -> None:
    last_state = None
    last_printed = ""

    while True:
        try:
            print(f"Connexion à {host}:{port} ...")
            with socket.create_connection((host, port), timeout=10) as sock:
                sock.settimeout(None)
                print("Connecté. En attente des données du match...")
                for msg in iter_messages(sock):
                    event = msg.get("Event")
                    data = parse_data(msg)

                    if event == "UpdateState":
                        last_state = data
                        line = score_line(data)
                        if line != last_printed:
                            print(line)
                            last_printed = line

                    elif event == "GoalScored":
                        scorer = (data.get("Scorer") or {}).get("Name", "?")
                        print(f"  >>> BUT de {scorer} !")

                    elif event == "MatchEnded":
                        winner = data.get("WinnerTeamNum")
                        print(f"=== FIN DU MATCH - équipe gagnante : "
                              f"{'Bleu' if winner == 0 else 'Orange' if winner == 1 else winner} ===")
                        if last_state:
                            print("Score final : " + score_line(last_state))
                            if output:
                                save_result(output, build_result(last_state, winner))
                                print(f"Résultat enregistré dans {output}")
                        last_state = None

                    elif verbose and event:
                        print(f"[{event}]")

            print("Connexion fermée par le jeu.")
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            print(f"Impossible de se connecter ({e}). Rocket League est-il lancé "
                  f"avec la Stats API activée ?")
        except KeyboardInterrupt:
            print("\nArrêt.")
            return

        try:
            time.sleep(retry)
        except KeyboardInterrupt:
            print("\nArrêt.")
            return


def main():
    p = argparse.ArgumentParser(
        description="Suit un match Rocket League en direct via la Stats API officielle.")
    p.add_argument("--host", default="127.0.0.1",
                   help="Adresse du PC qui fait tourner le jeu (défaut : 127.0.0.1)")
    p.add_argument("--port", type=int, default=49123,
                   help="Port TCP de la Stats API (défaut : 49123)")
    p.add_argument("--output", default="resultats.jsonl",
                   help="Fichier où enregistrer les scores finaux (défaut : resultats.jsonl, "
                        "mettre '' pour désactiver)")
    p.add_argument("--retry", type=float, default=5.0,
                   help="Secondes entre deux tentatives de connexion (défaut : 5)")
    p.add_argument("--verbose", action="store_true",
                   help="Affiche tous les événements reçus")

    g = p.add_argument_group("Activation de la Stats API (à faire une fois)")
    g.add_argument("--setup-ini", metavar="CHEMIN_INI",
                   help="Chemin vers TAGame/Config/TAStatsAPI.ini (ou DefaultStatsAPI.ini) "
                        "à configurer, puis quitte")
    g.add_argument("--rate", type=int, default=30,
                   help="Mises à jour par seconde, 1 à 120 (défaut : 30)")
    g.add_argument("--web-port", type=int, default=49124,
                   help="Port WebSocket, doit être différent de --port (défaut : 49124)")

    args = p.parse_args()

    if args.setup_ini:
        if not 1 <= args.rate <= 120:
            sys.exit("Erreur : --rate doit être entre 1 et 120.")
        setup_ini(args.setup_ini, args.rate, args.port, args.web_port)
        return

    watch(args.host, args.port, args.output, args.retry, args.verbose)


if __name__ == "__main__":
    main()