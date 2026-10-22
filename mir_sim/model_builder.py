"""
Construit le modèle MuJoCo d'un robot à partir de la section "structure" de sa configuration
(mirRobotConfig) et des modules du catalogue (catalog/<type>.json).

Un module du catalogue décrit une pièce MIR, dans le repère de sa CAO, articulations à zéro :
  - "parts"      : pièces rigides {nom: {"mass", "geoms"}} (ex. stator, rotor)
  - "joints"     : articulations {nom: {"parent", "child", "pos", "axis"}} entre deux pièces (facultatif)
  - "connectors" : prises baïonnette {nom: {"part", "gender": "male"|"female", "pos", "zaxis", "xaxis"}}
                   z sort du module (vers le module branché), le détrompeur est côté -x.
                   Deux connecteurs branchés ont la même origine, des z opposés et des x alignés.
  - "sensors"    : capteurs portés {nom: {"type": "camera", "part", "pos", "zaxis", "xaxis", "fovy"}}
                   (une caméra MuJoCo regarde selon -z de son repère, le haut de l'image selon +y)
                   ou {"type": "lidar", "part", "pos", "zaxis", "xaxis", "points", "range_m"} : pos = centre de la
                   fenêtre de mesure, z = haut du lidar, x = angle 0 ; angles croissants dans le sens horaire vu de dessus
  - une articulation "mode": "velocity" (roue) est asservie en vitesse : rotation continue, sans butées
  - "contact_pairs" : paires [geom1, geom2] (champ "name" des géométries) de pièces du module qui doivent
                   pouvoir se toucher (MuJoCo ignore sinon les contacts entre corps parent et enfant)
Géométries : "visual_only" (affichage), "collision_only" (contacts, masquées), "stiff_contact" (surface de
préhension), "select" (ne garder qu'une zone d'un STL, pour la colorer à part).

Structure d'un robot (section "structure" de la config) :
  {"modules": {
      "socle":   {"type": "mir_socle", "fixed": true},
      "servo_1": {"type": "mir_servo", "on": "socle.dessus", "connector": "rotor", "motor": "joint_1"},
      "camera":  {"type": "mir_camera", "on": "pince.camera", "connector": "embout", "sensors": {"objectif": "cam_1"}},
      ...}}
  - le module sans "on" est la racine ; "fixed": true en fait le bâti (fixé au monde), sinon le robot est
    libre (robot mobile)
  - "on" : "<module>.<connecteur>" sur lequel il est branché, "connector" : son propre connecteur utilisé
  - "motor" : moteur de la config qui entraîne l'articulation du module ("motors": {articulation: moteur}
    s'il en a plusieurs) ; "direction" (-1 si le moteur réel tourne dans l'autre sens), "zero_offset_deg"
  - "sensors" : {capteur du module: capteur de la config}
Un module peut être branché par n'importe lequel de ses connecteurs : un servo branché par son rotor a son
stator mobile (le sens du moteur est conservé).

Scène (fichier JSON propre à une tâche, facultatif) : {"robot": {"pos", "euler_deg"}, "table": {...},
"cameras": [...], "objects": [...], "lights": [...]}
  - "lights" (facultatif) : remplace l'éclairage par défaut (LUMIERES_DEFAUT) ; chaque lumière :
    {"name", "type": "directional" (soleil) ou "spot" (projecteur), "pos", "dir" ou "target" (point visé),
     "diffuse", "specular", "castshadow", "cutoff" (demi-angle du cône d'un projecteur, °), "exponent"}.
    Les ombres d'un soleil couvrent toute la scène : dans une grande scène, elles sont grossières. Celles d'un
    projecteur ne couvrent que son cône : pour une grande scène, un projecteur au-dessus de la zone utile.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import numpy as np
import mujoco

CATALOG_DIR = Path(__file__).parent / "catalog"
STS3215_RESOLUTION = 4095
# contact raide pour les objets légers saisis (sinon un dé de quelques grammes s'enfonce de plusieurs mm dans les mors)
STIFF_SOLREF = [0.004, 1.0]
STIFF_SOLIMP = [0.99, 0.999, 0.001]
DEFAULT_RANGE_DEG = (-90.0, 90.0)   # plage d'une articulation sans calibration ni plage dans le catalogue
VELOCITY_MODE = 1           # OperatingMode.VELOCITY du STS3215
# rendu : couleurs du catalogue = vraies couleurs ; à l'écran, un noir pur écrase les volumes dans l'ombre
NOIR_AFFICHE = 0.17         # luminance minimale des couleurs sombres (PLA noir -> gris très foncé)
MATIERE = {"specular": 0.15, "shininess": 0.3}      # plastique mat : reflets doux
MATIERE_BRILLANTE = {"specular": 1.0, "shininess": 0.8}     # "glossy" : verre, optique (œil du lidar)
DEFAULT_STALL_TORQUE = 2.9  # N.m, STS3215 alimenté en 12V (≈1.9 N.m en 7.4V)
DEFAULT_NO_LOAD_SPEED_DEG_S = 270.0     # STS3215 à vide en 12V : 0,222 s pour 60° (45 tr/min)
# PID du servo simulé (unités des registres P, I, D, gains dans sim_world.GAINS_*) : propre à la simulation,
# indépendant de la configuration (dont les P, I, D sont ceux du servo réel). Réglages par défaut, cherchés sur des
# échelons du bras 4 ddl (avec et sans gravité, 10° et 45°) et du robot mobile :
# - position : PD, le plus rapide sans dépassement ; écart dû à la gravité ≤ 0,04°, sous la résolution du capteur
#   (0,088°). Un terme I ne ferait qu'empirer : il s'accumule pendant que la tension sature (pas d'anti-emballement) ;
# - vitesse (roues) : PI, sans dépassement ni écart statique, ≈ 50 ms.
SIM_PID_POSITION = (45, 0, 60)
SIM_PID_VELOCITY = (25, 32, 0)
# un connecteur branché sur un autre : demi-tour autour de x (z opposés, détrompeurs alignés)
FLIP_X = np.array([0.0, 1.0, 0.0, 0.0])
MATING_GENDERS = {("male", "female"), ("female", "male")}
# type de capteur de la configuration -> type de capteur porté par les modules du catalogue
SENSOR_KINDS = {"pi_camera": "camera", "esp_lidar": "lidar"}
# arène par défaut d'un robot mobile : 3 x 3 m, murs de 20 cm, deux obstacles
_MUR = {"type": "box", "free": False, "rgba": [0.62, 0.57, 0.5, 1]}
ARENE = [
    {**_MUR, "name": "mur_nord", "size": [1.5, 0.02, 0.1], "pos": [0, 1.5, 0.1]},
    {**_MUR, "name": "mur_sud", "size": [1.5, 0.02, 0.1], "pos": [0, -1.5, 0.1]},
    {**_MUR, "name": "mur_est", "size": [0.02, 1.5, 0.1], "pos": [1.5, 0, 0.1]},
    {**_MUR, "name": "mur_ouest", "size": [0.02, 1.5, 0.1], "pos": [-1.5, 0, 0.1]},
    {"type": "box", "free": False, "name": "obstacle_1", "size": [0.15, 0.15, 0.1], "pos": [0.7, 0.6, 0.1],
     "rgba": [0.35, 0.42, 0.52, 1]},
    {"type": "cylinder", "free": False, "name": "obstacle_2", "size": [0.12, 0.1], "pos": [-0.6, -0.5, 0.1],
     "rgba": [0.35, 0.42, 0.52, 1]},
]
# éclairage de studio : une lumière principale qui porte des ombres douces, une lumière d'appoint (la lumière ambiante
# vient de la lampe frontale de MuJoCo, réglée dans _add_scene)
LUMIERES_DEFAUT = [
    {"name": "principale", "type": "directional", "pos": [0.6, -0.8, 1.6], "dir": [-0.35, 0.45, -1.0],
     "diffuse": [0.62, 0.62, 0.6], "specular": [0.6, 0.6, 0.6], "castshadow": True},
    {"name": "appoint", "type": "directional", "pos": [-1.0, 0.8, 1.2], "dir": [0.6, -0.5, -0.6],
     "diffuse": [0.22, 0.22, 0.24], "specular": [0.35, 0.35, 0.35], "castshadow": False},
]
TYPES_LUMIERE = {"directional": mujoco.mjtLightType.mjLIGHT_DIRECTIONAL, "spot": mujoco.mjtLightType.mjLIGHT_SPOT}
# pastilles des connecteurs libres (éditeur de structure) : groupe de géométries masqué par défaut au rendu
CONNECTOR_MARKER_GROUP = 4
CONNECTOR_MARKER_PREFIX = "connecteur:"
# maillages découpés par "select" (lents à calculer), réutilisés d'une construction à l'autre
_CLIPPED_MESHES: dict[tuple[str, str], np.ndarray] = {}


class StructureError(ValueError):
    """Structure de robot invalide ; errors contient la liste des problèmes."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("structure du robot invalide :\n  - " + "\n  - ".join(errors))


@dataclass
class SimJointInfo:
    motor: str
    joint_name: str
    actuator_name: str
    direction: float = 1.0
    zero_offset_deg: float = 0.0
    range_deg: tuple[float, float] = (-180.0, 180.0)  # dans le repère moteur (degrés normalisés lerobot)
    velocity: bool = False      # asservi en vitesse (roue) : rotation continue, consigne en tr/min
    pid: tuple[float, float, float] = SIM_PID_POSITION  # PID du servo simulé (unités des registres P, I, D)
    stall_torque: float = DEFAULT_STALL_TORQUE          # couple rotor bloqué sous 12 V (N.m)
    no_load_speed_deg_s: float = DEFAULT_NO_LOAD_SPEED_DEG_S    # vitesse à vide sous 12 V

    def motor_to_sim_rad(self, motor_deg: float) -> float:
        return float(np.deg2rad(self.direction * motor_deg + self.zero_offset_deg))

    def sim_rad_to_motor(self, sim_rad: float) -> float:
        return float((np.rad2deg(sim_rad) - self.zero_offset_deg) * self.direction)


@dataclass
class MotorParams:
    """Paramètres moteur issus de la configuration du robot (mirRobotConfig)."""
    range_deg: tuple[float, float] | None = None   # None : pas de calibration, plage par défaut du module (catalogue)
    velocity: bool = False              # moteur en mode vitesse (operating_mode VELOCITY de la configuration)


@dataclass
class BuiltModel:
    spec: mujoco.MjSpec
    model: mujoco.MjModel
    joints: dict[str, SimJointInfo] = field(default_factory=dict)
    max_velocity_deg_s: dict[str, float] = field(default_factory=dict)   # vitesse à vide sous 12 V
    body_module: dict[int, str] = field(default_factory=dict)        # id du corps -> module de la structure
    connector_markers: dict[int, str] = field(default_factory=dict)  # id de la pastille -> "module.connecteur" libre
    lidars: dict[str, dict[str, Any]] = field(default_factory=dict)  # capteur de la config -> {"points", "range_m"}


def euler_deg_to_quat(euler_deg: list[float] | None) -> np.ndarray:
    quat = np.zeros(4)
    mujoco.mju_euler2Quat(quat, np.deg2rad(euler_deg or [0, 0, 0]), "xyz")
    return quat


def frame_from_dict(d: dict[str, Any] | None, scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Repère {"pos", "euler_deg"} ou {"pos", "zaxis", "xaxis"} -> (pos en mètres, quaternion)."""
    if not d:
        return np.zeros(3), np.array([1.0, 0, 0, 0])
    pos = np.asarray(d.get("pos", [0, 0, 0]), float) * scale
    if "zaxis" in d:
        z = np.asarray(d["zaxis"], float)
        z /= np.linalg.norm(z)
        x = np.asarray(d.get("xaxis", [1, 0, 0] if abs(z[0]) < 0.9 else [0, 0, 1]), float)
        x -= z * np.dot(x, z)
        x /= np.linalg.norm(x)
        quat = np.zeros(4)
        mujoco.mju_mat2Quat(quat, np.column_stack([x, np.cross(z, x), z]).flatten())
        return pos, quat
    return pos, euler_deg_to_quat(d.get("euler_deg"))


def compose(pos_a: np.ndarray, quat_a: np.ndarray, pos_b: np.ndarray, quat_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Repère b exprimé dans a -> repère b exprimé dans le parent de a."""
    pos, quat = np.zeros(3), np.zeros(4)
    mujoco.mju_mulPose(pos, quat, pos_a, quat_a, pos_b, quat_b)
    return pos, quat


def invert(pos: np.ndarray, quat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    inv_pos, inv_quat = np.zeros(3), np.zeros(4)
    mujoco.mju_negPose(inv_pos, inv_quat, pos, quat)
    return inv_pos, inv_quat


def load_stl(path: str | Path) -> np.ndarray:
    """Triangles d'un STL (binaire ou ASCII), tableau (n, 3, 3)."""
    data = Path(path).read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:512]:
        verts = [line.split()[1:4] for line in data.decode(errors="ignore").splitlines() if line.strip().startswith("vertex")]
        return np.asarray(verts, float).reshape(-1, 3, 3)
    count = int(np.frombuffer(data[80:84], "<u4")[0])
    records = np.frombuffer(data[84:84 + count * 50], np.dtype([("n", "<3f4"), ("v", "<9f4"), ("attr", "<u2")]))
    return records["v"].reshape(-1, 3, 3).astype(float)


def clip_triangles(triangles: np.ndarray, normal: np.ndarray, offset: float) -> np.ndarray:
    """Garde la partie des triangles du côté normal·p >= offset, en coupant ceux qui traversent le plan."""
    dist = triangles @ normal - offset
    inside = dist >= 0
    out = [triangles[inside.all(axis=1)]]
    for tri, d in zip(triangles[inside.any(axis=1) & ~inside.all(axis=1)], dist[inside.any(axis=1) & ~inside.all(axis=1)]):
        poly = []
        for i in range(3):
            j = (i + 1) % 3
            if d[i] >= 0:
                poly.append(tri[i])
            if (d[i] >= 0) != (d[j] >= 0):
                poly.append(tri[i] + (tri[j] - tri[i]) * d[i] / (d[i] - d[j]))
        out.extend(np.array([[poly[0], poly[k], poly[k + 1]]]) for k in range(1, len(poly) - 1))
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def lookat_quat(pos: list[float], target: list[float]) -> np.ndarray:
    """Orientation d'une caméra MuJoCo (regarde selon -z, haut selon +y) placée en pos et visant target."""
    forward = np.asarray(target, float) - np.asarray(pos, float)
    forward /= np.linalg.norm(forward)
    up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(forward, up)) > 0.99:
        up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    cam_up = np.cross(right, forward)
    rot = np.column_stack([right, cam_up, -forward])
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, rot.flatten())
    return quat


def motor_params_from_config(config: Any) -> dict[str, MotorParams]:
    """Extrait plages et modes d'une mirRobotConfig (positions normalisées comme lerobot : 0° au milieu de la plage).
    Les P, I, D de la configuration (servo réel) ne servent pas : le servo simulé a les siens (SIM_PID_*)."""
    params: dict[str, MotorParams] = {}
    if config is None or config.motor_bus is None:
        return params
    for name, motor in config.motor_bus.motors.items():
        p = MotorParams(velocity=int(getattr(motor.operating_mode, "value", motor.operating_mode)) == VELOCITY_MODE)
        cal = config.motor_bus.calibration.get(name)
        if cal is not None:
            half = (cal.range_max - cal.range_min) / 2 * 360 / STS3215_RESOLUTION
            p.range_deg = (-half, half)
        params[name] = p
    return params


def load_catalog(catalog_dir: str | Path = CATALOG_DIR) -> dict[str, dict[str, Any]]:
    """Modules disponibles {type: description}, un fichier JSON par module."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(Path(catalog_dir).glob("*.json"))}


def motor_module_types(catalog: dict[str, dict[str, Any]]) -> list[str]:
    """Types de module qui contiennent un moteur (une articulation) : servo, pince..."""
    # les modules réservés au bras leader ne se choisissent pas pour un robot
    return [t for t, module in catalog.items() if len(module.get("joints", {})) == 1 and not module.get("leader_only")]


def sensor_module_types(catalog: dict[str, dict[str, Any]], sensor_type: str) -> list[str]:
    """Types de module qui portent un capteur de ce type de la configuration (ex. pi_camera -> module caméra)."""
    kind = SENSOR_KINDS.get(sensor_type)
    return [t for t, module in catalog.items()
            if kind is not None and any(s.get("type") == kind for s in module.get("sensors", {}).values())]


def module_sensor_key(module: dict[str, Any], sensor_type: str) -> str | None:
    """Capteur du module qui correspond à ce type de capteur de la configuration."""
    kind = SENSOR_KINDS.get(sensor_type)
    return next((key for key, s in module.get("sensors", {}).items() if s.get("type") == kind), None)


ROOT_TYPE = "mir_socle"


def hardware_module_name(module_type: str, hardware: str) -> str:
    """Nom du module qui représente un moteur ou un capteur de la config, ex. servo_joint_1, camera_cam_1."""
    return f"{module_type.removeprefix('mir_')}_{hardware}"


def initial_structure(catalog: dict[str, dict[str, Any]], motor_types: dict[str, str],
                      sensor_types: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Ébauche de structure après la découverte du matériel : le socle (bâti) et un module non placé par
    moteur {moteur: type de module} et par capteur {capteur: (type de capteur config, type de module)}."""
    unplaced: dict[str, dict[str, Any]] = {}
    for motor, module_type in motor_types.items():
        unplaced[hardware_module_name(module_type, motor)] = {"type": module_type, "motor": motor}
    for sensor, (sensor_type, module_type) in sensor_types.items():
        key = module_sensor_key(catalog[module_type], sensor_type)
        unplaced[hardware_module_name(module_type, sensor)] = {"type": module_type, "sensors": {key: sensor}}
    return {"modules": {"socle": {"type": ROOT_TYPE, "fixed": True}}, "unplaced": unplaced}


def check_structure(structure: dict[str, Any] | None, catalog: dict[str, dict[str, Any]],
                    motors: list[str] | None = None, sensors: list[str] | None = None) -> list[str]:
    """Liste des problèmes de la structure (vide si elle est valide).
    motors / sensors : moteurs et capteurs de la config, pour vérifier les associations (None : pas de vérification).
    Les modules de "unplaced" (détectés mais pas encore branchés) sont vérifiés mais pas construits."""
    if not structure or not structure.get("modules"):
        return ["aucun module dans la structure"]
    instances: dict[str, dict[str, Any]] = structure["modules"]
    errors: list[str] = []
    roots = [name for name, inst in instances.items() if "on" not in inst]
    if len(roots) != 1:
        errors.append(f"il faut exactement un module racine (sans \"on\"), trouvés : {roots or 'aucun'}")
    used_connectors: dict[str, str] = {}
    used_motors: dict[str, str] = {}
    unplaced: dict[str, dict[str, Any]] = structure.get("unplaced", {})
    for name in unplaced:
        if name in instances:
            errors.append(f"{name} : nom utilisé à la fois par un module placé et un module non placé")
    for name, inst in list(instances.items()) + list(unplaced.items()):
        module = catalog.get(inst.get("type", ""))
        if module is None:
            errors.append(f"{name} : type de module inconnu '{inst.get('type')}'")
            continue
        joints = module.get("joints", {})
        motor_map = inst.get("motors", {})
        if "motor" in inst:
            if len(joints) != 1:
                errors.append(f"{name} : \"motor\" n'est possible que pour un module à une articulation, utiliser \"motors\"")
            else:
                motor_map = {next(iter(joints)): inst["motor"]}
        for joint, motor in motor_map.items():
            if joint not in joints:
                errors.append(f"{name} : articulation '{joint}' inconnue pour {inst['type']}")
            if motors is not None and motor not in motors:
                errors.append(f"{name} : moteur '{motor}' absent de la configuration")
            if motor in used_motors:
                errors.append(f"{name} : moteur '{motor}' déjà utilisé par {used_motors[motor]}")
            used_motors[motor] = name
        for key, sensor in inst.get("sensors", {}).items():
            if key not in module.get("sensors", {}):
                errors.append(f"{name} : capteur '{key}' inconnu pour {inst['type']}")
            if sensors is not None and sensor not in sensors:
                errors.append(f"{name} : capteur '{sensor}' absent de la configuration")
        if "on" not in inst or name in unplaced:
            continue
        own = inst.get("connector")
        if own not in module.get("connectors", {}):
            errors.append(f"{name} : connecteur '{own}' inconnu pour {inst['type']}")
            continue
        parent_name, _, parent_conn = str(inst["on"]).partition(".")
        parent = instances.get(parent_name)
        parent_module = catalog.get(parent.get("type", "")) if parent else None
        if parent_module is None:
            errors.append(f"{name} : branché sur '{inst['on']}', module '{parent_name}' inconnu")
            continue
        if parent_conn not in parent_module.get("connectors", {}):
            errors.append(f"{name} : branché sur '{inst['on']}', connecteur '{parent_conn}' inconnu pour {parent['type']}")
            continue
        genders = (module["connectors"][own]["gender"], parent_module["connectors"][parent_conn]["gender"])
        if genders not in MATING_GENDERS:
            errors.append(f"{name} : '{own}' ({genders[0]}) ne peut pas se brancher sur '{inst['on']}' ({genders[1]})")
        for key in (f"{name}.{own}", str(inst["on"])):
            if key in used_connectors:
                errors.append(f"connecteur {key} utilisé deux fois ({used_connectors[key]} et {name})")
            used_connectors[key] = name
    # tous les modules doivent descendre de la racine (pas de cycle, pas de module isolé)
    if len(roots) == 1 and not errors:
        reached, todo = {roots[0]}, [roots[0]]
        while todo:
            current = todo.pop()
            for name, inst in instances.items():
                if str(inst.get("on", "")).partition(".")[0] == current and name not in reached:
                    reached.add(name)
                    todo.append(name)
        for name in instances:
            if name not in reached:
                errors.append(f"{name} : pas relié au module racine {roots[0]} (boucle ?)")
    return errors


class ModelBuilder:
    GEOM_TYPES = {
        "box": mujoco.mjtGeom.mjGEOM_BOX,
        "cylinder": mujoco.mjtGeom.mjGEOM_CYLINDER,
        "capsule": mujoco.mjtGeom.mjGEOM_CAPSULE,
        "sphere": mujoco.mjtGeom.mjGEOM_SPHERE,
        "ellipsoid": mujoco.mjtGeom.mjGEOM_ELLIPSOID,
        "mesh": mujoco.mjtGeom.mjGEOM_MESH,
    }

    def __init__(self, structure: dict[str, Any], motor_params: dict[str, MotorParams] | None = None,
                 scene: dict[str, Any] | None = None, catalog_dir: str | Path = CATALOG_DIR,
                 motors: list[str] | None = None, sensors: list[str] | None = None, connector_markers: bool = False):
        self._catalog_dir = Path(catalog_dir).resolve()
        self._catalog = load_catalog(self._catalog_dir)
        errors = check_structure(structure, self._catalog, motors, sensors)
        if errors:
            raise StructureError(errors)
        self._instances: dict[str, dict[str, Any]] = structure["modules"]
        self._motor_params = motor_params or {}
        self._scene = scene or {}
        self._mesh_names: dict[tuple[str, float, str], str] = {}
        self._materials: dict[tuple[float, ...], str] = {}
        self._connector_markers = connector_markers

    def build(self) -> BuiltModel:
        spec = mujoco.MjSpec()
        spec.modelname = "mir_robot"
        spec.compiler.degree = False
        spec.option.timestep = 0.002
        spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
        # frottement elliptique : les objets serrés dans la pince ne glissent pas
        spec.option.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
        spec.option.impratio = 10
        self._add_scene(spec)

        self._joints: dict[str, SimJointInfo] = {}
        self._max_vel: dict[str, float] = {}
        self._part_bodies: dict[str, dict[str, Any]] = {}
        self._geom_body: dict[str, str] = {}
        self._marker_names: list[str] = []
        self._lidars: dict[str, dict[str, Any]] = {}

        root = next(name for name, inst in self._instances.items() if "on" not in inst)
        root_inst = self._instances[root]
        root_module = self._catalog[root_inst["type"]]
        robot_pos, robot_quat = frame_from_dict(self._scene.get("robot"))
        root_part = root_inst.get("part", next(iter(root_module["parts"])))
        body = spec.worldbody.add_body(name=f"{root}_{root_part}", pos=robot_pos, quat=robot_quat)
        mobile = not root_inst.get("fixed", False)
        if mobile:
            body.add_freejoint(name=f"{root}_libre")
        self._add_instance(spec, root, root_part, body)

        for cam in self._scene.get("cameras", []):
            self._add_scene_camera(spec, cam)
        objets = self._scene.get("objects")
        if objets is None and mobile:
            objets = ARENE        # robot mobile sans scène : une arène avec murs et obstacles, pour le lidar
        for obj in objets or []:
            self._add_object(spec, obj)

        if self._connector_markers:
            self._add_connector_markers()
        model = spec.compile()
        if mobile and "robot" not in self._scene:
            # robot mobile sans position imposée : posé sur le sol par son point le plus bas (ses roues)
            body.pos = robot_pos + [0, 0, 0.0005 - self._lowest_point(model, body.name)]
            model = spec.compile()
        body_module = {model.body(body.name).id: name
                       for name, bodies in self._part_bodies.items() for body in bodies.values()}
        markers = {model.geom(geom).id: geom[len(CONNECTOR_MARKER_PREFIX):] for geom in self._marker_names}
        return BuiltModel(spec=spec, model=model, joints=self._joints, max_velocity_deg_s=self._max_vel,
                          body_module=body_module, connector_markers=markers, lidars=self._lidars)

    @staticmethod
    def _lowest_point(model: mujoco.MjModel, root_body: str) -> float:
        """Altitude du point le plus bas des formes de contact du robot (modèle à sa position de départ) ; root_body :
        corps racine du robot (les objets de la scène ne comptent pas)."""
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        root = model.body(root_body).id
        lowest = np.inf
        for g in range(model.ngeom):
            if model.body_rootid[model.geom_bodyid[g]] != root or model.geom_contype[g] == 0:
                continue        # sol, objets de la scène, géométries visuelles
            axe = data.geom_xmat[g].reshape(3, 3)[2]      # composantes z des axes de la géométrie
            size = model.geom_size[g]
            kind = model.geom_type[g]
            if kind == mujoco.mjtGeom.mjGEOM_BOX:
                half = float(np.abs(axe) @ size)
            elif kind == mujoco.mjtGeom.mjGEOM_CYLINDER:
                half = size[0] * float(np.sqrt(max(0.0, 1 - axe[2] ** 2))) + size[1] * abs(axe[2])
            elif kind == mujoco.mjtGeom.mjGEOM_SPHERE:
                half = size[0]
            else:
                half = model.geom_rbound[g]
            lowest = min(lowest, data.geom_xpos[g][2] - half)
        return float(lowest) if np.isfinite(lowest) else 0.0

    def _add_connector_markers(self) -> None:
        """Pastille sur chaque connecteur libre, légèrement en avant de la face de branchement."""
        used = set()
        for name, inst in self._instances.items():
            if "on" in inst:
                used.add(str(inst["on"]))
                used.add(f"{name}.{inst['connector']}")
        for name, inst in self._instances.items():
            module = self._catalog[inst["type"]]
            scale = float(module.get("unit_scale", 1.0))
            for conn_name, conn in module.get("connectors", {}).items():
                key = f"{name}.{conn_name}"
                if key in used:
                    continue
                pos, quat = frame_from_dict(conn, scale)
                zaxis = np.zeros(9)
                mujoco.mju_quat2Mat(zaxis, quat)
                geom = f"{CONNECTOR_MARKER_PREFIX}{key}"
                self._part_bodies[name][conn["part"]].add_geom(
                    name=geom, type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.007, 0, 0],
                    pos=pos + 0.004 * zaxis.reshape(3, 3)[:, 2], rgba=[0.44, 0.53, 0.66, 0.95],
                    group=CONNECTOR_MARKER_GROUP, contype=0, conaffinity=0, density=0)
                self._marker_names.append(geom)

    # ------------------------------------------------------------------ modules
    def _add_instance(self, spec: mujoco.MjSpec, name: str, attach_part: str, attach_body: Any) -> None:
        """Ajoute le module name, dont la pièce attach_part est portée par attach_body (repère = repère CAO du
        module), puis les modules branchés sur lui. Toutes les pièces d'un module partagent le repère CAO
        à articulations nulles : chaque articulation est placée à sa position dans ce repère."""
        inst = self._instances[name]
        module = self._catalog[inst["type"]]
        scale = float(module.get("unit_scale", 1.0))
        bodies = {attach_part: attach_body}
        self._add_part(spec, name, attach_body, module["parts"][attach_part], scale)

        joints = module.get("joints", {})
        motor_map = dict(inst.get("motors", {}))
        if "motor" in inst:
            motor_map[next(iter(joints))] = inst["motor"]
        pending = dict(joints)
        while pending:
            for joint_name, joint in list(pending.items()):
                if joint["parent"] in bodies and joint["child"] not in bodies:
                    placed, new, axis = joint["parent"], joint["child"], list(joint["axis"])
                elif joint["child"] in bodies and joint["parent"] not in bodies:
                    # module branché par la pièce entraînée : l'autre pièce tourne en sens inverse
                    placed, new, axis = joint["child"], joint["parent"], [-a for a in joint["axis"]]
                else:
                    continue
                del pending[joint_name]
                motor = motor_map.get(joint_name)
                if motor is None:
                    # articulation sans moteur : pièces solidaires
                    bodies[new] = bodies[placed]
                else:
                    bodies[new] = bodies[placed].add_body(name=f"{name}_{new}")
                    self._add_joint(spec, bodies[new], joint, np.asarray(joint["pos"], float) * scale, axis,
                                    self._joint_info(inst, motor, joint))
                self._add_part(spec, name, bodies[new], module["parts"][new], scale)
                break
            else:
                raise StructureError([f"{inst['type']} : articulations qui ne relient pas toutes les pièces"])
        for part in module["parts"]:
            if part not in bodies:
                raise StructureError([f"{inst['type']} : pièce '{part}' reliée à aucune articulation"])
        self._part_bodies[name] = bodies

        for sensor_key, config_key in inst.get("sensors", {}).items():
            sensor = module["sensors"][sensor_key]
            pos, quat = frame_from_dict(sensor, scale)
            if sensor.get("type") == "lidar":
                # repère de mesure : les rayons partent de son origine, dans son plan xy
                bodies[sensor["part"]].add_site(name=config_key, pos=pos, quat=quat, size=[0.004, 0, 0],
                                                rgba=[0.9, 0.2, 0.2, 0.0])
                self._lidars[config_key] = {"points": int(sensor.get("points", 400)),
                                            "range_m": list(sensor.get("range_m", [0.05, 12.0]))}
            else:
                bodies[sensor["part"]].add_camera(name=config_key, pos=pos, quat=quat, fovy=sensor.get("fovy", 60))

        for geom1, geom2 in module.get("contact_pairs", []):
            g1, g2 = f"{name}_{geom1}", f"{name}_{geom2}"
            # pièces solidaires (articulation sans moteur) : même corps, pas de contact possible
            if self._geom_body[g1] != self._geom_body[g2]:
                spec.add_pair(geomname1=g1, geomname2=g2)

        for child_name, child in self._instances.items():
            parent_name, _, parent_conn = str(child.get("on", "")).partition(".")
            if parent_name != name:
                continue
            connector = module["connectors"][parent_conn]
            parent_pos, parent_quat = frame_from_dict(connector, scale)
            child_module = self._catalog[child["type"]]
            child_connector = child_module["connectors"][child["connector"]]
            child_pos, child_quat = frame_from_dict(child_connector, float(child_module.get("unit_scale", 1.0)))
            # repère CAO de l'enfant dans le corps parent : prise du parent, demi-tour, puis inverse de sa prise
            mate_pos, mate_quat = compose(parent_pos, parent_quat, np.zeros(3), FLIP_X)
            body_pos, body_quat = compose(mate_pos, mate_quat, *invert(child_pos, child_quat))
            child_part = child_connector["part"]
            child_body = bodies[connector["part"]].add_body(name=f"{child_name}_{child_part}", pos=body_pos, quat=body_quat)
            self._add_instance(spec, child_name, child_part, child_body)

    def _joint_info(self, inst: dict[str, Any], motor: str, joint: dict[str, Any]) -> SimJointInfo:
        params = self._motor_params.get(motor, MotorParams())
        # plage calibrée si elle existe, sinon plage par défaut du module (robot conçu sans matériel)
        range_deg = params.range_deg or tuple(joint.get("default_range_deg", DEFAULT_RANGE_DEG))
        info = SimJointInfo(motor=motor, joint_name=f"{motor}_joint", actuator_name=motor,
                            direction=float(inst.get("direction", 1)),
                            zero_offset_deg=float(inst.get("zero_offset_deg", 0)),
                            range_deg=range_deg,
                            velocity=params.velocity or joint.get("mode") == "velocity",
                            stall_torque=joint.get("stall_torque", DEFAULT_STALL_TORQUE),
                            no_load_speed_deg_s=joint.get("no_load_speed_deg_s", DEFAULT_NO_LOAD_SPEED_DEG_S))
        info.pid = SIM_PID_VELOCITY if info.velocity else SIM_PID_POSITION
        if info.velocity:
            info.range_deg = (-180.0, 180.0)        # position lue sur un tour, comme le servo réel en mode vitesse
        self._joints[motor] = info
        self._max_vel[motor] = info.no_load_speed_deg_s
        return info

    def _add_joint(self, spec: mujoco.MjSpec, body: Any, joint: dict[str, Any], pos: np.ndarray, axis: list[float],
                   joint_info: SimJointInfo) -> None:
        lo, hi = joint_info.range_deg
        sim_range = sorted([joint_info.motor_to_sim_rad(lo), joint_info.motor_to_sim_rad(hi)])
        kwargs: dict[str, Any] = {"range": sim_range}
        if joint_info.velocity:
            kwargs = {"limited": mujoco.mjtLimited.mjLIMITED_FALSE}     # rotation continue
        body.add_joint(name=joint_info.joint_name, type=mujoco.mjtJoint.mjJNT_HINGE,
                       pos=pos, axis=axis, **kwargs,
                       damping=joint.get("damping", 0.02),     # frottements visqueux du réducteur
                       armature=joint.get("armature", 0.01),
                       frictionloss=joint.get("frictionloss", 0.02))
        # actionneur de couple pur : le couple est calculé par le servo simulé (PID, tension, moteur), voir SimWorld
        spec.add_actuator(name=joint_info.actuator_name, target=joint_info.joint_name,
                          trntype=mujoco.mjtTrn.mjTRN_JOINT)

    def _add_part(self, spec: mujoco.MjSpec, prefix: str, body: Any, part: dict[str, Any], scale: float = 1.0) -> None:
        geoms = part.get("geoms", [])
        part_mass = part.get("mass")
        # la masse est répartie sur les géométries de collision ; les géométries purement visuelles ne pèsent rien
        massive = [g for g in geoms if not g.get("visual_only", False)]
        default_geom_mass = part_mass / len(massive) if part_mass is not None and massive else None
        for g in geoms:
            pos, quat = frame_from_dict(g, scale)
            kwargs: dict[str, Any] = {
                "type": self.GEOM_TYPES[g.get("type", "box")],
                "pos": pos,
                "quat": quat,
            }
            if "size" in g:
                kwargs["size"] = [s * scale for s in g["size"]]
            if "name" in g:
                kwargs["name"] = f"{prefix}_{g['name']}"
                self._geom_body[kwargs["name"]] = body.name
            if "rgba" in g:
                kwargs["material"] = self._material(spec, g["rgba"], g.get("glossy", False))
            if "friction" in g:
                kwargs["friction"] = g["friction"]
            if g.get("stiff_contact", False):
                kwargs["solref"] = STIFF_SOLREF
                kwargs["solimp"] = STIFF_SOLIMP + [0.5, 2]
            if "group" in g:
                kwargs["group"] = g["group"]
            if g.get("visual_only", False):
                kwargs["contype"] = 0
                kwargs["conaffinity"] = 0
                kwargs["density"] = 0
            elif "mass" in g or default_geom_mass is not None:
                kwargs["mass"] = g.get("mass", default_geom_mass)
            if g.get("collision_only", False):
                kwargs["group"] = 3  # groupe masqué au rendu
            if kwargs["type"] == mujoco.mjtGeom.mjGEOM_MESH:
                # maillage dans les mêmes unités que le module (sinon mm par défaut)
                kwargs["meshname"] = self._add_mesh(spec, g["file"], g.get("scale", scale if scale != 1.0 else 0.001),
                                                    g.get("select"))
            body.add_geom(**kwargs)

    def _material(self, spec: mujoco.MjSpec, rgba: list[float], glossy: bool = False) -> str:
        """Matière d'une couleur du catalogue (une par couleur) : plastique mat, noirs éclaircis pour l'écran ;
        glossy : surface brillante (optique du lidar...)."""
        key = (*(round(float(v), 4) for v in rgba), glossy)
        if key not in self._materials:
            r, g, b, a = key[:4]
            # une surface brillante garde son noir : ce sont ses reflets qui la distinguent du PLA mat
            plancher = 0.04 if glossy else NOIR_AFFICHE
            affiche = [plancher + (1 - plancher) * c for c in (r, g, b)] + [a]
            name = f"matiere_{len(self._materials)}"
            spec.add_material(name=name, rgba=affiche, **(MATIERE_BRILLANTE if glossy else MATIERE))
            self._materials[key] = name
        return self._materials[key]

    def _add_mesh(self, spec: mujoco.MjSpec, file: str, scale: float,
                  select: dict[str, Any] | list[dict[str, Any]] | None = None) -> str:
        """select = {"axis": [x, y, z], "min": a, "max": b} : ne garde que la partie du maillage dont la projection
        sur axis (unités du STL) est entre min et max ; {"axis", "center": [x, y, z], "rmin": a, "rmax": b} : celle
        dont la distance à l'axe passant par center est entre rmin et rmax (triangles gardés entiers, d'après leur
        sommet le plus proche de l'axe) ; une liste de conditions doit être vérifiée en entier.
        Sert à colorer différemment des zones d'un même STL."""
        path = (self._catalog_dir / file).resolve()
        key = (str(path), scale, json.dumps(select, sort_keys=True))
        if key not in self._mesh_names:
            name = f"mesh_{len(self._mesh_names)}_{path.stem}"
            if select is None:
                spec.add_mesh(name=name, file=str(path), scale=[scale] * 3)
            else:
                cache_key = (str(path), json.dumps(select, sort_keys=True))
                if cache_key not in _CLIPPED_MESHES:
                    keep = load_stl(path)
                    for cond in select if isinstance(select, list) else [select]:
                        axis = np.asarray(cond["axis"], float)
                        if "rmin" in cond or "rmax" in cond:
                            unit = axis / np.linalg.norm(axis)
                            d = keep - np.asarray(cond.get("center", [0, 0, 0]), float)
                            # distance à l'axe du sommet le plus proche : rmin et rmax se complètent sans trou
                            r = np.linalg.norm(d - (d @ unit)[..., None] * unit, axis=2).min(axis=1)
                            keep = keep[(r >= cond.get("rmin", -np.inf)) & (r <= cond.get("rmax", np.inf))]
                            continue
                        if "min" in cond:
                            keep = clip_triangles(keep, axis, cond["min"])
                        if "max" in cond:
                            keep = clip_triangles(keep, -axis, -cond["max"])
                    _CLIPPED_MESHES[cache_key] = keep
                keep = _CLIPPED_MESHES[cache_key]
                if len(keep) == 0:
                    raise ValueError(f"{path.name} : aucun triangle dans la sélection {select}")
                spec.add_mesh(name=name, uservert=keep.reshape(-1).tolist(),
                              userface=list(range(keep.shape[0] * 3)), scale=[scale] * 3)
            self._mesh_names[key] = name
        return self._mesh_names[key]

    # ------------------------------------------------------------------ scène
    def _add_scene(self, spec: mujoco.MjSpec) -> None:
        # un peu de lumière ambiante (la lampe frontale de MuJoCo, forte par défaut, aplatissait tout) ; les lumières de
        # la scène (LUMIERES_DEFAUT, ou "lights" de la scène) portent les ombres
        spec.visual.headlight.ambient = [0.36, 0.36, 0.36]
        spec.visual.headlight.diffuse = [0.28, 0.28, 0.28]
        spec.visual.headlight.specular = [0.05, 0.05, 0.05]
        spec.visual.quality.shadowsize = 8192          # ombres nettes mais douces
        spec.visual.quality.offsamples = 8             # contours lissés (anticrénelage)
        spec.visual.global_.offwidth = 1280
        spec.visual.global_.offheight = 960
        # ciel gris chaud, accordé au thème « Atelier » de l'éditeur (mir_utils/ui/theme.py)
        spec.add_texture(name="sky", type=mujoco.mjtTexture.mjTEXTURE_SKYBOX, builtin=mujoco.mjtBuiltin.mjBUILTIN_GRADIENT,
                         rgb1=[0.95, 0.93, 0.89], rgb2=[0.81, 0.78, 0.73], width=256, height=256)
        for lumiere in self._scene.get("lights", LUMIERES_DEFAUT):
            self._add_light(spec, lumiere)
        root = next(inst for inst in self._instances.values() if "on" not in inst)
        # bras : petite table de travail ; robot mobile : le sol de son arène (3 x 3 m)
        defaut = ({"size": [0.4, 0.3], "pos": [0.1, 0, 0], "rgba": [0.75, 0.68, 0.58, 1]} if root.get("fixed", False)
                  else {"size": [1.6, 1.6], "pos": [0, 0, 0], "rgba": [0.75, 0.68, 0.58, 1]})
        table = self._scene.get("table", defaut)
        # trame discrète (carreaux de 5 cm) : elle donne la profondeur et l'échelle
        couleur = np.array(table.get("rgba", [0.75, 0.68, 0.58, 1])[:3])
        spec.add_texture(name="trame", type=mujoco.mjtTexture.mjTEXTURE_2D, builtin=mujoco.mjtBuiltin.mjBUILTIN_CHECKER,
                         rgb1=couleur, rgb2=couleur, mark=mujoco.mjtMark.mjMARK_EDGE, markrgb=couleur * 0.93,
                         width=512, height=512)
        spec.add_material(name="table", textures=["", "trame"], texrepeat=[10, 10], texuniform=True,
                          specular=0.1, shininess=0.1)
        spec.worldbody.add_geom(name="table", type=mujoco.mjtGeom.mjGEOM_PLANE,
                                size=[table["size"][0], table["size"][1], 0.01],
                                pos=table.get("pos", [0, 0, 0]), material="table")

    @staticmethod
    def _add_light(spec: mujoco.MjSpec, lumiere: dict[str, Any]) -> None:
        pos = np.array(lumiere["pos"], dtype=float)
        direction = np.array(lumiere["target"], dtype=float) - pos if "target" in lumiere else lumiere["dir"]
        options = {"cutoff": lumiere["cutoff"], "exponent": lumiere.get("exponent", 1.0),
                   "attenuation": [1, 0, 0]} if lumiere.get("type") == "spot" else {}
        spec.worldbody.add_light(name=lumiere["name"], pos=pos, dir=direction,
                                 diffuse=lumiere.get("diffuse", [0.6, 0.6, 0.6]),
                                 specular=lumiere.get("specular", [0.3, 0.3, 0.3]),
                                 castshadow=lumiere.get("castshadow", False),
                                 type=TYPES_LUMIERE[lumiere.get("type", "directional")], **options)

    def _add_scene_camera(self, spec: mujoco.MjSpec, cam: dict[str, Any]) -> None:
        if "lookat" in cam:
            quat = lookat_quat(cam["pos"], cam["lookat"])
        else:
            quat = euler_deg_to_quat(cam.get("euler_deg"))
        spec.worldbody.add_camera(name=cam["name"], pos=cam["pos"], quat=quat, fovy=cam.get("fovy", 60))

    def _add_object(self, spec: mujoco.MjSpec, obj: dict[str, Any]) -> None:
        # "mocap": true : objet immobile que le programme peut déplacer entre deux épisodes (obstacles tirés au hasard)
        mocap = obj.get("mocap", False)
        body = spec.worldbody.add_body(name=obj["name"], pos=obj["pos"], quat=euler_deg_to_quat(obj.get("euler_deg")),
                                       mocap=mocap)
        if obj.get("free", True) and not mocap:
            body.add_freejoint(name=f"{obj['name']}_free")
        # objet fait de plusieurs formes (ex. boîte percée) : "geoms" = [{"type", "size", "pos"}], repère de l'objet ;
        # la masse de l'objet est répartie également entre elles
        formes = obj.get("geoms") or [{"type": obj.get("type", "box"), "size": obj["size"]}]
        for forme in formes:
            body.add_geom(type=self.GEOM_TYPES[forme.get("type", "box")], size=forme["size"],
                          pos=forme.get("pos", [0, 0, 0]), mass=obj.get("mass", 0.01) / len(formes),
                          material=self._material(spec, forme.get("rgba", obj.get("rgba", [0.8, 0.2, 0.2, 1]))),
                          friction=obj.get("friction", [1.0, 0.02, 0.001]),
                          solref=STIFF_SOLREF, solimp=STIFF_SOLIMP + [0.5, 2])


def load_scene(scene: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if scene is None:
        return {}
    if isinstance(scene, dict):
        return scene
    return json.loads(Path(scene).read_text(encoding="utf-8"))


def build_model(robot_config: Any, scene: str | Path | dict[str, Any] | None = None,
                catalog_dir: str | Path = CATALOG_DIR) -> BuiltModel:
    """Modèle MuJoCo d'un robot décrit par sa configuration (mirRobotConfig, ou chemin du fichier JSON)."""
    if isinstance(robot_config, (str, Path)):
        from mir_robot.mir_robot_config import mirRobotConfig
        robot_config = mirRobotConfig.load(str(robot_config))
    if not robot_config.structure:
        raise StructureError(["la configuration ne contient pas de structure (section \"structure\")"])
    motors = list(robot_config.motor_bus.motors) if robot_config.motor_bus is not None else []
    builder = ModelBuilder(robot_config.structure, motor_params_from_config(robot_config), load_scene(scene),
                           catalog_dir, motors=motors, sensors=list(robot_config.sensors))
    return builder.build()
