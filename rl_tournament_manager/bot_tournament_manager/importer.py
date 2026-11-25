"""Import unique des anciens fichiers de tournament_manager dans la base, via l'API.

    .venv\\Scripts\\python -m bot_tournament_manager.importer

Envoie `data/tournois/<id>.json` (tournois lancés) et `data/salons/<id>.json` (inits de
/start_tournament_init) avec `API_URL` et `BOT_API_KEY` du `.env`. Ce qui existe déjà dans
l'API n'est jamais écrasé ; on peut relancer le script sans risque. Les archives
(`data/archives/`, anciens lancements) ne sont pas importées : l'API n'en garde aucune.
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

from .config import RACINE
from .stockage_api import StockageAPI, verifier_parametres


async def importer(api: StockageAPI) -> dict[str, int]:
    try:
        return await api.importer()
    finally:
        await api.fermer()


def main() -> None:
    load_dotenv(RACINE / ".env")
    try:
        parametres = verifier_parametres(os.getenv("API_URL"), os.getenv("BOT_API_KEY"))
    except ValueError as erreur:
        sys.exit(f"❌ {erreur}")
    if parametres is None:
        sys.exit("❌ API_URL est vide dans le .env : il faut l'adresse de l'API pour importer.")
    bilan = asyncio.run(importer(StockageAPI(*parametres, RACINE / "data")))
    print(f"\n{bilan['importe']} importé(s), {bilan['deja']} déjà en base, {bilan['erreur']} erreur(s).")
    if bilan["erreur"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
