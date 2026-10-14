
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
from torchvision.models import resnet18

from mir_robot.mir_robot import mirRobot, mirRobotConfig
from mir_utils.period_waiters import PeriodWaiterExact




# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(
    "/Users/marius/Documents/Atelier Vectoriel/MIR/"
    "MIR-software/mir/mir_user_scripts/bras_leader_follower_cam"
)

LEADER_CONFIG = BASE_DIR / "bras_leader.json"
FOLLOWER_CONFIG = BASE_DIR / "bras_follower_cam.json"

MODEL_PATH = (
    BASE_DIR
    / "outputs/train/resnet18_mir/model_resnet18_best.pth"
)

IMAGE_WIDTH = 320
IMAGE_HEIGHT = 240

FPS = 20
PERIOD = 1 / FPS
MOVEMENT_DURATION = 5.0

MAX_DELTA = 5.0

JOINT_KEYS = [f"joint_{i}.position" for i in range(1, 6)]

DEVICE = torch.device(
    "mps" if torch.backends.mps.is_available() else "cpu"
)


INITIAL_POSITION = np.array(
    [-56.57, 27.0, -80.66, 80.31, 9.54],
    dtype=np.float32,
)

# ============================================================
# MODELE
# ============================================================

class ResNet18Policy(nn.Module):
    def __init__(self):
        super().__init__()

        self.cnn = resnet18(weights=None)
        self.cnn.fc = nn.Identity()

        self.state_encoder = nn.Sequential(
            nn.Linear(5, 32),
            nn.ReLU(),
        )

        self.mlp = nn.Sequential(
            nn.Linear(512 + 32, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 5),
        )

    def forward(self, image, state):
        visual_features = self.cnn(image)
        state_features = self.state_encoder(state)
        x = torch.cat([visual_features, state_features], dim=1)
        return self.mlp(x)


def load_policy():
    checkpoint = torch.load(
        MODEL_PATH,
        map_location="cpu",
        weights_only=False,
    )

    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        weights = checkpoint["model_state_dict"]
    elif isinstance(checkpoint, dict) and "model" in checkpoint:
        weights = checkpoint["model"]
    else:
        weights = checkpoint

    model = ResNet18Policy()
    model.load_state_dict(weights)
    model.to(DEVICE)
    model.eval()

    return model


# ============================================================
# PRETRAITEMENT
# ============================================================

IMAGE_MEAN = torch.tensor(
    [0.485, 0.456, 0.406]
).view(1, 3, 1, 1)

IMAGE_STD = torch.tensor(
    [0.229, 0.224, 0.225]
).view(1, 3, 1, 1)


def prepare_inputs(image, state):
    image = np.asarray(image)

    # Même rotation que lors de la création du dataset.
    image = cv2.rotate(image, cv2.ROTATE_180)
    image = cv2.resize(image, (IMAGE_WIDTH, IMAGE_HEIGHT))

    image = torch.from_numpy(
        np.ascontiguousarray(image)
    ).float()

    if image.max() > 1.5:
        image = image / 255.0

    image = image.permute(2, 0, 1).unsqueeze(0)

    image = (image - IMAGE_MEAN) / IMAGE_STD

    state = torch.tensor(
        np.asarray(state, dtype=np.float32)
    ).reshape(1, 5)

    return image.to(DEVICE), state.to(DEVICE)


def extract_state(observation):
    return np.array(
        [observation[k] for k in JOINT_KEYS],
        dtype=np.float32,
    )


# ============================================================
# SEQUENCE DE 5 SECONDES
# ============================================================

def run_policy_for_5_seconds(model, follower):

    print("\nDébut de la séquence de 5 secondes.")

    # Le compteur de temps démarre au début de cette séquence.
    period_waiter = PeriodWaiterExact(PERIOD)
    period_waiter.start()

    start_time = time.perf_counter()
    step = 0

    try:
        while time.perf_counter() - start_time < MOVEMENT_DURATION:

            # Observation actuelle du follower et caméra.
            obs = follower.get_observation()

            state = extract_state(obs)
            camera = np.asarray(obs["cam_1"])

            # Inférence.
            image_tensor, state_tensor = prepare_inputs(
                camera, state
            )

            with torch.no_grad():
                prediction = model(
                    image_tensor, state_tensor
                )[0].cpu().numpy()

            # Limitation du déplacement par cycle.
            delta = prediction - state
            safe_delta = np.clip(
                delta, -MAX_DELTA, MAX_DELTA
            )
            safe_action = state + safe_delta

            # Construction de l'action.
            action = {
                key: float(value)
                for key, value in zip(JOINT_KEYS, safe_action)
            }

            # Envoi au follower.
            follower.send_action(action)

            step += 1

            # Cadence cible : 20 Hz.
            period_waiter.wait()

    except KeyboardInterrupt:
        print("\nSéquence interrompue par l'utilisateur.")

    elapsed = time.perf_counter() - start_time

    print(
        f"Fin de séquence : {elapsed:.2f} s, "
        f"{step} commandes envoyées."
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Checkpoint introuvable : {MODEL_PATH}"
        )

    model = load_policy()
    print(f"Modèle chargé sur {DEVICE}")

    leader = mirRobot(
        mirRobotConfig.load(str(LEADER_CONFIG))
    )

    follower = mirRobot(
        mirRobotConfig.load(str(FOLLOWER_CONFIG))
    )

    try:
        leader.connect()
        leader.configure()
        leader.enable_all_observations()

        follower.connect()
        follower.configure()
        follower.enable_all_observations()

        print("\nRobots connectés.")

        input(
            "\nPlace le bras dans une configuration sûre, "
            "dégage la zone de travail, puis appuie sur Entrée."
        )

        print("Position initiale cible :", INITIAL_POSITION)

        input(
            "\nVérifie que la zone est dégagée, "
            "puis appuie sur Entrée pour rejoindre la position initiale."
        )

        follower.send_action({
            key: float(value)
            for key, value in zip(JOINT_KEYS, INITIAL_POSITION)
        })

        time.sleep(1.0)

        print("Position initiale envoyée.")

        while True:
            command = input(
                "\nEntrée : lancer 5 secondes de politique ; "
                "'q' : quitter : "
            ).strip().lower()

            if command == "q":
                break

            run_policy_for_5_seconds(model, follower)

    finally:
        print("\nFin du programme.")
        # Ajouter ici la procédure de déconnexion propre
        # prévue par ta version de mirRobot.


if __name__ == "__main__":
    main()
