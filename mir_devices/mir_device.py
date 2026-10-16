from lerobot.motors import MotorCalibration
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeAlias
import numpy as np

ObservationValue: TypeAlias = float | np.ndarray
ActionValue : TypeAlias = int|float

class ObservableProperty :
    stype : Any

class ObservablePropertyFloat(ObservableProperty):
    min_value: float
    max_value: float
    unit: str
    dtype: np.dtype

    def __init__(self, min_value: float, max_value: float, unit: str, dtype: np.dtype = np.dtype(np.float32)):
        self.min_value = min_value
        self.max_value = max_value
        self.stype = 'float'
        self.unit = unit
        self.dtype = dtype

class ObservablePropertyBitmap(ObservableProperty):
    def __init__(self, height:int, width:int, channels:int):
        self.stype = (height, width,channels)

class ObservablePropertyPolar(ObservableProperty):
    max_range:float
    def __init__(self, num_points:int, max_range:float):
        self.stype = (num_points, 2)
        self.max_range = max_range

class ObservablePropertyConverter :
    @classmethod
    def property_to_dict(cls, property: ObservableProperty) -> dict[str, Any]:
        if isinstance(property, ObservablePropertyFloat):
            return {
                "type": property.stype,
                "min_value": property.min_value,
                "max_value": property.max_value,
                "unit": property.unit,
                "dtype": property.dtype
            }
        elif isinstance(property, ObservablePropertyBitmap):
            return {
                "type": property.stype,
            }
        elif isinstance(property, ObservablePropertyPolar):
            return {
                "type": property.stype,
                "max_range": property.max_range
            }
        raise NotImplementedError(f"ObservableProperty type {type(property)} not supported")

    @classmethod
    def observables_to_dict(cls, observables: dict[str, ObservableProperty]) -> dict[str, dict[str, Any]]:
        return {name: cls.property_to_dict(property) for name, property in observables.items()}
    
class DeviceAction :
    def __init__(self, device_name: str, action_name: str, default_value: ActionValue, type :str, unit: str, range:tuple[ActionValue, ActionValue]|None):
        self.device_name: str = device_name
        self.action_name: str = action_name
        self._value: ActionValue = default_value
        self._type = type
        self._unit = unit
        self._range = range

    def full_name(self):
        return f"{self.device_name}.{self.action_name}"
        
    def get_value(self):
        if self._type == 'int':
            return int(self._value)
        return self._value

    def set_value(self, value: ActionValue):
        if self._type == 'int':
            self._value = int(value)
        else:
            self._value = value

    def get_unit(self):
        return self._unit

    def get_type(self) -> str:
        return self._type

    def get_range(self) -> tuple[ActionValue, ActionValue]|None:
        return self._range

    def set_range(self, range: tuple[ActionValue, ActionValue]):
        self._range = range
    
def device_feature_name_from_feature(feature: str) -> tuple[str, str]:
    elems = feature.split(".")
    if len(elems) > 1:
        return elems[0], elems[1]
    return elems[0], ""            

class mirDevice(ABC):

    def __init__(self):
       self.subscribed_observations : set[str] = set()
       self._actions : dict[str, DeviceAction] = {}
        
    @abstractmethod
    def mir_connect(self)->None:
        pass
    @abstractmethod
    def mir_disconnect(self)->None:
        pass
    @abstractmethod
    def mir_is_connected(self) -> bool:
        pass

    @abstractmethod
    def get_observation(self) -> dict[str, ObservationValue]: 
        pass
    
    @abstractmethod
    def get_observables(self) -> dict[str, ObservableProperty]:
        pass

    def unsubscribe_all(self):
        self.subscribed_observations.clear()

    def subscribe(self, feature: str):
        self.subscribed_observations.add(feature)

    def get_observables_in(self, features: list[str]) -> dict[str, ObservableProperty]:
        return {k: v for k, v in self.get_observables().items() if k in features}

    def send_action(self, actions:dict[str, ActionValue])->dict[str, ActionValue]:
        return {}
    
    def get_actions(self) -> dict[str, DeviceAction]:
        return self._actions


@dataclass 
class mirMotorCalibration(MotorCalibration):
    pass

class ImirFeetechMotorBus(mirDevice):
    
    @property
    @abstractmethod
    def mir_is_calibrated_changed(self) -> Any:
        """Événement déclenché lorsque l'état de calibration change."""
        pass

    @abstractmethod
    def mir_read_calibration_from_motors(self) -> dict[str, mirMotorCalibration] | None:
        """
        Lit la calibration de tous les moteurs
        retourne None si la calibration n'existe pas ou n'est pas valide
        """
        pass
        
    @abstractmethod
    def mir_read_register(self, data_name: str, motor: str, num_retry: int = 0) ->int:
        pass
    
    @abstractmethod
    def mir_read_register_by_id(self, data_name: str, motor_id: int, num_retry: int = 0) ->int:
        pass

    @abstractmethod
    def mir_write_register_by_id(self, data_name: str, motor_id: int, value: int, num_retry: int = 0) ->None:
        pass

    @abstractmethod
    def mir_calibrate_from_motors(self):
        pass

    @abstractmethod
    def mir_is_calibrated(self) -> bool:
        """Retourne l'état actuel de la calibration."""
        pass

    @abstractmethod
    def mir_is_connected(self) -> bool:
        """le bus est-il connecté."""
        pass

    @abstractmethod
    def mir_disable_torques(self, motors: list[str] | None = None)->None:
        pass

    @abstractmethod
    def mir_set_operating_mode(self, motor: str, operating_mode: Any) -> None:
        """Définit le mode de fonctionnement d'un moteur spécifique."""
        pass

    @abstractmethod
    def mir_get_position_unit(self, motor: str) -> str:
        """Retourne l'unité de mesure des positions."""
        pass

    @abstractmethod
    def mir_get_velocity_unit(self) -> str:
        """Retourne l'unité de mesure des vitesses."""
        pass

    @abstractmethod
    def mir_goal_position(self, name: str, pos: int|float, vel:int) -> None:
        """Déplace un moteur vers une position normalisée si le bus est calibré, sinon vers une position brute."""
        pass
    
    @abstractmethod
    def mir_stop(self, name:str|list[str]|None):
        pass

    @abstractmethod
    def mir_goal_positions(self, positions : dict[str, int|float] | int | float, velocities: dict[str, int|float]|None) -> None:
        """Déplace un ou plsuieurs moteurs vers une position normalisée si le bus est calibré."""
        pass

    @abstractmethod
    def mir_goal_velocity(self, name: str, velocity: int) -> None:
        """Déplace un moteur à une vitesse donnée."""
        pass

    @abstractmethod
    def mir_goal_velocities(self, velocities: int | dict[str, int|float]) -> None:
        """Déplace un ou plusieurs moteurs à des vitesses données."""
        pass 
    
    @abstractmethod
    def mir_read_positions(self, motors: list[str]|None = None) -> dict[str, int|float]:
        """
            Lit les positions des moteurs
        
        Args:
          motors : liste des moteurs, si None retourne les positions de tous les moteurs

        Returns:
            un dictionnaire avec  les valeurs normalisées si le bus est calibré, brutes sinon.
            exemple : {"joint1":30, "joint2":45 }
        """
        pass

    @abstractmethod
    def mir_read_raw_positions(self, motors: list[str]|None = None) -> dict[str, int|float]:
        pass

    @abstractmethod
    def mir_read_velocities(self, motors: list[str]|None = None) -> dict[str, int|float]:    
        pass

    @abstractmethod
    def mir_read_currents(self, motors: list[str]|None) -> dict[str, int|float]:    
        pass

    @abstractmethod
    def mir_read_loads(self, motors: list[str]|None = None) -> dict[str, int|float]:
        pass
        
    @abstractmethod
    def mir_read_temperatures(self, motors: list[str]|None = None) -> dict[str, int|float]:            
        pass

    @abstractmethod
    def mir_reset_calibration(self, motors: list[str] | None = None) -> None:
        """Réinitialise la calibration des moteurs spécifiés ou de tous les moteurs."""
        pass

    @abstractmethod
    def mir_calibrate(self, homing_offsets: dict, range_mins: dict, range_maxes: dict) -> None:
        """Calibre les moteurs avec les paramètres fournis."""
        pass

    @abstractmethod
    def mir_store_calibration(self) -> None:
        """Sauvegarde la calibration actuelle en mémoire locale."""
        pass

    @abstractmethod
    def mir_restore_calibration(self) -> None:
        """Restaure la calibration préalablement sauvegardée."""
        pass

    @abstractmethod
    def mir_configure_motors(self) -> None:
        """Configure les registres initiaux de l'ensemble des moteurs."""
        pass

    @abstractmethod
    def mir_is_moving(self, motors:list[str]|None=None) -> bool:
        """
        retourne True si au moins un des moteurs est en mouvement
        """
        pass

    @abstractmethod
    def mir_get_motors(self)->dict[str, Any]:
        pass

    @abstractmethod
    def mir_get_motor_position_range(self, motor:str)->tuple[float, float]:
        pass

    @abstractmethod
    def mir_get_motor_velocity_range(self, motor:str)->tuple[float, float]:
        pass

    @abstractmethod
    def mir_emergency_stop(self) -> None:
        """Arrêt d'urgence des moteurs."""
        pass

    @staticmethod
    @abstractmethod
    def mir_make_empty_bus(port: str) -> "ImirFeetechMotorBus":
        """Fabrique une instance de bus vide sur un port donné."""
        pass

    @staticmethod
    @abstractmethod
    def mir_make_bus_from_motors(port: str, motors: dict) -> "ImirFeetechMotorBus":
        """Fabrique une instance de bus initialisée avec des moteurs sur un port donné."""
        pass

    @staticmethod
    @abstractmethod
    def mir_scan_motors(port: str) -> list[int]:
        """Scanne un port spécifique pour lister les identifiants des moteurs présents."""
        pass

    @staticmethod
    @abstractmethod
    def mir_scan_motors_on_all_ports() -> tuple[str, list[int]] | tuple[None, None]:
        """Scanne l'intégralité des ports disponibles à la recherche de moteurs."""
        pass
        

class mirDevices:
    def __init__(self, devices:dict[str, mirDevice],observables : dict[str, ObservableProperty]):
        self.devices = devices
        self.observables = observables
        self.actions : dict[str, DeviceAction] = {}
        self.action_to_device : dict[str, mirDevice] = {}
        for device in self.devices.values():
            device_actions = device.get_actions()
            self.actions.update(device_actions)
            for action_feature in device_actions.keys():
                self.action_to_device[action_feature] = device

    def get_motor_bus(self) -> ImirFeetechMotorBus| None:
        if "motor_bus" in self.devices:
            if isinstance(self.devices["motor_bus"], ImirFeetechMotorBus):
                return self.devices["motor_bus"]
            else:
                raise RuntimeError("Le device motor_bus n'est pas de type ImirFeetechMotorBus")
        return None

    def mir_connect(self):
        device_name : str = ""
        try:
            for key, device in self.devices.items():
                device_name = key
                device.mir_connect()
        except Exception as e:
            raise ConnectionError(f"Echec connexion {device_name} : {e}")

    def mir_disconnect(self):
        for device in self.devices.values():
            device.mir_disconnect()

    def mir_is_connected(self) -> bool:
        for device in self.devices.values():
            if device.mir_is_connected() is False:
                return False
        return True    

    def subscribe_to_observables(self, selected: dict[str, ObservableProperty]):
        for device in self.devices.values():
            device.unsubscribe_all()
        for feature, observable_property in selected.items():
            for device in self.devices.values():
                if feature in device.get_observables():
                    device.subscribe(feature)
                    break

    def get_observation(self) -> dict[str, ObservationValue]: 
        observation = {}    
        for device in self.devices.values():
            observation.update(device.get_observation())
        return observation
    
    def get_actions(self) -> dict[str, DeviceAction]:
        return self.actions

    def send_action(self, action:dict[str, ActionValue]) -> dict[str, ActionValue]:
        prefixes = [key.rsplit(".", 1)[0] for key in action.keys()]
        if len(prefixes) != len(set(prefixes)):
            raise ValueError(f"Duplicate action prefix detected: {prefixes}")

        unknown = set(action) - set(self.actions)
        if unknown:
            raise ValueError(f"actions non définies dans action_features : {unknown}")

        actions_by_device : dict[mirDevice, dict[str, ActionValue]] = {}
        for key, dev_action in action.items():
            device = self.action_to_device[key]
            if device not in actions_by_device:
                actions_by_device[device] = {}
            actions_by_device[device][key] = dev_action

        for device, device_actions in actions_by_device.items():
            device.send_action(device_actions)
        
        return action