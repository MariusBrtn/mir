"""
Monde simulé : modèle MuJoCo + émulation des servos STS3215.

Servo simulé : un PID (le sien, voir SIM_PID_* de model_builder) calcule la tension du moteur à partir de l'écart
consigne - mesure, en position (servo) ou en vitesse (roue). La seule saturation est celle de l'alimentation (±12 V).
Le moteur à courant continu (inductance négligée) donne le couple : C = C_bloqué × (U / 12 V - ω / ω_à_vide).

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

TENSION_MAX = 12.0          # V, alimentation des servos : seule saturation de l'asservissement
# gains du PID simulé par unité de « registre » P, I, D. Écart en ° (position) ou en tr/min (vitesse),
# sortie en V. Ils ne sont pas calés sur le servo réel : mêmes registres, réponse différente.
GAINS_POSITION = (1.0, 1.0, 0.01)           # V/°, V/(°.s), V/(°/s)
GAINS_VITESSE = (0.01, 0.5, 0.0)            # V/(tr/min), V/(tr/min.s) ; pas de D : dériver une vitesse
#   bruitée par les contacts au sol rend la boucle instable avec le pas de 2 ms (le registre D est ignoré pour une roue)
RAD_S_TO_RPM = 60 / (2 * np.pi)


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
        # consigne du servo : position (rad) ou, pour une roue, vitesse (rad/s), dans le repère de la simulation
        self._goal = {m: 0.0 for m in self.motors}
        self._torque_enabled = {m: True for m in self.motors}
        # moteurs asservis en vitesse (roues)
        self._velocity = {m: j.velocity for m, j in self.joints.items()}
        # PID : réglage (unités des registres) et gains, intégrale et écart précédent de chaque servo ; tension appliquée
        self._pid: dict[str, tuple[float, float, float]] = {}
        self._gains: dict[str, tuple[float, float, float]] = {}
        self._integrale = {m: 0.0 for m in self.motors}
        self._ecart_prec: dict[str, float | None] = {m: None for m in self.motors}
        for m, j in self.joints.items():
            self.set_pid(m, j.pid)
        self._tension = {m: 0.0 for m in self.motors}
        self._couple = {m: 0.0 for m in self.motors}
        # lidars : (site de mesure, corps qui le porte, directions des rayons dans le repère du site)
        self._lidars: dict[str, tuple[int, int, np.ndarray]] = {}
        for name, lidar in built.lidars.items():
            site = self.model.site(name).id
            n = lidar["points"]
            angles = np.deg2rad(np.arange(n) * 360.0 / n)
            # angle croissant dans le sens horaire vu de dessus (z) : de x vers -y
            directions = np.column_stack([np.cos(angles), -np.sin(angles), np.zeros(n)])
            self._lidars[name] = (site, int(self.model.site_bodyid[site]), directions)
        # robot mobile : liaison libre de sa base (None si le robot est fixé au sol)
        self._robot_bodies = set(built.body_module)
        libres = [j for j in range(self.model.njnt) if self.model.jnt_type[j] == mujoco.mjtJoint.mjJNT_FREE
                  and self.model.jnt_bodyid[j] in self._robot_bodies]
        self._base = (int(self.model.jnt_bodyid[libres[0]]), int(self.model.jnt_qposadr[libres[0]]),
                      int(self.model.jnt_dofadr[libres[0]])) if libres else None
        self.base_body: int | None = self._base[0] if self._base else None      # corps de la base (caméra qui suit)
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
                self._reset_pid(m)
                if self._velocity[m]:
                    self._goal[m] = 0.0     # roue à l'arrêt
                    continue
                q = self.joints[m].motor_to_sim_rad((motor_positions_deg or {}).get(m, 0.0))
                q = self._clip_to_range(m, q)
                self.data.qpos[self._qpos_adr[m]] = q
                self._goal[m] = q
            mujoco.mj_forward(self.model, self.data)

    def step(self, n: int = 1) -> None:
        with self.lock:
            dt = self.model.opt.timestep
            for _ in range(n):
                self._asservir(dt)
                mujoco.mj_step(self.model, self.data)

    def advance(self, duration_s: float) -> float:
        """Avance la physique d'un nombre entier de pas, au plus près de duration_s (au moins un pas) ; renvoie la
        durée exacte. Pour un calcul pas à pas (essai, RL), le fil du temps réel doit être arrêté."""
        n = max(1, round(duration_s / self.model.opt.timestep))
        self.step(n)
        return n * self.model.opt.timestep

    def _asservir(self, dt: float) -> None:
        """Un pas de chaque servo : PID sur l'écart -> tension (±12 V) -> couple du moteur à courant continu."""
        for m in self.motors:
            i = self._act_id[m]
            vitesse = float(self.data.qvel[self._dof_adr[m]])
            if not self._torque_enabled[m]:
                tension = 0.0           # moteur débranché : il tourne librement
                couple = 0.0
            else:
                if self._velocity[m]:
                    ecart = (self._goal[m] - vitesse) * RAD_S_TO_RPM
                else:
                    ecart = float(np.rad2deg(self._goal[m] - self.data.qpos[self._qpos_adr[m]]))
                kp, ki, kd = self._gains[m]
                self._integrale[m] += ecart * dt
                precedent = self._ecart_prec[m]
                derivee = 0.0 if precedent is None else (ecart - precedent) / dt
                self._ecart_prec[m] = ecart
                tension = float(np.clip(kp * ecart + ki * self._integrale[m] + kd * derivee, -TENSION_MAX, TENSION_MAX))
                joint = self.joints[m]
                couple = joint.stall_torque * (tension / TENSION_MAX - vitesse / np.deg2rad(joint.no_load_speed_deg_s))
            self._tension[m] = tension
            self._couple[m] = couple
            self.data.ctrl[i] = couple

    def get_pid(self, motor: str) -> tuple[float, float, float]:
        """Réglage P, I, D du servo simulé (mêmes unités que les registres du servo réel)."""
        return self._pid[motor]

    def set_pid(self, motor: str, pid: tuple[float, float, float]) -> None:
        """Change le PID d'un servo simulé, sans reconstruire le modèle (le réglage par défaut revient au prochain
        modèle construit). Le D d'une roue est ignoré (voir GAINS_VITESSE)."""
        with self.lock:
            unites = GAINS_VITESSE if self._velocity[motor] else GAINS_POSITION
            self._pid[motor] = tuple(pid)
            self._gains[motor] = tuple(r * g for r, g in zip(pid, unites))
            self._reset_pid(motor)

    def _reset_pid(self, motor: str) -> None:
        self._integrale[motor] = 0.0
        self._ecart_prec[motor] = None

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
                if self._velocity[m]:
                    raise ValueError(f"{m} est asservi en vitesse : consigne de vitesse ({m}.velocity), pas de position")
                self._goal[m] = self._clip_to_range(m, self.joints[m].motor_to_sim_rad(float(deg)))

    def set_goal_velocities(self, velocities_rpm: dict[str, float]) -> None:
        """Consigne de vitesse des moteurs asservis en vitesse (roues), en tr/min. Pas de borne : au-delà de sa
        vitesse à vide, le moteur sature (12 V) et n'atteint pas la consigne."""
        with self.lock:
            for m, rpm in velocities_rpm.items():
                if not self._velocity.get(m):
                    raise ValueError(f"{m} n'est pas asservi en vitesse")
                self._goal[m] = float(np.deg2rad(float(rpm) * 6) * self.joints[m].direction)

    def is_velocity_motor(self, motor: str) -> bool:
        return self._velocity.get(motor, False)

    def get_positions(self, motors: list[str] | None = None) -> dict[str, float]:
        with self.lock:
            result = {}
            for m in (motors or self.motors):
                deg = self.joints[m].sim_rad_to_motor(self.data.qpos[self._qpos_adr[m]])
                # en mode vitesse, le servo réel donne sa position sur un tour
                result[m] = (deg + 180.0) % 360.0 - 180.0 if self._velocity[m] else deg
            return result

    def get_velocities_deg_s(self, motors: list[str] | None = None) -> dict[str, float]:
        with self.lock:
            return {m: float(np.rad2deg(self.data.qvel[self._dof_adr[m]]) * self.joints[m].direction)
                    for m in (motors or self.motors)}

    def get_load_ratios(self, motors: list[str] | None = None) -> dict[str, float]:
        """Tension appliquée / tension max, entre -1 et 1 (la « charge » du STS3215 est son rapport cyclique)."""
        with self.lock:
            return {m: self._tension[m] / TENSION_MAX for m in (motors or self.motors)}

    def get_torque_ratios(self, motors: list[str] | None = None) -> dict[str, float]:
        """Couple du moteur / couple rotor bloqué : le courant est proportionnel au couple."""
        with self.lock:
            return {m: self._couple[m] / self.joints[m].stall_torque for m in (motors or self.motors)}

    def set_torque_enabled(self, motors: list[str] | None, enabled: bool) -> None:
        with self.lock:
            for m in (motors or self.motors):
                self._torque_enabled[m] = enabled
                self._reset_pid(m)
                if enabled:
                    self._goal[m] = 0.0 if self._velocity[m] else self.data.qpos[self._qpos_adr[m]]

    def place_motor(self, motor: str, position_deg: float) -> None:
        """Met un servo (asservi en position) à cette position, immobile, consigne comprise : un départ identique
        quel que soit son réglage (avant un essai, par exemple, même avec un PID qui oscille)."""
        with self.lock:
            q = self._clip_to_range(motor, self.joints[motor].motor_to_sim_rad(float(position_deg)))
            self.data.qpos[self._qpos_adr[motor]] = q
            self.data.qvel[self._dof_adr[motor]] = 0.0
            self._goal[motor] = q
            self._reset_pid(motor)
            mujoco.mj_forward(self.model, self.data)

    def hold_current_positions(self, motors: list[str] | None = None) -> None:
        with self.lock:
            for m in (motors or self.motors):
                self._reset_pid(m)
                self._goal[m] = 0.0 if self._velocity[m] else self.data.qpos[self._qpos_adr[m]]    # roue : arrêt

    def is_moving(self, motors: list[str] | None = None, threshold_deg_s: float = 1.0) -> bool:
        return any(abs(v) > threshold_deg_s for v in self.get_velocities_deg_s(motors).values())

    # ------------------------------------------------------------------ objets de la scène
    def set_object_pose(self, name: str, pos: list[float] | np.ndarray, yaw_deg: float = 0.0,
                        forward: bool = True) -> None:
        """Replace un objet libre (ou "mocap") de la scène (position en m, rotation autour de la verticale), immobile.
        forward=False : ne recalcule pas la scène (pour en déplacer plusieurs d'affilée, puis appeler mj_forward)."""
        demi = np.radians(yaw_deg) / 2
        quat = [np.cos(demi), 0.0, 0.0, np.sin(demi)]
        with self.lock:
            mocap = self.model.body_mocapid[self.model.body(name).id]
            if mocap >= 0:
                self.data.mocap_pos[mocap] = pos
                self.data.mocap_quat[mocap] = quat
            else:
                joint = self.model.joint(f"{name}_free")
                adr, dof = self.model.jnt_qposadr[joint.id], self.model.jnt_dofadr[joint.id]
                self.data.qpos[adr:adr + 7] = [*pos, *quat]
                self.data.qvel[dof:dof + 6] = 0.0
            if forward:
                mujoco.mj_forward(self.model, self.data)

    def get_object_position(self, name: str) -> np.ndarray:
        """Position (m) du centre d'un objet de la scène."""
        with self.lock:
            return self.data.xpos[self.model.body(name).id].copy()

    # ------------------------------------------------------------------ base d'un robot mobile
    def set_robot_pose(self, x: float, y: float, yaw_deg: float = 0.0) -> None:
        """Pose la base du robot mobile au sol en (x, y) (m), tournée de yaw_deg autour de la verticale, immobile."""
        body, adr, dof = self._require_base()
        demi = np.radians(yaw_deg) / 2
        with self.lock:
            z = self.model.qpos0[adr + 2]       # hauteur de départ : roues posées au sol
            self.data.qpos[adr:adr + 7] = [x, y, z, np.cos(demi), 0.0, 0.0, np.sin(demi)]
            self.data.qvel[dof:dof + 6] = 0.0
            mujoco.mj_forward(self.model, self.data)

    def get_robot_pose(self) -> tuple[float, float, float]:
        """(x, y en m, cap en ° : direction de l'avant de la base, son axe x, vue de dessus)."""
        body, adr, dof = self._require_base()
        with self.lock:
            rot = self.data.xmat[body].reshape(3, 3)
            return (float(self.data.qpos[adr]), float(self.data.qpos[adr + 1]),
                    float(np.degrees(np.arctan2(rot[1, 0], rot[0, 0]))))

    def get_robot_velocity(self) -> tuple[float, float]:
        """(vitesse vers l'avant en m/s, vitesse de rotation autour de la verticale en rad/s), base du robot."""
        body, adr, dof = self._require_base()
        with self.lock:
            rot = self.data.xmat[body].reshape(3, 3)
            avant = float(self.data.qvel[dof:dof + 3] @ rot[:, 0])      # vitesse linéaire : repère du monde
            rotation = float(rot @ self.data.qvel[dof + 3:dof + 6] @ [0, 0, 1])    # vitesse angulaire : repère local
            return avant, rotation

    def is_robot_upright(self, max_tilt_deg: float = 45.0) -> bool:
        body, _, _ = self._require_base()
        with self.lock:
            return float(self.data.xmat[body].reshape(3, 3)[2, 2]) > np.cos(np.radians(max_tilt_deg))

    def robot_contacts(self) -> set[str]:
        """Objets de la scène que le robot touche (le sol n'en fait pas partie)."""
        with self.lock:
            touches = set()
            for contact in self.data.contact[:self.data.ncon]:
                a, b = self.model.geom_bodyid[contact.geom1], self.model.geom_bodyid[contact.geom2]
                if (a in self._robot_bodies) == (b in self._robot_bodies):
                    continue        # contact interne au robot, ou entre deux objets
                autre = b if a in self._robot_bodies else a
                if autre != 0:      # corps 0 : le monde, qui porte le sol
                    touches.add(self.model.body(autre).name)
            return touches

    def _require_base(self) -> tuple[int, int, int]:
        if self._base is None:
            raise ValueError("le robot est fixé au sol : il n'a pas de base mobile")
        return self._base

    # ------------------------------------------------------------------ lidar
    def lidar_scan(self, name: str, range_m: tuple[float, float] = (0.05, 12.0)) -> tuple[np.ndarray, np.ndarray]:
        """Un tour du lidar : (angles en degrés, distances en m ; 0 si rien n'est touché dans la portée).
        Les rayons touchent les pièces visibles (STL, objets, sol), pas le lidar lui-même."""
        site, body, directions = self._lidars[name]
        n = len(directions)
        geomid = np.zeros(n, np.int32)
        dist = np.zeros(n)
        groupes = np.array([1, 1, 1, 0, 0, 0], np.uint8)    # pas les formes de contact (3) ni les pastilles (4)
        with self.lock:
            origine = self.data.site_xpos[site].copy()
            rot = self.data.site_xmat[site].reshape(3, 3)
            vec = (directions @ rot.T).flatten()
            mujoco.mj_multiRay(self.model, self.data, origine, vec, groupes, 1, body, geomid, dist, None, n, range_m[1])
        dist[(geomid < 0) | (dist < range_m[0]) | (dist > range_m[1])] = 0.0
        return np.arange(n) * 360.0 / n, dist

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
