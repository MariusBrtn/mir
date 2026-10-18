"""
Fabrique de devices simulés, à passer à mirRobot à la place de DefaultDevicesFactory :

    factory = SimDevicesFactory(scene="scene_de.json")   # scène facultative (table, objets, caméras fixes)
    robot = mirRobot(config, devices_factory=factory)

La même configuration JSON que le robot réel est utilisée : moteurs, plages de calibration,
couples et vitesses, et la structure du robot (section "structure", modules du catalogue).
Chaque caméra "pi_camera" de la config est remplacée par la caméra simulée du même nom, chaque lidar "esp_lidar"
placé dans la structure par le lidar simulé du même nom.
"""
from __future__ import annotations
from pathlib import Path
from loguru import logger
from mir_devices.mir_device import mirDevice, mirDevices, ObservableProperty
from mir_devices.mir_devices_factory import ImirDevicesFactory
from mir_devices.mir_sensor import EspSensorLidarConfiguration, mirPiCameraConfiguration
from mir_robot.mir_robot_config import mirRobotConfig
from mir_sim.sim_world import SimWorld
from mir_sim.sim_devices import SimMotorBus, SimCamera, SimLidar

class SimDevicesFactory(ImirDevicesFactory):
    def __init__(self, scene: str | Path | dict | None = None):
        self._scene = scene
        self.world: SimWorld | None = None

    def create_devices(self, config: mirRobotConfig) -> mirDevices:
        self.world = SimWorld.from_config(config, self._scene)

        devices: dict[str, mirDevice] = {}
        for key, sensor_cfg in config.sensors.items():
            if isinstance(sensor_cfg, mirPiCameraConfiguration):
                devices[key] = SimCamera(key, self.world, sensor_cfg.width or 640, sensor_cfg.height or 480)
            elif isinstance(sensor_cfg, EspSensorLidarConfiguration) and key in self.world.built.lidars:
                devices[key] = SimLidar(key, self.world)
            else:
                logger.warning(f"capteur '{key}' ({sensor_cfg.sensor_type}) non simulé, ignoré")
        if config.motor_bus is not None:
            devices["motor_bus"] = SimMotorBus(config.motor_bus, self.world)

        observables: dict[str, ObservableProperty] = {}
        for device in devices.values():
            observables.update(device.get_observables_in(list(config.observations.keys())))
        return mirDevices(devices, observables)
