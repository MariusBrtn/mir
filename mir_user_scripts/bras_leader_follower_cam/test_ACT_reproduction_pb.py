"""
Comparaison hors ligne ACT : reproduction du pipeline d'inférence RÉELLE
LeRobot 0.5.1

Les images du dataset (float32 [0,1], CHW) sont reconverties en uint8 HWC [0,255]
pour simuler la sortie caméra, puis passées dans le MÊME build_observation que le
script d'inférence réelle.

Modes comparés sur tout l'épisode :
  - baseline        : image du dataset telle quelle (float 0-1)         [ancien script offline]
  - real_no_div     : uint8 -> CHW float32, SANS /255                   [script réel actuel]
  - real_div255     : uint8 -> CHW float32, AVEC /255                   [correction proposée]
  - real_bgr_div255 : idem + canaux inversés (test BGR/RGB)
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
    BASE_DIR / "outputs" / "train" / "act_batch4_chunk20"
    / "checkpoints" / "last" / "pretrained_model"
)

DEVICE = torch.device("mps")
EPISODE_INDEX = 0
N_ACTION_STEPS = 10  # identique à la config du checkpoint
JOINT_NAMES = [f"joint_{i}" for i in range(1, 6)]

OUTPUT_CSV = BASE_DIR / "comparison_act_real_pipeline.csv"
OUTPUT_PNG = BASE_DIR / "comparison_act_real_pipeline.png"

# Actions obtenues en réel à t=0 (pour référence)
REAL_RUN_FIRST_ACTION = np.array(
    [-52.74412536621094, 53.473751068115234, -71.02053833007812,
     80.32911682128906, 2.884345769882202]
)

# ============================================================
# CHARGEMENT
# ============================================================

metadata = LeRobotDatasetMetadata(repo_id=DATASET_REPO_ID, root=DATASET_ROOT)
dataset = LeRobotDataset(
    repo_id=DATASET_REPO_ID, root=DATASET_ROOT, episodes=[EPISODE_INDEX]
)
episode_length = len(dataset)
fps = float(metadata.fps)
print("Frames :", episode_length, "| FPS :", fps)

policy = ACTPolicy.from_pretrained(str(MODEL_ROOT))
policy.config.n_action_steps = N_ACTION_STEPS
policy.config.device = str(DEVICE)
policy = policy.to(DEVICE)
policy.eval()
print("chunk_size :", policy.config.chunk_size,
      "| n_action_steps :", policy.config.n_action_steps)

preprocessor, postprocessor = make_pre_post_processors(
    policy_cfg=policy.config,
    pretrained_path=str(MODEL_ROOT),
    dataset_stats=metadata.stats,
)

# ============================================================
# SIMULATION DE LA CAMÉRA : dataset -> uint8 HWC [0,255]
# ============================================================

def as_tensor(v):
    return v if isinstance(v, torch.Tensor) else torch.as_tensor(v)


def dataset_image_to_camera_uint8(frame):
    """Ce que renverrait la caméra : numpy uint8, HWC, 0-255."""
    img = as_tensor(frame["observation.images.cam_1"]).float()  # CHW [0,1]
    if img.shape[0] != 3:  # sécurité si HWC
        img = img.permute(2, 0, 1)
    img_u8 = (img.clamp(0, 1) * 255.0).round().to(torch.uint8)
    return img_u8.permute(1, 2, 0).contiguous().cpu().numpy()  # HWC


# ============================================================
# build_observation : COPIE EXACTE du script d'inférence réelle
# ============================================================

def build_observation_real(image_hwc, state_np, divide_255=False):
    image_tensor = torch.from_numpy(
        np.ascontiguousarray(image_hwc)
    ).permute(2, 0, 1).to(torch.float32)

    if divide_255:
        image_tensor = image_tensor / 255.0

    state = torch.tensor(state_np, dtype=torch.float32)

    return {
        "observation.images.cam_1": image_tensor,
        "observation.state": state,
    }


def build_observation_baseline(frame):
    """Ancien script offline : image du dataset telle quelle."""
    image = as_tensor(frame["observation.images.cam_1"])
    if image.shape[0] != 3:
        image = image.permute(2, 0, 1)
    return {
        "observation.images.cam_1": image.to(torch.float32),
        "observation.state": as_tensor(
            frame["observation.state"]
        ).to(torch.float32).reshape(-1),
    }


MODES = {
    "baseline": lambda frame, img_u8, st: build_observation_baseline(frame),
    "real_no_div": lambda frame, img_u8, st: build_observation_real(
        img_u8, st, divide_255=False),
    "real_div255": lambda frame, img_u8, st: build_observation_real(
        img_u8, st, divide_255=True),
    "real_bgr_div255": lambda frame, img_u8, st: build_observation_real(
        img_u8[..., ::-1], st, divide_255=True),
}

# ============================================================
# PRÉDICTION (identique à predict_action du script réel)
# ============================================================

def predict(observation_frame):
    observation_processed = preprocessor(observation_frame)
    with torch.inference_mode():
        action_processed = policy.select_action(observation_processed)
    action_unprocessed = postprocessor(action_processed)
    action_tensor = (
        action_unprocessed["action"]
        if isinstance(action_unprocessed, dict) else action_unprocessed
    )
    return (
        action_tensor.detach().cpu().reshape(-1).numpy(),
        observation_processed["observation.images.cam_1"],
    )


# ============================================================
# STATS D'IMAGE (avant / après preprocessor, frame 0)
# ============================================================

frame0 = dataset[0]
img0_u8 = dataset_image_to_camera_uint8(frame0)
state0 = as_tensor(frame0["observation.state"]).cpu().numpy().reshape(-1)

print("\n--- Stats image frame 0 ---")
print("Caméra simulée :", img0_u8.dtype, img0_u8.shape,
      "min", img0_u8.min(), "max", img0_u8.max())

for name, fn in MODES.items():
    obs = fn(frame0, img0_u8, state0)
    im = obs["observation.images.cam_1"]
    print(f"[{name:16s}] AVANT preproc : shape={tuple(im.shape)} "
          f"min={im.min().item():.3f} max={im.max().item():.3f} "
          f"mean={im.mean().item():.3f}")
    policy.reset()
    _, im_proc = predict(obs)
    print(f"[{name:16s}] APRÈS preproc : min={im_proc.min().item():.3f} "
          f"max={im_proc.max().item():.3f} mean={im_proc.mean().item():.3f}")

# ============================================================
# BOUCLE SUR L'ÉPISODE, POUR CHAQUE MODE
# ============================================================

real_actions = np.stack([
    as_tensor(dataset[i]["action"]).cpu().numpy().reshape(-1)
    for i in range(episode_length)
]).astype(np.float32)

results = {}

for name, fn in MODES.items():
    print(f"\n=== Mode : {name} ===")
    policy.reset()
    preds = []

    for i in range(episode_length):
        frame = dataset[i]
        img_u8 = dataset_image_to_camera_uint8(frame)
        st = as_tensor(frame["observation.state"]).cpu().numpy().reshape(-1)

        obs = fn(frame, img_u8, st)
        action, _ = predict(obs)

        if not np.isfinite(action).all():
            raise RuntimeError(f"Action non finie, mode {name}, frame {i}")
        preds.append(action)

    preds = np.asarray(preds, dtype=np.float32)
    results[name] = preds

    err = preds - real_actions
    print("Première action prédite :", np.round(preds[0], 2))
    print("MAE par joint           :", np.round(np.mean(np.abs(err), 0), 3))
    print("MAE globale             :", round(float(np.mean(np.abs(err))), 3))
    print("Écart-type temporel des prédictions (≈0 => sortie figée) :",
          np.round(preds.std(axis=0), 3))

print("\nRéférence - première action observée en RÉEL :",
      np.round(REAL_RUN_FIRST_ACTION, 2))

# ============================================================
# EXPORT CSV
# ============================================================

header = ["frame", "time_s"] \
    + [f"{j}_real" for j in JOINT_NAMES]
for name in MODES:
    header += [f"{j}_{name}" for j in JOINT_NAMES]

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(header)
    for i in range(episode_length):
        row = [i, i / fps, *real_actions[i].tolist()]
        for name in MODES:
            row += results[name][i].tolist()
        w.writerow(row)

print("CSV enregistré :", OUTPUT_CSV)

# ============================================================
# GRAPHIQUE
# ============================================================

times = np.arange(episode_length) / fps
fig, axes = plt.subplots(5, 1, figsize=(14, 16), sharex=True)

for j, ax in enumerate(axes):
    ax.plot(times, real_actions[:, j], "k", lw=2, label="Démo réelle")
    for name, preds in results.items():
        ax.plot(times, preds[:, j], label=name, alpha=0.85)
    ax.set_ylabel(JOINT_NAMES[j])
    ax.grid(True)
    ax.legend(loc="best", fontsize=8)

axes[-1].set_xlabel("Temps (s)")
fig.suptitle(
    f"ACT : pipeline réel simulé vs démo | épisode {EPISODE_INDEX + 1}"
)
fig.tight_layout()
fig.savefig(OUTPUT_PNG, dpi=150)
print("Graphique enregistré :", OUTPUT_PNG)
plt.show()