"""
Apprentissage par renforcement (Stable-Baselines3) : entraîner en simulation, puis piloter le robot depuis Piloter → IA.

L'environnement Gymnasium décrit la tâche (monde simulé, récompense, fin d'épisode). Sa partie « robot » est une
RobotInterface : elle passe de l'observation de MIR au vecteur donné au réseau, et de la sortie du réseau aux consignes
du robot. La même interface sert dans l'environnement d'entraînement et sur le robot piloté par MIR (réel ou simulé) :
ce que le réseau voit ne change pas quand on passe de l'un à l'autre.

    class MonRobot(RobotInterface):
        fps = 10                                    # décisions par seconde
        observations = ["lidar_1"]                  # observations du robot utilisées
        def setup(self, actions): ...               # consignes du robot : {"roue_avant_gauche.velocity": (min, max)}
        def reset(self): ...                        # début d'un épisode
        def observation(self, robot_observation): ...   # -> np.ndarray (entrée du réseau)
        def action(self, action): ...               # np.ndarray (sortie du réseau) -> {"roue_avant_gauche.velocity": 60.0}

Le script d'entraînement (robots/<robot>/modeles/<script>.py, lancé depuis « Entraîner un modèle ») se termine par :

    save_rl_model(model, MonRobot)      # -> robots/<robot>/modeles/<script>/<date>/, proposé dans Piloter → IA

Le fichier qui définit l'interface est copié avec le modèle : le modèle se recharge sans le dossier d'origine.
"""
from __future__ import annotations
import importlib.util
import inspect
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any
import numpy as np
from mir_robot.commande import Commande

RL_FILE = "rl.json"
SB3_FILE = "model.zip"
ALGORITHMS = ("PPO", "SAC", "TD3", "A2C", "DQN", "DDPG")


class RobotInterface:
    """Passage de l'observation du robot à l'entrée du réseau, et de la sortie du réseau aux consignes du robot."""
    fps: float = 10
    observations: list[str] = []

    def setup(self, actions: dict[str, tuple[float, float] | None]) -> None:
        """Appelée une fois avec les consignes acceptées par le robot : nom -> plage (min, max), ou None."""
        pass

    def reset(self) -> None:
        """Début d'un épisode (ou du pilotage) : remise à zéro de ce que l'interface retient (action précédente...)."""
        pass

    def observation(self, robot_observation: dict[str, Any]) -> np.ndarray:
        raise NotImplementedError

    def action(self, action: np.ndarray) -> dict[str, float]:
        raise NotImplementedError


def save_rl_model(model, interface: type[RobotInterface], folder: str | Path | None = None) -> Path:
    """Enregistre un modèle Stable-Baselines3 avec le fichier de son interface et une copie du script ; renvoie le
    dossier. Par défaut : robots/<robot>/modeles/<nom du script>/<date>/ (le script est dans robots/<robot>/modeles)."""
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0].endswith(".py") else None
    if folder is None:
        if script is None:
            raise ValueError("save_rl_model : indiquer le dossier (folder=...) hors d'un script")
        folder = script.parent / script.stem / time.strftime("%Y-%m-%d_%Hh%Mm%S")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    model.save(folder / SB3_FILE)
    module = Path(inspect.getfile(interface))
    shutil.copy(module, folder / module.name)
    if script is not None and script.exists() and script != module:
        shutil.copy(script, folder / script.name)
    infos = {"algorithm": type(model).__name__, "interface": interface.__name__, "module": module.name,
             "fps": interface.fps, "observations": list(interface.observations),
             "script": script.name if script else None, "date": time.strftime("%Y-%m-%d %H:%M:%S"),
             "timesteps": int(getattr(model, "num_timesteps", 0)), "versions": _versions()}
    (folder / RL_FILE).write_text(json.dumps(infos, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Modèle enregistré : {folder}")
    return folder


def _versions() -> dict[str, str]:
    import importlib.metadata
    versions = {}
    for paquet in ("mir_robot", "stable-baselines3", "gymnasium", "torch"):
        try:
            versions[paquet] = importlib.metadata.version(paquet)
        except importlib.metadata.PackageNotFoundError:
            versions[paquet] = "?"
    return versions


def is_rl_model(folder: str | Path) -> bool:
    folder = Path(folder)
    return (folder / RL_FILE).exists() and (folder / SB3_FILE).exists()


def rl_model_info(folder: str | Path) -> dict[str, Any]:
    infos = json.loads((Path(folder) / RL_FILE).read_text(encoding="utf-8"))
    return {"type": "rl", "kind": f"RL {infos['algorithm']}", "inputs": infos.get("observations", []), "images": [],
            "actions": [], "fps": infos.get("fps"), "date": infos.get("date", Path(folder).name),
            "dataset": None, "timesteps": infos.get("timesteps")}


def _load_interface(folder: Path, infos: dict[str, Any]) -> RobotInterface:
    """Importe la copie du fichier de l'interface rangée avec le modèle (un nom de module propre à ce dossier)."""
    fichier = folder / infos["module"]
    nom = f"mir_rl_{abs(hash(str(folder.resolve())))}_{fichier.stem}"
    spec = importlib.util.spec_from_file_location(nom, fichier)
    if spec is None or spec.loader is None:
        raise ImportError(f"impossible de charger {fichier}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    sys.path.insert(0, str(folder))         # le fichier peut importer ses voisins copiés avec lui
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(folder))
    return getattr(module, infos["interface"])()


class RLPolicy(Commande):
    """Un modèle Stable-Baselines3 qui pilote le robot : observation -> interface -> réseau -> interface -> consignes."""
    nom = "Modèle RL"
    famille = "ia"

    def __init__(self, folder: str | Path):
        super().__init__()
        import stable_baselines3
        self.folder = Path(folder)
        self.infos = json.loads((self.folder / RL_FILE).read_text(encoding="utf-8"))
        if self.infos["algorithm"] not in ALGORITHMS:
            raise ValueError(f"algorithme inconnu : {self.infos['algorithm']}")
        self.interface = _load_interface(self.folder, self.infos)
        algorithm = getattr(stable_baselines3, self.infos["algorithm"])
        self.model = algorithm.load(self.folder / SB3_FILE, device="cpu")

    def observations(self) -> list[str]:
        return list(self.interface.observations)

    def demarrer(self, robot):
        manquantes = [n for n in self.interface.observations if n not in robot.observations]
        if manquantes:
            raise ValueError(f"observations nécessaires au modèle et absentes du robot : {', '.join(manquantes)}")
        self.interface.setup({nom: action.get_range() for nom, action in robot.actions.items()})
        self.interface.reset()

    def action(self, observation):
        action, _ = self.model.predict(self.interface.observation(observation), deterministic=True)
        return self.interface.action(action)
