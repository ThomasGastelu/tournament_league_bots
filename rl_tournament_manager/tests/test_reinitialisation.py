"""/reset_tournament_rl : remise à zéro d'un tournoi (fichiers, tâches, salons de discussion)."""

import asyncio
import json

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, attendre_que
from .test_deroulement import TID, creer

AUTRE = "15711690590249288"  # ID qui commence comme TID : ses fichiers ne doivent pas être effacés


def ecrire(chemin, contenu: dict) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(contenu), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Fichiers (stockage)
# --------------------------------------------------------------------------- #

def test_fichiers_du_tournoi_et_rien_d_autre(tmp_path):
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    donnees = tmp_path / "data"
    a_effacer = [
        donnees / "tournois" / f"{TID}.json",
        donnees / "tournois" / f"{TID}.json.tmp",
        donnees / "pp" / f"{TID}_ronde_1.json",
        donnees / "pp" / f"{TID}_ronde_12.json",
        donnees / "archives" / f"{TID}_2026-11-14T15-00-00.json",
    ]
    a_garder = [
        tmp_path / "inscriptions" / f"{TID}.json",  # fichier du bot d'inscription
        donnees / "tournois" / f"{AUTRE}.json",
        donnees / "pp" / f"{AUTRE}_ronde_1.json",
        donnees / "archives" / f"{AUTRE}_2026-11-14T15-00-00.json",
    ]
    for chemin in a_effacer + a_garder:
        ecrire(chemin, {"tournoi_id": TID})

    assert stockage.fichiers_du_tournoi(TID) == sorted(a_effacer)
    assert sorted(stockage.supprimer_tournoi(TID)) == sorted(a_effacer)
    assert not any(c.exists() for c in a_effacer)
    assert all(c.exists() for c in a_garder)
    assert stockage.supprimer_tournoi(TID) == []  # deuxième fois : plus rien


def test_id_invalide_refuse(tmp_path):
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    with pytest.raises(ValueError):
        stockage.fichiers_du_tournoi("../inscriptions")
    with pytest.raises(ValueError):
        stockage.supprimer_tournoi("*")


def test_salons_discussion_sans_doublon():
    etats = [{"salon_discussion_id": "3"}, {}, {"salon_discussion_id": "1"}, {"salon_discussion_id": "3"}]
    assert L.salons_discussion(etats) == ["3", "1"]
    assert L.salons_discussion([]) == []


def test_texte_de_confirmation():
    etat = {"titre": "Coupe", "statut": L.EN_COURS}
    texte = M.confirmation_reinitialisation(etat, 4, 1, garder_salon=False)
    assert "en cours" in texte and "4 fichiers" in texte and "je supprime le salon de discussion" in texte
    texte = M.confirmation_reinitialisation({"titre": "Coupe", "statut": L.TERMINE}, 1, 2, garder_salon=True)
    assert "en cours" not in texte and "1 fichier " in texte and "les 2 salons de discussion du tournoi restent" in texte


# --------------------------------------------------------------------------- #
# Gestionnaire
# --------------------------------------------------------------------------- #

def test_remise_a_zero_d_un_tournoi_en_cours(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 4, delai=60)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.demarrer(TID, 5, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"]))
        assert stockage.fichiers_du_tournoi(TID)  # état + parties privées du round 1
        bilan = await g.reinitialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        assert not g.est_actif(TID)
        return g, bilan, stockage, messagerie

    g, bilan, stockage, messagerie = asyncio.run(scenario())
    assert bilan["etait_en_cours"] and bilan["nb_fichiers"] >= 2
    assert stockage.fichiers_du_tournoi(TID) == []
    assert stockage.charger_etat(TID) is None
    assert stockage.charger_inscription(TID) is not None  # inscriptions intactes
    assert messagerie.salons_supprimes == ["4242"] and bilan["salons_supprimes"] == ["4242"]
    assert sum("remis à zéro" in t for _, t in messagerie.mps) == 8  # 4 équipes × 2 joueurs
    assert any("remis à zéro" in (t or "") for t, _ in messagerie.annonces)
    assert any("remis à zéro" in t for t in messagerie.journaux)
    assert not any(cle[0] == TID for cle in g._pp_creees)


def test_remise_a_zero_puis_relance_de_zero(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)  # archive le premier lancement
        await g.attendre(TID)
        nb_mps = len(messagerie.mps)
        bilan = await g.reinitialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        assert len(messagerie.mps) == nb_mps  # tournoi terminé : personne n'est dérangé
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        return bilan, stockage

    bilan, stockage = asyncio.run(scenario())
    assert not bilan["etait_en_cours"]
    assert bilan["salons_supprimes"] == ["4242"]  # même ID pour les deux lancements : supprimé une fois
    assert list((tmp_path / "data" / "archives").iterdir()) == []  # relance propre : pas d'archive
    etat = stockage.charger_etat(TID)
    assert etat["statut"] == L.TERMINE and len(etat["rondes"]) == 1


def test_garder_le_salon(tmp_path):
    async def scenario():
        g, _, messagerie = creer(tmp_path, 2)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        return await g.reinitialiser(TID, serveur_id=SERVEUR, par=ADMIN, garder_salon=True), messagerie

    bilan, messagerie = asyncio.run(scenario())
    assert messagerie.salons_supprimes == []
    assert bilan["salons_gardes"] == ["4242"]
    assert "<#4242>" in M.reponse_reinitialisation(bilan)


def test_salon_impossible_a_supprimer_n_empeche_pas_la_remise_a_zero(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2)
        messagerie.suppression_salon_possible = False
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        return await g.reinitialiser(TID, serveur_id=SERVEUR, par=ADMIN), stockage

    bilan, stockage = asyncio.run(scenario())
    assert bilan["salons_en_echec"] == ["4242"]
    assert stockage.fichiers_du_tournoi(TID) == []
    assert "Gérer les salons" in M.reponse_reinitialisation(bilan)


def test_refus_si_rien_a_effacer_ou_autre_serveur(tmp_path):
    async def scenario():
        g, _, _ = creer(tmp_path, 2)
        with pytest.raises(L.ErreurTournoi, match="Rien à remettre à zéro"):
            await g.reinitialiser(TID, serveur_id=SERVEUR, par=ADMIN)  # jamais lancé
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        with pytest.raises(L.ErreurTournoi, match="Rien à remettre à zéro"):
            await g.reinitialiser(TID, serveur_id="123", par=ADMIN)
        with pytest.raises(L.ErreurTournoi):
            await g.reinitialiser("../x", serveur_id=SERVEUR, par=ADMIN)

    asyncio.run(scenario())
    assert (tmp_path / "data" / "tournois" / f"{TID}.json").exists()


def test_seules_les_archives_restent(tmp_path):
    """Un ancien lancement archivé, sans état actuel : la remise à zéro l'efface aussi."""
    async def scenario():
        g, stockage, _ = creer(tmp_path, 2)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        stockage.archiver_etat(TID, "ancien")
        etat, salons, fichiers = g.a_reinitialiser(TID, SERVEUR)
        assert etat["statut"] == L.TERMINE and salons == ["4242"] and fichiers
        await g.reinitialiser(TID, serveur_id=SERVEUR, par=ADMIN)
        return stockage

    stockage = asyncio.run(scenario())
    assert stockage.fichiers_du_tournoi(TID) == []
