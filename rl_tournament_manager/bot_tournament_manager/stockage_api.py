"""Stockage des tournois dans la base de données, via l'API du site (routes /api/bot/*).

Utilisé quand `API_URL` est rempli dans le `.env` (même modèle que inscription_manager).

- Inscriptions : lues dans l'API (`GET /api/bot/tournaments…`), plus dans les fichiers copiés
  par inscription_manager. `rafraichir_inscription` / `rafraichir_inscriptions` les relisent
  (async) ; `charger_inscription` / `lister_inscriptions` rendent ce qui a été relu.
- État d'un tournoi lancé et init (`/start_tournament_init`) : toujours écrits d'abord dans
  `data/` (copie de secours, lue par le bot comme avant), puis envoyés à l'API en tâche de
  fond (`PUT .../run`, `PUT .../launch-init`), un tournoi après l'autre et dans l'ordre.
  Si l'API ne répond pas, le tournoi continue : l'envoi est réessayé, et comme on envoie
  toujours l'état complet, une sauvegarde ratée est rattrapée par la suivante.
- Les envois en attente sont notés dans `data/synchro/<id>.json` (avec la version de l'API) :
  après un arrêt ou un plantage, `synchroniser()` les reprend au démarrage.
- Pas d'archive : relancer un tournoi efface l'ancien lancement dans l'API (`DELETE .../run`).
- `/reset_tournament_rl` efface aussi le lancement et l'init dans l'API (`DELETE .../run-data`),
  jamais l'inscription.
- Équipes qui n'ont pas validé leur participation à temps : annulées dans l'inscription
  (`POST .../teams/<numero>/cancel`).

L'état contient les mots de passe des parties privées : ne jamais logger les corps envoyés.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import aiohttp

from . import logique as L
from .stockage import Stockage, _verifier_id

log = logging.getLogger(__name__)

DELAI_REPONSE_SECONDES = 10
DELAIS_REESSAI = (5.0, 15.0, 60.0, 300.0)  # secondes entre deux essais d'envoi (le dernier se répète)
DUREE_LISTE_SECONDES = 30.0  # l'autocomplétion relit la liste des tournois au plus toutes les 30 s
ATTENTE_ARRET_SECONDES = 10.0  # à l'arrêt du bot, temps laissé aux envois en attente
LONGUEUR_MIN_CLE_API = 32  # comme l'API, qui refuse une BOT_API_KEY plus courte
RAISON_PLACE_PERDUE = "participation non validée à temps (/start_tournament_init)"

MESSAGE_API_INJOIGNABLE = "Le serveur des tournois ne répond pas. Réessaie dans un instant."
MESSAGE_ROUTE_ABSENTE = ("Le serveur des tournois ne sait pas encore faire ça (route absente de l'API). "
                         "Mets à jour le site, puis réessaie.")
MESSAGE_API_REFUSE = ("Le serveur des tournois refuse le bot : vérifie que `BOT_API_KEY` est la même "
                      "dans le `.env` du bot et dans celui de l'API.")

# Opérations envoyées à l'API, par tournoi et dans l'ordre.
ENVOYER_ETAT = "etat"
ENVOYER_INIT = "init"
SUPPRIMER_ETAT = "supprimer_etat"
SUPPRIMER_TOUT = "supprimer_tout"


class ErreurAPI(L.ErreurTournoi):
    """Erreur renvoyée par l'API (ou API injoignable), avec un message en français."""

    def __init__(self, message: str, statut: int | None = None, erreur: str = "") -> None:
        super().__init__(message)
        self.statut = statut
        self.erreur = erreur  # message d'origine de l'API (« Run version conflict »…)


def verifier_parametres(url: str | None, cle: str | None) -> tuple[str, str] | None:
    """(url, clé) si API_URL est rempli, None sinon. ValueError si l'un des deux est mal rempli."""
    url, cle = (url or "").strip(), (cle or "").strip()
    if not url:
        return None
    if not re.match(r"https?://[^\s/]+", url):
        raise ValueError(f"API_URL doit commencer par http:// ou https:// (ex : API_URL=http://localhost), "
                         f"pas « {url} ».")
    if len(cle) < LONGUEUR_MIN_CLE_API:
        raise ValueError(f"BOT_API_KEY manquante ou trop courte ({LONGUEUR_MIN_CLE_API} caractères minimum) : "
                         "mets la même clé que dans le .env de l'API.")
    return url.rstrip("/"), cle


def traduire_erreur(statut: int, corps: Any) -> str:
    """Message en français pour une réponse d'erreur de l'API."""
    message = corps.get("error", "") if isinstance(corps, dict) else ""
    if statut in (401, 503):
        return MESSAGE_API_REFUSE
    if statut >= 500:
        return MESSAGE_API_INJOIGNABLE
    simples = {
        "Tournament not found": "Ce tournoi n'existe plus dans le serveur des tournois.",
        "Run not found": "Ce tournoi n'a pas été lancé.",
        "Launch init not found": "Pas de `/start_tournament_init` pour ce tournoi.",
        "Team not found": "Cette équipe n'existe pas dans l'inscription.",
        "Team already cancelled": "Cette équipe est déjà annulée.",
        "Team does not match tournament": ("Les équipes du tournoi ne correspondent plus à l'inscription "
                                           "(équipe supprimée ou modifiée sur le site ?)."),
        "Run version conflict": "Le tournoi a été modifié ailleurs en même temps.",
        "Launch init version conflict": "Le tournoi a été modifié ailleurs en même temps.",
        "Run already exists": "Ce tournoi a déjà été lancé.",
    }
    if message in simples:
        return simples[message]
    if statut == 404:
        return MESSAGE_ROUTE_ABSENTE
    if statut == 413:
        return "Le tournoi est trop gros pour le serveur des tournois."
    if statut == 400:
        details = corps.get("details") if isinstance(corps, dict) else None
        champs = ", ".join(d.get("path") or "?" for d in details if isinstance(d, dict)) \
            if isinstance(details, list) else ""
        return "Données refusées par le serveur des tournois" + (f" ({champs})." if champs else ".")
    return f"Le serveur des tournois a refusé l'action ({statut} {message})."


class StockageAPI(Stockage):
    def __init__(self, url: str, cle: str, dossier_donnees: Path, *,
                 delais_reessai: tuple[float, ...] = DELAIS_REESSAI) -> None:
        super().__init__(None, dossier_donnees)
        self.url = url.rstrip("/")
        self._cle = cle
        self._session: aiohttp.ClientSession | None = None
        self._boucle: asyncio.AbstractEventLoop | None = None
        self.delais_reessai = delais_reessai
        self.dossier_synchro = self.dossier_donnees / "synchro"
        self.dossier_synchro.mkdir(parents=True, exist_ok=True)
        self._inscriptions: dict[str, dict] = {}
        self._listes: dict[str, tuple[float, list[dict]]] = {}  # serveur → (heure, tournois)
        self._synchro: dict[str, dict] = {}  # tournoi → {"version_etat", "version_init", "a_envoyer"}
        self._envois: dict[str, asyncio.Task] = {}

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
                     params: dict | None = None) -> Any:
        try:
            statut, donnees = await self._requete(methode, chemin, corps, params)
        except (aiohttp.ClientError, TimeoutError, OSError) as erreur:
            raise ErreurAPI(MESSAGE_API_INJOIGNABLE) from erreur
        if statut >= 400:
            message = donnees.get("error", "") if isinstance(donnees, dict) else ""
            # Jamais le corps envoyé dans les logs (mots de passe des parties privées).
            niveau = logging.ERROR if statut in (401, 503) or statut >= 500 else logging.INFO
            log.log(niveau, "API %s %s -> %s %s", methode, chemin, statut, message)
            raise ErreurAPI(traduire_erreur(statut, donnees), statut, message)
        return donnees

    async def fermer(self) -> None:
        """Arrêt du bot : laisse un peu de temps aux envois en attente (repris au prochain démarrage sinon)."""
        envois = [t for t in self._envois.values() if not t.done()]
        if envois:
            _, restants = await asyncio.wait(envois, timeout=ATTENTE_ARRET_SECONDES)
            for tache in restants:
                tache.cancel()
            await asyncio.gather(*restants, return_exceptions=True)
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # --- Inscriptions ---------------------------------------------------- #

    async def rafraichir_inscription(self, tournoi_id: str) -> None:
        tournoi_id = str(tournoi_id).strip()
        if not tournoi_id.isdigit():
            return
        try:
            tournoi = await self._appel("GET", f"/tournaments/{tournoi_id}")
        except ErreurAPI as erreur:
            if erreur.statut in (400, 404) and erreur.erreur in ("Tournament not found", "Validation failed"):
                self._inscriptions.pop(tournoi_id, None)
                return
            raise
        if isinstance(tournoi, dict):
            self._inscriptions[tournoi_id] = tournoi

    async def rafraichir_inscriptions(self, serveur_id: str) -> None:
        """Liste légère des tournois du serveur (id, titre, date, heure), relue au plus toutes les 30 s."""
        serveur_id = str(serveur_id)
        deja = self._listes.get(serveur_id)
        if deja and time.monotonic() - deja[0] < DUREE_LISTE_SECONDES:
            return
        resumes = await self._appel("GET", "/tournaments", params={"serveur_id": serveur_id})
        if isinstance(resumes, list):
            self._listes[serveur_id] = (time.monotonic(), [dict(r, serveur_id=serveur_id) for r in resumes
                                                           if isinstance(r, dict) and "id" in r])

    def charger_inscription(self, tournoi_id: str) -> dict | None:
        """Inscription relue par le dernier `rafraichir_inscription` (None si inconnue)."""
        return self._inscriptions.get(str(tournoi_id).strip())

    def lister_inscriptions(self, serveur_id: str | None = None) -> list[dict]:
        """Tournois relus par `rafraichir_inscriptions` : la version complète si elle a déjà été lue
        (avec les équipes), sinon le résumé (sans `equipes`)."""
        if serveur_id is None:
            listes = [liste for _, liste in self._listes.values()]
        else:
            listes = [self._listes[serveur_id][1]] if serveur_id in self._listes else []
        return [self._inscriptions.get(r["id"], r) for liste in listes for r in liste]

    async def annuler_equipes_perdues(self, tournoi_id: str, equipes: list[dict]) -> None:
        for equipe in equipes:
            try:
                await self._appel("POST", f"/tournaments/{tournoi_id}/teams/{int(equipe['id'])}/cancel",
                                  {"raison": RAISON_PLACE_PERDUE})
            except ErreurAPI as erreur:
                if erreur.erreur == "Team already cancelled":
                    continue
                log.warning("Tournoi %s : l'équipe %s (« %s ») n'a pas pu être annulée dans l'inscription (%s). "
                            "Retire-la avec /tournoi_rl_remove_team.", tournoi_id, equipe.get("id"),
                            equipe.get("nom"), erreur)
            else:
                log.info("Tournoi %s : équipe %s annulée dans l'inscription (place perdue)", tournoi_id,
                         equipe.get("id"))

    # --- Écritures : copie locale + envoi à l'API ------------------------- #

    def sauvegarder_etat(self, etat: dict) -> None:
        super().sauvegarder_etat(etat)
        self._planifier(etat["tournoi_id"], ENVOYER_ETAT)

    def sauvegarder_init(self, init: dict) -> None:
        super().sauvegarder_init(init)
        self._planifier(init["tournoi_id"], ENVOYER_INIT)

    def archiver_etat(self, tournoi_id: str, suffixe: str) -> Path | None:
        """Relance d'un tournoi : pas d'archive, l'ancien lancement est effacé (ici et dans l'API)."""
        chemin = self.dossier_etats / f"{_verifier_id(tournoi_id)}.json"
        try:
            chemin.unlink()
        except FileNotFoundError:
            pass
        self._planifier(tournoi_id, SUPPRIMER_ETAT)
        return None

    def supprimer_tournoi(self, tournoi_id: str) -> list[Path]:
        supprimes = super().supprimer_tournoi(tournoi_id)
        tournoi_id = _verifier_id(tournoi_id)
        synchro = self._lire_synchro(tournoi_id)
        synchro["a_envoyer"] = []  # plus rien à envoyer : tout est effacé
        self._planifier(tournoi_id, SUPPRIMER_TOUT)
        return supprimes

    def _planifier(self, tournoi_id: str, operation: str) -> None:
        tournoi_id = _verifier_id(tournoi_id)
        synchro = self._lire_synchro(tournoi_id)
        a_envoyer = synchro["a_envoyer"]
        # Deux envois du même état à la suite : un seul suffit (on envoie le fichier le plus récent).
        if not a_envoyer or a_envoyer[-1] != operation:
            a_envoyer.append(operation)
        self._ecrire_synchro(tournoi_id)
        self._lancer_envois(tournoi_id)

    def _lancer_envois(self, tournoi_id: str) -> None:
        try:
            boucle = asyncio.get_running_loop()
        except RuntimeError:
            return  # hors du bot (script) : synchroniser() enverra plus tard
        tache = self._envois.get(tournoi_id)
        if tache is None or tache.done():
            self._envois[tournoi_id] = boucle.create_task(self._envoyer(tournoi_id))

    async def attendre_envois(self) -> None:
        """Attend que tout soit parti (tests, import)."""
        while True:
            envois = [t for t in self._envois.values() if not t.done()]
            if not envois:
                return
            await asyncio.gather(*envois, return_exceptions=True)

    async def _envoyer(self, tournoi_id: str) -> None:
        essai = 0
        synchro = self._lire_synchro(tournoi_id)
        while synchro["a_envoyer"]:
            # Retirée AVANT l'envoi : une sauvegarde faite pendant l'envoi en replanifie un autre.
            operation = synchro["a_envoyer"].pop(0)
            self._ecrire_synchro(tournoi_id)
            try:
                await self._executer(tournoi_id, operation, synchro)
            except asyncio.CancelledError:
                self._remettre(tournoi_id, synchro, operation)
                raise
            except ErreurAPI as erreur:
                if erreur.statut in (400, 404, 409, 413):
                    # Refus définitif : réessayer ne changerait rien. La prochaine sauvegarde réessaiera.
                    log.error("Tournoi %s : l'API refuse l'envoi (%s) : %s Le tournoi continue avec la copie "
                              "locale.", tournoi_id, operation, erreur)
                    continue
                self._remettre(tournoi_id, synchro, operation)
                delai = self.delais_reessai[min(essai, len(self.delais_reessai) - 1)]
                if essai == 0 or essai % 10 == 0:
                    log.warning("Tournoi %s : envoi à l'API impossible (%s). Le tournoi continue avec la copie "
                                "locale ; nouvel essai dans %s s.", tournoi_id, erreur, int(delai))
                essai += 1
                await asyncio.sleep(delai)
            except Exception:
                log.exception("Tournoi %s : erreur pendant l'envoi à l'API (%s)", tournoi_id, operation)
            else:
                if essai:
                    log.warning("Tournoi %s : l'API répond de nouveau, envoi fait.", tournoi_id)
                essai = 0

    def _remettre(self, tournoi_id: str, synchro: dict, operation: str) -> None:
        if not synchro["a_envoyer"] or synchro["a_envoyer"][0] != operation:
            synchro["a_envoyer"].insert(0, operation)
        self._ecrire_synchro(tournoi_id)

    async def _executer(self, tournoi_id: str, operation: str, synchro: dict) -> None:
        base = f"/tournaments/{tournoi_id}"
        if operation in (ENVOYER_ETAT, ENVOYER_INIT):
            chemin, cle = (f"{base}/run", "version_etat") if operation == ENVOYER_ETAT \
                else (f"{base}/launch-init", "version_init")
            document = self.charger_etat(tournoi_id) if operation == ENVOYER_ETAT else self.charger_init(tournoi_id)
            if document is None:
                return  # effacé entre-temps
            try:
                reponse = await self._appel("PUT", chemin, {"etat": document, "version": synchro.get(cle)})
            except ErreurAPI as erreur:
                if erreur.erreur not in ("Run version conflict", "Run already exists",
                                         "Launch init version conflict"):
                    raise
                # Ce bot est le seul à écrire ces données : sa copie locale est la bonne. On reprend la
                # version de l'API et on renvoie.
                actuel = await self._appel("GET", chemin)
                reponse = await self._appel("PUT", chemin, {"etat": document, "version": actuel.get("version")})
            synchro[cle] = reponse.get("version") if isinstance(reponse, dict) else None
        elif operation == SUPPRIMER_ETAT:
            try:
                await self._appel("DELETE", f"{base}/run")
            except ErreurAPI as erreur:
                if erreur.erreur not in ("Run not found", "Tournament not found"):
                    raise
            synchro["version_etat"] = None
        elif operation == SUPPRIMER_TOUT:
            try:
                await self._appel("DELETE", f"{base}/run-data")
            except ErreurAPI as erreur:
                if erreur.erreur != "Tournament not found":
                    raise
            synchro["version_etat"] = synchro["version_init"] = None
        self._ecrire_synchro(tournoi_id)

    # --- data/synchro/<id>.json --------------------------------------------- #

    def _lire_synchro(self, tournoi_id: str) -> dict:
        tournoi_id = _verifier_id(tournoi_id)
        if tournoi_id not in self._synchro:
            donnees = None
            try:
                donnees = json.loads((self.dossier_synchro / f"{tournoi_id}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            if not isinstance(donnees, dict):
                donnees = {}
            self._synchro[tournoi_id] = {
                "version_etat": donnees.get("version_etat"),
                "version_init": donnees.get("version_init"),
                "a_envoyer": [o for o in donnees.get("a_envoyer", []) if o in
                              (ENVOYER_ETAT, ENVOYER_INIT, SUPPRIMER_ETAT, SUPPRIMER_TOUT)],
            }
        return self._synchro[tournoi_id]

    def _ecrire_synchro(self, tournoi_id: str) -> None:
        chemin = self.dossier_synchro / f"{tournoi_id}.json"
        synchro = self._synchro[tournoi_id]
        if not synchro["a_envoyer"] and synchro["version_etat"] is None and synchro["version_init"] is None:
            try:
                chemin.unlink()
            except FileNotFoundError:
                pass
            return
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(json.dumps(synchro, indent=2) + "\n", encoding="utf-8")
        os.replace(temporaire, chemin)

    # --- Démarrage -------------------------------------------------------- #

    async def synchroniser(self, serveur_id: str | None) -> None:
        """Au démarrage du bot, avant `reprendre()` :
        1. reprend les envois qui n'étaient pas partis (copie locale plus récente que l'API) ;
        2. récupère dans l'API les tournois lancés et les inits absents ou plus anciens ici
           (bot déplacé sur un autre PC, dossier data/ effacé…).
        Sans `serveur_id` (GUILD_ID vide), seuls les tournois en cours sont récupérés."""
        for chemin in sorted(self.dossier_synchro.glob("*.json")):
            if chemin.stem.isdigit():
                self._lire_synchro(chemin.stem)
        en_attente = {t for t, s in self._synchro.items() if s["a_envoyer"]}

        try:
            params = {"serveur_id": serveur_id} if serveur_id else {"statut": L.EN_COURS}
            lancements = await self._appel("GET", "/runs", params=params)
            inits = await self._appel("GET", "/launch-inits", params={"serveur_id": serveur_id}) \
                if serveur_id else []
        except ErreurAPI as erreur:
            log.warning("Synchronisation avec l'API impossible au démarrage (%s) : le bot part des fichiers "
                        "locaux et enverra ses sauvegardes dès que l'API répondra.", erreur)
            lancements, inits = [], []

        recuperes = 0
        # Écriture locale seule (sans renvoyer à l'API ce qui en vient).
        ecrire_etat, ecrire_init = super().sauvegarder_etat, super().sauvegarder_init
        a_recuperer = [(l, "version_etat", self.charger_etat, ecrire_etat) for l in lancements or []] \
            + [(i, "version_init", self.charger_init, ecrire_init) for i in inits or []]
        for element, cle, charger, ecrire in a_recuperer:
            document = element.get("etat") if isinstance(element, dict) else None
            if not isinstance(document, dict) or not str(document.get("tournoi_id", "")).isdigit():
                continue
            tournoi_id = document["tournoi_id"]
            if tournoi_id in en_attente:
                continue  # la copie locale est plus récente : elle sera envoyée
            synchro = self._lire_synchro(tournoi_id)
            if charger(tournoi_id) is None or synchro[cle] != element.get("version"):
                ecrire(document)
                synchro[cle] = element.get("version")
                self._ecrire_synchro(tournoi_id)
                recuperes += 1
        if recuperes:
            log.info("%s tournoi(s) récupéré(s) depuis l'API", recuperes)
        for tournoi_id in sorted(en_attente):
            log.info("Tournoi %s : envoi à l'API des sauvegardes faites hors ligne", tournoi_id)
            self._lancer_envois(tournoi_id)

    # --- Import des anciens fichiers -------------------------------------- #

    async def importer(self) -> dict[str, int]:
        """Envoie à l'API les états et inits locaux jamais envoyés (fichiers d'avant API_URL).
        Ce qui existe déjà dans l'API n'est pas écrasé. Les archives (anciens lancements) ne sont
        pas importées. Renvoie {"importe", "deja", "erreur"}."""
        bilan = {"importe": 0, "deja": 0, "erreur": 0}
        for documents, cle, route in ((self.lister_etats(), "version_etat", "run"),
                                      (self.lister_inits(), "version_init", "launch-init")):
            for document in documents:
                tournoi_id = document["tournoi_id"]
                synchro = self._lire_synchro(tournoi_id)
                if synchro[cle] is not None:
                    bilan["deja"] += 1
                    continue
                try:
                    reponse = await self._appel("PUT", f"/tournaments/{tournoi_id}/{route}",
                                                {"etat": document, "version": None})
                except ErreurAPI as erreur:
                    if erreur.erreur in ("Run already exists", "Launch init version conflict",
                                         "Launch init already exists"):
                        bilan["deja"] += 1
                    else:
                        print(f"❌ {route} {tournoi_id} : {erreur}")
                        bilan["erreur"] += 1
                    continue
                synchro[cle] = reponse.get("version") if isinstance(reponse, dict) else None
                self._ecrire_synchro(tournoi_id)
                print(f"✅ {route} {tournoi_id} ({document.get('titre', '?')})")
                bilan["importe"] += 1
        return bilan
