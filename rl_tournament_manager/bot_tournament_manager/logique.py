"""Règles du tournoi : tirage, rotation des zones, points, classement.

Ce module ne dépend pas de Discord : il travaille sur le dictionnaire
« état » d'un tournoi (le contenu de data/tournois/<id>.json), ce qui
permet de le tester.

Zones : il y a une zone par match (nb_equipes / 2). La zone 1 est la plus
basse, la dernière (nb_zones) est la zone haute ⭐.
  - le gagnant d'une zone monte d'une zone (le gagnant de la zone haute y reste) ;
  - le perdant descend d'une zone (le perdant de la zone 1 y reste).
Points : victoire +1, défaite 0. À partir du « golden round » (choisi au lancement, 1 par défaut),
la victoire en zone haute rapporte +3.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterator

# Statuts du tournoi
EN_COURS = "en_cours"
TERMINE = "termine"
ARRETE = "arrete"

# Statuts d'une ronde
RONDE_EN_COURS = "en_cours"
RONDE_TERMINEE = "terminee"

# Statuts d'un match
MATCH_EN_ATTENTE = "en_attente"   # pas encore commencé
MATCH_EN_COURS = "en_cours"       # MP envoyés, l'observateur suit le match
MATCH_TERMINE = "termine"         # vainqueur connu, points donnés
MATCH_A_VALIDER = "a_valider"     # le bot n'a pas le score : déclaration des équipes ou admin
MATCH_ANNULE = "annule"           # tournoi arrêté avant la fin du match
MATCHS_A_JOUER = (MATCH_EN_ATTENTE, MATCH_EN_COURS)

POINTS_VICTOIRE_ZONE_HAUTE = 3
POINTS_VICTOIRE = 1
POINTS_DEFAITE = 0

# Statuts du fichier d'inscription (rl_bot_ppname_creator)
INSCRITE = "inscrite"
CONFIRME = "confirme"

# Ce que renvoie l'observateur (format de rl_api_pp_connector)
BLEU, ORANGE = 0, 1
OBSERVATEUR_TERMINE = "terminé"

# Qui a donné le score d'un match terminé
SOURCE_BOT = "bot"                    # l'observateur (simulateur ou vrai connecteur)
SOURCE_DECLARATIONS = "declarations"  # les deux équipes ont déclaré le même score
SOURCE_ADMIN = "admin"                # /set_result_tournament_rl

# Résultat d'une déclaration de score
DECLARATION_EN_ATTENTE = "en_attente"    # l'autre équipe n'a pas encore déclaré
DECLARATION_VALIDEE = "validee"          # les deux équipes sont d'accord : match terminé
DECLARATION_DESACCORD = "desaccord"      # les deux équipes ne déclarent pas le même score
DECLARATION_INCOHERENTE = "incoherente"  # score plus bas que celui vu par le bot


class ErreurTournoi(Exception):
    """Erreur dont le message peut être montré tel quel à l'admin."""


# --------------------------------------------------------------------------- #
# Lancement
# --------------------------------------------------------------------------- #

def equipes_participantes(tournoi: dict) -> list[dict]:
    """Équipes inscrites du fichier d'inscription, après vérification."""
    equipes = sorted((e for e in tournoi.get("equipes", []) if e.get("statut") == INSCRITE),
                     key=lambda e: e["id"])
    if len(equipes) < 2:
        raise ErreurTournoi(
            f"Il faut au moins 2 équipes inscrites pour lancer le tournoi (il y en a {len(equipes)}).")
    if len(equipes) % 2:
        raise ErreurTournoi(f"Le nombre d'équipes inscrites doit être pair (il y en a {len(equipes)}).")
    incompletes = [e["nom"] for e in equipes
                   if not e.get("joueurs") or any(j.get("statut") != CONFIRME for j in e["joueurs"])]
    if incompletes:
        raise ErreurTournoi("Ces équipes ont des joueurs qui n'ont pas encore confirmé : "
                            + ", ".join(f"**{nom}**" for nom in incompletes) + ".")
    return equipes


def nouvel_etat(tournoi: dict, equipes: list[dict], *, nombre_de_rondes: int,
                lance_par: str, maintenant: str, golden_round: int = 1) -> dict:
    if nombre_de_rondes < 1:
        raise ErreurTournoi("Il faut au moins 1 match par équipe.")
    if not 1 <= golden_round <= nombre_de_rondes:
        raise ErreurTournoi(f"Le golden round doit être entre 1 et {nombre_de_rondes} "
                            f"(le nombre de matchs), pas {golden_round}.")
    return {
        "tournoi_id": tournoi["id"],
        "titre": tournoi["titre"],
        "serveur_id": tournoi["serveur_id"],
        "salon_id": tournoi["salon_id"],
        "salon_discussion_id": None,  # salon texte créé au lancement (joueurs + admins)
        "joueurs_par_equipe": tournoi.get("joueurs_par_equipe"),
        "statut": EN_COURS,
        "nombre_de_rondes": nombre_de_rondes,
        "golden_round": golden_round,  # à partir de ce round, la victoire en zone haute rapporte +3
        "nb_zones": len(equipes) // 2,
        "lance_par": lance_par,
        "lance_le": maintenant,
        "termine_le": None,
        "arrete_par": None,
        "arrete_le": None,
        "equipes": {str(e["id"]): _nouvelle_equipe(e) for e in equipes},
        "rondes": [],
        "modifications": [],  # /edit_player_tournament_rl : qui a changé quoi, et quand
    }


def _nouvelle_equipe(equipe: dict) -> dict:
    return {
        "id": equipe["id"],
        "nom": equipe["nom"],
        "capitaine_id": equipe["capitaine_id"],
        "joueurs": [{"id": j["id"], "pseudo": j["pseudo"], "pseudo_jeu": j.get("pseudo_jeu")}
                    for j in equipe["joueurs"]],
        "zone_actuelle": None,
        "points": 0,
        "matchs_joues": 0,
        "victoires": 0,
        "defaites": 0,
        "buts_pour": 0,
        "buts_contre": 0,
        "historique": [],
    }


# --------------------------------------------------------------------------- #
# Rondes et zones
# --------------------------------------------------------------------------- #

def premier_tirage(equipe_ids: list[int], rng: random.Random) -> list[tuple[int, int]]:
    """Tirage aléatoire du round 1. Élément i = match de la zone i + 1."""
    ids = list(equipe_ids)
    rng.shuffle(ids)
    return [(ids[i], ids[i + 1]) for i in range(0, len(ids), 2)]


def affectations_suivantes(ronde: dict, nb_zones: int) -> list[tuple[int, int]]:
    """Qui joue dans quelle zone au round suivant.

    Zone 1      : perdant zone 1  vs perdant zone 2
    Zone z      : gagnant zone z-1 vs perdant zone z+1
    Zone haute  : gagnant zone haute-1 vs gagnant zone haute
    La première équipe de chaque paire est l'« équipe A » (son capitaine crée la partie).
    """
    matchs = {m["zone"]: m for m in ronde["matchs"]}
    if sorted(matchs) != list(range(1, nb_zones + 1)) or any(
            m["statut"] != MATCH_TERMINE for m in matchs.values()):
        raise ErreurTournoi("Le round précédent n'est pas terminé.")
    gagnant = {z: m["vainqueur"] for z, m in matchs.items()}
    perdant = {z: adversaire(m, m["vainqueur"]) for z, m in matchs.items()}

    affectations = []
    for zone in range(1, nb_zones + 1):
        venant_du_bas = gagnant[zone - 1] if zone > 1 else perdant[1]
        venant_du_haut = perdant[zone + 1] if zone < nb_zones else gagnant[nb_zones]
        affectations.append((venant_du_bas, venant_du_haut))
    return affectations


def nouvelle_ronde(etat: dict, affectations: list[tuple[int, int]], parties: list[dict],
                   *, fichier_pp: str, maintenant: str) -> dict:
    """Ajoute une ronde à l'état. `parties` = liste de generer_pp_names.py (match 1 → zone 1…)."""
    if len(affectations) != etat["nb_zones"] or len(parties) != len(affectations):
        raise ErreurTournoi("Le nombre de parties privées ne correspond pas au nombre de zones.")
    matchs = []
    for zone, ((equipe_a, equipe_b), partie) in enumerate(zip(affectations, parties), start=1):
        matchs.append(_nouveau_match(zone, equipe_a, equipe_b, partie))
        etat["equipes"][str(equipe_a)]["zone_actuelle"] = zone
        etat["equipes"][str(equipe_b)]["zone_actuelle"] = zone
    ronde = {
        "numero": len(etat["rondes"]) + 1,
        "statut": RONDE_EN_COURS,
        "fichier_pp": fichier_pp,
        "debut": maintenant,
        "fin": None,
        "matchs": matchs,
    }
    etat["rondes"].append(ronde)
    return ronde


def _nouveau_match(zone: int, equipe_a: int, equipe_b: int, partie: dict) -> dict:
    return {
        "zone": zone,
        "pp": {"nom": partie["nom"], "mot_de_passe": partie["mot_de_passe"]},
        "equipe_a": equipe_a,          # son capitaine crée la partie ; consigne : Bleu
        "equipe_b": equipe_b,          # consigne : Orange
        "statut": MATCH_EN_ATTENTE,
        "debut": None,
        "fin": None,
        "score": None,                 # {"equipe_a": 3, "equipe_b": 1}
        "vainqueur": None,             # id de l'équipe gagnante
        "points_attribues": 0,
        "bleu": None,                  # id de l'équipe qui était vraiment en Bleu
        "couleurs_detectees_par": None,  # "pseudos" (pseudos en jeu) ou "consigne" (A = Bleu)
        "raison_a_valider": None,
        "valide_par": None,            # id Discord de l'admin si validé à la main
        "source_resultat": None,       # "bot", "declarations" ou "admin"
        "declarations": {},            # {"<id équipe>": {"pour", "contre", "par", "le"}}
        "pp_creee_le": None,           # quand le capitaine a cliqué sur « Partie privée créée »
        "pp_creee_par": None,
        "resultat_observateur": None,  # résultat brut renvoyé par l'observateur
    }


def terminer_ronde(ronde: dict, maintenant: str) -> None:
    ronde["statut"] = RONDE_TERMINEE
    ronde["fin"] = maintenant


# --------------------------------------------------------------------------- #
# Lecture
# --------------------------------------------------------------------------- #

def ronde_actuelle(etat: dict) -> dict | None:
    return etat["rondes"][-1] if etat["rondes"] else None


def trouver_ronde(etat: dict, numero: int) -> dict:
    for ronde in etat["rondes"]:
        if ronde["numero"] == numero:
            return ronde
    raise ErreurTournoi(f"Round {numero} introuvable.")


def trouver_match(ronde: dict, zone: int) -> dict:
    for match in ronde["matchs"]:
        if match["zone"] == zone:
            return match
    raise ErreurTournoi(f"Il n'y a pas de zone {zone} dans ce tournoi.")


def equipe(etat: dict, equipe_id: int) -> dict:
    return etat["equipes"][str(equipe_id)]


def adversaire(match: dict, equipe_id: int) -> int:
    return match["equipe_b"] if equipe_id == match["equipe_a"] else match["equipe_a"]


def est_zone_haute(etat: dict, zone: int) -> bool:
    return zone == etat["nb_zones"]


def golden_round(etat: dict) -> int:
    """Round à partir duquel la victoire en zone haute rapporte +3.
    1 pour les tournois lancés avant cette option : ils gardent le +3 dès le round 1."""
    return etat.get("golden_round") or 1


def bonus_zone_haute(etat: dict, numero_ronde: int) -> bool:
    """True si, à ce round, la victoire en zone haute rapporte +3."""
    return numero_ronde >= golden_round(etat)


def points_victoire(etat: dict, zone: int, numero_ronde: int) -> int:
    """+3 en zone haute à partir du golden round, +1 sinon."""
    if est_zone_haute(etat, zone) and bonus_zone_haute(etat, numero_ronde):
        return POINTS_VICTOIRE_ZONE_HAUTE
    return POINTS_VICTOIRE


def zone_suivante(zone: int, nb_zones: int, a_gagne: bool) -> int:
    return min(zone + 1, nb_zones) if a_gagne else max(zone - 1, 1)


def ronde_complete(ronde: dict) -> bool:
    return all(m["statut"] == MATCH_TERMINE for m in ronde["matchs"])


def classement(etat: dict) -> list[dict]:
    """Points, puis victoires, puis différence de buts, puis buts marqués."""
    def cle(e: dict):
        return (-e["points"], -e["victoires"], -(e["buts_pour"] - e["buts_contre"]),
                -e["buts_pour"], e["nom"].casefold())
    return sorted(etat["equipes"].values(), key=cle)


def rang(etat: dict, equipe_id: int) -> int:
    for position, e in enumerate(classement(etat), start=1):
        if e["id"] == equipe_id:
            return position
    raise ErreurTournoi(f"Équipe {equipe_id} introuvable.")


def joueurs(etat: dict) -> Iterator[tuple[dict, dict]]:
    """(équipe, joueur) pour chaque joueur du tournoi."""
    for e in etat["equipes"].values():
        for joueur in e["joueurs"]:
            yield e, joueur


def trouver_joueur(etat: dict, joueur_id: str) -> tuple[dict, dict]:
    """(équipe, joueur) du joueur `joueur_id` (ID Discord)."""
    for e, joueur in joueurs(etat):
        if joueur["id"] == str(joueur_id):
            return e, joueur
    raise ErreurTournoi("Ce joueur ne joue pas dans ce tournoi : choisis-le dans la liste proposée.")


def match_de_l_equipe(ronde: dict | None, equipe_id: int) -> dict | None:
    """Match de l'équipe dans cette ronde (None s'il n'y en a pas)."""
    for match in (ronde or {}).get("matchs", []):
        if equipe_id in (match["equipe_a"], match["equipe_b"]):
            return match
    return None


# --------------------------------------------------------------------------- #
# Modification d'un joueur pendant le tournoi (/edit_player_tournament_rl)
# --------------------------------------------------------------------------- #

LONGUEUR_MAX_PSEUDO = 32       # comme les noms Discord
LONGUEUR_MAX_PSEUDO_JEU = 32   # comme le bot d'inscription
LONGUEUR_MAX_NOM_EQUIPE = 32   # comme le bot d'inscription


def _texte(valeur: str | None, quoi: str, longueur_max: int) -> str | None:
    """Valeur nettoyée (None si vide), ou erreur si elle est trop longue."""
    valeur = (valeur or "").strip()
    if len(valeur) > longueur_max:
        raise ErreurTournoi(f"{quoi} : {longueur_max} caractères maximum.")
    return valeur or None


def modifier_joueur(etat: dict, joueur_id: str, *, pseudo: str | None = None, pseudo_jeu: str | None = None,
                    nom_equipe: str | None = None, devient_capitaine: bool | None = None,
                    remplacant: tuple[str, str] | None = None, par: str, maintenant: str) -> dict:
    """Modifie un joueur (ou le nom de son équipe) pendant le tournoi.

    `remplacant` = (ID Discord, pseudo Discord) d'un membre qui prend sa place dans l'équipe : il reprend
    son rôle de capitaine s'il l'avait ; `pseudo` et `pseudo_jeu` s'appliquent alors au remplaçant.
    Renvoie la modification (aussi ajoutée à etat["modifications"]) :
    {"le", "par", "equipe", "joueur", "changements": {champ: [avant, après]}, "ancien_joueur"}.
    Rien n'est modifié si une valeur est refusée.
    """
    equipe_j, joueur = trouver_joueur(etat, joueur_id)
    pseudo = _texte(pseudo, "Pseudo", LONGUEUR_MAX_PSEUDO)
    pseudo_jeu = _texte(pseudo_jeu, "Pseudo en jeu", LONGUEUR_MAX_PSEUDO_JEU)
    nom_equipe = _texte(nom_equipe, "Nom d'équipe", LONGUEUR_MAX_NOM_EQUIPE)
    if devient_capitaine is False:
        raise ErreurTournoi("Pour changer de capitaine, choisis le **nouveau** capitaine dans `joueur` "
                            "et mets `devient_capitaine: True`.")

    # Vérifications, avant de toucher à quoi que ce soit.
    if remplacant is not None:
        nouvel_id = str(remplacant[0])
        if any(j["id"] == nouvel_id for _, j in joueurs(etat)):
            raise ErreurTournoi("Ce membre joue déjà dans ce tournoi.")
    if pseudo_jeu is not None:
        doublon = next((j for _, j in joueurs(etat)
                        if j is not joueur and _normaliser(j.get("pseudo_jeu")) == _normaliser(pseudo_jeu)), None)
        if doublon is not None:
            raise ErreurTournoi(f"Le pseudo en jeu `{pseudo_jeu}` est déjà celui de **{doublon['pseudo']}** : "
                                "le bot ne pourrait plus reconnaître les couleurs.")
    if nom_equipe is not None and any(e is not equipe_j and e["nom"].casefold() == nom_equipe.casefold()
                                      for e in etat["equipes"].values()):
        raise ErreurTournoi(f"Une autre équipe s'appelle déjà **{nom_equipe}**.")

    changements: dict[str, list] = {}
    ancien_joueur = dict(joueur)

    def changer(cible: dict, cle: str, nom: str, valeur) -> None:
        if cible.get(cle) != valeur:
            changements[nom] = [cible.get(cle), valeur]
            cible[cle] = valeur

    if remplacant is not None:
        changer(joueur, "id", "joueur", str(remplacant[0]))
        changer(joueur, "pseudo", "pseudo", pseudo or remplacant[1])
        changer(joueur, "pseudo_jeu", "pseudo_jeu", pseudo_jeu)  # celui de l'ancien joueur ne vaut plus
        if equipe_j["capitaine_id"] == ancien_joueur["id"]:
            changer(equipe_j, "capitaine_id", "capitaine", joueur["id"])
    else:
        if pseudo is not None:
            changer(joueur, "pseudo", "pseudo", pseudo)
        if pseudo_jeu is not None:
            changer(joueur, "pseudo_jeu", "pseudo_jeu", pseudo_jeu)
    if nom_equipe is not None:
        changer(equipe_j, "nom", "nom_equipe", nom_equipe)
    if devient_capitaine:
        changer(equipe_j, "capitaine_id", "capitaine", joueur["id"])

    if not changements:
        raise ErreurTournoi("Rien à changer : les valeurs données sont déjà celles du tournoi.")
    modification = {
        "le": maintenant,
        "par": par,
        "equipe": equipe_j["id"],
        "joueur": ancien_joueur["id"],
        "changements": changements,
        "ancien_joueur": ancien_joueur,
    }
    etat.setdefault("modifications", []).append(modification)
    return modification


# --------------------------------------------------------------------------- #
# Résultats
# --------------------------------------------------------------------------- #

def _normaliser(pseudo: str | None) -> str:
    return (pseudo or "").strip().casefold()


def detecter_couleur_equipe_a(joueurs_resultat: list[dict] | None, equipe_a: dict, equipe_b: dict) -> int | None:
    """Couleur (0 = Bleu, 1 = Orange) de l'équipe A d'après les pseudos en jeu.

    Chaque joueur reconnu « vote ». None si personne n'est reconnu ou s'il y a égalité.
    """
    pseudos_a = {_normaliser(j.get("pseudo_jeu")) for j in equipe_a["joueurs"]} - {""}
    pseudos_b = {_normaliser(j.get("pseudo_jeu")) for j in equipe_b["joueurs"]} - {""}
    votes: Counter[int] = Counter()
    for joueur in joueurs_resultat or []:
        couleur = joueur.get("TeamNum")
        if couleur not in (BLEU, ORANGE):
            continue
        nom = _normaliser(joueur.get("Name"))
        if nom in pseudos_a:
            votes[couleur] += 1
        elif nom in pseudos_b:
            votes[1 - couleur] += 1
    if votes[BLEU] == votes[ORANGE]:
        return None
    return BLEU if votes[BLEU] > votes[ORANGE] else ORANGE


def lire_resultat(etat: dict, match: dict, resultat: dict) -> dict:
    """Traduit le résultat de l'observateur (Bleu/Orange) en équipes du tournoi.

    Renvoie {"bleu", "couleurs_detectees_par", "score_a", "score_b", "vainqueur", "raison"}.
    "vainqueur" vaut None (et "raison" explique pourquoi) si un admin doit valider.
    """
    equipe_a, equipe_b = equipe(etat, match["equipe_a"]), equipe(etat, match["equipe_b"])
    couleur_a = detecter_couleur_equipe_a(resultat.get("players"), equipe_a, equipe_b)
    detectees_par = "pseudos"
    if couleur_a is None:
        couleur_a, detectees_par = BLEU, "consigne"

    scores = {t.get("team_num"): t.get("score") for t in resultat.get("teams") or []}
    score_a, score_b = scores.get(couleur_a), scores.get(1 - couleur_a)
    lecture = {
        "bleu": match["equipe_a"] if couleur_a == BLEU else match["equipe_b"],
        "couleurs_detectees_par": detectees_par,
        "score_a": score_a,
        "score_b": score_b,
        "vainqueur": None,
        "raison": None,
    }

    statut = resultat.get("statut") or OBSERVATEUR_TERMINE
    gagnant = resultat.get("winner_team_num")
    if statut != OBSERVATEUR_TERMINE:
        lecture["raison"] = statut  # ex. « le bot n'a pas pu rejoindre la partie après 3 essais »
    elif not isinstance(score_a, int) or not isinstance(score_b, int):
        lecture["raison"] = "score illisible"
    elif gagnant not in (BLEU, ORANGE):
        lecture["raison"] = "pas de vainqueur"
    else:
        vainqueur = match["equipe_a"] if gagnant == couleur_a else match["equipe_b"]
        if (score_a > score_b) != (vainqueur == match["equipe_a"]):
            lecture["raison"] = "le score ne correspond pas au vainqueur annoncé"
        else:
            lecture["vainqueur"] = vainqueur
    return lecture


def appliquer_resultat(etat: dict, numero_ronde: int, match: dict, resultat: dict, maintenant: str) -> bool:
    """Enregistre le résultat de l'observateur. True si le match est terminé, False s'il est à valider."""
    lecture = lire_resultat(etat, match, resultat)
    match["resultat_observateur"] = resultat
    match["bleu"] = lecture["bleu"]
    match["couleurs_detectees_par"] = lecture["couleurs_detectees_par"]
    if lecture["vainqueur"] is None:
        match["statut"] = MATCH_A_VALIDER
        match["raison_a_valider"] = lecture["raison"]
        if isinstance(lecture["score_a"], int) and isinstance(lecture["score_b"], int):
            match["score"] = {"equipe_a": lecture["score_a"], "equipe_b": lecture["score_b"]}
        return False
    _terminer_match(etat, numero_ronde, match, lecture["vainqueur"],
                    lecture["score_a"], lecture["score_b"], maintenant, source=SOURCE_BOT)
    return True


def valider_manuellement(etat: dict, numero_ronde: int, match: dict, gagnant_id: int,
                         score_gagnant: int, score_perdant: int, *, par: str, maintenant: str) -> None:
    """Un admin fixe le résultat (match à valider, ou bloqué en cours)."""
    if match["statut"] == MATCH_TERMINE:
        raise ErreurTournoi("Ce match est déjà terminé : son résultat ne peut plus être changé.")
    if match["statut"] == MATCH_ANNULE:
        raise ErreurTournoi("Ce match a été annulé.")
    if gagnant_id not in (match["equipe_a"], match["equipe_b"]):
        raise ErreurTournoi("Cette équipe ne joue pas dans cette zone.")
    if score_perdant < 0 or score_gagnant <= score_perdant:
        raise ErreurTournoi("Le score du gagnant doit être plus grand que celui du perdant "
                            "(pour un forfait, mets 1 - 0).")
    if gagnant_id == match["equipe_a"]:
        score_a, score_b = score_gagnant, score_perdant
    else:
        score_a, score_b = score_perdant, score_gagnant
    match["valide_par"] = par
    match["debut"] = match["debut"] or maintenant
    _terminer_match(etat, numero_ronde, match, gagnant_id, score_a, score_b, maintenant, source=SOURCE_ADMIN)


def marquer_pp_creee(match: dict, *, par: str, maintenant: str) -> bool:
    """Le capitaine a cliqué sur « Partie privée créée ». False si c'était déjà noté."""
    if match["statut"] == MATCH_TERMINE:
        raise ErreurTournoi("Ce match est déjà terminé.")
    if match["statut"] == MATCH_ANNULE:
        raise ErreurTournoi("Ce match a été annulé.")
    if match["statut"] == MATCH_A_VALIDER:
        raise ErreurTournoi("Le bot n'a pas pu prendre le score de ce match : déclarez-le avec le bouton "
                            "« Déclarer le score » reçu en MP.")
    if match.get("pp_creee_le"):
        return False
    match["pp_creee_le"] = maintenant
    match["pp_creee_par"] = par
    return True


def score_vu_par_le_bot(match: dict) -> dict | None:
    """Dernier score vu par le bot pour un match à valider ({"equipe_a", "equipe_b"}), si fiable.

    Seulement si les couleurs ont été reconnues grâce aux pseudos : avec la consigne
    (équipe A = Bleu), le score pourrait être inversé.
    """
    score = match.get("score")
    if match["statut"] != MATCH_A_VALIDER or not score or match.get("couleurs_detectees_par") != "pseudos":
        return None
    return score


def declarer_score(etat: dict, numero_ronde: int, match: dict, equipe_id: int, buts_equipe: int,
                   buts_adversaire: int, *, par: str, maintenant: str) -> str:
    """Un joueur déclare le score de son match (quand le bot n'a pas pu le prendre).

    Une nouvelle déclaration remplace la précédente de la même équipe.
    Renvoie DECLARATION_EN_ATTENTE, _VALIDEE, _DESACCORD ou _INCOHERENTE.
    """
    if match["statut"] == MATCH_TERMINE:
        raise ErreurTournoi("Le résultat de ce match est déjà enregistré.")
    if match["statut"] == MATCH_ANNULE:
        raise ErreurTournoi("Ce match a été annulé.")
    if match["statut"] != MATCH_A_VALIDER:
        raise ErreurTournoi("Le bot s'occupe encore de ce match : attends son message.")
    if equipe_id not in (match["equipe_a"], match["equipe_b"]):
        raise ErreurTournoi("Cette équipe ne joue pas dans ce match.")
    if buts_equipe < 0 or buts_adversaire < 0:
        raise ErreurTournoi("Un score ne peut pas être négatif.")
    if buts_equipe == buts_adversaire:
        raise ErreurTournoi("Il n'y a pas d'égalité en Rocket League : la prolongation départage les équipes.")

    declarations = match.setdefault("declarations", {})
    declarations[str(equipe_id)] = {"pour": buts_equipe, "contre": buts_adversaire, "par": par, "le": maintenant}

    vu = score_vu_par_le_bot(match)
    a, b = score_declare(match, equipe_id)
    if vu and (a < vu["equipe_a"] or b < vu["equipe_b"]):
        return DECLARATION_INCOHERENTE

    autre = declarations.get(str(adversaire(match, equipe_id)))
    if autre is None:
        return DECLARATION_EN_ATTENTE
    if (autre["pour"], autre["contre"]) != (buts_adversaire, buts_equipe):
        return DECLARATION_DESACCORD

    vainqueur = match["equipe_a"] if a > b else match["equipe_b"]
    match["debut"] = match["debut"] or maintenant
    _terminer_match(etat, numero_ronde, match, vainqueur, a, b, maintenant, source=SOURCE_DECLARATIONS)
    return DECLARATION_VALIDEE


def score_declare(match: dict, equipe_id: int) -> tuple[int, int]:
    """Score déclaré par une équipe, remis dans l'ordre (buts de A, buts de B)."""
    d = match["declarations"][str(equipe_id)]
    return (d["pour"], d["contre"]) if equipe_id == match["equipe_a"] else (d["contre"], d["pour"])


def _terminer_match(etat: dict, numero_ronde: int, match: dict, vainqueur: int,
                    score_a: int, score_b: int, maintenant: str, *, source: str) -> None:
    points = points_victoire(etat, match["zone"], numero_ronde)
    match.update({
        "statut": MATCH_TERMINE,
        "source_resultat": source,
        "score": {"equipe_a": score_a, "equipe_b": score_b},
        "vainqueur": vainqueur,
        "points_attribues": points,
        "fin": maintenant,
    })
    for equipe_id, pour, contre in ((match["equipe_a"], score_a, score_b),
                                    (match["equipe_b"], score_b, score_a)):
        e = equipe(etat, equipe_id)
        gagne = equipe_id == vainqueur
        gagnes = points if gagne else POINTS_DEFAITE
        e["matchs_joues"] += 1
        e["victoires" if gagne else "defaites"] += 1
        e["points"] += gagnes
        e["buts_pour"] += pour
        e["buts_contre"] += contre
        e["historique"].append({
            "ronde": numero_ronde,
            "zone": match["zone"],
            "adversaire": adversaire(match, equipe_id),
            "score": f"{pour}-{contre}",
            "resultat": "victoire" if gagne else "defaite",
            "points": gagnes,
        })


# --------------------------------------------------------------------------- #
# Fin du tournoi
# --------------------------------------------------------------------------- #

def terminer(etat: dict, maintenant: str) -> None:
    etat["statut"] = TERMINE
    etat["termine_le"] = maintenant


def arreter(etat: dict, *, par: str, maintenant: str) -> None:
    """Arrêt par un admin : les matchs pas encore terminés du round en cours sont annulés."""
    etat["statut"] = ARRETE
    etat["arrete_par"] = par
    etat["arrete_le"] = maintenant
    ronde = ronde_actuelle(etat)
    if ronde and ronde["statut"] == RONDE_EN_COURS:
        for match in ronde["matchs"]:
            if match["statut"] != MATCH_TERMINE:
                match["statut"] = MATCH_ANNULE
