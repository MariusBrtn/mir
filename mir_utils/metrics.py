import threading
import math
import numpy as np
import io
import zipfile
from typing import Any
import json
from pathlib import Path
import time

#moyenne glissante
class SimpleMovingAverage:
    def __init__(self, window_size: int):
        if window_size <= 0:
            raise ValueError("window_size must be > 0")

        self.window_size = window_size
        self.buffer = [0.0] * window_size
        self.index = 0
        self.count = 0
        self.sum = 0.0

        self._lock = threading.Lock()

    def add(self, value: float):
        with self._lock:
            # Retirer l’ancienne valeur si la fenêtre est pleine
            if self.count == self.window_size:
                old = self.buffer[self.index]
                self.sum -= old
            else:
                self.count += 1

            # Ajouter la nouvelle valeur
            self.buffer[self.index] = value
            self.sum += value

            # Avancer l’index circulaire
            self.index = (self.index + 1) % self.window_size

    def average(self) -> float:
        with self._lock:
            if self.count == 0:
                return 0.0
            return self.sum / self.count

#classe de statistiques qui met à jour à chaque ajout de valeur (add) :
#min, max, moyenne, ecart-type, total échantillons
#les données statistiques sont fournies sous forme de dictionnaire (get)
class Stats:
    """
    Accumulateur statistique temps réel, thread-safe.
    Calcule min, max, moyenne, variance, écart-type en O(1).
    Peut ignorer les N premières valeurs ajoutées.
    """
    def __init__(self, num_values_to_ignore=0):
        self._ignore_left = num_values_to_ignore

        self._count = 0
        self._sum = 0.0
        self._sum_sq = 0.0
        self._min = float('inf')
        self._max = float('-inf')

        self._lock = threading.Lock()

    def add(self, value: float):
        """Ajoute une valeur et met à jour les stats en O(1)."""
        with self._lock:

            # Phase d'ignorés
            if self._ignore_left > 0:
                self._ignore_left -= 1
                return

            # Phase normale
            self._count += 1
            self._sum += value
            self._sum_sq += value * value

            if value < self._min:
                self._min = value
            if value > self._max:
                self._max = value

    def reset(self):
        """Réinitialise toutes les statistiques."""
        with self._lock:
            self._count = 0
            self._sum = 0.0
            self._sum_sq = 0.0
            self._min = float('inf')
            self._max = float('-inf')
            # On ne réinitialise PAS _ignore_left volontairement
            # (comportement classique). Si tu veux le réinitialiser,
            # je peux te faire une version alternative.

    def get(self):
        """
        Retourne un dictionnaire :
        - count
        - min
        - max
        - mean
        - variance
        - std
        """
        with self._lock:
            if self._count == 0:
                return {
                    "count": 0,
                    "min": 0,
                    "max": 0,
                    "mean": 0,
                    "variance": 0,
                    "std": 0
                }

            mean = self._sum / self._count
            variance = (self._sum_sq / self._count) - (mean * mean)
            variance = max(variance, 0.0)  # protection flottants

            return {
                "count": self._count,
                "min": self._min,
                "max": self._max,
                "mean": mean,
                "variance": variance,
                "std": math.sqrt(variance)
            }

#tableau de données rempli par la droite
#utilisable pour une vue à la façon d'un oscilloscope en mode rolling
class RollingArray:
    def __init__(self, size=1000):
        self._buffer = np.zeros(size)
        self._end_index = size-1
        self._samples_count = 0
        self._lock = threading.Lock()

    def add(self, value):
        with self._lock:
            self._buffer[0:self._end_index] = self._buffer[1:]
            self._buffer[self._end_index] = value
            if self._samples_count < self._buffer.size:
                self._samples_count += 1

    def get_array(self):
        with self._lock:
            return self._samples_count, self._buffer.copy()


class DataRecorder:
    def __init__(self, observables: dict[str, dict[str, Any]], capacity: int):
        self._observables = {
            name: prop 
            for name, prop 
            in observables.items() 
            if prop["type"] == "float"
        }
        self._capacity = capacity
        

        self._data: dict[str, np.ndarray] = {
            name: np.empty(capacity, dtype=prop["dtype"]) 
            for name, prop in self._observables.items()
        }
        timestamps: np.ndarray = np.empty(capacity, dtype=np.float64)
        self._data["__timestamps__"] = timestamps
        self.start()
    
    def start(self):
        self._start_time = time.perf_counter()
        self._count = 0

    def append(self, observations: dict[str, float|np.ndarray]) -> None:
        if self._count >= self._capacity:
            return

        for name, value in observations.items():
            if name in self._data:
                self._data[name][self._count] = value
        self._data["__timestamps__"][self._count] = time.perf_counter() - self._start_time

        self._count += 1

    def get(self, name: str) -> np.ndarray:
        """Vue des données effectivement ajoutées"""
        return self._data[name][: self._count]

    def save(self, path: str | Path, conditions: dict[str, Any] | None = None) -> None:
        """Sauvegarde les données (un .npy par observable) et les métadonnées
        (metadata.json) dans une archive '<path>.npz'.
        conditions : informations libres sur l'enregistrement (conditions.json), voir load_conditions."""

        def write_array(zf, name):
            buffer = io.BytesIO()
            np.save(buffer, self.get(name))
            zf.writestr(f"{name}.npy", buffer.getvalue())

        path = Path(path)

        serializable_observables = {
            name: {**prop, "dtype": np.dtype(prop["dtype"]).name}
            for name, prop in self._observables.items()
        }
        metadata_json = json.dumps(serializable_observables, indent=2)

        with zipfile.ZipFile(path, mode="w") as zf:
            zf.writestr("metadata.json", metadata_json)
            if conditions is not None:
                zf.writestr("conditions.json", json.dumps(conditions, indent=2, ensure_ascii=False, default=str))
            for name in self._observables:
                write_array(zf, name)
            write_array(zf, "__timestamps__")

    @classmethod
    def load(cls, path: str | Path) -> tuple[dict[str, np.ndarray], dict[str, dict[str, Any]]]:
        """Charge données et métadonnées depuis une archive '<path>.npz'."""
        path = Path(path)

        with zipfile.ZipFile(path, mode="r") as zf:
            metadata = json.loads(zf.read("metadata.json").decode("utf-8"))

            data: dict[str, np.ndarray] = {}
            for info in zf.infolist():
                if info.filename.endswith(".npy"):
                    name = info.filename[:-len(".npy")]
                    buffer = io.BytesIO(zf.read(info.filename))
                    data[name] = np.load(buffer)

        return data, metadata

    @classmethod
    def load_conditions(cls, path: str | Path) -> dict[str, Any]:
        """Conditions de l'enregistrement (vide si l'archive n'en contient pas)."""
        with zipfile.ZipFile(Path(path), mode="r") as zf:
            if "conditions.json" not in zf.namelist():
                return {}
            return json.loads(zf.read("conditions.json").decode("utf-8"))

    def __len__(self) -> int:
        return self._count            