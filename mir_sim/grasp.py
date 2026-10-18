"""
Modèle géométrique d'un bras qui porte une pince MIR (module mir_pince) : où est le point de saisie, et quels
angles moteurs l'amènent sur un objet. Sert à écrire des démonstrations automatiques en simulation.

    ik = GripperIK(world)                                   # world : SimWorld du robot
    angles = ik.solve([0.19, 0.0, 0.008])                   # {"joint_1": ..., "joint_4": ...} en degrés moteur, ou None
    point, doigts, serrage = ik.forward(angles)

Le point de saisie est le centre de l'ouverture de la pince OUVERTE : seul le mors mobile s'écarte, ce centre est
donc décalé vers lui. Si le bras a au moins 4 articulations, le MGI impose aussi des mors qui serrent à
l'horizontale (sur deux faces verticales de l'objet). Parmi les solutions (coude haut ou bas...), il garde celle où
les doigts pointent le plus vers le bas.
"""
from __future__ import annotations
import numpy as np
import mujoco
from mir_sim.sim_world import SimWorld

OPEN_DEG = -14.0                # ouverture maximale de la pince (un angle positif ferme)
TOLERANCE_M = 5e-4              # écart accepté sur la position du point de saisie
CLOSING_WEIGHT = 0.05           # poids de la contrainte « serrage horizontal » face à l'erreur de position (m)


class GripperIK:
    def __init__(self, world: SimWorld, open_deg: float = OPEN_DEG):
        self.world = world
        m = world.model
        self.gripper_motor = self._gripper_motor(world)
        # bras : les moteurs asservis en position autres que celui de la pince, dans l'ordre de la structure
        self.arm = [mot for mot in world.motors if mot != self.gripper_motor and not world.is_velocity_motor(mot)]
        self._support = next(i for i in range(m.nbody) if m.body(i).name.endswith("_support"))
        fixe = next(i for i in range(m.ngeom) if m.geom(i).name.endswith("mors_fixe"))
        mobile = next(i for i in range(m.ngeom) if m.geom(i).name.endswith("mors_mobile"))
        self._data = mujoco.MjData(m)           # données à part : le MGI ne touche pas à la simulation en cours
        self._qadr = {mot: m.jnt_qposadr[m.joint(j.joint_name).id] for mot, j in world.joints.items()}
        self._range = {mot: sorted(world.joints[mot].sim_rad_to_motor(v)
                                   for v in m.jnt_range[m.joint(world.joints[mot].joint_name).id]) for mot in self.arm}

        # point de saisie et direction de serrage dans le repère du support de la pince, pince ouverte
        self._set({self.gripper_motor: open_deg})
        rot = self._data.xmat[self._support].reshape(3, 3)
        origine = self._data.xpos[self._support]
        pf = rot.T @ (self._data.geom_xpos[fixe] - origine)
        pm = rot.T @ (self._data.geom_xpos[mobile] - origine)
        self.point_local = np.array([(pf[0] + pm[0]) / 2, (pf[1] + pm[1]) / 2, pf[2]])
        self.fingers_local = np.array([1.0, 0.0, 0.0])      # les doigts s'étendent selon x (repère CAO de la pince)
        self.closing_local = np.array([0.0, 1.0, 0.0])      # perpendiculaire au mors fixe

    @staticmethod
    def _gripper_motor(world: SimWorld) -> str:
        """Moteur de la pince : celui dont l'articulation porte le mors mobile."""
        m = world.model
        for mot, j in world.joints.items():
            corps = m.body(m.jnt_bodyid[m.joint(j.joint_name).id]).name
            if corps.endswith("_mors"):
                return mot
        raise ValueError("le robot n'a pas de pince MIR (module mir_pince)")

    def _set(self, angles_deg: dict[str, float]) -> None:
        for mot, deg in angles_deg.items():
            self._data.qpos[self._qadr[mot]] = self.world.joints[mot].motor_to_sim_rad(float(deg))
        mujoco.mj_kinematics(self.world.model, self._data)

    def forward(self, angles_deg: dict[str, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Angles moteur (°) -> (point de saisie en m, direction des doigts, direction de serrage), repère monde."""
        self._set(angles_deg)
        rot = self._data.xmat[self._support].reshape(3, 3)
        return (self._data.xpos[self._support] + rot @ self.point_local, rot @ self.fingers_local,
                rot @ self.closing_local)

    def _residual(self, q: np.ndarray, target: np.ndarray) -> np.ndarray:
        point, _, closing = self.forward(dict(zip(self.arm, q)))
        if len(self.arm) >= 4:
            return np.r_[point - target, CLOSING_WEIGHT * closing[2]]
        return point - target

    def _solve_from(self, target: np.ndarray, start: np.ndarray, iterations: int = 60) -> tuple[np.ndarray, bool]:
        """Gauss-Newton amorti, jacobienne par différences finies, angles bornés aux butées."""
        q = start.astype(float)
        lo = np.array([self._range[mot][0] for mot in self.arm])
        hi = np.array([self._range[mot][1] for mot in self.arm])
        for _ in range(iterations):
            e = self._residual(q, target)
            if np.linalg.norm(e[:3]) < TOLERANCE_M and (len(e) == 3 or abs(e[3]) < 1e-3):
                return q, True
            pas = 1e-3
            jac = np.column_stack([(self._residual(q + h, target) - e) / pas for h in np.eye(len(q)) * pas])
            q = np.clip(q - np.linalg.solve(jac.T @ jac + 1e-6 * np.eye(len(q)), jac.T @ e), lo, hi)
        return q, False

    def solve(self, target: list[float] | np.ndarray, start: dict[str, float] | None = None) -> dict[str, float] | None:
        """Angles moteur (°) du bras qui amènent le point de saisie en target (m, repère monde), ou None.
        start : solution voisine (ex. la saisie, pour l'approche juste au-dessus) ; sinon, plusieurs départs."""
        target = np.asarray(target, float)
        if start is not None:
            q, ok = self._solve_from(target, np.array([start[mot] for mot in self.arm]))
            return dict(zip(self.arm, q.tolist())) if ok else None
        solutions = []
        valeurs = (-70.0, -35.0, 0.0, 35.0, 70.0)
        for base in (-60.0, 0.0, 60.0):
            for a in valeurs:
                for b in valeurs:
                    for c in (-80.0, 0.0, 80.0):
                        depart = np.array([base, a, b, c][:len(self.arm)] + [0.0] * max(0, len(self.arm) - 4))
                        q, ok = self._solve_from(target, depart)
                        if ok:
                            solutions.append((self.forward(dict(zip(self.arm, q)))[1][2], q))
        if not solutions:
            return None
        q = min(solutions, key=lambda s: s[0])[1]           # doigts le plus vers le bas
        return dict(zip(self.arm, q.tolist()))
