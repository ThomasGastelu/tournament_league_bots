"""Simule les interactions Discord avec de faux objets (sans token ni serveur).

Vérifie que les commandes, la fiche et les boutons enchaînent correctement :
JSON mis à jour, MP envoyés, annonce modifiée.
"""

import asyncio
from types import SimpleNamespace

import pytest

from bot_inscription_manager import logique as L
from bot_inscription_manager.commandes import (autocomplete_tournoi, texte_modification, tournoi_rl,
                                               tournoi_rl_modify, tournoi_rl_remove, tournoi_rl_remove_team,
                                               tournoi_rl_status, tournoi_rl_status_all,
                                               tournoi_rl_modify_member, tournoi_rl_modify_player)
from bot_inscription_manager.inscription import (BoutonAnnuler, BoutonInscription, BoutonRefuser, BoutonValider,
                                                 FicheConfirmation,
                             ConfirmationAnnulation, FicheInscription)
from bot_inscription_manager.stockage import Stockage


class FauxUtilisateur:
    def __init__(self, uid, nom, bot=False, mp_fermes=False):
        self.id, self.display_name, self.bot, self.mp_fermes = uid, nom, bot, mp_fermes
        self.mention = f"<@{uid}>"
        self.mp = []

    async def send(self, texte, **kwargs):
        if self.mp_fermes:
            import discord
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "MP fermés")
        self.mp.append(texte)


class FauxMessage:
    def __init__(self, mid):
        self.id = mid
        self.editions = []
        self.supprimee = False

    async def edit(self, **kwargs):
        self.editions.append(kwargs)

    async def delete(self):
        self.supprimee = True


class FauxSalon:
    def __init__(self):
        self.id = 2
        self.envoyes = []
        self.annonce = FauxMessage(777)

    async def send(self, texte=None, **kwargs):
        self.envoyes.append((texte, kwargs))
        return self.annonce

    def get_partial_message(self, mid):
        return self.annonce


class FauxClient:
    def __init__(self, dossier, utilisateurs):
        self.stockage = Stockage(dossier)
        self.utilisateurs = {u.id: u for u in utilisateurs}
        self.salon = FauxSalon()

    def get_user(self, uid):
        return self.utilisateurs.get(uid)

    async def fetch_user(self, uid):
        return self.utilisateurs[uid]

    def get_channel(self, cid):
        return self.salon


class FauxServeur:
    def __init__(self, client):
        self.client = client

    async def fetch_member(self, uid):
        import discord
        if uid not in self.client.utilisateurs:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "inconnu")
        return self.client.utilisateurs[uid]


class FausseReponse:
    def __init__(self, inter):
        self.inter, self.fait = inter, False

    def is_done(self):
        return self.fait

    async def defer(self, **kwargs):
        self.fait = True

    async def send_message(self, texte, **kwargs):
        self.fait = True
        self.inter.reponses.append((texte, kwargs))

    async def send_modal(self, modal):
        self.fait = True
        self.inter.modal = modal

    async def edit_message(self, **kwargs):
        self.fait = True
        self.inter.editions.append(kwargs)


class FausseInteraction:
    _compteur = 1544015944353976341

    def __init__(self, client, utilisateur):
        FausseInteraction._compteur += 1
        self.id = FausseInteraction._compteur
        self.client, self.user = client, utilisateur
        self.guild, self.guild_id = FauxServeur(client), 1
        self.channel, self.channel_id = client.salon, client.salon.id
        self.reponses, self.editions, self.modal = [], [], None
        self.response = FausseReponse(self)
        self.followup = SimpleNamespace(send=self._followup)
        self.namespace = SimpleNamespace()

    async def _followup(self, texte, **kwargs):
        self.reponses.append((texte, kwargs))

    def dernier_texte(self):
        return self.reponses[-1][0]


@pytest.fixture
def monde(tmp_path):
    joueurs = {n: FauxUtilisateur(i, n) for i, n in enumerate(
        ["Admin", "Thomas", "Lucas", "Hugo", "Nina", "Leo", "Zoe"], start=10)}
    joueurs["Ferme"] = FauxUtilisateur(90, "Ferme", mp_fermes=True)
    joueurs["Robot"] = FauxUtilisateur(91, "Robot", bot=True)
    client = FauxClient(tmp_path, joueurs.values())
    return client, joueurs


def lancer(coro):
    return asyncio.run(coro)


def creer_tournoi(client, admin, equipes_max=1):
    inter = FausseInteraction(client, admin)
    lancer(tournoi_rl.callback(inter, titre="caca", cashprize="100", joueurs_par_equipe=2,
                               equipes_max=equipes_max, date="6 septembre"))
    return str(inter.id)


def inscrire(client, capitaine, coequipiers, nom, tid):
    inter = FausseInteraction(client, capitaine)
    lancer(BoutonInscription(tid).callback(inter))
    fiche = inter.modal
    if fiche is None:  # refusé avant d'ouvrir la fiche
        return inter
    assert isinstance(fiche, FicheInscription)
    fiche.nom = SimpleNamespace(value=nom)
    fiche.pseudo_jeu = SimpleNamespace(value=capitaine.display_name + "_RL")
    fiche.coequipiers = SimpleNamespace(values=coequipiers)
    lancer(fiche.on_submit(inter))
    return inter


def confirmer(client, joueur, tid, equipe_id, inter=None):
    """Clic sur « Confirmer ma participation » puis envoi de la fiche avec le pseudo Rocket League."""
    inter = inter or FausseInteraction(client, joueur)
    lancer(BoutonValider(tid, equipe_id).callback(inter))
    fiche = inter.modal
    if fiche is None:  # refusé avant d'ouvrir la fiche
        return inter
    assert isinstance(fiche, FicheConfirmation)
    fiche.pseudo_jeu = SimpleNamespace(value=f"  {joueur.display_name}_RL ")
    lancer(fiche.on_submit(inter))
    return inter


def test_parcours_complet(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=1)
    t = client.stockage.charger(tid)
    assert t["message_id"] == "777" and t["liste_attente_max"] == 4
    assert "caca" in client.salon.envoyes[0][1]["embed"].title

    # Thomas inscrit Lucas : place obtenue tout de suite, Lucas reçoit un MP.
    inter = inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    assert "Tu t'es inscrit au tournoi **caca**" in inter.dernier_texte()
    assert "En attente de : **Lucas**" in inter.dernier_texte()
    assert "Place obtenue : 1/1" in inter.dernier_texte()
    assert "t'a inscrit dans l'équipe **Les Tomates**" in j["Lucas"].mp[-1]
    assert "Tu t'es inscrit" in j["Thomas"].mp[-1]
    assert "Ton pseudo Rocket League : `Thomas_RL`" in j["Thomas"].mp[-1]
    assert "exactement le même que dans le jeu" in j["Lucas"].mp[-1]
    assert client.salon.annonce.editions[-1]["embed"].fields[2].value == "1/1"

    # Lucas ne peut pas créer une autre équipe.
    inter = inscrire(client, j["Lucas"], [j["Hugo"]], "Autre", tid)
    assert "déjà dans l'équipe **Les Tomates**" in inter.dernier_texte()

    # Lucas valide : le capitaine est prévenu.
    inter = FausseInteraction(client, j["Lucas"])
    confirmer(client, j["Lucas"], tid, 1, inter)
    assert "a confirmé sa participation" in inter.editions[-1]["content"]
    assert "`Lucas_RL`" in inter.editions[-1]["content"]
    assert "`Lucas_RL`" in j["Thomas"].mp[-1]
    inter = confirmer(client, j["Lucas"], tid, 1)  # deuxième clic : pas de fiche
    assert inter.modal is None and "déjà confirmé" in inter.dernier_texte()
    t = client.stockage.charger(tid)
    assert [jr["pseudo_jeu"] for jr in t["equipes"][0]["joueurs"]] == ["Thomas_RL", "Lucas_RL"]
    assert "Toute l'équipe a validé" in j["Thomas"].mp[-1]

    # Hugo inscrit Nina : tournoi plein -> liste d'attente.
    inter = inscrire(client, j["Hugo"], [j["Nina"]], "Turbo", tid)
    assert "liste d'attente" in inter.dernier_texte() and "position 1/4" in inter.dernier_texte()
    lignes = inter.dernier_texte().splitlines()
    assert lignes[0].startswith("⏳ Le tournoi est plein") and lignes[1].startswith("🎮 Ton pseudo Rocket League")
    assert "Tu t'es inscrit" not in inter.dernier_texte()

    # Nina valide, puis Leo inscrit un joueur aux MP fermés -> message dans le salon.
    confirmer(client, j["Nina"], tid, 2)
    inscrire(client, j["Leo"], [j["Ferme"]], "Fermés", tid)
    texte, kwargs = client.salon.envoyes[-1]
    assert texte.startswith("<@90> (tes MP sont fermés)") and "view" in kwargs

    # Ferme refuse : son équipe est annulée, Leo est prévenu.
    inter = FausseInteraction(client, j["Ferme"])
    lancer(BoutonRefuser(tid, 3).callback(inter))
    assert "a refusé" in inter.editions[-1]["content"]
    assert "a refusé" in j["Leo"].mp[-1]

    # Thomas (capitaine) annule -> Turbo est promue, ses joueurs reçoivent un MP.
    inter = FausseInteraction(client, j["Lucas"])
    lancer(BoutonAnnuler(tid, 1).callback(inter))
    assert "Seul le capitaine" in inter.dernier_texte()
    inter = FausseInteraction(client, j["Thomas"])
    lancer(BoutonAnnuler(tid, 1).callback(inter))
    confirmation = inter.reponses[-1][1]["view"]
    assert isinstance(confirmation, ConfirmationAnnulation)
    lancer(confirmation.confirmer.callback(inter))
    assert "est annulée" in inter.editions[-1]["content"]
    assert "Le capitaine a annulé" in j["Lucas"].mp[-1]
    assert "Une place s'est libérée" in j["Hugo"].mp[-1] and "Une place s'est libérée" in j["Nina"].mp[-1]
    t = client.stockage.charger(tid)
    assert [e["nom"] for e in L.equipes_inscrites(t)] == ["Turbo"]

    # Status
    inter = FausseInteraction(client, j["Zoe"])
    lancer(tournoi_rl_status.callback(inter, tournoi_id=tid))
    description = inter.reponses[0][1]["embed"].description
    assert "`#2` **Turbo** — 👑 Hugo (🎮 `Hugo_RL`) ✅, Nina (🎮 `Nina_RL`) ✅" in description

    # Admin retire Turbo.
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_remove_team.callback(inter, tournoi_id=tid, team_id=2))
    assert "retirée du tournoi" in inter.dernier_texte()
    assert "retirée du tournoi **caca** par un admin" in j["Nina"].mp[-1]
    lancer(tournoi_rl_remove_team.callback(FausseInteraction(client, j["Admin"]), tournoi_id=tid, team_id=2))
    assert client.stockage.charger(tid)["equipes"][1]["raison_annulation"] == "retirée par Admin"


def test_joueurs_invalides_dans_la_fiche(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=4)
    inter = inscrire(client, j["Thomas"], [j["Robot"]], "A", tid)
    assert "est un bot" in inter.dernier_texte()
    inconnu = FauxUtilisateur(555, "Inconnu")
    inter = inscrire(client, j["Thomas"], [inconnu], "A", tid)
    assert "n'est pas membre du serveur" in inter.dernier_texte()
    inter = inscrire(client, j["Thomas"], [j["Thomas"]], "A", tid)
    assert "toi-même" in inter.dernier_texte()
    assert client.stockage.charger(tid)["equipes"] == []


def test_status_tournoi_inconnu(monde):
    client, j = monde
    inter = FausseInteraction(client, j["Zoe"])
    lancer(tournoi_rl_status.callback(inter, tournoi_id="123"))
    assert "Aucun tournoi" in inter.dernier_texte()


def test_suppression_du_tournoi(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=1)
    inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    inscrire(client, j["Hugo"], [j["Nina"]], "Turbo", tid)
    lancer(BoutonRefuser(tid, 2).callback(FausseInteraction(client, j["Nina"])))  # Turbo déjà annulée
    mp_hugo = len(j["Hugo"].mp)

    # "Non" : rien ne change.
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_remove.callback(inter, tournoi_id=tid))
    lancer(inter.reponses[-1][1]["view"].garder.callback(inter))
    assert "conservé" in inter.editions[-1]["content"]
    assert client.stockage.charger(tid) is not None

    # "Oui" : annonce supprimée, fichier effacé, joueurs prévenus.
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_remove.callback(inter, tournoi_id=tid))
    assert "définitif" in inter.dernier_texte() and "1 équipe(s)" in inter.dernier_texte()
    lancer(inter.reponses[-1][1]["view"].confirmer.callback(inter))
    assert "annulé et effacé" in inter.editions[-1]["content"]
    assert client.stockage.charger(tid) is None
    assert client.salon.annonce.supprimee
    for nom in ("Thomas", "Lucas"):
        assert "a été annulé par un admin" in j[nom].mp[-1]
    assert len(j["Hugo"].mp) == mp_hugo  # équipe déjà annulée : pas de MP en plus

    # Les anciens boutons répondent proprement, et on ne peut pas effacer deux fois.
    inter = FausseInteraction(client, j["Lucas"])
    lancer(BoutonValider(tid, 1).callback(inter))
    assert "n'existe plus" in inter.dernier_texte()
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_remove.callback(inter, tournoi_id=tid))
    assert "Aucun tournoi" in inter.dernier_texte()


# --------------------------------------------------------------------------- #
# /tournoi_rl_modify
# --------------------------------------------------------------------------- #

def lancer_sans_blocage(coro):
    """Comme lancer(), mais échoue au lieu de bloquer si un verrou est pris deux fois."""
    return asyncio.run(asyncio.wait_for(coro, timeout=5))


def modifier(client, admin, tid, **champs):
    inter = FausseInteraction(client, admin)
    lancer_sans_blocage(tournoi_rl_modify.callback(inter, tournoi_id=tid, **champs))
    return inter


def bouton_annonce(client):
    return client.salon.annonce.editions[-1]["view"].children[0].item


def remplir(client, j, tid, nb_equipes):
    """Inscrit nb_equipes équipes de 2 (crée les joueurs qui manquent)."""
    for n in range(1, nb_equipes + 1):
        cap, coe = FauxUtilisateur(300 + 2 * n, f"Cap{n}"), FauxUtilisateur(301 + 2 * n, f"Coe{n}")
        client.utilisateurs.update({cap.id: cap, coe.id: coe})
        j[cap.display_name], j[coe.display_name] = cap, coe
        inscrire(client, cap, [coe], f"Team {n}", tid)


def test_modification_du_tournoi(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=1)
    remplir(client, j, tid, 5)  # 1 inscrite + 4 en liste d'attente : complet
    assert bouton_annonce(client).disabled
    mp_cap4 = len(j["Cap4"].mp)

    inter = modifier(client, j["Admin"], tid, titre="Grand Tournoi", cashprize="  300€ ", equipes_max=3)
    texte = inter.dernier_texte()
    assert "✅ Tournoi **Grand Tournoi** modifié" in texte
    assert "Titre : caca → **Grand Tournoi**" in texte
    assert "Cashprize : 100 → **300€**" in texte
    assert "Équipes max : 1 → **3** (liste d'attente max : **12**)" in texte
    assert "`#2` **Team 2**, `#3` **Team 3**" in texte
    assert "⚠️" not in texte

    # JSON
    t = client.stockage.charger(tid)
    assert (t["titre"], t["cashprize"], t["equipes_max"], t["liste_attente_max"]) == ("Grand Tournoi", "300€", 3, 12)
    assert [e["nom"] for e in L.equipes_inscrites(t)] == ["Team 1", "Team 2", "Team 3"]
    assert [e["nom"] for e in L.liste_attente(t)] == ["Team 4", "Team 5"]

    # Annonce : nouveau titre, nouveaux compteurs, bouton de nouveau cliquable.
    embed = client.salon.annonce.editions[-1]["embed"]
    assert embed.title == "🏆 Grand Tournoi"
    assert [f.value for f in embed.fields[:5]] == ["300€", "2v2", "3/3", "6 septembre", "2/12"]
    assert not bouton_annonce(client).disabled

    # MP aux équipes promues seulement.
    for nom in ("Cap2", "Coe2", "Cap3", "Coe3"):
        assert "De nouvelles places ont été ouvertes" in j[nom].mp[-1]
        assert "**Grand Tournoi**" in j[nom].mp[-1]
    assert len(j["Cap4"].mp) == mp_cap4

    # Le verrou est bien relâché, et l'autocomplétion affiche le nouveau titre.
    assert not client.stockage.verrou(tid).locked()
    choix = lancer(autocomplete_tournoi(FausseInteraction(client, j["Admin"]), "grand"))
    assert [c.value for c in choix] == [tid]

    # Une nouvelle équipe va en liste d'attente avec le nouveau maximum.
    inter = inscrire(client, j["Zoe"], [j["Leo"]], "Nouvelle", tid)
    assert "position 3/12" in inter.dernier_texte()


def test_modification_refusee(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=2)
    inscrire(client, j["Thomas"], [j["Lucas"]], "A", tid)
    inscrire(client, j["Hugo"], [j["Nina"]], "B", tid)
    avant = client.stockage.charger(tid)
    editions = len(client.salon.annonce.editions)

    cas = [
        ({}, "au moins un champ"),
        ({"titre": "   "}, "titre ne peut pas être vide"),
        ({"equipes_max": 1}, "2 équipes sont déjà inscrites"),
        ({"titre": " caca", "cashprize": "100", "equipes_max": 2}, "ℹ️ Rien à modifier"),
    ]
    for champs, message in cas:
        assert message in modifier(client, j["Admin"], tid, **champs).dernier_texte()
    assert "Aucun tournoi" in modifier(client, j["Admin"], "123", titre="x").dernier_texte()
    assert "Aucun tournoi" in modifier(client, j["Admin"], "../x", titre="x").dernier_texte()

    # Tournoi d'un autre serveur.
    inter = FausseInteraction(client, j["Admin"])
    inter.guild_id = 2
    lancer_sans_blocage(tournoi_rl_modify.callback(inter, tournoi_id=tid, titre="x"))
    assert "Aucun tournoi" in inter.dernier_texte()

    assert client.stockage.charger(tid) == avant
    assert len(client.salon.annonce.editions) == editions
    assert not client.stockage.verrou(tid).locked()


def test_modification_quand_l_annonce_a_ete_supprimee(monde):
    import discord
    client, j = monde
    tid = creer_tournoi(client, j["Admin"])

    async def annonce_supprimee(**kwargs):
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")

    client.salon.annonce.edit = annonce_supprimee
    inter = modifier(client, j["Admin"], tid, cashprize="50€")
    assert "Cashprize : 100 → **50€**" in inter.dernier_texte()
    assert "⚠️ Modification enregistrée, mais l'annonce n'a pas pu être mise à jour" in inter.dernier_texte()
    assert client.stockage.charger(tid)["cashprize"] == "50€"


def test_message_de_modification_reste_sous_la_limite_discord():
    t = L.nouveau_tournoi(tournoi_id="1", titre="T" * 100, cashprize="C" * 100, joueurs_par_equipe=2,
                          equipes_max=128, date="d", serveur_id="1", salon_id="2", cree_par="3", maintenant="x")
    promues = [{"id": i, "nom": "N" * 32} for i in range(1, 128)]
    changements = [("titre", "A" * 100, "T" * 100), ("cashprize", "B" * 100, "C" * 100), ("equipes_max", 1, 128)]
    texte = texte_modification(t, changements, promues, annonce_ok=False)
    assert len(texte) < 2000
    assert "127 équipes (détail dans `/tournoi_rl_status`)" in texte


def test_desinscription_automatique_apres_30_minutes(monde):
    from datetime import datetime, timedelta
    from bot_inscription_manager.inscription import expirer_inscriptions

    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=1)
    inter = inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    assert "Ils doivent confirmer avant <t:" in inter.dernier_texte()
    assert "30 minutes" in j["Lucas"].mp[-1] and "<t:" in j["Lucas"].mp[-1]
    inscrire(client, j["Hugo"], [j["Nina"]], "Turbo", tid)  # liste d'attente
    confirmer(client, j["Nina"], tid, 2)

    # Avant la fin du délai : rien ne se passe.
    assert lancer(expirer_inscriptions(client)) == 0

    # On fait comme si les 30 minutes étaient passées pour « Les Tomates ».
    t = client.stockage.charger(tid)
    t["equipes"][0]["cree_le"] = (datetime.now().astimezone() - timedelta(minutes=30, seconds=1)).isoformat()
    t["equipes"][0]["confirmer_avant"] = (datetime.now().astimezone() - timedelta(seconds=1)).isoformat()
    client.stockage.sauvegarder(t)

    # Lucas clique trop tard : refusé.
    inter = confirmer(client, j["Lucas"], tid, 1)
    assert inter.modal is None and "Trop tard" in inter.dernier_texte()

    assert lancer(expirer_inscriptions(client)) == 1
    t = client.stockage.charger(tid)
    assert t["equipes"][0]["statut"] == L.ANNULEE
    assert t["equipes"][1]["statut"] == L.INSCRITE  # Turbo monte
    for nom in ("Thomas", "Lucas"):
        assert "est désinscrite du tournoi **caca**" in j[nom].mp[-1]
        assert "**Lucas** n'a pas confirmé sa participation dans les 30 minutes" in j[nom].mp[-1]
    assert "Une place s'est libérée" in j["Hugo"].mp[-1]
    assert client.salon.annonce.editions[-1]["embed"].fields[2].value == "1/1"
    assert lancer(expirer_inscriptions(client)) == 0  # déjà traitée


def test_status_all_visible_par_tous(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=4)
    inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    prive = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_status.callback(prive, tournoi_id=tid))
    public = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_status_all.callback(public, tournoi_id=tid))
    assert len(public.reponses) == len(prive.reponses) >= 1
    for (_, kw_public), (_, kw_prive) in zip(public.reponses, prive.reponses):
        assert kw_prive["ephemeral"] is True
        assert not kw_public.get("ephemeral", False)
        assert kw_public["embed"].description == kw_prive["embed"].description
    assert "Les Tomates" in public.reponses[0][1]["embed"].description


def test_status_all_tournoi_inconnu(monde):
    client, j = monde
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_status_all.callback(inter, tournoi_id="123"))
    assert "Aucun tournoi" in inter.dernier_texte()
    assert inter.reponses[-1][1]["ephemeral"] is True


def test_modify_player_change_le_pseudo_et_previent_le_joueur(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=4)
    inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_modify_player.callback(inter, tournoi_id=tid, joueur=j["Thomas"], pseudo_jeu="Tomato_King"))
    assert "Pseudo Rocket League : Thomas_RL → **Tomato_King**" in inter.dernier_texte()
    assert inter.reponses[-1][1]["ephemeral"] is True
    assert "Tomato_King" in j["Thomas"].mp[-1]
    equipe = client.stockage.charger(tid)["equipes"][0]
    assert equipe["joueurs"][0]["pseudo_jeu"] == "Tomato_King"
    assert equipe["capitaine"]["pseudo_jeu"] == "Tomato_King"

    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_modify_player.callback(inter, tournoi_id=tid, joueur=j["Lucas"], pseudo_jeu="X"))
    assert "pas encore confirmé" in inter.dernier_texte()
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_modify_player.callback(inter, tournoi_id=tid, joueur=j["Zoe"], pseudo="Z"))
    assert "aucune équipe" in inter.dernier_texte()


def test_modify_member_remplace_le_joueur_et_previent_les_deux(monde):
    client, j = monde
    tid = creer_tournoi(client, j["Admin"], equipes_max=4)
    inscrire(client, j["Thomas"], [j["Lucas"]], "Les Tomates", tid)
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_modify_member.callback(inter, tournoi_id=tid, ancien=j["Lucas"], nouveau=j["Zoe"],
                                             pseudo_jeu="Zoe_RL"))
    assert "**Lucas** remplacé par **Zoe**" in inter.dernier_texte()
    assert inter.reponses[-1][1]["ephemeral"] is True
    assert "remplacé par **Zoe**" in j["Lucas"].mp[-1]
    assert "à la place de **Lucas**" in j["Zoe"].mp[-1]
    equipe = client.stockage.charger(tid)["equipes"][0]
    assert [(p["pseudo"], p["statut"]) for p in equipe["joueurs"]] == [("Thomas", L.CONFIRME), ("Zoe", L.CONFIRME)]

    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_modify_member.callback(inter, tournoi_id=tid, ancien=j["Thomas"], nouveau=j["Robot"],
                                             pseudo_jeu="X"))
    assert "est un bot" in inter.dernier_texte()
    inter = FausseInteraction(client, j["Admin"])
    lancer(tournoi_rl_modify_member.callback(inter, tournoi_id=tid, ancien=j["Thomas"], nouveau=j["Zoe"],
                                             pseudo_jeu="X"))
    assert "déjà dans l'équipe" in inter.dernier_texte()
