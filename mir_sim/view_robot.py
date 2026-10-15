"""
Visualiseur 3D interactif d'un robot décrit par sa configuration (section "structure"), pour vérifier
modules, branchements et plages articulaires.

  python -m mir_sim.view_robot config_robot.json
  python -m mir_sim.view_robot config_robot.json --scene scene.json      # avec table, objets, caméras
  python -m mir_sim.view_robot config_robot.json --export robot.xml      # exporte le modèle MuJoCo (MJCF)

Dans le viewer : panneau de droite > Control pour bouger chaque moteur, double-clic pour sélectionner un corps.
"""
import argparse
import sys
import mujoco
import mujoco.viewer
from mir_sim.model_builder import StructureError, build_model

parser = argparse.ArgumentParser()
parser.add_argument("config", help="configuration du robot (JSON) contenant une section \"structure\"")
parser.add_argument("--scene", default=None, help="scène JSON (table, objets, caméras fixes, position du robot)")
parser.add_argument("--export", default=None, help="chemin du fichier MJCF à écrire")
args = parser.parse_args()

try:
    built = build_model(args.config, args.scene)
except StructureError as e:
    sys.exit(str(e))
if args.export:
    with open(args.export, "w") as f:
        f.write(built.spec.to_xml())
    print(f"modèle exporté : {args.export}")
else:
    mujoco.viewer.launch(built.model)
