"""Étape « Entraîner un modèle » : scripts créés à partir des modèles proposés, adaptés au dataset du robot."""
import os
import subprocess
import sys
from unittest.mock import MagicMock
import pytest
from conftest import config_robot
from mir_robot.donnees import DatasetMIR, FormatDataset
from mir_robot.mir_robot import mirRobot
from mir_robot.training import DATASET_ENV, MODELS_DIR, trained_models
from mir_robot_editor.entrainement.entrainement_view_model import EntrainementViewModel, LEROBOT, PYTORCH
from mir_sim.sim_devices_factory import SimDevicesFactory


def enregistrer_dataset(dossier, nom_robot, capteurs):
    """Un petit dataset du robot simulé : positions, et les capteurs demandés."""
    robot = mirRobot(config_robot(nom_robot), devices_factory=SimDevicesFactory())
    robot.connect()
    try:
        robot.configure()
        robot.enable_all_observations()
        observables = robot.get_observables()
        fmt = FormatDataset.depuis_robot(observables, [n for n in observables if n.endswith(".position") or n in capteurs],
                                         list(robot.action_features))
        ds = DatasetMIR(dossier)
        for _ in range(2):
            ds.ajouter_episode(fmt, 20, [fmt.trame(robot.get_observation(), {}) for _ in range(6)], "test")
    finally:
        robot.disconnect()
    return ds


@pytest.fixture
def entrainement(tmp_path):
    vm = EntrainementViewModel(MagicMock())
    return vm, tmp_path / "robot"


@pytest.mark.parametrize("nom_robot, capteurs", [("bras_4ddl_cam_V2", ["cam_1"]), ("bras_2ddl", [])])
def test_script_pytorch_adapte_au_dataset(entrainement, nom_robot, capteurs):
    vm, robot_dir = entrainement
    enregistrer_dataset(robot_dir / "datasets" / "demo", nom_robot, capteurs)
    vm.set_dossier_robot(robot_dir)
    assert [ds.nom for ds in vm.datasets()] == ["demo"] and vm.dataset().nom == "demo"     # choisi d'office
    assert "2 épisodes" in vm.resume_dataset()

    script = vm.nouveau("Mon réseau", PYTORCH)
    assert script == robot_dir / MODELS_DIR / "mon_reseau.py" and vm.fichiers() == [script]
    texte = script.read_text(encoding="utf-8")
    compile(texte, str(script), "exec")
    assert ("cam_1" in texte) == bool(capteurs)              # CNN si le dataset a une caméra, sinon MLP

    # le script, raccourci à 1 epoch, entraîne et enregistre son modèle (comme lancé par MIR)
    script.write_text(texte.replace("EPOCHS = 15", "EPOCHS = 1"), encoding="utf-8")
    resultat = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=300,
                              env={**os.environ, DATASET_ENV: str(vm.dataset().dossier), "MPLBACKEND": "Agg"})
    assert resultat.returncode == 0, resultat.stderr[-2000:]
    assert [m["name"] for m in vm.modeles()] == ["mon_reseau"] == [d.parent.name for d in trained_models(robot_dir)]


def test_script_lerobot(entrainement):
    vm, robot_dir = entrainement
    vm.set_dossier_robot(robot_dir)
    assert vm.dataset() is None and "Aucun dataset" in vm.resume_dataset()
    script = vm.nouveau("ACT ramassage", LEROBOT)
    texte = script.read_text(encoding="utf-8")
    compile(texte, str(script), "exec")
    assert 'train_lerobot(policy="act"' in texte
    assert vm.nouveau("ACT ramassage", LEROBOT) is None                     # existe déjà


def test_lancer_sans_dataset_est_refuse(entrainement):
    vm, robot_dir = entrainement
    vm.set_dossier_robot(robot_dir)
    vm.lancer(vm.nouveau("Essai", PYTORCH))
    assert not vm.is_running()
    vm._dialogProvider.information.assert_called()
