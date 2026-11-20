"""LOG_CHANNEL : copie des problèmes du bot, et identifiants des boutons des MP."""

import asyncio
import logging
import re

from bot_tournament_manager.declaration import MODELE_ID, MODELE_ID_PP, custom_id, custom_id_pp, lire_custom_id
from bot_tournament_manager.journal import HORS_JOURNAL, JournalDiscord, decouper


def test_journal_regroupe_les_problemes_dans_un_message():
    envois = []

    async def envoyer(texte):
        envois.append(texte)

    async def scenario():
        journal = JournalDiscord(envoyer, delai=0.05)
        logger = logging.getLogger("bot_tournament_manager.essai_journal")
        logger.addHandler(journal)
        try:
            logger.warning("avant le démarrage")  # gardé jusqu'à ce que la boucle tourne
            journal.demarrer(asyncio.get_running_loop())
            logger.info("pas un problème")
            logger.warning("salon introuvable")
            logger.warning("échec d'envoi dans LOG_CHANNEL", extra=HORS_JOURNAL)
            try:
                raise ValueError("boum")
            except ValueError:
                logger.exception("erreur dans le tournoi")
            await asyncio.sleep(0.2)
        finally:
            logger.removeHandler(journal)

    asyncio.run(scenario())
    assert len(envois) == 1
    texte = envois[0]
    assert "avant le démarrage" in texte and "salon introuvable" in texte
    assert "erreur dans le tournoi — ValueError: boum" in texte
    assert "pas un problème" not in texte and "LOG_CHANNEL" not in texte
    assert "Traceback" not in texte  # la trace complète reste dans la console


def test_decouper_respecte_la_limite_discord():
    blocs = decouper([f"ligne {i} " + "x" * 300 for i in range(20)])
    assert len(blocs) > 1 and all(len(b) <= 2000 for b in blocs)
    assert decouper(["```injection```"])[0].count("```") == 2


def test_identifiant_du_bouton_de_declaration():
    identifiant = custom_id("1571169059024928818", 2, 3, 7)
    assert len(identifiant) <= 100  # limite Discord
    assert lire_custom_id(identifiant) == ("1571169059024928818", 2, 3, 7)
    assert lire_custom_id("autre:chose") is None


def test_identifiant_du_bouton_partie_creee():
    identifiant = custom_id_pp("1571169059024928818", 2, 3)
    trouve = re.fullmatch(MODELE_ID_PP, identifiant)
    assert len(identifiant) <= 100 and trouve and (trouve["ronde"], trouve["zone"]) == ("2", "3")
    assert re.fullmatch(MODELE_ID, identifiant) is None  # pas confondu avec le bouton de déclaration
    assert re.fullmatch(MODELE_ID_PP, "rlpp:fait") is None  # le bouton grisé ne déclenche rien
