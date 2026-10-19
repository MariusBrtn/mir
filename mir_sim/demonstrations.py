"""
Outils communs aux générateurs de démonstrations automatiques en simulation (robots/<robot>/scripts/generer_*.py) :
un « expert » qui connaît la scène enchaîne des postures clés ; ses démonstrations sont enregistrées comme une collecte
par téléopération (observations du robot et consignes envoyées), la physique avançant pas à pas.

    robot, world, observations = open_sim_robot("bras_4ddl_cam_V2", "scene.json", "cam_1")
    command = lambda t: interpolate(t, [("au-dessus", 1.5), ("descente", 1.0)], start, poses)
    frames = record_episode(robot, world, fmt, fps=20, duration=2.5, command=command)
"""
from __future__ import annotations
import math
from pathlib import Path
from typing import Any, Callable
import cv2
from mir_robot.mir_robot import chemin_robot, mirRobot, mirRobotConfig
from mir_sim.config_from_structure import complete_config_from_structure
from mir_sim.grasp import GripperIK
from mir_sim.sim_devices_factory import SimDevicesFactory
from mir_sim.sim_world import SimWorld


def open_sim_robot(robot_name: str, scene: str | Path | dict, camera: str):
    """Robot simulé dans la scène, physique arrêtée (c'est le générateur qui la fait avancer).
    Observations activées : positions des moteurs et la caméra. Renvoie (robot, monde, observations)."""
    config = mirRobotConfig.load(str(chemin_robot(robot_name)))
    complete_config_from_structure(config)
    factory = SimDevicesFactory(scene=scene)
    robot = mirRobot(config, devices_factory=factory)
    robot.connect()
    robot.configure()
    observations = [n for n in robot.get_observables() if n.endswith(".position")] + [camera]
    robot.enable_observations_by_name(observations)
    world = factory.world
    world.stop_realtime()
    return robot, world, observations


def interpolate(t: float, steps: list[tuple[str, float]], start: dict[str, float],
                poses: dict[str, dict[str, float]]) -> dict[str, float]:
    """Consigne à l'instant t : pendant chaque étape (nom, durée), on va en ligne droite (angles) de la posture
    précédente vers poses[nom]."""
    previous, begin = start, 0.0
    for name, duration in steps:
        if t < begin + duration:
            s = (t - begin) / duration
            return {m: previous[m] + s * (poses[name][m] - previous[m]) for m in start}
        previous, begin = poses[name], begin + duration
    return dict(previous)


def resize_camera(observation: dict[str, Any], camera: str, size: tuple[int, int] | None) -> dict[str, Any]:
    """Image de la caméra réduite à size = (largeur, hauteur), comme une caméra réglée plus petite."""
    if size is None:
        return observation
    return {**observation, camera: cv2.resize(observation[camera], size, interpolation=cv2.INTER_AREA)}


def record_episode(robot, world: SimWorld, fmt, fps: float, duration: float,
                   command: Callable[[float], dict[str, float]], camera: str, size: tuple[int, int] | None = None
                   ) -> list[dict[str, Any]]:
    """Une démonstration : à chaque trame, observation, consigne de l'expert (angles moteur en °), envoi au robot,
    puis la physique avance d'une période. Renvoie les trames du dataset."""
    steps = round(1 / fps / world.model.opt.timestep)
    frames = []
    for k in range(round(duration * fps)):
        observation = resize_camera(robot.get_observation(), camera, size)
        action = {f"{m}.position": v for m, v in command(k / fps).items()}
        robot.send_action(action)
        frames.append(fmt.trame(observation, action))
        world.step(steps)
    return frames


def place_in_gripper(world: SimWorld, ik: GripperIK, name: str, arm_angles: dict[str, float],
                     close_deg: float, hold_s: float = 0.25, settle_s: float = 0.3) -> None:
    """Met un objet de la scène dans la pince (avant une démonstration, non enregistré) : l'objet est maintenu au point
    de saisie, les mors face à ses côtés, pendant que la pince se ferme, puis lâché une fois serré."""
    point, _, closing = ik.forward(arm_angles)
    yaw = math.degrees(math.atan2(closing[1], closing[0]))
    world.set_goal_positions({ik.gripper_motor: close_deg})
    steps = 5
    for _ in range(round(hold_s / world.model.opt.timestep / steps)):
        world.set_object_pose(name, point, yaw)
        world.step(steps)
    world.step(round(settle_s / world.model.opt.timestep))
