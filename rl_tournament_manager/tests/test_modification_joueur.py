"""/edit_player_tournament_rl : modifier un joueur pendant le tournoi."""

import asyncio
import logging
import random
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.deroulement import GestionnaireTournois, MessagerieDiscord
from bot_tournament_manager.simulateur import ObservateurSimule
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, FausseMessagerie, attendre_que, ecrire_inscription, faux_pp, tournoi_inscription

TID = "1571169059024928818"
REMPLACANT = "5000"


# --------------------------------------------------------------------------- #
# Règles (logique.modifier_joueur)
# --------------------------------------------------------------------------- #
# Équipe 1 : cap1 (1010, capitaine, Cap1RL) et mate1 (1011, Mate1RL) ; équipe 2 : 1020 et 1021.

def etat_2_equipes() -> dict:
    tournoi = tournoi_inscription(2, TID)
    return L.nouvel_etat(tournoi, L.equipes_participantes(tournoi), nombre_de_rondes=1, lance_par=ADMIN,
                         maintenant="2026-11-18T15:00:00")


def modifier(etat: dict, joueur_id: str, **valeurs) -> dict:
    return L.modifier_joueur(etat, joueur_id, par=ADMIN, maintenant="2026-11-18T16:00:00", **valeurs)


def test_changer_le_pseudo_en_jeu():
    etat = etat_2_equipes()
    modif = modifier(etat, "1011", pseudo_jeu="  NouveauRL ")

    assert L.trouver_joueur(etat, "1011")[1]["pseudo_jeu"] == "NouveauRL"
    assert modif["changements"] == {"pseudo_jeu": ["Mate1RL", "NouveauRL"]}
    assert modif["equipe"] == 1 and modif["par"] == ADMIN and modif["joueur"] == "1011"
    assert etat["modifications"] == [modif]  # historique dans le JSON


def test_pseudo_en_jeu_deja_pris_refuse():
    etat = etat_2_equipes()
    with pytest.raises(L.ErreurTournoi, match="déjà celui de"):
        modifier(etat, "1011", pseudo_jeu="cap2rl")  # majuscules ignorées, comme pour les couleurs
    assert L.trouver_joueur(etat, "1011")[1]["pseudo_jeu"] == "Mate1RL"
    assert etat["modifications"] == []


def test_changer_pseudo_et_nom_d_equipe():
    etat = etat_2_equipes()
    modif = modifier(etat, "1011", pseudo="Mathéo", nom_equipe="Les Tomates")
    assert modif["changements"] == {"pseudo": ["mate1", "Mathéo"], "nom_equipe": ["Equipe1", "Les Tomates"]}
    assert etat["equipes"]["1"]["nom"] == "Les Tomates"

    with pytest.raises(L.ErreurTournoi, match="Une autre équipe"):
        modifier(etat, "1011", nom_equipe="equipe2")


def test_nouveau_capitaine():
    etat = etat_2_equipes()
    modif = modifier(etat, "1011", devient_capitaine=True)
    assert etat["equipes"]["1"]["capitaine_id"] == "1011"
    assert modif["changements"] == {"capitaine": ["1010", "1011"]}

    with pytest.raises(L.ErreurTournoi, match="Rien à changer"):
        modifier(etat, "1011", devient_capitaine=True)  # déjà capitaine
    with pytest.raises(L.ErreurTournoi, match="nouveau"):
        modifier(etat, "1011", devient_capitaine=False)


def test_remplacer_le_capitaine():
    etat = etat_2_equipes()
    modif = modifier(etat, "1010", remplacant=(REMPLACANT, "Remplaçant"))

    equipe = etat["equipes"]["1"]
    assert [j["id"] for j in equipe["joueurs"]] == [REMPLACANT, "1011"]
    assert equipe["joueurs"][0] == {"id": REMPLACANT, "pseudo": "Remplaçant", "pseudo_jeu": None}
    assert equipe["capitaine_id"] == REMPLACANT  # il reprend le rôle de capitaine
    assert modif["changements"]["joueur"] == ["1010", REMPLACANT]
    assert modif["changements"]["capitaine"] == ["1010", REMPLACANT]
    assert modif["changements"]["pseudo_jeu"] == ["Cap1RL", None]  # l'ancien pseudo en jeu ne vaut plus
    assert modif["ancien_joueur"]["pseudo"] == "cap1"


def test_remplacant_avec_ses_pseudos():
    etat = etat_2_equipes()
    modifier(etat, "1011", remplacant=(REMPLACANT, "pseudo_discord"), pseudo="Rempla", pseudo_jeu="RemplaRL")
    assert L.trouver_joueur(etat, REMPLACANT)[1] == {"id": REMPLACANT, "pseudo": "Rempla", "pseudo_jeu": "RemplaRL"}
    assert etat["equipes"]["1"]["capitaine_id"] == "1010"  # le capitaine ne change pas


@pytest.mark.parametrize("joueur, valeurs, erreur", [
    ("1011", {"remplacant": ("1020", "cap2")}, "joue déjà"),
    ("4242", {"pseudo": "x"}, "ne joue pas dans ce tournoi"),
    ("1011", {"pseudo": "mate1"}, "Rien à changer"),
    ("1011", {}, "Rien à changer"),
    ("1011", {"pseudo_jeu": "x" * 33}, "32 caractères"),
])
def test_modifications_refusees(joueur, valeurs, erreur):
    etat = etat_2_equipes()
    with pytest.raises(L.ErreurTournoi, match=erreur):
        modifier(etat, joueur, **valeurs)


# --------------------------------------------------------------------------- #
# Pendant un vrai tournoi (simulateur + fausse messagerie)
# --------------------------------------------------------------------------- #

def creer(tmp_path: Path, *, sans_gagnant: float = 0, observateur=None):
    """Tournoi à 2 équipes (1 zone). Les capitaines ne cliquent pas tout seuls."""
    ecrire_inscription(tmp_path / "inscriptions", tournoi_inscription(2, TID))
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    messagerie = FausseMessagerie(clic_auto=False)
    observateur = observateur or ObservateurSimule(duree_min=0, duree_max=0, proba_sans_gagnant=sans_gagnant,
                                                   proba_couleurs_inversees=0, rng=random.Random(1))
    g = GestionnaireTournois(stockage, observateur, messagerie, script_pp=Path("inutile.py"), pause_entre_rondes=0,
                             rappel_clic_pp=60, attente_clic_pp_max=120, generer_pp=faux_pp, rng=random.Random(1))
    messagerie.gestionnaire = g
    return g, stockage, messagerie


async def lancer(g, stockage, messagerie) -> tuple[dict, dict]:
    """Lance le tournoi et attend les MP du round 1. Renvoie (état, match de la zone 1)."""
    await g.demarrer(TID, 1, serveur_id=SERVEUR, lance_par=ADMIN)
    await attendre_que(lambda: messagerie.boutons_pp)
    etat = stockage.charger_etat(TID)
    return etat, etat["rondes"][0]["matchs"][0]


def test_nouveau_capitaine_recoit_le_bouton_partie_creee(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path)
        etat, match = await lancer(g, stockage, messagerie)
        equipe_a = L.equipe(etat, match["equipe_a"])
        ancien = equipe_a["capitaine_id"]
        nouveau = next(j["id"] for j in equipe_a["joueurs"] if j["id"] != ancien)

        _, _, notes = await g.modifier_joueur(TID, nouveau, serveur_id=SERVEUR, par=ADMIN, devient_capitaine=True)

        assert (nouveau, (1, 1)) in messagerie.boutons_pp
        assert any("Vous devez créer la partie privée" in t for t in messagerie.mps_de(nouveau))
        assert any("Tu n'es plus capitaine" in t and "Si tu as déjà créé" in t for t in messagerie.mps_de(ancien))
        assert any("Partie privée créée" in n for n in notes)
        with pytest.raises(L.ErreurTournoi, match="Seul le capitaine"):
            await g.signaler_pp_creee(TID, 1, 1, par=ancien)  # son ancien bouton est refusé
        await g.signaler_pp_creee(TID, 1, 1, par=nouveau)
        await g.attendre(TID)
        return stockage.charger_etat(TID), messagerie, nouveau

    etat, messagerie, nouveau = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert etat["rondes"][0]["matchs"][0]["pp_creee_par"] == nouveau
    assert len(messagerie.journaux) == 1 and "Capitaine" in messagerie.journaux[0]


def test_remplacant_pendant_un_match(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path)
        etat, match = await lancer(g, stockage, messagerie)
        remplace = L.equipe(etat, match["equipe_b"])["joueurs"][1]["id"]

        etat, modif, notes = await g.modifier_joueur(TID, remplace, serveur_id=SERVEUR, par=ADMIN,
                                                     remplacant=(REMPLACANT, "Remplaçant"), pseudo_jeu="RemplaRL")
        assert messagerie.acces_salon == [(REMPLACANT, remplace)]
        textes = messagerie.mps_de(REMPLACANT)
        assert any("tu remplaces" in t for t in textes)
        assert any(match["pp"]["nom"] in t and "Rejoins-la" in t for t in textes)  # infos du match en cours
        assert any("Un admin t'a remplacé" in t for t in messagerie.mps_de(remplace))
        reponse = M.reponse_modification(etat, modif, notes)
        assert f"<@{REMPLACANT}>" in reponse and "accès au salon" in reponse

        nb_mp_ancien = len(messagerie.mps_de(remplace))
        await g.signaler_pp_creee(TID, 1, 1, par=L.equipe(etat, match["equipe_a"])["capitaine_id"])
        await g.attendre(TID)
        return stockage.charger_etat(TID), messagerie, remplace, nb_mp_ancien

    etat, messagerie, remplace, nb_mp_ancien = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    textes = messagerie.mps_de(REMPLACANT)
    assert any("a créé la partie privée" in t for t in textes)
    assert any("Match terminé" in t for t in textes) and any("est terminé" in t for t in textes)
    assert len(messagerie.mps_de(remplace)) == nb_mp_ancien  # l'ancien joueur ne reçoit plus rien
    assert L.trouver_joueur(etat, REMPLACANT)[1]["pseudo_jeu"] == "RemplaRL"
    assert [m["changements"]["joueur"] for m in etat["modifications"]] == [[remplace, REMPLACANT]]


def test_remplacant_sans_gerer_les_roles(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path)
        messagerie.acces_salon_possible = False
        etat, match = await lancer(g, stockage, messagerie)
        remplace = L.equipe(etat, match["equipe_b"])["joueurs"][1]["id"]
        _, _, notes = await g.modifier_joueur(TID, remplace, serveur_id=SERVEUR, par=ADMIN,
                                              remplacant=(REMPLACANT, "Remplaçant"))
        await g.arreter(TID, serveur_id=SERVEUR, par=ADMIN)
        return notes

    notes = asyncio.run(scenario())
    assert any("Gérer les rôles" in n and "à la main" in n for n in notes)
    assert any("pas de pseudo en jeu" in n for n in notes)


def test_remplacant_d_un_match_a_valider_peut_declarer(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path, sans_gagnant=1)
        etat, match = await lancer(g, stockage, messagerie)
        equipe_a, equipe_b = match["equipe_a"], match["equipe_b"]
        await g.signaler_pp_creee(TID, 1, 1, par=L.equipe(etat, equipe_a)["capitaine_id"])
        await attendre_que(lambda: messagerie.boutons)  # le bot n'a pas le score : déclarations
        remplace = L.equipe(etat, equipe_b)["joueurs"][1]["id"]

        await g.modifier_joueur(TID, remplace, serveur_id=SERVEUR, par=ADMIN, remplacant=(REMPLACANT, "Remplaçant"))
        assert (REMPLACANT, (1, 1, equipe_b)) in messagerie.boutons
        with pytest.raises(L.ErreurTournoi, match="ne joues pas"):
            await g.declarer_score(TID, 1, 1, equipe_b, 29, 30, par=remplace)
        await g.declarer_score(TID, 1, 1, equipe_a, 30, 29, par=L.equipe(etat, equipe_a)["capitaine_id"])
        await g.declarer_score(TID, 1, 1, equipe_b, 29, 30, par=REMPLACANT)
        await g.attendre(TID)
        return stockage.charger_etat(TID)

    etat = asyncio.run(scenario())
    assert etat["statut"] == L.TERMINE
    assert etat["rondes"][0]["matchs"][0]["source_resultat"] == L.SOURCE_DECLARATIONS


class ObservateurEspion:
    """Garde les parties à observer ; ne trouve jamais le score."""

    def __init__(self) -> None:
        self.parties = []

    async def observer(self, partie):
        self.parties.append(partie)
        return {"statut": "partie introuvable", "winner_team_num": None}


def test_pseudo_en_jeu_change_avant_le_clic_arrive_a_l_observateur(tmp_path):
    async def scenario():
        espion = ObservateurEspion()
        g, stockage, messagerie = creer(tmp_path, observateur=espion)
        etat, match = await lancer(g, stockage, messagerie)
        equipe_a = L.equipe(etat, match["equipe_a"])
        coequipier = next(j["id"] for j in equipe_a["joueurs"] if j["id"] != equipe_a["capitaine_id"])

        _, _, notes = await g.modifier_joueur(TID, coequipier, serveur_id=SERVEUR, par=ADMIN, pseudo_jeu="NouveauRL")
        await g.signaler_pp_creee(TID, 1, 1, par=equipe_a["capitaine_id"])
        await attendre_que(lambda: espion.parties)
        await g.arreter(TID, serveur_id=SERVEUR, par=ADMIN)
        return espion.parties[0], notes

    partie, notes = asyncio.run(scenario())
    assert "NouveauRL" in partie.pseudos_bleu
    assert any("prochain score" in n for n in notes)


def test_tournoi_arrete_pas_modifiable(tmp_path):
    async def scenario():
        g, stockage, messagerie = creer(tmp_path)
        await lancer(g, stockage, messagerie)
        await g.arreter(TID, serveur_id=SERVEUR, par=ADMIN)
        with pytest.raises(L.ErreurTournoi, match="pas en cours"):
            await g.modifier_joueur(TID, "1011", serveur_id=SERVEUR, par=ADMIN, pseudo="x")
        with pytest.raises(L.ErreurTournoi, match="Aucun tournoi"):
            await g.modifier_joueur(TID, "1011", serveur_id="123", par=ADMIN, pseudo="x")

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Accès au salon de discussion (Discord)
# --------------------------------------------------------------------------- #

class FauxSalonDiscussion:
    def __init__(self, permissions: dict, refus: Exception | None = None) -> None:
        self.overwrites = permissions
        self.refus = refus
        self.modifications: list[dict] = []

    async def edit(self, **kwargs) -> None:
        if self.refus:
            raise self.refus
        self.modifications.append(kwargs)


def changer_acces(salon: FauxSalonDiscussion) -> bool:
    client = SimpleNamespace(get_channel=lambda salon_id: salon if salon_id == 4242 else None)
    etat = {"tournoi_id": TID, "titre": "Tournoi test", "salon_discussion_id": "4242"}
    return asyncio.run(MessagerieDiscord(client).changer_acces_salon(etat, ajouter=REMPLACANT, retirer="1021"))


def test_acces_salon_remplacant_ajoute_ancien_retire():
    ancien = discord.Object(id=1021, type=discord.Member)
    admins = discord.Object(id=77, type=discord.Role)
    salon = FauxSalonDiscussion({ancien: discord.PermissionOverwrite(view_channel=True),
                                 admins: discord.PermissionOverwrite(view_channel=True)})

    assert changer_acces(salon) is True
    permissions = salon.modifications[0]["overwrites"]
    assert {cible.id for cible in permissions} == {77, int(REMPLACANT)}
    nouveau = next(cible for cible in permissions if cible.id == int(REMPLACANT))
    assert nouveau.type is discord.Member
    assert permissions[nouveau].view_channel and permissions[nouveau].send_messages


def test_acces_salon_sans_gerer_les_roles(caplog):
    refus = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"),
                              {"code": 50013, "message": "Missing Permissions"})
    with caplog.at_level(logging.WARNING):
        assert changer_acces(FauxSalonDiscussion({}, refus=refus)) is False
    assert "Gérer les rôles" in caplog.text
