"""
Lance une commande sur le robot réel ou simulé.

  python demo_commande.py                     # liste les commandes disponibles
  python demo_commande.py Aller-retour --sim  # commande "Aller-retour" sur le robot simulé
  python demo_commande.py Clavier             # commande "Clavier" sur le robot réel
"""
import argparse
from pathlib import Path
from mir_robot.mir_robot import mirRobot, mirRobotConfig
from mir_robot.commande import decouvrir_commandes, executer

HERE = Path(__file__).parent

parser = argparse.ArgumentParser()
parser.add_argument("commande", nargs="?", help="nom de la commande")
parser.add_argument("--sim", action="store_true", help="robot simulé")
parser.add_argument("--config", default=str(HERE.parent / "bras_leader_follower_cam" / "bras_follower_cam.json"))
parser.add_argument("--fps", type=float, default=30)
parser.add_argument("--duree", type=float, default=None, help="durée en s (par défaut : jusqu'à Ctrl+C)")
args = parser.parse_args()

disponibles = decouvrir_commandes()
for fichier, erreur in disponibles.erreurs.items():
    print(f"Erreur dans {fichier} : {erreur}")
if args.commande not in disponibles.commandes:
    print("Commandes disponibles :")
    for nom, classe in disponibles.commandes.items():
        print(f"  {nom:15} {classe.description}")
    raise SystemExit

config = mirRobotConfig.load(args.config)
if args.sim:
    from mir_sim.sim_devices_factory import SimDevicesFactory
    robot = mirRobot(config, devices_factory=SimDevicesFactory())
else:
    robot = mirRobot(config)
robot.connect()
try:
    robot.configure()
    robot.enable_observations_by_name([nom for nom in robot.get_observables() if nom.endswith(".position")])
    executer(robot, disponibles.commandes[args.commande](), fps=args.fps, duree=args.duree)
finally:
    robot.disconnect()
