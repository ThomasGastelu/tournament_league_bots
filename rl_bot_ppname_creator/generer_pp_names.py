"""Génère le nom et le mot de passe d'une partie privée Rocket League.

Le nom et le mot de passe sont identiques, au format : tomato_<aléatoire>

Exemples :
    python generer_pp.py            -> une partie privée
    python generer_pp.py -n 8       -> 8 parties privées (une par match)
    python generer_pp.py -l 8       -> partie aléatoire de 8 caractères
    python generer_pp.py -c         -> copie aussi le résultat dans le presse-papiers
    python generer_pp.py -o a.json  -> écrit dans a.json au lieu de pp.json

Le résultat est toujours écrit dans un fichier JSON (pp.json par défaut).
"""

import argparse
import json
import secrets
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PREFIXE = "tomato_"
FICHIER_PAR_DEFAUT = "pp.json"

# Minuscules + chiffres, sans les caractères faciles à confondre
# quand on les recopie dans le jeu (0/o, 1/l/i).
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generer_pp(longueur: int = 6) -> str:
    """Retourne un identifiant du type tomato_xxxxxx (nom = mot de passe)."""
    aleatoire = "".join(secrets.choice(ALPHABET) for _ in range(longueur))
    return PREFIXE + aleatoire


def generer_plusieurs(nombre: int, longueur: int) -> list[str]:
    """Génère `nombre` identifiants tous différents."""
    resultats: set[str] = set()
    while len(resultats) < nombre:
        resultats.add(generer_pp(longueur))
    return list(resultats)


def ecrire_json(pps: list[str], chemin: Path) -> None:
    """Écrit les parties privées dans un fichier JSON (écrase le fichier existant)."""
    donnees = {
        "genere_le": datetime.now().isoformat(timespec="seconds"),
        "parties": [
            {"match": i, "nom": pp, "mot_de_passe": pp}
            for i, pp in enumerate(pps, start=1)
        ],
    }
    chemin.write_text(json.dumps(donnees, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def copier_presse_papiers(texte: str) -> bool:
    """Copie le texte dans le presse-papiers (Windows uniquement)."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.run("clip", input=texte, text=True, check=True, shell=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Génère nom + mot de passe (identiques) de partie privée Rocket League."
    )
    parser.add_argument("-n", "--nombre", type=int, default=1,
                        help="nombre de parties privées à générer (défaut : 1)")
    parser.add_argument("-l", "--longueur", type=int, default=6,
                        help="longueur de la partie aléatoire (défaut : 6)")
    parser.add_argument("-c", "--copier", action="store_true",
                        help="copie le résultat dans le presse-papiers")
    parser.add_argument("-o", "--sortie", type=Path, default=Path(FICHIER_PAR_DEFAUT),
                        help=f"fichier JSON de sortie (défaut : {FICHIER_PAR_DEFAUT})")
    args = parser.parse_args()

    if args.nombre < 1:
        parser.error("--nombre doit être au moins 1")
    if args.longueur < 1:
        parser.error("--longueur doit être au moins 1")

    pps = generer_plusieurs(args.nombre, args.longueur)

    lignes = []
    for i, pp in enumerate(pps, start=1):
        titre = f"Match {i}" if args.nombre > 1 else "Partie privée"
        print(f"{titre}")
        print(f"  Nom          : {pp}")
        print(f"  Mot de passe : {pp}")
        lignes.append(f"{titre} -> Nom : {pp} | Mot de passe : {pp}")

    try:
        ecrire_json(pps, args.sortie)
        print(f"\nÉcrit dans {args.sortie.resolve()}")
    except OSError as erreur:
        print(f"\nImpossible d'écrire {args.sortie} : {erreur}", file=sys.stderr)
        sys.exit(1)

    if args.copier:
        # Une seule partie : on copie juste l'identifiant, prêt à coller en jeu.
        texte = pps[0] if args.nombre == 1 else "\n".join(lignes)
        if copier_presse_papiers(texte):
            print("\n(Copié dans le presse-papiers)")
        else:
            print("\n(Impossible de copier dans le presse-papiers)")


if __name__ == "__main__":
    main()
