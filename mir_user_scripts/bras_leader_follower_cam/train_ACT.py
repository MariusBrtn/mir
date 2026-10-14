
"""
Entraînement ACT pour le robot MIR
Environnement : Conda robot312
LeRobot : 0.5.1

Lancer depuis le dossier bras_leader_follower_cam.
"""

from pathlib import Path
import subprocess
import sys


# ==================================================
# PARAMÈTRES À RÉGLER
# ==================================================

# Identifiant du dataset
DATASET_REPO_ID = "local/mir_4ddl_cam_dice"

# Chemin local ABSOLU du dataset
DATASET_ROOT = Path(
    "/Users/marius/Documents/Atelier Vectoriel/MIR/"
    "MIR-software/mir/mir_user_scripts/"
    "bras_leader_follower_cam/dataset_dice"
)

# Entraînement
STEPS = 10000
BATCH_SIZE = 8
SAVE_FREQ = 5000
LOG_FREQ = 100
NUM_WORKERS = 0

# ACT
CHUNK_SIZE = 20
N_ACTION_STEPS = 10

# Matériel
DEVICE = "mps"

# Répertoire de sortie
OUTPUT_DIR = Path("outputs/train/act_batch4_chunk20")

# Nom de l'expérience
JOB_NAME = "act_mir_experiment"

# Reprise d'un entraînement interrompu
RESUME = False

# Options facultatives
PUSH_TO_HUB = False
WANDB_ENABLE = False


# ==================================================
# VALIDATION
# ==================================================

if not DATASET_ROOT.is_dir():
    raise FileNotFoundError(
        f"Dataset local introuvable : {DATASET_ROOT}"
    )

if not (DATASET_ROOT / "meta" / "info.json").is_file():
    raise FileNotFoundError(
        f"Fichier meta/info.json absent dans {DATASET_ROOT}"
    )

if CHUNK_SIZE < 1:
    raise ValueError("CHUNK_SIZE doit être >= 1.")

if not 1 <= N_ACTION_STEPS <= CHUNK_SIZE:
    raise ValueError(
        "N_ACTION_STEPS doit être compris entre 1 et CHUNK_SIZE."
    )


# ==================================================
# CONSTRUCTION DE LA COMMANDE
# ==================================================

cmd = [
    sys.executable,
    "-m",
    "lerobot.scripts.lerobot_train",

    f"--dataset.repo_id={DATASET_REPO_ID}",
    f"--dataset.root={DATASET_ROOT}",

    "--policy.type=act",
    f"--policy.device={DEVICE}",
    f"--policy.chunk_size={CHUNK_SIZE}",
    f"--policy.n_action_steps={N_ACTION_STEPS}",

    f"--output_dir={OUTPUT_DIR}",
    f"--job_name={JOB_NAME}",

    f"--batch_size={BATCH_SIZE}",
    f"--steps={STEPS}",
    f"--save_freq={SAVE_FREQ}",
    f"--log_freq={LOG_FREQ}",
    f"--num_workers={NUM_WORKERS}",

    "--dataset.video_backend=pyav",

    f"--policy.push_to_hub={str(PUSH_TO_HUB).lower()}",
    f"--wandb.enable={str(WANDB_ENABLE).lower()}",
]


# ==================================================
# LANCEMENT
# ==================================================

print("\nDataset local :", DATASET_ROOT)
print("Interpréteur Python :", sys.executable)
print("\nCommande d'entraînement :")
print(subprocess.list2cmdline(cmd))
print("\nDémarrage de l'entraînement...\n")

subprocess.run(cmd, check=True)
