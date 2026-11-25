"""Noms et mots de passe des parties privées : tomato_<round><zone>.

Round 1 : tomato_11, tomato_12, tomato_13… ; round 2 : tomato_21, tomato_22… ; round 12 : tomato_121…
Le mot de passe est le même que le nom.
À partir de 10 zones, la zone s'écrit sur 2 chiffres pour tout le tournoi (round 1 : tomato_101 … tomato_112,
round 11 : tomato_1101…), sinon le round 1 zone 11 et le round 11 zone 1 donneraient tous deux tomato_111.
Les parties de chaque round sont aussi écrites dans data/pp/<id>_ronde_<n>.json.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PREFIXE = "tomato_"


def nom_partie(ronde: int, zone: int, nb_zones: int) -> str:
    """tomato_<round><zone>, la zone sur autant de chiffres que `nb_zones` (1 → tomato_11, 10 zones → tomato_101)."""
    largeur = len(str(nb_zones))
    return f"{PREFIXE}{ronde}{zone:0{largeur}d}"


def generer_parties(nombre: int, sortie: Path, ronde: int = 1) -> list[dict]:
    """Parties privées des `nombre` zones du round `ronde`, triées par match (match 1 = zone 1), écrites dans `sortie`.

    Chaque partie : {"match": 1, "nom": "tomato_11", "mot_de_passe": "tomato_11"}.
    """
    parties = []
    for i in range(1, nombre + 1):
        nom = nom_partie(ronde, i, nombre)
        parties.append({"match": i, "nom": nom, "mot_de_passe": nom})
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({"genere_le": datetime.now().isoformat(timespec="seconds"), "parties": parties},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
    return parties
