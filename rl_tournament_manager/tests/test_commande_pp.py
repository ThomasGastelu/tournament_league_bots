"""/start_tournament_rl_pp : nom et mot de passe de toutes les parties privées d'un tournoi (admins, éphémère)."""

import asyncio
from types import SimpleNamespace

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.commandes import start_tournament_rl_pp
from bot_tournament_manager.pp import partie_finale
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, tournoi_inscription

TID = "1571169059024928818"


def etat(rondes: int = 2) -> dict:
    tournoi = tournoi_inscription(4, TID, serveur_id=SERVEUR)
    e = L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=2, lance_par=ADMIN,
                      maintenant="2026-11-27T15:00:00", finale=True)
    for numero in range(1, rondes + 1):
        parties = [{"nom": f"tomato_{numero}{z}", "mot_de_passe": f"tomato_{numero}{z}"} for z in (1, 2)]
        L.nouvelle_ronde(e, [(1, 2), (3, 4)], parties, fichier_pp="x.json", maintenant="t")
    return e


def texte(embeds) -> str:
    return "\n".join(x.description for x in embeds)


def test_liste_toutes_les_parties_de_chaque_round():
    contenu = texte(M.embeds_pp(etat()))
    for nom in ("tomato_11", "tomato_12", "tomato_21", "tomato_22"):
        assert f"`{nom}` / `{nom}`" in contenu
    assert contenu.index("**🎯 Round 1/2**") < contenu.index("**🎯 Round 2/2**")
    assert contenu.index("Zone 2 ⭐") < contenu.index("Zone 1 ·")  # zone haute en premier
    assert "Finale" not in contenu


def test_partie_changee_a_la_main_affichee():
    e = etat(rondes=1)
    L.trouver_match(L.trouver_ronde(e, 1), 2)["pp"] = {"nom": "ma_partie", "mot_de_passe": "secret"}
    assert "`ma_partie` / `secret`" in texte(M.embeds_pp(e))


def test_finale_affichee_quand_elle_est_notee():
    e = etat()
    L.preparer_finale(e, partie_finale(), "t")
    contenu = texte(M.embeds_pp(e))
    assert "**🏆 Finale (BO3)**" in contenu and "`tomato_finale` / `tomato_finale`" in contenu


def test_avant_le_premier_round():
    assert "Pas encore de partie privée" in texte(M.embeds_pp(etat(rondes=0)))


class FausseReponse:
    def __init__(self) -> None:
        self.envois = []

    def is_done(self) -> bool:
        return False

    async def send_message(self, texte, **kwargs) -> None:
        self.envois.append((texte, kwargs))


def interaction(stockage: Stockage, serveur: str = SERVEUR) -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(gestionnaire=SimpleNamespace(stockage=stockage)),
                           guild_id=int(serveur), response=FausseReponse(), user="admin")


def test_commande_repond_en_ephemere(tmp_path):
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    stockage.sauvegarder_etat(etat())
    i = interaction(stockage)

    asyncio.run(start_tournament_rl_pp.callback(i, f" {TID} "))

    [(texte_envoye, kwargs)] = i.response.envois
    assert texte_envoye is None and kwargs["ephemeral"]
    assert "`tomato_22` / `tomato_22`" in texte(kwargs["embeds"])


def test_commande_refuse_un_tournoi_inconnu_ou_d_un_autre_serveur(tmp_path):
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    inconnu = interaction(stockage)
    asyncio.run(start_tournament_rl_pp.callback(inconnu, TID))
    stockage.sauvegarder_etat(etat())
    autre = interaction(stockage, serveur="999")
    asyncio.run(start_tournament_rl_pp.callback(autre, TID))

    for faux in (inconnu, autre):
        [(texte_envoye, kwargs)] = faux.response.envois
        assert texte_envoye.startswith("❌ Aucun tournoi") and kwargs["ephemeral"]


def test_commande_reservee_aux_admins():
    assert start_tournament_rl_pp.default_permissions.manage_guild
