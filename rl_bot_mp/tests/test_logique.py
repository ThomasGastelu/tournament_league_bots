from types import SimpleNamespace

from bot_mp import logique as L


def membre(uid, nom="x", bot=False):
    return SimpleNamespace(id=uid, display_name=nom, bot=bot)


def test_destinataires_ignore_les_bots_et_les_doublons():
    a, b, robot = membre(1), membre(2), membre(3, bot=True)
    assert L.destinataires([a, robot, b, a]) == [a, b]


def test_duree_estimee():
    assert L.duree_estimee(10) == "moins d'une minute"
    assert L.duree_estimee(100) == "environ 3 min"     # 150 s
    assert L.duree_estimee(3000) == "environ 1 h 15"   # 4500 s


def test_liste_noms_courte_et_echappee():
    assert L.liste_noms(["a_b", "c"]) == "a\\_b, c"


def test_liste_noms_coupee_si_trop_longue():
    texte = L.liste_noms([f"joueur{i}" for i in range(500)], limite=50)
    assert texte.endswith("autres")
    assert len(texte) < 80
    assert L.liste_noms(["un_nom_beaucoup_trop_long"], limite=5) == "… et 1 autre"


def test_rapport_tient_dans_un_message_discord():
    rapport = L.Rapport(total=10_000, recus=4000,
                        mp_fermes=[f"ferme{i}" for i in range(3000)],
                        erreurs=[f"erreur{i}" for i in range(3000)])
    texte = L.texte_rapport(rapport)
    assert len(texte) <= 2000
    assert "4000/10000" in texte and "MP fermés (3000)" in texte and "Erreur d'envoi (3000)" in texte


def test_rapport_sans_echec():
    assert L.texte_rapport(L.Rapport(total=2, recus=2)) == \
        "✅ Envoi terminé : **2/2** membres ont reçu le message."


def test_textes_apercu_et_progression():
    assert "Aucun membre" in L.texte_apercu(0)
    assert "**1** membre " in L.texte_apercu(1)
    assert "**25** membres" in L.texte_apercu(25)
    progression = L.texte_progression(L.Rapport(total=50, recus=8, mp_fermes=["a", "b"]))
    assert "**10/50**" in progression and "MP fermés : 2" in progression


def test_embed_mp():
    embed = L.embed_mp("Salut\ntout le monde", "Mon serveur")
    assert embed.description == "Salut\ntout le monde"
    assert embed.author.name == "Mon serveur"
    assert "Mon serveur" in embed.footer.text


def test_probleme_token():
    assert "manquant" in L.probleme_token("")
    assert "Bot" in L.probleme_token("Bot abc.def.ghi")
    assert "Application ID" in L.probleme_token("123456789")
    assert "Public Key" in L.probleme_token("a" * 64)
    assert "Client Secret" in L.probleme_token("abcdef")
    assert L.probleme_token("MTIz.Gh1jK2.xyz") is None
