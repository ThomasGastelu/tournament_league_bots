"""Option finals de /start_tournament_rl : BO3 entre les 2 premiers à la fin des rounds
(partie privée à créer dans LOG_CHANNEL, partie à rejoindre en MP aux deux équipes)."""

import asyncio
import random
from pathlib import Path

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.deroulement import GestionnaireTournois
from bot_tournament_manager.pp import partie_finale
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, FausseMessagerie, demarrer, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"


def etat(finale: bool = True, nb_equipes: int = 8) -> dict:
    tournoi = tournoi_inscription(nb_equipes, TID)
    return L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=2, lance_par=ADMIN,
                         maintenant="2026-11-27T15:00:00", finale=finale)


def jouer(e: dict, equipe_id: int, *, points: int, zone: int, pour: int = 3, contre: int = 1) -> None:
    """Résultat fictif : une victoire dans `zone`."""
    eq = L.equipe(e, equipe_id)
    eq.update(points=eq["points"] + points, victoires=eq["victoires"] + 1, matchs_joues=eq["matchs_joues"] + 1,
              buts_pour=eq["buts_pour"] + pour, buts_contre=eq["buts_contre"] + contre)
    eq["historique"].append({"ronde": len(eq["historique"]) + 1, "zone": zone, "adversaire": 0,
                             "score": f"{pour}-{contre}", "resultat": "victoire", "points": points})


# --------------------------------------------------------------------------- #
# Règles
# --------------------------------------------------------------------------- #

def test_finale_notee_entre_les_deux_premiers():
    e = etat()
    jouer(e, 3, points=4, zone=4)
    jouer(e, 5, points=2, zone=3)
    finale = L.preparer_finale(e, partie_finale(), "2026-11-27T18:00:00", gain="10 €")
    assert finale == {"format": "bo3", "equipe_a": 3, "equipe_b": 5,
                      "pp": {"nom": "tomato_finale", "mot_de_passe": "tomato_finale"},
                      "cree_le": "2026-11-27T18:00:00", "gain": "10 €",
                      "pp_creee_le": None, "pp_creee_par": None, "score_demande_le": None,
                      "score": None, "vainqueur": None, "score_le": None, "score_par": None}
    assert e["match_finale"] is finale


def test_sans_finale_rien_n_est_note():
    e = etat(finale=False)
    assert e["finale"] is False
    assert L.preparer_finale(e, partie_finale(), "t") is None and e["match_finale"] is None


def test_ancien_tournoi_sans_option_n_a_pas_de_finale():
    e = etat()
    del e["finale"], e["match_finale"]  # JSON d'un tournoi lancé avant cette option
    assert not L.a_une_finale(e)
    assert L.preparer_finale(e, partie_finale(), "t") is None


def test_finale_jamais_notee_deux_fois():
    e = etat()
    premiere = L.preparer_finale(e, partie_finale(), "t1")
    assert L.preparer_finale(e, partie_finale(), "t2") is None
    assert e["match_finale"] is premiere


def test_egalite_parfaite_departagee_par_la_zone_du_dernier_round():
    e = etat()
    jouer(e, 1, points=5, zone=4)
    # Équipes 7 et 2 : mêmes points, victoires, différence et buts. La 7 a fini en zone 3, la 2 en zone 2 :
    # la 7 passe devant, même si « Equipe2 » vient avant dans l'ordre alphabétique.
    jouer(e, 2, points=3, zone=2)
    jouer(e, 7, points=3, zone=3)
    assert [x["id"] for x in L.classement(e)[:3]] == [1, 7, 2]
    assert L.preparer_finale(e, partie_finale(), "t")["equipe_b"] == 7


def test_egalite_totale_meme_zone_departagee_par_le_nom():
    e = etat()
    jouer(e, 2, points=3, zone=2)
    jouer(e, 7, points=3, zone=2)
    noms = {2: L.equipe(e, 2)["nom"].casefold(), 7: L.equipe(e, 7)["nom"].casefold()}
    attendu = sorted((2, 7), key=noms.get)
    assert [x["id"] for x in L.classement(e)[:2]] == attendu


# --------------------------------------------------------------------------- #
# Textes
# --------------------------------------------------------------------------- #

def test_textes_de_la_finale():
    e = etat()
    jouer(e, 3, points=4, zone=4)
    jouer(e, 5, points=2, zone=3)
    L.preparer_finale(e, partie_finale(), "t", gain="10 €")
    a, b = L.equipe(e, 3)["nom"], L.equipe(e, 5)["nom"]
    journal = M.texte_journal_finale(e)
    assert "Finale (BO3)" in journal and a in journal and b in journal
    assert "Crée la partie privée" in journal and "`tomato_finale`" in journal
    assert "**Partie privée créée**" in journal
    mp = M.mp_finale(e, 5)
    assert mp.startswith(f"🏆 Rejoins **{e['titre']}** · **BO3 final** · 💰 **10 € à gagner** !")
    assert f"affronte **{a}**" in mp and "`tomato_finale`" in mp
    assert M.ligne_finale(e).startswith("🏆 Finale : oui")
    assert M.ligne_finale(etat(finale=False)) == "🏆 Finale : non"


# --------------------------------------------------------------------------- #
# Tournoi complet
# --------------------------------------------------------------------------- #

def gestionnaire(tmp_path: Path):
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(8, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(declaration_auto=True)
    g = GestionnaireTournois(stockage, messagerie, pause_entre_rondes=0,
                             delai_declaration=0, generer_pp=faux_pp, rng=random.Random(3))
    messagerie.gestionnaire = g
    return g, stockage, messagerie


def lancer(tmp_path: Path, finale: bool):
    async def scenario():
        g, stockage, messagerie = gestionnaire(tmp_path)
        await demarrer(g, TID, 2, serveur_id=SERVEUR, lance_par=ADMIN, finale=finale)
        await g.attendre(TID)
        return stockage.charger_etat(TID), messagerie
    return asyncio.run(scenario())


def test_tournoi_complet_avec_finale(tmp_path):
    e, messagerie = lancer(tmp_path, finale=True)

    assert e["statut"] == L.TERMINE
    premier, second = L.classement(e)[:2]
    finale = e["match_finale"]
    assert (finale["equipe_a"], finale["equipe_b"]) == (premier["id"], second["id"])

    # LOG_CHANNEL : la partie privée à créer, avec le bouton « Partie privée créée ».
    [(texte, bouton)] = messagerie.boutons_finale
    assert "Finale (BO3)" in texte and "`tomato_finale`" in texte and bouton == ("pp", TID)
    # Les joueurs ne reçoivent rien avant le clic.
    assert not any("BO3 final" in texte for _, texte in messagerie.mps)


def test_tournoi_complet_sans_finale(tmp_path):
    e, messagerie = lancer(tmp_path, finale=False)

    assert e["statut"] == L.TERMINE and e["match_finale"] is None
    assert not any("Finale" in j for j in messagerie.journaux) and messagerie.boutons_finale == []
    assert not any("finale" in texte.lower() for _, texte in messagerie.mps)
