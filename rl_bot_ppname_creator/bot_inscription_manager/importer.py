"""Import unique des anciens fichiers JSON dans la base : python -m bot_inscription_manager.importer

Envoie chaque fichier de data/tournois/ à POST /api/bot/import (API_URL et BOT_API_KEY du .env).
Sans danger à relancer : un tournoi déjà en base répond « déjà importé » et n'est pas modifié.
Les fichiers ne sont ni modifiés ni effacés.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .main import RACINE, choisir_stockage
from .stockage_api import ErreurAPI, StockageAPI


async def importer(api: StockageAPI, dossier: Path) -> dict[str, int]:
    """Importe tous les fichiers du dossier. Retourne le compte par résultat (importe, deja, erreur)."""
    bilan = {"importe": 0, "deja": 0, "erreur": 0}
    for chemin in sorted(dossier.glob("*.json")):
        try:
            tournoi = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as erreur:
            print(f"❌ {chemin.name} : fichier illisible ({erreur})")
            bilan["erreur"] += 1
            continue
        try:
            await api._appel("POST", "/import", tournoi)
            print(f"✅ {chemin.name} : importé ({tournoi.get('titre')})")
            bilan["importe"] += 1
        except ErreurAPI as erreur:
            if erreur.statut == 409:
                print(f"ℹ️ {chemin.name} : déjà en base")
                bilan["deja"] += 1
            else:
                print(f"❌ {chemin.name} : {erreur}")
                bilan["erreur"] += 1
    await api.fermer()
    return bilan


def main() -> None:
    load_dotenv(RACINE / ".env")
    dossier = RACINE / "data" / "tournois"
    try:
        api = choisir_stockage(os.getenv("API_URL"), os.getenv("BOT_API_KEY"), dossier)
    except ValueError as erreur:
        sys.exit(f"❌ {erreur}")
    if not isinstance(api, StockageAPI):
        sys.exit("❌ API_URL est vide dans le .env : il faut l'adresse de l'API pour importer.")
    # Pas de copie locale pendant l'import : les fichiers d'origine restent tels quels.
    api.miroir = None
    bilan = asyncio.run(importer(api, dossier))
    print(f"\n{bilan['importe']} importé(s), {bilan['deja']} déjà en base, {bilan['erreur']} erreur(s).")
    if bilan["erreur"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
