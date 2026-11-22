"""/start_tournament_init delai_confirmation : validation des participations et liste d'attente."""

import asyncio
import random
from pathlib import Path

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.simulation import Simulation
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, FausseMessagerie, attendre_que, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"
# 0,02 minute = 1,2 s : assez long pour cliquer, assez court pour le test.
DELAI = 0.02


def inscription(nb_inscrites: int = 4, nb_attente: int = 2) -> dict:
    """Équipes 1..nb_inscrites inscrites, les suivantes en liste d'attente (dans l'ordre)."""
    tournoi = tournoi_inscription(nb_inscrites + nb_attente, TID, equipes_max=nb_inscrites)
    for equipe in tournoi["equipes"][nb_inscrites:]:
        equipe["statut"] = "liste_attente"
    return tournoi


def creer(tmp_path: Path, tournoi: dict | None = None, *, simulation: Simulation | None = None):
    ecrire_inscription(tmp_path / "inscriptions", tournoi or inscription())
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(declaration_auto=True)
    g = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0, delai_declaration=0,
                             generer_pp=faux_pp, rng=random.Random(1), simulation=simulation)
    messagerie.gestionnaire = g
    return g, stockage, messagerie


def joueurs(equipe_id: int) -> list[str]:
    return [str(1000 + equipe_id * 10), str(1000 + equipe_id * 10 + 1)]


def test_start_tournament_rl_refuse_sans_init(tmp_path):
    async def scenario():
        g, stockage, _ = creer(tmp_path)
        with pytest.raises(L.ErreurTournoi, match="start_tournament_init"):
            await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        return stockage.charger_etat(TID)

    assert asyncio.run(scenario()) is None


def test_init_envoie_le_bouton_aux_inscrits_et_previent_la_liste_d_attente(tmp_path):
    async def scenario():
        g, _, messagerie = creer(tmp_path)
        init = await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=30)
        await g.fermer()
        return init, messagerie

    init, messagerie = asyncio.run(scenario())
    assert init["confirmation"]["delai_minutes"] == 30 and not init["confirmation"]["terminee"]
    assert [e["id"] for e in init["confirmation"]["attente"]] == [5, 6]
    # Chaque joueur des 4 équipes inscrites a le bouton de son équipe.
    assert sorted(messagerie.boutons_confirmation) == sorted((j, e) for e in range(1, 5) for j in joueurs(e))
    assert "30 minutes" in messagerie.mps_de(joueurs(1)[0])[0]
    # Liste d'attente : position, et le premier participera au tournoi si une équipe ne valide pas.
    premier, second = messagerie.mps_de(joueurs(5)[1])[0], messagerie.mps_de(joueurs(6)[0])[0]
    assert "**1er** sur la liste d'attente" in premier and "tu participeras au tournoi" in premier
    assert "**2e** sur la liste d'attente" in second and "tu participeras" not in second
    assert "30 minutes" in second


def test_start_tournament_rl_refuse_pendant_le_delai(tmp_path):
    async def scenario():
        g, _, _ = creer(tmp_path)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=30)
        with pytest.raises(L.ErreurTournoi, match="peuvent encore valider"):
            await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.fermer()

    asyncio.run(scenario())


def test_un_joueur_valide_pour_toute_l_equipe(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=30)
        premiere = await g.valider_participation(TID, 1, par=joueurs(1)[0])
        deuxieme = await g.valider_participation(TID, 1, par=joueurs(1)[1])
        with pytest.raises(L.ErreurTournoi, match="Seuls les joueurs"):
            await g.valider_participation(TID, 2, par=joueurs(1)[0])
        await g.fermer()
        return premiere, deuxieme, stockage.charger_init(TID), messagerie

    premiere, deuxieme, init, messagerie = asyncio.run(scenario())
    assert "validée !" in premiere and "déjà validée" in deuxieme
    assert init["confirmation"]["validees"]["1"]["par"] == joueurs(1)[0]
    assert any("a validé la participation" in t for t in messagerie.mps_de(joueurs(1)[1]))


def test_fin_du_delai_la_liste_d_attente_prend_les_places(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=DELAI)
        for equipe_id in (1, 3):  # les équipes 2 et 4 ne valident pas
            await g.valider_participation(TID, equipe_id, par=joueurs(equipe_id)[0])
        await asyncio.wait_for(g.attendre_confirmation(TID), 5)
        with pytest.raises(L.ErreurTournoi, match="Le délai est passé"):
            await g.valider_participation(TID, 2, par=joueurs(2)[0])
        etat = await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_init(TID), etat, messagerie

    init, etat, messagerie = asyncio.run(scenario())
    assert init["confirmation"]["perdues"] == [2, 4] and init["confirmation"]["promues"] == [5, 6]
    assert sorted(etat["equipes"]) == ["1", "3", "5", "6"]
    assert any("perd sa place" in t for t in messagerie.mps_de(joueurs(2)[0]))
    assert any("participe au tournoi" in t for t in messagerie.mps_de(joueurs(6)[1]))
    # Accès au salon : retiré aux équipes 2 et 4, donné aux équipes 5 et 6.
    assert sorted(r for _, r in messagerie.acces_salon if r) == sorted(joueurs(2) + joueurs(4))
    assert sorted(a for a, _ in messagerie.acces_salon if a) == sorted(joueurs(5) + joueurs(6))
    bilan = [t for _, t, _ in messagerie.messages_salons if "Fin des validations" in t]
    assert bilan and "Equipe2" in bilan[0] and "Equipe5" in bilan[0]
    assert any("Fin des validations" in j for j in messagerie.journaux)


def test_liste_d_attente_qui_reste_est_prevenue(tmp_path):
    async def scenario():
        g, _, messagerie = creer(tmp_path, inscription(nb_inscrites=2, nb_attente=3))
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=DELAI)
        await g.valider_participation(TID, 1, par=joueurs(1)[0])  # l'équipe 2 ne valide pas
        await asyncio.wait_for(g.attendre_confirmation(TID), 5)
        return messagerie

    messagerie = asyncio.run(scenario())
    assert any("participe au tournoi" in t for t in messagerie.mps_de(joueurs(3)[0]))
    assert any("reste **1er** sur la liste d'attente" in t for t in messagerie.mps_de(joueurs(4)[0]))
    assert any("reste **2e** sur la liste d'attente" in t for t in messagerie.mps_de(joueurs(5)[0]))


def test_tout_le_monde_valide_le_delai_se_termine_tout_de_suite(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=30)
        for equipe_id in range(1, 5):
            await g.valider_participation(TID, equipe_id, par=joueurs(equipe_id)[1])
        await asyncio.wait_for(g.attendre_confirmation(TID), 2)
        return stockage.charger_init(TID), messagerie

    init, messagerie = asyncio.run(scenario())
    assert init["confirmation"]["terminee"] and init["confirmation"]["perdues"] == []
    assert messagerie.acces_salon == []
    assert any("reste **1er**" in t for t in messagerie.mps_de(joueurs(5)[0]))


def test_nombre_impair_apres_le_delai_refuse_le_lancement(tmp_path):
    async def scenario():
        g, _, _ = creer(tmp_path, inscription(nb_inscrites=4, nb_attente=0))
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=DELAI)
        for equipe_id in (1, 2, 3):
            await g.valider_participation(TID, equipe_id, par=joueurs(equipe_id)[0])
        await asyncio.wait_for(g.attendre_confirmation(TID), 5)
        with pytest.raises(L.ErreurTournoi, match="pair"):
            await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)

    asyncio.run(scenario())


def test_le_delai_reprend_apres_un_redemarrage(tmp_path):
    async def avant():
        g, _, _ = creer(tmp_path)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=DELAI)
        await g.fermer()  # le bot s'arrête pendant le délai

    async def apres():
        stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
        messagerie = FausseMessagerie()
        g = GestionnaireTournois(stockage, messagerie, generer_pp=faux_pp)
        repris = g.reprendre()
        await asyncio.wait_for(g.attendre_confirmation(TID), 5)
        return repris, stockage.charger_init(TID)

    asyncio.run(avant())
    repris, init = asyncio.run(apres())
    assert any(TID in r for r in repris)
    assert init["confirmation"]["terminee"] and init["confirmation"]["perdues"] == [1, 2, 3, 4]


def test_simulation_valide_les_participations(tmp_path):
    async def scenario():
        simulation = Simulation(delai_clic=0, delai_declaration=0, rng=random.Random(2))
        g, stockage, _ = creer(tmp_path, simulation=simulation)
        await g.initialiser(TID, serveur_id=SERVEUR, par=ADMIN, delai_confirmation=30)
        await attendre_que(lambda: stockage.charger_init(TID)["confirmation"]["terminee"])
        await g.fermer()
        return stockage.charger_init(TID)

    init = asyncio.run(scenario())
    assert sorted(init["confirmation"]["validees"]) == ["1", "2", "3", "4"]


def test_terminer_confirmation_dans_l_ordre_de_la_liste_d_attente():
    tournoi = inscription(nb_inscrites=4, nb_attente=3)
    init = L.etat_init(tournoi, L.equipes_participantes(tournoi), par=ADMIN, maintenant="2026-11-14T15:00:00",
                       attente=L.equipes_en_attente(tournoi), delai_confirmation=10)
    L.valider_participation(init, 2, joueurs(2)[0], maintenant="2026-11-14T15:01:00")
    L.valider_participation(init, 4, joueurs(4)[1], maintenant="2026-11-14T15:02:00")
    perdues, promues = L.terminer_confirmation(init)
    assert [e["id"] for e in perdues] == [1, 3] and [e["id"] for e in promues] == [5, 6]
    assert sorted(init["equipes"]) == ["2", "4", "5", "6"]
    assert [e["id"] for e in init["confirmation"]["attente"]] == [7]
    assert L.terminer_confirmation(init) == ([], [])  # une seule fois
    assert [e["id"] for e in L.equipes_du_lancement(tournoi, init)] == [2, 4, 5, 6]


def test_liste_d_attente_incomplete_ignoree():
    tournoi = inscription(nb_inscrites=2, nb_attente=2)
    tournoi["equipes"][2]["joueurs"][1]["statut"] = "en_attente"  # équipe 3 : un joueur n'a pas confirmé
    assert [e["id"] for e in L.equipes_en_attente(tournoi)] == [4]
