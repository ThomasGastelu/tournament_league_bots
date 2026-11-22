"""Salon de discussion créé par /start_tournament_rl (joueurs du tournoi + admins)."""

import asyncio
import logging
import random
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.commandes import probleme_salon_discussion
from bot_tournament_manager.deroulement import GestionnaireTournois, MessagerieDiscord
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SALON, SERVEUR, FausseMessagerie, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"
TOUTES = dict(manage_channels=True, view_channel=True, send_messages=True, embed_links=True,
              attach_files=True, read_message_history=True)


# --------------------------------------------------------------------------- #
# Faux serveur Discord
# --------------------------------------------------------------------------- #

class FauxRole:
    def __init__(self, nom: str, defaut: bool = False, managed: bool = False, **permissions) -> None:
        self.id = sum(map(ord, nom))
        self.name = nom
        self._defaut = defaut
        self.managed = managed
        self.permissions = discord.Permissions(**permissions)

    def is_default(self) -> bool:
        return self._defaut


class FauxMembre:
    def __init__(self, membre_id: int, **permissions) -> None:
        self.id = membre_id
        self.guild_permissions = discord.Permissions(**permissions)


class FausseCategorie:
    def __init__(self, nom: str = "Tournois", overwrites: dict | None = None, **permissions) -> None:
        self.name = nom
        self.overwrites = overwrites or {}
        self._permissions = discord.Permissions(**permissions)

    def permissions_for(self, _membre) -> discord.Permissions:
        return self._permissions


class FauxSalon:
    def __init__(self, nom: str) -> None:
        self.id = 4242
        self.name = nom
        self.messages: list[str] = []

    async def send(self, texte: str) -> None:
        self.messages.append(texte)


class FauxServeur:
    def __init__(self, membres: set[int], categorie=None, refus: Exception | None = None, **permissions_bot) -> None:
        self.default_role = FauxRole("@everyone", defaut=True)
        self.me = FauxMembre(1, **(permissions_bot or TOUTES))
        self.roles = [
            self.default_role,
            FauxRole("Admin", manage_guild=True),
            FauxRole("Proprio", administrator=True),
            FauxRole("Membre", send_messages=True),
            FauxRole("AutreBot", managed=True, manage_guild=True),
        ]
        self.membres = membres
        self.salon_tournoi = SimpleNamespace(category=categorie)
        self.refus = refus
        self.crees: list[tuple[str, dict]] = []
        self.salon: FauxSalon | None = None

    def get_channel_or_thread(self, salon_id: int):
        return self.salon_tournoi if salon_id == int(SALON) else None

    def get_member(self, _membre_id: int):
        return None  # cache vide, comme sans l'intent privilégié des membres

    async def fetch_member(self, membre_id: int) -> FauxMembre:
        if membre_id not in self.membres:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"),
                                   {"code": 10007, "message": "Unknown Member"})
        return FauxMembre(membre_id)

    async def create_text_channel(self, nom: str, **kwargs) -> FauxSalon:
        if self.refus:
            raise self.refus
        self.crees.append((nom, kwargs))
        self.salon = FauxSalon(nom)
        return self.salon


def etat_tournoi(nb_equipes: int = 2) -> dict:
    tournoi = tournoi_inscription(nb_equipes, TID)
    return L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=2, lance_par=ADMIN,
                         maintenant="2026-11-18T15:00:00")


def creer_salon(serveur: FauxServeur, etat: dict) -> int | None:
    client = SimpleNamespace(get_guild=lambda serveur_id: serveur if serveur_id == int(SERVEUR) else None)
    return asyncio.run(MessagerieDiscord(client).creer_salon_discussion(etat))


# --------------------------------------------------------------------------- #
# Création du salon
# --------------------------------------------------------------------------- #

def test_salon_visible_seulement_par_les_joueurs_et_les_admins(caplog):
    categorie = FausseCategorie()
    # 1021 (mate2) a quitté le serveur.
    serveur = FauxServeur(membres={1010, 1011, 1020, int(ADMIN)}, categorie=categorie)
    etat = etat_tournoi()

    with caplog.at_level(logging.WARNING):
        salon_id = creer_salon(serveur, etat)

    assert salon_id == 4242
    nom, kwargs = serveur.crees[0]
    assert nom == "💬-tournoi-test"
    assert kwargs["category"] is categorie  # dans la catégorie du salon du tournoi
    assert TID in kwargs["topic"]

    permissions = kwargs["overwrites"]
    assert permissions[serveur.default_role].view_channel is False
    bot = permissions[serveur.me]
    assert bot.view_channel and bot.send_messages and bot.embed_links
    autorises = {cible.id for cible, p in permissions.items()
                 if isinstance(cible, FauxMembre) and cible is not serveur.me and p.view_channel and p.send_messages}
    assert autorises == {1010, 1011, 1020, int(ADMIN)}  # joueurs présents + admin qui a lancé
    roles = {cible.name for cible in permissions if isinstance(cible, FauxRole) and not cible.is_default()}
    assert roles == {"Admin", "Proprio"}  # ni les membres simples, ni les rôles des autres bots
    assert all(p.attach_files for cible, p in permissions.items() if cible is not serveur.default_role)

    assert "mate2" in caplog.text  # joueur absent signalé
    bienvenue = "\n".join(serveur.salon.messages)
    assert "Tournoi test" in bienvenue
    assert all(f"<@{j}>" in bienvenue for j in ("1010", "1011", "1020", "1021"))


def test_salon_a_la_racine_si_le_salon_du_tournoi_est_hors_categorie():
    serveur = FauxServeur(membres={1010, 1011, 1020, 1021, int(ADMIN)}, categorie=None)
    assert creer_salon(serveur, etat_tournoi()) == 4242
    assert serveur.crees[0][1]["category"] is None


def test_creation_refusee_explique_la_permission_manquante(caplog):
    refus = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"),
                              {"code": 50013, "message": "Missing Permissions"})
    categorie = FausseCategorie(**{**TOUTES, "manage_channels": False})
    serveur = FauxServeur(membres={1010, 1011, 1020, 1021, int(ADMIN)}, categorie=categorie, refus=refus)

    with caplog.at_level(logging.WARNING):
        assert creer_salon(serveur, etat_tournoi()) is None
    assert "Gérer les salons" in caplog.text
    assert "Tournois" in caplog.text


def test_serveur_introuvable(caplog):
    client = SimpleNamespace(get_guild=lambda _id: None)
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(MessagerieDiscord(client).creer_salon_discussion(etat_tournoi())) is None
    assert "pas créé" in caplog.text


# --------------------------------------------------------------------------- #
# Vérification avant /start_tournament_rl
# --------------------------------------------------------------------------- #

def interaction(serveur: FauxServeur) -> SimpleNamespace:
    gestionnaire = SimpleNamespace(stockage=SimpleNamespace(charger_inscription=lambda _id: {"salon_id": SALON}))
    client = SimpleNamespace(gestionnaire=gestionnaire, user=SimpleNamespace(name="tournament_manager"),
                             lien_invitation=lambda: "https://discord.com/oauth2/authorize?client_id=1")
    return SimpleNamespace(client=client, guild=serveur)


def test_start_refuse_si_la_categorie_retire_les_permissions():
    """Cas vu en vrai : le rôle du bot a tout sur le serveur, mais la catégorie (en lecture seule)
    refuse à @everyone « Gérer les salons », « Envoyer des messages »… et rien ne les rend au bot."""
    serveur = FauxServeur(set())
    lecture_seule = discord.PermissionOverwrite(view_channel=True, manage_channels=False, send_messages=False,
                                                embed_links=False, attach_files=False)
    categorie = FausseCategorie("⚔️🏆 Tournoi Rocket League", overwrites={serveur.default_role: lecture_seule},
                                **{**TOUTES, "manage_channels": False, "send_messages": False,
                                   "embed_links": False, "attach_files": False})
    serveur.salon_tournoi.category = categorie

    message = probleme_salon_discussion(interaction(serveur), TID)

    assert "la catégorie **⚔️🏆 Tournoi Rocket League** me retire" in message
    assert ("**Gérer les salons, Envoyer des messages, Intégrer des liens, Joindre des fichiers**" in message)
    assert "« @everyone »" in message
    assert "Modifier la catégorie" in message and "rôle **tournament_manager**" in message
    assert "Paramètres du serveur" not in message  # le rôle du bot n'y est pour rien
    assert "oauth2" not in message                  # réinviter le bot ne changerait rien


def test_start_refuse_si_le_role_du_bot_n_a_pas_la_permission():
    serveur = FauxServeur(set(), categorie=FausseCategorie(**{**TOUTES, "manage_channels": False}),
                          **{**TOUTES, "manage_channels": False})
    message = probleme_salon_discussion(interaction(serveur), TID)
    assert "sur le serveur, mon rôle n'a pas **Gérer les salons**" in message
    assert "Paramètres du serveur > **Rôles** > **tournament_manager**" in message
    assert "https://discord.com/oauth2/authorize?client_id=1" in message
    assert "me retire" not in message


def test_start_accepte_si_le_bot_a_tout():
    assert probleme_salon_discussion(interaction(FauxServeur(set(), categorie=FausseCategorie(**TOUTES))), TID) is None


def test_start_hors_categorie_regarde_les_permissions_du_serveur():
    sans = FauxServeur(set(), categorie=None, **{**TOUTES, "manage_channels": False})
    assert "le serveur" in probleme_salon_discussion(interaction(sans), TID)
    assert probleme_salon_discussion(interaction(FauxServeur(set(), categorie=None)), TID) is None


# --------------------------------------------------------------------------- #
# Lancement du tournoi
# --------------------------------------------------------------------------- #

def gestionnaire_test(tmp_path: Path, messagerie: FausseMessagerie) -> tuple[GestionnaireTournois, Stockage]:
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(4, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie.declaration_auto = True
    g = GestionnaireTournois(stockage, messagerie, script_pp=Path("inutile.py"), pause_entre_rondes=0,
                             delai_declaration=0, generer_pp=faux_pp, rng=random.Random(1))
    messagerie.gestionnaire = g
    return g, stockage


def jouer(tmp_path: Path, messagerie: FausseMessagerie) -> tuple[dict, dict]:
    async def scenario():
        g, stockage = gestionnaire_test(tmp_path, messagerie)
        etat = await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
        await g.attendre(TID)
        return etat, stockage.charger_etat(TID)

    return asyncio.run(scenario())


def test_demarrer_cree_le_salon_avant_les_mp(tmp_path):
    messagerie = FausseMessagerie()
    etat_lance, etat = jouer(tmp_path, messagerie)

    assert messagerie.salons_crees == [(TID, 0)]  # une seule fois, avant le premier MP
    assert etat_lance["salon_discussion_id"] == "4242"
    assert etat["salon_discussion_id"] == "4242"  # gardé dans le JSON
    assert etat["statut"] == L.TERMINE


@pytest.mark.parametrize("echec", [None, RuntimeError("Discord en panne")])
def test_salon_pas_cree_le_tournoi_continue(tmp_path, caplog, echec):
    messagerie = FausseMessagerie(salon_discussion=echec)
    with caplog.at_level(logging.ERROR):
        etat_lance, etat = jouer(tmp_path, messagerie)

    assert etat_lance["salon_discussion_id"] is None
    assert etat["salon_discussion_id"] is None
    assert etat["statut"] == L.TERMINE
    if echec is not None:
        assert "impossible de créer le salon de discussion" in caplog.text


# --------------------------------------------------------------------------- #
# Textes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("titre, nom", [
    ("Tournoi test", "💬-tournoi-test"),
    ("Coupe Été #1 !", "💬-coupe-été-1"),
    ("  ---  ", "💬-tournoi"),
])
def test_nom_du_salon(titre, nom):
    assert M.nom_salon_discussion({"titre": titre}) == nom


def test_nom_du_salon_limite_a_100_caracteres():
    assert len(M.nom_salon_discussion({"titre": "a" * 300})) == 100


def test_bienvenue_decoupee_pour_un_gros_tournoi():
    etat = etat_tournoi(40)
    for e in etat["equipes"].values():
        e["nom"] = "Une équipe au nom vraiment très long " * 2
    textes = M.textes_bienvenue_salon(etat)

    assert len(textes) > 1
    assert all(len(t) <= M.LIMITE_MESSAGE for t in textes)
    tout = "\n".join(textes)
    assert all(f"<@{j['id']}>" in tout for _, j in L.joueurs(etat))
