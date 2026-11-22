"""Déroulement d'un tournoi : rounds, matchs, déclarations des scores, messages.

Une tâche asyncio par tournoi en cours. L'état est relu et réécrit dans le
JSON à chaque étape : si le bot redémarre, reprendre() relance les tournois
là où ils en étaient.

Pour chaque round :
  1. tirage (round 1) ou rotation des zones (rounds suivants) ;
  2. parties privées tomato_A, tomato_B… (une lettre par zone, voir pp.py) ;
  3. tous les matchs se jouent en même temps : MP au capitaine de l'équipe A
     (créer la partie, bouton « Partie privée créée ») et aux autres joueurs (la
     rejoindre) ;
  4. au clic du capitaine (ou, sans clic, après ATTENTE_CLIC_PP_MAX, avec une alerte),
     les autres joueurs sont prévenus et le délai DELAI_DECLARATION (6 min par défaut)
     démarre. Son départ est noté dans le JSON : après un redémarrage, le bot attend
     seulement le temps qui reste ;
  5. délai passé : MP aux joueurs pour qu'ils déclarent le score (bouton). Le résultat
     est validé quand les deux équipes déclarent le même score ; un admin peut toujours
     trancher avec /set_result_tournament_rl ;
  6. quand toutes les zones ont un score : récap du round (scores et classement) dans le salon
     des résultats (SALON_RESULTATS), pause, puis round suivant.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import discord

from . import logique as L
from . import messages as M
from .journal import HORS_JOURNAL
from .pp import generer_parties
from .stockage import Stockage

if TYPE_CHECKING:
    from .simulation import Simulation

log = logging.getLogger(__name__)


def maintenant() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Messagerie(Protocol):
    """Envoi des messages Discord (remplacé par une fausse messagerie dans les tests)."""

    async def pret(self) -> None: ...

    async def mp(self, etat: dict, joueur_id: str, texte: str, secours: str | None = None,
                 declaration: tuple[int, int, int] | None = None,
                 pp_creee: tuple[int, int] | None = None) -> bool:
        """MP à un joueur. Boutons : `declaration` = (round, zone, équipe) → « Déclarer le score » ;
        `pp_creee` = (round, zone) → « Partie privée créée »."""
        ...

    async def annonce(self, etat: dict, texte: str | None = None,
                      embeds: list[discord.Embed] | None = None) -> None:
        """Message dans le salon des annonces (public)."""
        ...

    async def alerte(self, etat: dict, texte: str | None = None,
                     embeds: list[discord.Embed] | None = None) -> None:
        """Alerte pour les admins : LOG_CHANNEL, ou MP à l'admin qui a lancé le tournoi."""
        ...

    async def creer_salon_discussion(self, etat: dict) -> int | None:
        """Salon texte du tournoi, visible seulement par ses joueurs, les admins et le bot.
        Renvoie son ID, ou None s'il n'a pas pu être créé."""
        ...

    async def changer_acces_salon(self, etat: dict, *, ajouter: str | None = None,
                                  retirer: str | None = None) -> bool:
        """Donne (`ajouter`) ou retire (`retirer`) l'accès au salon de discussion. True si c'est fait."""
        ...

    async def supprimer_salon_discussion(self, etat: dict, salon_id: str) -> bool:
        """Supprime un salon de discussion du tournoi (/reset_tournament_rl). True s'il n'existe plus."""
        ...

    async def journal(self, texte: str) -> None:
        """Message d'information dans LOG_CHANNEL, sans mentionner personne."""
        ...

    async def resultats(self, etat: dict, texte: str | None = None,
                        embeds: list[discord.Embed] | None = None) -> None:
        """Salon des résultats (SALON_RESULTATS) : lancement du tournoi, récap de chaque round terminé."""
        ...


class GestionnaireTournois:
    def __init__(
        self,
        stockage: Stockage,
        messagerie: Messagerie,
        *,
        pause_entre_rondes: float = 60,
        rappel_clic_pp: float = 180,
        attente_clic_pp_max: float = 600,
        delai_declaration: float = 360,
        pp_forcee_zone_2: tuple[str, str] | None = None,
        generer_pp: Callable[[int, Path], list[dict]] = generer_parties,
        rng: random.Random | None = None,
        simulation: Simulation | None = None,
    ) -> None:
        self.stockage = stockage
        self.messagerie = messagerie
        self.pause_entre_rondes = pause_entre_rondes
        self.rappel_clic_pp = rappel_clic_pp
        self.attente_clic_pp_max = attente_clic_pp_max
        self.delai_declaration = delai_declaration
        self.pp_forcee_zone_2 = pp_forcee_zone_2
        self.generer_pp = generer_pp
        self.rng = rng or random.Random()
        self.simulation = simulation  # SIMULATION=1 : clics et déclarations automatiques (simulation.py)
        if simulation is not None:
            simulation.brancher(self)
        self._taches: dict[str, asyncio.Task] = {}
        self._taches_matchs: dict[tuple[str, int, int], asyncio.Task] = {}
        self._validations: dict[str, asyncio.Event] = {}
        self._pp_creees: dict[tuple[str, int, int], asyncio.Event] = {}  # clic « Partie privée créée »

    # ------------------------------------------------------------------- #
    # Commandes
    # ------------------------------------------------------------------- #

    def est_actif(self, tournoi_id: str) -> bool:
        tache = self._taches.get(tournoi_id)
        return tache is not None and not tache.done()

    async def demarrer(self, tournoi_id: str, nombre_de_rondes: int, *, serveur_id: str, lance_par: str,
                       golden_round: int = 1) -> dict:
        tournoi_id = tournoi_id.strip()
        async with self.stockage.verrou(tournoi_id):
            tournoi = self.stockage.charger_inscription(tournoi_id)
            if tournoi is None or tournoi.get("serveur_id") != serveur_id:
                raise L.ErreurTournoi(f"Aucun tournoi avec l'ID `{tournoi_id}` sur ce serveur.")
            ancien = self.stockage.charger_etat(tournoi_id)
            if ancien and ancien["statut"] == L.EN_COURS:
                raise L.ErreurTournoi("Ce tournoi est déjà en cours. Arrête-le d'abord avec `/stop_tournament_rl`.")
            equipes = L.equipes_participantes(tournoi)
            etat = L.nouvel_etat(tournoi, equipes, nombre_de_rondes=nombre_de_rondes,
                                 lance_par=lance_par, maintenant=maintenant(), golden_round=golden_round)
            if ancien:
                self.stockage.archiver_etat(tournoi_id, ancien.get("lance_le") or maintenant())
            self.stockage.sauvegarder_etat(etat)
        # Avant le premier round : le salon existe quand les joueurs reçoivent leurs MP.
        await self._creer_salon_discussion(etat)
        # Séparateur + lancement dans le salon des résultats, avant le récap du premier round.
        await self.messagerie.resultats(etat, texte=M.texte_lancement_tournoi(etat))
        self._lancer(tournoi_id)
        return etat

    async def _creer_salon_discussion(self, etat: dict) -> None:
        """Crée le salon de discussion et garde son ID dans le JSON. Un échec ne bloque pas le tournoi."""
        tournoi_id = etat["tournoi_id"]
        try:
            salon_id = await self.messagerie.creer_salon_discussion(etat)
        except Exception:
            log.exception("Tournoi %s : impossible de créer le salon de discussion", tournoi_id)
            return
        if not salon_id:
            return
        etat["salon_discussion_id"] = str(salon_id)
        async with self.stockage.verrou(tournoi_id):
            sur_disque = self.stockage.charger_etat(tournoi_id)
            if sur_disque is not None:
                sur_disque["salon_discussion_id"] = str(salon_id)
                self.stockage.sauvegarder_etat(sur_disque)
        log.info("Tournoi %s : salon de discussion %s créé", tournoi_id, salon_id)

    def reprendre(self) -> list[str]:
        """Relance les tournois en cours (au démarrage du bot)."""
        ids = [e["tournoi_id"] for e in self.stockage.lister_etats() if e.get("statut") == L.EN_COURS]
        for tournoi_id in ids:
            self._lancer(tournoi_id)
        return ids

    async def arreter(self, tournoi_id: str, *, serveur_id: str, par: str) -> dict:
        tournoi_id = tournoi_id.strip()
        async with self.stockage.verrou(tournoi_id):
            etat = self._etat_du_serveur(tournoi_id, serveur_id)
            if etat["statut"] != L.EN_COURS:
                raise L.ErreurTournoi("Ce tournoi n'est pas en cours.")
            L.arreter(etat, par=par, maintenant=maintenant())
            self.stockage.sauvegarder_etat(etat)
        await self._annuler_taches(tournoi_id)
        log.info("Tournoi %s arrêté par %s", tournoi_id, par)

        await self.messagerie.annonce(etat, texte=M.texte_arret(etat),
                                      embeds=M.embeds_classement(etat, f"📊 {etat['titre']} — classement à l'arrêt"))
        for e, joueur in L.joueurs(etat):
            await self.messagerie.mp(etat, joueur["id"], M.mp_arret(etat, e["id"]))
        return etat

    def a_reinitialiser(self, tournoi_id: str, serveur_id: str) -> tuple[dict, list[str], list[Path]]:
        """Ce que /reset_tournament_rl effacerait : (état le plus récent, salons de discussion, fichiers).
        L'état peut venir d'une archive si seul un ancien lancement reste."""
        tournoi_id = tournoi_id.strip()
        try:
            fichiers = self.stockage.fichiers_du_tournoi(tournoi_id)
        except ValueError:
            fichiers = []
        actuel = self.stockage.charger_etat(tournoi_id)
        etats = ([actuel] if actuel else []) + (self.stockage.charger_archives(tournoi_id) if fichiers else [])
        if not etats or etats[0].get("serveur_id") != serveur_id:
            raise L.ErreurTournoi(f"Rien à remettre à zéro pour l'ID `{tournoi_id}` sur ce serveur "
                                  "(aucun tournoi lancé avec cet ID).")
        return etats[0], L.salons_discussion(etats), fichiers

    async def reinitialiser(self, tournoi_id: str, *, serveur_id: str, par: str, garder_salon: bool = False) -> dict:
        """/reset_tournament_rl : arrête le tournoi s'il tourne, efface tout ce que ce bot a gardé sur lui
        (état, parties privées, archives) et supprime ses salons de discussion (sauf `garder_salon`).
        Le fichier d'inscription n'est jamais touché : le tournoi peut être relancé de zéro."""
        tournoi_id = tournoi_id.strip()
        async with self.stockage.verrou(tournoi_id):
            etat, salons, _ = self.a_reinitialiser(tournoi_id, serveur_id)
            etait_en_cours = etat.get("statut") == L.EN_COURS
            if etait_en_cours:
                # Les tâches qui reliraient l'état avant d'être annulées voient un tournoi arrêté.
                L.arreter(etat, par=par, maintenant=maintenant())
                self.stockage.sauvegarder_etat(etat)
        await self._annuler_taches(tournoi_id)
        async with self.stockage.verrou(tournoi_id):
            supprimes = self.stockage.supprimer_tournoi(tournoi_id)
        self._validations.pop(tournoi_id, None)
        for cle in [c for c in self._pp_creees if c[0] == tournoi_id]:
            del self._pp_creees[cle]
        log.info("Tournoi %s remis à zéro par %s : %s fichier(s) effacé(s)", tournoi_id, par, len(supprimes))

        bilan = {"tournoi_id": tournoi_id, "titre": etat["titre"], "etait_en_cours": etait_en_cours,
                 "nb_fichiers": len(supprimes), "salons_supprimes": [], "salons_gardes": [], "salons_en_echec": []}
        for salon_id in salons:
            if garder_salon:
                bilan["salons_gardes"].append(salon_id)
                continue
            try:
                ok = await self.messagerie.supprimer_salon_discussion(etat, salon_id)
            except Exception:
                log.exception("Tournoi %s : impossible de supprimer le salon de discussion %s", tournoi_id, salon_id)
                ok = False
            bilan["salons_supprimes" if ok else "salons_en_echec"].append(salon_id)

        if etait_en_cours:
            await self.messagerie.annonce(etat, texte=M.texte_reinitialisation(etat, par))
            for _, joueur in L.joueurs(etat):
                await self.messagerie.mp(etat, joueur["id"], M.mp_reinitialisation(etat))
        await self.messagerie.journal(M.texte_reinitialisation(etat, par))
        return bilan

    async def valider_resultat(self, tournoi_id: str, zone: int, gagnant_id: int, score_gagnant: int,
                               score_perdant: int, *, serveur_id: str, par: str) -> tuple[dict, dict]:
        """Résultat fixé par un admin (match « à valider », ou bloqué)."""
        tournoi_id = tournoi_id.strip()
        async with self.stockage.verrou(tournoi_id):
            etat = self._etat_du_serveur(tournoi_id, serveur_id)
            ronde = L.ronde_actuelle(etat)
            if etat["statut"] != L.EN_COURS or ronde is None or ronde["statut"] != L.RONDE_EN_COURS:
                raise L.ErreurTournoi("Aucun round en cours pour ce tournoi.")
            match = L.trouver_match(ronde, zone)
            L.valider_manuellement(etat, ronde["numero"], match, gagnant_id, score_gagnant, score_perdant,
                                   par=par, maintenant=maintenant())
            self.stockage.sauvegarder_etat(etat)

        # Si le bot attendait encore la fin de ce match, il n'a plus rien à faire.
        tache = self._taches_matchs.get((tournoi_id, ronde["numero"], zone))
        if tache is not None and tache is not asyncio.current_task():
            tache.cancel()
        log.info("Tournoi %s, round %s, zone %s : résultat validé par %s", tournoi_id, ronde["numero"], zone, par)
        await self._annoncer_fin_match(etat, ronde["numero"], match)
        self._validation(tournoi_id).set()
        return etat, match

    async def signaler_pp_creee(self, tournoi_id: str, numero: int, zone: int, *, par: str) -> str:
        """Le capitaine a cliqué sur « Partie privée créée ». Renvoie la réponse à lui afficher."""
        async with self.stockage.verrou(tournoi_id):
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None:
                raise L.ErreurTournoi("Ce tournoi n'existe plus.")
            if etat["statut"] != L.EN_COURS:
                raise L.ErreurTournoi("Ce tournoi n'est plus en cours.")
            match = L.trouver_match(L.trouver_ronde(etat, numero), zone)
            equipe_a = L.equipe(etat, match["equipe_a"])
            if par != equipe_a["capitaine_id"]:
                raise L.ErreurTournoi(f"Seul le capitaine de {equipe_a['nom']} peut utiliser ce bouton.")
            nouveau = L.marquer_pp_creee(match, par=par, maintenant=maintenant())
            if nouveau:
                self.stockage.sauvegarder_etat(etat)

        evenement = self._pp_creees.get((tournoi_id, numero, zone))
        if evenement is not None:
            evenement.set()  # le délai avant la demande de score démarre
        if nouveau:
            log.info("Tournoi %s, round %s, zone %s : partie privée créée (clic de %s)", tournoi_id, numero, zone, par)
            for equipe_id in (match["equipe_a"], match["equipe_b"]):
                for joueur in L.equipe(etat, equipe_id)["joueurs"]:
                    if joueur["id"] != par:
                        await self.messagerie.mp(etat, joueur["id"], M.mp_pp_creee(etat, numero, match, equipe_id))
        return M.reponse_pp_creee(nouveau, match)

    async def modifier_joueur(self, tournoi_id: str, joueur_id: str, *, serveur_id: str, par: str,
                              **valeurs) -> tuple[dict, dict, list[str]]:
        """/edit_player_tournament_rl : modifie un joueur pendant le tournoi (voir logique.modifier_joueur).

        Le changement compte tout de suite : chaque étape du tournoi relit le JSON. Le bot prévient les joueurs
        concernés, envoie au remplaçant ou au nouveau capitaine les infos du match en cours, met à jour l'accès
        au salon de discussion et le note dans LOG_CHANNEL. Renvoie (état, modification, notes pour l'admin).
        """
        tournoi_id = tournoi_id.strip()
        async with self.stockage.verrou(tournoi_id):
            etat = self._etat_du_serveur(tournoi_id, serveur_id)
            if etat["statut"] != L.EN_COURS:
                raise L.ErreurTournoi("Ce tournoi n'est pas en cours.")
            modif = L.modifier_joueur(etat, str(joueur_id), par=par, maintenant=maintenant(), **valeurs)
            self.stockage.sauvegarder_etat(etat)
        log.info("Tournoi %s : joueur %s modifié par %s : %s", tournoi_id, joueur_id, par, modif["changements"])
        notes = await self._suites_modification(etat, modif)
        await self.messagerie.journal(M.texte_journal_modification(etat, modif))
        return etat, modif, notes

    async def _suites_modification(self, etat: dict, modif: dict) -> list[str]:
        """Prévient les joueurs concernés par une modification. Renvoie les notes pour l'admin."""
        notes: list[str] = []
        changements = modif["changements"]
        equipe_id = modif["equipe"]
        equipe = L.equipe(etat, equipe_id)
        pseudos = {j["id"]: j["pseudo"] for j in equipe["joueurs"]}
        remplacement = changements.get("joueur")
        capitaine = changements.get("capitaine")

        ronde = L.ronde_actuelle(etat)
        match = L.match_de_l_equipe(ronde, equipe_id) if ronde and ronde["statut"] == L.RONDE_EN_COURS else None
        numero = ronde["numero"] if match else None
        # La partie privée du round en cours reste à créer par le capitaine de cette équipe.
        partie_a_creer = bool(match and match["statut"] == L.MATCH_EN_COURS and match["equipe_a"] == equipe_id
                              and not match.get("pp_creee_le"))

        if remplacement:
            ancien_id, nouvel_id = remplacement
            if etat.get("salon_discussion_id"):
                if await self.messagerie.changer_acces_salon(etat, ajouter=nouvel_id, retirer=ancien_id):
                    notes.append(f"💬 <@{nouvel_id}> a maintenant accès au salon <#{etat['salon_discussion_id']}> "
                                 f"(et plus <@{ancien_id}>).")
                else:
                    notes.append(f"⚠️ Je n'ai pas pu changer l'accès au salon <#{etat['salon_discussion_id']}> "
                                 f"(il me faut **Gérer les rôles**) : ajoute <@{nouvel_id}> à la main "
                                 f"(clic droit sur le salon > Modifier le salon > Permissions).")
            if not await self.messagerie.mp(etat, nouvel_id, M.mp_remplacant(
                    etat, equipe_id, nouvel_id, modif["ancien_joueur"]["pseudo"])):
                notes.append(f"⚠️ Impossible d'envoyer un MP à <@{nouvel_id}> : il doit ouvrir ses MP pour ce serveur.")
            await self.messagerie.mp(etat, ancien_id, M.mp_remplace(etat, equipe_id, pseudos[nouvel_id]))

        if capitaine:
            ancien_cap, nouveau_cap = capitaine
            if not remplacement or nouveau_cap != remplacement[1]:
                await self.messagerie.mp(etat, nouveau_cap, M.mp_nouveau_capitaine(etat, equipe_id))
            if not remplacement or ancien_cap != remplacement[0]:
                await self.messagerie.mp(etat, ancien_cap, M.mp_plus_capitaine(
                    etat, equipe_id, pseudos[nouveau_cap], partie_a_creer))

        # Match en cours de l'équipe : le remplaçant et le nouveau capitaine reçoivent ce qu'il leur faut.
        if match is not None:
            zone = match["zone"]
            if partie_a_creer and capitaine:
                await self.messagerie.mp(etat, capitaine[1], M.mp_creation(etat, numero, match),
                                         M.secours_infos_match(etat, numero, match), pp_creee=(numero, zone))
                notes.append(f"📨 <@{capitaine[1]}> a reçu le MP pour créer la partie privée du round {numero} "
                             f"(zone {zone}), avec le bouton **Partie privée créée**.")
            elif remplacement and match["statut"] == L.MATCH_EN_COURS:
                await self.messagerie.mp(etat, remplacement[1], M.mp_infos_remplacant(etat, numero, match, equipe_id),
                                         M.secours_infos_match(etat, numero, match))
                notes.append(f"📨 <@{remplacement[1]}> a reçu les infos de son match en cours "
                             f"(round {numero}, zone {zone}).")
            elif remplacement and match["statut"] == L.MATCH_A_VALIDER:
                await self.messagerie.mp(etat, remplacement[1], M.mp_declaration(etat, numero, match, equipe_id),
                                         secours=M.secours_declaration(etat, numero, match),
                                         declaration=(numero, zone, equipe_id))
                notes.append(f"📨 <@{remplacement[1]}> a reçu le bouton pour déclarer le score de son match "
                             f"(round {numero}, zone {zone}).")
        return notes

    async def declarer_score(self, tournoi_id: str, numero: int, zone: int, equipe_id: int, buts_equipe: int,
                             buts_adversaire: int, *, par: str) -> str:
        """Un joueur déclare le score de son match (bouton du MP). Renvoie la réponse à lui afficher."""
        async with self.stockage.verrou(tournoi_id):
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None or str(equipe_id) not in etat["equipes"]:
                raise L.ErreurTournoi("Ce tournoi n'existe plus.")
            if etat["statut"] != L.EN_COURS:
                raise L.ErreurTournoi("Ce tournoi n'est plus en cours.")
            if not any(j["id"] == par for j in L.equipe(etat, equipe_id)["joueurs"]):
                raise L.ErreurTournoi("Tu ne joues pas dans cette équipe.")
            match = L.trouver_match(L.trouver_ronde(etat, numero), zone)
            issue = L.declarer_score(etat, numero, match, equipe_id, buts_equipe, buts_adversaire,
                                     par=par, maintenant=maintenant())
            self.stockage.sauvegarder_etat(etat)

        log.info("Tournoi %s, round %s, zone %s : l'équipe %s déclare %s-%s (%s)",
                 tournoi_id, numero, zone, equipe_id, buts_equipe, buts_adversaire, issue)
        if issue == L.DECLARATION_VALIDEE:
            await self._annoncer_fin_match(etat, numero, match)
            self._validation(tournoi_id).set()
        elif issue == L.DECLARATION_DESACCORD:
            await self.messagerie.alerte(etat, texte=M.texte_alerte(etat),
                                         embeds=M.embeds_alerte_match(etat, numero, match, M.ALERTE_DESACCORD))
            for e_id in (match["equipe_a"], match["equipe_b"]):
                for joueur in L.equipe(etat, e_id)["joueurs"]:
                    await self.messagerie.mp(etat, joueur["id"], M.mp_desaccord(etat, numero, match, e_id),
                                             declaration=(numero, zone, e_id))
        return M.REPONSES_DECLARATION[issue]

    async def attendre(self, tournoi_id: str) -> None:
        """Attend la fin de la tâche du tournoi (utile pour les tests)."""
        tache = self._taches.get(tournoi_id)
        if tache is not None:
            await tache

    async def fermer(self) -> None:
        """Arrêt du bot : les tâches s'arrêtent, les tournois restent « en cours » et reprendront."""
        taches = list(self._taches.values()) + list(self._taches_matchs.values())
        for tache in taches:
            tache.cancel()
        await asyncio.gather(*taches, return_exceptions=True)
        if self.simulation is not None:
            await self.simulation.fermer()

    # ------------------------------------------------------------------- #
    # Boucle d'un tournoi
    # ------------------------------------------------------------------- #

    def _lancer(self, tournoi_id: str) -> None:
        if not self.est_actif(tournoi_id):
            self._taches[tournoi_id] = asyncio.create_task(self._boucle(tournoi_id), name=f"tournoi-{tournoi_id}")

    async def _boucle(self, tournoi_id: str) -> None:
        try:
            await self.messagerie.pret()
            while (numero := await self._prochaine_ronde(tournoi_id)) is not None:
                await self._jouer_ronde(tournoi_id, numero)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Erreur dans le tournoi %s", tournoi_id)
            etat = self.stockage.charger_etat(tournoi_id)
            if etat:
                await self.messagerie.alerte(etat, texte=M.texte_erreur(etat))
        finally:
            if self._taches.get(tournoi_id) is asyncio.current_task():
                del self._taches[tournoi_id]

    async def _prochaine_ronde(self, tournoi_id: str) -> int | None:
        """Numéro du round à jouer (le crée si besoin), ou None si le tournoi est fini/arrêté."""
        async with self.stockage.verrou(tournoi_id):
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None or etat["statut"] != L.EN_COURS:
                return None
            ronde = L.ronde_actuelle(etat)
            if ronde and ronde["statut"] == L.RONDE_EN_COURS:
                return ronde["numero"]  # reprise après un redémarrage
            fini = len(etat["rondes"]) >= etat["nombre_de_rondes"]
            if fini:
                L.terminer(etat, maintenant())
                self.stockage.sauvegarder_etat(etat)
        if fini:
            await self._annoncer_fin_tournoi(etat)
            return None

        if etat["rondes"] and self.pause_entre_rondes > 0:
            await asyncio.sleep(self.pause_entre_rondes)

        async with self.stockage.verrou(tournoi_id):
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None or etat["statut"] != L.EN_COURS:
                return None
            if etat["rondes"]:
                affectations = L.affectations_suivantes(etat["rondes"][-1], etat["nb_zones"])
            else:
                affectations = L.premier_tirage([e["id"] for e in etat["equipes"].values()], self.rng)
            numero = len(etat["rondes"]) + 1
            chemin = self.stockage.chemin_pp(tournoi_id, numero)
            parties = await asyncio.to_thread(self.generer_pp, len(affectations), chemin)
            if self.pp_forcee_zone_2 and len(parties) >= 2:  # TESTS uniquement (PP_FORCEE_ZONE_2)
                nom_pp, mot_de_passe = self.pp_forcee_zone_2
                parties[1] = {**parties[1], "nom": nom_pp, "mot_de_passe": mot_de_passe}
                log.warning("Tournoi %s, round %s : partie privée de la zone 2 FORCÉE par PP_FORCEE_ZONE_2 (%s) "
                            "— à vider avant un vrai tournoi", tournoi_id, numero, nom_pp)
            ronde = L.nouvelle_ronde(etat, affectations, parties, fichier_pp=chemin.name, maintenant=maintenant())
            self.stockage.sauvegarder_etat(etat)
        log.info("Tournoi %s : round %s/%s lancé", tournoi_id, numero, etat["nombre_de_rondes"])
        await self.messagerie.annonce(etat, embeds=M.embeds_debut_ronde(etat, ronde))
        return numero

    async def _jouer_ronde(self, tournoi_id: str, numero: int) -> None:
        etat = self.stockage.charger_etat(tournoi_id)
        ronde = L.trouver_ronde(etat, numero)
        taches = []
        for match in ronde["matchs"]:
            if match["statut"] == L.MATCH_A_VALIDER and self.simulation is not None:
                self.simulation.declarations_demandees(etat, numero, match)  # reprise après un redémarrage
            if match["statut"] in L.MATCHS_A_JOUER:
                cle = (tournoi_id, numero, match["zone"])
                tache = asyncio.create_task(self._jouer_match(tournoi_id, numero, match["zone"]),
                                            name=f"match-{tournoi_id}-{numero}-{match['zone']}")
                self._taches_matchs[cle] = tache
                tache.add_done_callback(lambda t, cle=cle: self._taches_matchs.pop(cle, None)
                                        if self._taches_matchs.get(cle) is t else None)
                taches.append(tache)
        if taches:
            await asyncio.gather(*taches, return_exceptions=True)

        # Les matchs « à valider » attendent les déclarations des équipes ou un admin.
        validation = self._validation(tournoi_id)
        while True:
            validation.clear()
            async with self.stockage.verrou(tournoi_id):
                etat = self.stockage.charger_etat(tournoi_id)
                if etat is None or etat["statut"] != L.EN_COURS:
                    return
                ronde = L.trouver_ronde(etat, numero)
                termine = L.ronde_complete(ronde)
                if termine:
                    L.terminer_ronde(ronde, maintenant())
                    self.stockage.sauvegarder_etat(etat)
            if termine:
                log.info("Tournoi %s : round %s terminé", tournoi_id, numero)
                await self.messagerie.resultats(etat, embeds=M.embeds_resultats_ronde(etat, ronde))
                return
            await validation.wait()

    async def _jouer_match(self, tournoi_id: str, numero: int, zone: int) -> None:
        async with self.stockage.verrou(tournoi_id):
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None or etat["statut"] != L.EN_COURS:
                return
            match = L.trouver_match(L.trouver_ronde(etat, numero), zone)
            if match["statut"] not in L.MATCHS_A_JOUER:
                return
            reprise = match["statut"] == L.MATCH_EN_COURS
            match["statut"] = L.MATCH_EN_COURS
            match["debut"] = match["debut"] or maintenant()
            self.stockage.sauvegarder_etat(etat)

        cle = (tournoi_id, numero, zone)
        evenement = self._pp_creees.setdefault(cle, asyncio.Event())  # avant les MP : le clic peut être rapide
        try:
            await self._envoyer_infos_match(etat, numero, match, reprise)
            if self.simulation is not None:
                self.simulation.match_lance(etat, numero, match)
            await self._attendre_pp_creee(tournoi_id, numero, zone, evenement)
        finally:
            if self._pp_creees.get(cle) is evenement:
                del self._pp_creees[cle]
        # Départ du délai : le clic du capitaine, ou maintenant (attente du clic dépassée). Noté dans le JSON
        # pour qu'un redémarrage n'attende que le temps qui reste.
        async with self.stockage.verrou(tournoi_id):
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None or etat["statut"] != L.EN_COURS:
                return
            match = L.trouver_match(L.trouver_ronde(etat, numero), zone)
            if match["statut"] != L.MATCH_EN_COURS:
                return  # validé à la main entre-temps
            deja_note = bool(match.get("chrono_declaration"))
            depart = L.demarrer_chrono_declaration(match, maintenant())
            if not deja_note:
                self.stockage.sauvegarder_etat(etat)

        await asyncio.sleep(_secondes_restantes(depart, self.delai_declaration))

        async with self.stockage.verrou(tournoi_id):
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None or etat["statut"] != L.EN_COURS:
                return
            match = L.trouver_match(L.trouver_ronde(etat, numero), zone)
            if match["statut"] != L.MATCH_EN_COURS:
                return  # validé à la main entre-temps
            L.ouvrir_declarations(match)
            self.stockage.sauvegarder_etat(etat)
        log.info("Tournoi %s, round %s, zone %s : délai passé, déclaration du score demandée aux équipes",
                 tournoi_id, numero, zone)
        await self._demander_declarations(etat, numero, match)
        if self.simulation is not None:
            self.simulation.declarations_demandees(etat, numero, match)

    # ------------------------------------------------------------------- #
    # Messages
    # ------------------------------------------------------------------- #

    async def _envoyer_infos_match(self, etat: dict, numero: int, match: dict, reprise: bool) -> None:
        secours = M.secours_infos_match(etat, numero, match)
        capitaine_id = L.equipe(etat, match["equipe_a"])["capitaine_id"]
        bouton = None if match.get("pp_creee_le") else (numero, match["zone"])
        await self.messagerie.mp(etat, capitaine_id, M.mp_creation(etat, numero, match, reprise), secours,
                                 pp_creee=bouton)
        for equipe_id in (match["equipe_a"], match["equipe_b"]):
            for joueur in L.equipe(etat, equipe_id)["joueurs"]:
                if joueur["id"] != capitaine_id:
                    await self.messagerie.mp(etat, joueur["id"],
                                             M.mp_rejoindre(etat, numero, match, equipe_id, reprise), secours)

    async def _attendre_pp_creee(self, tournoi_id: str, numero: int, zone: int, evenement: asyncio.Event) -> None:
        """Attend le clic du capitaine sur « Partie privée créée ».

        Sans clic : rappel au capitaine après RAPPEL_CLIC_PP, puis, après ATTENTE_CLIC_PP_MAX,
        alerte dans LOG_CHANNEL et le délai avant la demande de score démarre quand même.
        Rien à attendre si le délai a déjà démarré (reprise après un redémarrage).
        """
        def match_en_attente() -> tuple[dict, dict] | None:
            """(état, match) si le tournoi continue et que la partie n'est pas encore dite créée."""
            etat = self.stockage.charger_etat(tournoi_id)
            if etat is None or etat["statut"] != L.EN_COURS:
                return None
            match = L.trouver_match(L.trouver_ronde(etat, numero), zone)
            return None if match.get("pp_creee_le") or match.get("chrono_declaration") else (etat, match)

        if match_en_attente() is None:
            return
        rappel = min(self.rappel_clic_pp, self.attente_clic_pp_max)
        if await _attendre(evenement, rappel):
            return
        if rappel < self.attente_clic_pp_max:
            trouve = match_en_attente()
            if trouve is None:
                return
            etat, match = trouve
            capitaine_id = L.equipe(etat, match["equipe_a"])["capitaine_id"]
            await self.messagerie.mp(etat, capitaine_id, M.mp_rappel_creation(
                etat, numero, match, M.duree(self.attente_clic_pp_max - rappel)), pp_creee=(numero, zone))
            if await _attendre(evenement, self.attente_clic_pp_max - rappel):
                return
        trouve = match_en_attente()
        if trouve is None:
            return
        etat, match = trouve
        log.info("Tournoi %s, round %s, zone %s : pas de clic « Partie privée créée », le délai démarre quand même",
                 tournoi_id, numero, zone)
        probleme = M.ALERTE_PAS_DE_CLIC.format(duree=M.duree(self.attente_clic_pp_max))
        await self.messagerie.alerte(etat, texte=M.texte_alerte(etat), embeds=M.embeds_alerte_match(
            etat, numero, match, probleme, M.CONCLUSION_PAS_DE_CLIC))

    async def _demander_declarations(self, etat: dict, numero: int, match: dict) -> None:
        """Délai passé : bouton de déclaration du score à tous les joueurs du match."""
        for equipe_id in (match["equipe_a"], match["equipe_b"]):
            texte = M.mp_declaration(etat, numero, match, equipe_id)
            for joueur in L.equipe(etat, equipe_id)["joueurs"]:
                await self.messagerie.mp(etat, joueur["id"], texte, secours=M.secours_declaration(etat, numero, match),
                                         declaration=(numero, match["zone"], equipe_id))

    async def _annoncer_fin_match(self, etat: dict, numero: int, match: dict) -> None:
        for equipe_id in (match["equipe_a"], match["equipe_b"]):
            texte = M.mp_fin_match(etat, numero, match, equipe_id)
            for joueur in L.equipe(etat, equipe_id)["joueurs"]:
                await self.messagerie.mp(etat, joueur["id"], texte, secours=texte)

    async def _annoncer_fin_tournoi(self, etat: dict) -> None:
        log.info("Tournoi %s terminé", etat["tournoi_id"])
        await self.messagerie.annonce(etat, embeds=M.embeds_classement(etat, f"🏆 {etat['titre']} — classement final"))
        for e, joueur in L.joueurs(etat):
            await self.messagerie.mp(etat, joueur["id"], M.mp_fin_tournoi(etat, e["id"]))

    # ------------------------------------------------------------------- #

    def _etat_du_serveur(self, tournoi_id: str, serveur_id: str) -> dict:
        etat = self.stockage.charger_etat(tournoi_id)
        if etat is None or etat.get("serveur_id") != serveur_id:
            raise L.ErreurTournoi(f"Aucun tournoi lancé avec l'ID `{tournoi_id}` sur ce serveur.")
        return etat

    def _validation(self, tournoi_id: str) -> asyncio.Event:
        return self._validations.setdefault(tournoi_id, asyncio.Event())

    async def _annuler_taches(self, tournoi_id: str) -> None:
        taches = [t for cle, t in self._taches_matchs.items() if cle[0] == tournoi_id]
        principale = self._taches.pop(tournoi_id, None)
        if principale is not None:
            taches.append(principale)
        taches = [t for t in taches if t is not asyncio.current_task()]
        for tache in taches:
            tache.cancel()
        await asyncio.gather(*taches, return_exceptions=True)


def _secondes_restantes(depart: str, delai: float) -> float:
    """Secondes qui restent avant la fin du délai commencé à `depart` (horodatage ISO), au moins 0."""
    try:
        ecoule = (datetime.now() - datetime.fromisoformat(depart)).total_seconds()
    except ValueError:
        ecoule = 0.0
    return max(0.0, delai - max(0.0, ecoule))


async def _attendre(evenement: asyncio.Event, delai: float) -> bool:
    """True si l'événement arrive avant `delai` secondes."""
    try:
        await asyncio.wait_for(evenement.wait(), timeout=max(0.0, delai))
        return True
    except asyncio.TimeoutError:
        return False


# --------------------------------------------------------------------------- #
# Discord
# --------------------------------------------------------------------------- #

class MessagerieDiscord:
    """Envoi des MP, des annonces et des alertes via le client Discord.

    `salon_annonces` (SALON_ANNONCES du .env) : salon de toutes les annonces. Sans lui, chaque tournoi
    poste dans le salon où il a été créé avec le bot d'inscription.
    `salon_logs` (LOG_CHANNEL du .env) : alertes et problèmes du bot. Sans lui, les alertes partent
    en MP à l'admin qui a lancé le tournoi.
    `salon_resultats` (SALON_RESULTATS du .env, ex. #resultat-match) : récap de chaque round terminé.
    Sans lui, le récap part dans le salon des annonces.
    """

    def __init__(self, client: discord.Client, salon_annonces: int | None = None,
                 salon_logs: int | None = None, salon_resultats: int | None = None) -> None:
        self.client = client
        self.salon_annonces = salon_annonces
        self.salon_logs = salon_logs
        self.salon_resultats = salon_resultats

    def salon_id(self, tournoi: dict) -> int:
        """ID du salon des annonces d'un tournoi (état ou fichier d'inscription)."""
        return self.salon_annonces or int(tournoi["salon_id"])

    async def pret(self) -> None:
        await self.client.wait_until_ready()

    async def mp(self, etat: dict, joueur_id: str, texte: str, secours: str | None = None,
                 declaration: tuple[int, int, int] | None = None,
                 pp_creee: tuple[int, int] | None = None) -> bool:
        """Envoie un MP. S'il est impossible (MP fermés…), poste `secours` dans le salon des annonces."""
        from .declaration import vue_declaration, vue_pp_creee  # ici : utiles seulement avec Discord

        if declaration:
            vue = vue_declaration(etat["tournoi_id"], *declaration)
        elif pp_creee:
            vue = vue_pp_creee(etat["tournoi_id"], *pp_creee)
        else:
            vue = None
        kwargs = {"view": vue} if vue else {}
        try:
            utilisateur = self.client.get_user(int(joueur_id)) or await self.client.fetch_user(int(joueur_id))
            await utilisateur.send(texte, **kwargs)
            return True
        except discord.HTTPException as erreur:
            log.info("MP impossible pour %s : %s", joueur_id, erreur)
        if secours:  # le bouton de déclaration suit dans le salon ; pas celui de la partie privée
            await self._poster(self._salon_annonces_de(etat), f"<@{joueur_id}> {secours}", None,
                               vue=vue if declaration else None,
                               quoi=f"le salon des annonces du tournoi {etat.get('tournoi_id')}")
        return False

    async def annonce(self, etat: dict, texte: str | None = None,
                      embeds: list[discord.Embed] | None = None) -> None:
        await self._poster(self._salon_annonces_de(etat), texte, embeds,
                           quoi=f"le salon des annonces du tournoi {etat.get('tournoi_id')}")

    async def alerte(self, etat: dict, texte: str | None = None,
                     embeds: list[discord.Embed] | None = None) -> None:
        if self.salon_logs and await self._poster(self.salon_logs, texte, embeds, quoi="LOG_CHANNEL",
                                                  journal=False):
            return
        # Sans LOG_CHANNEL (ou s'il ne marche pas) : en MP à l'admin qui a lancé le tournoi.
        try:
            admin = self.client.get_user(int(etat["lance_par"])) or await self.client.fetch_user(int(etat["lance_par"]))
            await admin.send(texte, embeds=(embeds or [])[:10])
        except (discord.HTTPException, KeyError, ValueError) as erreur:
            log.warning("Alerte impossible à envoyer (ni LOG_CHANNEL, ni MP à l'admin) : %s", erreur,
                        extra=HORS_JOURNAL)

    async def resultats(self, etat: dict, texte: str | None = None,
                        embeds: list[discord.Embed] | None = None) -> None:
        if self.salon_resultats:
            await self._poster(self.salon_resultats, texte, embeds, quoi="SALON_RESULTATS")
        else:
            await self.annonce(etat, texte=texte, embeds=embeds)

    async def journal(self, texte: str) -> None:
        """Message dans LOG_CHANNEL (problèmes du bot, démarrage), sans mentionner personne."""
        if self.salon_logs:
            await self._poster(self.salon_logs, texte, None, quoi="LOG_CHANNEL", journal=False,
                               mentions=discord.AllowedMentions.none())

    async def creer_salon_discussion(self, etat: dict) -> int | None:
        """Crée le salon texte du tournoi dans la catégorie du salon où il a été créé (bot d'inscription).

        Seuls les joueurs des équipes participantes, les admins (rôles avec « Gérer le serveur » ou
        « Administrateur ») et l'admin qui a lancé le tournoi le voient. Toutes les permissions sont posées
        à la création : « Gérer les salons » suffit au bot (les changer après coup demanderait « Gérer les rôles »).
        """
        tournoi_id = etat["tournoi_id"]
        serveur = self.client.get_guild(int(etat["serveur_id"]))
        if serveur is None:
            log.warning("Salon de discussion du tournoi %s pas créé : le bot ne voit pas le serveur %s.",
                        tournoi_id, etat["serveur_id"])
            return None
        categorie = categorie_du_tournoi(serveur, etat)

        participant = discord.PermissionOverwrite(**dict.fromkeys(DROITS_PARTICIPANT, True))
        permissions: dict = {
            serveur.default_role: discord.PermissionOverwrite(view_channel=False),
            serveur.me: discord.PermissionOverwrite(**dict.fromkeys(DROITS_BOT, True)),
        }
        for role in serveur.roles:
            if est_role_admin(role):
                permissions[role] = participant

        pseudos = {j["id"]: j["pseudo"] for _, j in L.joueurs(etat)}
        absents = []
        for membre_id in dict.fromkeys([*pseudos, etat["lance_par"]]):  # sans doublon, dans l'ordre
            membre = await _membre(serveur, membre_id)
            if membre is None:
                absents.append(pseudos.get(membre_id, membre_id))
            else:
                permissions[membre] = participant

        ou = f"la catégorie « {categorie.name} »" if categorie is not None else "le serveur"
        try:
            salon = await serveur.create_text_channel(
                M.nom_salon_discussion(etat), category=categorie, overwrites=permissions,
                topic=M.sujet_salon_discussion(etat), reason=f"Tournoi {etat['titre']} lancé")
        except discord.Forbidden as erreur:
            manquantes = permissions_manquantes_discussion(serveur, categorie)
            cause = (f"il manque au bot : {', '.join(manquantes)}" if manquantes
                     else f"Discord refuse ({erreur.status} {erreur.text})")
            log.warning("Salon de discussion du tournoi %s pas créé dans %s : %s. Le tournoi continue sans.",
                        tournoi_id, ou, cause)
            return None
        except discord.HTTPException as erreur:
            log.warning("Salon de discussion du tournoi %s pas créé dans %s : %s. Le tournoi continue sans.",
                        tournoi_id, ou, erreur)
            return None

        if absents:
            log.warning("Salon de discussion du tournoi %s : ces joueurs ne sont plus sur le serveur et n'y ont "
                        "pas accès : %s.", tournoi_id, ", ".join(absents))
        try:
            for texte in M.textes_bienvenue_salon(etat):
                await salon.send(texte)
        except discord.HTTPException as erreur:
            log.warning("Message de bienvenue impossible dans le salon de discussion #%s : %s", salon.name, erreur)
        return salon.id

    async def changer_acces_salon(self, etat: dict, *, ajouter: str | None = None,
                                  retirer: str | None = None) -> bool:
        """Change l'accès d'un joueur au salon de discussion (remplaçant). Demande « Gérer les rôles » au bot :
        Discord l'exige pour modifier les permissions d'un salon qui existe déjà."""
        tournoi_id = etat.get("tournoi_id")
        try:
            salon_id = int(etat["salon_discussion_id"])
            salon = self.client.get_channel(salon_id) or await self.client.fetch_channel(salon_id)
            cibles = {int(i) for i in (ajouter, retirer) if i}
            # Les membres absents du cache sont des discord.Object : on garde le dictionnaire tel quel.
            permissions = {cible: p for cible, p in salon.overwrites.items() if cible.id not in cibles}
            if ajouter:
                permissions[discord.Object(id=int(ajouter), type=discord.Member)] = discord.PermissionOverwrite(
                    **dict.fromkeys(DROITS_PARTICIPANT, True))
            await salon.edit(overwrites=permissions, reason=f"Tournoi {etat.get('titre')} : remplacement d'un joueur")
            return True
        except discord.Forbidden:
            log.warning("Salon de discussion du tournoi %s : accès pas mis à jour, il manque « Gérer les rôles » au "
                        "bot. Ajoute le remplaçant <@%s> à la main (clic droit sur le salon > Modifier le salon > "
                        "Permissions).", tournoi_id, ajouter)
        except discord.NotFound:
            log.warning("Salon de discussion du tournoi %s introuvable (supprimé ?) : accès pas mis à jour.", tournoi_id)
        except (discord.HTTPException, KeyError, TypeError, ValueError) as erreur:
            log.warning("Salon de discussion du tournoi %s : accès pas mis à jour (%s).", tournoi_id, erreur)
        return False

    async def supprimer_salon_discussion(self, etat: dict, salon_id: str) -> bool:
        """Supprime le salon (il faut « Gérer les salons » au bot). True s'il n'existe plus."""
        tournoi_id = etat.get("tournoi_id")
        try:
            salon = self.client.get_channel(int(salon_id)) or await self.client.fetch_channel(int(salon_id))
            await salon.delete(reason=f"Tournoi {etat.get('titre')} remis à zéro")
            return True
        except discord.NotFound:
            return True  # déjà supprimé à la main
        except discord.Forbidden:
            log.warning("Salon de discussion %s du tournoi %s pas supprimé : il manque « Gérer les salons » au bot. "
                        "Supprime-le à la main.", salon_id, tournoi_id)
        except (discord.HTTPException, TypeError, ValueError) as erreur:
            log.warning("Salon de discussion %s du tournoi %s pas supprimé (%s).", salon_id, tournoi_id, erreur)
        return False

    def _salon_annonces_de(self, etat: dict) -> int | None:
        try:
            return self.salon_id(etat)
        except (KeyError, TypeError, ValueError):
            return None

    async def _poster(self, salon_id: int | None, texte: str | None, embeds: list[discord.Embed] | None, *,
                      quoi: str, vue: discord.ui.View | None = None, journal: bool = True,
                      mentions: discord.AllowedMentions | None = None) -> bool:
        """Poste dans un salon. En cas d'échec, explique pourquoi dans la console (et dans LOG_CHANNEL
        si `journal`, sauf pour LOG_CHANNEL lui-même : il ne faut pas tourner en rond)."""
        extra = {} if journal else HORS_JOURNAL
        if salon_id is None:
            log.warning("Impossible de poster dans %s : salon inconnu.", quoi, extra=extra)
            return False
        salon = None
        try:
            salon = self.client.get_channel(salon_id) or await self.client.fetch_channel(salon_id)
            kwargs: dict = {}
            if embeds:
                kwargs["embeds"] = embeds[:10]
            if vue:
                kwargs["view"] = vue
            if mentions:
                kwargs["allowed_mentions"] = mentions
            await salon.send(texte, **kwargs)  # type: ignore[union-attr]
            return True
        except discord.Forbidden as erreur:
            manquantes = permissions_manquantes(salon)
            cause = (f"il manque au bot : {', '.join(manquantes)}" if manquantes
                     else f"Discord refuse ({erreur.status} {erreur.text})")
            role = self.client.user.name if self.client.user else "du bot"
            log.warning("Impossible de poster dans %s (#%s) : %s. Dans Discord : clic droit sur le salon > "
                        "Modifier le salon > Permissions > ajoute le rôle « %s » et autorise « %s ».",
                        quoi, getattr(salon, "name", salon_id), cause, role,
                        "», «".join(PERMISSIONS_SALON.values()), extra=extra)
        except discord.NotFound:
            log.warning("Impossible de poster dans %s : le salon %s n'existe pas ou le bot ne le voit pas "
                        "(vérifie l'identifiant dans le .env).", quoi, salon_id, extra=extra)
        except (discord.HTTPException, AttributeError, ValueError) as erreur:
            log.warning("Impossible de poster dans %s : %s", quoi, erreur, extra=extra)
        return False


# Permissions dont le bot a besoin dans un salon pour y poster (embeds).
PERMISSIONS_SALON = {
    "view_channel": "Voir le salon",
    "send_messages": "Envoyer des messages",
    "embed_links": "Intégrer des liens",
}


def permissions_manquantes(salon) -> list[str]:
    """Permissions qui manquent au bot dans `salon` ([] si tout va bien ou si on ne peut pas le savoir)."""
    moi = getattr(getattr(salon, "guild", None), "me", None)
    if moi is None or not hasattr(salon, "permissions_for"):
        return []
    permissions = salon.permissions_for(moi)
    return [nom for attribut, nom in PERMISSIONS_SALON.items() if not getattr(permissions, attribut)]


# --------------------------------------------------------------------------- #
# Salon de discussion du tournoi
# --------------------------------------------------------------------------- #

# Droits donnés aux joueurs et aux admins dans le salon de discussion.
DROITS_PARTICIPANT = ("view_channel", "send_messages", "read_message_history", "attach_files")
# Droits du bot dans ce salon.
DROITS_BOT = ("view_channel", "send_messages", "embed_links", "read_message_history", "attach_files")
# Pour créer le salon, le bot doit avoir « Gérer les salons » et chaque droit qu'il donne
# (Discord refuse qu'il accorde un droit qu'il n'a pas lui-même).
PERMISSIONS_DISCUSSION = {
    "manage_channels": "Gérer les salons",
    "view_channel": "Voir les salons",
    "send_messages": "Envoyer des messages",
    "embed_links": "Intégrer des liens",
    "attach_files": "Joindre des fichiers",
    "read_message_history": "Voir les anciens messages",
}


def categorie_du_tournoi(serveur, tournoi: dict):
    """Catégorie du salon où le tournoi a été créé (`salon_id`), ou None (salon introuvable, hors catégorie)."""
    try:
        salon = serveur.get_channel_or_thread(int(tournoi["salon_id"]))
    except (KeyError, TypeError, ValueError):
        return None
    return getattr(salon, "category", None)


def manques_discussion(serveur, categorie) -> tuple[list[str], list[str]]:
    """Permissions qui manquent au bot pour créer le salon de discussion dans `categorie` (None : à la racine) :
    (celles que ses rôles n'ont pas sur le serveur, celles que la catégorie lui retire).
    ([], []) si tout va bien ou si on ne peut pas le savoir."""
    moi = getattr(serveur, "me", None)
    sur_serveur = getattr(moi, "guild_permissions", None)
    if sur_serveur is None or sur_serveur.administrator:
        return [], []
    absentes = [nom for attribut, nom in PERMISSIONS_DISCUSSION.items() if not getattr(sur_serveur, attribut)]
    if categorie is None or not hasattr(categorie, "permissions_for"):
        return absentes, []
    dans_categorie = categorie.permissions_for(moi)
    retirees = [nom for attribut, nom in PERMISSIONS_DISCUSSION.items()
                if getattr(sur_serveur, attribut) and not getattr(dans_categorie, attribut)]
    return absentes, retirees


def permissions_manquantes_discussion(serveur, categorie) -> list[str]:
    """Toutes les permissions qui manquent au bot pour créer le salon de discussion dans `categorie`."""
    absentes, retirees = manques_discussion(serveur, categorie)
    return absentes + retirees


def qui_retire(categorie, moi, noms: list[str]) -> list[str]:
    """Entrées de la catégorie (@everyone, rôles du bot) qui refusent au bot ces permissions."""
    attributs = [attribut for attribut, nom in PERMISSIONS_DISCUSSION.items() if nom in noms]
    ids_du_bot = {getattr(r, "id", None) for r in getattr(moi, "roles", [])} | {getattr(moi, "id", None)}
    cibles = []
    for cible, permission in getattr(categorie, "overwrites", {}).items():
        concerne = cible.id in ids_du_bot or getattr(cible, "is_default", lambda: False)()
        if concerne and any(getattr(permission, a) is False for a in attributs):
            cibles.append(getattr(cible, "name", None) or f"<@{cible.id}>")
    return cibles


def est_role_admin(role) -> bool:
    """Rôle d'admin du serveur (« Gérer le serveur » ou « Administrateur »), hors @everyone et rôles de bots."""
    if role.is_default() or role.managed:
        return False
    return role.permissions.administrator or role.permissions.manage_guild


async def _membre(serveur, membre_id: str):
    """Membre du serveur (sans l'intent privilégié des membres), ou None s'il n'y est plus."""
    try:
        return serveur.get_member(int(membre_id)) or await serveur.fetch_member(int(membre_id))
    except (discord.HTTPException, ValueError):
        return None
