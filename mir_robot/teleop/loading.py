"""
Recherche des téléopérations et exécution par MIR.

Les téléopérations proposées pour un robot sont celles fournies avec MIR (dossier provided) et celles du dossier
teleop du robot (robots/<robot>/teleop). Chaque fichier .py peut en définir une ou plusieurs.
Un périphérique qui a besoin d'une configuration la trouve dans le dossier teleop du robot (<config_name>.json) ;
une téléopération fournie qui utilise un tel périphérique n'est proposée que si le robot l'a (ex. « Bras leader »
dès que le bras leader est construit).
"""
from __future__ import annotations
import inspect
from pathlib import Path
from typing import Any
from loguru import logger
from mir_robot.commande import Commande, CommandesDisponibles, _charger_module
from mir_robot.teleop.keyboard import KeyboardTeleoperator
from mir_robot.teleop.leader_arm import LeaderArmTeleoperator
from mir_robot.teleop.teleoperator import Teleoperator
from mir_utils.keyboard_listener import Key

PROVIDED_DIR = Path(__file__).parent / "provided"
DEVICE_CLASSES = (Teleoperator, KeyboardTeleoperator, LeaderArmTeleoperator)
class TeleopCommande(Commande):
    """Une téléopération exécutée comme une commande de MIR (même boucle que les autres commandes)."""
    famille = "teleop"
    teleop_class: type[Teleoperator]
    teleop_dir: Path | None = None

    def demarrer(self, robot):
        self.teleop = self.teleop_class()
        self.teleop.teleop_dir = self.teleop_dir
        self.teleop.actions = robot.actions
        self.teleop.fps = robot.fps
        self.teleop.keyboard = robot.clavier
        self.teleop.connect()

    def action(self, observation):
        if self.teleop.keyboard is not None and self.teleop.keyboard.is_pressed(Key.Esc):
            self.terminer()
            return None
        action = self.teleop.get_action(observation)
        if action is not None and not isinstance(action, dict):
            raise TypeError(f"get_action() doit renvoyer un dictionnaire d'actions ou None, pas {type(action).__name__}")
        return action

    def arreter(self):
        if getattr(self, "teleop", None) is not None and self.teleop.is_connected:
            self.teleop.disconnect()


def teleop_classes(module) -> list[type[Teleoperator]]:
    """Téléopérations définies dans ce module (pas celles qu'il importe, ni les classes des périphériques)."""
    return [cls for _, cls in inspect.getmembers(module, inspect.isclass)
            if issubclass(cls, Teleoperator) and cls not in DEVICE_CLASSES and cls.__module__ == module.__name__]


def discover_teleops(robot_teleop_dir: Path | None = None) -> CommandesDisponibles:
    """Téléopérations fournies et celles du robot, sous forme de commandes. Les fichiers sont relus à chaque appel ;
    ceux dont le nom commence par '_' sont ignorés."""
    result = CommandesDisponibles()
    folders = [PROVIDED_DIR] + ([robot_teleop_dir] if robot_teleop_dir is not None else [])
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                classes = teleop_classes(_charger_module(path))
            except BaseException as e:
                logger.warning(f"téléopération non chargée : {path} : {e}")
                result.erreurs[path] = e
                continue
            for cls in classes:
                if folder == PROVIDED_DIR and cls.config_name and \
                        (robot_teleop_dir is None or not (robot_teleop_dir / f"{cls.config_name}.json").exists()):
                    continue        # périphérique pas encore construit ou configuré pour ce robot
                name = cls.display_name()
                if name in result.commandes:
                    logger.warning(f"téléopération '{name}' définie deux fois, {path} ignoré")
                    continue
                result.commandes[name] = type(f"Teleop_{cls.__name__}", (TeleopCommande,), {
                    "nom": name, "description": cls.description, "teleop_class": cls, "teleop_dir": robot_teleop_dir,
                    "__module__": cls.__module__})
                result.fichiers[name] = path
    return result


def check_teleop_file(path: Path) -> tuple[list[str], str | None, int | None]:
    """Charge un fichier de téléopération pour le vérifier.
    Renvoie (noms des téléopérations trouvées, message d'erreur ou None, numéro de la ligne en cause ou None)."""
    import traceback
    try:
        module = _charger_module(path)
    except SyntaxError as e:
        return [], f"Erreur de syntaxe ligne {e.lineno} : {e.msg}", e.lineno
    except BaseException as e:
        lines = [f.lineno for f in traceback.extract_tb(e.__traceback__) if Path(f.filename) == path]
        line = lines[-1] if lines else None
        return [], f"{type(e).__name__} : {e}" + (f" (ligne {line})" if line else ""), line
    names = [cls.display_name() for cls in teleop_classes(module)]
    if not names:
        return [], "aucune téléopération dans ce fichier (classe dérivée de KeyboardTeleoperator, LeaderArmTeleoperator...)", None
    return names, None, None


def run_teleop(robot, teleop_class: type[Teleoperator], teleop_dir: Path | None = None, fps: float = 30,
               duration: float | None = None) -> None:
    """En script : fait tourner la téléopération sur un robot connecté et configuré (réel ou simulé).
    teleop_dir : dossier teleop du robot (configurations des périphériques, ex. robots/mon_bras/teleop)."""
    from mir_robot.commande import executer
    commande_class: Any = type("Teleop", (TeleopCommande,), {"teleop_class": teleop_class, "teleop_dir": teleop_dir})
    executer(robot, commande_class(), fps=fps, duree=duration)
