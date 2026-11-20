import pytest

from bot_inscription_manager.main import lire_delai_confirmation, probleme_token


@pytest.mark.parametrize("token, attendu", [
    ("", "manquant"),
    ("Bot abc.def.ghi", "Enlève « Bot »"),
    ("1544015944353976341", "Application ID"),
    ("a3" * 32, "Public Key"),
    ("AbCdEfGhIjKlMnOpQrStUvWxYz012345", "Client Secret"),
])
def test_erreurs_de_copier_coller(token, attendu):
    assert attendu in probleme_token(token)


def test_token_de_bot_valide():
    # Faux token au format « partie1.partie2.partie3 » (pas un vrai token, pour ne pas déclencher le secret scanning de GitHub).
    assert probleme_token("faux-id-de-bot.horodatage.signature-de-test") is None


@pytest.mark.parametrize("valeur, attendu", [(None, 30), ("", 30), (" 45 ", 45), ("1", 1), ("10080", 10080)])
def test_delai_confirmation_valide(valeur, attendu):
    assert lire_delai_confirmation(valeur) == attendu


@pytest.mark.parametrize("valeur", ["0", "-5", "30min", "1.5", "abc", "10081"])
def test_delai_confirmation_invalide(valeur):
    with pytest.raises(ValueError, match="DELAI_CONFIRMATION_MINUTES doit être un nombre entier"):
        lire_delai_confirmation(valeur)
