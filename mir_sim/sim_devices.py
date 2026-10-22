"""
Devices simulés, interchangeables avec les devices réels (mêmes observables, mêmes actions).
"""
from __future__ import annotations
from typing import Any
import numpy as np
import mujoco
from loguru import logger
from mir_devices.mir_device import (ImirFeetechMotorBus,
                                    ObservableProperty,
                                    ObservablePropertyFloat,
                                    ObservablePropertyBitmap,
                                    ObservablePropertyPolar,
                                    ObservationValue,
                                    ActionValue,
                                    DeviceAction,
                                    mirMotorCalibration)
from mir_devices.mir_sensor import mirSensor, SensorProperty
from mir_devices.mir_feetech_motor_bus import (mirMotorBusConfiguration,
                                               mirMotor,
                                               POSITION_SUFFIX,
                                               VELOCITY_SUFFIX,
                                               CURRENT_SUFFIX,
                                               TEMPERATURE_SUFFIX,
                                               LOAD_SUFFIX,
                                               RPM_PER_UNIT)
from mir_utils.events import Event_
from mir_sim.sim_world import SimWorld

DEG_S_TO_RPM = 1 / 6
MAX_CURRENT_MA = 2700


class SimMotorBus(ImirFeetechMotorBus):
    """Bus moteur simulé : les moteurs de la config pilotent les articulations du SimWorld."""

    def __init__(self, config: mirMotorBusConfiguration, world: SimWorld):
        super().__init__()
        self._config = config
        self._world = world
        self._connected = False
        self._is_calibrated_changed = Event_[[bool]]()
        missing = set(config.motors) - set(world.motors)
        if missing:
            raise ValueError(f"moteurs absents de l'assemblage simulé : {sorted(missing)}")
        for name, motor in config.motors.items():
            if world.is_velocity_motor(name):
                # roue : consigne de vitesse en tr/min, comme le bus réel en mode vitesse
                self._actions[f"{name}.{VELOCITY_SUFFIX}"] = DeviceAction(
                    name, VELOCITY_SUFFIX, 0.0, "float", "tr/min", self.mir_get_motor_velocity_range(name))
            else:
                self._actions[f"{name}.{POSITION_SUFFIX}"] = DeviceAction(
                    name, POSITION_SUFFIX, 0.0, "float", "°", self.mir_get_motor_position_range(name))

    # ---------------------------------------------------------------- mirDevice
    def mir_connect(self) -> None:
        if not self._connected:
            self._world.acquire()
        self._connected = True
        positions = self._position_motors()
        if positions:       # liste vide = que des roues (get_positions([]) lirait tous les moteurs)
            for name, pos in self._world.get_positions(positions).items():
                self._actions[f"{name}.{POSITION_SUFFIX}"].set_value(pos)

    def mir_disconnect(self) -> None:
        if self._connected:
            self._world.release()
        self._connected = False

    def mir_is_connected(self) -> bool:
        return self._connected

    def get_observables(self) -> dict[str, ObservableProperty]:
        observables: dict[str, ObservableProperty] = {}
        for key in self._config.motors:
            min_pos, max_pos = self.mir_get_motor_position_range(key)
            observables[f"{key}.{POSITION_SUFFIX}"] = ObservablePropertyFloat(min_pos, max_pos, "deg")
            min_vel, max_vel = self.mir_get_motor_velocity_range(key)
            observables[f"{key}.{VELOCITY_SUFFIX}"] = ObservablePropertyFloat(min_vel, max_vel, "rpm")
            observables[f"{key}.{CURRENT_SUFFIX}"] = ObservablePropertyFloat(0, MAX_CURRENT_MA, "mA")
            observables[f"{key}.{TEMPERATURE_SUFFIX}"] = ObservablePropertyFloat(0, 100, "°C")
            observables[f"{key}.{LOAD_SUFFIX}"] = ObservablePropertyFloat(-100, 100, "%")
        return observables

    def get_observation(self) -> dict[str, ObservationValue]:
        observation: dict[str, ObservationValue] = {}
        readers = {
            POSITION_SUFFIX: self.mir_read_positions,
            VELOCITY_SUFFIX: self.mir_read_velocities,
            CURRENT_SUFFIX: self.mir_read_currents,
            TEMPERATURE_SUFFIX: self.mir_read_temperatures,
            LOAD_SUFFIX: self.mir_read_loads,
        }
        for suffix, reader in readers.items():
            motors = [f.split(".")[0] for f in self.subscribed_observations if f.endswith(f".{suffix}")]
            if motors:
                observation.update({f"{m}.{suffix}": v for m, v in reader(motors).items()})
        return observation

    def send_action(self, actions: dict[str, ActionValue]) -> dict[str, ActionValue]:
        goal_positions = {k.split(".")[0]: v for k, v in actions.items() if k.endswith(f".{POSITION_SUFFIX}")}
        if goal_positions:
            self.mir_goal_positions(goal_positions, None)
        goal_velocities = {k.split(".")[0]: v for k, v in actions.items() if k.endswith(f".{VELOCITY_SUFFIX}")}
        if goal_velocities:
            self.mir_goal_velocities(goal_velocities)
        return actions

    def _position_motors(self) -> list[str]:
        return [m for m in self._config.motors if not self._world.is_velocity_motor(m)]

    # ---------------------------------------------------------------- calibration (toujours calibré en simu)
    @property
    def mir_is_calibrated_changed(self) -> Any:
        return self._is_calibrated_changed

    def mir_is_calibrated(self) -> bool:
        return True

    def mir_read_calibration_from_motors(self) -> dict[str, mirMotorCalibration] | None:
        return dict(self._config.calibration)

    def mir_calibrate_from_motors(self):
        pass

    def mir_reset_calibration(self, motors: list[str] | None = None) -> None:
        logger.warning("SimMotorBus : la calibration n'a pas de sens en simulation, ignoré")

    def mir_calibrate(self, homing_offsets: dict, range_mins: dict, range_maxes: dict) -> None:
        logger.warning("SimMotorBus : la calibration n'a pas de sens en simulation, ignoré")

    def mir_store_calibration(self) -> None:
        pass

    def mir_restore_calibration(self) -> None:
        pass

    def mir_configure_motors(self) -> None:
        self._world.set_torque_enabled(None, True)

    # ---------------------------------------------------------------- registres : non simulés
    def mir_read_register(self, data_name: str, motor: str, num_retry: int = 0) -> int:
        raise NotImplementedError(f"SimMotorBus : lecture du registre {data_name} non simulée")

    def mir_read_register_by_id(self, data_name: str, motor_id: int, num_retry: int = 0) -> int:
        raise NotImplementedError(f"SimMotorBus : lecture du registre {data_name} non simulée")

    def mir_write_register_by_id(self, data_name: str, motor_id: int, value: int, num_retry: int = 0) -> None:
        raise NotImplementedError(f"SimMotorBus : écriture du registre {data_name} non simulée")

    def mir_set_operating_mode(self, motor: str, operating_mode: Any) -> None:
        vitesse = int(getattr(operating_mode, "value", operating_mode)) == 1
        if vitesse != self._world.is_velocity_motor(motor):
            raise NotImplementedError("SimMotorBus : le mode d'un moteur simulé vient de la structure et de la configuration")

    # ---------------------------------------------------------------- commandes
    def mir_disable_torques(self, motors: list[str] | None = None) -> None:
        self._world.set_torque_enabled(motors, False)

    def mir_get_position_unit(self, motor: str) -> str:
        return "deg"

    def mir_get_velocity_unit(self) -> str:
        return "rpm"

    def mir_goal_position(self, name: str, pos: int | float, vel: int | float) -> None:
        self._world.set_goal_positions({name: float(pos)})

    def mir_goal_positions(self, positions: dict[str, int | float] | int | float,
                           velocities: dict[str, int | float] | None) -> None:
        if not isinstance(positions, dict):
            positions = {m: positions for m in self._position_motors()}
        self._world.set_goal_positions({m: float(p) for m, p in positions.items()})

    def mir_goal_velocity(self, name: str, velocity: int | float) -> None:
        self._world.set_goal_velocities({name: float(velocity)})

    def mir_goal_velocities(self, velocities: int | dict[str, int | float]) -> None:
        if not isinstance(velocities, dict):
            velocities = {m: velocities for m in self._config.motors if self._world.is_velocity_motor(m)}
        self._world.set_goal_velocities({m: float(v) for m, v in velocities.items()})

    def mir_stop(self, name: str | list[str] | None):
        motors = [name] if isinstance(name, str) else name
        self._world.hold_current_positions(motors)

    def mir_emergency_stop(self) -> None:
        self._world.set_torque_enabled(None, False)

    # ---------------------------------------------------------------- lectures
    def mir_read_positions(self, motors: list[str] | None = None) -> dict[str, int | float]:
        return dict(self._world.get_positions(motors))

    def mir_read_raw_positions(self, motors: list[str] | None = None) -> dict[str, int | float]:
        result = {}
        for m, deg in self._world.get_positions(motors).items():
            cal = self._config.calibration.get(m)
            mid = (cal.range_min + cal.range_max) / 2 if cal is not None else 2048
            result[m] = int(deg * 4095 / 360 + mid)
        return result

    def mir_read_velocities(self, motors: list[str] | None = None) -> dict[str, int | float]:
        # même quantification que le bus réel (unités de 0.732 tr/min)
        return {m: int(round(v * DEG_S_TO_RPM / RPM_PER_UNIT) * RPM_PER_UNIT)
                for m, v in self._world.get_velocities_deg_s(motors).items()}

    def mir_read_currents(self, motors: list[str] | None = None) -> dict[str, int | float]:
        # courant proportionnel au couple : MAX_CURRENT_MA rotor bloqué sous 12 V
        return {m: int(abs(r) * MAX_CURRENT_MA) for m, r in self._world.get_torque_ratios(motors).items()}

    def mir_read_loads(self, motors: list[str] | None = None) -> dict[str, int | float]:
        # comme le STS3215 : rapport cyclique du moteur (tension appliquée / 12 V), en %
        return {m: int(r * 100) for m, r in self._world.get_load_ratios(motors).items()}

    def mir_read_temperatures(self, motors: list[str] | None = None) -> dict[str, int | float]:
        return {m: 30 for m in (motors or self._config.motors)}

    def mir_is_moving(self, motors: list[str] | None = None) -> bool:
        return self._world.is_moving(motors)

    def mir_get_motors(self) -> dict[str, mirMotor]:
        return self._config.motors

    def mir_get_motor_position_range(self, motor: str) -> tuple[float, float]:
        return self._world.joints[motor].range_deg

    def mir_get_motor_velocity_range(self, motor: str) -> tuple[float, float]:
        max_rpm = self._world.built.max_velocity_deg_s.get(motor, 360.0) * DEG_S_TO_RPM
        return (-max_rpm, max_rpm)

    # ---------------------------------------------------------------- fabriques statiques (sans objet en simu)
    @staticmethod
    def mir_make_empty_bus(port: str) -> ImirFeetechMotorBus:
        raise NotImplementedError("SimMotorBus : utiliser SimDevicesFactory")

    @staticmethod
    def mir_make_bus_from_motors(port: str, motors: dict) -> ImirFeetechMotorBus:
        raise NotImplementedError("SimMotorBus : utiliser SimDevicesFactory")

    @staticmethod
    def mir_scan_motors(port: str) -> list[int]:
        return []

    @staticmethod
    def mir_scan_motors_on_all_ports() -> tuple[str, list[int]] | tuple[None, None]:
        return (None, None)


class SimCamera(mirSensor):
    """Caméra simulée : rendu MuJoCo de la caméra du même nom dans l'assemblage."""

    def __init__(self, sensor_key: str, world: SimWorld, width: int = 640, height: int = 480,
                 camera_name: str | None = None):
        super().__init__(sensor_key)
        self._world = world
        self._width = width
        self._height = height
        self._camera_name = camera_name or sensor_key
        if mujoco.mj_name2id(self._world.model, mujoco.mjtObj.mjOBJ_CAMERA, self._camera_name) < 0:
            raise ValueError(f"caméra '{self._camera_name}' absente de l'assemblage simulé")
        self._connected = False

    def mir_connect(self) -> None:
        if not self._connected:
            self._world.acquire()
        self._connected = True

    def mir_disconnect(self) -> None:
        if self._connected:
            self._world.release()
        self._connected = False

    def mir_is_connected(self) -> bool:
        return self._connected

    def get_observables(self) -> dict[str, ObservableProperty]:
        return {self.sensor_key: ObservablePropertyBitmap(self._height, self._width, 3)}

    def get_observation(self) -> dict[str, ObservationValue]:
        if self.sensor_key not in self.subscribed_observations:
            return {}
        return {self.sensor_key: np.ascontiguousarray(self._world.render(self._camera_name, self._width, self._height))}

    def send_action(self, actions: dict[str, ActionValue]) -> dict[str, ActionValue]:
        return {}

    def test_connection(self) -> bool:
        return True

    def get_configurable_properties(self) -> dict[str, SensorProperty]:
        return {}

    def set_property(self, key: str, value: Any) -> bool:
        return False

    def reset_sensor(self):
        pass


class SimLidar(mirSensor):
    """Lidar simulé (RPLidar C1) : un tour de mesures par lancer de rayons dans la scène.
    Même observation que le lidar réel esp_lidar : tableau (points, 2) = [angle en degrés, distance en cm],
    distance 0 quand rien n'est mesuré (hors de la portée de 5 cm à 12 m)."""

    MAX_RANGE_CM = 600      # échelle d'affichage, comme EspSensorLidar

    def __init__(self, sensor_key: str, world: SimWorld):
        super().__init__(sensor_key)
        self._world = world
        if sensor_key not in world.built.lidars:
            raise ValueError(f"lidar '{sensor_key}' absent de l'assemblage simulé")
        self._points = world.built.lidars[sensor_key]["points"]
        self._range_m = tuple(world.built.lidars[sensor_key]["range_m"])
        self._connected = False

    def mir_connect(self) -> None:
        if not self._connected:
            self._world.acquire()
        self._connected = True

    def mir_disconnect(self) -> None:
        if self._connected:
            self._world.release()
        self._connected = False

    def mir_is_connected(self) -> bool:
        return self._connected

    def get_observables(self) -> dict[str, ObservableProperty]:
        return {self.sensor_key: ObservablePropertyPolar(self._points, self.MAX_RANGE_CM)}

    def get_observation(self) -> dict[str, ObservationValue]:
        if self.sensor_key not in self.subscribed_observations:
            return {}
        angles, distances_m = self._world.lidar_scan(self.sensor_key, self._range_m)
        # comme le firmware : centimètres arrondis
        scan = np.column_stack([angles, np.round(distances_m * 100)]).astype(np.float32)
        return {self.sensor_key: scan}

    def send_action(self, actions: dict[str, ActionValue]) -> dict[str, ActionValue]:
        return {}

    def test_connection(self) -> bool:
        return True

    def get_configurable_properties(self) -> dict[str, SensorProperty]:
        return {}

    def set_property(self, key: str, value: Any) -> bool:
        return False

    def reset_sensor(self):
        pass
