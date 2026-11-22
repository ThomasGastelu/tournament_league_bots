"""/start_tournament_modify_pp : changer le nom et le mot de passe de la partie privée d'une zone."""

import asyncio

import pytest

from bot_tournament_manager import logique as L

from .outils import ADMIN, SERVEUR, attendre_que
from .test_deroulement import TID, creer


def lancer(tmp_path, *, clic: bool):
    """Tournoi à 2 équipes (1 zone), en cours ; avec `clic`, la partie est déjà créée."""
    async def demarrer():
        g, stockage, messagerie = creer(tmp_path, 2, delai=60, clic_auto=clic)
        await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        if clic:
            await attendre_que(lambda: bool(stockage.charger_etat(TID)["rondes"])
                               and bool(stockage.charger_etat(TID)["rondes"][0]["matchs"][0]["pp_creee_le"]))
        else:
            await attendre_que(lambda: bool(messagerie.boutons_pp))
        return g, stockage, messagerie
    return demarrer


def test_partie_deja_creee_tous_les_joueurs_recoivent_la_nouvelle(tmp_path):
    async def scenario():
        g, stockage, messagerie = await lancer(tmp_path, clic=True)()
        nb_mps = len(messagerie.mps)
        etat, match = await g.modifier_pp(TID, 1, " tomato_Z ", None, serveur_id=SERVEUR, par=ADMIN)
        nouveaux = messagerie.mps[nb_mps:]
        await g.fermer()
        return stockage.charger_etat(TID), match, nouveaux, messagerie

    etat, match, nouveaux, messagerie = asyncio.run(scenario())
    assert match["pp"] == {"nom": "tomato_Z", "mot_de_passe": "tomato_Z"}  # mot de passe vide = nom
    assert etat["rondes"][0]["matchs"][0]["pp"] == match["pp"]  # gardé dans le JSON
    assert len(nouveaux) == 4 and all("La partie privée a changé" in t and "tomato_Z" in t for _, t in nouveaux)
    assert any("tomato_test1" in t and "tomato_Z" in t for t in messagerie.journaux)


def test_partie_pas_encore_creee_seul_le_capitaine_est_prevenu(tmp_path):
    async def scenario():
        g, stockage, messagerie = await lancer(tmp_path, clic=False)()
        nb_mps = len(messagerie.mps)
        etat, match = await g.modifier_pp(TID, 1, "maPartie", "secret", serveur_id=SERVEUR, par=ADMIN)
        nouveaux = messagerie.mps[nb_mps:]
        capitaine = etat["equipes"][str(match["equipe_a"])]["capitaine_id"]
        # Au clic, les autres joueurs reçoivent la nouvelle partie.
        await g.signaler_pp_creee(TID, 1, 1, par=capitaine)
        apres_clic = messagerie.mps[nb_mps + len(nouveaux):]
        await g.fermer()
        return capitaine, nouveaux, apres_clic, messagerie

    capitaine, nouveaux, apres_clic, messagerie = asyncio.run(scenario())
    assert [j for j, _ in nouveaux] == [capitaine]
    assert "Vous devez créer la partie privée" in nouveaux[0][1] and "secret" in nouveaux[0][1]
    assert messagerie.boutons_pp[-1] == (capitaine, (1, 1))  # avec le bouton « Partie privée créée »
    assert len(apres_clic) == 3 and all("maPartie" in t and "secret" in t for _, t in apres_clic)


def test_refus(tmp_path):
    async def scenario():
        g, _, _ = await lancer(tmp_path, clic=True)()
        with pytest.raises(L.ErreurTournoi, match="vide"):
            await g.modifier_pp(TID, 1, "  ", None, serveur_id=SERVEUR, par=ADMIN)
        with pytest.raises(L.ErreurTournoi, match="32 caractères"):
            await g.modifier_pp(TID, 1, "x" * 33, None, serveur_id=SERVEUR, par=ADMIN)
        with pytest.raises(L.ErreurTournoi):
            await g.modifier_pp(TID, 7, "a", None, serveur_id=SERVEUR, par=ADMIN)  # zone inconnue
        with pytest.raises(L.ErreurTournoi, match="Aucun tournoi"):
            await g.modifier_pp(TID, 1, "a", None, serveur_id="autre", par=ADMIN)
        await g.valider_resultat(TID, 1, 1, 3, 1, serveur_id=SERVEUR, par=ADMIN)
        await g.attendre(TID)
        with pytest.raises(L.ErreurTournoi):
            await g.modifier_pp(TID, 1, "a", None, serveur_id=SERVEUR, par=ADMIN)  # tournoi terminé

    asyncio.run(scenario())


def test_match_fini_refuse():
    match = {"statut": L.MATCH_A_VALIDER, "pp": {"nom": "a", "mot_de_passe": "a"}}
    with pytest.raises(L.ErreurTournoi, match="plus en cours"):
        L.modifier_pp(match, "b", None)
