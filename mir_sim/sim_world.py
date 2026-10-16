"""
Monde simulé : modèle MuJoCo + émulation des servos STS3215.

Deux façons de faire avancer la physique :
  - start_realtime() : un thread fait avancer la simu au rythme de l'horloge
    (téléopération, scripts existants via mirRobot qui ne font que lire/écrire)
  - step(n) : avance de n pas de façon synchrone (RL, aussi vite que possible)
"""
from __future__ import annotations
from pathlib import Path
from threading import Event, RLock, Thread, get_ident
from typing import Any
import time
import numpy as np
import mujoco
from loguru import logger
from mir_sim.model_builder import BuiltModel, build_model


class SimWorld:
    def __init__(self, built: BuiltModel):
        self.built = built
        self.model = built.model
        self.data = mujoco.MjData(self.model)
        self.lock = RLock()
        self.joints = built.joints
        self.motors = list(self.joints.keys())
        self._qpos_adr = {m: self.model.jnt_qposadr[self.model.joint(j.joint_name).id] for m, j in self.joints.items()}
        self._dof_adr = {m: self.model.jnt_dofadr[self.model.joint(j.joint_name).id] for m, j in self.joints.items()}
        self._act_id = {m: self.model.actuator(j.actuator_name).id for m, j in self.joints.items()}
        # consigne finale demandée par l'utilisateur ; data.ctrl la rejoint à vitesse limitée (comme le servo réel)
        self._goal = {m: 0.0 for m in self.motors}
        self._max_vel_rad_s = {m: np.deg2rad(built.max_velocity_deg_s.get(m, 360.0)) for m in self.motors}
        self._gain = {m: (self.model.actuator_gainprm[i].copy(), self.model.actuator_biasprm[i].copy())
                      for m, i in self._act_id.items()}
        self._torque_enabled = {m: True for m in self.motors}
        self._thread: Thread | None = None
        self._stop = Event()
        self._renderers: dict[tuple[int, int, int], mujoco.Renderer] = {}
        self.realtime_factor = 1.0
        self._users = 0
        self.reset()

    @staticmethod
    def from_config(robot_config: Any, scene: str | Path | dict[str, Any] | None = None) -> SimWorld:
        """robot_config : mirRobotConfig avec une section "structure" (ou chemin du fichier) ; scene : voir model_builder."""
        return SimWorld(build_model(robot_config, scene))

    # ------------------------------------------------------------------ physique
    def reset(self, motor_positions_deg: dict[str, float] | None = None) -> None:
        with self.lock:
            mujoco.mj_resetData(self.model, self.data)
            for m in self.motors:
                q = self.joints[m].motor_to_sim_rad((motor_positions_deg or {}).get(m, 0.0))
                q = self._clip_to_range(m, q)
                self.data.qpos[self._qpos_adr[m]] = q
                self.data.ctrl[self._act_id[m]] = q
                self._goal[m] = q
            mujoco.mj_forward(self.model, self.data)

    def step(self, n: int = 1) -> None:
        with self.lock:
            dt = self.model.opt.timestep
            for _ in range(n):
                self._update_servo_profiles(dt)
                mujoco.mj_step(self.model, self.data)

    def _update_servo_profiles(self, dt: float) -> None:
        for m in self.motors:
            i = self._act_id[m]
            if not self._torque_enabled[m]:
                continue
            delta = self._goal[m] - self.data.ctrl[i]
            max_delta = self._max_vel_rad_s[m] * dt
            self.data.ctrl[i] += float(np.clip(delta, -max_delta, max_delta))

    def _clip_to_range(self, motor: str, q: float) -> float:
        lo, hi = self.model.jnt_range[self.model.joint(self.joints[motor].joint_name).id]
        return float(np.clip(q, lo, hi))

    def acquire(self) -> None:
        """Un device se connecte : la physique tourne en temps réel tant qu'au moins un device est connecté."""
        with self.lock:
            self._users += 1
        self.start_realtime()

    def release(self) -> None:
        with self.lock:
            self._users = max(0, self._users - 1)
            users = self._users
        if users == 0:
            self.stop_realtime()
            self.close_renderers()

    def close_renderers(self) -> None:
        """Libère les contextes OpenGL des rendus. Sans cela, ils sont détruits à la sortie de Python,
        après la disparition de leur contexte, ce qui provoque une erreur de segmentation."""
        with self.lock:
            renderers, self._renderers = list(self._renderers.values()), {}
        for renderer in renderers:
            try:
                renderer.close()
            except Exception as e:
                logger.warning(f"fermeture du rendu : {e}")

    def start_realtime(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._realtime_loop, daemon=True, name="mir_sim_physics")
        self._thread.start()

    def stop_realtime(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _realtime_loop(self) -> None:
        wall_start = time.perf_counter()
        sim_start = self.data.time
        while not self._stop.is_set():
            target = sim_start + (time.perf_counter() - wall_start) * self.realtime_factor
            steps = int((target - self.data.time) / self.model.opt.timestep)
            if steps > 0:
                self.step(min(steps, 50))  # si on prend du retard, on ne cherche pas à tout rattraper d'un coup
                if steps > 50:
                    wall_start = time.perf_counter()
                    sim_start = self.data.time
            else:
                time.sleep(0.001)

    # ------------------------------------------------------------------ servos (unités moteur : degrés normalisés lerobot)
    def set_goal_positions(self, positions_deg: dict[str, float]) -> None:
        with self.lock:
            for m, deg in positions_deg.items():
                self._goal[m] = self._clip_to_range(m, self.joints[m].motor_to_sim_rad(float(deg)))

    def get_positions(self, motors: list[str] | None = None) -> dict[str, float]:
        with self.lock:
            return {m: self.joints[m].sim_rad_to_motor(self.data.qpos[self._qpos_adr[m]]) for m in (motors or self.motors)}

    def get_velocities_deg_s(self, motors: list[str] | None = None) -> dict[str, float]:
        with self.lock:
            return {m: float(np.rad2deg(self.data.qvel[self._dof_adr[m]]) * self.joints[m].direction)
                    for m in (motors or self.motors)}

    def get_load_ratios(self, motors: list[str] | None = None) -> dict[str, float]:
        """Effort actuel / effort max, entre -1 et 1."""
        with self.lock:
            result = {}
            for m in (motors or self.motors):
                i = self._act_id[m]
                max_force = self.model.actuator_forcerange[i][1]
                result[m] = float(self.data.actuator_force[i] / max_force) if max_force > 0 else 0.0
            return result

    def set_torque_enabled(self, motors: list[str] | None, enabled: bool) -> None:
        with self.lock:
            for m in (motors or self.motors):
                i = self._act_id[m]
                self._torque_enabled[m] = enabled
                gain, bias = self._gain[m]
                if enabled:
                    q = self.data.qpos[self._qpos_adr[m]]
                    self.data.ctrl[i] = q
                    self._goal[m] = q
                    self.model.actuator_gainprm[i] = gain
                    self.model.actuator_biasprm[i] = bias
                else:
                    self.model.actuator_gainprm[i] = 0
                    self.model.actuator_biasprm[i] = 0

    def hold_current_positions(self, motors: list[str] | None = None) -> None:
        with self.lock:
            for m in (motors or self.motors):
                q = self.data.qpos[self._qpos_adr[m]]
                self.data.ctrl[self._act_id[m]] = q
                self._goal[m] = q

    def is_moving(self, motors: list[str] | None = None, threshold_deg_s: float = 1.0) -> bool:
        return any(abs(v) > threshold_deg_s for v in self.get_velocities_deg_s(motors).values())

    # ------------------------------------------------------------------ rendu
    def render(self, camera: str, width: int, height: int) -> np.ndarray:
        """Image RGB (height, width, 3) uint8. Un renderer par thread (contexte OpenGL)."""
        key = (get_ident(), width, height)
        renderer = self._renderers.get(key)
        if renderer is None:
            renderer = mujoco.Renderer(self.model, height, width)
            self._renderers[key] = renderer
        with self.lock:
            renderer.update_scene(self.data, camera)
        return renderer.render()
