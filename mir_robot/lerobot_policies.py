"""
Modèles de LeRobot (ACT, Diffusion...) : les entraîner sur un dataset de MIR, puis les faire piloter le robot.

C'est le seul endroit de MIR qui utilise l'API des politiques de LeRobot : si elle change avec une nouvelle version
de LeRobot, seul ce fichier change (voir doc/architecture.md, partie 4.6).

Script d'entraînement (lancé depuis l'étape « Entraîner un modèle », avec le dataset choisi dans MIR) :

    from mir_robot.lerobot_policies import train_lerobot
    train_lerobot(policy="act", steps=5000, batch_size=8, chunk_size=20, n_action_steps=10)

L'entraînement de LeRobot tourne dans le programme du script (■ Arrêter l'interrompt vraiment) ; la courbe de loss
est tracée avec matplotlib. Le modèle est rangé, comme ceux écrits en PyTorch, dans robots/<robot>/modeles/<script>/<date>/.

Sur le robot, la préparation est celle de LeRobot (normalisation enregistrée avec le modèle) ; MIR ramène seulement
l'observation au format du dataset relu par LeRobot : image redimensionnée à la taille du dataset, réels entre 0 et 1,
C×H×W (la même chose que pour les modèles PyTorch, voir mir_robot/training.py).
"""
from __future__ import annotations
import contextlib
import json
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
import numpy as np
from mir_robot.commande import Commande
from mir_robot.donnees import ACTION, ETAT, DatasetMIR, decodeur_video

MIR_FILE = "mir.json"               # dans le dossier d'un modèle LeRobot entraîné par MIR : grandeurs, dataset, versions
PRETRAINED = Path("checkpoints") / "last" / "pretrained_model"
IMAGES_PREFIX = "observation.images."
POLICIES = ("act", "diffusion")     # modèles proposés ; SmolVLA demande une carte graphique (plus tard)
DEFAULTS = {"act": {"chunk_size": 20, "n_action_steps": 10}}


def pretrained_dir(folder: str | Path) -> Path | None:
    """Dossier des poids d'un modèle LeRobot (checkpoints/last/pretrained_model, ou le dossier lui-même)."""
    folder = Path(folder)
    for candidate in (folder / PRETRAINED, folder):
        if (candidate / "config.json").exists() and (candidate / "model.safetensors").exists():
            return candidate
    return None


def is_lerobot_model(folder: str | Path) -> bool:
    return pretrained_dir(folder) is not None


# ---------------------------------------------------------------- entraînement

def train_lerobot(policy: str = "act", steps: int = 5000, batch_size: int = 8, dataset: str | Path | None = None,
                  device: str | None = None, folder: str | Path | None = None, log_freq: int = 100,
                  plot: bool = True, **policy_options: Any) -> Path:
    """Entraîne un modèle de LeRobot (policy : "act", "diffusion"...) sur le dataset choisi dans MIR (ou dataset=...).
    policy_options : réglages du modèle, ex. chunk_size=20 (--policy.chunk_size de LeRobot). Renvoie le dossier."""
    from mir_robot.training import DATASET_ENV, MODELS_DIR, _versions, default_device
    if dataset is None:
        dataset = os.environ.get(DATASET_ENV)
        if not dataset:
            raise ValueError("aucun dataset : lancer l'entraînement depuis MIR, ou indiquer "
                             "train_lerobot(..., dataset=\"robots/<robot>/datasets/<nom>\")")
    ds = DatasetMIR(Path(dataset))
    if not ds.existe():
        raise ValueError(f"dataset introuvable : {ds.dossier}")
    script = Path(sys.argv[0]) if sys.argv and sys.argv[0].endswith(".py") else None
    if folder is None:
        folder = ds.dossier.parent.parent / MODELS_DIR / (script.stem if script else policy) / \
                 time.strftime("%Y-%m-%d_%Hh%Mm%S")
    folder = Path(folder)
    device = device or str(default_device())
    options = {**DEFAULTS.get(policy, {}), **policy_options}
    args = [f"--dataset.repo_id={ds.repo_id}", f"--dataset.root={ds.dossier.resolve()}",
            f"--dataset.video_backend={decodeur_video()}", f"--policy.type={policy}", f"--policy.device={device}",
            f"--output_dir={folder.resolve()}", f"--job_name={folder.parent.name}", f"--batch_size={batch_size}",
            f"--steps={steps}", f"--save_freq={steps}", f"--log_freq={log_freq}", "--num_workers=0",
            "--policy.push_to_hub=false", "--wandb.enable=false"]
    args += [f"--policy.{k}={str(v).lower() if isinstance(v, bool) else v}" for k, v in options.items()]
    print(f"Dataset {ds.nom} : {len(ds.episodes())} épisodes ; modèle {policy} ({options}), {steps} pas, "
          f"batch {batch_size}, calcul sur {device}")

    os.environ.setdefault("TQDM_DISABLE", "1")          # pas de barre de progression : la console de MIR suffit
    import draccus
    from lerobot.configs.train import TrainPipelineConfig
    from lerobot.scripts.lerobot_train import train
    from lerobot.utils.import_utils import register_third_party_plugins
    register_third_party_plugins()
    cfg = draccus.parse(config_class=TrainPipelineConfig, args=args)
    courbe = _LossCurve(log_freq, plot)
    logging.getLogger().addHandler(courbe)
    try:
        # LeRobot écrit son journal sur la sortie d'erreur : dans MIR, il apparaîtrait comme des erreurs
        with contextlib.redirect_stderr(sys.stdout):
            train(cfg)
    finally:
        logging.getLogger().removeHandler(courbe)

    fmt = ds.format()
    infos = {"type": "lerobot", "policy": policy, "options": options, "steps": steps, "batch_size": batch_size,
             "dataset": str(ds.dossier), "fps": ds.fps(), "state_names": fmt.etat, "action_names": fmt.actions,
             "script": script.name if script else None, "date": time.strftime("%Y-%m-%d %H:%M:%S"),
             "loss": courbe.losses, "versions": _versions()}
    (folder / MIR_FILE).write_text(json.dumps(infos, indent=2, ensure_ascii=False), encoding="utf-8")
    if script is not None and script.exists():
        shutil.copy(script, folder / script.name)
    print(f"Modèle enregistré : {folder}")
    return folder


class _LossCurve(logging.Handler):
    """Lit les lignes de journal de LeRobot (« step:1K ... loss:0.271 ... ») et trace la loss."""
    LIGNE = re.compile(r"\bloss:([0-9.eE+-]+)")

    def __init__(self, log_freq: int, plot: bool):
        super().__init__()
        self.log_freq, self.plot = log_freq, plot
        self.losses: list[float] = []

    def emit(self, record: logging.LogRecord) -> None:
        match = self.LIGNE.search(record.getMessage())
        if not match:
            return
        self.losses.append(float(match.group(1)))
        if self.plot:
            import matplotlib.pyplot as plt
            plt.figure("loss")
            plt.clf()
            plt.plot(np.arange(1, len(self.losses) + 1) * self.log_freq, self.losses, label="train")
            plt.xlabel("pas d'entraînement")
            plt.ylabel("loss")
            plt.yscale("log")
            plt.legend()
            plt.pause(0.01)


# ---------------------------------------------------------------- sur le robot

def _infos(folder: Path, pretrained: Path) -> dict[str, Any]:
    """Grandeurs du modèle : celles notées par MIR à l'entraînement, sinon celles du dataset d'entraînement."""
    mir = folder / MIR_FILE
    if mir.exists():
        return json.loads(mir.read_text(encoding="utf-8"))
    train_config = json.loads((pretrained / "train_config.json").read_text(encoding="utf-8"))
    racine = train_config["dataset"]["root"]
    fmt = DatasetMIR(Path(racine)).format()
    return {"type": "lerobot", "policy": train_config["policy"]["type"], "dataset": racine,
            "state_names": fmt.etat, "action_names": fmt.actions}


class LeRobotPolicy(Commande):
    """Un modèle de LeRobot qui pilote le robot : observation -> format du dataset -> préparation de LeRobot ->
    modèle (select_action, qui gère les séquences d'actions) -> actions."""
    nom = "Modèle LeRobot"
    famille = "ia"

    def __init__(self, folder: str | Path, device: str | None = None):
        super().__init__()
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import get_policy_class, make_pre_post_processors
        from mir_robot.training import default_device
        self.folder = Path(folder)
        pretrained = pretrained_dir(self.folder)
        if pretrained is None:
            raise ValueError(f"pas de modèle LeRobot dans {self.folder}")
        self.infos = _infos(self.folder, pretrained)
        config = PreTrainedConfig.from_pretrained(str(pretrained))
        self.device = device or str(default_device())
        self.policy = get_policy_class(config.type).from_pretrained(str(pretrained))
        self.policy.config.device = self.device
        self.policy = self.policy.to(self.device).eval()
        # préparation enregistrée avec le modèle, mais sur l'appareil de calcul de cette machine (pas celui de l'entraînement)
        self.pre, self.post = make_pre_post_processors(
            policy_cfg=self.policy.config, pretrained_path=str(pretrained),
            preprocessor_overrides={"device_processor": {"device": self.device}})
        self.state_names: list[str] = list(self.infos["state_names"])
        self.action_names: list[str] = list(self.infos["action_names"])
        # images : taille du dataset (C, H, W) ; autres entrées (lidar) : forme du tableau
        features = self.policy.config.input_features
        self.images = {k.removeprefix(IMAGES_PREFIX): tuple(f.shape) for k, f in features.items()
                       if k.startswith(IMAGES_PREFIX)}
        self.arrays = {k.removeprefix("observation."): tuple(f.shape) for k, f in features.items()
                       if k not in (ETAT,) and not k.startswith(IMAGES_PREFIX)}

    def observations(self) -> list[str]:
        """Observations du robot nécessaires au modèle."""
        return list(self.state_names) + list(self.images) + list(self.arrays)

    def demarrer(self, robot):
        manquantes = [n for n in self.observations() if n not in robot.observations]
        if manquantes:
            raise ValueError(f"observations nécessaires au modèle et absentes du robot : {', '.join(manquantes)}")
        inconnues = [n for n in self.action_names if n not in robot.actions]
        if inconnues:
            raise ValueError(f"actions du modèle inconnues du robot : {', '.join(inconnues)}")
        self.policy.reset()             # séquence d'actions en cours (ACT, Diffusion) oubliée

    def frame(self, observation: dict[str, Any]):
        """Observation du robot -> trame au format du dataset relu par LeRobot."""
        import cv2
        import torch
        frame = {}
        if self.state_names:
            frame[ETAT] = torch.tensor([float(observation[n]) for n in self.state_names], dtype=torch.float32)
        for name, (_, height, width) in self.images.items():
            image = np.ascontiguousarray(observation[name])
            if image.shape[:2] != (height, width):
                image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
            # caméra : entiers 0..255, H×W×C ; dataset relu par LeRobot : réels entre 0 et 1, C×H×W
            frame[IMAGES_PREFIX + name] = torch.from_numpy(image).permute(2, 0, 1).float() / 255.0
        for name, shape in self.arrays.items():
            frame["observation." + name] = torch.as_tensor(np.asarray(observation[name], np.float32)).reshape(shape)
        return frame

    def predict(self, observation: dict[str, Any]) -> dict[str, float]:
        import torch
        with torch.inference_mode():
            action = self.post(self.policy.select_action(self.pre(self.frame(observation))))
        action = action[ACTION] if isinstance(action, dict) else action
        return {name: float(v) for name, v in zip(self.action_names, action.squeeze(0).cpu().tolist())}

    def action(self, observation):
        return self.predict(observation)
