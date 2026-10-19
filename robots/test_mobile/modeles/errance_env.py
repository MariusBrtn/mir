"""
Tâche « errance » : le robot mobile doit parcourir une rue encombrée sans rien percuter, en ne regardant que son lidar.

Ce fichier n'entraîne rien : il décrit la tâche, utilisée par le script d'entraînement errance_ppo.py.
« Entraîner » sur ce fichier vérifie l'environnement : conformité Gymnasium, vitesse, score d'une politique au hasard
(la référence à battre). Il écrit aussi la scène robots/test_mobile/scenes/rue_decombres.json, pour voir la rue dans MIR.

  1. ErranceRobot (interface robot) : toutes les 0,1 s (le lidar réel fait 10 tours/s)
       - observation : 40 secteurs de lidar de 9° (distance du plus proche obstacle, ramenée entre 0 et 1 ;
         1 = à 2 m ou plus) + la consigne précédente des deux côtés ;
       - action : 2 nombres entre -1 et 1, consigne des roues de gauche et de droite (fraction de la vitesse max).
     Elle sert telle quelle dans la simulation d'entraînement et quand le modèle pilote le robot dans Piloter → IA.
  2. La rue : 10 x 4 m, façades, barricades aux deux bouts, et une réserve de 30 décombres redistribués au hasard
     à chaque épisode. Ils dépassent tous le plan du lidar (16,5 cm du sol) : un obstacle plus bas serait invisible.
  3. ErranceEnv (environnement Gymnasium) : récompense = avancer + découvrir de nouvelles cases de 50 cm,
     pénalités = tourner sur soi, frôler un obstacle ; fin = choc (-10) ou robot renversé ; coupure au bout de 60 s.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
import gymnasium as gym
import mujoco
import numpy as np
from mir_robot.rl import RobotInterface

ROBOT = Path(__file__).resolve().parents[1] / "robot.json"
LIDAR = "lidar_1"


# ---------------------------------------------------------------- 1. interface robot (simulation et Piloter → IA)

SENS = {"gauche": 1, "droite": -1}      # sens de rotation des roues de chaque côté pour avancer (cf. conduite_clavier)
SECTEURS = 40                           # secteurs du lidar (9° chacun, le secteur 0 centré sur l'avant)
PORTEE = 2.0                            # m : au-delà, un obstacle compte comme « loin »


class ErranceRobot(RobotInterface):
    fps = 10
    observations = [LIDAR]

    def setup(self, actions):
        # roues de chaque côté, d'après le nom de leur consigne de vitesse (ex. roue_avant_gauche.velocity)
        self.roues = {cote: [nom for nom in actions if nom.endswith(".velocity") and cote in nom] for cote in SENS}
        if not self.roues["gauche"] or not self.roues["droite"]:
            raise ValueError("il faut des roues à gauche et à droite (consignes « ..._gauche.velocity » et "
                             "« ..._droite.velocity »)")
        self.vmax = min(actions[nom][1] for roues in self.roues.values() for nom in roues)     # tr/min

    def reset(self):
        self.action_precedente = np.zeros(2, np.float32)

    def observation(self, robot_observation):
        # tour de lidar du capteur esp_lidar : tableau (n, 2) = [angle en °, distance en cm], 0 = pas de mesure
        scan = np.asarray(robot_observation[LIDAR], dtype=float)
        angles, distances = scan[:, 0], scan[:, 1] / 100.0
        distances = np.where(distances > 0, distances, np.inf)      # pas de mesure : rien dans la portée
        secteur = (((angles + 180.0 / SECTEURS) % 360.0) // (360.0 / SECTEURS)).astype(int)
        proches = np.full(SECTEURS, np.inf)
        np.minimum.at(proches, secteur, distances)
        lidar = np.minimum(proches, PORTEE) / PORTEE
        return np.concatenate([lidar, self.action_precedente]).astype(np.float32)

    def action(self, action):
        action = np.clip(np.asarray(action, np.float32), -1.0, 1.0)
        self.action_precedente = action
        consigne = {"gauche": float(action[0]), "droite": float(action[1])}
        return {nom: SENS[cote] * consigne[cote] * self.vmax for cote, roues in self.roues.items() for nom in roues}


# ---------------------------------------------------------------- 2. la rue

LONGUEUR, LARGEUR = 10.0, 4.0           # m, chaussée entre les façades
HAUTEUR_LIDAR = 0.165                   # m, plan de mesure du lidar
CACHE = 50.0                            # m : les décombres inutilisés sont rangés loin de la rue
BETON = [0.55, 0.53, 0.5, 1]
FACADE = [0.66, 0.6, 0.52, 1]
ROUILLE = [0.5, 0.3, 0.2, 1]
BOIS = [0.45, 0.35, 0.25, 1]
EPAVE = [0.4, 0.15, 0.13, 1]
POUBELLE = [0.25, 0.35, 0.3, 1]


def scene_rue(graine: int = 0) -> dict:
    """Scène MIR de la rue : façades fixes (segments plus ou moins en retrait) et réserve de décombres "mocap"
    (immobiles pour la physique, déplacés par le programme), tirées une fois pour toutes avec la graine."""
    rng = np.random.default_rng(graine)
    objets = []
    for cote, signe in (("nord", 1), ("sud", -1)):
        x, i = -LONGUEUR / 2, 0
        while x < LONGUEUR / 2:
            largeur = min(rng.uniform(1.0, 2.5), LONGUEUR / 2 - x)
            y = signe * (LARGEUR / 2 + rng.choice([0.0, 0.0, 0.15, 0.3]) + 0.1)
            objets.append({"name": f"facade_{cote}_{i}", "type": "box", "free": False, "rgba": FACADE,
                           "size": [largeur / 2, 0.1, 0.5], "pos": [x + largeur / 2, y, 0.5]})
            x += largeur
            i += 1
    for bout, signe in (("est", 1), ("ouest", -1)):
        objets.append({"name": f"barricade_{bout}", "type": "box", "free": False, "rgba": BETON,
                       "size": [0.1, LARGEUR / 2 + 0.5, 0.4], "pos": [signe * (LONGUEUR / 2 + 0.1), 0, 0.4]})

    decombres = []

    def ajouter(nom, type_, taille, rgba):
        hauteur = taille[2] if type_ == "box" else taille[1]       # demi-hauteur
        assert 2 * hauteur > HAUTEUR_LIDAR, f"{nom} est sous le plan du lidar"
        decombres.append({"name": f"{nom}_{len(decombres)}", "type": type_, "mocap": True, "rgba": rgba,
                          "size": [round(float(t), 3) for t in taille], "pos": [CACHE + len(decombres), 0, hauteur]})

    for _ in range(12):
        ajouter("bloc", "box", [rng.uniform(0.1, 0.3), rng.uniform(0.1, 0.3), rng.uniform(0.1, 0.25)], BETON)
    for _ in range(6):
        ajouter("fut", "cylinder", [rng.uniform(0.12, 0.2), rng.uniform(0.2, 0.3)], ROUILLE)
    for _ in range(6):
        ajouter("poutre", "box", [rng.uniform(0.5, 1.0), rng.uniform(0.05, 0.08), rng.uniform(0.1, 0.15)], BOIS)
    for _ in range(4):
        ajouter("poubelle", "box", [0.2, 0.2, 0.35], POUBELLE)
    for _ in range(2):
        ajouter("epave", "box", [0.8, 0.4, 0.3], EPAVE)
    return {
        "name": "Rue encombrée",
        "description": "Portion de rue de 10 x 4 m avec des décombres, pour l'apprentissage par renforcement "
                       "(errer sans rien percuter, au lidar). Écrite par modeles/errance_env.py.",
        "table": {"size": [LONGUEUR / 2 + 0.3, LARGEUR / 2 + 0.6], "pos": [0, 0, 0], "rgba": [0.42, 0.42, 0.44, 1]},
        "cameras": [{"name": "vue_rue", "pos": [0, -6.5, 5.5], "lookat": [0, 0, 0], "fovy": 60}],
        "objects": objets + decombres,
    }


def placer_decombres(monde, scene: dict, rng: np.random.Generator, nombre: tuple[int, int] = (15, 30)) -> None:
    """Répartit au hasard dans la rue entre nombre[0] et nombre[1] décombres de la réserve ; les autres restent
    rangés hors de la rue."""
    objets = [obj for obj in scene["objects"] if obj.get("mocap")]
    n = int(rng.integers(nombre[0], min(nombre[1], len(objets)) + 1))
    choisis = set(rng.choice(len(objets), n, replace=False).tolist())
    for i, obj in enumerate(objets):
        z = obj["pos"][2]
        if i in choisis:
            x = rng.uniform(-LONGUEUR / 2 + 0.3, LONGUEUR / 2 - 0.3)
            y = rng.uniform(-LARGEUR / 2 + 0.2, LARGEUR / 2 - 0.2)
            monde.set_object_pose(obj["name"], [x, y, z], rng.uniform(0, 360), forward=False)
        else:
            monde.set_object_pose(obj["name"], [CACHE + i, 0, z], forward=False)
    mujoco.mj_forward(monde.model, monde.data)


def ecrire_scene() -> Path:
    """Écrit la rue dans les scènes du robot, avec une disposition fixe des décombres, pour la voir dans MIR."""
    scene = scene_rue()
    rng = np.random.default_rng(1)
    for i, obj in enumerate(o for o in scene["objects"] if o.get("mocap")):
        if i < 24:
            obj["pos"] = [round(rng.uniform(-LONGUEUR / 2 + 0.3, LONGUEUR / 2 - 0.3), 2),
                          round(rng.uniform(-LARGEUR / 2 + 0.2, LARGEUR / 2 - 0.2), 2), obj["pos"][2]]
            obj["euler_deg"] = [0, 0, round(rng.uniform(0, 360))]
    chemin = ROBOT.parent / "scenes" / "rue_decombres.json"
    chemin.parent.mkdir(exist_ok=True)
    chemin.write_text(json.dumps(scene, indent=4, ensure_ascii=False), encoding="utf-8")
    return chemin


# ---------------------------------------------------------------- 3. environnement Gymnasium

DUREE_MAX = 600                         # décisions par épisode (60 s)
VITESSE_MAX = 0.47                      # m/s, vitesse mesurée en simu à 100 tr/min (roue de 90 mm)
CASE = 0.5                              # m, côté des cases de la rue (bonus d'exploration)
DISTANCE_PRUDENCE = 0.35                # m (depuis le lidar) : en dessous, pénalité de proximité
DISTANCE_DEPART = 0.5                   # m : place libre minimale autour du robot au départ


class ErranceEnv(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": ErranceRobot.fps}

    def __init__(self, render_mode: str | None = None, graine_scene: int = 0, bruit_lidar: bool = True):
        from mir_robot.mir_robot_config import mirRobotConfig
        from mir_sim.model_builder import build_model
        from mir_sim.sim_world import SimWorld
        self.render_mode = render_mode
        self.bruit_lidar = bruit_lidar
        self.scene = scene_rue(graine_scene)
        self.monde = SimWorld(build_model(mirRobotConfig.load(str(ROBOT)), self.scene))
        vmax_rpm = {m: self.monde.built.max_velocity_deg_s[m] / 6 for m in self.monde.motors}
        self.robot = ErranceRobot()
        self.robot.setup({f"{m}.velocity": (-v, v) for m, v in vmax_rpm.items()})
        self.pas_physique = round(1 / ErranceRobot.fps / self.monde.model.opt.timestep)
        self.observation_space = gym.spaces.Box(-1.0, 1.0, (SECTEURS + 2,), np.float32)
        self.action_space = gym.spaces.Box(-1.0, 1.0, (2,), np.float32)
        self._renderer = None

    def _observer(self) -> np.ndarray:
        """Un tour de lidar : distance exacte du plus proche obstacle (pour la récompense), et observation du robot
        au format du vrai capteur ([°, cm], 0 = pas de mesure), avec ses défauts si bruit_lidar (pour le réseau)."""
        angles, distances = self.monde.lidar_scan(LIDAR)
        self.plus_proche = float(distances[distances > 0].min(initial=np.inf))
        if self.bruit_lidar:
            mesure = distances > 0
            distances = np.where(mesure, distances + self.np_random.normal(0, 0.01, len(distances)), 0.0)
            distances[self.np_random.random(len(distances)) < 0.05] = 0.0       # 5 % de mesures perdues
        self.scan = np.column_stack([angles, np.round(np.clip(distances, 0, 12.0) * 100)])
        return self.robot.observation({LIDAR: self.scan})

    def _case(self) -> tuple[int, int]:
        x, y, _ = self.monde.get_robot_pose()
        return int(np.floor(x / CASE)), int(np.floor(y / CASE))

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self.monde.reset()
        self.robot.reset()
        placer_decombres(self.monde, self.scene, self.np_random)
        # départ : une place libre de la rue, cap au hasard
        for _ in range(200):
            x = self.np_random.uniform(-LONGUEUR / 2 + 0.5, LONGUEUR / 2 - 0.5)
            y = self.np_random.uniform(-LARGEUR / 2 + 0.5, LARGEUR / 2 - 0.5)
            self.monde.set_robot_pose(x, y, self.np_random.uniform(-180, 180))
            self._observer()
            if not self.monde.robot_contacts() and self.plus_proche > DISTANCE_DEPART:
                break
        self.monde.step(25)         # le robot se pose sur ses roues
        self.cases = {self._case()}
        self.pas = 0
        return self._observer(), {}

    def step(self, action):
        consignes = self.robot.action(action)
        self.monde.set_goal_velocities({nom.removesuffix(".velocity"): v for nom, v in consignes.items()})
        self.monde.step(self.pas_physique)
        self.pas += 1

        observation = self._observer()
        avance, rotation = self.monde.get_robot_velocity()
        case = self._case()
        nouvelle_case = case not in self.cases
        self.cases.add(case)
        choc = bool(self.monde.robot_contacts())
        renverse = not self.monde.is_robot_upright()

        recompense = (0.5 * avance / VITESSE_MAX
                      + 2.0 * nouvelle_case
                      - 0.2 * abs(rotation)
                      - 1.0 * float(np.clip((DISTANCE_PRUDENCE - self.plus_proche) / 0.15, 0, 1)))
        terminated = choc or renverse
        if terminated:
            recompense -= 10.0
        truncated = self.pas >= DUREE_MAX
        info = {"choc": choc, "cases": len(self.cases)}
        return observation, float(recompense), terminated, truncated, info

    def render(self):
        """Image vue de dessus, caméra qui suit le robot ; les points rouges sont les mesures du lidar."""
        if self._renderer is None:
            self._renderer = mujoco.Renderer(self.monde.model, 480, 640)
            self._camera = mujoco.MjvCamera()
            self._camera.type = mujoco.mjtCamera.mjCAMERA_TRACKING
            self._camera.trackbodyid = self.monde.base_body
            self._camera.distance, self._camera.elevation, self._camera.azimuth = 4.0, -89.9, 90
        self._renderer.update_scene(self.monde.data, self._camera)
        scene = self._renderer.scene
        site = self.monde.model.site(LIDAR).id
        origine = self.monde.data.site_xpos[site]
        rot = self.monde.data.site_xmat[site].reshape(3, 3)
        for angle, cm in self.scan[::2]:
            if cm <= 0 or scene.ngeom >= scene.maxgeom:
                continue
            a = np.radians(angle)
            point = origine + rot @ np.array([np.cos(a), -np.sin(a), 0.0]) * cm / 100
            mujoco.mjv_initGeom(scene.geoms[scene.ngeom], mujoco.mjtGeom.mjGEOM_SPHERE, [0.02, 0, 0], point,
                                np.eye(3).flatten(), np.array([0.9, 0.1, 0.1, 1], np.float32))
            scene.ngeom += 1
        return self._renderer.render()

    def close(self):
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None


# ---------------------------------------------------------------- vérification (« Entraîner » sur ce fichier)

if __name__ == "__main__":
    from gymnasium.utils.env_checker import check_env
    print(f"scène écrite (à choisir dans MIR, en simulé) : {ecrire_scene()}")
    env = ErranceEnv()
    check_env(env, skip_render_check=True)
    print("conformité Gymnasium : ok")
    debut, pas, chocs, cases = time.time(), 0, 0, []
    for episode in range(5):
        env.reset(seed=episode)
        fini = False
        while not fini:
            _, _, terminated, truncated, info = env.step(env.action_space.sample())
            pas += 1
            fini = terminated or truncated
        chocs += info["choc"]
        cases.append(info["cases"])
    print(f"vitesse : {pas / (time.time() - debut):.0f} pas/s sur un cœur")
    print(f"politique au hasard (5 épisodes) : {chocs} chocs, {np.mean(cases):.1f} cases visitées")
