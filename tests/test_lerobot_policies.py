"""Modèles de LeRobot (ACT, Diffusion) : entraînement par un script d'élève, puis pilotage du robot simulé."""
import os
import runpy
import subprocess
import sys
import pytest
from mir_robot.commande import ExecutionCommande
from mir_robot.mir_robot import chemin_robot
from mir_robot.lerobot_policies import LeRobotPolicy
from mir_robot.training import DATASET_ENV, load_policy, model_info, trained_models

ROBOT = "bras_4ddl_cam_V2"


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    """2 démonstrations de ramassage, images réduites (les modèles de LeRobot s'entraînent à cette taille)."""
    generateur = runpy.run_path(str(chemin_robot(ROBOT).parent / "scripts" / "generer_ramassage.py"))
    dossier = tmp_path_factory.mktemp("robot") / "datasets" / "ramassage"
    reussies, _ = generateur["generer"](2, dossier, graine=1, taille=(128, 96))
    assert reussies == 2
    return dossier


SCRIPT = '''
from mir_robot.lerobot_policies import train_lerobot
train_lerobot(policy="{policy}", steps=4, batch_size=2, log_freq=2, device="cpu"{options})
'''


@pytest.mark.parametrize("policy, options", [("act", ""), ("diffusion", ", n_obs_steps=2")])
def test_entrainer_puis_piloter(dataset, policy, options, robot_simule, clavier):
    robot_dir = dataset.parent.parent
    script = robot_dir / "modeles" / f"mon_{policy}.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(SCRIPT.format(policy=policy, options=options), encoding="utf-8")
    resultat = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=600,
                              env={**os.environ, DATASET_ENV: str(dataset), "MPLBACKEND": "Agg"})
    assert resultat.returncode == 0, resultat.stdout[-1500:] + resultat.stderr[-1500:]
    assert "loss:" in resultat.stdout and "Modèle enregistré" in resultat.stdout     # journal dans la console

    dossier = next(d for d in trained_models(robot_dir) if d.parent.name == f"mon_{policy}")
    info = model_info(dossier)
    assert info["type"] == "lerobot" and info["actions"] == [f"joint_{i}.position" for i in range(1, 6)]
    assert (dossier / f"mon_{policy}.py").exists()                                   # copie du script

    politique = load_policy(dossier)
    assert isinstance(politique, LeRobotPolicy) and politique.images == {"cam_1": (3, 96, 128)}
    robot = robot_simule(ROBOT)                     # caméra en 640 x 480 : réduite à la taille du dataset
    execution = ExecutionCommande(robot, politique, fps=20, clavier=clavier)
    for _ in range(3):
        execution.tour(robot.get_observation())
        assert set(execution.derniere_action) == set(info["actions"])
    execution.arreter()
