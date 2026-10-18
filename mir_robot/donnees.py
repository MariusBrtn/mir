"""
Datasets de démonstrations, au format LeRobot (LeRobotDataset v3.0).

C'est le seul endroit de MIR qui utilise l'API des datasets de LeRobot : si elle change avec une nouvelle version
de LeRobot, seul ce fichier change (voir doc/architecture.md, partie 4.6).

Correspondance entre les grandeurs de MIR et les colonnes du dataset (comme le script de collecte d'origine) :
  positions, vitesses... (nombres)   -> "observation.state"           vecteur, noms = noms MIR ("joint_1.position")
  caméra "cam_1"                      -> "observation.images.cam_1"    vidéo
  lidar "lidar_1"                     -> "observation.lidar_1"         tableau (points, 2) : [angle °, distance cm]
  consignes de la téléopération       -> "action"                      vecteur, noms = noms MIR ("joint_1.position")
Les conditions d'enregistrement (réel ou simulé, scène, téléopération, versions) sont dans meta/mir.json.
"""
from __future__ import annotations
import importlib.metadata
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import numpy as np
from mir_devices.mir_device import (ObservableProperty, ObservablePropertyBitmap, ObservablePropertyFloat,
                                    ObservablePropertyPolar)

ETAT = "observation.state"
ACTION = "action"
TACHE = "task"
CODEC_VIDEO = "h264"
FICHIER_MIR = "mir.json"


def cle_image(nom: str) -> str:
    return f"observation.images.{nom}"


def cle_tableau(nom: str) -> str:
    return f"observation.{nom}"


def _version(paquet: str) -> str:
    try:
        return importlib.metadata.version(paquet)
    except importlib.metadata.PackageNotFoundError:
        return "?"


@dataclass
class FormatDataset:
    """Ce qu'enregistre un dataset : les grandeurs choisies du robot et les consignes de la téléopération."""
    etat: list[str] = field(default_factory=list)                         # nombres -> observation.state
    images: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # caméra -> (hauteur, largeur, 3)
    tableaux: dict[str, tuple[int, ...]] = field(default_factory=dict)      # lidar -> (points, 2)
    actions: list[str] = field(default_factory=list)

    @staticmethod
    def depuis_robot(observables: dict[str, ObservableProperty], observations: list[str],
                     actions: list[str]) -> FormatDataset:
        """Format à partir des grandeurs choisies (dans l'ordre des observables du robot)."""
        fmt = FormatDataset(actions=list(actions))
        for nom, prop in observables.items():
            if nom not in observations:
                continue
            if isinstance(prop, ObservablePropertyBitmap):
                fmt.images[nom] = tuple(int(v) for v in prop.stype)
            elif isinstance(prop, ObservablePropertyPolar):
                fmt.tableaux[nom] = tuple(int(v) for v in prop.stype)
            elif isinstance(prop, ObservablePropertyFloat):
                fmt.etat.append(nom)
        return fmt

    @staticmethod
    def depuis_features(features: dict[str, Any]) -> FormatDataset:
        fmt = FormatDataset()
        for cle, f in features.items():
            if cle == ETAT:
                fmt.etat = list(f["names"])
            elif cle == ACTION:
                fmt.actions = list(f["names"])
            elif cle.startswith("observation.images."):
                fmt.images[cle.removeprefix("observation.images.")] = tuple(f["shape"])
            elif cle.startswith("observation.") and f.get("dtype") == "float32":
                fmt.tableaux[cle.removeprefix("observation.")] = tuple(f["shape"])
        return fmt

    def features(self) -> dict[str, Any]:
        """Colonnes du dataset LeRobot."""
        features: dict[str, Any] = {}
        if self.etat:
            features[ETAT] = {"dtype": "float32", "shape": (len(self.etat),), "names": list(self.etat)}
        for nom, forme in self.images.items():
            features[cle_image(nom)] = {"dtype": "video", "shape": forme, "names": ["height", "width", "channels"]}
        for nom, forme in self.tableaux.items():
            features[cle_tableau(nom)] = {"dtype": "float32", "shape": forme, "names": None}
        features[ACTION] = {"dtype": "float32", "shape": (len(self.actions),), "names": list(self.actions)}
        return features

    def trame(self, observation: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        """Une trame du dataset à partir d'une observation du robot et de l'action envoyée."""
        trame: dict[str, Any] = {}
        if self.etat:
            trame[ETAT] = np.array([observation[nom] for nom in self.etat], dtype=np.float32)
        for nom in self.images:
            trame[cle_image(nom)] = np.ascontiguousarray(observation[nom], dtype=np.uint8)
        for nom, forme in self.tableaux.items():
            trame[cle_tableau(nom)] = np.asarray(observation[nom], dtype=np.float32).reshape(forme)
        trame[ACTION] = np.array([float(action.get(nom, np.nan)) for nom in self.actions], dtype=np.float32)
        return trame


@dataclass
class Episode:
    index: int
    trames: int
    duree_s: float
    tache: str
    conditions: dict[str, Any] = field(default_factory=dict)


class DatasetMIR:
    """Un dataset de démonstrations rangé dans un dossier (robots/<robot>/datasets/<nom>)."""

    def __init__(self, dossier: str | Path):
        self.dossier = Path(dossier)

    @property
    def nom(self) -> str:
        return self.dossier.name

    @property
    def repo_id(self) -> str:
        return f"local/{self.nom}"

    def existe(self) -> bool:
        return (self.dossier / "meta" / "info.json").exists()

    # ------------------------------------------------------------------ lecture
    def info(self) -> dict[str, Any]:
        return json.loads((self.dossier / "meta" / "info.json").read_text())

    def fps(self) -> int:
        return int(self.info()["fps"])

    def format(self) -> FormatDataset:
        return FormatDataset.depuis_features(self.info()["features"])

    def _mir(self) -> dict[str, Any]:
        chemin = self.dossier / "meta" / FICHIER_MIR
        return json.loads(chemin.read_text()) if chemin.exists() else {"episodes": []}

    def _ecrire_mir(self, mir: dict[str, Any]) -> None:
        (self.dossier / "meta" / FICHIER_MIR).write_text(json.dumps(mir, indent=2, ensure_ascii=False))

    def episodes(self) -> list[Episode]:
        if not self.existe():
            return []
        from lerobot.datasets import LeRobotDatasetMetadata
        meta = LeRobotDatasetMetadata(self.repo_id, root=self.dossier)
        conditions = self._mir()["episodes"]
        fps = meta.fps
        result = []
        for i in range(meta.total_episodes):
            ep = meta.episodes[i]
            taches = ep.get("tasks") or [""]
            result.append(Episode(i, int(ep["length"]), int(ep["length"]) / fps, str(taches[0]),
                                  conditions[i] if i < len(conditions) else {}))
        return result

    def charger_episode(self, index: int) -> dict[str, Any]:
        """Les données d'un épisode, pour l'afficher : {"t", "etat", "actions", "images": {cam: [H x W x 3]},
        "tableaux": {lidar: [...]}} (tableaux numpy, images décodées des vidéos)."""
        from lerobot.datasets import LeRobotDataset
        ds = LeRobotDataset(self.repo_id, root=self.dossier, episodes=[index])
        fmt = self.format()
        t, etat, actions = [], [], []
        images: dict[str, list[np.ndarray]] = {nom: [] for nom in fmt.images}
        tableaux: dict[str, list[np.ndarray]] = {nom: [] for nom in fmt.tableaux}
        for k in range(len(ds)):
            item = ds[k]
            t.append(float(item["timestamp"]))
            if fmt.etat:
                etat.append(item[ETAT].numpy())
            actions.append(item[ACTION].numpy())
            for nom in fmt.images:
                # image décodée : C x H x W, réels entre 0 et 1
                images[nom].append((item[cle_image(nom)].numpy().transpose(1, 2, 0) * 255).astype(np.uint8))
            for nom in fmt.tableaux:
                tableaux[nom].append(item[cle_tableau(nom)].numpy())
        return {"t": np.array(t), "etat": np.array(etat), "actions": np.array(actions), "images": images,
                "tableaux": tableaux, "format": fmt}

    # ------------------------------------------------------------------ écriture
    def ajouter_episode(self, fmt: FormatDataset, fps: int, trames: list[dict[str, Any]], tache: str,
                        conditions: dict[str, Any] | None = None, robot_type: str = "mir_robot") -> int:
        """Ajoute un épisode (crée le dataset s'il n'existe pas). Renvoie son index.
        Le dataset est fermé après chaque épisode : il reste valide même si l'application est fermée ensuite."""
        from lerobot.datasets import LeRobotDataset
        if not trames:
            raise ValueError("épisode vide")
        if self.existe():
            if self.fps() != fps:
                raise ValueError(f"le dataset {self.nom} est enregistré à {self.fps()} Hz, pas à {fps} Hz")
            if self.format() != fmt:
                raise ValueError(f"le dataset {self.nom} n'enregistre pas les mêmes grandeurs : créez un autre dataset")
            ds = LeRobotDataset.resume(self.repo_id, root=self.dossier, vcodec=CODEC_VIDEO)
        else:
            self.dossier.parent.mkdir(parents=True, exist_ok=True)
            ds = LeRobotDataset.create(self.repo_id, fps=fps, features=fmt.features(), root=self.dossier,
                                       robot_type=robot_type, vcodec=CODEC_VIDEO)
        try:
            for trame in trames:
                ds.add_frame({**trame, TACHE: tache})
            ds.save_episode()
        finally:
            ds.finalize()
        mir = self._mir()
        mir.update({"version_mir": _version("mir_robot"), "version_lerobot": _version("lerobot")})
        mir["episodes"].append({**(conditions or {}), "date": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "version_lerobot": _version("lerobot")})
        self._ecrire_mir(mir)
        return len(mir["episodes"]) - 1

    def supprimer_episodes(self, indices: list[int]) -> None:
        """Supprime des épisodes ; le dernier épisode supprimé emporte tout le dataset."""
        from lerobot.datasets import LeRobotDataset
        from lerobot.datasets.dataset_tools import delete_episodes
        total = len(self.episodes())
        if set(range(total)) <= set(indices):
            shutil.rmtree(self.dossier)
            return
        temporaire = self.dossier.with_name(f"_{self.nom}_modifie")
        if temporaire.exists():
            shutil.rmtree(temporaire)
        mir = self._mir()
        delete_episodes(LeRobotDataset(self.repo_id, root=self.dossier), sorted(indices), output_dir=temporaire,
                        repo_id=self.repo_id)
        ancien = self.dossier.with_name(f"_{self.nom}_ancien")
        self.dossier.rename(ancien)
        temporaire.rename(self.dossier)
        shutil.rmtree(ancien)
        mir["episodes"] = [c for i, c in enumerate(mir["episodes"]) if i not in indices]
        self._ecrire_mir(mir)


def episode_depuis_trames(fmt: FormatDataset, fps: int, trames: list[dict[str, Any]]) -> dict[str, Any]:
    """Un épisode pas encore enregistré, sous la même forme que DatasetMIR.charger_episode (pour le revoir)."""
    return {"t": np.arange(len(trames)) / fps,
            "etat": np.array([tr[ETAT] for tr in trames]) if fmt.etat else np.zeros((len(trames), 0)),
            "actions": np.array([tr[ACTION] for tr in trames]),
            "images": {nom: [tr[cle_image(nom)] for tr in trames] for nom in fmt.images},
            "tableaux": {nom: [tr[cle_tableau(nom)] for tr in trames] for nom in fmt.tableaux},
            "format": fmt}


def datasets_du_robot(dossier_robot: str | Path) -> list[DatasetMIR]:
    dossier = Path(dossier_robot) / "datasets"
    if not dossier.is_dir():
        return []
    return [DatasetMIR(d) for d in sorted(dossier.iterdir()) if d.is_dir() and not d.name.startswith("_")]
