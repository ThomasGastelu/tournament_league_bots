"""Copie dans LOG_CHANNEL les problèmes du bot (avertissements et erreurs de la console).

Les lignes sont regroupées (un message toutes les quelques secondes au plus) pour
éviter le spam. Un message qui ne doit pas partir dans Discord (par exemple
l'échec d'envoi dans LOG_CHANNEL lui-même) se logge avec `extra=HORS_JOURNAL`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import traceback
from collections.abc import Awaitable, Callable

HORS_JOURNAL = {"journal": False}
LIMITE_MESSAGE = 1900  # Discord : 2000 caractères par message


class _Format(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(levelname)s %(name)s : %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        # Copie : ne pas modifier l'enregistrement (la console garde la trace complète).
        copie = logging.makeLogRecord(record.__dict__)
        exception = copie.exc_info
        copie.exc_info, copie.exc_text, copie.stack_info = None, None, None
        texte = super().format(copie).replace("bot_tournament_manager.", "")
        if exception and exception[0] is not None:
            texte += " — " + traceback.format_exception_only(exception[0], exception[1])[-1].strip()
        return texte


class JournalDiscord(logging.Handler):
    """Handler logging → LOG_CHANNEL. `envoyer` poste un texte (coroutine)."""

    def __init__(self, envoyer: Callable[[str], Awaitable[None]], *, delai: float = 3.0,
                 niveau: int = logging.WARNING) -> None:
        super().__init__(niveau)
        self.setFormatter(_Format())
        self.envoyer = envoyer
        self.delai = delai
        self._lignes: list[str] = []
        self._verrou = threading.Lock()
        self._boucle: asyncio.AbstractEventLoop | None = None
        self._planifie = False

    def demarrer(self, boucle: asyncio.AbstractEventLoop) -> None:
        """À appeler quand la boucle asyncio du bot tourne : envoie aussi ce qui attendait."""
        self._boucle = boucle
        with self._verrou:
            a_envoyer = bool(self._lignes) and not self._planifie
            self._planifie = self._planifie or a_envoyer
        if a_envoyer:
            boucle.call_soon_threadsafe(self._planifier)

    def emit(self, record: logging.LogRecord) -> None:
        if not getattr(record, "journal", True):
            return
        try:
            ligne = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with self._verrou:
            self._lignes.append(ligne)
            a_planifier = self._boucle is not None and not self._planifie
            self._planifie = self._planifie or a_planifier
        if a_planifier:
            try:
                self._boucle.call_soon_threadsafe(self._planifier)  # type: ignore[union-attr]
            except RuntimeError:  # boucle fermée (arrêt du bot)
                pass

    def _planifier(self) -> None:
        asyncio.ensure_future(self._vider())

    async def _vider(self) -> None:
        await asyncio.sleep(self.delai)
        with self._verrou:
            lignes, self._lignes = self._lignes, []
            self._planifie = False
        for bloc in decouper(lignes):
            try:
                await self.envoyer(bloc)
            except Exception as erreur:  # ne jamais faire planter le bot pour un log
                logging.getLogger(__name__).warning("LOG_CHANNEL : envoi impossible (%s)", erreur, extra=HORS_JOURNAL)


def decouper(lignes: list[str]) -> list[str]:
    """Regroupe les lignes en messages Discord (bloc de code, 2000 caractères max)."""
    blocs, courant = [], ""
    for ligne in lignes:
        ligne = ligne.replace("```", "'''")[:LIMITE_MESSAGE - 20]
        if courant and len(courant) + len(ligne) + 1 > LIMITE_MESSAGE - 20:
            blocs.append(courant)
            courant = ""
        courant += ligne + "\n"
    if courant:
        blocs.append(courant)
    return [f"⚠️ Problème(s) du bot :\n```\n{bloc}```" for bloc in blocs]
