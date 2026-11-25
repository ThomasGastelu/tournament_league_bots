"""Outils communs aux tests : faux tournoi, fausse messagerie, faux générateur de pp."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

SERVEUR = "1540386765054148639"
SALON = "1543205821490528366"
ADMIN = "999"


def tournoi_inscription(nb_equipes: int, tournoi_id: str = "1571169059024928818", **modifs) -> dict:
    """Fichier d'inscription au même format que rl_bot_ppname_creator (avec pseudo_jeu)."""
    equipes = []
    for i in range(1, nb_equipes + 1):
        capitaine = str(1000 + i * 10)
        equipes.append({
            "id": i,
            "nom": f"Equipe{i}",
            "capitaine_id": capitaine,
            "statut": "inscrite",
            "cree_le": "2026-11-14T15:25:20",
            "annulee_le": None,
            "raison_annulation": None,
            "joueurs": [
                {"id": capitaine, "pseudo": f"cap{i}", "pseudo_jeu": f"Cap{i}RL", "statut": "confirme"},
                {"id": str(1000 + i * 10 + 1), "pseudo": f"mate{i}", "pseudo_jeu": f"Mate{i}RL", "statut": "confirme"},
            ],
        })
    tournoi = {
        "id": tournoi_id, "titre": "Tournoi test", "cashprize": "50", "joueurs_par_equipe": 2,
        "equipes_max": nb_equipes, "liste_attente_max": nb_equipes * 4, "date": "20 septembre",
        "serveur_id": SERVEUR, "salon_id": SALON, "message_id": "1", "cree_par": ADMIN,
        "cree_le": "2026-11-14T15:24:54", "equipes": equipes,
    }
    tournoi.update(modifs)
    return tournoi


def ecrire_inscription(dossier: Path, tournoi: dict) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / f"{tournoi['id']}.json").write_text(json.dumps(tournoi, ensure_ascii=False), encoding="utf-8")


def faux_pp(nombre: int, sortie: Path, ronde: int = 1) -> list[dict]:
    """Remplace pp.generer_parties (noms reconnaissables dans les tests) : même format de fichier."""
    parties = [{"match": i, "nom": f"tomato_test{i}", "mot_de_passe": f"tomato_test{i}"}
               for i in range(1, nombre + 1)]
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({"genere_le": "2026-11-14T15:00:00", "parties": parties}), encoding="utf-8")
    return parties


def score_auto(numero: int, zone: int) -> tuple[int, int]:
    """Score (équipe A, équipe B) déclaré par `declaration_auto` : A gagne une zone sur deux."""
    return (3, 1) if (numero + zone) % 2 else (0, 2)


class FausseMessagerie:
    """Fausse messagerie Discord (il faut brancher `gestionnaire` pour les clics automatiques).

    `clic_auto` : le capitaine clique tout de suite sur « Partie privée créée ».
    `declaration_auto` : au premier bouton « Déclarer le score » reçu par une équipe, elle déclare
    le score de `score_auto` (les deux équipes sont donc d'accord)."""

    def __init__(self, clic_auto: bool = True, salon_discussion: int | Exception | None = 4242,
                 declaration_auto: bool = False) -> None:
        # Salon de discussion : ID renvoyé, None (pas créé) ou exception levée.
        self.salon_discussion = salon_discussion
        self.salons_crees: list[tuple[str, int]] = []  # (tournoi, nombre de MP déjà envoyés à ce moment)
        self.acces_salon: list[tuple[str | None, str | None]] = []  # (ajouté, retiré)
        self.acces_salon_possible = True  # False : comme sans « Gérer les rôles »
        self.salons_supprimes: list[str] = []
        self.suppression_salon_possible = True  # False : comme sans « Gérer les salons »
        self.journaux: list[str] = []      # messages d'information de LOG_CHANNEL
        self.messages_salons: list[tuple[str, str, bool]] = []  # (salon, texte, @here)
        self.resultats_rondes: list[list] = []  # récaps de fin de round (SALON_RESULTATS)
        self.textes_resultats: list[str] = []   # autres messages du salon des résultats (lancement)
        self.mps: list[tuple[str, str]] = []
        self.boutons: list[tuple[str, tuple[int, int, int]]] = []  # déclaration : (joueur, (round, zone, équipe))
        self.boutons_pp: list[tuple[str, tuple[int, int]]] = []    # partie créée : (joueur, (round, zone))
        self.boutons_confirmation: list[tuple[str, int]] = []      # valider sa participation : (joueur, équipe)
        self.annonces: list[tuple[str | None, list | None]] = []
        self.alertes: list[tuple[str | None, list | None]] = []
        self.clic_auto = clic_auto
        self.declaration_auto = declaration_auto
        self._declarees: set[tuple[str, int, int, int]] = set()
        self.gestionnaire = None
        self._clics: set[asyncio.Task] = set()

    async def pret(self) -> None:
        pass

    async def mp(self, etat, joueur_id, texte, secours=None, declaration=None, pp_creee=None,
                 confirmation=None) -> bool:
        self.mps.append((joueur_id, texte))
        if confirmation is not None:
            self.boutons_confirmation.append((joueur_id, confirmation))
        if declaration:
            self.boutons.append((joueur_id, declaration))
            cle = (etat["tournoi_id"], *declaration)
            if self.declaration_auto and self.gestionnaire is not None and cle not in self._declarees:
                self._declarees.add(cle)
                self._lancer(self._declarer(etat, declaration, joueur_id))
        if pp_creee:
            self.boutons_pp.append((joueur_id, pp_creee))
            if self.clic_auto and self.gestionnaire is not None:
                self._lancer(self._cliquer(etat["tournoi_id"], pp_creee, joueur_id))
        return True

    def _lancer(self, coro) -> None:
        tache = asyncio.create_task(coro)
        self._clics.add(tache)
        tache.add_done_callback(self._clics.discard)

    async def _declarer(self, etat, declaration, joueur_id) -> None:
        numero, zone, equipe_id = declaration
        match = next(m for r in etat["rondes"] if r["numero"] == numero for m in r["matchs"] if m["zone"] == zone)
        a, b = score_auto(numero, zone)
        pour, contre = (a, b) if equipe_id == match["equipe_a"] else (b, a)
        try:
            await self.gestionnaire.declarer_score(etat["tournoi_id"], numero, zone, equipe_id, pour, contre,
                                                   par=joueur_id)
        except Exception:  # tournoi arrêté entre-temps…
            pass
        finally:
            self._declarees.discard((etat["tournoi_id"], *declaration))  # le tournoi peut être relancé

    async def _cliquer(self, tournoi_id, pp_creee, joueur_id) -> None:
        try:
            await self.gestionnaire.signaler_pp_creee(tournoi_id, *pp_creee, par=joueur_id)
        except Exception:  # tournoi arrêté entre-temps…
            pass

    async def annonce(self, etat, texte=None, embeds=None) -> None:
        self.annonces.append((texte, embeds))

    async def alerte(self, etat, texte=None, embeds=None) -> None:
        self.alertes.append((texte, embeds))

    async def creer_salon_discussion(self, etat) -> int | None:
        self.salons_crees.append((etat["tournoi_id"], len(self.mps)))
        if isinstance(self.salon_discussion, Exception):
            raise self.salon_discussion
        return self.salon_discussion

    async def salon_existe(self, salon_id) -> bool:
        return str(salon_id) not in self.salons_supprimes

    async def message_salon(self, salon_id, texte, *, mentionner_here=False) -> bool:
        self.messages_salons.append((str(salon_id), texte, mentionner_here))
        return True

    async def changer_acces_salon(self, etat, *, ajouter=None, retirer=None) -> bool:
        self.acces_salon.append((ajouter, retirer))
        return self.acces_salon_possible

    async def supprimer_salon_discussion(self, etat, salon_id) -> bool:
        if self.suppression_salon_possible:
            self.salons_supprimes.append(salon_id)
        return self.suppression_salon_possible

    async def journal(self, texte) -> None:
        self.journaux.append(texte)

    async def resultats(self, etat, texte=None, embeds=None) -> None:
        if embeds:
            self.resultats_rondes.append(embeds)
        if texte:
            self.textes_resultats.append(texte)

    def titres_alertes(self) -> list[str]:
        """Texte de chaque alerte (embeds compris), pour les assertions."""
        return [" ".join([t or ""] + [(e.title or "") + " " + (e.description or "") for e in (embeds or [])])
                for t, embeds in self.alertes]

    def mps_de(self, joueur_id: str) -> list[str]:
        return [t for j, t in self.mps if j == joueur_id]


async def demarrer(g, tournoi_id: str, nombre_de_rondes: int, **kwargs) -> dict:
    """/start_tournament_rl dans les tests : /start_tournament_init est obligatoire, on écrit d'abord un
    init sans salon ni validation des participations s'il n'y en a pas (comme un init avec délai 0)."""
    from bot_tournament_manager import logique as L

    tournoi = g.stockage.charger_inscription(tournoi_id)
    if tournoi is not None and g.stockage.charger_init(tournoi_id) is None:
        g.stockage.sauvegarder_init(L.etat_init(tournoi, [], par=ADMIN, maintenant="2026-11-14T15:00:00"))
    return await g.demarrer(tournoi_id, nombre_de_rondes, **kwargs)


async def attendre_que(condition, delai: float = 5.0) -> None:
    """Attend (sans bloquer la boucle) qu'une condition devienne vraie."""
    for _ in range(int(delai / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition jamais remplie")
