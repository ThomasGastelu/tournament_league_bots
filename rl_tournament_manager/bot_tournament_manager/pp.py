"""Génération des parties privées avec rl_bot_ppname_creator/generer_pp_names.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


class ErreurPP(Exception):
    """Le script generer_pp_names.py n'a pas pu générer les parties privées."""


def generer_parties(script: Path, nombre: int, sortie: Path) -> list[dict]:
    """Lance `generer_pp_names.py -n <nombre> -o <sortie>` et renvoie les parties, triées par match.

    Chaque partie : {"match": 1, "nom": "tomato_xxxxxx", "mot_de_passe": "tomato_xxxxxx"}.
    `-o` évite d'écraser le pp.json partagé du dossier rl_bot_ppname_creator.
    Bloquant : à appeler avec asyncio.to_thread().
    """
    sortie = Path(sortie).resolve()
    sortie.parent.mkdir(parents=True, exist_ok=True)
    try:
        processus = subprocess.run(
            [sys.executable, str(script), "-n", str(nombre), "-o", str(sortie)],
            cwd=Path(script).parent, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as erreur:
        raise ErreurPP(f"Impossible de lancer {script} : {erreur}") from erreur
    if processus.returncode != 0:
        raise ErreurPP(f"{Path(script).name} a échoué : {processus.stderr.strip() or processus.stdout.strip()}")

    try:
        donnees = json.loads(sortie.read_text(encoding="utf-8"))
        parties = sorted(donnees["parties"], key=lambda p: p["match"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as erreur:
        raise ErreurPP(f"Fichier {sortie} illisible : {erreur}") from erreur
    if len(parties) != nombre:
        raise ErreurPP(f"{len(parties)} partie(s) générée(s) au lieu de {nombre}.")
    return parties
