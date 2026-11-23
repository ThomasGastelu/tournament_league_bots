"""/start_tournament_init_status : état des équipes avant le tournoi (validations, liste d'attente)."""

import asyncio
from types import SimpleNamespace

from bot_tournament_manager import logique as L
from bot_tournament_manager import messages as M
from bot_tournament_manager.commandes import start_tournament_init_status
from bot_tournament_manager.stockage import Stockage

from .outils import ADMIN, SERVEUR, ecrire_inscription, tournoi_inscription

TID = "1571169059024928818"
MAINTENANT = "2026-11-23T15:00:00"
FIN = "2026-11-23T15:30:00"


def inscription(nb_inscrites: int = 4, nb_attente: int = 2) -> dict:
    """Équipes 1..nb_inscrites inscrites, les suivantes en liste d'attente (dans l'ordre)."""
    tournoi = tournoi_inscription(nb_inscrites + nb_attente, TID, equipes_max=nb_inscrites, serveur_id=SERVEUR)
    for equipe in tournoi["equipes"][nb_inscrites:]:
        equipe["statut"] = "liste_attente"
    return tournoi


def init_avec_validation(tournoi: dict) -> dict:
    return L.etat_init(tournoi, L.equipes_participantes(tournoi), par=ADMIN, maintenant=MAINTENANT,
                       attente=L.equipes_en_attente(tournoi), delai_confirmation=30, fin_confirmation=FIN)


def capitaine(equipe_id: int) -> str:
    return str(1000 + equipe_id * 10)


def texte(embeds) -> str:
    return "\n".join(e.description for e in embeds)


def test_bilan_pendant_le_delai():
    tournoi = inscription()
    init = init_avec_validation(tournoi)
    for equipe_id in (1, 3):
        L.valider_participation(init, equipe_id, capitaine(equipe_id), maintenant=MAINTENANT)

    bilan = L.bilan_validations(init, tournoi)

    assert bilan["avec_validation"] and bilan["en_cours"]
    assert [e["id"] for e in bilan["validees"]] == [1, 3]
    assert bilan["validees"][0]["validee_par"] == capitaine(1)
    assert [e["id"] for e in bilan["a_valider"]] == [2, 4]
    assert [e["id"] for e in bilan["attente"]] == [5, 6]
    assert bilan["perdues"] == [] and bilan["promues"] == []


def test_bilan_apres_le_delai_avec_liste_d_attente_montee():
    tournoi = inscription()
    init = init_avec_validation(tournoi)
    for equipe_id in (1, 3):
        L.valider_participation(init, equipe_id, capitaine(equipe_id), maintenant=MAINTENANT)
    L.terminer_confirmation(init, fin_suivante="2026-11-23T16:00:00")
    L.valider_participation(init, 5, capitaine(5), maintenant=MAINTENANT)

    bilan = L.bilan_validations(init, tournoi)

    assert bilan["en_cours"]  # les équipes montées ont un nouveau délai
    assert [e["id"] for e in bilan["validees"]] == [1, 3, 5]
    assert [e["id"] for e in bilan["a_valider"]] == [6]
    # Les équipes perdues ne sont plus dans l'init : nom et joueurs viennent du fichier d'inscription.
    assert [(e["id"], e["nom"]) for e in bilan["perdues"]] == [(2, "Equipe2"), (4, "Equipe4")]
    assert bilan["perdues"][0]["joueurs"]
    assert bilan["attente"] == [] and bilan["promues"] == [5, 6]


def test_bilan_equipe_perdue_sans_fichier_d_inscription():
    init = init_avec_validation(inscription())
    L.valider_participation(init, 1, capitaine(1), maintenant=MAINTENANT)
    L.terminer_confirmation(init)

    bilan = L.bilan_validations(init)

    assert [e["nom"] for e in bilan["perdues"]] == ["Équipe #2", "Équipe #3", "Équipe #4"]
    assert not bilan["en_cours"]


def test_bilan_sans_validation():
    tournoi = inscription(nb_attente=0)
    init = L.etat_init(tournoi, L.equipes_participantes(tournoi), par=ADMIN, maintenant=MAINTENANT)

    bilan = L.bilan_validations(init, tournoi)

    assert not bilan["avec_validation"] and not bilan["en_cours"]
    assert [e["id"] for e in bilan["a_valider"]] == [1, 2, 3, 4]


def test_embeds_montrent_qui_a_valide_et_la_liste_d_attente():
    tournoi = inscription()
    init = init_avec_validation(tournoi)
    L.valider_participation(init, 1, capitaine(1), maintenant=MAINTENANT)

    contenu = texte(M.embeds_init_status(init, L.bilan_validations(init, tournoi)))

    assert "Validation en cours" in contenu and "30 minutes" in contenu
    assert "**1/4** équipe" in contenu
    assert "**✅ Ont validé (1)**" in contenu and "validé par" in contenu
    assert "**⏳ Pas encore validé (3)**" in contenu
    assert "**📋 Liste d'attente (2)**" in contenu and "`1.` **Equipe5**" in contenu
    assert "👑" in contenu
    assert "Places perdues" not in contenu and "déjà lancé" not in contenu


def test_embeds_signalent_les_places_perdues_et_les_equipes_montees():
    tournoi = inscription()
    init = init_avec_validation(tournoi)
    for equipe_id in (1, 2, 3):
        L.valider_participation(init, equipe_id, capitaine(equipe_id), maintenant=MAINTENANT)
    L.terminer_confirmation(init, fin_suivante="2026-11-23T16:00:00")
    L.valider_participation(init, 5, capitaine(5), maintenant=MAINTENANT)
    L.terminer_confirmation(init)

    contenu = texte(M.embeds_init_status(init, L.bilan_validations(init, tournoi)))

    assert "Validation terminée" in contenu
    assert "**4/4** équipes ont validé" in contenu
    assert "**Equipe5** ⬆️" in contenu and "1 équipe montée" in contenu
    assert "**❌ Places perdues (1)**" in contenu and "**Equipe4**" in contenu
    assert "**📋 Liste d'attente (1)**" in contenu and "`1.` **Equipe6**" in contenu


def test_embeds_signalent_un_tournoi_deja_lance():
    tournoi = inscription(nb_attente=0)
    init = L.etat_init(tournoi, L.equipes_participantes(tournoi), par=ADMIN, maintenant=MAINTENANT)

    contenu = texte(M.embeds_init_status(init, L.bilan_validations(init, tournoi), {"statut": L.EN_COURS}))

    assert "Pas de validation" in contenu and "**Équipes (4)**" in contenu
    assert "déjà lancé" in contenu and f"/start_tournament_rl_status id_tournoi:{TID}" in contenu


class FausseReponse:
    def __init__(self) -> None:
        self.envois = []

    def is_done(self) -> bool:
        return False

    async def send_message(self, texte, **kwargs) -> None:
        self.envois.append((texte, kwargs))


def interaction(stockage: Stockage, serveur: str = SERVEUR) -> SimpleNamespace:
    return SimpleNamespace(client=SimpleNamespace(gestionnaire=SimpleNamespace(stockage=stockage)),
                           guild_id=int(serveur), response=FausseReponse())


def test_commande_affiche_l_etat_en_ephemere(tmp_path):
    tournoi = inscription()
    ecrire_inscription(tmp_path / "inscriptions", tournoi)
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    stockage.sauvegarder_init(init_avec_validation(tournoi))
    i = interaction(stockage)

    asyncio.run(start_tournament_init_status.callback(i, f" {TID} "))

    [(texte_envoye, kwargs)] = i.response.envois
    assert texte_envoye is None and kwargs["ephemeral"]
    assert "**0/4** équipe" in texte(kwargs["embeds"])


def test_commande_refuse_un_tournoi_sans_init_ou_d_un_autre_serveur(tmp_path):
    tournoi = inscription()
    stockage = Stockage(tmp_path / "inscriptions", tmp_path / "data")
    i = interaction(stockage)
    asyncio.run(start_tournament_init_status.callback(i, TID))
    stockage.sauvegarder_init(init_avec_validation(tournoi))
    autre = interaction(stockage, serveur="999")
    asyncio.run(start_tournament_init_status.callback(autre, TID))

    for faux in (i, autre):
        [(texte_envoye, _)] = faux.response.envois
        assert texte_envoye.startswith("❌ Pas de `/start_tournament_init`")
