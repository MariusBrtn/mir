"""Téléopérations : découverte, téléopérations fournies et boucle complète sur le robot simulé."""
import pytest
from mir_robot.commande import ExecutionCommande
from mir_robot.mir_robot import chemin_robot, robots_disponibles
from mir_robot.teleop.loading import discover_teleops
from mir_utils.keyboard_listener import Key


def dossier_teleop(nom: str):
    return chemin_robot(nom).parent / "teleop"


def test_teleops_fournies():
    trouvees = discover_teleops()
    assert "Clavier" in trouvees.commandes
    assert "Bras leader" not in trouvees.commandes      # proposé seulement si le robot a un bras leader configuré
    assert not trouvees.erreurs


@pytest.mark.parametrize("nom", [n for n in robots_disponibles() if dossier_teleop(n).is_dir()])
def test_teleops_des_robots_se_chargent(nom):
    assert not discover_teleops(dossier_teleop(nom)).erreurs


def demarrer_teleop(robot, nom_teleop, clavier, robot_nom, fps=10):
    commande = discover_teleops(dossier_teleop(robot_nom)).commandes[nom_teleop]()
    return ExecutionCommande(robot, commande, fps=fps, clavier=clavier)


def test_clavier_deplace_l_actionneur_choisi(robot_simule, clavier):
    robot = robot_simule("bras_2ddl")
    execution = demarrer_teleop(robot, "Clavier", clavier, "bras_2ddl")
    observation = robot.get_observation()

    execution.tour(observation)
    assert execution.derniere_action is None                   # aucune touche : rien n'est envoyé

    clavier.enfoncees = {Key.Digit2, Key.Right}
    execution.tour(observation)
    depart = observation["joint_2.position"]
    assert execution.derniere_action == {"joint_2.position": pytest.approx(depart + 3.0)}   # 30 °/s à 10 Hz

    clavier.enfoncees = {Key.Right}
    for _ in range(100):                                       # la consigne s'arrête à la butée
        execution.tour(observation)
    assert execution.derniere_action["joint_2.position"] == robot.action_features["joint_2.position"].get_range()[1]

    clavier.enfoncees = {Key.Esc}
    assert not execution.tour(observation)                     # Échap termine la téléopération
    execution.arreter()


def test_conduite_au_clavier_du_robot_mobile(robot_simule, clavier):
    robot = robot_simule("test_mobile")
    execution = demarrer_teleop(robot, "Conduite au clavier", clavier, "test_mobile")
    clavier.enfoncees = {Key.Up}
    execution.tour(robot.get_observation())
    action = execution.derniere_action
    gauche = [v for n, v in action.items() if "gauche" in n]
    droite = [v for n, v in action.items() if "droite" in n]
    assert len(gauche) == len(droite) == 2
    assert len(set(gauche)) == 1 and gauche[0] > 0
    assert droite == [-gauche[0]] * 2                          # roues de droite montées en miroir
    execution.arreter()
