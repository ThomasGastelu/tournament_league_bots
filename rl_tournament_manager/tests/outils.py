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


def faux_pp(_script: Path, nombre: int, sortie: Path) -> list[dict]:
    """Remplace generer_pp_names.py : même format de fichier."""
    parties = [{"match": i, "nom": f"tomato_test{i}", "mot_de_passe": f"tomato_test{i}"}
               for i in range(1, nombre + 1)]
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({"genere_le": "2026-11-14T15:00:00", "parties": parties}), encoding="utf-8")
    return parties


class FausseMessagerie:
    """Fausse messagerie Discord. Avec `clic_auto`, le capitaine clique tout de suite sur
    « Partie privée créée » (il faut brancher `gestionnaire`)."""

    def __init__(self, clic_auto: bool = True, salon_discussion: int | Exception | None = 4242) -> None:
        # Salon de discussion : ID renvoyé, None (pas créé) ou exception levée.
        self.salon_discussion = salon_discussion
        self.salons_crees: list[tuple[str, int]] = []  # (tournoi, nombre de MP déjà envoyés à ce moment)
        self.acces_salon: list[tuple[str | None, str | None]] = []  # (ajouté, retiré)
        self.acces_salon_possible = True  # False : comme sans « Gérer les rôles »
        self.journaux: list[str] = []      # messages d'information de LOG_CHANNEL
        self.mps: list[tuple[str, str]] = []
        self.boutons: list[tuple[str, tuple[int, int, int]]] = []  # déclaration : (joueur, (round, zone, équipe))
        self.boutons_pp: list[tuple[str, tuple[int, int]]] = []    # partie créée : (joueur, (round, zone))
        self.annonces: list[tuple[str | None, list | None]] = []
        self.alertes: list[tuple[str | None, list | None]] = []
        self.clic_auto = clic_auto
        self.gestionnaire = None
        self._clics: set[asyncio.Task] = set()

    async def pret(self) -> None:
        pass

    async def mp(self, etat, joueur_id, texte, secours=None, declaration=None, pp_creee=None) -> bool:
        self.mps.append((joueur_id, texte))
        if declaration:
            self.boutons.append((joueur_id, declaration))
        if pp_creee:
            self.boutons_pp.append((joueur_id, pp_creee))
            if self.clic_auto and self.gestionnaire is not None:
                tache = asyncio.create_task(self._cliquer(etat["tournoi_id"], pp_creee, joueur_id))
                self._clics.add(tache)
                tache.add_done_callback(self._clics.discard)
        return True

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

    async def changer_acces_salon(self, etat, *, ajouter=None, retirer=None) -> bool:
        self.acces_salon.append((ajouter, retirer))
        return self.acces_salon_possible

    async def journal(self, texte) -> None:
        self.journaux.append(texte)

    def titres_alertes(self) -> list[str]:
        """Texte de chaque alerte (embeds compris), pour les assertions."""
        return [" ".join([t or ""] + [(e.title or "") + " " + (e.description or "") for e in (embeds or [])])
                for t, embeds in self.alertes]

    def mps_de(self, joueur_id: str) -> list[str]:
        return [t for j, t in self.mps if j == joueur_id]


async def attendre_que(condition, delai: float = 5.0) -> None:
    """Attend (sans bloquer la boucle) qu'une condition devienne vraie."""
    for _ in range(int(delai / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition jamais remplie")
