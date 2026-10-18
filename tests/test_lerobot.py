"""
Test de compatibilité avec LeRobot, en simulation (aucun matériel nécessaire).

À lancer avant de changer la version de LeRobot figée dans mir_devices/pyproject.toml :
    python tests/test_lerobot.py
(il fait aussi partie des tests lancés par python -m pytest)
Vérifie la chaîne des données : robot simulé -> épisodes enregistrés -> dataset complété puis modifié -> relecture par
MIR et par un DataLoader PyTorch (comme les scripts d'entraînement). Le bus moteur réel, lui, se vérifie sur le robot.
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path
import importlib.metadata

from mir_robot.donnees import DatasetMIR, FormatDataset, decodeur_video
from mir_robot.mir_robot import chemin_robot, mirRobot, mirRobotConfig
from mir_sim.config_from_structure import complete_config_from_structure
from mir_sim.sim_devices_factory import SimDevicesFactory

ROBOTS = {"bras_4ddl_cam_V2": "cam_1", "test_mobile": "lidar_1"}     # un robot avec caméra, un avec lidar


def verifier(condition: bool, message: str):
    print(("  ok    " if condition else "  ÉCHEC ") + message)
    if not condition:
        sys.exit(1)


def main():
    print(f"LeRobot {importlib.metadata.version('lerobot')}, MuJoCo {importlib.metadata.version('mujoco')}")
    racine = Path(tempfile.mkdtemp(prefix="mir_test_lerobot_"))
    try:
        for nom, capteur in ROBOTS.items():
            print(f"{nom} :")
            cfg = mirRobotConfig.load(str(chemin_robot(nom)))
            complete_config_from_structure(cfg)
            robot = mirRobot(cfg, devices_factory=SimDevicesFactory())
            robot.connect()
            robot.configure()
            robot.enable_all_observations()
            observables = robot.get_observables()
            choisies = [n for n in observables if n.endswith(".position") or n == capteur]
            fmt = FormatDataset.depuis_robot(observables, choisies, list(robot.action_features))
            ds = DatasetMIR(racine / nom)
            for _ in range(3):
                trames = []
                for _ in range(10):
                    trames.append(fmt.trame(robot.get_observation(), {a: 0.0 for a in fmt.actions}))
                    time.sleep(0.01)
                ds.ajouter_episode(fmt, 20, trames, "test", {"simulation": True})
            robot.disconnect()
            verifier(len(ds.episodes()) == 3, "création puis ajout d'épisodes à un dataset existant")
            ds.supprimer_episodes([1])
            verifier([e.trames for e in ds.episodes()] == [10, 10], "suppression d'un épisode")
            episode = ds.charger_episode(1)
            donnees = list(episode["images"].values()) + list(episode["tableaux"].values())
            verifier(len(episode["t"]) == 10 and all(len(d) == 10 for d in donnees), f"relecture d'un épisode ({capteur})")

            import torch
            from lerobot.datasets import LeRobotDataset
            lot = next(iter(torch.utils.data.DataLoader(LeRobotDataset(ds.repo_id, root=ds.dossier,
                                                                         video_backend=decodeur_video()), batch_size=4)))
            verifier("action" in lot and lot["action"].shape[0] == 4, "lecture par un DataLoader PyTorch")
        print("Tout est compatible.")
    finally:
        shutil.rmtree(racine, ignore_errors=True)


def test_compatibilite_lerobot():
    main()


def test_compatibilite_lerobot_sans_ffmpeg(monkeypatch):
    """Comme sur un Mac ou un Linux sans ffmpeg installé : vidéos décodées par PyAV, qui embarque le sien."""
    import mir_robot.donnees
    monkeypatch.setattr(mir_robot.donnees, "decodeur_video", lambda: "pyav")
    monkeypatch.setitem(globals(), "decodeur_video", lambda: "pyav")
    main()


if __name__ == "__main__":
    main()
