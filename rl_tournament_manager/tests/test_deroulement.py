"""Tournois complets, joués avec une fausse messagerie Discord : les joueurs déclarent les scores."""

import asyncio
import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.stockage import Stockage

from .outils import (ADMIN, SERVEUR, FausseMessagerie, attendre_que, ecrire_inscription, faux_pp, score_auto,
                     tournoi_inscription)

TID = "1571169059024928818"


def creer(tmp_path: Path, nb_equipes: int, *, delai: float = 0, declaration_auto: bool = True, graine: int = 1,
          clic_auto: bool = True, rappel: float = 60, attente_max: float = 120):
    """Par défaut, chaque capitaine clique tout de suite sur « Partie privée créée », le bot demande le
    score sans attendre (`delai` = DELAI_DECLARATION) et les deux équipes déclarent le même score."""
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(nb_equipes, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(clic_auto=clic_auto, declaration_auto=declaration_auto)
    gestionnaire = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0, rappel_clic_pp=rappel, attente_clic_pp_max=attente_max,
                                        delai_declaration=delai, generer_pp=faux_pp, rng=random.Random(graine))
    messagerie.gestionnaire = gestionnaire
    return gestionnaire, stockage, messagerie


def test_tournoi_complet_8_equipes(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 8)
        await g.demarrer(TID, 3, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        return stockage.charger_etat(TID), messagerie

    etat, messagerie = asyncio.run(scenario())

    assert etat["statut"] == L.TERMINE
    assert len(etat["rondes"]) == 3
    assert all(r["statut"] == L.RONDE_TERMINEE for r in etat["rondes"])
    assert all(e["matchs_joues"] == 3 for e in etat["equipes"].values())
    # Par ronde : 3 victoires à +1 et 1 victoire en zone haute à +3.
    assert sum(e["points"] for e in etat["equipes"].values()) == 3 * (3 + 3)
    # Score déclaré par les équipes.
    assert all((m["score"]["equipe_a"], m["score"]["equipe_b"]) == score_auto(r["numero"], m["zone"])
               for r in etat["rondes"] for m in r["matchs"])

    # Les gagnants montent, les perdants descendent.
    for avant, apres in zip(etat["rondes"], etat["rondes"][1:]):
        zone_apres = {i: m["zone"] for m in apres["matchs"] for i in (m["equipe_a"], m["equipe_b"])}
        for m in avant["matchs"]:
            perdant = L.adversaire(m, m["vainqueur"])
            assert zone_apres[m["vainqueur"]] == min(m["zone"] + 1, 4)
            assert zone_apres[perdant] == max(m["zone"] - 1, 1)

    # MP : à chaque ronde, le capitaine A doit créer la partie, les autres la rejoindre.
    for ronde in etat["rondes"]:
        for m in ronde["matchs"]:
            capitaine = etat["equipes"][str(m["equipe_a"])]["capitaine_id"]
            assert any("Vous devez créer la partie privée" in t and m["pp"]["nom"] in t
                       for t in messagerie.mps_de(capitaine))
    joueur = etat["equipes"]["1"]["joueurs"][1]["id"]
    textes = messagerie.mps_de(joueur)
    # Premier MP : ni nom ni mot de passe, ils n'arrivent qu'une fois la partie créée.
    infos = [t for t in textes if "tu recevras son nom et son mot de passe" in t]
    assert len(infos) == 3
    assert all("le bot vous envoie un MP pour déclarer le score" in t for t in infos)
    assert not any("tomato_test" in t or "Mot de passe" in t for t in infos)
    assert all("Mot de passe" in t and "tomato_test" in t for t in textes if "a créé la partie privée" in t)
    assert sum("Déclare le score de ton match" in t for t in textes) == 3
    fins = [t for t in textes if "Match terminé" in t]
    assert len(fins) == 3 and all("déclaré par les deux équipes" in t for t in fins)
    assert sum("a créé la partie privée" in t for t in textes) == 3  # prévenu à chaque round
    assert all(m["pp_creee_par"] == etat["equipes"][str(m["equipe_a"])]["capitaine_id"]
               for r in etat["rondes"] for m in r["matchs"])
    assert "est terminé" in textes[-1]
    assert all(m["source_resultat"] == L.SOURCE_DECLARATIONS for r in etat["rondes"] for m in r["matchs"])
    assert all(m["chrono_declaration"] == m["pp_creee_le"] for r in etat["rondes"] for m in r["matchs"])

    # Récap de chaque round (scores et classement) dans le salon des résultats.
    assert len(messagerie.resultats_rondes) == 3
    for numero, embeds in enumerate(messagerie.resultats_rondes, start=1):
        texte = " ".join((e.title or "") + " " + (e.description or "") for e in embeds)
        assert f"🎯 Round {numero}**" in texte and "📊 Classement" in texte
        assert texte.count("*(déclaré par les équipes)*") == 4 and "Zone 4 ⭐" in texte

    # Salon : une annonce par ronde + le classement final. Aucune alerte.
    assert len(messagerie.annonces) == 4
    assert messagerie.alertes == []
    assert "classement final" in messagerie.annonces[-1][1][0].title

    # Les fichiers de parties privées de chaque ronde existent.
    assert sorted(p.name for p in (tmp_path / "data" / "pp").iterdir()) == [
        f"{TID}_ronde_{n}.json" for n in (1, 2, 3)]


def test_tous_les_matchs_se_jouent_en_meme_temps(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 8, delai=1.5)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        max_simultanes = 0
        while g.est_actif(TID):
            etat = stockage.charger_etat(TID)
            if etat and etat["rondes"]:
                en_cours = sum(m["statut"] == L.MATCH_EN_COURS for m in etat["rondes"][0]["matchs"])
                max_simultanes = max(max_simultanes, en_cours)
            await asyncio.sleep(0.01)
        return stockage.charger_etat(TID), max_simultanes, messagerie

    etat, max_simultanes, messagerie = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert max_simultanes == 4  # les 4 zones en même temps
    # Les 4 capitaines ont reçu leur MP avant la première fin de match.
    premiere_fin = next(i for i, (_, t) in enumerate(messagerie.mps) if "Match terminé" in t)
    assert sum("Vous devez créer la partie privée" in t for _, t in messagerie.mps[:premiere_fin]) == 4


def attendre_a_valider(stockage):
    def tous_a_valider():
        etat = stockage.charger_etat(TID)
        return bool(etat["rondes"]) and all(m["statut"] == L.MATCH_A_VALIDER for m in etat["rondes"][-1]["matchs"])
    return attendre_que(tous_a_valider)


def test_apres_le_delai_bouton_de_declaration_sans_alerte(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 4, declaration_auto=False)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_a_valider(stockage)
        assert g.est_actif(TID)  # le round attend
        etat = stockage.charger_etat(TID)
        for m in etat["rondes"][0]["matchs"]:
            await g.valider_resultat(TID, m["zone"], m["equipe_b"], 3, 2, serveur_id=SERVEUR, par=ADMIN)
        await asyncio.wait_for(g.attendre(TID), 5)
        return etat, stockage.charger_etat(TID), messagerie

    avant, etat, messagerie = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert all(m["valide_par"] == ADMIN and m["source_resultat"] == L.SOURCE_ADMIN for m in etat["rondes"][0]["matchs"])

    # Demander le score aux joueurs est le cas normal : pas d'alerte aux admins.
    assert messagerie.alertes == []
    assert all(m["raison_a_valider"] == L.RAISON_DECLARATION for m in avant["rondes"][0]["matchs"])

    # Chaque joueur (4 équipes × 2) a reçu le bouton de déclaration pour SON équipe.
    assert len(messagerie.boutons) == 8
    for joueur, (numero, zone, equipe_id) in messagerie.boutons:
        assert numero == 1
        assert any(j["id"] == joueur for j in avant["equipes"][str(equipe_id)]["joueurs"])
    declarations = [t for _, t in messagerie.mps if "Déclare le score de ton match" in t]
    assert len(declarations) == 8 and not any("n'a pas pu prendre le score" in t for t in declarations)


def test_le_bot_attend_le_delai_avant_de_demander_le_score(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2, delai=1.5, declaration_auto=False)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"])
                           and bool(stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["pp_creee_le"]))
        await asyncio.sleep(0.1)
        avant = (stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["statut"], list(messagerie.boutons))
        etat = stockage.charger_etat(TID)
        m = etat["rondes"][0]["matchs"][0]
        with pytest.raises(L.ErreurTournoi, match="pas encore fini"):
            await g.declarer_score(TID, 1, 1, m["equipe_a"], 3, 1, par=_joueur(etat, m["equipe_a"]))
        await attendre_a_valider(stockage)
        apres = list(messagerie.boutons)
        await g.fermer()
        return avant, apres

    (statut_avant, boutons_avant), boutons_apres = asyncio.run(scenario())
    assert statut_avant == L.MATCH_EN_COURS and boutons_avant == []  # pas de demande avant la fin du délai
    assert len(boutons_apres) == 4  # puis les 4 joueurs reçoivent le bouton


def _joueur(etat, equipe_id):
    return etat["equipes"][str(equipe_id)]["joueurs"][1]["id"]


def test_les_deux_equipes_declarent_le_meme_score(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2, declaration_auto=False)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_a_valider(stockage)
        etat = stockage.charger_etat(TID)
        m = etat["rondes"][0]["matchs"][0]
        a, b = 6, 0  # A gagne

        with pytest.raises(L.ErreurTournoi, match="ne joues pas"):
            await g.declarer_score(TID, 1, 1, m["equipe_a"], a, b, par=_joueur(etat, m["equipe_b"]))
        reponse_a = await g.declarer_score(TID, 1, 1, m["equipe_a"], a, b, par=_joueur(etat, m["equipe_a"]))
        assert g.est_actif(TID)
        reponse_b = await g.declarer_score(TID, 1, 1, m["equipe_b"], b, a, par=_joueur(etat, m["equipe_b"]))
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_etat(TID), messagerie, m, (a, b), reponse_a, reponse_b

    etat, messagerie, m, (a, b), reponse_a, reponse_b = asyncio.run(scenario())
    assert "autre équipe" in reponse_a
    assert "résultat enregistré" in reponse_b
    match = etat["rondes"][0]["matchs"][0]
    assert etat["statut"] == L.TERMINE
    assert match["source_resultat"] == L.SOURCE_DECLARATIONS and match["valide_par"] is None
    assert match["score"] == {"equipe_a": a, "equipe_b": b} and match["vainqueur"] == m["equipe_a"]
    assert etat["equipes"][str(m["equipe_a"])]["points"] == 3  # 1 seule zone = zone haute
    fin = [t for _, t in messagerie.mps if "Match terminé" in t]
    assert fin and all("déclaré par les deux équipes" in t for t in fin)
    assert messagerie.alertes == []


def test_declarations_differentes_alerte_puis_admin(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2, declaration_auto=False)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_a_valider(stockage)
        etat = stockage.charger_etat(TID)
        m = etat["rondes"][0]["matchs"][0]
        a, b = 6, 0
        await g.declarer_score(TID, 1, 1, m["equipe_a"], a, b, par=_joueur(etat, m["equipe_a"]))
        reponse = await g.declarer_score(TID, 1, 1, m["equipe_b"], b, a + 1, par=_joueur(etat, m["equipe_b"]))
        assert g.est_actif(TID)  # personne n'est d'accord : le round attend
        await g.valider_resultat(TID, 1, m["equipe_a"], a, b, serveur_id=SERVEUR, par=ADMIN)
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_etat(TID), messagerie, reponse

    etat, messagerie, reponse = asyncio.run(scenario())
    assert "score différent" in reponse
    assert etat["statut"] == L.TERMINE
    alertes = messagerie.titres_alertes()
    assert len(alertes) == 1 and "pas déclaré le même score" in alertes[0] and "Déclarations des équipes" in alertes[0]
    assert "score à déclarer par les équipes" not in alertes[0]
    # Les 4 joueurs sont prévenus, avec de nouveau le bouton pour corriger.
    assert sum("pas déclaré le même score" in t for _, t in messagerie.mps) == 4
    assert len(messagerie.boutons) == 4 + 4


def test_admin_peut_forcer_un_match_bloque_en_cours(tmp_path):
    async def scenario():
        g, stockage, _ = creer(tmp_path, 2, delai=60)  # le bot attend 60 s avant de demander le score
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: stockage.charger_etat(TID)["rondes"]
                           and stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["statut"] == L.MATCH_EN_COURS)
        await g.valider_resultat(TID, 1, 1, 1, 0, serveur_id=SERVEUR, par=ADMIN)
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_etat(TID)

    etat = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert etat["equipes"]["1"]["points"] == 3


def test_arret_du_tournoi(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 4, delai=60)
        await g.demarrer(TID, 5, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"]))
        await g.arreter(TID, serveur_id=SERVEUR, par=ADMIN)
        assert not g.est_actif(TID)
        with pytest.raises(L.ErreurTournoi, match="pas en cours"):
            await g.arreter(TID, serveur_id=SERVEUR, par=ADMIN)
        return stockage.charger_etat(TID), messagerie

    etat, messagerie = asyncio.run(scenario())
    assert etat["statut"] == L.ARRETE and etat["arrete_par"] == ADMIN
    assert all(m["statut"] == L.MATCH_ANNULE for m in etat["rondes"][0]["matchs"])
    assert sum("a été arrêté" in t for _, t in messagerie.mps) == 8  # 4 équipes × 2 joueurs


def test_reprise_apres_redemarrage(tmp_path):
    async def premier_lancement():
        g, stockage, _ = creer(tmp_path, 4, delai=60)
        await g.demarrer(TID, 2, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: any(m["statut"] == L.MATCH_EN_COURS
                                       for r in stockage.charger_etat(TID)["rondes"] for m in r["matchs"]))
        await g.fermer()  # le bot s'arrête en plein match

    async def redemarrage():
        g, stockage, messagerie = creer(tmp_path, 4)
        assert g.reprendre() == [TID]
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_etat(TID), messagerie

    asyncio.run(premier_lancement())
    etat, messagerie = asyncio.run(redemarrage())
    assert etat["statut"] == L.TERMINE and len(etat["rondes"]) == 2
    assert any("le bot a redémarré" in t for _, t in messagerie.mps)


def test_refus_de_lancement(tmp_path):
    async def scenario():
        g, _, _ = creer(tmp_path, 4, delai=60)
        with pytest.raises(L.ErreurTournoi, match="Aucun tournoi"):
            await g.demarrer("123", 2, serveur_id=SERVEUR, lance_par=ADMIN)
        with pytest.raises(L.ErreurTournoi, match="Aucun tournoi"):
            await g.demarrer(TID, 2, serveur_id="autre_serveur", lance_par=ADMIN)
        await g.demarrer(TID, 2, serveur_id=SERVEUR, lance_par=ADMIN)
        with pytest.raises(L.ErreurTournoi, match="déjà en cours"):
            await g.demarrer(TID, 2, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.fermer()

    asyncio.run(scenario())


def test_relancer_un_tournoi_termine_archive_l_ancien(tmp_path):
    async def scenario():
        g, stockage, _ = creer(tmp_path, 2)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)

    asyncio.run(scenario())
    archives = list((tmp_path / "data" / "archives").iterdir())
    assert len(archives) == 1
    assert json.loads(archives[0].read_text(encoding="utf-8"))["statut"] == L.TERMINE


# --------------------------------------------------------------------------- #
# Bouton « Partie privée créée »
# --------------------------------------------------------------------------- #

def test_le_bot_attend_le_clic_du_capitaine(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2, clic_auto=False)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(messagerie.boutons_pp))
        await asyncio.sleep(0.1)
        etat = stockage.charger_etat(TID)
        m = etat["rondes"][0]["matchs"][0]
        assert m["statut"] == L.MATCH_EN_COURS and m["pp_creee_le"] is None  # pas de clic : pas de délai
        assert m["chrono_declaration"] is None and messagerie.boutons == []

        capitaine = etat["equipes"][str(m["equipe_a"])]["capitaine_id"]
        assert messagerie.boutons_pp == [(capitaine, (1, 1))]  # seul le capitaine a le bouton
        with pytest.raises(L.ErreurTournoi, match="Seul le capitaine"):
            await g.signaler_pp_creee(TID, 1, 1, par=_joueur(etat, m["equipe_a"]))
        premier = await g.signaler_pp_creee(TID, 1, 1, par=capitaine)
        deuxieme = await g.signaler_pp_creee(TID, 1, 1, par=capitaine)
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_etat(TID), messagerie, capitaine, premier, deuxieme

    etat, messagerie, capitaine, premier, deuxieme = asyncio.run(scenario())
    assert "Merci" in premier and "Déjà noté" in deuxieme
    assert etat["statut"] == L.TERMINE
    match = etat["rondes"][0]["matchs"][0]
    assert match["pp_creee_par"] == capitaine and match["pp_creee_le"]
    # Les 3 autres joueurs sont prévenus une seule fois (pas au deuxième clic).
    prevenus = [j for j, t in messagerie.mps if "a créé la partie privée" in t]
    assert len(prevenus) == 3 and capitaine not in prevenus
    assert messagerie.alertes == []


def test_sans_clic_rappel_puis_le_delai_demarre_quand_meme(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, 2, clic_auto=False, rappel=0.05, attente_max=0.15)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await asyncio.wait_for(g.attendre(TID), 5)
        return stockage.charger_etat(TID), messagerie

    etat, messagerie = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE  # le score a été demandé quand même
    match = etat["rondes"][0]["matchs"][0]
    capitaine = etat["equipes"][str(match["equipe_a"])]["capitaine_id"]
    assert match["pp_creee_le"] is None and match["chrono_declaration"]
    assert match["source_resultat"] == L.SOURCE_DECLARATIONS
    rappels = [t for j, t in messagerie.mps if j == capitaine and "Rappel" in t]
    assert len(rappels) == 1 and match["pp"]["mot_de_passe"] in rappels[0]
    assert messagerie.boutons_pp == [(capitaine, (1, 1))] * 2  # le rappel a aussi le bouton
    alertes = messagerie.titres_alertes()
    assert len(alertes) == 1 and "n'a pas cliqué sur « Partie privée créée »" in alertes[0]


def test_redemarrage_apres_le_clic(tmp_path):
    async def premier_lancement():
        g, stockage, _ = creer(tmp_path, 2, delai=60)  # le capitaine clique, puis le bot attend 60 s
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"])
                           and bool(stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["pp_creee_le"]))
        await g.fermer()

    async def redemarrage():
        g, stockage, messagerie = creer(tmp_path, 2, clic_auto=False)
        g.reprendre()
        await asyncio.wait_for(g.attendre(TID), 5)  # pas besoin d'un nouveau clic
        return stockage.charger_etat(TID), messagerie

    asyncio.run(premier_lancement())
    etat, messagerie = asyncio.run(redemarrage())
    assert etat["statut"] == L.TERMINE
    assert messagerie.boutons_pp == []
    assert any("Tu as indiqué que la partie est créée" in t for _, t in messagerie.mps)
    # Partie déjà créée : le rappel aux autres joueurs redonne le nom et le mot de passe.
    match = etat["rondes"][0]["matchs"][0]
    rappels = [t for _, t in messagerie.mps if "a créé la partie privée. Rejoins-la avec" in t]
    assert len(rappels) == 3 and all(match["pp"]["mot_de_passe"] in t for t in rappels)


# --------------------------------------------------------------------------- #
# Délai avant la demande de score, après un redémarrage
# --------------------------------------------------------------------------- #

def _redemarrer_avec_chrono(tmp_path, il_y_a: float, delai: float):
    """Bot arrêté pendant le délai, relancé avec un départ du délai noté `il_y_a` secondes plus tôt.
    Renvoie (secondes écoulées avant la demande de score, nombre de boutons de déclaration)."""
    async def premier_lancement():
        g, stockage, _ = creer(tmp_path, 2, delai=600)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"])
                           and bool(stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["chrono_declaration"]))
        await g.fermer()
        etat = stockage.charger_etat(TID)
        depart = datetime.now() - timedelta(seconds=il_y_a)
        etat["rondes"][0]["matchs"][0]["chrono_declaration"] = depart.isoformat(timespec="seconds")
        stockage.sauvegarder_etat(etat)

    async def redemarrage():
        g, stockage, messagerie = creer(tmp_path, 2, delai=delai, declaration_auto=False, clic_auto=False)
        debut = time.monotonic()
        g.reprendre()
        await attendre_a_valider(stockage)
        ecoule = time.monotonic() - debut
        await g.fermer()
        return ecoule, messagerie

    asyncio.run(premier_lancement())
    ecoule, messagerie = asyncio.run(redemarrage())
    return ecoule, messagerie


def test_redemarrage_le_delai_deja_passe_demande_le_score_tout_de_suite(tmp_path):
    ecoule, messagerie = _redemarrer_avec_chrono(tmp_path, il_y_a=400, delai=360)
    assert ecoule < 1
    assert len(messagerie.boutons) == 4
    assert messagerie.boutons_pp == []  # pas de nouveau bouton « Partie privée créée »


def test_redemarrage_attend_seulement_le_temps_qui_reste(tmp_path):
    # Délai de 360 s commencé il y a 359 s : il reste environ 1 s (horodatage à la seconde près).
    ecoule, messagerie = _redemarrer_avec_chrono(tmp_path, il_y_a=359, delai=360)
    assert ecoule < 3
    assert len(messagerie.boutons) == 4
