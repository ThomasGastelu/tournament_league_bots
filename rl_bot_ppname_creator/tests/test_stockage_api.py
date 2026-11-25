"""Stockage dans la base de données via l'API (StockageAPI).

1. Sans API : traduction des erreurs, corps envoyés, copie JSON pour tournament_manager,
   API injoignable. La requête HTTP est remplacée par une fausse.
2. Avec une vraie API (facultatif) : le parcours complet du bot, des commandes aux boutons.
   Lancé seulement si API_TEST_URL et API_TEST_KEY sont définis, par exemple :
       $env:API_TEST_URL="http://localhost"; $env:API_TEST_KEY="<BOT_API_KEY>"; .venv\\Scripts\\python -m pytest
   ⚠️ Il crée de vrais tournois : à lancer sur une base de test, jamais sur la base de production.
"""

import itertools
import json
import os
import time
from pathlib import Path

import aiohttp
import pytest

from bot_inscription_manager import logique as L
from bot_inscription_manager.commandes import (autocomplete_tournoi, tournoi_rl, tournoi_rl_modify,
                                               tournoi_rl_remove, tournoi_rl_remove_team, tournoi_rl_reserve,
                                               tournoi_rl_status, tournoi_rl_unreserve)
from bot_inscription_manager.inscription import BoutonAnnuler, BoutonRefuser, expirer_inscriptions
from bot_inscription_manager.main import choisir_stockage
from bot_inscription_manager.stockage import StockageFichiers
from bot_inscription_manager.stockage_api import (MESSAGE_API_INJOIGNABLE, MESSAGE_API_REFUSE,
                                                  MESSAGE_PAS_ENCORE_DANS_L_API, ErreurAPI, StockageAPI,
                                                  traduire_erreur)
from tests.test_bot_simulation import (FausseInteraction, FauxClient, FauxMessage, FauxUtilisateur, confirmer,
                                       inscrire, lancer)

CLE = "k" * 40


def tournoi_api(**champs):
    t = L.nouveau_tournoi(
        tournoi_id="1573714661659123762", titre="caca", cashprize="100", joueurs_par_equipe=2, equipes_max=1,
        date="6 septembre", serveur_id="1540386765054148639", salon_id="1543205821490528366",
        cree_par="543505378210611220", maintenant="2026-11-21T15:00:14.000Z")
    t.update(champs)
    return t


class FausseAPI(StockageAPI):
    """StockageAPI dont la requête HTTP renvoie des réponses préparées."""

    def __init__(self, reponses, dossier=None):
        super().__init__("http://api.test", CLE, dossier_miroir=dossier)
        self.reponses = list(reponses)
        self.requetes = []

    async def _requete(self, methode, chemin, corps=None, params=None):
        self.requetes.append((methode, chemin, corps, params))
        reponse = self.reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


# --------------------------------------------------------------------------- #
# Sans API
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("statut, corps, contexte, attendu", [
    (404, {"error": "Tournament not found"}, {}, "Ce tournoi n'existe plus."),
    (404, {"error": "Team not found"}, {"numero": 3}, "Aucune équipe #3"),
    (409, {"error": "Tournament is full"}, {}, "complet, liste d'attente comprise"),
    (409, {"error": "Team name already taken"}, {"nom": "Turbo"}, "Le nom **Turbo** est déjà pris"),
    (409, {"error": "Player already in a team of this tournament", "details": {"playerIds": ["12"]}},
     {"pseudos": {"12": "Lucas"}}, "**Lucas** est déjà dans une équipe"),
    (409, {"error": "Registrations not open yet", "details": {"ouverture_inscriptions": "2026-11-21T17:00:00.000Z"}},
     {}, "Les inscriptions ouvrent <t:1795280400:R>"),
    (400, {"error": "Wrong number of teammates (expected 2)"}, {}, "exactement 2 coéquipier(s)"),
    (409, {"error": "equipes_max cannot be lower than 5 (4 registered + 1 reserved)"}, {},
     "en dessous de 5"),
    (409, {"error": "Reservation is not active"}, {"numero": 2}, "R2 n'est plus active"),
    (409, {"error": "Confirmation deadline passed"}, {}, "Trop tard"),
    (400, {"error": "Validation failed", "details": [{"path": "nom", "message": "trop long"}]}, {}, "(nom)"),
    (401, {"error": "Unauthorized"}, {}, MESSAGE_API_REFUSE),
    (503, {"error": "Bot API not configured"}, {}, MESSAGE_API_REFUSE),
    (500, {"error": "Internal server error"}, {}, MESSAGE_API_INJOIGNABLE),
    (502, None, {}, MESSAGE_API_INJOIGNABLE),
    (409, {"error": "Something new"}, {}, "409 Something new"),
])
def test_traduction_des_erreurs_de_l_api(statut, corps, contexte, attendu):
    assert attendu in traduire_erreur(statut, corps, contexte)


def test_inscription_envoie_la_fiche_et_copie_le_tournoi_pour_tournament_manager(tmp_path):
    t = tournoi_api()
    apres = tournoi_api(equipes=[{"id": 1, "nom": "Les Tomates"}])
    api = FausseAPI([(200, t), (201, {"tournoi": apres, "equipe": {"id": 1}})], tmp_path)
    L.DELAI_CONFIRMATION_MINUTES = 12
    try:
        tournoi, equipe = lancer(api.inscrire(
            t["id"], nom="  Les Tomates ", capitaine=("111", "Thomas"), pseudo_jeu_capitaine=" Tom_RL ",
            coequipiers=[("222", "Lucas")], maintenant="x"))
    finally:
        L.DELAI_CONFIRMATION_MINUTES = 30
    assert equipe == {"id": 1} and tournoi == apres
    methode, chemin, corps, _ = api.requetes[1]
    assert (methode, chemin) == ("POST", f"/tournaments/{t['id']}/teams")
    assert corps == {"nom": "Les Tomates",
                     "capitaine": {"id": "111", "pseudo": "Thomas", "pseudo_jeu": "Tom_RL"},
                     "coequipiers": [{"id": "222", "pseudo": "Lucas"}], "delai_confirmation_minutes": 12}
    assert json.loads((tmp_path / f"{t['id']}.json").read_text(encoding="utf-8")) == apres


def test_la_fiche_est_verifiee_avant_d_appeler_l_api():
    t = tournoi_api(equipes=[{"id": 1, "nom": "Turbo", "statut": L.INSCRITE, "capitaine_id": "333",
                              "joueurs": [{"id": "333", "pseudo": "Hugo", "statut": L.CONFIRME}]}])
    for kwargs, message in [
        ({"nom": "turbo"}, "déjà pris"),
        ({"coequipiers": [("333", "Hugo")]}, "**Hugo** est déjà dans l'équipe **Turbo**"),
        ({"coequipiers": []}, "exactement 1 coéquipier"),
        ({"pseudo_jeu_capitaine": "  "}, "ne peut pas être vide"),
    ]:
        api = FausseAPI([(200, t)])
        fiche = {"nom": "Les Tomates", "capitaine": ("111", "Thomas"), "pseudo_jeu_capitaine": "Tom",
                 "coequipiers": [("222", "Lucas")], "maintenant": "x"} | kwargs
        with pytest.raises(L.ErreurTournoi, match=message.replace("*", r"\*")):
            lancer(api.inscrire(t["id"], **fiche))
        assert len(api.requetes) == 1  # seulement la lecture du tournoi


def test_erreur_de_l_api_traduite_avec_les_pseudos():
    t = tournoi_api()
    api = FausseAPI([(200, t), (409, {"error": "Player already in a team of this tournament",
                                      "details": {"playerIds": ["222"]}})])
    with pytest.raises(ErreurAPI, match=r"\*\*Lucas\*\* est déjà dans une équipe") as erreur:
        lancer(api.inscrire(t["id"], nom="A", capitaine=("111", "Thomas"), pseudo_jeu_capitaine="T",
                            coequipiers=[("222", "Lucas")], maintenant="x"))
    assert erreur.value.statut == 409


def test_lire_un_tournoi_inconnu_renvoie_none():
    api = FausseAPI([(404, {"error": "Tournament not found"})])
    assert lancer(api.lire("1573714661659123762")) is None
    assert lancer(api.lire("../secret")) is None  # même pas envoyé
    assert len(api.requetes) == 1


def test_api_injoignable():
    api = FausseAPI([aiohttp.ClientConnectionError("refusé"), TimeoutError()])
    for _ in range(2):
        with pytest.raises(ErreurAPI, match="ne répond pas"):
            lancer(api.lire("1573714661659123762"))


def test_modifier_ou_remplacer_un_joueur_est_refuse_clairement_sans_appeler_l_api():
    api = FausseAPI([])
    with pytest.raises(ErreurAPI) as erreur:
        lancer(api.modifier_joueur("1573714661659123762", "1", pseudo="Nouveau"))
    assert str(erreur.value) == MESSAGE_PAS_ENCORE_DANS_L_API
    with pytest.raises(ErreurAPI, match="pas encore"):
        lancer(api.remplacer_joueur("1573714661659123762", "1", ("2", "Remplaçant"), "Pseudo"))
    assert api.requetes == []


def test_modification_ignore_le_recalcul_de_la_liste_d_attente():
    t = tournoi_api(equipes_max=2)
    api = FausseAPI([(200, {"tournoi": t, "promues": [], "changements": [
        {"champ": "equipes_max", "ancienne": 1, "nouvelle": 2},
        {"champ": "liste_attente_max", "ancienne": 4, "nouvelle": 8}]})])
    tournoi, changements, promues = lancer(api.modifier(t["id"], equipes_max=2, titre=" Nouveau "))
    assert changements == [("equipes_max", 1, 2)] and promues == [] and tournoi == t
    assert api.requetes[0][2] == {"titre": "Nouveau", "equipes_max": 2}
    with pytest.raises(L.ErreurTournoi, match="au moins un champ"):
        lancer(api.modifier(t["id"]))


def test_suppression_efface_la_copie_locale(tmp_path):
    t = tournoi_api()
    StockageFichiers(tmp_path).sauvegarder(t)
    api = FausseAPI([(200, t), (404, {"error": "Tournament not found"})], tmp_path)
    assert lancer(api.supprimer(t["id"])) == t
    assert not (tmp_path / f"{t['id']}.json").exists()
    assert lancer(api.supprimer(t["id"])) is None


def test_echeances_recopient_les_tournois_modifies(tmp_path):
    t = tournoi_api()
    resultat = {"tournoi": t, "equipes_expirees": [], "reservations_expirees": [], "promues": [],
                "inscriptions_ouvertes": True}
    api = FausseAPI([(200, [resultat])], tmp_path)
    assert lancer(api.echeances("x")) == [resultat]
    assert api.requetes[0][:2] == ("POST", "/maintenance/tick")
    assert (tmp_path / f"{t['id']}.json").exists()


def test_choix_du_stockage(tmp_path):
    assert isinstance(choisir_stockage("", "", tmp_path), StockageFichiers)
    assert isinstance(choisir_stockage(None, None, tmp_path), StockageFichiers)
    api = choisir_stockage(" http://localhost/ ", CLE, tmp_path)
    assert isinstance(api, StockageAPI) and api.url == "http://localhost"
    with pytest.raises(ValueError, match="BOT_API_KEY"):
        choisir_stockage("http://localhost", "courte", tmp_path)
    with pytest.raises(ValueError, match="http://"):
        choisir_stockage("localhost", CLE, tmp_path)


# --------------------------------------------------------------------------- #
# Avec une vraie API (facultatif)
# --------------------------------------------------------------------------- #

API_URL, API_KEY = os.getenv("API_TEST_URL"), os.getenv("API_TEST_KEY")
avec_api = pytest.mark.skipif(not (API_URL and API_KEY), reason="API_TEST_URL et API_TEST_KEY non définis")

# Ids Discord uniques à chaque lancement (l'API veut des ids de 17 à 20 chiffres).
_ids = itertools.count(int(time.time() * 1000) * 1000)


def snowflake() -> int:
    return next(_ids) + 10 ** 17


class InteractionDiscord(FausseInteraction):
    def __init__(self, client, utilisateur):
        super().__init__(client, utilisateur)
        self.id = snowflake()
        self.guild_id, self.channel_id = client.serveur_id, client.salon_id


@pytest.fixture
def monde_api(tmp_path):
    noms = ["Admin", "Thomas", "Lucas", "Hugo", "Nina", "Leo", "Zoe"]
    joueurs = {n: FauxUtilisateur(snowflake(), n) for n in noms}
    client = FauxClient(tmp_path, joueurs.values())
    client.stockage = StockageAPI(API_URL, API_KEY, dossier_miroir=Path(tmp_path))
    client.serveur_id, client.salon_id = snowflake(), snowflake()
    client.salon.annonce = FauxMessage(snowflake())
    yield client, joueurs
    lancer(client.stockage.fermer())


def _inter(client, joueur):
    return InteractionDiscord(client, joueur)


@avec_api
def test_parcours_complet_avec_la_vraie_api(monde_api, monkeypatch):
    import tests.test_bot_simulation as simulation
    monkeypatch.setattr(simulation, "FausseInteraction", InteractionDiscord)  # utilisé par inscrire / confirmer
    client, j = monde_api
    st = client.stockage

    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl.callback(inter, titre="Tomato API", cashprize="100€", joueurs_par_equipe=2, equipes_max=1,
                               date="6 septembre"))
    tid = str(inter.id)
    assert "créé" in inter.dernier_texte(), inter.dernier_texte()
    t = lancer(st.lire(tid))
    assert t["cashprize"] == "100€" and t["message_id"] == str(client.salon.annonce.id)
    assert (Path(st.miroir.dossier) / f"{tid}.json").exists()  # copie pour tournament_manager

    inter = _inter(client, j["Admin"])
    choix = lancer(autocomplete_tournoi(inter, "tomato"))
    assert [c.value for c in choix] == [tid]

    # Inscription, confirmation, liste d'attente.
    inter = inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    assert "Place obtenue : 1/1" in inter.dernier_texte(), inter.dernier_texte()
    assert "t'a inscrit dans l'équipe **Les Tomates**" in j["Lucas"].mp[-1]
    inter = confirmer(client, j["Lucas"], tid, 1)
    assert "a confirmé sa participation" in inter.editions[-1]["content"]
    inter = inscrire(client, j["Hugo"], [j["Lucas"]], "Doublon", tid)
    assert "**Lucas** est déjà dans l'équipe **Les Tomates**" in inter.dernier_texte()
    inter = inscrire(client, j["Hugo"], [j["Nina"]], "Turbo", tid)
    assert "position 1/4" in inter.dernier_texte(), inter.dernier_texte()
    inter = inscrire(client, j["Leo"], [j["Zoe"]], "Refus", tid)

    # Zoe refuse : l'équipe 3 est annulée.
    inter = _inter(client, j["Zoe"])
    lancer(BoutonRefuser(tid, 3).callback(inter))
    assert "a refusé" in inter.editions[-1]["content"]
    assert "a refusé" in j["Leo"].mp[-1]

    # Le capitaine annule : Turbo monte.
    inter = _inter(client, j["Thomas"])
    lancer(BoutonAnnuler(tid, 1).callback(inter))
    lancer(inter.reponses[-1][1]["view"].confirmer.callback(inter))
    assert "est annulée" in inter.editions[-1]["content"]
    assert "Une place s'est libérée" in j["Hugo"].mp[-1]
    t = lancer(st.lire(tid))
    assert [e["nom"] for e in L.equipes_inscrites(t)] == ["Turbo"]

    # Modification : 2 places, puis réservation de la place libre.
    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_modify.callback(inter, tournoi_id=tid, titre=None, cashprize=None, equipes_max=2))
    assert "Équipes max : 1 → **2**" in inter.dernier_texte(), inter.dernier_texte()
    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_reserve.callback(inter, tournoi_id=tid, capitaine=j["Leo"], nom="Partenaire", duree=60))
    assert "Place `R1` réservée" in inter.dernier_texte(), inter.dernier_texte()
    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_reserve.callback(inter, tournoi_id=tid, capitaine=j["Zoe"], nom="Autre", duree=60))
    assert "Plus aucune place libre" in inter.dernier_texte(), inter.dernier_texte()
    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_unreserve.callback(inter, tournoi_id=tid, reservation=1))
    assert "Réservation `R1` **Partenaire** annulée" in inter.dernier_texte(), inter.dernier_texte()

    # Status, retrait par un admin, tâche de chaque minute (rien à expirer).
    inter = _inter(client, j["Zoe"])
    lancer(tournoi_rl_status.callback(inter, tournoi_id=tid))
    assert "Turbo" in inter.reponses[0][1]["embed"].description
    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_remove_team.callback(inter, tournoi_id=tid, team_id=2))
    assert "retirée du tournoi" in inter.dernier_texte(), inter.dernier_texte()
    assert lancer(expirer_inscriptions(client)) == 0

    # Suppression : l'annonce et la copie locale disparaissent.
    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_remove.callback(inter, tournoi_id=tid))
    lancer(inter.reponses[-1][1]["view"].confirmer.callback(inter))
    assert "annulé et effacé" in inter.editions[-1]["content"]
    assert lancer(st.lire(tid)) is None
    assert not (Path(st.miroir.dossier) / f"{tid}.json").exists()


@avec_api
def test_ouverture_differee_et_place_reservee_avec_la_vraie_api(monde_api, monkeypatch):
    import tests.test_bot_simulation as simulation
    monkeypatch.setattr(simulation, "FausseInteraction", InteractionDiscord)
    client, j = monde_api

    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl.callback(inter, titre="Tomato différé", cashprize="50€", joueurs_par_equipe=2,
                               equipes_max=2, date="7 septembre", delay=60))
    tid = str(inter.id)
    assert "Les inscriptions ouvrent" in inter.dernier_texte(), inter.dernier_texte()

    # Avant l'ouverture : refusé pour tout le monde…
    inter = inscrire(client, j["Thomas"], [j["Lucas"]], "Trop tôt", tid)
    assert "Les inscriptions ouvrent <t:" in inter.dernier_texte(), inter.dernier_texte()

    # … sauf pour le capitaine d'une place réservée.
    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_reserve.callback(inter, tournoi_id=tid, capitaine=j["Leo"], nom="Partenaire", duree=60))
    assert "réservée" in inter.dernier_texte(), inter.dernier_texte()
    assert "Une place t'est réservée" in j["Leo"].mp[-1]
    inter = inscrire(client, j["Leo"], [j["Zoe"]], "Partenaire", tid)
    assert "Place obtenue (place réservée) : 1/2" in inter.dernier_texte(), inter.dernier_texte()
    t = lancer(client.stockage.lire(tid))
    assert t["reservations"][0]["statut"] == L.RESERVATION_UTILISEE and t["equipes"][0]["reservation_id"] == 1

    inter = _inter(client, j["Admin"])
    lancer(tournoi_rl_remove.callback(inter, tournoi_id=tid))
    lancer(inter.reponses[-1][1]["view"].confirmer.callback(inter))
    assert "annulé et effacé" in inter.editions[-1]["content"]


def test_copies_json_rafraichies_au_demarrage(tmp_path):
    t = tournoi_api()
    api = FausseAPI([(200, [{"id": t["id"], "titre": "caca", "date": "6 septembre"}]), (200, t)], tmp_path)
    assert lancer(api.rafraichir_copies("1540386765054148639")) == 1
    assert api.requetes[0][3] == {"serveur_id": "1540386765054148639"}
    assert (tmp_path / f"{t['id']}.json").exists()


def ancien_fichier(tournoi_id: str, serveur_id: str) -> dict:
    """Tournoi au format des anciens fichiers : sans réservations, avec une équipe annulée."""
    joueur = lambda i, statut: {"id": str(i), "pseudo": f"J{i}", "pseudo_jeu": f"J{i}_RL", "statut": statut}  # noqa: E731
    a, b, c = snowflake(), snowflake(), snowflake()
    return {
        "id": tournoi_id, "titre": "Ancien", "cashprize": "30", "joueurs_par_equipe": 2, "equipes_max": 8,
        "liste_attente_max": 32, "date": "21 Novembre 2026", "serveur_id": serveur_id,
        "salon_id": str(snowflake()), "message_id": str(snowflake()), "cree_par": str(snowflake()),
        "cree_le": "2026-11-21T16:00:14+01:00",
        "equipes": [
            {"id": 1, "nom": "Annulée", "capitaine_id": str(a), "statut": "annulee",
             "cree_le": "2026-11-21T16:00:24+01:00", "confirmer_avant": "2026-11-21T16:30:24+01:00",
             "annulee_le": "2026-11-21T16:10:00+01:00", "raison_annulation": "J2 a refusé",
             "joueurs": [joueur(a, "confirme"), joueur(b, "refuse")]},
            {"id": 2, "nom": "Inscrite", "capitaine_id": str(b), "statut": "inscrite",
             "cree_le": "2026-11-21T16:20:00+01:00", "confirmer_avant": "2026-11-21T16:50:00+01:00",
             "annulee_le": None, "raison_annulation": None,
             "joueurs": [joueur(b, "confirme"), joueur(c, "confirme")]},
        ],
    }


def test_import_des_anciens_fichiers(tmp_path, capsys):
    from bot_inscription_manager.importer import importer
    (tmp_path / "1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "2.json").write_text("{}", encoding="utf-8")
    (tmp_path / "3.json").write_text("{abîmé", encoding="utf-8")
    api = FausseAPI([(201, {}), (409, {"error": "Tournament already exists"})])
    assert lancer(importer(api, tmp_path)) == {"importe": 1, "deja": 1, "erreur": 1}
    assert [r[:2] for r in api.requetes] == [("POST", "/import")] * 2
    assert "déjà en base" in capsys.readouterr().out


@avec_api
def test_import_avec_la_vraie_api(tmp_path):
    from bot_inscription_manager.importer import importer
    tid, serveur = str(snowflake()), str(snowflake())
    (tmp_path / f"{tid}.json").write_text(json.dumps(ancien_fichier(tid, serveur)), encoding="utf-8")
    assert lancer(importer(StockageAPI(API_URL, API_KEY), tmp_path)) == {"importe": 1, "deja": 0, "erreur": 0}
    assert lancer(importer(StockageAPI(API_URL, API_KEY), tmp_path)) == {"importe": 0, "deja": 1, "erreur": 0}
    t = lancer(StockageAPI(API_URL, API_KEY).lire(tid))
    assert [(e["id"], e["statut"]) for e in t["equipes"]] == [(1, "annulee"), (2, "inscrite")]
    assert t["equipes"][0]["joueurs"][1]["statut"] == "refuse"
