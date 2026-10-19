"""
Démonstrations automatiques d'insertion, en simulation : le bras tient un cube et doit le lâcher dans le trou du
couvercle d'une boîte.

Au début de chaque démonstration, le cube est mis dans la pince (non enregistré) et la boîte est posée au hasard dans
une zone que la caméra de la pince voit depuis la posture de départ, et où le bras peut lâcher le cube au-dessus du
trou : de 20,5 à 22 cm du socle, à ±15° de l'axe du bras, tournée d'un angle quelconque. Un « expert », qui connaît la
position exacte de la boîte et du cube (on est en simulation), enchaîne : au-dessus du trou, en hauteur -> descente
verticale -> ouverture de la pince (le cube tombe dans la boîte) -> remontée. Les démonstrations réussies (cube dans
la boîte) sont enregistrées dans un dataset de MIR : image de cam_1, angles des moteurs et consignes envoyées.

    uv run python robots/bras_4ddl_cam_V2/scripts/generer_insertion.py --nombre 50 --taille 320x240
"""
from __future__ import annotations
import argparse
import math
import random
import time
from pathlib import Path
import numpy as np
from loguru import logger
from mir_robot.donnees import DatasetMIR, FormatDataset
from mir_robot.mir_robot import chemin_robot
from mir_sim.demonstrations import interpolate, open_sim_robot, place_in_gripper, record_episode
from mir_sim.grasp import GripperIK

ROBOT = "bras_4ddl_cam_V2"
SCENE = Path(__file__).with_name("insertion_boite.json")
BOITE, OBJET = "boite", "objet"
CAMERA = "cam_1"
FPS = 20
TACHE = "Mettre le cube dans la boîte"

PINCE_OUVERTE, PINCE_FERMEE = -14.0, 14.0
# posture de départ, cube en main : la caméra de la pince voit la boîte, où qu'elle soit dans sa zone
DEPART = {"joint_1": 0.0, "joint_2": -50.0, "joint_3": 90.0, "joint_4": -90.0, "joint_5": PINCE_FERMEE}
RAYON_M = (0.205, 0.22)                 # zone de la boîte : distance de son centre à l'axe du socle
ANGLE_DEG = (-15.0, 15.0)               # et angle autour de l'axe du bras
HAUTEUR_BOITE_M = 0.04
DEMI_LARGEUR_BOITE_M = 0.04
PASSAGE_M = 0.11                        # hauteur du cube pendant le trajet vers le trou (au-dessus de la boîte)
LACHER_M = 0.07                         # hauteur du cube au moment de le lâcher (le bout des doigts passe au-dessus)

ETAPES = [("attente", 0.6), ("au-dessus", 1.5), ("descente", 1.0), ("ouverture", 0.6), ("remontée", 0.9),
          ("tenue", 0.4)]
DUREE_S = sum(duree for _, duree in ETAPES)


def ouvrir_robot():
    """Bras simulé dans la scène de la boîte, physique arrêtée : c'est le générateur qui la fait avancer."""
    return open_sim_robot(ROBOT, SCENE, CAMERA)


def mettre_en_place(monde, ik, x, y, orientation_deg):
    """Bras en posture de départ, cube dans la pince, boîte posée en (x, y)."""
    monde.reset({**DEPART, "joint_5": PINCE_OUVERTE})
    monde.set_object_pose(BOITE, [x, y, 0.0], orientation_deg)
    bras = {m: v for m, v in DEPART.items() if m in ik.arm}
    place_in_gripper(monde, ik, OBJET, bras, PINCE_FERMEE)


def postures(ik, monde, x, y):
    """Postures clés de l'expert pour une boîte en (x, y), ou None si le trou est hors de portée.
    Le cube n'est pas exactement au point de saisie (il se cale contre un mors) : l'expert vise avec le cube."""
    bras = {m: v for m, v in DEPART.items() if m in ik.arm}
    decalage = ik.forward(bras)[0] - monde.get_object_position(OBJET)
    trou = np.array([x, y, 0.0])
    dessus = ik.solve(trou + [0, 0, PASSAGE_M] + decalage, start=bras) or ik.solve(trou + [0, 0, PASSAGE_M] + decalage)
    if dessus is None:
        return None
    lacher = ik.solve(trou + [0, 0, LACHER_M] + decalage, start=dessus)
    if lacher is None:
        return None
    return {"attente": {**DEPART},
            "au-dessus": {**dessus, "joint_5": PINCE_FERMEE},
            "descente": {**lacher, "joint_5": PINCE_FERMEE},
            "ouverture": {**lacher, "joint_5": PINCE_OUVERTE},
            "remontée": {**dessus, "joint_5": PINCE_OUVERTE},
            "tenue": {**dessus, "joint_5": PINCE_OUVERTE}}


def consigne(t, cles):
    """Consigne de l'expert à l'instant t : on va en ligne droite de la posture précédente vers celle de l'étape."""
    return interpolate(t, ETAPES, DEPART, cles)


def dans_la_boite(monde):
    """Le cube est-il dans la boîte (sous le couvercle, entre les parois) ?"""
    position = monde.get_object_position(OBJET) - monde.get_object_position(BOITE)
    rotation = monde.data.xmat[monde.model.body(BOITE).id].reshape(3, 3)
    local = rotation.T @ position
    return local[2] < HAUTEUR_BOITE_M - 0.005 and max(abs(local[0]), abs(local[1])) < DEMI_LARGEUR_BOITE_M


def demonstration(robot, monde, fmt, cles, taille=None):
    """Une démonstration (bras déjà mis en place) : renvoie (trames du dataset, cube dans la boîte ?)."""
    trames = record_episode(robot, monde, fmt, FPS, DUREE_S, lambda t: consigne(t, cles), CAMERA, taille)
    return trames, dans_la_boite(monde)


def tirer_boite(hasard):
    rayon, angle = hasard.uniform(*RAYON_M), math.radians(hasard.uniform(*ANGLE_DEG))
    return rayon * math.cos(angle), rayon * math.sin(angle), hasard.uniform(0.0, 90.0)


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
            x, y, orientation = tirer_boite(hasard)
            mettre_en_place(monde, ik, x, y, orientation)
            cles = postures(ik, monde, x, y)
            if cles is None:
                print(f"  boîte en ({x*100:.1f}, {y*100:.1f}) cm : trou hors de portée, ignorée")
                continue
            debut = time.perf_counter()
            trames, ok = demonstration(robot, monde, fmt, cles, taille)
            if not ok:
                print(f"  démonstration {essais} : boîte en ({x*100:.1f}, {y*100:.1f}) cm, ratée (non enregistrée)")
                continue
            ds.ajouter_episode(fmt, FPS, trames, TACHE, {
                "simulation": True, "scene": SCENE.name, "generateur": Path(__file__).name, "graine": graine,
                "boite": {"x_m": round(x, 4), "y_m": round(y, 4), "orientation_deg": round(orientation, 1)}})
            reussies += 1
            print(f"  démonstration {reussies}/{nombre} : boîte en ({x*100:.1f}, {y*100:.1f}) cm, "
                  f"tournée de {orientation:.0f}°, calculée en {time.perf_counter() - debut:.1f} s")
        return reussies, essais
    finally:
        robot.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Démonstrations automatiques d'insertion d'un cube (simulation)")
    parser.add_argument("--nombre", type=int, default=50, help="nombre de démonstrations réussies à enregistrer")
    parser.add_argument("--dataset", default="insertion_sim", help="nom du dataset (dans le dossier du robot)")
    parser.add_argument("--graine", type=int, default=0, help="graine du hasard (mêmes positions de la boîte)")
    parser.add_argument("--taille", help="taille des images enregistrées, ex. 320x240 (par défaut : celle de la caméra)")
    args = parser.parse_args()
    logger.remove()
    logger.add(lambda message: print(message, end=""), level="WARNING")
    dossier = chemin_robot(ROBOT).parent / "datasets" / args.dataset
    taille = tuple(int(v) for v in args.taille.split("x")) if args.taille else None
    print(f"{args.nombre} démonstrations -> {dossier}")
    reussies, essais = generer(args.nombre, dossier, args.graine, taille)
    print(f"Terminé : {reussies} démonstrations enregistrées sur {essais} essayées.")
