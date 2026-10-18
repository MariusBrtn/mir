"""Entraîner un modèle PyTorch sur un dataset, puis le faire piloter le robot simulé (mir_robot.training)."""
import math
import os
import subprocess
import sys
import time
import pytest
import torch
from torch import nn
from conftest import config_robot
from mir_robot.commande import ExecutionCommande
from mir_robot.donnees import DatasetMIR, FormatDataset, cle_image
from mir_robot.mir_robot import mirRobot
from mir_robot.training import (DATASET_ENV, MODEL_FILE, PREPARATION_FILE, TrainedPolicy, load_data, save_model,
                                trained_models)
from mir_sim.sim_devices_factory import SimDevicesFactory

ROBOT = "bras_4ddl_cam_V2"
IMAGE_SIZE = (48, 64)


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """Dataset de 3 épisodes enregistré sur le bras simulé (qui bouge), et les observations brutes enregistrées."""
    robot = mirRobot(config_robot(ROBOT), devices_factory=SimDevicesFactory())
    robot.connect()
    robot.configure()
    robot.enable_all_observations()
    observables = robot.get_observables()
    fmt = FormatDataset.depuis_robot(observables, [n for n in observables if n.endswith(".position") or n == "cam_1"],
                                     list(robot.action_features))
    dossier = tmp_path_factory.mktemp("robot") / "datasets" / "demo"
    ds = DatasetMIR(dossier)
    observations = []
    try:
        for episode in range(3):
            trames = []
            for k in range(8):
                action = {a: 25.0 * math.sin(0.4 * k + episode + i) for i, a in enumerate(fmt.actions)}
                robot.send_action(action)
                time.sleep(0.03)
                observation = robot.get_observation()
                observations.append({n: (v.copy() if hasattr(v, "copy") else v) for n, v in observation.items()})
                trames.append(fmt.trame(observation, action))
            ds.ajouter_episode(fmt, 20, trames, "test")
    finally:
        robot.disconnect()
    return ds, observations


class Policy(nn.Module):
    """Petit réseau d'élève : image -> petit CNN, concaténé à l'état -> actions."""

    def __init__(self, n_state, n_actions):
        super().__init__()
        self.cnn = nn.Sequential(nn.Conv2d(3, 4, 5, stride=4), nn.ReLU(), nn.AdaptiveAvgPool2d(1), nn.Flatten())
        self.head = nn.Sequential(nn.Linear(4 + n_state, 16), nn.ReLU(), nn.Linear(16, n_actions))

    def forward(self, batch):
        return self.head(torch.cat([self.cnn(batch["cam_1"]), batch["state"]], dim=1))


def entrainer(data, epochs=2):
    model = Policy(data.n_state, data.n_actions).to(data.device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
    for _ in range(epochs):
        for batch in data.train_loader:
            loss = nn.functional.mse_loss(model(batch), batch["action"])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
    return model


# ---------------------------------------------------------------- préparation

def test_meme_preparation_sur_le_robot_et_dans_le_dataset(demo):
    """La même observation, préparée en direct sur le robot ou relue dans le dataset, donne le même tenseur.
    C'est ce qui garantit que le modèle voit sur le robot ce qu'il a vu à l'entraînement (ex. division par 255)."""
    from lerobot.datasets import LeRobotDataset
    ds, observations = demo
    data = load_data(["state", "cam_1"], image_size=IMAGE_SIZE, dataset=ds.dossier, device="cpu")
    preparation = data.preparation
    relu = LeRobotDataset(ds.repo_id, root=ds.dossier)
    for i in (0, 5, 12, 23):
        item = relu[i]
        depuis_dataset = preparation.prepare({"state": item["observation.state"][None],
                                              "cam_1": item[cle_image("cam_1")][None]})
        en_direct = preparation.prepare(preparation.raw_from_observation(observations[i]))
        assert depuis_dataset["state"].shape == en_direct["state"].shape == (1, 5)
        assert torch.allclose(depuis_dataset["state"], en_direct["state"], atol=1e-4)
        assert depuis_dataset["cam_1"].shape == en_direct["cam_1"].shape == (1, 3, *IMAGE_SIZE)
        # la vidéo est compressée : écart faible, mais pas nul (un oubli de /255 donnerait un écart de l'ordre de 100)
        assert (depuis_dataset["cam_1"] - en_direct["cam_1"]).abs().mean() < 0.05


def test_donnees_preparees(demo):
    ds, _ = demo
    data = load_data(["state", "cam_1"], image_size=IMAGE_SIZE, dataset=ds.dossier, batch_size=4, device="cpu")
    assert data.n_state == data.n_actions == 5
    assert data.shapes == {"state": (5,), "cam_1": (3, *IMAGE_SIZE)}
    assert sorted(data.train_episodes + data.val_episodes) == [0, 1, 2] and len(data.val_episodes) == 1

    batches = list(data.train_loader)
    assert sum(len(b["action"]) for b in batches) == 16                    # 2 épisodes de 8 trames
    batch = batches[0]
    assert set(batch) == {"state", "cam_1", "action"}
    assert batch["cam_1"].shape == (4, 3, *IMAGE_SIZE) and batch["cam_1"].dtype == torch.float32
    assert -3 < batch["cam_1"].mean() < 3                                   # standardisée, pas entre 0 et 255
    tout = torch.cat([b["action"] for b in batches])
    assert tout.abs().max() < 5                                             # actions standardisées
    assert data.evaluate(Policy(5, 5)) > 0


def test_entree_inconnue(demo):
    ds, _ = demo
    with pytest.raises(ValueError, match="Entrées possibles .*state, cam_1"):
        load_data(["state", "camera"], dataset=ds.dossier)


def test_sans_dataset(monkeypatch):
    monkeypatch.delenv(DATASET_ENV, raising=False)
    with pytest.raises(ValueError, match="aucun dataset"):
        load_data(["state"])


# ---------------------------------------------------------------- enregistrement et pilotage

def test_entrainer_enregistrer_puis_piloter_le_robot(demo, tmp_path, robot_simule, clavier):
    ds, observations = demo
    data = load_data(["state", "cam_1"], image_size=IMAGE_SIZE, dataset=ds.dossier, batch_size=4, device="cpu")
    model = entrainer(data)
    dossier = save_model(model, data, tmp_path / "cnn")
    assert (dossier / MODEL_FILE).exists() and (dossier / PREPARATION_FILE).exists()

    politique = TrainedPolicy(dossier)          # rechargé sans la classe Policy (torch.export)
    observation = observations[3]
    with torch.no_grad():
        attendu = data.preparation.denormalize_action(
            model.eval()(data.preparation.prepare(data.preparation.raw_from_observation(observation))))[0]
    actions = politique.predict(observation)
    assert list(actions) == data.preparation.action_names
    assert list(actions.values()) == pytest.approx(attendu.tolist(), abs=1e-4)   # en degrés, pas normalisées

    robot = robot_simule(ROBOT)
    execution = ExecutionCommande(robot, politique, fps=20, clavier=clavier)
    for _ in range(5):
        assert execution.tour(robot.get_observation())
        assert set(execution.derniere_action) == set(data.preparation.action_names)
    execution.arreter()


def test_robot_sans_les_observations_du_modele(demo, tmp_path, robot_simule, clavier):
    ds, _ = demo
    data = load_data(["state", "cam_1"], image_size=IMAGE_SIZE, dataset=ds.dossier, device="cpu")
    dossier = save_model(entrainer(data, epochs=0), data, tmp_path / "cnn")
    with pytest.raises(ValueError, match="cam_1"):
        ExecutionCommande(robot_simule("bras_2ddl"), TrainedPolicy(dossier), fps=20, clavier=clavier)


def test_modele_non_exportable(demo, tmp_path):
    class AvecUnIf(Policy):
        def forward(self, batch):
            if batch["state"].sum() > 0:            # dépend des valeurs : torch.export ne sait pas faire
                return super().forward(batch)
            return -super().forward(batch)

    ds, _ = demo
    data = load_data(["state", "cam_1"], image_size=IMAGE_SIZE, dataset=ds.dossier, device="cpu")
    with pytest.raises(ValueError, match="torch.export"):
        save_model(AvecUnIf(5, 5), data, tmp_path / "x")


SCRIPT_ELEVE = '''
import torch
from torch import nn
from mir_robot.training import load_data, save_model

data = load_data(inputs=["state"], batch_size=8)


class Policy(nn.Module):
    def __init__(self, n_state, n_actions):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_state, 32), nn.ReLU(), nn.Linear(32, n_actions))

    def forward(self, batch):
        return self.net(batch["state"])


model = Policy(data.n_state, data.n_actions).to(data.device)
optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
for epoch in range(3):
    for batch in data.train_loader:
        loss = nn.functional.mse_loss(model(batch), batch["action"])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    print(epoch, loss.item(), data.evaluate(model))
save_model(model, data)
'''


def test_script_eleve_lance_comme_par_mir(demo, tmp_path):
    """Le script de l'élève, lancé dans un processus à part avec le dataset choisi dans MIR."""
    ds, _ = demo
    script = tmp_path / "mlp.py"
    script.write_text(SCRIPT_ELEVE, encoding="utf-8")
    resultat = subprocess.run([sys.executable, str(script)], env={**os.environ, DATASET_ENV: str(ds.dossier)},
                              capture_output=True, text=True, timeout=300)
    assert resultat.returncode == 0, resultat.stderr[-2000:]
    assert "Modèle enregistré" in resultat.stdout

    robot_dir = ds.dossier.parent.parent
    modeles = trained_models(robot_dir)
    assert len(modeles) == 1 and modeles[0].parent.name == "mlp"            # robots/<robot>/modeles/mlp/<date>
    assert (modeles[0] / "mlp.py").read_text(encoding="utf-8") == SCRIPT_ELEVE
    assert TrainedPolicy(modeles[0]).preparation.inputs == ["state"]
