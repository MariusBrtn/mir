
"""
Comparaison hors ligne ACT / démonstration réelle
LeRobot 0.5.1

- Épisode 1 du dataset (index 0)
- Aucune connexion au robot
- Comparaison des actions réelles et prédites sur toutes les frames
- ACT : chunk_size=20, n_action_steps=10
"""

from pathlib import Path
import csv

import numpy as np
import torch
import matplotlib.pyplot as plt

from lerobot.datasets import LeRobotDataset
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

DEVICE = torch.device("mps")

# Episode 1 = index 0
EPISODE_INDEX = 0

EXPECTED_CHUNK_SIZE = 20
EXPECTED_N_ACTION_STEPS = 10
N_ACTION_STEPS = 10

INITIAL_STATE = np.array(
    [
        -55.912086486816406,
        28.30769157409668,
        -80.70330047607422,
        78.63735961914062,
        12.04395580291748,
    ],
    dtype=np.float32,
)

JOINT_NAMES = [f"joint_{i}" for i in range(1, 6)]

OUTPUT_CSV = BASE_DIR / "comparison_act_episode1.csv"
OUTPUT_PNG = BASE_DIR / "comparison_act_episode1.png"


# ============================================================
# VALIDATION
# ============================================================

if not DATASET_ROOT.is_dir():
    raise FileNotFoundError(
        f"Dataset introuvable : {DATASET_ROOT}"
    )

if not MODEL_ROOT.is_dir():
    raise FileNotFoundError(
        f"Checkpoint introuvable : {MODEL_ROOT}"
    )


# ============================================================
# CHARGEMENT DU DATASET
# ============================================================

print("\nChargement du dataset...")

metadata = LeRobotDatasetMetadata(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT,
)

dataset = LeRobotDataset(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT,
    episodes=[EPISODE_INDEX],
)

episode_length = len(dataset)
fps = float(metadata.fps)

print("Épisode :", EPISODE_INDEX + 1)
print("Nombre de frames :", episode_length)
print("FPS :", fps)

if episode_length == 0:
    raise RuntimeError("L'épisode sélectionné est vide.")


# ============================================================
# CHARGEMENT DU MODÈLE ACT
# ============================================================

print("\nChargement du modèle ACT...")



policy = ACTPolicy.from_pretrained(str(MODEL_ROOT))

# Vérifier que le chunk prédit contient bien 20 actions
print("chunk_size avant :", policy.config.chunk_size)
print("n_action_steps avant :", policy.config.n_action_steps)

assert policy.config.chunk_size >= N_ACTION_STEPS

# Modifier le nombre d'actions exécutées avant recalcul
policy.config.n_action_steps = N_ACTION_STEPS

policy.to(DEVICE)
policy.eval()

print("n_action_steps après :", policy.config.n_action_steps)
print("Device :", DEVICE)
print("Chunk size :", policy.config.chunk_size)


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
    dataset_stats=metadata.stats,
)

print("Modèle et processeurs chargés.")


# ============================================================
# PRÉPARATION DES DONNÉES
# ============================================================

def as_tensor(value):
    if isinstance(value, torch.Tensor):
        return value
    return torch.as_tensor(value)


def build_observation(frame):
    """
    Construit l'observation dans le format du script d'inférence.
    L'image est convertie en CHW float32, sans division par 255.
    """

    image = as_tensor(
        frame["observation.images.cam_1"]
    )

    if image.ndim != 3:
        raise RuntimeError(
            f"Image de forme inattendue : {tuple(image.shape)}"
        )

    if image.shape[0] == 3:
        pass
    elif image.shape[-1] == 3:
        image = image.permute(2, 0, 1)
    else:
        raise RuntimeError(
            f"Format d'image non reconnu : {tuple(image.shape)}"
        )

    image = image.to(torch.float32)

    state = as_tensor(
        frame["observation.state"]
    ).to(torch.float32).reshape(-1)

    if state.numel() != 5:
        raise RuntimeError(
            f"État de dimension {state.numel()}, 5 attendues."
        )

    return {
        "observation.images.cam_1": image,
        "observation.state": state,
    }


# ============================================================
# VÉRIFICATION DE LA PREMIÈRE FRAME
# ============================================================

first_frame = dataset[0]

first_state = (
    as_tensor(first_frame["observation.state"])
    .cpu()
    .numpy()
    .reshape(-1)
)

print("\nÉtat initial du dataset :")
print(first_state)

print("État initial attendu :")
print(INITIAL_STATE)

print("Écart :")
print(first_state - INITIAL_STATE)

if not np.allclose(
    first_state,
    INITIAL_STATE,
    atol=0.05,
    rtol=0,
):
    raise RuntimeError(
        "La première position ne correspond pas à la position "
        "initiale attendue. Vérifie l'épisode sélectionné."
    )


# ============================================================
# INFÉRENCE SUR TOUT L'ÉPISODE
# ============================================================

real_actions = []
predicted_actions = []
states = []
frame_numbers = []

policy.reset()

print("\nDébut de la comparaison hors ligne...")

with torch.inference_mode():

    # IMPORTANT : toute l'inférence est DANS cette boucle.
    for local_index in range(episode_length):

        frame = dataset[local_index]

        observation = build_observation(frame)

        # Action enregistrée dans la démonstration.
        real_action = (
            as_tensor(frame["action"])
            .cpu()
            .numpy()
            .reshape(-1)
        )

        if real_action.size != 5:
            raise RuntimeError(
                f"Action réelle de dimension {real_action.size}."
            )

        # Prétraitement LeRobot.
        observation_processed = preprocessor(observation)

        # Prédiction ACT avec son cache de chunks.
        action_processed = policy.select_action(
            observation_processed
        )

        # Retour dans l'espace réel des actions.
        action_unprocessed = postprocessor(action_processed)

        if isinstance(action_unprocessed, dict):
            action_tensor = action_unprocessed["action"]
        else:
            action_tensor = action_unprocessed

        predicted_action = (
            action_tensor.detach()
            .cpu()
            .numpy()
            .reshape(-1)
        )

        if predicted_action.size != 5:
            raise RuntimeError(
                f"Action prédite de dimension "
                f"{predicted_action.size} à la frame {local_index}."
            )

        if not np.isfinite(predicted_action).all():
            raise RuntimeError(
                f"Action non finie à la frame {local_index}."
            )

        # Enregistrement des résultats de CETTE frame.
        real_actions.append(real_action)
        predicted_actions.append(predicted_action)

        states.append(
            as_tensor(frame["observation.state"])
            .cpu()
            .numpy()
            .reshape(-1)
        )

        frame_numbers.append(local_index)

        if local_index % max(1, int(fps)) == 0:
            print(
                f"Frame {local_index:4d}/{episode_length} | "
                f"Réel : {np.round(real_action, 2)} | "
                f"ACT : {np.round(predicted_action, 2)}"
            )


# ============================================================
# CONVERSION ET CONTRÔLE DES RÉSULTATS
# ============================================================

real_actions = np.asarray(real_actions, dtype=np.float32)
predicted_actions = np.asarray(
    predicted_actions, dtype=np.float32
)
states = np.asarray(states, dtype=np.float32)
frame_numbers = np.asarray(frame_numbers, dtype=np.int64)

print("\nDiagnostic final :")
print("Frames du dataset :", episode_length)
print("Frames analysées :", len(frame_numbers))
print("Actions réelles :", real_actions.shape)
print("Actions prédites :", predicted_actions.shape)

if len(frame_numbers) != episode_length:
    raise RuntimeError(
        "Toutes les frames de l'épisode n'ont pas été analysées."
    )

if real_actions.shape != (episode_length, 5):
    raise RuntimeError(
        f"Forme inattendue des actions réelles : "
        f"{real_actions.shape}"
    )

if predicted_actions.shape != (episode_length, 5):
    raise RuntimeError(
        f"Forme inattendue des prédictions : "
        f"{predicted_actions.shape}"
    )


# ============================================================
# CALCUL DES ERREURS
# ============================================================

errors = predicted_actions - real_actions

mae = np.mean(np.abs(errors), axis=0)
rmse = np.sqrt(np.mean(errors ** 2, axis=0))

print("\n" + "=" * 65)
print("RÉSULTATS SUR L'ENSEMBLE DE L'ÉPISODE")
print("=" * 65)

for j, name in enumerate(JOINT_NAMES):
    print(
        f"{name}: MAE = {mae[j]:.3f} | "
        f"RMSE = {rmse[j]:.3f}"
    )

print(f"\nMAE globale : {np.mean(np.abs(errors)):.3f}")
print(f"RMSE globale : {np.sqrt(np.mean(errors ** 2)):.3f}")


# ============================================================
# EXPORT CSV
# ============================================================

header = (
    ["frame", "time_s"]
    + [f"{name}_real" for name in JOINT_NAMES]
    + [f"{name}_predicted" for name in JOINT_NAMES]
    + [f"{name}_error" for name in JOINT_NAMES]
)

with open(
    OUTPUT_CSV,
    "w",
    newline="",
    encoding="utf-8",
) as file:

    writer = csv.writer(file)
    writer.writerow(header)

    for i in range(episode_length):
        writer.writerow(
            [
                int(frame_numbers[i]),
                float(frame_numbers[i] / fps),
                *real_actions[i].tolist(),
                *predicted_actions[i].tolist(),
                *errors[i].tolist(),
            ]
        )

print("\nCSV enregistré :", OUTPUT_CSV)


# ============================================================
# GRAPHIQUES
# ============================================================

times = frame_numbers / fps

fig, axes = plt.subplots(
    5,
    1,
    figsize=(14, 16),
    sharex=True,
)

for j, ax in enumerate(axes):

    ax.plot(
        times,
        real_actions[:, j],
        label="Action réelle",
    )

    ax.plot(
        times,
        predicted_actions[:, j],
        label="Action ACT",
    )

    ax.set_ylabel(f"{JOINT_NAMES[j]}\n(position)")
    ax.grid(True)
    ax.legend()

axes[-1].set_xlabel("Temps (s)")

fig.suptitle(
    "ACT : prédictions vs démonstration réelle\n"
    f"Épisode {EPISODE_INDEX + 1} | "
    f"chunk={policy.config.chunk_size} | "
    f"n_action_steps={policy.config.n_action_steps}"
)

fig.tight_layout()
fig.savefig(OUTPUT_PNG, dpi=150)

print("Graphique enregistré :", OUTPUT_PNG)

plt.show()
