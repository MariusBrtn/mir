"""
Entraîner un modèle écrit en PyTorch (behavior cloning) sur un dataset de MIR, puis le faire piloter le robot.

Le script de l'élève est un script PyTorch ordinaire ; MIR fournit les données préparées et l'enregistrement :

    from mir_robot.training import load_data, save_model

    data = load_data(inputs=["state", "cam_1"], image_size=(224, 224))   # dataset choisi dans MIR
    model = Policy(data.n_state, data.n_actions).to(data.device)
    for epoch in range(20):
        for batch in data.train_loader:          # {"state": B×n, "cam_1": B×3×224×224, "action": B×m}
            loss = nn.functional.mse_loss(model(batch), batch["action"])
            ...
        print(epoch, data.evaluate(model))       # perte sur les épisodes de validation
    save_model(model, data)                      # -> Piloter, IA

Toute la préparation des données est faite par MIR, à l'entraînement comme sur le robot, avec la même fonction
(Preparation.prepare) et les mêmes statistiques, enregistrées avec le modèle (fiche de préparation) :
  images : réels entre 0 et 1, C×H×W, redimensionnées à image_size, standardisées avec les statistiques d'ImageNet ;
  état, actions et autres grandeurs (lidar) : standardisés avec les statistiques du dataset ((x - moyenne) / écart-type) ;
  sur le robot, les actions prédites sont ramenées dans les unités du robot avant d'être envoyées.

Le modèle est enregistré avec torch.export : il se recharge sans le script qui l'a défini.
"""
from __future__ import annotations
import copy
import json
import os
import random
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import numpy as np
import torch
from torch.nn import functional as F
from mir_robot.commande import Commande
from mir_robot.donnees import ACTION, ETAT, DatasetMIR, FormatDataset, cle_image, cle_tableau, decodeur_video

DATASET_ENV = "MIR_DATASET"         # dataset choisi dans MIR, transmis au script d'entraînement
STATE = "state"                     # nom de l'état (angles...) parmi les entrées d'un modèle
MODELS_DIR = "modeles"              # dans le dossier du robot : scripts des modèles et modèles entraînés
MODEL_FILE = "model.pt2"
PREPARATION_FILE = "preparation.json"
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
MIN_STD = 1e-6                      # grandeur constante dans le dataset : pas de division par 0


# ---------------------------------------------------------------- fiche de préparation

@dataclass
class Preparation:
    """Fiche de préparation : passage des données brutes aux tenseurs du réseau, et des sorties aux actions.
    Calculée à partir du dataset, enregistrée avec le modèle, appliquée à l'entraînement et sur le robot."""
    inputs: list[str]                           # entrées du réseau : "state", caméras, autres grandeurs
    images: list[str]                           # caméras parmi les entrées
    image_size: tuple[int, int] | None          # (hauteur, largeur) ; None : taille d'origine
    state_names: list[str]                      # grandeurs du vecteur d'état, dans l'ordre (ex. "joint_1.position")
    action_names: list[str]                     # actions prédites, dans l'ordre
    shapes: dict[str, tuple[int, ...]]          # forme brute de chaque entrée (sans la dimension du batch)
    stats: dict[str, dict[str, list]] = field(default_factory=dict)   # entrée ou "action" -> mean, std

    def prepare(self, raw: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        """Batch brut au format du dataset (images réelles entre 0 et 1, B×C×H×W) -> batch donné au réseau."""
        batch = {}
        for name in self.inputs:
            x = raw[name].float()
            if name in self.images:
                if self.image_size is not None and tuple(x.shape[-2:]) != tuple(self.image_size):
                    x = F.interpolate(x, size=tuple(self.image_size), mode="bilinear", antialias=True,
                                      align_corners=False)
                mean = torch.tensor(IMAGENET_MEAN, device=x.device).view(1, 3, 1, 1)
                std = torch.tensor(IMAGENET_STD, device=x.device).view(1, 3, 1, 1)
                x = (x - mean) / std
            else:
                x = self._standardize(name, x)
            batch[name] = x
        return batch

    def normalize_action(self, action: torch.Tensor) -> torch.Tensor:
        return self._standardize(ACTION, action)

    def denormalize_action(self, action: torch.Tensor) -> torch.Tensor:
        mean, std = self._mean_std(ACTION, action)
        return action * std + mean

    def _standardize(self, name: str, x: torch.Tensor) -> torch.Tensor:
        mean, std = self._mean_std(name, x)
        return (x - mean) / std

    def _mean_std(self, name: str, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        s = self.stats[name]
        mean = torch.tensor(s["mean"], dtype=x.dtype, device=x.device)
        std = torch.tensor(s["std"], dtype=x.dtype, device=x.device).clamp_min(MIN_STD)
        return mean, std

    def raw_from_observation(self, observation: dict[str, Any]) -> dict[str, torch.Tensor]:
        """Observation du robot -> batch brut de taille 1, au format du dataset (comme le relit LeRobot)."""
        raw = {}
        for name in self.inputs:
            if name == STATE:
                raw[name] = torch.tensor([[float(observation[n]) for n in self.state_names]])
            elif name in self.images:
                # caméra : entiers 0..255, H×W×C ; dataset relu par LeRobot : réels entre 0 et 1, C×H×W
                image = torch.from_numpy(np.ascontiguousarray(observation[name]))
                raw[name] = (image.permute(2, 0, 1).float() / 255.0).unsqueeze(0)
            else:
                raw[name] = torch.as_tensor(np.asarray(observation[name], dtype=np.float32)).reshape(
                    1, *self.shapes[name])
        return raw

    def observations(self) -> list[str]:
        """Observations du robot nécessaires au modèle."""
        return [n for name in self.inputs for n in (self.state_names if name == STATE else [name])]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> Preparation:
        d = dict(d)
        d["image_size"] = tuple(d["image_size"]) if d.get("image_size") else None
        d["shapes"] = {k: tuple(v) for k, v in d["shapes"].items()}
        return Preparation(**d)


def _dataset_key(name: str, fmt: FormatDataset) -> str:
    """Nom d'une entrée du modèle ("state", "cam_1", "lidar_1") -> colonne du dataset LeRobot."""
    if name == STATE and fmt.etat:
        return ETAT
    if name in fmt.images:
        return cle_image(name)
    if name in fmt.tableaux:
        return cle_tableau(name)
    possibles = ([STATE] if fmt.etat else []) + list(fmt.images) + list(fmt.tableaux)
    raise ValueError(f"entrée inconnue : '{name}'. Entrées possibles avec ce dataset : {', '.join(possibles)}")


# ---------------------------------------------------------------- données d'entraînement

class _Frames(torch.utils.data.Dataset):
    """Trames d'un LeRobotDataset, réduites aux colonnes utiles et renommées avec les noms des entrées."""

    def __init__(self, lerobot_dataset, keys: dict[str, str]):
        self.ds = lerobot_dataset
        self.keys = keys            # nom de l'entrée (ou "action") -> colonne du dataset

    def __len__(self):
        return len(self.ds)

    def __getitem__(self, i):
        item = self.ds[i]
        return {name: item[key] for name, key in self.keys.items()}


class PreparedLoader:
    """Batches préparés par MIR, sur l'appareil de calcul : {"state": ..., "cam_1": ..., "action": ...}."""

    def __init__(self, loader: torch.utils.data.DataLoader, preparation: Preparation, device: torch.device):
        self._loader = loader
        self._preparation = preparation
        self._device = device

    def __len__(self):
        return len(self._loader)

    def __iter__(self):
        for raw in self._loader:
            batch = self._preparation.prepare(raw)
            batch[ACTION] = self._preparation.normalize_action(raw[ACTION].float())
            yield {name: x.to(self._device) for name, x in batch.items()}


class TrainingData:
    """Ce que load_data fournit au script d'entraînement."""

    def __init__(self, dataset: DatasetMIR, preparation: Preparation, train_loader: PreparedLoader,
                 val_loader: PreparedLoader | None, train_episodes: list[int], val_episodes: list[int],
                 device: torch.device):
        self.dataset = dataset
        self.preparation = preparation
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.train_episodes = train_episodes
        self.val_episodes = val_episodes
        self.device = device

    @property
    def n_state(self) -> int:
        return len(self.preparation.state_names)

    @property
    def n_actions(self) -> int:
        return len(self.preparation.action_names)

    @property
    def shapes(self) -> dict[str, tuple[int, ...]]:
        """Forme de chaque entrée telle que le réseau la reçoit (sans la dimension du batch)."""
        p = self.preparation
        return {name: (3, *p.image_size) if name in p.images and p.image_size else p.shapes[name]
                for name in p.inputs}

    def evaluate(self, model: torch.nn.Module) -> float:
        """Perte quadratique moyenne (MSE) du modèle sur les épisodes de validation, actions normalisées.
        nan s'il n'y a pas d'épisode de validation (dataset d'un seul épisode)."""
        if self.val_loader is None:
            return float("nan")
        was_training = model.training
        model.eval()
        total, count = 0.0, 0
        with torch.no_grad():
            for batch in self.val_loader:
                total += F.mse_loss(model(batch), batch[ACTION], reduction="sum").item()
                count += batch[ACTION].numel()
        model.train(was_training)
        return total / max(count, 1)


def default_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_data(inputs: list[str], image_size: tuple[int, int] | None = None, dataset: str | Path | None = None,
              batch_size: int = 32, val_ratio: float = 0.2, device: str | torch.device | None = None,
              seed: int = 0) -> TrainingData:
    """Données d'entraînement préparées par MIR.
    inputs : entrées du réseau, "state" (vecteur des grandeurs enregistrées) et/ou noms des caméras et capteurs ;
    image_size : (hauteur, largeur) des images données au réseau ; dataset : dossier du dataset (par défaut,
    celui choisi dans MIR) ; val_ratio : part des épisodes gardés pour la validation (épisodes entiers)."""
    from lerobot.datasets import LeRobotDataset
    if dataset is None:
        dataset = os.environ.get(DATASET_ENV)
        if not dataset:
            raise ValueError("aucun dataset : lancer l'entraînement depuis MIR, ou indiquer "
                             "load_data(..., dataset=\"robots/<robot>/datasets/<nom>\")")
    ds = DatasetMIR(Path(dataset))
    if not ds.existe():
        raise ValueError(f"dataset introuvable : {ds.dossier}")
    if not inputs:
        raise ValueError("aucune entrée : par exemple inputs=[\"state\"]")
    fmt = ds.format()
    keys = {name: _dataset_key(name, fmt) for name in inputs}
    keys[ACTION] = ACTION

    # séparation par épisodes entiers : des trames voisines d'un même épisode ne sont pas dans les deux parts
    episodes = list(range(len(ds.episodes())))
    n_val = max(1, round(len(episodes) * val_ratio)) if len(episodes) >= 2 else 0
    val_episodes = sorted(random.Random(seed).sample(episodes, n_val))
    train_episodes = [e for e in episodes if e not in val_episodes]

    stats = LeRobotDataset(ds.repo_id, root=ds.dossier, video_backend=decodeur_video()).meta.stats
    images = [name for name in inputs if name in fmt.images]
    preparation = Preparation(
        inputs=list(inputs), images=images, image_size=tuple(image_size) if image_size else None,
        state_names=list(fmt.etat), action_names=list(fmt.actions),
        shapes={name: tuple(fmt.images[name][2:] + fmt.images[name][:2]) if name in images
                else (len(fmt.etat),) if name == STATE else tuple(fmt.tableaux[name]) for name in inputs},
        stats={name: {"mean": np.asarray(stats[key]["mean"]).tolist(), "std": np.asarray(stats[key]["std"]).tolist()}
               for name, key in keys.items() if name not in images})

    device = torch.device(device) if device is not None else default_device()

    def loader(eps: list[int], shuffle: bool) -> PreparedLoader:
        lerobot_ds = LeRobotDataset(ds.repo_id, root=ds.dossier, episodes=eps, video_backend=decodeur_video())
        torch_loader = torch.utils.data.DataLoader(_Frames(lerobot_ds, keys), batch_size=batch_size, shuffle=shuffle,
                                                   generator=torch.Generator().manual_seed(seed))
        return PreparedLoader(torch_loader, preparation, device)

    data = TrainingData(ds, preparation, loader(train_episodes, True), loader(val_episodes, False) if val_episodes
                        else None, train_episodes, val_episodes, device)
    print(f"Dataset {ds.nom} : {len(train_episodes)} épisodes d'entraînement, {len(val_episodes)} de validation ; "
          f"entrées {data.shapes}, {data.n_actions} actions ; calcul sur {device}")
    return data


# ---------------------------------------------------------------- enregistrement

def save_model(model: torch.nn.Module, data: TrainingData, folder: str | Path | None = None) -> Path:
    """Enregistre le modèle avec sa fiche de préparation et une copie du script ; renvoie le dossier.
    Par défaut : robots/<robot>/modeles/<nom du script>/<date>/, proposé ensuite dans Piloter, IA."""
    script = Path(sys.argv[0]) if sys.argv and sys.argv[0].endswith(".py") else None
    if folder is None:
        robot_dir = data.dataset.dossier.parent.parent           # robots/<robot>/datasets/<nom>
        folder = robot_dir / MODELS_DIR / (script.stem if script else "modele") / time.strftime("%Y-%m-%d_%Hh%Mm%S")
    folder = Path(folder)

    # exemple d'entrée pour torch.export : une trame préparée, sur le processeur
    loader = data.val_loader or data.train_loader
    example = {name: x[:1].cpu() for name, x in next(iter(loader)).items() if name != ACTION}
    exportable = copy.deepcopy(model).cpu().eval()
    try:
        with torch.no_grad():
            exported = torch.export.export(exportable, (example,))
    except Exception as e:
        raise ValueError(f"le modèle ne peut pas être enregistré (torch.export) : {type(e).__name__} : {e}\n"
                         "Le plus souvent : un if qui dépend des valeurs d'un tenseur dans forward().") from e

    folder.mkdir(parents=True, exist_ok=True)
    torch.export.save(exported, folder / MODEL_FILE)
    infos = {"preparation": data.preparation.to_dict(),
             "dataset": str(data.dataset.dossier), "fps": data.dataset.fps(),
             "train_episodes": data.train_episodes, "val_episodes": data.val_episodes,
             "model_class": type(model).__name__, "script": script.name if script else None,
             "date": time.strftime("%Y-%m-%d %H:%M:%S"), "versions": _versions()}
    (folder / PREPARATION_FILE).write_text(json.dumps(infos, indent=2, ensure_ascii=False), encoding="utf-8")
    if script is not None and script.exists():
        shutil.copy(script, folder / script.name)
    print(f"Modèle enregistré : {folder}")
    return folder


def _versions() -> dict[str, str]:
    import importlib.metadata
    versions = {}
    for paquet in ("mir_robot", "lerobot", "torch"):
        try:
            versions[paquet] = importlib.metadata.version(paquet)
        except importlib.metadata.PackageNotFoundError:
            versions[paquet] = "?"
    return versions


# ---------------------------------------------------------------- sur le robot

def trained_models(robot_dir: str | Path) -> list[Path]:
    """Modèles entraînés d'un robot (dossiers robots/<robot>/modeles/<script>/<date>), écrits en PyTorch (save_model)
    ou de LeRobot (train_lerobot), du plus récent au plus ancien."""
    from mir_robot.lerobot_policies import is_lerobot_model
    root = Path(robot_dir) / MODELS_DIR
    if not root.is_dir():
        return []
    dossiers = [d for d in root.glob("*/*") if d.is_dir() and ((d / MODEL_FILE).exists() or is_lerobot_model(d))]
    return sorted(dossiers, key=lambda d: d.stat().st_mtime, reverse=True)


def model_info(folder: str | Path) -> dict[str, Any]:
    """Ce qu'on sait d'un modèle entraîné : type ("pytorch" ou "lerobot"), script, date, dataset, entrées, actions."""
    from mir_robot.lerobot_policies import _infos, is_lerobot_model, pretrained_dir
    folder = Path(folder)
    info: dict[str, Any] = {"name": folder.parent.name, "date": folder.name, "folder": str(folder)}
    try:
        if (folder / MODEL_FILE).exists():
            infos = json.loads((folder / PREPARATION_FILE).read_text(encoding="utf-8"))
            prep = infos["preparation"]
            info.update(type="pytorch", kind="PyTorch", dataset=infos.get("dataset"), inputs=prep["inputs"],
                        actions=prep["action_names"], date=infos.get("date", folder.name))
        elif is_lerobot_model(folder):
            infos = _infos(folder, pretrained_dir(folder))     # noté par MIR, sinon lu dans le dataset d'origine
            config = json.loads((pretrained_dir(folder) / "config.json").read_text(encoding="utf-8"))
            entrees = [k.removeprefix("observation.images.").removeprefix("observation.")
                       for k in config.get("input_features", {})]
            info.update(type="lerobot", kind=f"LeRobot {config.get('type', '').upper()}", dataset=infos.get("dataset"),
                        inputs=entrees, actions=infos.get("action_names", []), date=infos.get("date", folder.name))
    except (OSError, ValueError, KeyError) as e:
        info["error"] = str(e)
    return info


def load_policy(folder: str | Path) -> Commande:
    """Modèle entraîné prêt à piloter le robot (une Commande), qu'il soit écrit en PyTorch ou de LeRobot."""
    from mir_robot.lerobot_policies import LeRobotPolicy, is_lerobot_model
    folder = Path(folder)
    if (folder / MODEL_FILE).exists():
        return TrainedPolicy(folder)
    if is_lerobot_model(folder):
        return LeRobotPolicy(folder)
    raise ValueError(f"pas de modèle entraîné dans {folder}")


class TrainedPolicy(Commande):
    """Un modèle entraîné qui pilote le robot : observation -> fiche de préparation -> réseau -> actions."""
    nom = "Modèle entraîné"
    famille = "ia"

    def __init__(self, folder: str | Path):
        super().__init__()
        self.folder = Path(folder)
        infos = json.loads((self.folder / PREPARATION_FILE).read_text(encoding="utf-8"))
        self.infos = infos
        self.preparation = Preparation.from_dict(infos["preparation"])
        self.model = torch.export.load(self.folder / MODEL_FILE).module()

    def observations(self) -> list[str]:
        """Observations du robot nécessaires au modèle."""
        return self.preparation.observations()

    def demarrer(self, robot):
        manquantes = [n for n in self.preparation.observations() if n not in robot.observations]
        if manquantes:
            raise ValueError(f"observations nécessaires au modèle et absentes du robot : {', '.join(manquantes)}")
        inconnues = [n for n in self.preparation.action_names if n not in robot.actions]
        if inconnues:
            raise ValueError(f"actions du modèle inconnues du robot : {', '.join(inconnues)}")

    def predict(self, observation: dict[str, Any]) -> dict[str, float]:
        with torch.no_grad():
            output = self.model(self.preparation.prepare(self.preparation.raw_from_observation(observation)))
            values = self.preparation.denormalize_action(output)[0]
        return {name: float(v) for name, v in zip(self.preparation.action_names, values)}

    def action(self, observation):
        return self.predict(observation)
