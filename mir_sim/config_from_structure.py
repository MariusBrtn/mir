"""
Complète une configuration à partir de sa structure : c'est ce qui permet de concevoir un robot sans matériel.

Pour chaque module de la structure qui porte un moteur ou un capteur absent de la configuration, on ajoute
ce moteur (réglages par défaut, pas de calibration) ou ce capteur, ainsi que ses observations. Le robot est
alors utilisable en simulation ; l'assemblage du robot physique complétera la configuration (port, calibration).

Les ID des moteurs ajoutés suivent l'ordre de la structure, à partir de 2 : l'ID 1 est celui d'un servo neuf
et reste réservé pour reconnaître le module qu'on vient de brancher.
"""
from __future__ import annotations
from typing import Any
from lerobot.motors import MotorNormMode
from mir_devices.mir_feetech_motor_bus import mirMotor, mirMotorBusConfiguration
from mir_devices.mir_sensor import mirPiCameraConfiguration
from mir_sim.model_builder import load_catalog
from mir_sim.sim_world import SimWorld
from mir_sim.sim_devices import SimMotorBus, SimCamera

FIRST_MOTOR_ID = 2          # l'ID 1 est réservé au servo neuf
MOTOR_MODEL = "sts3215"
CAMERA_TYPE = "camera"      # type de capteur du catalogue -> configuration pi_camera
CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS = 640, 480, 30


def structure_hardware(structure: dict[str, Any] | None, catalog: dict[str, dict[str, Any]]
                       ) -> tuple[list[str], dict[str, str]]:
    """Moteurs et capteurs portés par les modules placés : ([moteur], {capteur: type de capteur du catalogue})."""
    motors: list[str] = []
    sensors: dict[str, str] = {}
    if not structure:
        return motors, sensors
    for inst in structure.get("modules", {}).values():
        module = catalog.get(inst.get("type", ""), {})
        if "motor" in inst:
            motors.append(inst["motor"])
        motors += list(inst.get("motors", {}).values())
        for key, sensor in inst.get("sensors", {}).items():
            sensors[sensor] = module.get("sensors", {}).get(key, {}).get("type", "")
    return motors, sensors


def complete_config_from_structure(config: Any, catalog: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Ajoute à la configuration les moteurs et capteurs de la structure qui lui manquent, avec leurs observations.
    Ne retire rien (un moteur détecté reste dans la configuration même s'il n'est pas placé).
    Renvoie la liste des éléments ajoutés."""
    catalog = catalog or load_catalog()
    motors, sensors = structure_hardware(config.structure, catalog)
    added: list[str] = []

    new_motors = [m for m in motors if config.motor_bus is None or m not in config.motor_bus.motors]
    if new_motors:
        if config.motor_bus is None:
            config.motor_bus = mirMotorBusConfiguration(motor_port="", motors={}, calibration={})
        used_ids = {motor.id for motor in config.motor_bus.motors.values()}
        next_id = FIRST_MOTOR_ID
        for name in new_motors:
            while next_id in used_ids:
                next_id += 1
            config.motor_bus.motors[name] = mirMotor(id=next_id, model=MOTOR_MODEL, norm_mode=MotorNormMode.DEGREES)
            used_ids.add(next_id)
            added.append(f"moteur {name} (ID {next_id})")

    new_sensors = []
    for name, sensor_type in sensors.items():
        if name in config.sensors:
            continue
        if sensor_type != CAMERA_TYPE:
            continue    # seule la caméra a un équivalent dans la configuration pour l'instant
        config.sensors[name] = mirPiCameraConfiguration(sensor_type=mirPiCameraConfiguration.SENSOR_TYPE, ip=None,
                                                        width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
        new_sensors.append(name)
        added.append(f"caméra {name}")

    if new_motors or new_sensors:
        _add_observations(config, new_motors, new_sensors)
    return added


def _add_observations(config: Any, motors: list[str], sensors: list[str]) -> None:
    """Observations des nouveaux moteurs et capteurs, celles que fournissent les appareils simulés
    (mêmes noms que les appareils réels). Les observations déjà présentes ne sont pas modifiées."""
    world = SimWorld.from_config(config)
    observables = {}
    if motors and config.motor_bus is not None:
        bus = SimMotorBus(config.motor_bus, world)
        observables.update({k: v for k, v in bus.get_observables().items() if k.split(".")[0] in motors})
    for name in sensors:
        cfg = config.sensors[name]
        observables.update(SimCamera(name, world, cfg.width or CAMERA_WIDTH, cfg.height or CAMERA_HEIGHT).get_observables())
    for key, prop in observables.items():
        config.observations.setdefault(key, prop.stype)
