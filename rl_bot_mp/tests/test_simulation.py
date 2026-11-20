"""Simule /mp_all avec de faux objets Discord (sans token ni serveur)."""

import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot_mp import logique as L
from bot_mp.commandes import TEXTE_DEJA_EN_COURS, Apercu, FicheMessage, mp_all
from bot_mp.envoi import envoyer_a_tous


def erreur_http(classe, status):
    return classe(SimpleNamespace(status=status, reason="x"), "simulée")


class FauxMembre:
    def __init__(self, uid, nom, bot=False, mp_fermes=False, en_panne=False):
        self.id, self.display_name, self.bot = uid, nom, bot
        self.mp_fermes, self.en_panne = mp_fermes, en_panne
        self.recus = []

    async def send(self, texte=None, **kwargs):
        if self.mp_fermes:
            raise erreur_http(discord.Forbidden, 403)
        if self.en_panne:
            raise erreur_http(discord.HTTPException, 500)
        self.recus.append(kwargs.get("embed") or texte)


class FauxMessage:
    def __init__(self):
        self.editions = []

    async def edit(self, **kwargs):
        self.editions.append(kwargs)


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
    def __init__(self, monde, utilisateur, expiree=False):
        self.client, self.guild, self.user = monde.client, monde.serveur, utilisateur
        self.expiree = expiree
        self.reponses, self.editions, self.modal = [], [], None
        self.response = FausseReponse(self)
        self.followup = SimpleNamespace(send=self._followup)

    async def _followup(self, texte, **kwargs):
        self.reponses.append((texte, kwargs))
        return FauxMessage()

    async def edit_original_response(self, **kwargs):
        if self.expiree:  # Discord refuse au-delà de 15 minutes
            raise erreur_http(discord.HTTPException, 401)
        self.editions.append(kwargs)

    def dernier_texte(self):
        return self.editions[-1]["content"]


@pytest.fixture
def monde(monkeypatch):
    monkeypatch.setattr(L, "PAUSE_ENTRE_MP", 0)
    membres = {
        "Admin": FauxMembre(1, "Admin"),
        "Thomas": FauxMembre(2, "Thomas"),
        "Lucas": FauxMembre(3, "Lucas"),
        "Ferme": FauxMembre(4, "Ferme", mp_fermes=True),
        "Panne": FauxMembre(5, "Panne", en_panne=True),
        "Robot": FauxMembre(6, "Robot", bot=True),
    }
    serveur = SimpleNamespace(name="Serveur RL", icon=None, chunked=True, members=list(membres.values()))
    client = SimpleNamespace(envoi_en_cours=False)
    return SimpleNamespace(client=client, serveur=serveur, membres=membres)


def lancer(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=5))


async def ouvrir_apercu(monde, texte="Tournoi samedi 21h !"):
    """/mp_all → fiche remplie → aperçu. Retourne l'interaction et la vue d'aperçu."""
    inter = FausseInteraction(monde, monde.membres["Admin"])
    await mp_all.callback(inter)
    fiche = inter.modal
    assert isinstance(fiche, FicheMessage)
    fiche.texte = SimpleNamespace(value=texte)
    await fiche.on_submit(inter)
    texte_apercu, options = inter.reponses[-1]
    return texte_apercu, options


def test_envoi_complet(monde):
    async def scenario():
        texte_apercu, options = await ouvrir_apercu(monde)
        assert "**5** membres" in texte_apercu  # le bot est ignoré
        assert options["ephemeral"] and options["embed"].description == "Tournoi samedi 21h !"
        vue = options["view"]
        assert isinstance(vue, Apercu)

        clic = FausseInteraction(monde, monde.membres["Admin"])
        await vue.envoyer.callback(clic)
        return clic

    clic = lancer(scenario())
    m = monde.membres
    for nom in ("Admin", "Thomas", "Lucas"):
        assert [e.description for e in m[nom].recus] == ["Tournoi samedi 21h !"]
    assert m["Robot"].recus == [] and m["Ferme"].recus == [] and m["Panne"].recus == []

    rapport = clic.dernier_texte()
    assert "**3/5**" in rapport and "MP fermés (1) : Ferme" in rapport and "Erreur d'envoi (1) : Panne" in rapport
    assert monde.client.envoi_en_cours is False


def test_annuler_n_envoie_rien(monde):
    async def scenario():
        _, options = await ouvrir_apercu(monde)
        clic = FausseInteraction(monde, monde.membres["Admin"])
        await options["view"].annuler.callback(clic)
        return clic

    clic = lancer(scenario())
    assert "annulé" in clic.editions[-1]["content"]
    assert all(membre.recus == [] for membre in monde.membres.values())


def test_un_seul_envoi_a_la_fois(monde):
    async def scenario():
        _, options = await ouvrir_apercu(monde)
        monde.client.envoi_en_cours = True  # un autre envoi a démarré entre-temps

        commande = FausseInteraction(monde, monde.membres["Thomas"])
        await mp_all.callback(commande)
        assert commande.modal is None and commande.reponses[-1][0] == TEXTE_DEJA_EN_COURS

        clic = FausseInteraction(monde, monde.membres["Admin"])
        await options["view"].envoyer.callback(clic)
        return clic

    clic = lancer(scenario())
    assert clic.editions[-1]["content"] == TEXTE_DEJA_EN_COURS
    assert all(membre.recus == [] for membre in monde.membres.values())


def test_rapport_en_mp_si_le_message_a_expire(monde):
    async def scenario():
        _, options = await ouvrir_apercu(monde)
        clic = FausseInteraction(monde, monde.membres["Admin"], expiree=True)
        await options["view"].envoyer.callback(clic)

    lancer(scenario())
    admin = monde.membres["Admin"]
    assert len(admin.recus) == 2  # le message à tous + le rapport
    assert "Envoi terminé" in admin.recus[-1]
    assert monde.client.envoi_en_cours is False


def test_apercu_expire(monde):
    async def scenario():
        _, options = await ouvrir_apercu(monde)
        vue = options["view"]
        await vue.on_timeout()
        return vue.message

    message = lancer(scenario())
    assert "expiré" in message.editions[-1]["content"] and message.editions[-1]["view"] is None


def test_progression_et_erreur_de_progression(monde):
    membres = [FauxMembre(i, f"m{i}") for i in range(25)]
    appels = []

    async def progression(rapport):
        appels.append(rapport.traites)
        raise RuntimeError("Discord indisponible")  # ne doit pas arrêter l'envoi

    rapport = lancer(envoyer_a_tous(membres, L.embed_mp("x", "s"), pause=0, progression=progression))
    assert rapport.recus == 25
    assert appels == [10, 20, 25]
