"""Format des datasets : correspondance entre les grandeurs de MIR et les colonnes LeRobot.
L'écriture et la relecture des datasets sont vérifiées par test_lerobot.py."""
import numpy as np
import pytest
from mir_robot.donnees import ACTION, ETAT, DatasetMIR, FormatDataset, cle_image, cle_tableau, episode_depuis_trames


@pytest.mark.parametrize("nom, capteur", [("bras_4ddl_cam_V2", "cam_1"), ("test_mobile", "lidar_1")])
def test_format_et_trame(robot_simule, nom, capteur):
    robot = robot_simule(nom)
    observables = robot.get_observables()
    choisies = [n for n in observables if n.endswith(".position") or n == capteur]
    fmt = FormatDataset.depuis_robot(observables, choisies, list(robot.action_features))

    assert fmt.etat == [n for n in observables if n.endswith(".position")]
    assert capteur in fmt.images or capteur in fmt.tableaux
    assert FormatDataset.depuis_features(fmt.features()) == fmt

    trame = fmt.trame(robot.get_observation(), {fmt.actions[0]: 12.5})
    assert trame[ETAT].dtype == np.float32 and trame[ETAT].shape == (len(fmt.etat),)
    assert trame[ACTION][0] == 12.5 and trame[ACTION].shape == (len(fmt.actions),)
    if capteur in fmt.images:
        assert trame[cle_image(capteur)].shape == fmt.images[capteur]
    else:
        assert trame[cle_tableau(capteur)].shape == fmt.tableaux[capteur]

    episode = episode_depuis_trames(fmt, 20, [trame] * 4)
    assert episode["t"].tolist() == [0, 0.05, 0.1, 0.15]
    assert episode["actions"].shape == (4, len(fmt.actions))


def test_ajout_refuse_si_le_format_change(robot_simule, tmp_path):
    robot = robot_simule("bras_2ddl")
    observables = robot.get_observables()
    fmt = FormatDataset.depuis_robot(observables, ["joint_1.position"], list(robot.action_features))
    trames = [fmt.trame(robot.get_observation(), {}) for _ in range(3)]
    ds = DatasetMIR(tmp_path / "demo")
    ds.ajouter_episode(fmt, 20, trames, "test")

    with pytest.raises(ValueError, match="Hz"):
        ds.ajouter_episode(fmt, 30, trames, "test")
    autre = FormatDataset.depuis_robot(observables, ["joint_2.position"], list(robot.action_features))
    with pytest.raises(ValueError, match="mêmes grandeurs"):
        ds.ajouter_episode(autre, 20, [autre.trame(robot.get_observation(), {})], "test")
    assert len(ds.episodes()) == 1
