
"""
Inférence ACT sur le robot MIR
Environnement : Conda robot312
LeRobot : 0.5.1

À lancer depuis bras_leader_follower_cam.
"""

from datetime import datetime
from pathlib import Path
import json
import time

import cv2
import numpy as np
import torch

from mir_robot.mir_robot import mirRobot, mirRobotConfig
from mir_utils.period_waiters import PeriodWaiterExact

from lerobot.datasets import LeRobotDatasetMetadata
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATASET_REPO_ID = "local/mir_4ddl_cam_dice"
DATASET_ROOT = BASE_DIR / "dataset_dice"

MODEL_ROOT = (
    BASE_DIR
    / "outputs"
    / "train"
    / "act_batch4_chunk20"
    / "checkpoints"
    / "last"
    / "pretrained_model"
)

LEADER_CONFIG = BASE_DIR / "bras_leader.json"
FOLLOWER_CONFIG = BASE_DIR / "bras_follower_cam.json"

DEVICE = torch.device("mps")

FPS = 20
EPISODE_TIME = 6
NUM_STEPS = FPS * EPISODE_TIME

EXPECTED_CHUNK_SIZE = 20
EXPECTED_N_ACTION_STEPS = 10

EXECUTE_ACTIONS = True

#INITIAL_POSITION = [
 #   -55.912086486816406,
 #   28.30769157409668,
 #   -80.70330047607422,
 #   78.63735961914062,
 #   12.04395580291748,
#]

INITIAL_POSITION = [-55.384617,  31.912088, -80.7033,    78.54945,   11.692307]

# Même préparation d'image que lors de l'enregistrement (dataset.py)
ROTATE_IMAGE_180 = True
IMAGE_SIZE = (320, 240)  # (largeur, hauteur)

# Enregistrement de chaque essai (images vues par le modèle, états, actions)
# pour l'analyser ensuite avec analyse_essai_ACT.py
SAVE_LOGS = True
LOG_DIR = BASE_DIR / "logs_essais_ACT"

period_waiter = PeriodWaiterExact(1 / FPS)


# ============================================================
# VALIDATION
# ============================================================

if not MODEL_ROOT.is_dir():
    raise FileNotFoundError(
        f"Checkpoint ACT introuvable : {MODEL_ROOT}"
    )

if not (MODEL_ROOT / "config.json").is_file():
    raise FileNotFoundError(
        f"config.json absent dans {MODEL_ROOT}"
    )

if not DATASET_ROOT.is_dir():
    raise FileNotFoundError(
        f"Dataset introuvable : {DATASET_ROOT}"
    )


# ============================================================
# MÉTADONNÉES DU DATASET
# ============================================================

print("\nChargement des métadonnées...")

dataset_metadata = LeRobotDatasetMetadata(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT,
)

print("FPS dataset :", dataset_metadata.fps)
print("Features :")

for key, feature in dataset_metadata.features.items():
    print(f"  {key}: {feature}")


# ============================================================
# CHARGEMENT ACT
# ============================================================

print("\nChargement de la politique ACT...")

policy = ACTPolicy.from_pretrained(str(MODEL_ROOT))
policy.config.device = str(DEVICE)
policy = policy.to(DEVICE)
policy.eval()

print("Device :", DEVICE)
print("Chunk size :", policy.config.chunk_size)
print("n_action_steps :", policy.config.n_action_steps)

if policy.config.chunk_size != EXPECTED_CHUNK_SIZE:
    raise RuntimeError(
        f"Chunk size inattendu : {policy.config.chunk_size}"
    )

if policy.config.n_action_steps != EXPECTED_N_ACTION_STEPS:
    raise RuntimeError(
        f"n_action_steps inattendu : "
        f"{policy.config.n_action_steps}"
    )

preprocessor, postprocessor = make_pre_post_processors(
    policy_cfg=policy.config,
    pretrained_path=str(MODEL_ROOT),
    dataset_stats=dataset_metadata.stats,
)

print("Politique et processeurs chargés.")


# ============================================================
# CONNEXION AU ROBOT
# ============================================================

leader = mirRobot(
    mirRobotConfig.load(str(LEADER_CONFIG))
)

follower = mirRobot(
    mirRobotConfig.load(str(FOLLOWER_CONFIG))
)

print("\nConnexion au leader...")
leader.connect()
leader.configure()
leader.enable_all_observations()

print("\nConnexion au follower...")
follower.connect()
follower.configure()
follower.enable_all_observations()


# ============================================================
# CONSTRUCTION DE L'OBSERVATION
# ============================================================

def build_observation(observation):
    """
    Prépare l'image et les positions articulaires.

    Reproduit la chaîne de l'enregistrement puis de la lecture du dataset :
    rotation 180°, redimensionnement en 320x240 (dataset.py),
    puis CHW float32 dans [0, 1] (division par 255 faite par le décodeur
    vidéo de LeRobotDataset). Le preprocessor ne fait que la normalisation
    moyenne / écart-type, il ne divise pas par 255.
    """

    image = observation["cam_1"]

    if ROTATE_IMAGE_180:
        image = cv2.rotate(image, cv2.ROTATE_180)

    image = cv2.resize(
        image,
        IMAGE_SIZE,
        interpolation=cv2.INTER_AREA,
    )

    image_tensor = torch.from_numpy(
        np.ascontiguousarray(image)
    ).permute(2, 0, 1).to(torch.float32) / 255.0

    state = torch.tensor(
        [
            observation[f"joint_{j}.position"]
            for j in range(1, 6)
        ],
        dtype=torch.float32,
    )

    observation_frame = {
        "observation.images.cam_1": image_tensor,
        "observation.state": state,
    }

    return observation_frame, image


# ============================================================
# PRÉDICTION
# ============================================================

def predict_action(observation):

    observation_frame, image = build_observation(observation)

    observation_processed = preprocessor(
        observation_frame
    )

    with torch.inference_mode():
        action_processed = policy.select_action(
            observation_processed
        )

    action_unprocessed = postprocessor(
        action_processed
    )

    if isinstance(action_unprocessed, dict):
        action_tensor = action_unprocessed["action"]
    else:
        action_tensor = action_unprocessed

    action_values = (
        action_tensor.detach()
        .cpu()
        .reshape(-1)
        .numpy()
    )

    if len(action_values) != 5:
        raise RuntimeError(
            f"Action de dimension {len(action_values)}, "
            f"5 attendues. Forme : {tuple(action_tensor.shape)}"
        )

    if not np.isfinite(action_values).all():
        raise RuntimeError("Action ACT non finie.")

    action = {
        f"joint_{j}.position": float(action_values[j - 1])
        for j in range(1, 6)
    }

    state = np.array(
        [
            observation[f"joint_{j}.position"]
            for j in range(1, 6)
        ],
        dtype=np.float32,
    )

    return state, action, image


# ============================================================
# POSITION INITIALE
# ============================================================

def move_to_initial_position():

    initial_action = {
        f"joint_{j}.position": float(INITIAL_POSITION[j - 1])
        for j in range(1, 6)
    }

    print("\nConsigne initiale :", INITIAL_POSITION)

    follower.send_action(initial_action)

    time.sleep(2)

    observation = follower.get_observation()

    current_position = np.array(
        [
            observation[f"joint_{j}.position"]
            for j in range(1, 6)
        ],
        dtype=np.float32,
    )

    print("Position mesurée :", current_position)
    print(
        "Écart à la cible :",
        current_position - np.array(
            INITIAL_POSITION, dtype=np.float32
        ),
    )


# ============================================================
# PRÉCHAUFFAGE DU MODÈLE
# ============================================================

def warmup_policy():
    """
    Le premier appel sur MPS prend ~400 ms (initialisation du GPU).
    Avec PeriodWaiterExact, ce retard serait rattrapé en enchaînant
    les cycles suivants sans pause : début de mouvement brusque.
    On fait donc un appel à vide avant l'essai, puis on vide le cache.
    """

    fake_observation = {
        "cam_1": np.zeros((480, 640, 3), dtype=np.uint8),
        **{
            f"joint_{j}.position": float(INITIAL_POSITION[j - 1])
            for j in range(1, 6)
        },
    }

    start = time.perf_counter()
    predict_action(fake_observation)
    policy.reset()

    print(
        f"Préchauffage du modèle : "
        f"{(time.perf_counter() - start) * 1000:.0f} ms"
    )


# ============================================================
# MESURE DES DURÉES DE CYCLE
# ============================================================

def print_timing_summary(timings):
    """
    Affiche la durée des étapes de chaque cycle (en ms).
    Un cycle doit tenir dans 1000 / FPS ms.
    """

    budget_ms = 1000 / FPS
    timings = np.asarray(timings) * 1000
    observation_ms, inference_ms, send_ms = timings.T
    cycle_ms = timings.sum(axis=1)
    late = int((cycle_ms > budget_ms).sum())

    print(f"\nDurées par cycle (budget : {budget_ms:.0f} ms)")

    for name, values in [
        ("Observation", observation_ms),
        ("Inférence", inference_ms),
        ("Envoi", send_ms),
        ("Total", cycle_ms),
    ]:
        print(
            f"  {name:<12}: moyenne {values.mean():5.1f} ms | "
            f"max {values.max():5.1f} ms"
        )

    print(f"  Cycles en retard : {late} / {len(cycle_ms)}")

    if late:
        slowest = np.argsort(cycle_ms)[-3:][::-1]
        print(
            "  Cycles les plus lents : "
            + ", ".join(
                f"n°{i} ({cycle_ms[i]:.0f} ms)" for i in slowest
            )
        )


# ============================================================
# ENREGISTREMENT D'UN ESSAI
# ============================================================

def save_log(log, timings):
    """
    Sauvegarde l'essai dans LOG_DIR/essai_<date>.npz (+ .json lisible).
    image : exactement ce que le modèle a vu (après rotation et redimensionnement).
    """

    LOG_DIR.mkdir(exist_ok=True)
    name = "essai_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    note = input(
        "Note sur cet essai (ce que tu as vu, position du dé...) : "
    )

    np.savez_compressed(
        LOG_DIR / f"{name}.npz",
        time=np.asarray(log["time"], dtype=np.float32),
        state=np.asarray(log["state"], dtype=np.float32),
        action=np.asarray(log["action"], dtype=np.float32),
        image=np.asarray(log["image"], dtype=np.uint8),
        new_chunk=np.asarray(log["new_chunk"], dtype=bool),
        timings=np.asarray(timings, dtype=np.float32),
    )

    meta = {
        "note": note,
        "model": str(MODEL_ROOT),
        "dataset": str(DATASET_ROOT),
        "fps": FPS,
        "initial_position": INITIAL_POSITION,
        "execute_actions": EXECUTE_ACTIONS,
        "chunk_size": policy.config.chunk_size,
        "n_action_steps": policy.config.n_action_steps,
    }
    (LOG_DIR / f"{name}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False)
    )

    print(f"Essai enregistré : {LOG_DIR / name}.npz")


# ============================================================
# BOUCLE D'INFÉRENCE
# ============================================================

warmup_policy()

try:

    print("\n" + "=" * 55)
    print("EXECUTE_ACTIONS :", EXECUTE_ACTIONS)
    print("Fréquence :", FPS, "Hz")
    print("Durée :", EPISODE_TIME, "s")
    print("Itérations :", NUM_STEPS)
    print("Chunk :", policy.config.chunk_size)
    print("Actions par chunk :", policy.config.n_action_steps)
    print("=" * 55)

    while True:

        command = input(
            "\nEntrée : lancer un essai ; q : quitter : "
        )

        if command.strip().lower() == "q":
            break

        if EXECUTE_ACTIONS:

            confirmation = input(
                "\nVérifie la zone et l'arrêt d'urgence. "
                "Tape O pour confirmer : "
            )

            if confirmation.strip().upper() != "O":
                print("Essai annulé.")
                continue

            move_to_initial_position()

        policy.reset()

        interrupted = False
        timings = []
        log = {"time": [], "state": [], "action": [], "image": [], "new_chunk": []}

        print("\nDébut de l'essai...")
        start_time = time.perf_counter()
        period_waiter.start()

        try:

            for i in range(NUM_STEPS):

                t0 = time.perf_counter()

                observation = follower.get_observation()

                t1 = time.perf_counter()

                new_chunk = len(policy._action_queue) == 0

                state, action, image = predict_action(observation)

                t2 = time.perf_counter()

                if i % FPS == 0:
                    print(
                        f"\nTemps : {i / FPS:.1f} / "
                        f"{EPISODE_TIME} s"
                    )
                    print("État :", state)
                    print("Action :", list(action.values()))

                if EXECUTE_ACTIONS:
                    follower.send_action(action)

                t3 = time.perf_counter()
                timings.append((t1 - t0, t2 - t1, t3 - t2))

                log["time"].append(t0 - start_time)
                log["state"].append(state)
                log["action"].append(list(action.values()))
                log["image"].append(image)
                log["new_chunk"].append(new_chunk)

                period_waiter.wait()

        except KeyboardInterrupt:
            print("\nInterruption demandée.")
            interrupted = True

        duration = time.perf_counter() - start_time

        print(
            f"\nEssai terminé en {duration:.2f} s "
            f"(cible : {EPISODE_TIME} s)."
        )

        if timings:
            print_timing_summary(timings)

        if SAVE_LOGS and log["time"]:
            save_log(log, timings)

        if interrupted:
            break

finally:
    print("\nFin du programme.")
    print(
        "Vérifie l'état des moteurs et déconnecte le robot "
        "selon les procédures habituelles du MIR."
    )
