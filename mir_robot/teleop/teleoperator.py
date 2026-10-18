"""
Téléopérateur : ce qui transforme ce que fait l'utilisateur (touches, manette, bras leader...) en actions du robot.

Toutes les téléopérations ont la même forme. MIR fait tourner la même boucle pour toutes, sur le robot réel
comme sur le robot simulé :

    teleop.connect()
    while running:
        observation = robot.get_observation()
        robot.send_action(teleop.get_action(observation))
    teleop.disconnect()

Une téléopération hérite de la classe de son périphérique (KeyboardTeleoperator, LeaderArmTeleoperator...),
qui s'occupe du matériel (connect, disconnect, read), et n'écrit que la correspondance :

    from mir_robot.teleop import KeyboardTeleoperator

    class MyTeleop(KeyboardTeleoperator):
        name = "My teleop"
        description = "Right/left arrows: turn joint 1"

        def get_action(self, observation):
            keys = self.read()                  # what the device gives: {"left": False, "right": True, ...}
            ...
            return {"joint_1.position": 30.0}   # what the robot receives (or None to send nothing)
"""
from __future__ import annotations
import inspect
from pathlib import Path
from typing import Any


class Teleoperator:
    """Classe de base des téléopérateurs.

    Fournis par MIR avant connect() :
      self.actions  : actions acceptées par le robot piloté (noms, unités, plages)
      self.fps      : fréquence de la boucle (tours par seconde)
      self.keyboard : touches de la fenêtre de MIR (ou du clavier, en script)
      self.teleop_dir : dossier teleop du robot, où sont les configurations des périphériques"""
    name: str = ""
    description: str = ""
    config_name: str = ""       # périphérique qui a une configuration : nom de son fichier .json dans le dossier teleop

    def __init__(self) -> None:
        self.actions: dict[str, Any] = {}
        self.fps: float = 30.0
        self.keyboard: Any = None
        self.teleop_dir: Path | None = None
        self._connected = False

    # ------------------------------------------------------------------ matériel (classe du périphérique)
    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def read(self) -> dict[str, Any]:
        """Ce que donne le périphérique, sous forme de dictionnaire."""
        raise NotImplementedError(f"{type(self).__name__} : le périphérique ne définit pas read()")

    # ------------------------------------------------------------------ correspondance (téléopération)
    def get_action(self, observation: dict[str, Any]) -> dict[str, Any] | None:
        """Appelée à chaque tour de boucle avec les mesures du robot. Renvoie l'action envoyée telle quelle
        au robot (ex. {"joint_1.position": 30.0}), ou None pour ne rien envoyer."""
        raise NotImplementedError(f"{type(self).__name__} doit définir la méthode get_action(self, observation)")

    # ------------------------------------------------------------------ outils
    @classmethod
    def display_name(cls) -> str:
        return cls.name or cls.__name__

    def config_file(self) -> Path:
        """Configuration du périphérique : <config_name>.json, dans le dossier teleop du robot (à défaut, à côté
        du fichier de la téléopération). Toutes les téléopérations du robot qui l'utilisent la partagent."""
        folder = self.teleop_dir or Path(inspect.getfile(type(self))).parent
        return folder / f"{self.config_name}.json"
