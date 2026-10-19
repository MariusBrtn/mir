"""
Scènes d'un robot (robots/<robot>/scenes/*.json) et placement de leurs objets.

Une scène décrit la table, les objets et, facultativement, comment la remettre en place au début d'un essai
("name" et "description" : nom et explication affichés dans MIR) :

    "start_pose": {"joint_1": 0, "joint_2": -60, ...}      posture de départ du robot (angles moteur en °)
    "objects": [{"name": "de", ...,
                 "placement": {"radius_m": [0.18, 0.20],   distance à l'axe du socle (m), tirée au hasard
                               "angle_deg": [-15, 15],     angle autour de l'axe du bras (0 : droit devant)
                               "yaw_deg": [-5, 5],         orientation de l'objet
                               "yaw_relative": true}},     orientation comptée par rapport à la direction du bras
                {"name": "cube", ..., "in_gripper": true}] objet mis dans la pince

Le même placement sert au bouton « Replacer la scène » de MIR et aux générateurs de démonstrations.
"""
from __future__ import annotations
import json
import math
import random
from pathlib import Path
from typing import Any
from mir_sim.demonstrations import place_in_gripper
from mir_sim.grasp import OPEN_DEG, GripperIK
from mir_sim.sim_world import SimWorld

SCENES_DIR = "scenes"


def scene_files(robot_dir: str | Path | None) -> list[Path]:
    """Scènes d'un robot, par nom."""
    if robot_dir is None:
        return []
    folder = Path(robot_dir) / SCENES_DIR
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def load_scene_file(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def draw_position(placement: dict[str, Any], rng: random.Random) -> tuple[float, float, float]:
    """Position (x, y en m) et orientation (°) tirées au hasard selon les règles de placement d'un objet."""
    radius = rng.uniform(*placement.get("radius_m", [0.2, 0.2]))
    angle = math.radians(rng.uniform(*placement.get("angle_deg", [0.0, 0.0])))
    yaw = rng.uniform(*placement.get("yaw_deg", [0.0, 0.0]))
    if placement.get("yaw_relative", False):
        yaw += math.degrees(angle)
    return radius * math.cos(angle), radius * math.sin(angle), yaw


def place_scene(world: SimWorld, scene: dict[str, Any], rng: random.Random | None = None) -> dict[str, tuple]:
    """Remet la scène en place : robot en posture de départ, objets placés au hasard selon leurs règles, objet tenu
    dans la pince. Renvoie les positions tirées {objet: (x, y, orientation)}."""
    rng = rng or random.Random()
    start = {m: float(v) for m, v in (scene.get("start_pose") or {}).items()}
    in_gripper = [obj for obj in scene.get("objects", []) if obj.get("in_gripper")]
    ik = GripperIK(world) if in_gripper else None
    # objet à mettre dans la pince : on part pince ouverte, elle se ferme dessus
    world.reset({**start, ik.gripper_motor: OPEN_DEG} if ik else start)
    placed = {}
    for obj in scene.get("objects", []):
        placement = obj.get("placement")
        if placement and obj.get("free", True):
            x, y, yaw = draw_position(placement, rng)
            world.set_object_pose(obj["name"], [x, y, obj["pos"][2]], yaw)
            placed[obj["name"]] = (x, y, yaw)
    for obj in in_gripper:
        arm = {m: start.get(m, 0.0) for m in ik.arm}
        place_in_gripper(world, ik, obj["name"], arm, start.get(ik.gripper_motor, -OPEN_DEG))
    return placed
