"""Piloter → IA : un modèle entraîné pilote le robot simulé (boucle de fond, arrêt, arrêt d'urgence, erreurs)."""
import time
from unittest.mock import MagicMock
import pytest
import torch
from torch import nn
from PySide6.QtCore import QCoreApplication
from mir_robot.donnees import DatasetMIR, FormatDataset
from mir_robot.training import load_data, save_model
from mir_robot_editor.ia.ia_view_model import IAViewModel


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


class Policy(nn.Module):
    def __init__(self, n_state, n_actions):
        super().__init__()
        self.net = nn.Linear(n_state, n_actions)

    def forward(self, batch):
        return self.net(batch["state"])


@pytest.fixture
def robot_et_modele(robot_simule, tmp_path):
    """Bras simulé et un petit modèle (état -> actions) rangé dans le dossier du robot, comme après un entraînement."""
    robot = robot_simule("bras_2ddl")
    observables = robot.get_observables()
    fmt = FormatDataset.depuis_robot(observables, [n for n in observables if n.endswith(".position")],
                                     list(robot.action_features))
    ds = DatasetMIR(tmp_path / "robot" / "datasets" / "demo")
    for e in range(2):
        ds.ajouter_episode(fmt, 20, [fmt.trame(robot.get_observation(), {a: 10.0 * e for a in fmt.actions})
                                     for _ in range(5)], "test")
    data = load_data(["state"], dataset=ds.dossier, device="cpu")
    dossier = save_model(Policy(data.n_state, data.n_actions), data, tmp_path / "robot" / "modeles" / "mlp" / "1")
    return robot, dossier


def attendre_la_fin(app, vm, delai=30):
    debut = time.time()
    while vm.is_running() and time.time() - debut < delai:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def test_le_modele_pilote_le_robot(app, robot_et_modele):
    robot, dossier = robot_et_modele
    replacer = MagicMock()
    vm = IAViewModel(MagicMock(), replacer_scene=replacer)
    vm.set_dossier_robot(dossier.parent.parent.parent)
    assert [m["name"] for m in vm.modeles()] == ["mlp"] and vm.modeles()[0]["fps"] == 20
    vm.connect_to_robot(robot)
    etats, occupe = [], []
    vm.etat_changed.connect(etats.append)
    vm.busy_state_changed.connect(occupe.append)

    debut = time.time()
    vm.demarrer(str(dossier), fps=20, duree_s=0.5, replacer=True)
    assert vm.is_running()
    attendre_la_fin(app, vm)
    assert not vm.is_running() and occupe == [True, False]
    assert 0.5 <= time.time() - debut < 10
    replacer.assert_called_once()
    assert etats[0] == "Chargement du modèle…" and etats[-1].startswith("Terminé au bout de")


def test_arreter_et_arret_d_urgence(app, robot_et_modele):
    robot, dossier = robot_et_modele
    vm = IAViewModel(MagicMock())
    vm.connect_to_robot(robot)
    vm.demarrer(str(dossier), fps=20, duree_s=None, replacer=False)      # jusqu'à « Arrêter »
    time.sleep(0.5)
    vm.arreter()
    attendre_la_fin(app, vm)
    assert not vm.is_running()

    etats = []
    vm.etat_changed.connect(etats.append)
    vm.demarrer(str(dossier), fps=20, duree_s=None, replacer=False)
    time.sleep(0.5)
    vm.arret_urgence()
    attendre_la_fin(app, vm)
    assert not vm.is_running() and etats[-1].startswith("Arrêt d'urgence")


def test_modele_incompatible_avec_le_robot(app, robot_et_modele, robot_simule):
    _, dossier = robot_et_modele
    dialogues = MagicMock()
    vm = IAViewModel(dialogues)
    vm.connect_to_robot(robot_simule("test_mobile"))           # robot à roues : pas les grandeurs du bras
    vm.demarrer(str(dossier), fps=20, duree_s=1, replacer=False)
    attendre_la_fin(app, vm)
    assert not vm.is_running()
    dialogues.information.assert_called_once()
    assert "joint_1.position" in dialogues.information.call_args[0][1]


def test_une_seule_activite_a_la_fois(app, robot_et_modele):
    robot, dossier = robot_et_modele
    dialogues = MagicMock()
    vm = IAViewModel(dialogues, other_busy=lambda: True)
    vm.connect_to_robot(robot)
    vm.demarrer(str(dossier), fps=20, duree_s=1, replacer=False)
    assert not vm.is_running()
    dialogues.information.assert_called_once()
