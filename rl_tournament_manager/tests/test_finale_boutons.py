"""Finale (BO3) : bouton « Partie privée créée » dans LOG_CHANNEL (MP aux joueurs), bouton « Entrer le score »
DELAI_SCORE_FINALE après, puis résultat dans le salon des résultats."""

import asyncio
import random
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.declaration import BoutonFinalePP, BoutonFinaleScore, FenetreScoreFinale
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, FausseMessagerie, demarrer, ecrire_inscription, faux_pp, tournoi_inscription
from .test_simulation import _config_env

TID = "1571169059024928818"


def gestionnaire(tmp_path: Path, delai_score_finale: float = 0):
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(8, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(declaration_auto=True)
    g = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0, delai_declaration=0, generer_pp=faux_pp,
                             rng=random.Random(3), gain_finale="10 €", delai_score_finale=delai_score_finale)
    messagerie.gestionnaire = g
    return g, stockage, messagerie


async def tournoi_fini(g) -> dict:
    await demarrer(g, TID, 2, serveur_id=SERVEUR, lance_par=ADMIN, finale=True)
    await g.attendre(TID)
    return g.stockage.charger_etat(TID)


def joueurs(etat: dict, *equipes: int) -> set[str]:
    return {j["id"] for equipe_id in equipes for j in L.equipe(etat, equipe_id)["joueurs"]}


# --------------------------------------------------------------------------- #
# Déroulement complet
# --------------------------------------------------------------------------- #

def test_clic_puis_score_puis_resultat(tmp_path):
    async def scenario():
        g, stockage, messagerie = gestionnaire(tmp_path)
        etat = await tournoi_fini(g)
        mps_avant = len(messagerie.mps)
        reponse_pp = await g.signaler_pp_finale(TID, serveur_id=SERVEUR, par=ADMIN)
        mps_pp = messagerie.mps[mps_avant:]
        await g.attendre_score_finale(TID)
        finale = stockage.charger_etat(TID)["match_finale"]
        reponse_score = await g.enregistrer_score_finale(TID, 1, 2, serveur_id=SERVEUR, par=ADMIN)
        return etat, finale, reponse_pp, mps_pp, reponse_score, stockage.charger_etat(TID), messagerie

    etat, finale, reponse_pp, mps_pp, reponse_score, fin, messagerie = asyncio.run(scenario())
    a, b = finale["equipe_a"], finale["equipe_b"]

    # Clic : MP « Rejoins … BO3 final … 10 € à gagner » à tous les joueurs des deux équipes, et à eux seuls.
    assert {j for j, _ in mps_pp} == joueurs(etat, a, b)
    assert all("BO3 final" in texte and "10 € à gagner" in texte and "`tomato_finale`" in texte
               for _, texte in mps_pp)
    assert reponse_pp.startswith(f"✅ Partie de la finale signalée : MP envoyé à {len(mps_pp)} joueurs")
    assert finale["pp_creee_par"] == ADMIN and finale["pp_creee_le"]

    # Après le délai : bouton « Entrer le score » dans LOG_CHANNEL.
    assert [bouton for _, bouton in messagerie.boutons_finale] == [("pp", TID), ("score", TID)]
    assert "Score de la finale (BO3)" in messagerie.boutons_finale[1][0]
    assert finale["score_demande_le"]

    # Score : l'équipe B gagne 2-1. Résultat dans le salon des résultats, MP aux deux équipes, note dans les logs.
    match = fin["match_finale"]
    assert match["score"] == {"equipe_a": 1, "equipe_b": 2} and match["vainqueur"] == b
    assert reponse_score.startswith("✅ Score de la finale enregistré : 1-2")
    resultat = "\n".join(e.title + "\n" + e.description for e in messagerie.resultats_rondes[-1])
    nom_b, nom_a = L.equipe(fin, b)["nom"], L.equipe(fin, a)["nom"]
    assert "vainqueur de la finale BO3" in resultat
    assert f"**{nom_b}** remporte la finale **2-1** contre **{nom_a}**" in resultat
    assert all(j["pseudo"] in resultat for j in L.equipe(fin, b)["joueurs"])
    gagnants = [j for j, t in messagerie.mps if "remporte la finale" in t]
    perdants = [j for j, t in messagerie.mps if "perd la finale" in t]
    assert set(gagnants) == joueurs(fin, b) and set(perdants) == joueurs(fin, a)
    assert "Score de la finale" in messagerie.journaux[-1] and "enregistré" in messagerie.journaux[-1]
    # Le classement par points ne change pas.
    assert [e["id"] for e in L.classement(fin)] == [e["id"] for e in L.classement(etat)]


def test_bouton_du_score_attend_le_delai(tmp_path):
    async def scenario():
        g, stockage, messagerie = gestionnaire(tmp_path, delai_score_finale=0.3)
        await tournoi_fini(g)
        await g.signaler_pp_finale(TID, serveur_id=SERVEUR, par=ADMIN)
        await asyncio.sleep(0.05)
        avant = list(messagerie.boutons_finale)
        await g.attendre_score_finale(TID)
        return avant, messagerie.boutons_finale

    avant, apres = asyncio.run(scenario())
    assert [b for _, b in avant] == [("pp", TID)]
    assert [b for _, b in apres] == [("pp", TID), ("score", TID)]


def test_second_clic_refuse_et_rien_renvoye(tmp_path):
    async def scenario():
        g, _, messagerie = gestionnaire(tmp_path)
        await tournoi_fini(g)
        await g.signaler_pp_finale(TID, serveur_id=SERVEUR, par=ADMIN)
        with pytest.raises(L.ErreurTournoi, match="déjà signalée"):
            await g.signaler_pp_finale(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.attendre_score_finale(TID)
        return g.stockage.charger_etat(TID), messagerie

    etat, messagerie = asyncio.run(scenario())
    finale = etat["match_finale"]
    nb_finalistes = len(joueurs(etat, finale["equipe_a"], finale["equipe_b"]))
    assert len([m for m in messagerie.mps if "BO3 final" in m[1]]) == nb_finalistes  # un seul MP chacun
    assert [b for _, b in messagerie.boutons_finale].count(("score", TID)) == 1


def test_score_avant_le_clic_refuse(tmp_path):
    async def scenario():
        g, _, _ = gestionnaire(tmp_path)
        await tournoi_fini(g)
        with pytest.raises(L.ErreurTournoi, match="Partie privée créée"):
            await g.enregistrer_score_finale(TID, 2, 0, serveur_id=SERVEUR, par=ADMIN)

    asyncio.run(scenario())


@pytest.mark.parametrize("score", [(2, 2), (1, 1), (3, 0), (0, 0), (1, 0)])
def test_score_impossible_pour_un_bo3_refuse(tmp_path, score):
    async def scenario():
        g, stockage, _ = gestionnaire(tmp_path)
        await tournoi_fini(g)
        await g.signaler_pp_finale(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.attendre_score_finale(TID)
        with pytest.raises(L.ErreurTournoi, match="Score impossible pour un BO3"):
            await g.enregistrer_score_finale(TID, *score, serveur_id=SERVEUR, par=ADMIN)
        return stockage.charger_etat(TID)["match_finale"]["score"]

    assert asyncio.run(scenario()) is None


def test_score_corrige(tmp_path):
    async def scenario():
        g, stockage, messagerie = gestionnaire(tmp_path)
        await tournoi_fini(g)
        await g.signaler_pp_finale(TID, serveur_id=SERVEUR, par=ADMIN)
        await g.attendre_score_finale(TID)
        await g.enregistrer_score_finale(TID, 2, 0, serveur_id=SERVEUR, par=ADMIN)
        reponse = await g.enregistrer_score_finale(TID, 0, 2, serveur_id=SERVEUR, par=ADMIN)
        return reponse, stockage.charger_etat(TID)["match_finale"], messagerie

    reponse, finale, messagerie = asyncio.run(scenario())
    assert reponse.startswith("✅ Score de la finale corrigé : 0-2")
    assert finale["vainqueur"] == finale["equipe_b"]
    assert "Score corrigé" in messagerie.resultats_rondes[-1][0].description


def test_autre_serveur_refuse(tmp_path):
    async def scenario():
        g, _, _ = gestionnaire(tmp_path)
        await tournoi_fini(g)
        with pytest.raises(L.ErreurTournoi, match="Aucun tournoi"):
            await g.signaler_pp_finale(TID, serveur_id="999", par=ADMIN)

    asyncio.run(scenario())


def test_redemarrage_reprend_le_delai_du_score(tmp_path):
    async def scenario():
        g, stockage, _ = gestionnaire(tmp_path)
        etat = await tournoi_fini(g)
        # Clic noté il y a 20 min, bot redémarré avant d'avoir posté le bouton du score.
        L.signaler_pp_finale(etat, par=ADMIN, maintenant=(datetime.now() - timedelta(minutes=20)).isoformat())
        stockage.sauvegarder_etat(etat)
        g2, _, messagerie2 = gestionnaire(tmp_path, delai_score_finale=900)
        ids = g2.reprendre()
        await g2.attendre_score_finale(TID)
        # Un autre redémarrage ne reposte pas le bouton.
        g3, _, messagerie3 = gestionnaire(tmp_path, delai_score_finale=900)
        ids3 = g3.reprendre()
        return ids, messagerie2.boutons_finale, ids3, messagerie3.boutons_finale

    ids, boutons, ids3, boutons3 = asyncio.run(scenario())
    assert f"{TID} (score de la finale)" in ids
    assert [b for _, b in boutons] == [("score", TID)]
    assert f"{TID} (score de la finale)" not in ids3 and boutons3 == []


# --------------------------------------------------------------------------- #
# Boutons Discord (faux objets)
# --------------------------------------------------------------------------- #

class FausseReponse:
    def __init__(self) -> None:
        self.envois, self.modales, self.differe = [], [], False

    async def send_message(self, texte, **kwargs) -> None:
        self.envois.append((texte, kwargs))

    async def send_modal(self, modale) -> None:
        self.modales.append(modale)

    async def defer(self, **kwargs) -> None:
        self.differe = True


class FausseSuite:
    def __init__(self) -> None:
        self.envois = []

    async def send(self, texte, **kwargs) -> None:
        self.envois.append((texte, kwargs))


def fausse_interaction(g, admin: bool = True):
    async def editer(**kwargs):
        interaction.vue_editee = kwargs.get("view")

    interaction = SimpleNamespace(
        client=SimpleNamespace(gestionnaire=g), guild_id=int(SERVEUR),
        user=SimpleNamespace(id=int(ADMIN), guild_permissions=SimpleNamespace(manage_guild=admin)),
        response=FausseReponse(), followup=FausseSuite(), edit_original_response=editer, vue_editee=None)
    return interaction


def test_boutons_reserves_aux_admins(tmp_path):
    async def scenario():
        g, _, messagerie = gestionnaire(tmp_path)
        await tournoi_fini(g)
        joueur = fausse_interaction(g, admin=False)
        await BoutonFinalePP(TID).callback(joueur)
        await BoutonFinaleScore(TID).callback(joueur)
        return joueur, g.stockage.charger_etat(TID)["match_finale"]

    joueur, finale = asyncio.run(scenario())
    assert [t for t, _ in joueur.response.envois] == [
        "❌ Seuls les admins (permission **Gérer le serveur**) peuvent utiliser ce bouton."] * 2
    assert finale["pp_creee_le"] is None


def test_bouton_pp_puis_fenetre_du_score(tmp_path):
    async def scenario():
        g, stockage, _ = gestionnaire(tmp_path)
        await tournoi_fini(g)
        clic = fausse_interaction(g)
        await BoutonFinalePP(TID).callback(clic)
        await g.attendre_score_finale(TID)
        bouton_score = fausse_interaction(g)
        await BoutonFinaleScore(TID).callback(bouton_score)
        [fenetre] = bouton_score.response.modales
        fenetre.manches_a._value, fenetre.manches_b._value = "2", "1"
        envoi = fausse_interaction(g)
        await fenetre.on_submit(envoi)
        return clic, fenetre, envoi, stockage.charger_etat(TID)

    clic, fenetre, envoi, etat = asyncio.run(scenario())
    assert clic.vue_editee is not None and clic.vue_editee.children[0].disabled  # bouton grisé
    assert clic.followup.envois[0][0].startswith("✅ Partie de la finale signalée")
    assert isinstance(fenetre, FenetreScoreFinale)
    assert envoi.followup.envois[0][0].startswith("✅ Score de la finale enregistré : 2-1")
    assert etat["match_finale"]["vainqueur"] == etat["match_finale"]["equipe_a"]


def test_fenetre_refuse_un_texte(tmp_path):
    async def scenario():
        g, _, _ = gestionnaire(tmp_path)
        await tournoi_fini(g)
        fenetre = FenetreScoreFinale(TID, "A", "B")
        fenetre.manches_a._value, fenetre.manches_b._value = "deux", "1"
        envoi = fausse_interaction(g)
        await fenetre.on_submit(envoi)
        return envoi

    envoi = asyncio.run(scenario())
    assert envoi.response.envois[0][0].startswith("❌ Mets seulement des nombres")


# --------------------------------------------------------------------------- #
# Réglages
# --------------------------------------------------------------------------- #

def test_config_finale(monkeypatch, tmp_path):
    for nom in ("GAIN_FINALE", "DELAI_SCORE_FINALE"):
        monkeypatch.delenv(nom, raising=False)
    config = _config_env(monkeypatch, tmp_path)
    assert config.gain_finale == "10 €" and config.delai_score_finale == 900
    config = _config_env(monkeypatch, tmp_path, GAIN_FINALE="20 €", DELAI_SCORE_FINALE="10")
    assert config.gain_finale == "20 €" and config.delai_score_finale == 10


def test_mp_sans_gain():
    tournoi = tournoi_inscription(4, TID)
    e = L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=1, lance_par=ADMIN,
                      maintenant="t", finale=True)
    L.preparer_finale(e, {"nom": "x", "mot_de_passe": "y"}, "t", gain="")
    assert "à gagner" not in M.mp_finale(e, e["match_finale"]["equipe_a"])
