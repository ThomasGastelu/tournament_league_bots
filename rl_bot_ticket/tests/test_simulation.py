"""Simule le panneau Support, la création et la fermeture des tickets avec de faux objets Discord
(sans token ni serveur)."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import discord
import pytest

from bot_ticket import embeds as E
from bot_ticket import logique as L
from bot_ticket import tickets as T
from bot_ticket.commandes import ticket_panel


def erreur_http(classe, status):
    return classe(SimpleNamespace(status=status, reason="x"), "simulée")


class FauxRole:
    def __init__(self, uid, nom):
        self.id, self.name, self.mention = uid, nom, f"<@&{uid}>"


class FauxMembre:
    def __init__(self, uid, nom, roles=(), gere_salons=False):
        self.id, self.display_name, self.roles, self.bot = uid, nom, list(roles), False
        self.mention = f"<@{uid}>"
        self.guild_permissions = SimpleNamespace(manage_channels=gere_salons)

    def __str__(self):
        return self.display_name


class FauxSalon:
    def __init__(self, nom, topic=None, category=None, overwrites=None):
        self.name, self.topic, self.category, self.overwrites = nom, topic, category, overwrites or {}
        self.id = id(self)
        self.mention = f"<#{nom}>"
        self.envois, self.supprime, self.historique = [], False, []

    async def send(self, texte=None, **kwargs):
        self.envois.append((texte, kwargs))
        self.ecrit(BOT, texte or "", embeds=[kwargs["embed"]] if kwargs.get("embed") else [])
        return SimpleNamespace()

    def ecrit(self, auteur, texte, date=None, embeds=()):
        """Ajoute un message à l'historique du salon (lu par la copie et la fermeture automatique)."""
        self.historique.append(SimpleNamespace(
            content=texte, embeds=list(embeds), attachments=[], author=auteur,
            created_at=date or datetime.now(timezone.utc)))

    async def delete(self, **kwargs):
        self.supprime = True

    async def history(self, limit=100, oldest_first=False):
        messages = sorted(self.historique, key=lambda m: m.created_at, reverse=not oldest_first)
        for message in messages[:limit]:
            yield message


BOT = SimpleNamespace(id=99, display_name="Bot ticket", bot=True)


class FausseCategorie:
    def __init__(self, nom):
        self.name, self.text_channels = nom, []


class FauxServeur:
    def __init__(self, roles):
        self.default_role = FauxRole(0, "@everyone")
        self.me = FauxMembre(99, "Bot ticket")
        self.roles = {r.id: r for r in roles}
        self.categories = []
        self.refuse = False

    def __str__(self):
        return "Serveur RL"

    def get_role(self, uid):
        return self.roles.get(uid)

    def get_channel(self, uid):
        return None

    async def create_category(self, nom, **kwargs):
        if self.refuse:
            raise erreur_http(discord.Forbidden, 403)
        categorie = FausseCategorie(nom)
        self.categories.append(categorie)
        return categorie

    async def create_text_channel(self, nom, *, category, overwrites, topic, reason):
        if self.refuse:
            raise erreur_http(discord.Forbidden, 403)
        salon = FauxSalon(nom, topic, category, overwrites)
        category.text_channels.append(salon)
        return salon


class FausseReponse:
    def __init__(self, inter):
        self.inter, self.fait = inter, False

    def is_done(self):
        return self.fait

    async def defer(self, **kwargs):
        self.fait = True

    async def send_message(self, texte=None, **kwargs):
        self.fait = True
        self.inter.reponses.append((texte, kwargs))

    async def edit_message(self, **kwargs):
        self.fait = True
        self.inter.editions.append(kwargs)


class FausseInteraction:
    def __init__(self, monde, utilisateur, salon=None):
        self.client, self.guild, self.user = monde.client, monde.serveur, utilisateur
        self.channel = salon or monde.salon_general
        self.reponses, self.editions = [], []
        self.response = FausseReponse(self)
        self.followup = SimpleNamespace(send=self._followup)

    async def _followup(self, texte=None, **kwargs):
        self.reponses.append((texte, kwargs))

    async def edit_original_response(self, **kwargs):
        self.editions.append(kwargs)

    def dernier_texte(self):
        return self.editions[-1]["content"]


@pytest.fixture
def monde(monkeypatch):
    monkeypatch.setattr(L, "DELAI_SUPPRESSION", 0)
    T._verrous.clear()
    T._en_fermeture.clear()
    staff = FauxRole(500, "Staff")
    serveur = FauxServeur([staff])
    logs = FauxSalon("logs")
    client = SimpleNamespace(reglages=L.Reglages(roles_staff=(500,), log_channel=777),
                             get_channel=lambda uid: logs if uid == 777 else None, guilds=[serveur])
    return SimpleNamespace(
        client=client, serveur=serveur, staff=staff, logs=logs, salon_general=FauxSalon("général"),
        thomas=FauxMembre(1, "Thomas"), lucas=FauxMembre(2, "Lucas"),
        modo=FauxMembre(3, "Modo", roles=[staff]),
    )


def lancer(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=5))


async def ouvrir(monde, membre, cle="aide"):
    """Clic sur « Créer un ticket » puis choix de la catégorie. Retourne l'interaction du choix."""
    clic = FausseInteraction(monde, membre)
    await T.BoutonCreerTicket().callback(clic)
    vue = clic.reponses[-1][1]["view"]
    vue.liste._values = [cle]
    choix = FausseInteraction(monde, membre)
    await vue.choisir(choix)
    return choix


def test_panneau_ressemble_au_modele(monde):
    async def scenario():
        inter = FausseInteraction(monde, monde.modo)
        await ticket_panel.callback(inter, None)
        return inter

    inter = lancer(scenario())
    _, options = monde.salon_general.envois[-1]
    assert options["embed"].title == "Support"
    assert options["embed"].description.startswith("Besoin d'aide ? Clique sur le bouton ci-dessous")
    bouton = options["view"].children[0].item
    assert (bouton.label, str(bouton.emoji), bouton.style, bouton.custom_id) == \
        ("Créer un ticket", "🎫", discord.ButtonStyle.success, "tk:creer")
    assert "Panneau Support publié" in inter.reponses[-1][0] and inter.reponses[-1][1]["ephemeral"]


def test_bouton_propose_les_sept_categories(monde):
    async def scenario():
        clic = FausseInteraction(monde, monde.thomas)
        await T.BoutonCreerTicket().callback(clic)
        return clic

    clic = lancer(scenario())
    texte, options = clic.reponses[-1]
    assert texte == E.TEXTE_CHOIX and options["ephemeral"]
    liste = options["view"].liste
    assert [o.value for o in liste.options] == [c.cle for c in L.CATEGORIES]
    assert liste.options[1].description == "Question générale, aide sur le serveur ou problème avec un membre."


def test_choisir_une_categorie_ouvre_un_salon_prive(monde):
    choix = lancer(ouvrir(monde, monde.thomas, "technique"))

    support = monde.serveur.categories[0]
    assert support.name == "Support"
    salon = support.text_channels[0]
    assert salon.name == "technique-thomas"
    assert L.lire_sujet(salon.topic) == (1, L.CATEGORIES_PAR_CLE["technique"])
    droits = salon.overwrites
    assert droits[monde.serveur.default_role].view_channel is False
    assert droits[monde.thomas].view_channel and droits[monde.staff].view_channel
    assert monde.lucas not in droits

    texte, options = salon.envois[0]
    assert texte == "<@1> <@&500>"
    assert options["embed"].title == "⚙️ Problème technique"
    assert [b.item.custom_id for b in options["view"].children] == ["tk:resolu", "tk:fermer"]
    assert "ne réponds plus pendant 72 h" in options["embed"].description
    assert choix.dernier_texte() == "✅ Ton ticket est ouvert : <#technique-thomas>"
    assert "a ouvert un ticket **Problème technique**" in monde.logs.envois[-1][0]


def test_un_seul_ticket_ouvert_a_la_fois(monde):
    async def scenario():
        await ouvrir(monde, monde.thomas, "aide")
        return await ouvrir(monde, monde.thomas, "signalement")

    choix = lancer(scenario())
    assert len(monde.serveur.categories[0].text_channels) == 1
    assert "déjà un ticket ouvert" in choix.dernier_texte()


def test_categorie_support_existante_reutilisee(monde):
    existante = FausseCategorie("SUPPORT")
    monde.serveur.categories.append(existante)
    lancer(ouvrir(monde, monde.lucas, "recrutement"))
    assert len(monde.serveur.categories) == 1
    assert existante.text_channels[0].name == "recrutement-lucas"


def test_permission_manquante_message_clair(monde):
    monde.serveur.refuse = True
    choix = lancer(ouvrir(monde, monde.thomas))
    assert choix.dernier_texte() == E.TEXTE_PERMISSION


def test_un_autre_membre_ne_peut_pas_fermer(monde):
    async def scenario():
        await ouvrir(monde, monde.thomas)
        salon = monde.serveur.categories[0].text_channels[0]
        clic = FausseInteraction(monde, monde.lucas, salon)
        await T.BoutonFermerTicket().callback(clic)
        return clic, salon

    clic, salon = lancer(scenario())
    assert clic.reponses[-1][0] == E.TEXTE_PAS_LE_DROIT and not salon.supprime


def test_fermeture_par_le_staff_copie_et_supprime(monde):
    async def scenario():
        await ouvrir(monde, monde.thomas)
        salon = monde.serveur.categories[0].text_channels[0]
        clic = FausseInteraction(monde, monde.modo, salon)
        await T.BoutonFermerTicket().callback(clic)
        vue = clic.reponses[-1][1]["view"]
        await vue.oui.callback(FausseInteraction(monde, monde.modo, salon))
        return salon

    salon = lancer(scenario())
    assert salon.supprime
    assert "fermé par **Modo**" in salon.envois[-1][0]
    texte, options = monde.logs.envois[-1]
    assert "fermé par <@3>" in texte and "de <@1>" in texte
    copie = options["file"].fp.read().decode()
    assert options["file"].filename == "aide-thomas.txt"
    assert "Demande d'aide" in copie and "fermé par **Modo**" in copie


def test_annuler_la_fermeture(monde):
    async def scenario():
        await ouvrir(monde, monde.thomas)
        salon = monde.serveur.categories[0].text_channels[0]
        clic = FausseInteraction(monde, monde.thomas, salon)
        await T.BoutonFermerTicket().callback(clic)
        annulation = FausseInteraction(monde, monde.thomas, salon)
        await clic.reponses[-1][1]["view"].non.callback(annulation)
        return salon, annulation

    salon, annulation = lancer(scenario())
    assert not salon.supprime and annulation.editions[-1]["content"] == E.TEXTE_FERMETURE_ANNULEE


def test_fermer_hors_d_un_ticket(monde):
    async def scenario():
        clic = FausseInteraction(monde, monde.modo)
        await T.BoutonFermerTicket().callback(clic)
        return clic

    assert lancer(scenario()).reponses[-1][0] == E.TEXTE_PAS_UN_TICKET


def test_probleme_resolu_par_l_auteur_ferme_le_ticket(monde):
    async def scenario():
        await ouvrir(monde, monde.thomas)
        salon = monde.serveur.categories[0].text_channels[0]
        await T.BoutonProblemeResolu().callback(FausseInteraction(monde, monde.thomas, salon))
        return salon

    salon = lancer(scenario())
    assert salon.supprime
    assert "**Thomas** a confirmé que le problème est résolu" in salon.envois[-1][0]
    assert "résolu, confirmé par son auteur" in monde.logs.envois[-1][0]


def test_seul_l_auteur_peut_dire_resolu(monde):
    async def scenario():
        await ouvrir(monde, monde.thomas)
        salon = monde.serveur.categories[0].text_channels[0]
        clic = FausseInteraction(monde, monde.modo, salon)
        await T.BoutonProblemeResolu().callback(clic)
        return clic, salon

    clic, salon = lancer(scenario())
    assert clic.reponses[-1][0] == E.TEXTE_RESOLU_RESERVE and not salon.supprime


def ticket_avec_reponses(monde, *messages):
    """Ouvre un ticket de Thomas puis ajoute (membre, il y a X heures, texte) à son historique."""
    lancer(ouvrir(monde, monde.thomas))
    salon = monde.serveur.categories[0].text_channels[0]
    maintenant = datetime.now(timezone.utc)
    for membre, heures, texte in messages:
        salon.ecrit(membre, texte, maintenant - timedelta(hours=heures))
    return salon


def test_fermeture_auto_apres_72h_sans_reponse_du_membre(monde):
    salon = ticket_avec_reponses(monde, (monde.thomas, 80, "J'ai un bug"), (monde.modo, 73, "C'est réglé ?"))
    assert lancer(T.fermer_tickets_inactifs(monde.client)) == 1
    assert salon.supprime and "fermé automatiquement" in salon.envois[-1][0]
    assert "fermé automatiquement (pas de réponse depuis 72 h)" in monde.logs.envois[-1][0]


def test_pas_de_fermeture_auto_si_le_membre_a_parle_en_dernier_ou_trop_tot(monde):
    salon = ticket_avec_reponses(monde, (monde.modo, 80, "Des nouvelles ?"), (monde.thomas, 75, "Pas encore"))
    assert lancer(T.fermer_tickets_inactifs(monde.client)) == 0
    salon.ecrit(monde.modo, "Ok, on attend", datetime.now(timezone.utc) - timedelta(hours=2))
    assert lancer(T.fermer_tickets_inactifs(monde.client)) == 0
    assert not salon.supprime


def test_fermeture_auto_desactivee_avec_zero(monde):
    monde.client.reglages = L.Reglages(roles_staff=(500,), fermeture_auto_heures=0)
    salon = ticket_avec_reponses(monde, (monde.modo, 100, "Réglé ?"))
    assert lancer(T.fermer_tickets_inactifs(monde.client)) == 0 and not salon.supprime
