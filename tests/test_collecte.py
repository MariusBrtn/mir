"""Collecter des données : une seule scène par dataset, en simulé."""
from unittest.mock import MagicMock
from mir_robot.donnees import DatasetMIR, FormatDataset
from mir_robot_editor.collecte.collecte_view_model import CollecteViewModel


def dataset_dans_la_scene(dossier, robot, scene):
    observables = robot.get_observables()
    fmt = FormatDataset.depuis_robot(observables, ["joint_1.position"], list(robot.action_features))
    ds = DatasetMIR(dossier)
    ds.ajouter_episode(fmt, 20, [fmt.trame(robot.get_observation(), {}) for _ in range(3)], "test",
                       {"simulation": True, "scene": scene})
    return ds


def test_une_scene_par_dataset(robot_simule, tmp_path):
    ds = dataset_dans_la_scene(tmp_path / "demo", robot_simule("bras_2ddl"), "ramassage_de.json")
    etat = {"scene": "bac_a_sable.json", "simulation": True}
    choisir = MagicMock(side_effect=lambda nom: etat.update(scene=nom) or True)
    vm = CollecteViewModel(MagicMock(), conditions=lambda: {"simulation": etat["simulation"]},
                           scene=lambda: etat["scene"], choisir_scene=choisir, nom_scene=str.upper)
    assert vm.scene_du_dataset(ds) == "ramassage_de.json"
    assert "RAMASSAGE_DE.JSON" in vm.conflit_de_scene(ds) and "BAC_A_SABLE.JSON" in vm.conflit_de_scene(ds)

    vm.aligner_scene(ds)                                    # choisir le dataset : sa scène est choisie
    choisir.assert_called_once_with("ramassage_de.json")
    assert vm.conflit_de_scene(ds) is None

    etat["simulation"] = False                              # robot réel : pas de scène
    etat["scene"] = "bac_a_sable.json"
    assert vm.conflit_de_scene(ds) is None


def test_dataset_sans_scene(robot_simule, tmp_path):
    vm = CollecteViewModel(MagicMock(), conditions=lambda: {"simulation": True}, scene=lambda: "table vide")
    assert vm.scene_du_dataset(None) is None
    assert vm.scene_du_dataset(DatasetMIR(tmp_path / "pas_encore_cree")) is None      # nouveau dataset : libre
    assert vm.conflit_de_scene(DatasetMIR(tmp_path / "pas_encore_cree")) is None
