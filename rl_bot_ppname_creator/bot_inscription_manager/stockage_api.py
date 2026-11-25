"""Stockage des tournois dans la base de données, via l'API du site (routes /api/bot/*).

Utilisé quand `API_URL` est rempli dans le `.env`. Mêmes méthodes asynchrones que
`StockageFichiers` (stockage.py) : le reste du bot ne change pas.

- C'est l'API qui applique les règles (places, liste d'attente, promotions, délais) dans
  des transactions : le bot n'a plus besoin de verrou.
- Avant d'appeler l'API, le bot vérifie ce qu'il peut vérifier seul (fiche d'inscription,
  pseudo, joueurs déjà inscrits) pour garder des messages précis en français.
- Les erreurs de l'API (en anglais) sont traduites en `ErreurAPI`, une `ErreurTournoi`
  dont le message peut être montré tel quel au joueur.
- Miroir : chaque tournoi renvoyé par l'API est aussi écrit dans `data/tournois/<id>.json`,
  parce que `tournament_manager` lit toujours ces fichiers. Ils ne servent plus qu'à ça.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from pathlib import Path
from typing import Any

import aiohttp

from . import logique as L
from .stockage import StockageFichiers

log = logging.getLogger(__name__)

DELAI_REPONSE_SECONDES = 10
MESSAGE_API_INJOIGNABLE = "Le serveur des tournois ne répond pas. Réessaie dans un instant."
MESSAGE_ROUTE_ABSENTE = ("Le serveur des tournois ne sait pas encore faire ça (route absente de l'API). "
                         "Mets à jour le site, puis réessaie.")
MESSAGE_API_REFUSE = ("Le serveur des tournois refuse le bot : vérifie que `BOT_API_KEY` est la même "
                      "dans le `.env` du bot et dans celui de l'API.")


class ErreurAPI(L.ErreurTournoi):
    """Erreur renvoyée par l'API (ou API injoignable), avec un message en français."""

    def __init__(self, message: str, statut: int | None = None) -> None:
        super().__init__(message)
        self.statut = statut


# --------------------------------------------------------------------------- #
# Traduction des erreurs de l'API
# --------------------------------------------------------------------------- #

def _nombre(texte: str) -> int | None:
    trouve = re.search(r"\d+", texte)
    return int(trouve.group()) if trouve else None


def traduire_erreur(statut: int, corps: Any, contexte: dict | None = None) -> str:
    """Message en français pour une réponse d'erreur de l'API.

    `contexte` peut donner : nom (équipe ou réservation), numero, pseudos ({id: pseudo}).
    """
    contexte = contexte or {}
    message = corps.get("error", "") if isinstance(corps, dict) else ""
    details = corps.get("details") if isinstance(corps, dict) else None
    numero = contexte.get("numero")

    if statut in (401, 503):
        return MESSAGE_API_REFUSE
    if statut >= 500:
        return MESSAGE_API_INJOIGNABLE

    if message == "Player already in a team of this tournament":
        ids = details.get("playerIds", []) if isinstance(details, dict) else []
        pseudos = contexte.get("pseudos", {})
        noms = ", ".join(f"**{pseudos.get(i, i)}**" for i in ids)
        if len(ids) == 1:
            return f"{noms} est déjà dans une équipe pour ce tournoi."
        if ids:
            return f"{noms} sont déjà dans une équipe pour ce tournoi."
        return "Un des joueurs est déjà dans une équipe pour ce tournoi."
    if message == "Registrations not open yet":
        ouverture = details.get("ouverture_inscriptions") if isinstance(details, dict) else None
        if ouverture:
            horodatage = int(L.lire_date(ouverture).timestamp())
            return f"Les inscriptions ouvrent <t:{horodatage}:R> (<t:{horodatage}:t>)."
        return "Les inscriptions ne sont pas encore ouvertes."
    if message.startswith("Wrong number of teammates"):
        attendus = _nombre(message)
        return f"Il faut choisir exactement {attendus} coéquipier(s)." if attendus is not None else \
            "Le nombre de coéquipiers n'est pas bon."
    if message.startswith("equipes_max cannot be lower than"):
        minimum = _nombre(message)
        return (f"equipes_max ne peut pas descendre en dessous de {minimum} (équipes inscrites + places "
                f"réservées). Retire d'abord des équipes avec `/tournoi_rl_remove_team` ou des réservations "
                f"avec `/tournoi_rl_unreserve`.")
    if message.startswith("Waitlist would exceed"):
        maximum = _nombre(message)
        return (f"La liste d'attente dépasserait le maximum de {maximum} équipes. Retire d'abord des équipes "
                f"de la liste d'attente avec `/tournoi_rl_remove_team`.")

    nom = contexte.get("nom", "")
    simples = {
        "Tournament not found": "Ce tournoi n'existe plus.",
        "Tournament already exists": "Ce tournoi existe déjà.",
        "Team not found": f"Aucune équipe #{numero} dans ce tournoi.",
        "Player not in this team": "Cette inscription ne te concerne pas.",
        "Team is cancelled": "L'inscription de cette équipe a été annulée.",
        "Team already cancelled": "Cette équipe est déjà annulée.",
        "Player already confirmed": "Tu as déjà confirmé ta participation.",
        "Player already refused": "Tu as déjà refusé cette inscription.",
        "Confirmation deadline passed": ("Trop tard : le délai pour confirmer est dépassé, "
                                         "l'équipe est désinscrite du tournoi."),
        "Team name already taken": f"Le nom **{nom}** est déjà pris dans ce tournoi.",
        "Tournament is full": "Ce tournoi est complet, liste d'attente comprise.",
        "Already exists": "Quelqu'un vient de s'inscrire au même moment : réessaie.",
        "Conflict, retry": "Quelqu'un vient de s'inscrire au même moment : réessaie.",
        "No free place to reserve": ("Plus aucune place libre à réserver. Augmente `equipes_max` avec "
                                     "`/tournoi_rl_modify` ou retire une équipe avec `/tournoi_rl_remove_team`."),
        "Captain already in a team of this tournament": "Ce capitaine est déjà dans une équipe pour ce tournoi.",
        "Captain already has an active reservation": "Ce capitaine a déjà une place réservée dans ce tournoi.",
        "Reservation not found": f"Aucune réservation R{numero} dans ce tournoi.",
        "Reservation is not active": f"La réservation R{numero} n'est plus active.",
        "Player not in an active team": ("Ce joueur n'est dans aucune équipe inscrite ou en liste "
                                         "d'attente de ce tournoi."),
        "Player has not confirmed yet": ("Ce joueur n'a pas encore confirmé sa participation : il donnera "
                                         "son pseudo Rocket League en confirmant."),
        "Same player": "Le nouveau joueur est le même que l'ancien.",
        "New player already in a team of this tournament": f"**{nom}** est déjà dans une équipe pour ce tournoi.",
        "New player has an active reservation": (f"**{nom}** a une place réservée dans ce tournoi. "
                                                 "Annule-la d'abord avec `/tournoi_rl_unreserve`."),
        "Tournament would start in the past": "Le tournoi commencerait dans le passé.",
        "Tournament would start before registrations open": ("Les inscriptions ouvrent après ce début : "
                                                             "le tournoi ne peut pas commencer avant."),
        "Tournament has no real date": "Ce tournoi n'a pas de vraie date : donne aussi `date` (JJ/MM/AAAA).",
        "Tournament has no start time": "Ce tournoi n'a pas d'heure de début : donne aussi `start_time` (HH:MM).",
    }
    if message in simples:
        return simples[message]
    if statut == 404:
        # 404 avec un message inconnu : la route n'existe pas (API pas encore mise à jour).
        return MESSAGE_ROUTE_ABSENTE
    if statut == 400:
        champs = ", ".join(d.get("path") or "?" for d in details if isinstance(d, dict)) \
            if isinstance(details, list) else ""
        return "Données refusées par le serveur des tournois" + (f" ({champs})." if champs else ".")
    return f"Le serveur des tournois a refusé l'action ({statut} {message})."


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class StockageAPI:
    def __init__(self, url: str, cle: str, dossier_miroir: Path | None = None) -> None:
        self.url = url.rstrip("/")
        self._cle = cle
        self._session: aiohttp.ClientSession | None = None
        self._boucle: asyncio.AbstractEventLoop | None = None
        self.miroir = StockageFichiers(dossier_miroir) if dossier_miroir else None

    # --- HTTP --------------------------------------------------------------- #

    async def _requete(self, methode: str, chemin: str, corps: dict | None = None,
                       params: dict | None = None) -> tuple[int, Any]:
        """Envoie la requête et renvoie (code HTTP, JSON). Remplaçable dans les tests."""
        boucle = asyncio.get_running_loop()
        if self._session is None or self._session.closed or self._boucle is not boucle:
            # Une session HTTP ne sert que dans la boucle asyncio qui l'a créée (une seule pour le bot).
            self._boucle = boucle
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=DELAI_REPONSE_SECONDES),
                headers={"Authorization": f"Bearer {self._cle}"},
            )
        async with self._session.request(methode, f"{self.url}/api/bot{chemin}", json=corps,
                                         params=params) as reponse:
            try:
                donnees = await reponse.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError):
                donnees = None
            return reponse.status, donnees

    async def _appel(self, methode: str, chemin: str, corps: dict | None = None, *,
                     params: dict | None = None, contexte: dict | None = None) -> Any:
        try:
            statut, donnees = await self._requete(methode, chemin, corps, params)
        except (aiohttp.ClientError, TimeoutError) as erreur:
            log.warning("API injoignable (%s %s) : %r", methode, chemin, erreur)
            raise ErreurAPI(MESSAGE_API_INJOIGNABLE) from erreur
        if statut >= 400:
            message = traduire_erreur(statut, donnees, contexte)
            niveau = logging.ERROR if statut in (401, 503) or statut >= 500 else logging.INFO
            log.log(niveau, "API %s %s -> %s %s", methode, chemin, statut, donnees)
            raise ErreurAPI(message, statut)
        return donnees

    async def fermer(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # --- Miroir pour tournament_manager ----------------------------------- #

    def _copier(self, tournoi: dict) -> dict:
        if self.miroir is not None:
            try:
                self.miroir.sauvegarder(tournoi)
            except (OSError, ValueError) as erreur:
                log.warning("Copie locale du tournoi %s impossible : %s", tournoi.get("id"), erreur)
        return tournoi

    async def rafraichir_copies(self, serveur_id: str) -> int:
        """Réécrit la copie JSON de chaque tournoi du serveur (au démarrage du bot).

        Retourne le nombre de tournois recopiés.
        """
        if self.miroir is None:
            return 0
        resumes = await self.lister(serveur_id)
        for resume in resumes:
            await self.lire(resume["id"])
        return len(resumes)

    # --- Lecture ------------------------------------------------------------ #

    async def lister(self, serveur_id: str) -> list[dict]:
        return await self._appel("GET", "/tournaments", params={"serveur_id": serveur_id})

    async def lire(self, tournoi_id: str) -> dict | None:
        if not str(tournoi_id).isdigit():
            return None
        try:
            tournoi = await self._appel("GET", f"/tournaments/{tournoi_id}")
        except ErreurAPI as erreur:
            if erreur.statut in (400, 404):
                return None
            raise
        return self._copier(tournoi)

    async def _exiger(self, tournoi_id: str) -> dict:
        tournoi = await self.lire(tournoi_id)
        if tournoi is None:
            raise ErreurAPI("Ce tournoi n'existe plus.", 404)
        return tournoi

    # --- Tournoi ------------------------------------------------------------ #

    async def creer(self, tournoi: dict) -> dict:
        return self._copier(await self._appel("POST", "/tournaments", tournoi))

    async def supprimer(self, tournoi_id: str) -> dict | None:
        try:
            tournoi = await self._appel("DELETE", f"/tournaments/{tournoi_id}")
        except ErreurAPI as erreur:
            if erreur.statut == 404:
                return None
            raise
        if self.miroir is not None:
            self.miroir.effacer(tournoi_id)
        return tournoi

    async def modifier(
        self, tournoi_id: str, *, titre: str | None = None, cashprize: str | None = None,
        equipes_max: int | None = None, date: str | None = None, start_time: str | None = None,
        maintenant: str | None = None,
    ) -> tuple[dict, list[tuple[str, object, object]], list[dict]]:
        if titre is None and cashprize is None and equipes_max is None and date is None and start_time is None:
            raise L.ErreurTournoi(L.TEXTE_AUCUN_CHAMP)
        corps: dict[str, object] = {}
        if date is not None or start_time is not None:
            # Vérifié ici d'abord (format JJ/MM/AAAA, début futur) pour des messages précis en français.
            tournoi = await self._exiger(tournoi_id)
            corps.update(L.verifier_nouveau_debut(tournoi, date=date, start_time=start_time,
                                                  maintenant=maintenant))
        if titre is not None:
            corps["titre"] = L._texte_obligatoire(titre, "titre", L.LONGUEUR_MAX_TITRE)
        if cashprize is not None:
            corps["cashprize"] = L._texte_obligatoire(cashprize, "cashprize", L.LONGUEUR_MAX_CASHPRIZE)
        if equipes_max is not None:
            corps["equipes_max"] = equipes_max
        reponse = await self._appel("PATCH", f"/tournaments/{tournoi_id}", corps)
        changements = [(c["champ"], c["ancienne"], c["nouvelle"]) for c in reponse["changements"]
                       if c["champ"] in L.CHAMPS_MODIFIABLES]
        return self._copier(reponse["tournoi"]), changements, reponse["promues"]

    # --- Équipes ------------------------------------------------------------ #

    async def inscrire(
        self, tournoi_id: str, *, nom: str, capitaine: tuple[str, str], pseudo_jeu_capitaine: str,
        coequipiers: list[tuple[str, str]], maintenant: str,
    ) -> tuple[dict, dict]:
        tournoi = await self._exiger(tournoi_id)
        nom, pseudo_jeu_capitaine = L.verifier_fiche(
            tournoi, nom=nom, capitaine=capitaine, pseudo_jeu_capitaine=pseudo_jeu_capitaine,
            coequipiers=coequipiers)
        # Mêmes vérifications que l'API, faites d'abord ici pour donner le nom de l'équipe en cause.
        if any(e["nom"].casefold() == nom.casefold() for e in L.equipes_actives(tournoi)):
            raise L.ErreurTournoi(f"Le nom **{nom}** est déjà pris dans ce tournoi.")
        for joueur_id, pseudo in [capitaine] + coequipiers:
            equipe = L.equipe_du_joueur(tournoi, joueur_id)
            if equipe is not None:
                raise L.ErreurTournoi(f"**{pseudo}** est déjà dans l'équipe **{equipe['nom']}** pour ce tournoi.")

        corps = {
            "nom": nom,
            "capitaine": {"id": capitaine[0], "pseudo": capitaine[1], "pseudo_jeu": pseudo_jeu_capitaine},
            "coequipiers": [{"id": i, "pseudo": p} for i, p in coequipiers],
            "delai_confirmation_minutes": L.DELAI_CONFIRMATION_MINUTES,
        }
        contexte = {"nom": nom, "pseudos": dict([capitaine] + coequipiers)}
        reponse = await self._appel("POST", f"/tournaments/{tournoi_id}/teams", corps, contexte=contexte)
        return self._copier(reponse["tournoi"]), reponse["equipe"]

    async def confirmer(
        self, tournoi_id: str, equipe_id: int, joueur_id: str, pseudo_jeu: str, maintenant: str,
    ) -> tuple[dict, dict]:
        pseudo_jeu = L.nettoyer_pseudo_jeu(pseudo_jeu)
        reponse = await self._appel(
            "POST", f"/tournaments/{tournoi_id}/teams/{equipe_id}/players/{joueur_id}/confirm",
            {"pseudo_jeu": pseudo_jeu}, contexte={"numero": equipe_id})
        return self._copier(reponse["tournoi"]), reponse["equipe"]

    async def refuser(
        self, tournoi_id: str, equipe_id: int, joueur_id: str, maintenant: str,
    ) -> tuple[dict, dict, list[dict]]:
        try:
            reponse = await self._appel(
                "POST", f"/tournaments/{tournoi_id}/teams/{equipe_id}/players/{joueur_id}/refuse", {},
                contexte={"numero": equipe_id})
        except ErreurAPI as erreur:
            if str(erreur) == "Tu as déjà confirmé ta participation.":
                raise ErreurAPI("Tu as déjà validé cette inscription.", erreur.statut) from erreur
            raise
        return self._copier(reponse["tournoi"]), reponse["equipe"], reponse["promues"]

    async def annuler_equipe(
        self, tournoi_id: str, equipe_id: int, raison: str, maintenant: str,
    ) -> tuple[dict, dict, list[dict]]:
        reponse = await self._appel(
            "POST", f"/tournaments/{tournoi_id}/teams/{equipe_id}/cancel", {"raison": raison[:200]},
            contexte={"numero": equipe_id})
        return self._copier(reponse["tournoi"]), reponse["equipe"], reponse["promues"]

    # --- Réservations ------------------------------------------------------- #

    async def reserver(
        self, tournoi_id: str, *, nom: str, capitaine: tuple[str, str], duree_minutes: int | None, cree_par: str,
        maintenant: str,
    ) -> tuple[dict, dict]:
        nom = nom.strip()
        if not nom:
            raise L.ErreurTournoi("Le nom de la réservation ne peut pas être vide.")
        # duree_minutes None : réservation sans limite de durée (l'API renvoie expire_le à null).
        corps = {"nom": nom, "capitaine": {"id": capitaine[0], "pseudo": capitaine[1]},
                 "duree_minutes": duree_minutes, "cree_par": cree_par}
        reponse = await self._appel("POST", f"/tournaments/{tournoi_id}/reservations", corps,
                                    contexte={"nom": nom})
        return self._copier(reponse["tournoi"]), reponse["reservation"]

    async def annuler_reservation(
        self, tournoi_id: str, reservation_id: int, maintenant: str,
    ) -> tuple[dict, dict, list[dict]]:
        reponse = await self._appel(
            "POST", f"/tournaments/{tournoi_id}/reservations/{reservation_id}/cancel", {},
            contexte={"numero": reservation_id})
        return self._copier(reponse["tournoi"]), reponse["reservation"], reponse["promues"]

    # --- Joueurs ------------------------------------------------------------ #
    # /tournoi_rl_modify_player et /tournoi_rl_modify_member. Le bot vérifie d'abord sur une copie
    # du tournoi avec les règles de logique.py (messages précis en français), puis l'API applique.

    async def modifier_joueur(
        self, tournoi_id: str, joueur_id: str, *, pseudo: str | None = None, pseudo_jeu: str | None = None,
    ) -> tuple[dict, dict, dict, list[tuple[str, object, object]]]:
        tournoi = await self._exiger(tournoi_id)
        _equipe, _joueur, changements = L.modifier_joueur(
            copy.deepcopy(tournoi), joueur_id, pseudo=pseudo, pseudo_jeu=pseudo_jeu)
        if not changements:
            equipe = L.equipe_du_joueur(tournoi, joueur_id)
            return tournoi, equipe, L.joueur_dans_equipe(equipe, joueur_id), []
        corps = {champ: nouvelle for champ, _ancienne, nouvelle in changements}
        reponse = await self._appel("PATCH", f"/tournaments/{tournoi_id}/players/{joueur_id}", corps)
        changements = [(c["champ"], c["ancienne"], c["nouvelle"]) for c in reponse["changements"]]
        return self._copier(reponse["tournoi"]), reponse["equipe"], reponse["joueur"], changements

    async def remplacer_joueur(
        self, tournoi_id: str, ancien_id: str, nouveau: tuple[str, str], pseudo_jeu: str,
    ) -> tuple[dict, dict, dict, dict]:
        tournoi = await self._exiger(tournoi_id)
        L.remplacer_joueur(copy.deepcopy(tournoi), ancien_id, nouveau, pseudo_jeu)
        corps = {"nouveau": {"id": nouveau[0], "pseudo": nouveau[1]},
                 "pseudo_jeu": L.nettoyer_pseudo_jeu(pseudo_jeu)}
        reponse = await self._appel("POST", f"/tournaments/{tournoi_id}/players/{ancien_id}/replace", corps,
                                    contexte={"nom": nouveau[1]})
        return self._copier(reponse["tournoi"]), reponse["equipe"], reponse["ancien"], reponse["nouveau"]

    # --- Tâche de chaque minute -------------------------------------------- #

    async def echeances(self, maintenant: str) -> list[dict]:
        resultats = await self._appel("POST", "/maintenance/tick", {})
        for resultat in resultats:
            self._copier(resultat["tournoi"])
        return resultats
