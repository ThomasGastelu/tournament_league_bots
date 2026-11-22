import pytest

from bot_ticket import logique as L


def test_les_sept_categories_et_leurs_textes_respectent_les_limites_discord():
    assert [c.nom for c in L.CATEGORIES] == [
        "Recrutement modérateur", "Demande d'aide", "Problème technique", "Partenariat",
        "Proposition / Suggestion", "Signalement", "Autre"]
    for c in L.CATEGORIES:
        assert len(c.nom) <= 100 and len(c.description) <= 100  # limites d'une option de liste
        assert c.emoji and c.consigne
    assert len({c.cle for c in L.CATEGORIES}) == 7


def test_nom_salon_simplifie_le_pseudo():
    aide = L.CATEGORIES_PAR_CLE["aide"]
    assert L.nom_salon(aide, "Thömas_RL ⭐") == "aide-thomas-rl"
    assert L.nom_salon(aide, "⭐⭐") == "aide-membre"
    assert len(L.nom_salon(aide, "x" * 300)) <= L.LONGUEUR_MAX_NOM_SALON


def test_sujet_relu_apres_redemarrage():
    signalement = L.CATEGORIES_PAR_CLE["signalement"]
    sujet = L.sujet_salon(signalement, 1234, "Thomas")
    assert L.lire_sujet(sujet) == (1234, signalement)
    assert L.lire_sujet("Discussion libre") is None
    assert L.lire_sujet(None) is None
    assert L.lire_sujet("ticket:12:inconnue") is None


def test_un_seul_ticket_ouvert_par_membre():
    class Salon:
        def __init__(self, topic):
            self.topic = topic

    a = Salon(L.sujet_salon(L.CATEGORIES[0], 1, "A"))
    b = Salon(L.sujet_salon(L.CATEGORIES[1], 2, "B"))
    assert L.ticket_ouvert([Salon(None), a, b], 2) is b
    assert L.ticket_ouvert([a, b], 3) is None


def test_qui_peut_fermer():
    assert L.peut_fermer(1, [], False, auteur_id=1, roles_staff=[9])          # l'auteur
    assert L.peut_fermer(2, [9], False, auteur_id=1, roles_staff=[9])         # le staff
    assert L.peut_fermer(2, [], True, auteur_id=1, roles_staff=[9])           # gère les salons
    assert not L.peut_fermer(2, [5], False, auteur_id=1, roles_staff=[9])     # un autre membre


def test_lire_reglages():
    regl = L.lire_reglages({"CATEGORIE_TICKETS": " 42 ", "ROLES_STAFF": "1, 2,1;3", "LOG_CHANNEL": ""})
    assert regl == L.Reglages(categorie_id=42, roles_staff=(1, 2, 3), log_channel=None)
    assert L.lire_reglages({}) == L.Reglages()


def test_reglages_invalides_disent_quoi_corriger():
    with pytest.raises(L.ErreurReglage, match="ROLES_STAFF"):
        L.lire_reglages({"ROLES_STAFF": "@Staff"})
    with pytest.raises(L.ErreurReglage, match="LOG_CHANNEL"):
        L.lire_reglages({"LOG_CHANNEL": "#logs"})


def test_texte_transcription():
    texte = L.texte_transcription("Ticket #aide-a", [
        L.MessageCopie("01/01/2026 10:00", "Thomas", "Salut", ("https://x/capture.png",)),
        L.MessageCopie("01/01/2026 10:05", "Modo", "Bonjour !"),
    ])
    assert "[01/01/2026 10:00] Thomas : Salut" in texte
    assert "📎 https://x/capture.png" in texte and "Modo : Bonjour !" in texte
    assert "(aucun message)" in L.texte_transcription("T", [])


def test_probleme_token():
    assert "manquant" in L.probleme_token("")
    assert "Bot" in L.probleme_token("Bot abc.def.ghi")
    assert "Application ID" in L.probleme_token("123456789")
    assert "Public Key" in L.probleme_token("a" * 64)
    assert "Client Secret" in L.probleme_token("abcdef")
    assert L.probleme_token("MTIz.Gh1jK2.xyz") is None
