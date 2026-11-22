"""Noms et mots de passe des parties privées : tomato_A, tomato_B, tomato_C… (une lettre par zone).

Zone 1 = tomato_A, zone 2 = tomato_B, etc. ; le mot de passe est le même que le nom.
Au-delà de 26 zones : tomato_AA, tomato_AB… Chaque round réutilise les mêmes noms.
Les parties de chaque round sont aussi écrites dans data/pp/<id>_ronde_<n>.json.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PREFIXE = "tomato_"


def lettres(numero: int) -> str:
    """1 → A, 2 → B… 26 → Z, 27 → AA, 28 → AB (comme les colonnes d'un tableur)."""
    texte = ""
    while numero > 0:
        numero, reste = divmod(numero - 1, 26)
        texte = chr(ord("A") + reste) + texte
    return texte


def generer_parties(nombre: int, sortie: Path) -> list[dict]:
    """Parties privées des `nombre` zones, triées par match (match 1 = zone 1), écrites dans `sortie`.

    Chaque partie : {"match": 1, "nom": "tomato_A", "mot_de_passe": "tomato_A"}.
    """
    parties = [{"match": i, "nom": f"{PREFIXE}{lettres(i)}", "mot_de_passe": f"{PREFIXE}{lettres(i)}"}
               for i in range(1, nombre + 1)]
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({"genere_le": datetime.now().isoformat(timespec="seconds"), "parties": parties},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    return parties
