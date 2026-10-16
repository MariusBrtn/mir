from pathlib import Path
from typing import Any
from loguru import logger
from typing_extensions import override
from lerobot.robots import Robot
from mir_devices.mir_device import mirDevices, ObservableProperty, DeviceAction, ObservablePropertyConverter
from mir_devices.mir_devices_factory import ImirDevicesFactory, DefaultDevicesFactory
from mir_robot.mir_robot_config import mirRobotConfig
from mir_devices.mir_feetech_motor_bus import ImirFeetechMotorBus

# dossier où sont rangées les configurations des robots (un fichier .json par robot, nommé comme le robot)
DOSSIER_ROBOTS = Path(__file__).parent.parent / "robots"


def chemin_robot(nom: str) -> Path:
    """Fichier de configuration du robot de ce nom, dans le dossier des robots."""
    return DOSSIER_ROBOTS / f"{nom}.json"


def robots_disponibles() -> list[str]:
    """Noms des robots du dossier des robots."""
    return sorted(p.stem for p in DOSSIER_ROBOTS.glob("*.json")) if DOSSIER_ROBOTS.is_dir() else []


class mirRobot(Robot):
    root_dir = Path(__file__).parent

    config_class = mirRobotConfig
    name = "car_robot"

    def __init__(self, 
                 config: mirRobotConfig, 
                 devices_factory: ImirDevicesFactory |None = None,
                ):
        logger.debug(f"root_dir={mirRobot.root_dir}")
        self.calibration_dir = Path()
        super().__init__(config)
        self._config = config
        self._enabled_observables: dict[str, ObservableProperty] = {}
        # création motor bus        
        if devices_factory is None:
            devices_factory = DefaultDevicesFactory()
        self._devices : mirDevices = devices_factory.create_devices(config)
        self._mir_motor_bus: ImirFeetechMotorBus|None = self._devices.get_motor_bus()
        self._observables = self._devices.observables

    def get_observables(self) -> dict[str, ObservableProperty]:
        return self._observables

    def enable_observations(self, selected : dict[str, ObservableProperty]) -> None:
        self._enabled_observables = selected
        self._devices.subscribe_to_observables(selected) 

    def enable_observations_by_name(self, names : list[str]) -> None:
        selected = {name: self._observables[name] for name in names}
        self._enabled_observables = selected
        self._devices.subscribe_to_observables(selected) 

    def enable_all_observations(self) -> None:
        self._enabled_observables = self._observables
        self._devices.subscribe_to_observables(self._observables) 

    def get_enabled_observables(self) -> dict[str, dict[str, str]]:
        return ObservablePropertyConverter.observables_to_dict(self._enabled_observables)

    def _device_name_from_feature_name(self, feature_name: str) -> str:
        return feature_name.split(".")[0]
    
    def _feature_value_from_feature_name(self, feature_name: str) -> str:
        elems = feature_name.split(".")
        if len(elems) > 1:
            return elems[1]
        return ""
    
    def _device_field_from_feature(self, feature_name: str) -> tuple[str, str]:
        elems = feature_name.split(".")
        if len(elems) > 1:
            return elems[0], elems[1]
        return elems[0], ""
        
    def get_actions(self) -> dict[str, DeviceAction]:
        return self._devices.get_actions()

    def get_motors_current_positions(self) -> dict[str, int|float]:
        if self._mir_motor_bus is None:
            return {}
        return self._mir_motor_bus.mir_read_positions()

    #hack, il est difficile de garantir que le constructeur de Robot ne charge pas de calibration
    #hors, mirRobot utilise la configuration pour sa calibration
    #ça pose aussi des problèmes dans les tests unitaires
    @override
    def _load_calibration(self, fpath: Path | None = None) -> None:
        pass

    #### <overrides
    @property
    @override
    def observation_features(self):
        return self._config.observations
    
    @property
    @override
    def action_features(self):
        return self._action_features
    
    @property
    @override  
    def is_connected(self):
        """
        Whether the robot is currently connected or not. If `False`, calling :pymeth:`get_observation` or
        :pymeth:`send_action` should raise an error.
        """        
        return self._devices.mir_is_connected()

    @override
    def connect(self, calibrate: bool = True):
        self._devices.mir_connect()
        self._action_features = self._devices.get_actions()

    @override
    def disconnect(self) -> None:
        self._devices.mir_disconnect()    

    @property
    @override
    def is_calibrated(self) -> bool:
        if self._mir_motor_bus is None:
            return True
        return self._mir_motor_bus.mir_is_calibrated()
    
    @override
    def calibrate(self):
        raise RuntimeError("La calibration n'est pas supportée par mirRobot, utiliser mirRobotEditor à cette fin")

    @override
    def configure(self) -> None:
        if self.is_connected is False:
            raise ConnectionError(f"{self} is not connected.")
        if self._mir_motor_bus is not None:
            self._mir_motor_bus.mir_configure_motors()
        self._is_configured = True
    
    def _check_state(self):
        if self.is_connected is False:
            raise ConnectionError(f"{self} is not connected.")
        if not hasattr(self, "_is_configured") or self._is_configured is False:
            raise RuntimeError(f"{self} is not configured.")
                    
    @override
    def get_observation(self) -> dict[str, Any]:
        self._check_state()
        return self._devices.get_observation()            

    @override
    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        self._check_state()
        action = self._devices.send_action(action)
        return action

    def motors_emergency_stop(self):
        if self._mir_motor_bus is None:
            raise RuntimeError("le bus moteur n'a pas été créé")
        self._mir_motor_bus.mir_emergency_stop()

    def motors_stop(self):
        if self._mir_motor_bus is None:
            return
        self._mir_motor_bus.mir_stop(None)

    @staticmethod
    def get_data_directory():
        return mirRobot.root_dir / "data"  

    def motor_is_moving(self, motors:list[str]|None = None) -> bool:
        if self._mir_motor_bus is None:
            raise RuntimeError("le bus moteur n'a pas été créé")
        return self._mir_motor_bus.mir_is_moving(motors)