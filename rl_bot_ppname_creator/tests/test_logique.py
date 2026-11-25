import json

import pytest

from bot_inscription_manager import logique as L
from bot_inscription_manager.stockage import Stockage

T0 = "2026-08-31T18:00:00"


def tournoi(joueurs_par_equipe=2, equipes_max=2):
    return L.nouveau_tournoi(
        tournoi_id="1544015944353976341", titre="caca", cashprize="100",
        joueurs_par_equipe=joueurs_par_equipe, equipes_max=equipes_max, date="6 septembre",
        serveur_id="1", salon_id="2", cree_par="9", maintenant=T0,
    )


def inscrire(t, n, nom=None):
    """Inscrit l'équipe n : capitaine c{n}, coéquipiers j{n}a, j{n}b…"""
    coeq = [(f"j{n}{x}", f"J{n}{x}") for x in "ab"[: t["joueurs_par_equipe"] - 1]]
    return L.inscrire_equipe(t, nom=nom or f"Team {n}", capitaine=(f"c{n}", f"C{n}"), pseudo_jeu_capitaine=f"C{n}_RL",
                             coequipiers=coeq, maintenant=T0)


def test_liste_attente_vaut_4_fois_le_nombre_d_equipes():
    assert tournoi(equipes_max=8)["liste_attente_max"] == 32


def test_place_attribuee_a_l_inscription_du_capitaine():
    t = tournoi()
    e = inscrire(t, 1)
    assert e["statut"] == L.INSCRITE
    assert e["joueurs"][0] == {"id": "c1", "pseudo": "C1", "pseudo_jeu": "C1_RL", "statut": L.CONFIRME}
    assert [j["pseudo"] for j in L.joueurs_en_attente(e)] == ["J1a"]
    assert not L.equipe_confirmee(e)


def test_places_puis_liste_attente_puis_complet():
    t = tournoi(equipes_max=1)  # 1 place, 4 en liste d'attente
    assert inscrire(t, 1)["statut"] == L.INSCRITE
    for n in range(2, 6):
        assert inscrire(t, n)["statut"] == L.LISTE_ATTENTE
    assert L.est_complet(t)
    with pytest.raises(L.ErreurTournoi, match="complet"):
        inscrire(t, 6)
    with pytest.raises(L.ErreurTournoi, match="complet"):
        L.verifier_peut_s_inscrire(t, "c6", T0)
    assert L.position_attente(t, L.trouver_equipe(t, 3)) == 2


def test_un_joueur_ne_peut_etre_que_dans_une_equipe():
    t = tournoi()
    inscrire(t, 1)
    with pytest.raises(L.ErreurTournoi, match="déjà dans l'équipe"):
        L.verifier_peut_s_inscrire(t, "j1a", T0)
    with pytest.raises(L.ErreurTournoi, match="J1a.*déjà dans l'équipe"):
        L.inscrire_equipe(t, nom="Autre", capitaine=("c2", "C2"), pseudo_jeu_capitaine="x", coequipiers=[("j1a", "J1a")], maintenant=T0)


@pytest.mark.parametrize("coequipiers, message", [
    ([("c1", "C1")], "toi-même"),
    ([], "exactement 1"),
    ([("x", "X"), ("y", "Y")], "exactement 1"),
])
def test_coequipiers_invalides(coequipiers, message):
    t = tournoi()
    with pytest.raises(L.ErreurTournoi, match=message):
        L.inscrire_equipe(t, nom="A", capitaine=("c1", "C1"), pseudo_jeu_capitaine="x", coequipiers=coequipiers, maintenant=T0)


def test_doublon_de_joueur():
    t = tournoi(joueurs_par_equipe=3)
    with pytest.raises(L.ErreurTournoi, match="deux fois"):
        L.inscrire_equipe(t, nom="A", capitaine=("c1", "C1"), pseudo_jeu_capitaine="x",
                          coequipiers=[("x", "X"), ("x", "X")], maintenant=T0)


def test_nom_d_equipe_unique_et_non_vide():
    t = tournoi()
    inscrire(t, 1, nom="Les Tomates")
    with pytest.raises(L.ErreurTournoi, match="déjà pris"):
        inscrire(t, 2, nom="les tomates")
    with pytest.raises(L.ErreurTournoi, match="vide"):
        inscrire(t, 2, nom="   ")


def test_1v1_confirme_directement():
    t = tournoi(joueurs_par_equipe=1)
    e = inscrire(t, 1)
    assert L.equipe_confirmee(e)


def test_validation_des_coequipiers():
    t = tournoi(joueurs_par_equipe=3)
    e = inscrire(t, 1)
    L.confirmer_joueur(t, e["id"], "j1a", "  Lucas_RL*  ", T0)
    assert not L.equipe_confirmee(e)
    L.confirmer_joueur(t, e["id"], "j1b", "Hugo", T0)
    assert L.equipe_confirmee(e)
    with pytest.raises(L.ErreurTournoi, match="déjà confirmé"):
        L.confirmer_joueur(t, e["id"], "j1b", "Hugo", T0)
    with pytest.raises(L.ErreurTournoi, match="ne te concerne pas"):
        L.confirmer_joueur(t, e["id"], "intrus", "x", T0)


def test_pseudo_jeu_garde_tel_quel():
    t = tournoi()
    e = inscrire(t, 1)
    L.confirmer_joueur(t, e["id"], "j1a", "  Lucas_RL *Pro*  ", T0)
    # Seuls les espaces autour sont enlevés : casse, _ et * sont conservés.
    assert L.joueur_dans_equipe(e, "j1a")["pseudo_jeu"] == "Lucas_RL *Pro*"


@pytest.mark.parametrize("pseudo, message", [("   ", "vide"), ("x" * 33, "maximum 32")])
def test_pseudo_jeu_invalide(pseudo, message):
    t = tournoi()
    e = inscrire(t, 1)
    with pytest.raises(L.ErreurTournoi, match=message):
        L.confirmer_joueur(t, e["id"], "j1a", pseudo, T0)
    assert L.joueur_dans_equipe(e, "j1a")["statut"] == L.EN_ATTENTE
    with pytest.raises(L.ErreurTournoi, match=message):
        L.inscrire_equipe(t, nom="B", capitaine=("c2", "C2"), pseudo_jeu_capitaine=pseudo,
                          coequipiers=[("j2a", "J2a")], maintenant=T0)


def test_refus_annule_l_equipe_libere_les_joueurs_et_promeut():
    t = tournoi(equipes_max=1)
    e1 = inscrire(t, 1)
    e2 = inscrire(t, 2)
    e3 = inscrire(t, 3)
    equipe, promues = L.refuser_joueur(t, e1["id"], "j1a", T0)
    assert equipe["statut"] == L.ANNULEE
    assert equipe["raison_annulation"] == "J1a a refusé"
    assert promues == [e2] and e2["statut"] == L.INSCRITE
    assert e3["statut"] == L.LISTE_ATTENTE and L.position_attente(t, e3) == 1
    # Les joueurs de l'équipe annulée peuvent se réinscrire
    L.verifier_peut_s_inscrire(t, "c1", T0)
    with pytest.raises(L.ErreurTournoi, match="annulée"):
        L.confirmer_joueur(t, e1["id"], "c1", "x", T0)


def test_annulation_admin_equipe_en_liste_attente_ne_promeut_personne():
    t = tournoi(equipes_max=1)
    inscrire(t, 1)
    e2 = inscrire(t, 2)
    e3 = inscrire(t, 3)
    _, promues = L.annuler_equipe(t, e2["id"], "retirée par un admin", T0)
    assert promues == []
    assert L.position_attente(t, e3) == 1
    with pytest.raises(L.ErreurTournoi, match="déjà annulée"):
        L.annuler_equipe(t, e2["id"], "x", T0)
    with pytest.raises(L.ErreurTournoi, match="Aucune équipe #99"):
        L.annuler_equipe(t, 99, "x", T0)


def test_ids_d_equipe_jamais_reutilises():
    t = tournoi()
    e1 = inscrire(t, 1)
    L.annuler_equipe(t, e1["id"], "x", T0)
    assert inscrire(t, 2)["id"] == 2


def test_stockage_aller_retour(tmp_path):
    s = Stockage(tmp_path)
    t = tournoi()
    inscrire(t, 1, nom="Équipe é")
    s.sauvegarder(t)
    assert s.charger(t["id"]) == t
    assert "Équipe é" in (tmp_path / f"{t['id']}.json").read_text(encoding="utf-8")
    assert not list(tmp_path.glob("*.tmp"))
    assert s.charger("999") is None
    assert s.charger("../secret") is None
    assert [x["id"] for x in s.tous("1")] == [t["id"]]
    assert s.tous("autre_serveur") == []
    assert s.effacer(t["id"]) is True
    assert s.charger(t["id"]) is None and s.effacer(t["id"]) is False
    assert s.effacer("../secret") is False


def test_stockage_ignore_fichier_abime(tmp_path):
    s = Stockage(tmp_path)
    (tmp_path / "123.json").write_text("{pas du json", encoding="utf-8")
    s.sauvegarder(tournoi())
    assert len(s.tous()) == 1
    json.loads((tmp_path / "1544015944353976341.json").read_text(encoding="utf-8"))


def test_capitaine_lisible_dans_le_json():
    t = tournoi()
    e = inscrire(t, 1)
    assert e["capitaine"] == {"pseudo": "C1", "pseudo_jeu": "C1_RL"}
    assert list(e).index("capitaine") == list(e).index("capitaine_id") + 1


def test_ancien_fichier_sans_capitaine_est_complete(tmp_path):
    s = Stockage(tmp_path)
    t = tournoi()
    e = inscrire(t, 1)
    del e["capitaine"]
    s.sauvegarder(t)
    charge = s.charger(t["id"])
    assert charge["equipes"][0]["capitaine"] == {"pseudo": "C1", "pseudo_jeu": "C1_RL"}
    assert list(charge["equipes"][0]).index("capitaine") == list(e).index("capitaine_id") + 1
    assert s.tous()[0]["equipes"][0]["capitaine"]["pseudo"] == "C1"
    assert L.completer_capitaines(charge) is False


# --------------------------------------------------------------------------- #
# Modification (/tournoi_rl_modify)
# --------------------------------------------------------------------------- #

def copie(t):
    return json.loads(json.dumps(t))


def test_modifier_titre_et_cashprize():
    t = tournoi()
    changements, promues = L.modifier_tournoi(t, titre="  Nouveau titre  ", cashprize=" 200€ ")
    assert changements == [("titre", "caca", "Nouveau titre"), ("cashprize", "100", "200€")]
    assert promues == []
    assert t["titre"] == "Nouveau titre" and t["cashprize"] == "200€"
    assert t["equipes_max"] == 2 and t["liste_attente_max"] == 8


def test_modifier_sans_champ():
    with pytest.raises(L.ErreurTournoi, match="au moins un champ"):
        L.modifier_tournoi(tournoi())


def test_modifier_avec_les_memes_valeurs_ne_change_rien():
    t = tournoi()
    avant = copie(t)
    assert L.modifier_tournoi(t, titre=" caca ", cashprize="100", equipes_max=2) == ([], [])
    assert t == avant


def test_modifier_seulement_ce_qui_change():
    t = tournoi()
    changements, _ = L.modifier_tournoi(t, titre="caca", cashprize="500")
    assert changements == [("cashprize", "100", "500")]


@pytest.mark.parametrize("champs, message", [
    ({"titre": "   "}, "titre ne peut pas être vide"),
    ({"cashprize": ""}, "cashprize ne peut pas être vide"),
    ({"titre": "x" * 101}, "maximum 100"),
    ({"equipes_max": 0}, "entre 1 et 128"),
    ({"equipes_max": 129}, "entre 1 et 128"),
    # Le titre est valide mais equipes_max non : rien ne doit être modifié.
    ({"titre": "Valide", "equipes_max": 0}, "entre 1 et 128"),
])
def test_modifier_valeurs_invalides_laisse_le_tournoi_intact(champs, message):
    t = tournoi()
    avant = copie(t)
    with pytest.raises(L.ErreurTournoi, match=message):
        L.modifier_tournoi(t, **champs)
    assert t == avant


def test_augmenter_equipes_max_promeut_la_liste_d_attente_dans_l_ordre():
    t = tournoi(equipes_max=1)
    for n in range(1, 6):
        inscrire(t, n)
    assert L.est_complet(t)
    changements, promues = L.modifier_tournoi(t, equipes_max=3)
    assert changements == [("equipes_max", 1, 3)]
    assert [e["id"] for e in promues] == [2, 3]
    assert [e["id"] for e in L.equipes_inscrites(t)] == [1, 2, 3]
    assert [e["id"] for e in L.liste_attente(t)] == [4, 5]
    assert t["liste_attente_max"] == 12
    assert not L.est_complet(t)
    assert inscrire(t, 6)["statut"] == L.LISTE_ATTENTE


def test_augmenter_equipes_max_sans_liste_d_attente():
    t = tournoi(equipes_max=2)
    inscrire(t, 1)
    _, promues = L.modifier_tournoi(t, equipes_max=4)
    assert promues == [] and L.places_libres(t) == 3


def test_baisser_equipes_max_sous_le_nombre_d_inscrites_est_refuse():
    t = tournoi(equipes_max=3)
    for n in range(1, 4):
        inscrire(t, n)
    avant = copie(t)
    with pytest.raises(L.ErreurTournoi, match=r"3 équipes sont déjà inscrites.*Retire d'abord 1 équipe"):
        L.modifier_tournoi(t, titre="Autre", equipes_max=2)
    assert t == avant


def test_baisser_equipes_max_au_nombre_d_inscrites():
    t = tournoi(equipes_max=4)
    for n in range(1, 3):
        inscrire(t, n)
    _, promues = L.modifier_tournoi(t, equipes_max=2)
    assert promues == [] and t["liste_attente_max"] == 8
    assert inscrire(t, 3)["statut"] == L.LISTE_ATTENTE


def test_les_equipes_annulees_ne_comptent_pas():
    t = tournoi(equipes_max=3)
    for n in range(1, 4):
        inscrire(t, n)
    L.annuler_equipe(t, 3, "x", T0)
    L.modifier_tournoi(t, equipes_max=2)
    assert t["equipes_max"] == 2


def test_avec_une_liste_d_attente_toute_baisse_est_refusee():
    """Liste d'attente non vide => toutes les places sont prises => baisser retirerait une inscrite."""
    t = tournoi(equipes_max=2)
    for n in range(1, 5):
        inscrire(t, n)
    with pytest.raises(L.ErreurTournoi, match="2 équipes sont déjà inscrites"):
        L.modifier_tournoi(t, equipes_max=1)


def test_liste_d_attente_trop_longue_pour_le_nouveau_maximum():
    """Fichier incohérent (places libres ET liste d'attente, ex. JSON modifié à la main) :
    la liste d'attente ne doit jamais dépasser son maximum."""
    t = tournoi(equipes_max=3)
    for n in range(1, 13):
        inscrire(t, n)  # 3 inscrites, 9 en attente
    for e in L.equipes_inscrites(t)[:2]:
        e["statut"] = L.ANNULEE  # 1 inscrite, 9 en attente, sans promotion
    avant = copie(t)
    # equipes_max=1 : aucune place libre, 9 en attente > 4 max -> refusé.
    with pytest.raises(L.ErreurTournoi, match=r"liste d'attente compte 9 équipes.*maximum serait 4.*Retire d'abord 5"):
        L.modifier_tournoi(t, equipes_max=1)
    assert t == avant
    # equipes_max=2 : 1 place libre -> 1 promue, 8 en attente <= 8 max -> accepté.
    _, promues = L.modifier_tournoi(t, equipes_max=2)
    assert [e["id"] for e in promues] == [4]
    assert len(L.liste_attente(t)) == 8 and t["liste_attente_max"] == 8


# --------------------------------------------------------------------------- #
# Délai de confirmation (30 minutes)
# --------------------------------------------------------------------------- #

def apres(minutes):
    """T0 + n minutes, au format ISO."""
    from datetime import timedelta
    return (L.lire_date(T0) + timedelta(minutes=minutes)).isoformat()


def test_delai_de_30_minutes_a_l_inscription():
    t = tournoi()
    e = inscrire(t, 1)
    assert L.lire_date(e["confirmer_avant"]) == L.lire_date(apres(30))
    assert inscrire(tournoi(joueurs_par_equipe=1), 1)["confirmer_avant"] is None  # 1v1 : rien à confirmer


def test_equipe_desinscrite_apres_30_minutes_et_liste_attente_avance():
    t = tournoi(equipes_max=1)
    e1 = inscrire(t, 1)
    e2 = inscrire(t, 2)  # liste d'attente
    L.confirmer_joueur(t, e2["id"], "j2a", "J2a_RL", apres(5))
    assert L.expirer_equipes(t, apres(29)) == ([], [])
    expirees, promues = L.expirer_equipes(t, apres(30))
    assert expirees == [e1] and e1["statut"] == L.ANNULEE
    assert e1["raison_annulation"] == "délai de confirmation dépassé (J1a)"
    assert promues == [e2] and e2["statut"] == L.INSCRITE
    assert L.expirer_equipes(t, apres(60)) == ([], [])  # e2 est confirmée : jamais désinscrite
    L.verifier_peut_s_inscrire(t, "c1", T0)  # les joueurs de e1 sont libres


def test_confirmation_refusee_apres_le_delai():
    t = tournoi()
    e = inscrire(t, 1)
    with pytest.raises(L.ErreurTournoi, match="Trop tard"):
        L.verifier_peut_confirmer(t, e["id"], "j1a", apres(31))
    with pytest.raises(L.ErreurTournoi, match="Trop tard"):
        L.confirmer_joueur(t, e["id"], "j1a", "x", apres(31))
    L.confirmer_joueur(t, e["id"], "j1a", "x", apres(29))
    assert L.equipe_confirmee(e)


def test_equipe_expiree_en_liste_attente_n_est_jamais_promue():
    t = tournoi(equipes_max=1)
    e1 = inscrire(t, 1)
    e2 = inscrire(t, 2)  # 1re en liste d'attente, ne confirme pas
    e3 = inscrire(t, 3)  # 2e en liste d'attente, confirme
    L.confirmer_joueur(t, e3["id"], "j3a", "x", apres(1))
    expirees, promues = L.expirer_equipes(t, apres(45))
    assert expirees == [e1, e2]
    assert promues == [e3]


def test_anciennes_equipes_sans_delai_et_dates_avec_ou_sans_fuseau():
    t = tournoi()
    e = inscrire(t, 1)
    e["confirmer_avant"] = None  # équipe inscrite avant l'ajout du délai
    assert L.expirer_equipes(t, apres(10_000)) == ([], [])
    e["confirmer_avant"] = L.lire_date(apres(30)).isoformat()  # avec fuseau horaire
    assert not L.delai_depasse(e, apres(29)) and L.delai_depasse(e, apres(30))


def test_changer_le_delai_ne_touche_que_les_nouvelles_equipes(monkeypatch):
    t = tournoi(equipes_max=4)
    e1 = inscrire(t, 1)
    monkeypatch.setattr(L, "DELAI_CONFIRMATION_MINUTES", 5)
    e2 = inscrire(t, 2)
    assert (L.delai_minutes(e1), L.delai_minutes(e2)) == (30, 5)
    with pytest.raises(L.ErreurTournoi, match="délai de 5 minutes"):
        L.verifier_peut_confirmer(t, e2["id"], "j2a", apres(6))
    expirees, _ = L.expirer_equipes(t, apres(6))
    assert expirees == [e2]


def test_modifier_joueur_change_les_pseudos_du_capitaine():
    t = tournoi()
    e = inscrire(t, 1)
    equipe, joueur, changements = L.modifier_joueur(t, "c1", pseudo="  Capi  ", pseudo_jeu=" Capi_RL ")
    assert equipe is e and joueur["pseudo"] == "Capi" and joueur["pseudo_jeu"] == "Capi_RL"
    assert changements == [("pseudo", "C1", "Capi"), ("pseudo_jeu", "C1_RL", "Capi_RL")]
    # La copie « capitaine » de l'équipe suit aussi.
    assert e["capitaine"] == {"pseudo": "Capi", "pseudo_jeu": "Capi_RL"}


def test_modifier_joueur_coequipier_et_rien_a_changer():
    t = tournoi()
    e = inscrire(t, 1)
    L.confirmer_joueur(t, e["id"], "j1a", "Lucas", T0)
    _, joueur, changements = L.modifier_joueur(t, "j1a", pseudo_jeu="Lucas_Pro")
    assert changements == [("pseudo_jeu", "Lucas", "Lucas_Pro")] and joueur["pseudo_jeu"] == "Lucas_Pro"
    assert e["capitaine"]["pseudo_jeu"] == "C1_RL"
    assert L.modifier_joueur(t, "j1a", pseudo_jeu="Lucas_Pro")[2] == []


def test_modifier_joueur_refuse():
    t = tournoi()
    e = inscrire(t, 1)
    with pytest.raises(L.ErreurTournoi, match="au moins un champ"):
        L.modifier_joueur(t, "c1")
    with pytest.raises(L.ErreurTournoi, match="aucune équipe"):
        L.modifier_joueur(t, "intrus", pseudo="X")
    with pytest.raises(L.ErreurTournoi, match="pas encore confirmé"):
        L.modifier_joueur(t, "j1a", pseudo_jeu="X")
    with pytest.raises(L.ErreurTournoi, match="maximum 32"):
        L.modifier_joueur(t, "c1", pseudo="ok", pseudo_jeu="x" * 33)
    assert L.joueur_dans_equipe(e, "c1")["pseudo"] == "C1"  # rien n'a bougé
    L.annuler_equipe(t, e["id"], "test", T0)
    with pytest.raises(L.ErreurTournoi, match="aucune équipe"):
        L.modifier_joueur(t, "c1", pseudo="X")


def test_remplacer_un_coequipier_en_attente():
    t = tournoi()
    e = inscrire(t, 1)
    equipe, ancien, nouveau = L.remplacer_joueur(t, "j1a", ("z", "Zoe"), "  Zoe_RL ")
    assert equipe is e and ancien["id"] == "j1a"
    assert e["joueurs"][1] == {"id": "z", "pseudo": "Zoe", "pseudo_jeu": "Zoe_RL", "statut": L.CONFIRME}
    assert L.equipe_confirmee(e) and e["capitaine_id"] == "c1"
    assert L.equipe_du_joueur(t, "j1a") is None  # l'ancien peut se réinscrire ailleurs


def test_remplacer_le_capitaine():
    t = tournoi()
    e = inscrire(t, 1)
    L.remplacer_joueur(t, "c1", ("z", "Zoe"), "Zoe_RL")
    assert e["capitaine_id"] == "z" and e["capitaine"] == {"pseudo": "Zoe", "pseudo_jeu": "Zoe_RL"}
    assert e["joueurs"][0]["id"] == "z"


def test_remplacer_joueur_refuse():
    t = tournoi(equipes_max=3)
    e = inscrire(t, 1)
    inscrire(t, 2)
    L.reserver_place(t, nom="Invités", capitaine=("r", "R"), duree_minutes=60, cree_par="9", maintenant=T0)
    with pytest.raises(L.ErreurTournoi, match="aucune équipe"):
        L.remplacer_joueur(t, "intrus", ("z", "Zoe"), "Zoe_RL")
    with pytest.raises(L.ErreurTournoi, match="même que l'ancien"):
        L.remplacer_joueur(t, "c1", ("c1", "C1"), "C1_RL")
    with pytest.raises(L.ErreurTournoi, match="déjà dans l'équipe \\*\\*Team 2"):
        L.remplacer_joueur(t, "c1", ("j2a", "J2a"), "X")
    with pytest.raises(L.ErreurTournoi, match="place réservée"):
        L.remplacer_joueur(t, "c1", ("r", "R"), "X")
    with pytest.raises(L.ErreurTournoi, match="vide"):
        L.remplacer_joueur(t, "c1", ("z", "Zoe"), "   ")
    assert [j["id"] for j in e["joueurs"]] == ["c1", "j1a"]  # rien n'a bougé
