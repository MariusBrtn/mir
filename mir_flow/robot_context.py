"""
Contexte du robot pour un modèle de langage : ses actionneurs et ses capteurs, déduits automatiquement de la configuration du robot (structure, moteurs, capteurs).

La géométrie vient du modèle MuJoCo construit à partir de la structure, le même que pour la simulation :
sens de chaque roue (faire avancer ou tourner le robot), effet de chaque articulation sur le bout du bras,
emplacement des caméras et du lidar. Le robot réel et le robot simulé ont donc le même contexte.

Le texte est en anglais (langue de travail des modèles) ; le modèle répond dans la langue de l'utilisateur.
"""
from __future__ import annotations
from typing import Any
import mujoco
import numpy as np
from loguru import logger

PROBE_DEG = 10.0            # rotation d'essai d'une articulation pour mesurer son effet sur le bout du bras
UP = np.array([0.0, 0.0, 1.0])
# grandeurs lues par défaut : les autres (courant, température, charge) ne servent qu'à la demande
DEFAULT_FIELDS = ("position", "velocity")


def default_observation_names(observables: list[str]) -> list[str]:
    """Grandeurs utiles par défaut : positions, vitesses et capteurs (pas le courant, la température, la charge)."""
    return [n for n in observables if "." not in n or n.rsplit(".", 1)[1] in DEFAULT_FIELDS]


def describe_robot(config: Any, actions: dict[str, Any], observables: dict[str, Any]) -> str:
    """Texte qui explique le robot au modèle de langage.
    config : mirRobotConfig ; actions : robot.get_actions() ; observables : robot.get_observables()."""
    modules = (config.structure or {}).get("modules", {}) if config.structure else {}
    geometry = _Geometry.build(config) if modules else None
    mobile = bool(modules) and not any(m.get("type") == "mir_socle" and m.get("fixed") for m in modules.values())

    lines = ["# Robot", ""]
    lines.append(f"A modular MIR robot, {'mobile (it drives on wheels)' if mobile else 'fixed to the table'}.")
    if modules:
        lines += ["", "## Modules (how the robot is assembled)"]
        for name, module in modules.items():
            on = module.get("on")
            lines.append(f"- {name} ({module.get('type', '?')})" + (f", mounted on {on.split('.')[0]}" if on else ""))
    if geometry is not None:
        lines += ["", "## Robot frame", geometry.frame_text()]

    lines += ["", "## Actuators", ""]
    module_of_motor = {m.get("motor"): (n, m) for n, m in modules.items() if m.get("motor")}
    for name, action in actions.items():
        motor, field = name.rsplit(".", 1)
        rng = action.get_range()
        rng_text = f"from {rng[0]:.4g} to {rng[1]:.4g} {action.get_unit()}" if rng else action.get_unit()
        module_name, module = module_of_motor.get(motor, (None, {}))
        kind = module.get("type", "")
        if field == "velocity":
            text = f"- `{name}`: wheel rotation speed, {rng_text}."
        else:
            text = f"- `{name}`: joint angle, {rng_text}."
        if kind == "mir_pince":
            sign = geometry.joint_direction(motor) if geometry else 1.0
            text += f" This is the gripper: a {'higher' if sign > 0 else 'lower'} angle closes it."
        effect = geometry.joint_effect(motor) if geometry and field == "position" and kind != "mir_pince" else ""
        if effect:
            text += " " + effect
        if field == "velocity" and geometry:
            effect = geometry.wheel_effect(motor)
            if effect:
                text += " " + effect
        lines.append(text)

    lines += ["", "## Sensors", ""]
    sensors_by_key = {}
    for name, module in modules.items():
        for sensor_key in (module.get("sensors") or {}).values():
            sensors_by_key[sensor_key] = (name, module)
    for name in default_observation_names(list(observables)):
        if "." in name:
            continue        # état des moteurs : décrit ci-dessous
        kind = type(observables[name]).__name__
        module_name, module = sensors_by_key.get(name, (None, {}))
        where = f", mounted on {module['on'].split('.')[0]}" if module.get("on") else ""
        if kind == "ObservablePropertyBitmap":
            lines.append(f"- `{name}`: camera{where}.")
        elif kind == "ObservablePropertyPolar":
            lines.append(f"- `{name}`: 360° lidar{where}. A list of [angle_deg, distance_cm] pairs: "
                         "angle 0 is the robot front, increasing clockwise seen from above (90 = right, "
                         "180 = back, 270 = left). Distance 0 means nothing was measured (out of range, "
                         "5 cm to 12 m).")
        else:
            lines.append(f"- `{name}`{where}.")
    motors = sorted({n.rsplit(".", 1)[0] for n in observables if "." in n})
    if motors:
        lines.append(f"- Motor state of {', '.join(motors)}: `<motor>.position` (deg), `<motor>.velocity` (rpm). "
                     "Also `.current` (mA), `.temperature` (°C), `.load` (%).")
    return "\n".join(lines)


def drive_presets(config: Any, actions: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Préréglages de consignes pour un robot à roues : {"Avancer": {"roue_avant_gauche.velocity": 60, ...}, ...}.
    Vide si le robot n'a pas de roues."""
    wheels = [n.rsplit(".", 1)[0] for n in actions if n.endswith(".velocity")]
    if not wheels or not config.structure:
        return {}
    geometry = _Geometry.build(config)
    return geometry.drive_presets(wheels, actions) if geometry else {}


class _Geometry:
    """Le robot en posture de repos (toutes les articulations à 0), dans le repère du robot : avant, gauche, haut."""

    def __init__(self, built, model: mujoco.MjModel, data: mujoco.MjData):
        self.built, self.model, self.data = built, model, data
        self.forward, self.left, self.origin = self._robot_frame()

    @staticmethod
    def build(config: Any) -> _Geometry | None:
        try:
            from mir_sim.model_builder import build_model
            built = build_model(config, None)
            data = mujoco.MjData(built.model)
            for motor, joint in built.joints.items():
                if not joint.velocity:
                    data.qpos[built.model.jnt_qposadr[built.model.joint(joint.joint_name).id]] = joint.motor_to_sim_rad(0)
            mujoco.mj_forward(built.model, data)
            return _Geometry(built, built.model, data)
        except Exception as e:
            logger.warning(f"contexte du robot sans géométrie : {e}")
            return None

    # ------------------------------------------------------------------ repère du robot
    def _robot_frame(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Avant = direction 0° du lidar s'il y en a un (les mesures du lidar sont alors dans le repère du robot),
        sinon l'axe x du socle. Origine : centre des roues, sinon le socle."""
        forward = None
        for name in self.built.lidars:
            forward = self.data.site_xmat[self.model.site(name).id].reshape(3, 3)[:, 0].copy()
        if forward is None:
            forward = self.data.xmat[self._root_body()].reshape(3, 3)[:, 0].copy()
        forward[2] = 0.0
        forward /= np.linalg.norm(forward) or 1.0
        left = np.cross(UP, forward)
        wheels = [self._anchor(m) for m, j in self.built.joints.items() if j.velocity]
        origin = np.mean(wheels, axis=0) if wheels else self.data.xpos[self._root_body()].copy()
        return forward, left, origin

    def _root_body(self) -> int:
        bodies = sorted(self.built.body_module)
        return next((b for b in bodies if self.model.body_parentid[b] == 0), bodies[0])

    def _local(self, vector: np.ndarray) -> np.ndarray:
        """Vecteur du monde -> (avant, gauche, haut)."""
        return np.array([vector @ self.forward, vector @ self.left, vector @ UP])

    def frame_text(self) -> str:
        return ("Directions below are given in the robot frame: forward, left, up. "
                + ("Forward is the direction of lidar angle 0." if self.built.lidars else
                   "Forward is the x axis of the base.") + self._rest_text())

    def _rest_text(self) -> str:
        """Où est le bout du bras en posture de repos (toutes les articulations à 0)."""
        if not any(not j.velocity for j in self.built.joints.values()):
            return ""
        tip = self._local(self.data.xpos[self._tip_body()] - self.data.xpos[self._root_body()]) * 100
        return (f" At rest (all joints at 0), the end of the arm is {round(tip[0]) + 0} cm forward, {round(tip[1]) + 0} cm left "
                f"and {round(tip[2]) + 0} cm up from the base.")

    def _joint_id(self, motor: str) -> int:
        return self.model.joint(self.built.joints[motor].joint_name).id

    def _anchor(self, motor: str) -> np.ndarray:
        return self.data.xanchor[self._joint_id(motor)].copy()

    def joint_direction(self, motor: str) -> float:
        joint = self.built.joints.get(motor)
        return joint.direction if joint else 1.0

    # ------------------------------------------------------------------ roues
    def _wheel_push(self, motor: str) -> np.ndarray | None:
        """Direction où la roue pousse le robot (repère du robot) pour une vitesse positive.
        Roue sans glissement : le centre de la roue avance de ω·r·(axe × haut)."""
        if motor not in self.built.joints:
            return None
        axis = self.data.xaxis[self._joint_id(motor)]
        push = self.joint_direction(motor) * np.cross(axis, UP)
        n = np.linalg.norm(push)
        return self._local(push / n) if n > 1e-6 else None

    def _wheel_yaw(self, motor: str) -> float:
        """> 0 : une vitesse positive fait tourner le robot vers la gauche (vu de dessus)."""
        push = self._wheel_push(motor)
        if push is None:
            return 0.0
        p = self._local(self._anchor(motor) - self.origin)
        return float(p[0] * push[1] - p[1] * push[0])

    def wheel_effect(self, motor: str) -> str:
        push = self._wheel_push(motor)
        if push is None:
            return ""
        p = self._local(self._anchor(motor) - self.origin)
        side = "left" if p[1] > 0 else "right"
        end = "front" if p[0] > 0 else "rear"
        if abs(push[0]) >= abs(push[1]):
            moves = "forward" if push[0] > 0 else "backward"
        else:
            moves = "to the left" if push[1] > 0 else "to the right"
        return f"This wheel is at the {end} {side}; a positive speed pushes the robot {moves}."

    def drive_presets(self, wheels: list[str], actions: dict[str, Any]) -> dict[str, dict[str, float]]:
        """Consignes des roues pour avancer, reculer et tourner sur place (60 % de la vitesse max)."""
        names = {m: f"{m}.velocity" for m in wheels}
        pushes = {m: self._wheel_push(m) for m in wheels}
        if any(p is None for p in pushes.values()) or any(n not in actions for n in names.values()):
            return {}
        ranges = [actions[names[m]].get_range() for m in wheels]
        v = round((min(r[1] for r in ranges) if all(ranges) else 100.0) * 0.6)
        forward = {m: float(np.sign(pushes[m][0]) or 1.0) for m in wheels}
        left = {m: float(np.sign(self._wheel_yaw(m)) or 1.0) for m in wheels}

        def preset(signs: dict[str, float], k: float = 1.0) -> dict[str, float]:
            return {names[m]: k * s * v + 0.0 for m, s in signs.items()}

        return {"Avancer": preset(forward), "Reculer": preset(forward, -1), "Tourner à gauche": preset(left),
                "Tourner à droite": preset(left, -1), "Arrêt": preset(forward, 0)}

    # ------------------------------------------------------------------ articulations
    def _tip_body(self) -> int:
        """Le bout du bras : le corps le plus éloigné du socle (sans les capteurs)."""
        root = self.data.xpos[self._root_body()]
        best, best_d = self._root_body(), -1.0
        for body, module in self.built.body_module.items():
            if module.startswith(("camera", "lidar")):
                continue
            d = float(np.linalg.norm(self.data.xpos[body] - root))
            if d > best_d:
                best, best_d = body, d
        return best

    def joint_effect(self, motor: str) -> str:
        """Effet d'une hausse de l'angle sur le bout du bras, mesuré en posture de repos."""
        joint = self.built.joints.get(motor)
        if joint is None or joint.velocity:
            return ""
        jid = self._joint_id(motor)
        axis = self._local(self.data.xaxis[jid])
        vertical = abs(axis[2]) > 0.9
        tip = self._tip_body()
        before = self.data.xpos[tip].copy()
        data = mujoco.MjData(self.model)
        data.qpos[:] = self.data.qpos
        data.qpos[self.model.jnt_qposadr[jid]] += np.deg2rad(joint.direction * PROBE_DEG)
        mujoco.mj_kinematics(self.model, data)
        delta = self._local(data.xpos[tip] - before) * 100        # cm
        parts = []
        for value, plus, minus in zip(delta, ("forward", "left", "up"), ("backward", "right", "down")):
            if abs(value) >= 0.5:
                parts.append(f"{abs(value):.1f} cm {plus if value > 0 else minus}")
        text = "Vertical axis: it turns the part above it around the vertical." if vertical else \
            "Horizontal axis: it tilts the part above it."
        if vertical:
            turn = joint.direction * np.sign(self.data.xaxis[jid][2])
            text += f" A higher angle turns it to the {'left' if turn > 0 else 'right'} (seen from above)."
        if parts:
            text += f" From the rest pose, +{PROBE_DEG:g}° moves the end of the arm " + ", ".join(parts) + "."
        return text
