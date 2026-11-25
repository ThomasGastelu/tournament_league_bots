"""Règles du tournoi : places, liste d'attente, validations, promotions.

Ce module ne dépend pas de Discord : il travaille sur le dictionnaire
d'un tournoi (le contenu du fichier JSON), ce qui permet de le tester.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Statuts d'une équipe
INSCRITE = "inscrite"
LISTE_ATTENTE = "liste_attente"
ANNULEE = "annulee"

# Statuts d'une réservation de place
RESERVATION_ACTIVE = "active"
RESERVATION_UTILISEE = "utilisee"
RESERVATION_EXPIREE = "expiree"
RESERVATION_ANNULEE = "annulee"

# Statuts d'un joueur dans son équipe
CONFIRME = "confirme"
EN_ATTENTE = "en_attente"
REFUSE = "refuse"

MULTIPLICATEUR_LISTE_ATTENTE = 4
LONGUEUR_MAX_TITRE = 100
LONGUEUR_MAX_CASHPRIZE = 100
EQUIPES_MAX_LIMITE = 128
LONGUEUR_MAX_NOM_EQUIPE = 32
LONGUEUR_MAX_PSEUDO_JEU = 32
LONGUEUR_MAX_PSEUDO = 32  # pseudo Discord enregistré dans l'équipe
AVERTISSEMENT_PSEUDO_JEU = "⚠️ Exactement le même que dans le jeu, sinon on ne pourra pas t'évaluer."
# Temps laissé aux coéquipiers pour confirmer, sinon l'équipe est désinscrite.
# Valeur par défaut : au démarrage, main.py la remplace par DELAI_CONFIRMATION_MINUTES du fichier .env.
# Chaque équipe garde l'heure limite calculée à son inscription (« confirmer_avant ») :
# changer le délai ne touche que les nouvelles inscriptions.
DELAI_CONFIRMATION_MINUTES = 30
DELAI_CONFIRMATION_MAX_MINUTES = 7 * 24 * 60  # une semaine
# Délai avant l'ouverture des inscriptions (option « delay » de /tournoi_rl).
DELAI_OUVERTURE_MAX_MINUTES = 7 * 24 * 60  # une semaine
# Durée maximale d'une réservation de place (/tournoi_rl_reserve).
DUREE_RESERVATION_MAX_MINUTES = 30 * 24 * 60  # 30 jours


class ErreurTournoi(Exception):
    """Erreur dont le message peut être montré tel quel au joueur."""


# --------------------------------------------------------------------------- #
# Création
# --------------------------------------------------------------------------- #

def nouveau_tournoi(
    *,
    tournoi_id: str,
    titre: str,
    cashprize: str,
    joueurs_par_equipe: int,
    equipes_max: int,
    date: str,
    serveur_id: str,
    salon_id: str,
    cree_par: str,
    maintenant: str,
    delai_ouverture_minutes: int = 0,
) -> dict:
    """Nouveau tournoi. Avec `delai_ouverture_minutes` > 0, les inscriptions n'ouvrent
    qu'après ce délai (« ouverture_inscriptions ») : le temps de réserver des places.
    """
    if not 1 <= joueurs_par_equipe <= 3:
        raise ErreurTournoi("Le nombre de joueurs par équipe doit être entre 1 et 3.")
    if equipes_max < 1:
        raise ErreurTournoi("Il faut au moins 1 équipe.")
    if not 0 <= delai_ouverture_minutes <= DELAI_OUVERTURE_MAX_MINUTES:
        raise ErreurTournoi(
            f"Le délai avant l'ouverture des inscriptions doit être entre 0 et {DELAI_OUVERTURE_MAX_MINUTES} minutes.")
    return {
        "id": tournoi_id,
        "titre": titre,
        "cashprize": cashprize,
        "joueurs_par_equipe": joueurs_par_equipe,
        "equipes_max": equipes_max,
        "liste_attente_max": equipes_max * MULTIPLICATEUR_LISTE_ATTENTE,
        "date": date,
        "serveur_id": serveur_id,
        "salon_id": salon_id,
        "message_id": None,
        "cree_par": cree_par,
        "cree_le": maintenant,
        # Heure d'ouverture des inscriptions ; None = ouvertes. Le bot la remet à None
        # une fois l'heure passée (et met l'annonce à jour).
        "ouverture_inscriptions": (
            (lire_date(maintenant) + timedelta(minutes=delai_ouverture_minutes)).isoformat(timespec="seconds")
            if delai_ouverture_minutes else None
        ),
        "reservations": [],
        "equipes": [],
    }


def completer_capitaines(tournoi: dict) -> bool:
    """Ajoute le champ « capitaine » aux équipes enregistrées avant qu'il existe.

    Retourne True si le tournoi a été modifié.
    """
    modifie = False
    for i, equipe in enumerate(tournoi["equipes"]):
        if "capitaine" in equipe:
            continue
        capitaine = joueur_dans_equipe(equipe, equipe["capitaine_id"]) or {}
        # On reconstruit le dictionnaire pour placer « capitaine » juste après « capitaine_id ».
        nouvelle = {}
        for cle, valeur in equipe.items():
            nouvelle[cle] = valeur
            if cle == "capitaine_id":
                nouvelle["capitaine"] = {"pseudo": capitaine.get("pseudo"), "pseudo_jeu": capitaine.get("pseudo_jeu")}
        tournoi["equipes"][i] = nouvelle
        modifie = True
    return modifie


def format_match(joueurs_par_equipe: int) -> str:
    return f"{joueurs_par_equipe}v{joueurs_par_equipe}"


# --------------------------------------------------------------------------- #
# Lecture
# --------------------------------------------------------------------------- #

def equipes_inscrites(tournoi: dict) -> list[dict]:
    return sorted((e for e in tournoi["equipes"] if e["statut"] == INSCRITE), key=lambda e: e["id"])


def liste_attente(tournoi: dict) -> list[dict]:
    """Équipes en liste d'attente, dans l'ordre (la première sera promue en premier)."""
    return sorted((e for e in tournoi["equipes"] if e["statut"] == LISTE_ATTENTE), key=lambda e: e["id"])


def equipes_actives(tournoi: dict) -> list[dict]:
    return [e for e in tournoi["equipes"] if e["statut"] != ANNULEE]


def reservations_actives(tournoi: dict) -> list[dict]:
    """Places réservées pas encore utilisées (ni expirées, ni annulées)."""
    return sorted((r for r in tournoi.get("reservations", []) if r["statut"] == RESERVATION_ACTIVE),
                  key=lambda r: r["id"])


def places_libres(tournoi: dict) -> int:
    """Places ouvertes à tous : equipes_max moins les équipes inscrites et les places réservées."""
    return tournoi["equipes_max"] - len(equipes_inscrites(tournoi)) - len(reservations_actives(tournoi))


def est_complet(tournoi: dict) -> bool:
    """Vrai quand toutes les places ET toute la liste d'attente sont prises."""
    return (
        places_libres(tournoi) <= 0
        and len(liste_attente(tournoi)) >= tournoi["liste_attente_max"]
    )


def inscriptions_ouvertes(tournoi: dict, maintenant: str) -> bool:
    ouverture = tournoi.get("ouverture_inscriptions")  # absent : tournoi créé avant l'option « delay »
    return not ouverture or lire_date(maintenant) >= lire_date(ouverture)


def reservation_du_capitaine(tournoi: dict, joueur_id: str) -> dict | None:
    """Réservation active au nom de ce joueur (il est le seul à pouvoir l'utiliser)."""
    for reservation in reservations_actives(tournoi):
        if reservation["capitaine_id"] == joueur_id:
            return reservation
    return None


def trouver_reservation(tournoi: dict, reservation_id: int) -> dict:
    for reservation in tournoi.get("reservations", []):
        if reservation["id"] == reservation_id:
            return reservation
    raise ErreurTournoi(f"Aucune réservation R{reservation_id} dans ce tournoi.")


def trouver_equipe(tournoi: dict, equipe_id: int) -> dict:
    for equipe in tournoi["equipes"]:
        if equipe["id"] == equipe_id:
            return equipe
    raise ErreurTournoi(f"Aucune équipe #{equipe_id} dans ce tournoi.")


def equipe_du_joueur(tournoi: dict, joueur_id: str) -> dict | None:
    """Équipe active (non annulée) dans laquelle se trouve ce joueur."""
    for equipe in equipes_actives(tournoi):
        if any(j["id"] == joueur_id for j in equipe["joueurs"]):
            return equipe
    return None


def joueur_dans_equipe(equipe: dict, joueur_id: str) -> dict | None:
    for joueur in equipe["joueurs"]:
        if joueur["id"] == joueur_id:
            return joueur
    return None


def joueurs_en_attente(equipe: dict) -> list[dict]:
    return [j for j in equipe["joueurs"] if j["statut"] == EN_ATTENTE]


def equipe_confirmee(equipe: dict) -> bool:
    return all(j["statut"] == CONFIRME for j in equipe["joueurs"])


def position_attente(tournoi: dict, equipe: dict) -> int | None:
    for position, e in enumerate(liste_attente(tournoi), start=1):
        if e["id"] == equipe["id"]:
            return position
    return None


def lire_date(texte: str) -> datetime:
    """Lit une date ISO. Une date sans fuseau horaire est considérée comme l'heure locale."""
    # « Z » (UTC, renvoyé par l'API) n'est compris par fromisoformat qu'à partir de Python 3.11.
    date = datetime.fromisoformat(texte[:-1] + "+00:00" if texte.endswith("Z") else texte)
    return date if date.tzinfo else date.astimezone()


def delai_minutes(equipe: dict) -> int:
    """Délai de confirmation donné à CETTE équipe (celui en vigueur à son inscription)."""
    duree = lire_date(equipe["confirmer_avant"]) - lire_date(equipe["cree_le"])
    return round(duree.total_seconds() / 60)


def delai_depasse(equipe: dict, maintenant: str) -> bool:
    """Vrai si des coéquipiers n'ont pas confirmé et que le délai de confirmation est passé.

    Les équipes inscrites avant l'ajout du délai (sans « confirmer_avant ») n'expirent jamais.
    """
    return (
        equipe["statut"] != ANNULEE
        and not equipe_confirmee(equipe)
        and bool(equipe.get("confirmer_avant"))
        and lire_date(maintenant) >= lire_date(equipe["confirmer_avant"])
    )


# --------------------------------------------------------------------------- #
# Inscription
# --------------------------------------------------------------------------- #

def _verifier_ouverture(tournoi: dict, maintenant: str) -> None:
    if not inscriptions_ouvertes(tournoi, maintenant):
        horodatage = int(lire_date(tournoi["ouverture_inscriptions"]).timestamp())
        raise ErreurTournoi(f"Les inscriptions ouvrent <t:{horodatage}:R> (<t:{horodatage}:t>).")


def verifier_peut_s_inscrire(tournoi: dict, joueur_id: str, maintenant: str) -> None:
    """Vérifie, avant d'ouvrir la fiche, que ce joueur peut créer une équipe.

    Le capitaine d'une place réservée peut s'inscrire avant l'ouverture et même si le tournoi est complet.
    """
    equipe = equipe_du_joueur(tournoi, joueur_id)
    if equipe is not None:
        raise ErreurTournoi(f"Tu es déjà dans l'équipe **{equipe['nom']}** pour ce tournoi.")
    if reservation_du_capitaine(tournoi, joueur_id) is not None:
        return
    _verifier_ouverture(tournoi, maintenant)
    if est_complet(tournoi):
        raise ErreurTournoi("Ce tournoi est complet, liste d'attente comprise.")


def nettoyer_pseudo_jeu(pseudo_jeu: str) -> str:
    """Pseudo Rocket League : on enlève seulement les espaces autour (pas de changement de casse)."""
    pseudo_jeu = (pseudo_jeu or "").strip()
    if not pseudo_jeu:
        raise ErreurTournoi("Le pseudo Rocket League ne peut pas être vide.")
    if len(pseudo_jeu) > LONGUEUR_MAX_PSEUDO_JEU:
        raise ErreurTournoi(f"Le pseudo Rocket League fait au maximum {LONGUEUR_MAX_PSEUDO_JEU} caractères.")
    return pseudo_jeu


def verifier_fiche(
    tournoi: dict,
    *,
    nom: str,
    capitaine: tuple[str, str],
    pseudo_jeu_capitaine: str,
    coequipiers: list[tuple[str, str]],
) -> tuple[str, str]:
    """Vérifie la fiche d'inscription elle-même (sans regarder les autres équipes).

    Sert aussi avant d'appeler l'API, pour garder des messages d'erreur précis.
    Retourne (nom nettoyé, pseudo Rocket League nettoyé).
    """
    pseudo_jeu_capitaine = nettoyer_pseudo_jeu(pseudo_jeu_capitaine)
    nom = nom.strip()
    if not nom:
        raise ErreurTournoi("Le nom de l'équipe ne peut pas être vide.")
    if len(nom) > LONGUEUR_MAX_NOM_EQUIPE:
        raise ErreurTournoi(f"Le nom de l'équipe fait au maximum {LONGUEUR_MAX_NOM_EQUIPE} caractères.")

    attendus = tournoi["joueurs_par_equipe"] - 1
    if len(coequipiers) != attendus:
        raise ErreurTournoi(f"Il faut choisir exactement {attendus} coéquipier(s).")

    capitaine_id, _ = capitaine
    ids = [capitaine_id] + [c[0] for c in coequipiers]
    if capitaine_id in ids[1:]:
        raise ErreurTournoi("Tu ne peux pas te choisir toi-même comme coéquipier.")
    if len(set(ids)) != len(ids):
        raise ErreurTournoi("Le même joueur a été choisi deux fois.")
    return nom, pseudo_jeu_capitaine


def inscrire_equipe(
    tournoi: dict,
    *,
    nom: str,
    capitaine: tuple[str, str],
    pseudo_jeu_capitaine: str,
    coequipiers: list[tuple[str, str]],
    maintenant: str,
) -> dict:
    """Crée l'équipe. `capitaine` et `coequipiers` sont des tuples (id, pseudo Discord).

    L'équipe obtient sa place (ou sa position en liste d'attente) dès
    maintenant ; les coéquipiers doivent ensuite valider en donnant
    leur pseudo Rocket League, dans les DELAI_CONFIRMATION_MINUTES minutes.
    Si le capitaine a une place réservée, l'équipe prend cette place
    (même avant l'ouverture des inscriptions) et la réservation est « utilisée ».
    """
    nom, pseudo_jeu_capitaine = verifier_fiche(
        tournoi, nom=nom, capitaine=capitaine, pseudo_jeu_capitaine=pseudo_jeu_capitaine, coequipiers=coequipiers)
    if any(e["nom"].casefold() == nom.casefold() for e in equipes_actives(tournoi)):
        raise ErreurTournoi(f"Le nom **{nom}** est déjà pris dans ce tournoi.")
    capitaine_id, _ = capitaine

    for joueur_id, pseudo in [capitaine] + coequipiers:
        equipe = equipe_du_joueur(tournoi, joueur_id)
        if equipe is not None:
            raise ErreurTournoi(f"**{pseudo}** est déjà dans l'équipe **{equipe['nom']}** pour ce tournoi.")

    reservation = reservation_du_capitaine(tournoi, capitaine_id)
    if reservation is not None:
        statut = INSCRITE
    else:
        _verifier_ouverture(tournoi, maintenant)
        if places_libres(tournoi) > 0:
            statut = INSCRITE
        elif len(liste_attente(tournoi)) < tournoi["liste_attente_max"]:
            statut = LISTE_ATTENTE
        else:
            raise ErreurTournoi("Ce tournoi est complet, liste d'attente comprise.")

    equipe = {
        "id": len(tournoi["equipes"]) + 1,  # les équipes ne sont jamais supprimées
        "nom": nom,
        "capitaine_id": capitaine_id,
        "capitaine": {"pseudo": capitaine[1], "pseudo_jeu": pseudo_jeu_capitaine},
        "statut": statut,
        "cree_le": maintenant,
        # Pas de délai en 1v1 : le capitaine est le seul joueur, il est déjà confirmé.
        "confirmer_avant": (
            (lire_date(maintenant) + timedelta(minutes=DELAI_CONFIRMATION_MINUTES)).isoformat(timespec="seconds")
            if coequipiers else None
        ),
        "annulee_le": None,
        "raison_annulation": None,
        "joueurs": [{"id": capitaine_id, "pseudo": capitaine[1], "pseudo_jeu": pseudo_jeu_capitaine,
                     "statut": CONFIRME}]
        + [{"id": i, "pseudo": p, "pseudo_jeu": None, "statut": EN_ATTENTE} for i, p in coequipiers],
    }
    if reservation is not None:
        equipe["reservation_id"] = reservation["id"]
        reservation["statut"] = RESERVATION_UTILISEE
        reservation["equipe_id"] = equipe["id"]
        reservation["terminee_le"] = maintenant
    tournoi["equipes"].append(equipe)
    return equipe


# --------------------------------------------------------------------------- #
# Validation par les coéquipiers
# --------------------------------------------------------------------------- #

def _equipe_modifiable(tournoi: dict, equipe_id: int, joueur_id: str) -> tuple[dict, dict]:
    equipe = trouver_equipe(tournoi, equipe_id)
    joueur = joueur_dans_equipe(equipe, joueur_id)
    if joueur is None:
        raise ErreurTournoi("Cette inscription ne te concerne pas.")
    if equipe["statut"] == ANNULEE:
        raise ErreurTournoi(f"L'inscription de l'équipe **{equipe['nom']}** a été annulée.")
    return equipe, joueur


def verifier_peut_confirmer(tournoi: dict, equipe_id: int, joueur_id: str, maintenant: str) -> dict:
    """Vérifie, avant d'ouvrir la fiche, que ce joueur doit encore confirmer."""
    equipe, joueur = _equipe_modifiable(tournoi, equipe_id, joueur_id)
    if joueur["statut"] == CONFIRME:
        raise ErreurTournoi("Tu as déjà confirmé ta participation.")
    if delai_depasse(equipe, maintenant):
        raise ErreurTournoi(
            f"Trop tard : le délai de {delai_minutes(equipe)} minutes pour confirmer est dépassé, "
            f"l'équipe **{equipe['nom']}** est désinscrite du tournoi.")
    return equipe


def confirmer_joueur(tournoi: dict, equipe_id: int, joueur_id: str, pseudo_jeu: str, maintenant: str) -> dict:
    pseudo_jeu = nettoyer_pseudo_jeu(pseudo_jeu)
    equipe = verifier_peut_confirmer(tournoi, equipe_id, joueur_id, maintenant)
    joueur = joueur_dans_equipe(equipe, joueur_id)
    joueur["pseudo_jeu"] = pseudo_jeu
    joueur["statut"] = CONFIRME
    return equipe


def refuser_joueur(tournoi: dict, equipe_id: int, joueur_id: str, maintenant: str) -> tuple[dict, list[dict]]:
    """Le joueur refuse : l'équipe est annulée. Retourne (équipe, équipes promues)."""
    equipe, joueur = _equipe_modifiable(tournoi, equipe_id, joueur_id)
    if joueur["statut"] == CONFIRME:
        raise ErreurTournoi("Tu as déjà validé cette inscription.")
    joueur["statut"] = REFUSE
    return annuler_equipe(tournoi, equipe_id, f"{joueur['pseudo']} a refusé", maintenant)


# --------------------------------------------------------------------------- #
# Annulation et liste d'attente
# --------------------------------------------------------------------------- #

def annuler_equipe(tournoi: dict, equipe_id: int, raison: str, maintenant: str) -> tuple[dict, list[dict]]:
    """Annule une équipe et fait avancer la liste d'attente.

    Retourne (équipe annulée, équipes promues de la liste d'attente).
    """
    equipe = trouver_equipe(tournoi, equipe_id)
    if equipe["statut"] == ANNULEE:
        raise ErreurTournoi(f"L'équipe **{equipe['nom']}** est déjà annulée.")
    equipe["statut"] = ANNULEE
    equipe["annulee_le"] = maintenant
    equipe["raison_annulation"] = raison
    return equipe, promouvoir_liste_attente(tournoi)


def expirer_equipes(tournoi: dict, maintenant: str) -> tuple[list[dict], list[dict]]:
    """Désinscrit les équipes dont le délai de confirmation est dépassé.

    Toutes les équipes expirées sont annulées AVANT de faire avancer la liste
    d'attente : une équipe expirée ne peut donc pas être promue.
    Retourne (équipes désinscrites, équipes promues de la liste d'attente).
    """
    expirees = [e for e in tournoi["equipes"] if delai_depasse(e, maintenant)]
    for equipe in expirees:
        equipe["statut"] = ANNULEE
        equipe["annulee_le"] = maintenant
        restants = ", ".join(j["pseudo"] for j in joueurs_en_attente(equipe))
        equipe["raison_annulation"] = f"délai de confirmation dépassé ({restants})"
    promues = promouvoir_liste_attente(tournoi) if expirees else []
    return expirees, promues


def promouvoir_liste_attente(tournoi: dict) -> list[dict]:
    """Fait monter les premières équipes de la liste d'attente sur les places libres."""
    promues = []
    attente = liste_attente(tournoi)
    while places_libres(tournoi) > 0 and attente:
        equipe = attente.pop(0)
        equipe["statut"] = INSCRITE
        promues.append(equipe)
    return promues


# --------------------------------------------------------------------------- #
# Places réservées et ouverture des inscriptions
# --------------------------------------------------------------------------- #

def reserver_place(
    tournoi: dict,
    *,
    nom: str,
    capitaine: tuple[str, str],
    duree_minutes: int,
    cree_par: str,
    maintenant: str,
) -> dict:
    """Bloque une place pour l'équipe de `capitaine` (tuple (id, pseudo Discord)).

    Seul ce capitaine peut l'utiliser, en s'inscrivant avec le bouton habituel,
    avant `duree_minutes`. Passé ce délai, la place est rendue (expirer_reservations).
    Une réservation prend une place libre : elle ne retire jamais une équipe inscrite.
    """
    nom = nom.strip()
    if not nom:
        raise ErreurTournoi("Le nom de la réservation ne peut pas être vide.")
    if len(nom) > LONGUEUR_MAX_NOM_EQUIPE:
        raise ErreurTournoi(f"Le nom de la réservation fait au maximum {LONGUEUR_MAX_NOM_EQUIPE} caractères.")
    if not 1 <= duree_minutes <= DUREE_RESERVATION_MAX_MINUTES:
        raise ErreurTournoi(f"La durée de la réservation doit être entre 1 et {DUREE_RESERVATION_MAX_MINUTES} minutes.")
    capitaine_id, pseudo = capitaine
    equipe = equipe_du_joueur(tournoi, capitaine_id)
    if equipe is not None:
        raise ErreurTournoi(f"**{pseudo}** est déjà dans l'équipe **{equipe['nom']}** pour ce tournoi.")
    if reservation_du_capitaine(tournoi, capitaine_id) is not None:
        raise ErreurTournoi(f"**{pseudo}** a déjà une place réservée dans ce tournoi.")
    if places_libres(tournoi) <= 0:
        raise ErreurTournoi(
            "Plus aucune place libre à réserver. Augmente `equipes_max` avec `/tournoi_rl_modify` "
            "ou retire une équipe avec `/tournoi_rl_remove_team`.")

    tournoi.setdefault("reservations", [])
    reservation = {
        "id": len(tournoi["reservations"]) + 1,  # les réservations ne sont jamais supprimées
        "nom": nom,
        "capitaine_id": capitaine_id,
        "capitaine": pseudo,
        "statut": RESERVATION_ACTIVE,
        "cree_par": cree_par,
        "cree_le": maintenant,
        "expire_le": (lire_date(maintenant) + timedelta(minutes=duree_minutes)).isoformat(timespec="seconds"),
        "equipe_id": None,
        "terminee_le": None,
    }
    tournoi["reservations"].append(reservation)
    return reservation


def annuler_reservation(tournoi: dict, reservation_id: int, maintenant: str) -> tuple[dict, list[dict]]:
    """Rend une place réservée. Retourne (réservation, équipes promues de la liste d'attente)."""
    reservation = trouver_reservation(tournoi, reservation_id)
    if reservation["statut"] != RESERVATION_ACTIVE:
        raise ErreurTournoi(f"La réservation R{reservation_id} n'est plus active ({reservation['statut']}).")
    reservation["statut"] = RESERVATION_ANNULEE
    reservation["terminee_le"] = maintenant
    return reservation, promouvoir_liste_attente(tournoi)


def expirer_reservations(tournoi: dict, maintenant: str) -> tuple[list[dict], list[dict]]:
    """Rend les places réservées dont l'échéance est passée.

    Retourne (réservations expirées, équipes promues de la liste d'attente).
    """
    expirees = [r for r in reservations_actives(tournoi) if lire_date(maintenant) >= lire_date(r["expire_le"])]
    for reservation in expirees:
        reservation["statut"] = RESERVATION_EXPIREE
        reservation["terminee_le"] = maintenant
    promues = promouvoir_liste_attente(tournoi) if expirees else []
    return expirees, promues


def ouvrir_inscriptions(tournoi: dict, maintenant: str) -> bool:
    """Marque les inscriptions comme ouvertes une fois l'heure passée.

    Retourne True la première fois (l'annonce doit alors être mise à jour).
    """
    if tournoi.get("ouverture_inscriptions") and inscriptions_ouvertes(tournoi, maintenant):
        tournoi["ouverture_inscriptions"] = None
        return True
    return False


# --------------------------------------------------------------------------- #
# Modification par un admin
# --------------------------------------------------------------------------- #


def modifier_joueur(
    tournoi: dict,
    joueur_id: str,
    *,
    pseudo: str | None = None,
    pseudo_jeu: str | None = None,
) -> tuple[dict, dict, list[tuple[str, object, object]]]:
    """Change le pseudo Discord et/ou le pseudo Rocket League d'un joueur inscrit (None = inchangé).

    Le joueur doit être dans une équipe active (inscrite ou en liste d'attente).
    Tout est vérifié avant de toucher au tournoi : en cas d'erreur, il reste intact.
    Retourne (équipe, joueur, changements [(champ, ancienne valeur, nouvelle valeur)]).
    """
    if pseudo is None and pseudo_jeu is None:
        raise ErreurTournoi("Indique au moins un champ à modifier : pseudo ou pseudo_jeu.")
    equipe = equipe_du_joueur(tournoi, joueur_id)
    if equipe is None:
        raise ErreurTournoi("Ce joueur n'est dans aucune équipe inscrite ou en liste d'attente de ce tournoi.")
    joueur = joueur_dans_equipe(equipe, joueur_id)

    nouvelles: dict[str, str] = {}
    if pseudo is not None:
        nouvelles["pseudo"] = _texte_obligatoire(pseudo, "pseudo", LONGUEUR_MAX_PSEUDO)
    if pseudo_jeu is not None:
        if joueur["statut"] != CONFIRME:
            raise ErreurTournoi(
                f"**{joueur['pseudo']}** n'a pas encore confirmé sa participation : "
                "il donnera son pseudo Rocket League en confirmant.")
        nouvelles["pseudo_jeu"] = nettoyer_pseudo_jeu(pseudo_jeu)

    changements = [(champ, joueur.get(champ), valeur) for champ, valeur in nouvelles.items()
                   if joueur.get(champ) != valeur]
    for champ, _ancienne, valeur in changements:
        joueur[champ] = valeur
        if joueur_id == equipe["capitaine_id"] and isinstance(equipe.get("capitaine"), dict):
            equipe["capitaine"][champ] = valeur
    return equipe, joueur, changements


def remplacer_joueur(
    tournoi: dict,
    ancien_id: str,
    nouveau: tuple[str, str],
    pseudo_jeu: str,
) -> tuple[dict, dict, dict]:
    """Remplace un joueur d'une équipe active par un autre membre (tuple (id, pseudo Discord)).

    Le nouveau joueur prend la même place dans l'équipe, avec son pseudo Rocket League
    donné par l'admin : il est directement confirmé. Si l'ancien joueur était capitaine,
    le nouveau devient capitaine. Tout est vérifié avant de toucher au tournoi.
    Retourne (équipe, ancien joueur, nouveau joueur).
    """
    nouveau_id, nouveau_pseudo = nouveau
    pseudo_jeu = nettoyer_pseudo_jeu(pseudo_jeu)
    equipe = equipe_du_joueur(tournoi, ancien_id)
    if equipe is None:
        raise ErreurTournoi("Ce joueur n'est dans aucune équipe inscrite ou en liste d'attente de ce tournoi.")
    if nouveau_id == ancien_id:
        raise ErreurTournoi("Le nouveau joueur est le même que l'ancien.")
    deja = equipe_du_joueur(tournoi, nouveau_id)
    if deja is not None:
        raise ErreurTournoi(f"**{nouveau_pseudo}** est déjà dans l'équipe **{deja['nom']}** pour ce tournoi.")
    if reservation_du_capitaine(tournoi, nouveau_id) is not None:
        raise ErreurTournoi(
            f"**{nouveau_pseudo}** a une place réservée dans ce tournoi. "
            "Annule-la d'abord avec `/tournoi_rl_unreserve`.")

    index = next(i for i, j in enumerate(equipe["joueurs"]) if j["id"] == ancien_id)
    ancien = equipe["joueurs"][index]
    remplacant = {"id": nouveau_id, "pseudo": nouveau_pseudo, "pseudo_jeu": pseudo_jeu, "statut": CONFIRME}
    equipe["joueurs"][index] = remplacant
    if equipe["capitaine_id"] == ancien_id:
        equipe["capitaine_id"] = nouveau_id
        equipe["capitaine"] = {"pseudo": nouveau_pseudo, "pseudo_jeu": pseudo_jeu}
    return equipe, ancien, remplacant


CHAMPS_MODIFIABLES = {"titre": "Titre", "cashprize": "Cashprize", "equipes_max": "Équipes max"}


def _texte_obligatoire(valeur: str, champ: str, longueur_max: int) -> str:
    valeur = valeur.strip()
    if not valeur:
        raise ErreurTournoi(f"Le {champ} ne peut pas être vide.")
    if len(valeur) > longueur_max:
        raise ErreurTournoi(f"Le {champ} fait au maximum {longueur_max} caractères.")
    return valeur


def modifier_tournoi(
    tournoi: dict,
    *,
    titre: str | None = None,
    cashprize: str | None = None,
    equipes_max: int | None = None,
) -> tuple[list[tuple[str, object, object]], list[dict]]:
    """Modifie le titre, le cashprize et/ou le nombre maximum d'équipes (None = inchangé).

    Tout est vérifié avant de toucher au tournoi : en cas d'erreur, il reste intact.
    Aucune équipe n'est jamais retirée ni renvoyée en liste d'attente : si le
    nouveau maximum est trop petit, la modification est refusée.

    Retourne (changements [(champ, ancienne valeur, nouvelle valeur)],
    équipes promues de la liste d'attente). Pas de changement → ([], []).
    """
    if titre is None and cashprize is None and equipes_max is None:
        raise ErreurTournoi("Indique au moins un champ à modifier : titre, cashprize ou equipes_max.")

    nouvelles: dict[str, object] = {}
    if titre is not None:
        nouvelles["titre"] = _texte_obligatoire(titre, "titre", LONGUEUR_MAX_TITRE)
    if cashprize is not None:
        nouvelles["cashprize"] = _texte_obligatoire(cashprize, "cashprize", LONGUEUR_MAX_CASHPRIZE)
    if equipes_max is not None:
        if not 1 <= equipes_max <= EQUIPES_MAX_LIMITE:
            raise ErreurTournoi(f"Le nombre maximum d'équipes doit être entre 1 et {EQUIPES_MAX_LIMITE}.")
        nb_inscrites = len(equipes_inscrites(tournoi))
        nb_reservees = len(reservations_actives(tournoi))
        if equipes_max < nb_inscrites + nb_reservees:
            detail = f" et {nb_reservees} place(s) réservée(s)" if nb_reservees else ""
            raise ErreurTournoi(
                f"{nb_inscrites} équipes sont déjà inscrites{detail} : equipes_max ne peut pas descendre "
                f"en dessous de {nb_inscrites + nb_reservees}. Retire d'abord "
                f"{nb_inscrites + nb_reservees - equipes_max} équipe(s) avec `/tournoi_rl_remove_team`"
                + (" ou des réservations avec `/tournoi_rl_unreserve`." if nb_reservees else "."))
        # Taille de la liste d'attente une fois les places libres remplies.
        attente_apres = max(0, len(liste_attente(tournoi)) - (equipes_max - nb_inscrites - nb_reservees))
        attente_max = equipes_max * MULTIPLICATEUR_LISTE_ATTENTE
        if attente_apres > attente_max:
            raise ErreurTournoi(
                f"La liste d'attente compte {attente_apres} équipes alors que le maximum serait "
                f"{attente_max} avec {equipes_max} équipes. Retire d'abord "
                f"{attente_apres - attente_max} équipe(s) de la liste d'attente avec `/tournoi_rl_remove_team`.")
        nouvelles["equipes_max"] = equipes_max

    changements = [(champ, tournoi[champ], valeur) for champ, valeur in nouvelles.items()
                   if tournoi[champ] != valeur]
    for champ, _ancienne, valeur in changements:
        tournoi[champ] = valeur

    promues: list[dict] = []
    if any(champ == "equipes_max" for champ, _, _ in changements):
        tournoi["liste_attente_max"] = tournoi["equipes_max"] * MULTIPLICATEUR_LISTE_ATTENTE
        promues = promouvoir_liste_attente(tournoi)
    return changements, promues
