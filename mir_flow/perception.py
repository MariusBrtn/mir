"""
Perception : transformer les observations brutes du robot (points du lidar, images des caméras) en quelques
informations simples, faciles à utiliser dans une condition ou par un LLM.

Fonctions pures (sans robot), testables sur des données enregistrées ou fabriquées.
"""
from __future__ import annotations
import threading
from pathlib import Path
from typing import Any
import numpy as np


# ---------------------------------------------------------------------- détection d'objets (MediaPipe)
# les 80 objets que reconnaît le modèle (jeu de données COCO), dans l'ordre de son fichier labels.txt
COCO_LABELS = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant",
    "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
    "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli",
    "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed", "dining table", "toilet",
    "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
]


def unknown_labels(classes: list[str]) -> list[str]:
    """Noms d'objets que le modèle ne connaît pas (fautes de frappe), avec une suggestion."""
    import difflib
    unknown = []
    for name in (c.strip() for c in classes):
        if name and name.lower() not in COCO_LABELS:
            close = difflib.get_close_matches(name.lower(), COCO_LABELS, n=1)
            unknown.append(f"« {name} »" + (f" (vouliez-vous dire « {close[0]} » ?)" if close else ""))
    return unknown

MODELS_DIR = Path.home() / ".cache" / "mir" / "models"
DETECTOR_URL = ("https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/latest/"
                "efficientdet_lite0.tflite")


def detector_model() -> Path:
    """Le modèle EfficientDet-Lite0 (MediaPipe, Google, licence Apache-2.0), téléchargé la première fois (7 Mo)."""
    path = MODELS_DIR / "efficientdet_lite0.tflite"
    if not path.exists():
        import urllib.request
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        try:
            urllib.request.urlretrieve(DETECTOR_URL, partial)
        except Exception as e:
            raise RuntimeError(f"téléchargement du modèle de vision impossible (connexion à internet ?) : {e}") from None
        partial.rename(path)
    return path


class ObjectDetector:
    """Détecteur d'objets courants (80 catégories COCO : person, sports ball, cup…) sur des images RGB."""

    def __init__(self, score_min: float = 0.5, max_results: int = 10):
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import ObjectDetector as MPDetector, ObjectDetectorOptions
        options = ObjectDetectorOptions(base_options=BaseOptions(model_asset_path=str(detector_model())),
                                        score_threshold=score_min, max_results=max_results)
        self._detector = MPDetector.create_from_options(options)
        self._lock = threading.Lock()

    def detect(self, image: np.ndarray, classes: list[str] | None = None) -> list[dict[str, Any]]:
        import mediapipe as mp
        frame = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(image, dtype=np.uint8))
        with self._lock:
            result = self._detector.detect(frame)
        wanted = {c.strip().lower() for c in classes or [] if c.strip()}
        detections = []
        for d in result.detections:
            category = d.categories[0]
            name = category.category_name or ""
            if wanted and name.lower() not in wanted:
                continue
            box = d.bounding_box
            detections.append({"classe": name, "score": round(float(category.score), 2), "x": int(box.origin_x),
                               "y": int(box.origin_y), "largeur": int(box.width), "hauteur": int(box.height)})
        return detections

    def close(self):
        """À appeler à la fin : MediaPipe libère ses fils (sinon le programme peut rester bloqué en quittant)."""
        with self._lock:
            self._detector.close()


def close_detectors(detectors: dict) -> None:
    for detector in detectors.values():
        try:
            detector.close()
        except Exception:
            pass
    detectors.clear()
