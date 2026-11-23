"""Places réservées (/tournoi_rl_reserve, /tournoi_rl_unreserve) et ouverture différée (option delay de /tournoi_rl)."""

from datetime import datetime, timedelta

import pytest

from bot_inscription_manager import logique as L
from bot_inscription_manager.commandes import (autocomplete_reservation, tournoi_rl, tournoi_rl_remove,
                                               tournoi_rl_reserve, tournoi_rl_status, tournoi_rl_unreserve)
from bot_inscription_manager.inscription import BoutonInscription, expirer_inscriptions
from tests.test_bot_simulation import (FausseInteraction, bouton_annonce, inscrire, lancer, lancer_sans_blocage,
                                       modifier, monde)  # noqa: F401 (fixture)

T0 = "2026-08-31T18:00:00+02:00"


def plus(minutes, depuis=T0):
    return (L.lire_date(depuis) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def tournoi(equipes_max=2, delai=0):
    return L.nouveau_tournoi(
        tournoi_id="1", titre="caca", cashprize="100", joueurs_par_equipe=2, equipes_max=equipes_max,
        date="6 septembre", serveur_id="1", salon_id="2", cree_par="9", maintenant=T0,
        delai_ouverture_minutes=delai,
    )


def inscrire_l(t, n, maintenant=T0):
    return L.inscrire_equipe(t, nom=f"Team {n}", capitaine=(f"c{n}", f"C{n}"), pseudo_jeu_capitaine=f"C{n}_RL",
                             coequipiers=[(f"j{n}", f"J{n}")], maintenant=maintenant)


def reserver(t, n, duree=60, maintenant=T0):
    return L.reserver_place(t, nom=f"Partenaire {n}", capitaine=(f"c{n}", f"C{n}"), duree_minutes=duree,
                            cree_par="9", maintenant=maintenant)


# --------------------------------------------------------------------------- #
# Logique
# --------------------------------------------------------------------------- #

def test_sans_delai_les_inscriptions_sont_ouvertes_tout_de_suite():
    t = tournoi()
    assert t["ouverture_inscriptions"] is None and t["reservations"] == []
    assert L.inscriptions_ouvertes(t, T0)


def test_anciens_tournois_sans_les_nouveaux_champs_restent_ouverts():
    t = tournoi()
    del t["ouverture_inscriptions"], t["reservations"]
    assert L.inscriptions_ouvertes(t, T0) and L.places_libres(t) == 2
    assert inscrire_l(t, 1)["statut"] == L.INSCRITE


def test_inscription_refusee_avant_l_ouverture():
    t = tournoi(delai=30)
    assert t["ouverture_inscriptions"] == plus(30)
    with pytest.raises(L.ErreurTournoi, match="Les inscriptions ouvrent <t:"):
        L.verifier_peut_s_inscrire(t, "c1", plus(29))
    with pytest.raises(L.ErreurTournoi, match="ouvrent"):
        inscrire_l(t, 1, plus(29))
    assert inscrire_l(t, 1, plus(30))["statut"] == L.INSCRITE


def test_delai_d_ouverture_invalide():
    with pytest.raises(L.ErreurTournoi, match="entre 0 et"):
        tournoi(delai=L.DELAI_OUVERTURE_MAX_MINUTES + 1)


def test_ouvrir_inscriptions_une_seule_fois():
    t = tournoi(delai=10)
    assert not L.ouvrir_inscriptions(t, plus(9))
    assert L.ouvrir_inscriptions(t, plus(10))
    assert t["ouverture_inscriptions"] is None
    assert not L.ouvrir_inscriptions(t, plus(11))


def test_une_reservation_bloque_une_place_pour_les_autres():
    t = tournoi(equipes_max=2)
    r = reserver(t, 1)
    assert r["id"] == 1 and r["statut"] == L.RESERVATION_ACTIVE and r["expire_le"] == plus(60)
    assert L.places_libres(t) == 1
    assert inscrire_l(t, 2)["statut"] == L.INSCRITE
    assert inscrire_l(t, 3)["statut"] == L.LISTE_ATTENTE  # la place réservée n'est pas donnée


def test_le_capitaine_reserve_prend_sa_place_meme_avant_l_ouverture_et_meme_complet():
    t = tournoi(equipes_max=1, delai=120)
    reserver(t, 1)
    L.verifier_peut_s_inscrire(t, "c1", T0)  # pas d'erreur
    with pytest.raises(L.ErreurTournoi, match="ouvrent"):
        L.verifier_peut_s_inscrire(t, "c2", T0)
    e = inscrire_l(t, 1)
    assert e["statut"] == L.INSCRITE and e["reservation_id"] == 1
    r = L.trouver_reservation(t, 1)
    assert (r["statut"], r["equipe_id"], r["terminee_le"]) == (L.RESERVATION_UTILISEE, e["id"], T0)
    assert L.reservations_actives(t) == [] and L.places_libres(t) == 0


def test_reservation_refusee():
    t = tournoi(equipes_max=2)
    inscrire_l(t, 1)
    with pytest.raises(L.ErreurTournoi, match="C1.*déjà dans l'équipe"):
        reserver(t, 1)
    reserver(t, 2)
    with pytest.raises(L.ErreurTournoi, match="déjà une place réservée"):
        reserver(t, 2)
    with pytest.raises(L.ErreurTournoi, match="Plus aucune place libre"):
        reserver(t, 3)
    with pytest.raises(L.ErreurTournoi, match="vide"):
        L.reserver_place(t, nom="  ", capitaine=("x", "X"), duree_minutes=5, cree_par="9", maintenant=T0)
    with pytest.raises(L.ErreurTournoi, match="durée"):
        L.reserver_place(t, nom="A", capitaine=("x", "X"), duree_minutes=0, cree_par="9", maintenant=T0)


def test_annuler_une_reservation_rend_la_place_a_la_liste_d_attente():
    t = tournoi(equipes_max=1)
    reserver(t, 1)
    inscrire_l(t, 2)  # liste d'attente
    r, promues = L.annuler_reservation(t, 1, plus(5))
    assert r["statut"] == L.RESERVATION_ANNULEE and r["terminee_le"] == plus(5)
    assert [e["nom"] for e in promues] == ["Team 2"]
    with pytest.raises(L.ErreurTournoi, match="n'est plus active"):
        L.annuler_reservation(t, 1, plus(5))
    with pytest.raises(L.ErreurTournoi, match="Aucune réservation R9"):
        L.annuler_reservation(t, 9, plus(5))


def test_reservation_expiree_rendue_et_inutilisable():
    t = tournoi(equipes_max=1)
    reserver(t, 1, duree=60)
    inscrire_l(t, 2)  # liste d'attente
    assert L.expirer_reservations(t, plus(59)) == ([], [])
    expirees, promues = L.expirer_reservations(t, plus(60))
    assert [r["id"] for r in expirees] == [1] and expirees[0]["statut"] == L.RESERVATION_EXPIREE
    assert [e["nom"] for e in promues] == ["Team 2"]
    # Le capitaine n'a plus de place réservée : il passe par le circuit normal.
    assert inscrire_l(t, 1, plus(61))["statut"] == L.LISTE_ATTENTE


def test_equipe_reservee_annulee_rend_la_place_a_tout_le_monde():
    t = tournoi(equipes_max=1)
    reserver(t, 1)
    e = inscrire_l(t, 1)
    inscrire_l(t, 2)
    _, promues = L.annuler_equipe(t, e["id"], "test", T0)
    assert [p["nom"] for p in promues] == ["Team 2"]


def test_equipes_max_ne_descend_pas_sous_inscrites_plus_reservees():
    t = tournoi(equipes_max=3)
    inscrire_l(t, 1)
    reserver(t, 2)
    with pytest.raises(L.ErreurTournoi, match="1 équipes sont déjà inscrites et 1 place.*en dessous de 2"):
        L.modifier_tournoi(t, equipes_max=1)
    changements, _ = L.modifier_tournoi(t, equipes_max=2)
    assert changements == [("equipes_max", 3, 2)] and L.places_libres(t) == 0


# --------------------------------------------------------------------------- #
# Commandes et boutons (faux objets Discord)
# --------------------------------------------------------------------------- #

def creer(client, admin, equipes_max=1, delay=0):
    inter = FausseInteraction(client, admin)
    lancer(tournoi_rl.callback(inter, titre="caca", cashprize="100", joueurs_par_equipe=2,
                               equipes_max=equipes_max, date="6 septembre", delay=delay))
    return str(inter.id), inter


def reserver_cmd(client, admin, tid, capitaine, nom="Partenaire", duree=120):
    inter = FausseInteraction(client, admin)
    lancer_sans_blocage(tournoi_rl_reserve.callback(inter, tournoi_id=tid, capitaine=capitaine, nom=nom, duree=duree))
    return inter


def test_delay_puis_reservation_puis_ouverture(monde):
    client, j = monde
    tid, inter = creer(client, j["Admin"], equipes_max=2, delay=60)
    assert "Les inscriptions ouvrent <t:" in inter.dernier_texte() and "/tournoi_rl_reserve" in inter.dernier_texte()
    annonce = client.salon.envoyes[0][1]["embed"]
    assert "Les inscriptions ouvrent <t:" in annonce.description

    # Avant l'ouverture : un joueur normal est refusé.
    inter = FausseInteraction(client, j["Hugo"])
    lancer(BoutonInscription(tid).callback(inter))
    assert inter.modal is None and "Les inscriptions ouvrent" in inter.dernier_texte()

    # L'admin réserve une place pour Thomas : MP + annonce mise à jour.
    inter = reserver_cmd(client, j["Admin"], tid, j["Thomas"], nom="Partenaire Tomato")
    assert "Place `R1` réservée pour **Partenaire Tomato**" in inter.dernier_texte()
    assert "Places libres restantes : **1**" in inter.dernier_texte()
    assert "Le capitaine a été prévenu en MP" in inter.dernier_texte()
    assert "Une place t'est réservée pour l'équipe **Partenaire Tomato**" in j["Thomas"].mp[-1]
    assert "https://discord.com/channels/1/2/777" in j["Thomas"].mp[-1]
    assert client.salon.annonce.editions[-1]["embed"].fields[2].value == "0/2 (+1 réservée)"

    # Status : la réservation et l'heure d'ouverture apparaissent.
    inter = FausseInteraction(client, j["Nina"])
    lancer(tournoi_rl_status.callback(inter, tid))
    status = inter.reponses[-1][1]["embed"].description
    assert "🔒 Places réservées (1)" in status and "`R1` **Partenaire Tomato** — capitaine Thomas" in status
    assert "🕒 Inscriptions ouvertes <t:" in status

    # Thomas s'inscrit avant l'ouverture, sur sa place réservée.
    inter = inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    assert "Place obtenue (place réservée) : 1/2" in inter.dernier_texte()
    t = client.stockage.charger(tid)
    assert t["reservations"][0]["statut"] == L.RESERVATION_UTILISEE
    assert L.trouver_equipe(t, 1)["reservation_id"] == 1

    # L'heure d'ouverture passe : la boucle met l'annonce à jour une seule fois.
    t["ouverture_inscriptions"] = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat()
    client.stockage.sauvegarder(t)
    editions = len(client.salon.annonce.editions)
    lancer(expirer_inscriptions(client))
    assert len(client.salon.annonce.editions) == editions + 1
    assert "Clique sur **S'inscrire**" in client.salon.annonce.editions[-1]["embed"].description
    lancer(expirer_inscriptions(client))
    assert len(client.salon.annonce.editions) == editions + 1

    inter = inscrire(client, j["Hugo"], [j["Nina"]], "Turbo", tid)
    assert "Place obtenue : 2/2" in inter.dernier_texte()


def test_bouton_reste_cliquable_si_complet_avec_une_place_reservee(monde):
    client, j = monde
    tid, _ = creer(client, j["Admin"], equipes_max=1)
    reserver_cmd(client, j["Admin"], tid, j["Thomas"])
    t = client.stockage.charger(tid)
    t["liste_attente_max"] = 0  # complet pour tout le monde sauf Thomas
    client.stockage.sauvegarder(t)
    modifier(client, j["Admin"], tid, titre="Plein")  # met l'annonce à jour
    assert not bouton_annonce(client).disabled

    inter = FausseInteraction(client, j["Hugo"])
    lancer(BoutonInscription(tid).callback(inter))
    assert inter.modal is None and "complet" in inter.dernier_texte()
    inter = inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    assert "Place obtenue (place réservée) : 1/1" in inter.dernier_texte()


def test_reservation_refusee_par_la_commande(monde):
    client, j = monde
    tid, _ = creer(client, j["Admin"], equipes_max=1)
    assert "est un bot" in reserver_cmd(client, j["Admin"], tid, j["Robot"]).dernier_texte()
    assert "Aucun tournoi" in reserver_cmd(client, j["Admin"], "123", j["Thomas"]).dernier_texte()
    reserver_cmd(client, j["Admin"], tid, j["Thomas"])
    assert "Plus aucune place libre" in reserver_cmd(client, j["Admin"], tid, j["Hugo"]).dernier_texte()
    assert not client.stockage.verrou(tid).locked()


def test_reservation_avec_mp_fermes(monde):
    client, j = monde
    tid, _ = creer(client, j["Admin"], equipes_max=1)
    inter = reserver_cmd(client, j["Admin"], tid, j["Ferme"])
    assert "Impossible d'envoyer un MP au capitaine" in inter.dernier_texte()


def test_unreserve_rend_la_place_et_promeut(monde):
    client, j = monde
    tid, _ = creer(client, j["Admin"], equipes_max=1)
    reserver_cmd(client, j["Admin"], tid, j["Thomas"], nom="Invités")
    inscrire(client, j["Hugo"], [j["Nina"]], "Turbo", tid)  # liste d'attente

    choix = FausseInteraction(client, j["Admin"])
    choix.namespace.id = tid
    assert [c.name for c in lancer(autocomplete_reservation(choix, ""))] == ["R1 Invités (capitaine Thomas)"]

    inter = FausseInteraction(client, j["Admin"])
    lancer_sans_blocage(tournoi_rl_unreserve.callback(inter, tournoi_id=tid, reservation=1))
    assert "Réservation `R1` **Invités** annulée" in inter.dernier_texte()
    assert "`#1` **Turbo**" in inter.dernier_texte()
    assert "a été annulée par un admin" in j["Thomas"].mp[-1]
    assert "Une place s'est libérée" in j["Hugo"].mp[-1]
    assert L.trouver_equipe(client.stockage.charger(tid), 1)["statut"] == L.INSCRITE

    inter = FausseInteraction(client, j["Admin"])
    lancer_sans_blocage(tournoi_rl_unreserve.callback(inter, tournoi_id=tid, reservation=1))
    assert "n'est plus active" in inter.dernier_texte()
    assert lancer(autocomplete_reservation(choix, "")) == []


def test_reservation_expiree_par_la_boucle(monde):
    client, j = monde
    tid, _ = creer(client, j["Admin"], equipes_max=1)
    reserver_cmd(client, j["Admin"], tid, j["Thomas"], nom="Invités")
    inscrire(client, j["Hugo"], [j["Nina"]], "Turbo", tid)  # liste d'attente
    assert lancer(expirer_inscriptions(client)) == 0
    assert client.stockage.charger(tid)["reservations"][0]["statut"] == L.RESERVATION_ACTIVE

    t = client.stockage.charger(tid)
    t["reservations"][0]["expire_le"] = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat()
    client.stockage.sauvegarder(t)
    assert lancer(expirer_inscriptions(client)) == 0  # aucune équipe désinscrite
    t = client.stockage.charger(tid)
    assert t["reservations"][0]["statut"] == L.RESERVATION_EXPIREE
    assert L.trouver_equipe(t, 1)["statut"] == L.INSCRITE
    assert "a expiré" in j["Thomas"].mp[-1]
    assert "Une place s'est libérée" in j["Hugo"].mp[-1]
    assert client.salon.annonce.editions[-1]["embed"].fields[2].value == "1/1"


def test_suppression_du_tournoi_previent_les_capitaines_reserves(monde):
    client, j = monde
    tid, _ = creer(client, j["Admin"], equipes_max=2)
    reserver_cmd(client, j["Admin"], tid, j["Thomas"], nom="Invités")
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_remove.callback(inter, tid))
    vue = inter.reponses[-1][1]["view"]
    lancer(vue.confirmer.callback(FausseInteraction(client, j["Admin"])))
    assert "La place réservée pour **Invités** est annulée" in j["Thomas"].mp[-1]
