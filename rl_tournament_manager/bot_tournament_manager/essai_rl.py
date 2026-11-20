"""Essai du vrai connecteur, sans Discord ni tournoi : le bot fait des visites dans UNE partie privée.

Rocket League ouvert au menu principal, partie privée déjà créée par quelqu'un, puis :

    .venv\\Scripts\\python -m bot_tournament_manager.essai_rl --nom tomato_abc --mot-de-passe tomato_abc

Avec --visites 3, le bot repasse 3 fois (comme pendant un tournoi) : pratique pour vérifier
qu'il voit bien la fin du match quand les joueurs restent dans la partie.
Réglages : les RL_* du fichier .env.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time

from dotenv import load_dotenv

from .config import RACINE, ErreurConfig, charger_reglages_rl
from .observation import PartieAObserver


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Le bot rejoint une partie privée, lit le score et la quitte.")
    parser.add_argument("--nom", required=True, help="nom de la partie privée")
    parser.add_argument("--mot-de-passe", default="", help="mot de passe de la partie privée")
    parser.add_argument("--visites", type=int, default=1, help="nombre de visites (défaut : 1)")
    parser.add_argument("--pause", type=float, default=20, help="secondes entre deux visites (défaut : 20)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    load_dotenv(RACINE / ".env")
    try:
        from .connecteur_rl import PiloteRL, resume
        pilote = PiloteRL(charger_reglages_rl())
    except ErreurConfig as erreur:
        sys.exit(f"❌ {erreur}")
    for avertissement in pilote.verifier():
        print(f"⚠️  {avertissement}")

    partie = PartieAObserver(tournoi_id="essai", ronde=1, zone=1, nom=args.nom, mot_de_passe=args.mot_de_passe,
                             pseudos_bleu=(), pseudos_orange=())
    print("Mets Rocket League au premier plan, au menu principal. Début dans 5 s… "
          "(arrêt d'urgence : souris dans le coin en haut à gauche)")
    time.sleep(5)

    lecture = None
    for numero in range(1, args.visites + 1):
        print(f"\n--- Visite {numero}/{args.visites} ---")
        try:
            lecture = pilote.visiter(partie, threading.Event())
        except Exception as erreur:
            if type(erreur).__name__ == "FailSafeException":
                sys.exit("Arrêt d'urgence.")
            raise
        if not lecture.rejoint:
            print(f"❌ Partie pas rejointe : {lecture.erreur}")
        else:
            print(f"✅ Partie rejointe. Événements reçus : {', '.join(lecture.evenements) or 'aucun'}")
            print(f"   {resume(lecture.etat)}")
            joueurs = [(p.get('Name'), p.get('TeamNum')) for p in (lecture.etat or {}).get("Players", [])]
            print(f"   Joueurs vus : {joueurs or 'aucun'}")
            print(f"   Match terminé : {'oui, gagnant ' + ('Bleu' if lecture.gagnant == 0 else 'Orange' if lecture.gagnant == 1 else '?') if lecture.termine else 'non'}")
            if lecture.termine:
                break
        if numero < args.visites:
            time.sleep(args.pause)

    if lecture and lecture.rejoint and lecture.etat:
        resultat = pilote.construire_resultat(lecture.etat, lecture.gagnant if lecture.termine else None)
        resultat.update({"partie": args.nom, "statut": "terminé" if lecture.termine else "match pas fini"})
        print("\nRésultat que le bot enregistrerait :")
        print(json.dumps(resultat, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
