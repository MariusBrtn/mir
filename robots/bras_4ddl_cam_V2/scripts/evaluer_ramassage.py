"""
Évaluer un modèle entraîné sur le ramassage du dé, en simulation : le modèle pilote seul le bras, le dé est posé
à des positions qu'il n'a jamais vues (autre graine que les démonstrations), et on compte les dés soulevés.

    uv run python robots/bras_4ddl_cam_V2/scripts/evaluer_ramassage.py                  # dernier modèle entraîné
    uv run python robots/bras_4ddl_cam_V2/scripts/evaluer_ramassage.py --modele <dossier> --essais 20 --video essai.gif
"""
from __future__ import annotations
import argparse
import math
import random
import runpy
from pathlib import Path
from loguru import logger
from mir_robot.commande import ExecutionCommande
from mir_robot.mir_robot import chemin_robot
from mir_robot.training import TrainedPolicy, trained_models

GENERATEUR = runpy.run_path(str(Path(__file__).with_name("generer_ramassage.py")))
OBJET, FPS, DUREE_S, DEPART = GENERATEUR["OBJET"], GENERATEUR["FPS"], GENERATEUR["DUREE_S"], GENERATEUR["DEPART"]
HAUTEUR_DE_M, REUSSITE_M = GENERATEUR["HAUTEUR_DE_M"], GENERATEUR["REUSSITE_M"]
RAYON_M, ANGLE_DEG, ORIENTATION_DEG = GENERATEUR["RAYON_M"], GENERATEUR["ANGLE_DEG"], GENERATEUR["ORIENTATION_DEG"]


class ClavierInutile:
    """Le modèle n'utilise pas le clavier."""
    def start(self): pass
    def stop(self): pass
    def get_key(self): return None
    def is_pressed(self, key): return False


def essai(robot, monde, politique, x, y, orientation_deg, images=None):
    """Le modèle pilote le bras pendant la durée d'une démonstration ; renvoie la hauteur finale du dé (m)."""
    monde.reset(DEPART)
    monde.set_object_pose(OBJET, [x, y, HAUTEUR_DE_M], orientation_deg)
    pas = round(1 / FPS / monde.model.opt.timestep)
    execution = ExecutionCommande(robot, politique, FPS, clavier=ClavierInutile())
    for _ in range(round(DUREE_S * FPS)):
        execution.tour(robot.get_observation())
        monde.step(pas)
        if images is not None:
            images.append(monde.render("overview", 480, 360))
    return float(monde.get_object_position(OBJET)[2])


def evaluer(dossier_modele, essais=20, graine=1000, video=None):
    politique = TrainedPolicy(dossier_modele)
    robot, monde, _ = GENERATEUR["ouvrir_robot"]()
    ik = GENERATEUR["GripperIK"](monde)
    hasard = random.Random(graine)
    reussis = 0
    try:
        for i in range(essais):
            rayon, angle = hasard.uniform(*RAYON_M), math.radians(hasard.uniform(*ANGLE_DEG))
            x, y = rayon * math.cos(angle), rayon * math.sin(angle)
            # même orientation que dans les démonstrations : deux faces face aux mors, à quelques degrés près
            cles = GENERATEUR["postures"](ik, x, y)
            if cles is None:
                continue
            serrage = ik.forward(cles["fermeture"])[2]
            orientation = math.degrees(math.atan2(serrage[1], serrage[0])) + hasard.uniform(-1, 1) * ORIENTATION_DEG
            images = [] if (video and i == 0) else None
            hauteur = essai(robot, monde, politique, x, y, orientation, images)
            ok = hauteur > REUSSITE_M
            reussis += ok
            print(f"  essai {i + 1}/{essais} : dé en ({x*100:.1f}, {y*100:.1f}) cm -> "
                  f"{'soulevé' if ok else 'raté'} (hauteur {hauteur*100:.1f} cm)")
            if images:
                import imageio.v2 as imageio
                imageio.mimsave(video, images[::2], duration=2 / FPS)
                print(f"  vidéo du premier essai : {video}")
    finally:
        robot.disconnect()
    print(f"Réussite : {reussis}/{essais} ({100 * reussis / essais:.0f} %)")
    return reussis / essais


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Évaluer un modèle de ramassage du dé en simulation")
    parser.add_argument("--modele", help="dossier du modèle entraîné (par défaut : le plus récent)")
    parser.add_argument("--essais", type=int, default=20)
    parser.add_argument("--video", help="fichier .gif du premier essai (vue d'ensemble)")
    args = parser.parse_args()
    logger.remove()
    logger.add(lambda message: print(message, end=""), level="WARNING")
    modele = args.modele or next(iter(trained_models(chemin_robot("bras_4ddl_cam_V2").parent)), None)
    if modele is None:
        raise SystemExit("aucun modèle entraîné : lancer d'abord un script de robots/bras_4ddl_cam_V2/modeles/")
    print(f"Modèle : {modele}")
    evaluer(modele, args.essais, video=args.video)
