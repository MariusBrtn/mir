"""Démonstrations automatiques en simulation : objets de la scène, MGI de la pince, générateur de ramassage."""
import runpy
import numpy as np
import pytest
from mir_robot.donnees import DatasetMIR
from mir_robot.mir_robot import chemin_robot
from mir_sim.grasp import GripperIK
from mir_sim.sim_world import SimWorld
from conftest import config_robot

GENERATEUR = chemin_robot("bras_4ddl_cam_V2").parent / "scripts" / "generer_ramassage.py"
SCENE = GENERATEUR.with_name("ramassage_de.json")


@pytest.fixture(scope="module")
def monde():
    return SimWorld.from_config(config_robot("bras_4ddl_cam_V2"), SCENE)


def test_replacer_un_objet(monde):
    monde.set_object_pose("de", [0.15, -0.03, 0.008], yaw_deg=30)
    assert monde.get_object_position("de") == pytest.approx([0.15, -0.03, 0.008])
    monde.step(250)                                         # 0,5 s : posé sur la table, il ne bouge pas
    assert monde.get_object_position("de") == pytest.approx([0.15, -0.03, 0.008], abs=1e-3)


def test_mgi_de_la_pince(monde):
    ik = GripperIK(monde)
    assert ik.gripper_motor == "joint_5" and ik.arm == ["joint_1", "joint_2", "joint_3", "joint_4"]
    cible = np.array([0.19, 0.02, 0.008])
    angles = ik.solve(cible)
    assert angles is not None
    point, doigts, serrage = ik.forward(angles)
    assert np.linalg.norm(point - cible) < 1e-3
    assert abs(serrage[2]) < 0.05                           # les mors serrent à l'horizontale
    assert doigts[2] < -0.7                                 # les doigts pointent vers le bas
    juste_au_dessus = ik.solve(cible + [0, 0, 0.05], start=angles)
    assert np.linalg.norm(ik.forward(juste_au_dessus)[0] - cible - [0, 0, 0.05]) < 1e-3
    assert ik.solve([0.5, 0.0, 0.008]) is None              # hors de portée


def test_generateur_de_ramassage(tmp_path):
    generateur = runpy.run_path(str(GENERATEUR))
    reussies, essais = generateur["generer"](2, tmp_path / "ramassage", graine=3)
    assert reussies == 2 and essais <= 3
    ds = DatasetMIR(tmp_path / "ramassage")
    episodes = ds.episodes()
    assert len(episodes) == 2 and all(e.trames == 100 for e in episodes)       # 5 s à 20 Hz
    fmt = ds.format()
    assert fmt.etat == [f"joint_{i}.position" for i in range(1, 6)] and list(fmt.images) == ["cam_1"]
    episode = ds.charger_episode(0)
    assert episode["actions"][-1][4] == pytest.approx(14.0)                     # pince fermée à la fin
    assert episode["etat"][0][:4] == pytest.approx([0, -60, 90, -90], abs=0.5)  # posture de départ


def test_objet_fait_de_plusieurs_formes():
    """La boîte percée de l'insertion : un seul objet (un corps), plusieurs formes."""
    monde = SimWorld.from_config(config_robot("bras_4ddl_cam_V2"), GENERATEUR.with_name("insertion_boite.json"))
    corps = monde.model.body("boite").id
    formes = [i for i in range(monde.model.ngeom) if monde.model.geom_bodyid[i] == corps]
    assert len(formes) == 9                                  # fond, 4 parois, couvercle en 4 plaques
    assert monde.model.body_mass[corps] == pytest.approx(0.3)


def test_generateur_d_insertion(tmp_path):
    generateur = runpy.run_path(str(GENERATEUR.with_name("generer_insertion.py")))
    reussies, essais = generateur["generer"](1, tmp_path / "insertion", graine=2, taille=(320, 240))
    assert reussies == 1
    ds = DatasetMIR(tmp_path / "insertion")
    assert ds.format().images == {"cam_1": (240, 320, 3)}
    episode = ds.charger_episode(0)
    assert episode["actions"][0][4] == pytest.approx(14.0)                      # cube tenu au départ
    assert episode["actions"][-1][4] == pytest.approx(-14.0)                    # pince ouverte à la fin
