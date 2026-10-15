from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from lerobot.robots import RobotConfig
from typing import Any
from copy import deepcopy
import os
import json
import dacite
from mir_devices.mir_sensor import mirSensorConfiguration
from mir_devices.mir_feetech_motor_bus import mirMotorBusConfiguration
from mir_utils.json_parse_helpers import JsonParseHelper
from mir_devices.mir_device import ObservableProperty

#forcer dacite à accepter les Enum et faire un cast lorsque nécessaire
_DACITE_CONFIG = dacite.Config(cast=[Enum])

@RobotConfig.register_subclass("car_robot")
@dataclass
class mirRobotConfig(RobotConfig):
    id : str|None = "mir_robot"
    motor_bus : mirMotorBusConfiguration | None = None
    sensors: dict[str, mirSensorConfiguration] =field(default_factory=lambda: { })
    observations: dict[str, Any] = field(default_factory=lambda: { })
    # structure mécanique du robot (modules du catalogue mir_sim et leurs branchements), facultative :
    # sert à construire le modèle de simulation. Voir mir_sim/README.md
    structure: dict[str, Any] | None = None
    path: str |None = None
    
    def save(self):
        if self.path is None:
            raise RuntimeError("le chemin n'a pas été défini")
        self.save_as(self.path)

    def save_as(self, path):
        self.path = path
        with open(path, "w") as f:
            json.dump(self._to_dict(), f, indent=4)

    def to_json(self):
        return json.dumps(self._to_dict())

    def _to_dict(self) -> dict[str, Any]:
        data = JsonParseHelper.to_dict(self)
        if data.get("structure") is None:
            # pas de structure : fichier identique à celui des versions qui ne la connaissent pas
            data.pop("structure", None)
        return data

    @staticmethod
    def from_dict(data: dict[str, Any], path: str | None = None) -> mirRobotConfig:
        """Crée une instance à partir d'un dictionnaire JSON (utilisé par load et from_json)"""
        try:
            sensors_dict = data.get("sensors")
            sensors = mirSensorConfiguration.create_sensors_from_dict(sensors_dict, _DACITE_CONFIG)
            motor_bus_dict = data.get("motor_bus")
            if motor_bus_dict is None:
                motor_bus = None
            else:
                motor_bus = mirMotorBusConfiguration.create_motor_bus_from_dict(motor_bus_dict, _DACITE_CONFIG)
            data["observations"] = {k: JsonParseHelper.decode_value(v) for k, v in data.get("observations", {}).items()}
            config_dict: dict[str, Any] = {**data, "motor_bus": motor_bus, "sensors": sensors, "path": path}
            return mirRobotConfig(**config_dict)
        except (dacite.DaciteError, TypeError, KeyError, ValueError) as e:
            location = f"'{path}'" if path else "la chaîne JSON"
            raise ValueError(f"{location} n'est pas une configuration conforme ({e})") from e

    @staticmethod
    def load(path: str) -> mirRobotConfig:
        """Charge une configuration depuis un fichier JSON"""
        try:
            with open(path) as f:
                data = json.load(f)
        except FileNotFoundError as e:
            raise ValueError(f"'{path}' le fichier n'a pas été trouvé ({e})") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"'{path}' n'est pas un fichier de configuration conforme ({e})") from e        
        return mirRobotConfig.from_dict(data, path=path)

    @staticmethod
    def from_json(json_str: str) -> mirRobotConfig:
        """Crée une instance à partir d'une chaîne JSON"""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"La chaîne JSON n'est pas valide ({e})") from e
        return mirRobotConfig.from_dict(data, path=None)

    def get_deep_copy(self):
        return deepcopy(self)

    def is_equal(self, other:mirRobotConfig)->bool:
        return self == other

    def get_dir_of_file(self):
        if self.path is not None and os.path.exists(self.path):
            return os.path.dirname(self.path)        
        return None

    def set_observations_from_observables(self, observables: dict[str, ObservableProperty]):
        self.observations = {
            key: prop.stype
            for key, prop in observables.items()
        }        