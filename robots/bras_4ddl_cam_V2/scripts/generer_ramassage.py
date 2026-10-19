"""
Démonstrations automatiques de ramassage d'un dé, en simulation.

À chaque démonstration, le dé est posé au hasard dans une zone que la caméra de la pince voit depuis la posture de
départ, et que la pince peut saisir : de 18 à 20 cm du socle, à ±15° de l'axe du bras. Un « expert », qui connaît
la position exacte du dé (on est en simulation), enchaîne : au-dessus du dé -> descente -> fermeture -> levée.
Les démonstrations réussies (dé soulevé) sont enregistrées dans un dataset de MIR, comme une collecte par
téléopération : image de cam_1, angles des moteurs et consignes envoyées.

    uv run python robots/bras_4ddl_cam_V2/scripts/generer_ramassage.py --nombre 50
    uv run python robots/bras_4ddl_cam_V2/scripts/generer_ramassage.py --nombre 50 --taille 320x240 --dataset ramassage_sim_320

La physique avance pas à pas (pas en temps réel) : une démonstration de 5 s se calcule en 1 à 2 s.
"""
from __future__ import annotations
import argparse
import math
import random
import time
from pathlib import Path
from loguru import logger
from mir_robot.donnees import DatasetMIR, FormatDataset
from mir_robot.mir_robot import chemin_robot
from mir_sim.demonstrations import interpolate, open_sim_robot, record_episode
from mir_sim.grasp import GripperIK
from mir_sim.scenes import load_scene_file

ROBOT = "bras_4ddl_cam_V2"
SCENE = chemin_robot(ROBOT).parent / "scenes" / "ramassage_de.json"
OBJET = "de"
CAMERA = "cam_1"
FPS = 20
TACHE = "Ramasser le dé"

PINCE_OUVERTE, PINCE_FERMEE = -14.0, 14.0
# posture de départ et zone du dé : celles de la scène (les mêmes que « Replacer la scène » dans MIR)
_SCENE = load_scene_file(SCENE)
_PLACEMENT = next(o for o in _SCENE["objects"] if o["name"] == OBJET)["placement"]
DEPART = {m: float(v) for m, v in _SCENE["start_pose"].items()}    # la caméra de la pince voit toute la zone du dé
RAYON_M = tuple(_PLACEMENT["radius_m"])     # zone du dé : distance à l'axe du socle
ANGLE_DEG = tuple(_PLACEMENT["angle_deg"])  # et angle autour de l'axe du bras
ORIENTATION_DEG = _PLACEMENT["yaw_deg"][1]  # le dé est tourné au hasard de ± cette valeur par rapport aux mors
HAUTEUR_DE_M = 0.008                    # centre du dé (16 mm) posé sur la table
APPROCHE_M = 0.05                       # hauteur de la pince au-dessus du dé avant de descendre
LEVEE_M = 0.06                          # hauteur de levée
REUSSITE_M = 0.03                       # dé soulevé : son centre est à plus de 3 cm de la table (posé : 0,8 cm)

# étapes de l'expert : (nom, durée en s) ; la consigne va en ligne droite (angles) vers la posture de l'étape
ETAPES = [("attente", 0.5), ("au-dessus", 1.5), ("descente", 1.0), ("fermeture", 0.6), ("levée", 1.0),
          ("tenue", 0.4)]
DUREE_S = sum(duree for _, duree in ETAPES)


def ouvrir_robot():
    """Bras simulé dans la scène du dé, physique arrêtée : c'est le générateur qui la fait avancer."""
    return open_sim_robot(ROBOT, SCENE, CAMERA)


def postures(ik, x, y):
    """Postures clés de l'expert pour un dé en (x, y), ou None si la saisie est impossible."""
    saisie = ik.solve([x, y, HAUTEUR_DE_M])
    if saisie is None:
        return None
    dessus = ik.solve([x, y, HAUTEUR_DE_M + APPROCHE_M], start=saisie)
    levee = ik.solve([x, y, HAUTEUR_DE_M + LEVEE_M], start=saisie)
    if dessus is None or levee is None:
        return None
    return {"attente": {**DEPART},
            "au-dessus": {**dessus, "joint_5": PINCE_OUVERTE},
            "descente": {**saisie, "joint_5": PINCE_OUVERTE},
            "fermeture": {**saisie, "joint_5": PINCE_FERMEE},
            "levée": {**levee, "joint_5": PINCE_FERMEE},
            "tenue": {**levee, "joint_5": PINCE_FERMEE}}


def consigne(t, cles):
    """Consigne de l'expert à l'instant t : on va en ligne droite de la posture précédente vers celle de l'étape."""
    return interpolate(t, ETAPES, DEPART, cles)


def demonstration(robot, monde, fmt, cles, x, y, orientation_deg, taille=None):
    """Une démonstration : renvoie (trames du dataset, dé soulevé ?)."""
    monde.reset(DEPART)
    monde.set_object_pose(OBJET, [x, y, HAUTEUR_DE_M], orientation_deg)
    trames = record_episode(robot, monde, fmt, FPS, DUREE_S, lambda t: consigne(t, cles), CAMERA, taille)
    return trames, monde.get_object_position(OBJET)[2] > REUSSITE_M


def generer(nombre, dataset, graine=0, taille=None):
    """Enregistre `nombre` démonstrations réussies dans le dataset (dossier) ; renvoie (réussies, essayées).
    taille : (largeur, hauteur) des images enregistrées ; None : taille de la caméra."""
    hasard = random.Random(graine)
    robot, monde, observations = ouvrir_robot()
    try:
        ik = GripperIK(monde)
        fmt = FormatDataset.depuis_robot(robot.get_observables(), observations, list(robot.action_features))
        if taille is not None:
            fmt.images[CAMERA] = (taille[1], taille[0], 3)
        ds = DatasetMIR(Path(dataset))
        reussies = essais = 0
        while reussies < nombre and essais < 2 * nombre + 10:
            essais += 1
            rayon, angle = hasard.uniform(*RAYON_M), math.radians(hasard.uniform(*ANGLE_DEG))
            x, y = rayon * math.cos(angle), rayon * math.sin(angle)
            cles = postures(ik, x, y)
            if cles is None:
                print(f"  dé en ({x*100:.1f}, {y*100:.1f}) cm : hors de portée, ignoré")
                continue
            # le dé présente deux faces aux mors (direction de serrage), à quelques degrés près
            serrage = ik.forward(cles["fermeture"])[2]
            orientation = math.degrees(math.atan2(serrage[1], serrage[0])) + hasard.uniform(-1, 1) * ORIENTATION_DEG
            debut = time.perf_counter()
            trames, ok = demonstration(robot, monde, fmt, cles, x, y, orientation, taille)
            if not ok:
                print(f"  démonstration {essais} : dé en ({x*100:.1f}, {y*100:.1f}) cm, raté (non enregistrée)")
                continue
            ds.ajouter_episode(fmt, FPS, trames, TACHE, {
                "simulation": True, "scene": SCENE.name, "generateur": Path(__file__).name, "graine": graine,
                "de": {"x_m": round(x, 4), "y_m": round(y, 4), "orientation_deg": round(orientation, 1)}})
            reussies += 1
            print(f"  démonstration {reussies}/{nombre} : dé en ({x*100:.1f}, {y*100:.1f}) cm, "
                  f"calculée en {time.perf_counter() - debut:.1f} s")
        return reussies, essais
    finally:
        robot.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Démonstrations automatiques de ramassage d'un dé (simulation)")
    parser.add_argument("--nombre", type=int, default=50, help="nombre de démonstrations réussies à enregistrer")
    parser.add_argument("--dataset", default="ramassage_sim", help="nom du dataset (dans le dossier du robot)")
    parser.add_argument("--graine", type=int, default=0, help="graine du hasard (mêmes positions du dé)")
    parser.add_argument("--taille", help="taille des images enregistrées, ex. 320x240 (par défaut : celle de la caméra)")
    args = parser.parse_args()
    logger.remove()
    logger.add(lambda message: print(message, end=""), level="WARNING")
    dossier = chemin_robot(ROBOT).parent / "datasets" / args.dataset
    print(f"{args.nombre} démonstrations -> {dossier}")
    taille = tuple(int(v) for v in args.taille.split("x")) if args.taille else None
    reussies, essais = generer(args.nombre, dossier, args.graine, taille)
    print(f"Terminé : {reussies} démonstrations enregistrées sur {essais} essayées.")
