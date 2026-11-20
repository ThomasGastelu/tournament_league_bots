"""Boucle d'envoi des MP, un membre après l'autre."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import discord

from . import logique as L

log = logging.getLogger(__name__)

PROGRESSION_TOUS_LES = 10  # met à jour la progression tous les 10 MP


async def envoyer_a_tous(
    membres: list,
    embed: discord.Embed,
    *,
    pause: float | None = None,
    progression: Callable[[L.Rapport], Awaitable[None]] | None = None,
) -> L.Rapport:
    """Envoie l'embed en MP à chaque membre. Une erreur sur un membre n'arrête jamais l'envoi."""
    pause = L.PAUSE_ENTRE_MP if pause is None else pause
    rapport = L.Rapport(total=len(membres))
    for numero, membre in enumerate(membres, start=1):
        try:
            await membre.send(embed=embed)
            rapport.recus += 1
        except discord.Forbidden:
            # MP fermés (paramètres de confidentialité du membre) ou bot bloqué.
            rapport.mp_fermes.append(membre.display_name)
        except discord.HTTPException as erreur:
            log.warning("MP impossible pour %s (%s) : %s", membre.display_name, membre.id, erreur)
            rapport.erreurs.append(membre.display_name)

        if progression and (numero % PROGRESSION_TOUS_LES == 0 or numero == rapport.total):
            try:
                await progression(rapport)
            except Exception:  # la progression est un bonus : elle ne doit jamais arrêter l'envoi
                log.exception("Erreur pendant la mise à jour de la progression")

        if numero < rapport.total:
            await asyncio.sleep(pause)
    return rapport
