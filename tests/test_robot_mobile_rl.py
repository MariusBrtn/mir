"""Robot mobile et apprentissage par renforcement : base libre simulée (pose, vitesse, contacts), obstacles mocap,
environnement « errance » (robots/test_mobile/modeles), modèle RL enregistré puis piloté depuis Piloter → IA."""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock
import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication
from mir_robot.rl import RLPolicy, save_rl_model
from mir_robot.training import load_policy, model_info, trained_models
from mir_sim.sim_world import SimWorld
from mir_robot_editor.entrainement.entrainement_view_model import besoin_dataset
from mir_robot_editor.ia.ia_view_model import IAViewModel

MODELES = Path(__file__).resolve().parents[1] / "robots" / "test_mobile" / "modeles"
sys.path.insert(0, str(MODELES))
from errance_env import SECTEURS, ErranceEnv, ErranceRobot, scene_rue      # noqa: E402

ROBOT = MODELES.parent / "robot.json"


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture(scope="module")
def monde():
    return SimWorld.from_config(str(ROBOT), scene_rue())


def test_pose_et_vitesse_de_la_base(monde):
    monde.reset()
    monde.set_robot_pose(1.0, -0.5, 30)
    x, y, cap = monde.get_robot_pose()
    assert (x, y, cap) == pytest.approx((1.0, -0.5, 30), abs=1e-6)
    monde.set_goal_velocities({m: 100 * (1 if "gauche" in m else -1) for m in monde.motors})
    monde.step(500)
    avance, rotation = monde.get_robot_velocity()
    assert avance == pytest.approx(0.47, abs=0.05)      # roue de 90 mm à 100 tr/min
    assert abs(rotation) < 0.1
    x2, y2, _ = monde.get_robot_pose()
    assert np.degrees(np.arctan2(y2 - y, x2 - x)) == pytest.approx(30, abs=3)    # il avance selon son cap


def test_obstacle_mocap_et_contact(monde):
    monde.reset()
    monde.set_robot_pose(0, 0, 0)
    assert monde.robot_contacts() == set()
    bloc = next(o for o in scene_rue()["objects"] if o.get("mocap"))
    monde.set_object_pose(bloc["name"], [0.1, 0, bloc["size"][2]])      # posé sur la chaussée, contre le robot
    monde.step(1)
    assert bloc["name"] in monde.robot_contacts()


def test_interface_robot():
    robot = ErranceRobot()
    robot.setup({"roue_a_gauche.velocity": (-100, 100), "roue_b_droite.velocity": (-100, 100), "x.position": None})
    robot.reset()
    # un seul obstacle à 1 m droit devant, aucune mesure ailleurs
    scan = np.zeros((400, 2))
    scan[:, 0] = np.arange(400) * 0.9
    scan[0, 1] = 100
    obs = robot.observation({"lidar_1": scan})
    assert obs.shape == (SECTEURS + 2,) and obs[0] == pytest.approx(0.5) and np.all(obs[1:] == [1.0] * 39 + [0, 0])
    assert robot.action(np.array([1.0, 0.5])) == {"roue_a_gauche.velocity": 100, "roue_b_droite.velocity": -50}
    assert list(robot.observation({"lidar_1": scan})[SECTEURS:]) == [1.0, 0.5]     # action précédente


def test_environnement_gymnasium():
    from gymnasium.utils.env_checker import check_env
    env = ErranceEnv()
    check_env(env, skip_render_check=True)
    observation, _ = env.reset(seed=0)
    assert env.observation_space.contains(observation)
    assert env.plus_proche > 0.5            # départ dans une place libre


def test_entrainement_sans_dataset(tmp_path):
    assert not besoin_dataset(MODELES / "errance_ppo.py")
    (tmp_path / "bc.py").write_text("data = load_data(inputs=['state'])")
    (tmp_path / "act.py").write_text("train_lerobot(policy='act')")
    assert besoin_dataset(tmp_path / "bc.py") and besoin_dataset(tmp_path / "act.py")


def test_modele_rl_pilote_le_robot(app, robot_simule, tmp_path):
    from stable_baselines3 import PPO
    model = PPO("MlpPolicy", ErranceEnv(), n_steps=64, batch_size=32, device="cpu", seed=0)
    dossier = save_rl_model(model, ErranceRobot, tmp_path / "robot" / "modeles" / "errance_ppo" / "1")
    assert trained_models(tmp_path / "robot") == [dossier]
    info = model_info(dossier)
    assert info["kind"] == "RL PPO" and info["fps"] == 10 and info["inputs"] == ["lidar_1"]
    assert (dossier / "errance_env.py").exists()            # l'interface est copiée avec le modèle
    assert isinstance(load_policy(dossier), RLPolicy)

    vm = IAViewModel(MagicMock())
    vm.set_dossier_robot(tmp_path / "robot")
    vm.connect_to_robot(robot_simule("test_mobile"))
    etats = []
    vm.etat_changed.connect(etats.append)
    vm.demarrer(str(dossier), fps=10, duree_s=0.5, replacer=False)
    debut = time.time()
    while vm.is_running() and time.time() - debut < 30:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert etats[-1].startswith("Terminé au bout de"), etats


def test_scene_de_mir_depart_libre():
    # dans MIR, le robot part du centre de la rue : la disposition fixe des décombres doit le laisser libre
    import json
    scene = json.loads((MODELES.parent / "scenes" / "rue_decombres.json").read_text(encoding="utf-8"))
    monde = SimWorld.from_config(str(ROBOT), scene)
    assert monde.data.qpos[2] < 0.05        # posé sur la chaussée (pas sur la réserve de décombres, sous le sol)
    assert monde.model.stat.extent < 20     # réserve rangée sous la rue : scène à sa taille, ombres nettes
    monde.step(10)
    assert monde.robot_contacts() == set()
    distances = monde.lidar_scan("lidar_1")[1]
    assert distances[distances > 0].min() > 0.5
