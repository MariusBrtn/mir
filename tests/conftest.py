"""
Outils communs aux tests : robot simulé et clavier factice. Aucun matériel nécessaire.

Lancer tous les tests (depuis le dossier mir) :
    python -m pytest
Un seul fichier, ou un seul test :
    python -m pytest tests/test_essai.py
    python -m pytest tests/test_essai.py -k echelon
"""
from __future__ import annotations
import pytest
from mir_robot.mir_robot import chemin_robot, mirRobot, mirRobotConfig
from mir_sim.config_from_structure import complete_config_from_structure
from mir_sim.sim_devices_factory import SimDevicesFactory


def config_robot(nom: str) -> mirRobotConfig:
    """Configuration d'un robot du dossier robots, complétée par sa structure (comme pour la simulation)."""
    cfg = mirRobotConfig.load(str(chemin_robot(nom)))
    complete_config_from_structure(cfg)
    return cfg


@pytest.fixture
def robot_simule():
    """Fabrique de robots simulés connectés et configurés : robot_simule("bras_2ddl").
    Les robots sont déconnectés à la fin du test, même en cas d'échec."""
    robots: list[mirRobot] = []

    def creer(nom: str = "bras_2ddl") -> mirRobot:
        robot = mirRobot(config_robot(nom), devices_factory=SimDevicesFactory())
        robot.connect()
        robots.append(robot)
        robot.configure()
        robot.enable_all_observations()
        return robot

    yield creer
    for robot in robots:
        robot.disconnect()


class ClavierFactice:
    """Remplace le clavier de MIR : le test choisit les touches enfoncées (clavier.enfoncees.add(Key.Right))."""

    def __init__(self):
        self.enfoncees: set = set()
        self.demarre = False

    def start(self):
        self.demarre = True

    def stop(self):
        self.demarre = False

    def get_key(self):
        return None

    def is_pressed(self, key) -> bool:
        return key in self.enfoncees


@pytest.fixture
def clavier():
    return ClavierFactice()
