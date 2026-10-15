"""
Analyse d'un essai ACT enregistré par controle_robot_ACT.py
Environnement : Conda robot312
LeRobot : 0.5.1

  python analyse_essai_ACT.py                    # dernier essai de logs_essais_ACT/
  python analyse_essai_ACT.py logs_essais_ACT/essai_20261015_101500.npz

Produit à côté de l'essai :
  <essai>_trajectoires.png : état mesuré, actions envoyées, rejeu hors ligne et démo la plus proche
  <essai>_images.png       : images vues par le modèle vs images de la démo la plus proche

Questions auxquelles l'analyse répond :
  1. Rejeu : en redonnant au modèle les mêmes images et états, retrouve-t-on les mêmes actions ?
     (sinon : le pipeline en ligne n'est pas celui qu'on croit)
  2. Images : ressemblent-elles à celles du dataset (luminosité, couleurs, cadrage) ?
  3. Démo la plus proche : le robot suit-il un geste appris, ou dérive-t-il hors des démos ?
  4. Suivi : le follower atteint-il les positions demandées (retard, butées, couple) ?
"""

from pathlib import Path
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

from lerobot.datasets import LeRobotDataset, LeRobotDatasetMetadata
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs_essais_ACT"
DATASET_REPO_ID = "local/mir_4ddl_cam_dice"
DEVICE = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
JOINTS = [f"joint_{j}" for j in range(1, 6)]


# ============================================================
# CHARGEMENT
# ============================================================

if len(sys.argv) > 1:
    log_path = Path(sys.argv[1])
else:
    logs = sorted(LOG_DIR.glob("essai_*.npz"))
    if not logs:
        raise FileNotFoundError(f"Aucun essai dans {LOG_DIR}")
    log_path = logs[-1]

log = np.load(log_path)
meta = json.loads(log_path.with_suffix(".json").read_text())
times, states, actions = log["time"], log["state"], log["action"]
images, new_chunk = log["image"], log["new_chunk"]
fps = meta["fps"]

print(f"Essai : {log_path.name}  ({len(times)} pas, {times[-1]:.1f} s)")
print(f"Note  : {meta.get('note', '')}")

model_root = Path(meta["model"])
dataset_root = Path(meta["dataset"])
metadata = LeRobotDatasetMetadata(repo_id=DATASET_REPO_ID, root=dataset_root)
dataset = LeRobotDataset(repo_id=DATASET_REPO_ID, root=dataset_root, video_backend="pyav")

policy = ACTPolicy.from_pretrained(str(model_root))
policy.config.device = str(DEVICE)
policy = policy.to(DEVICE)
policy.eval()
preprocessor, postprocessor = make_pre_post_processors(
    policy_cfg=policy.config,
    pretrained_path=str(model_root),
    dataset_stats=metadata.stats,
)


def to_model_input(image_uint8, state):
    """Même conversion que build_observation de controle_robot_ACT.py."""
    image = torch.from_numpy(np.ascontiguousarray(image_uint8)).permute(2, 0, 1).to(torch.float32) / 255.0
    return {"observation.images.cam_1": image, "observation.state": torch.as_tensor(state, dtype=torch.float32)}


def run_policy(frames, frame_states):
    policy.reset()
    out = []
    with torch.inference_mode():
        for image, state in zip(frames, frame_states):
            action = postprocessor(policy.select_action(preprocessor(to_model_input(image, state))))
            if isinstance(action, dict):
                action = action["action"]
            out.append(action.detach().cpu().reshape(-1).numpy())
    return np.asarray(out)


# ============================================================
# 1. REJEU HORS LIGNE DES MÊMES ENTRÉES
# ============================================================

replayed = run_policy(images, states)
replay_err = np.abs(replayed - actions)
print("\n1. Rejeu (mêmes images et états) — écart max avec les actions envoyées (°) :")
print("   " + "  ".join(f"{j}: {e:.2f}" for j, e in zip(JOINTS, replay_err.max(axis=0))))
if replay_err.max() > 1.0:
    print("   -> ÉCART : le modèle en ligne ne reçoit pas ce que l'on croit (ou n'est pas le même modèle).")
else:
    print("   -> OK : le pipeline en ligne est cohérent avec le rejeu.")


# ============================================================
# 2. IMAGES : COMPARAISON AVEC LE DATASET
# ============================================================

episodes = metadata.episodes
starts = [int(episodes[i]["dataset_from_index"]) for i in range(metadata.total_episodes)]
ends = [int(episodes[i]["dataset_to_index"]) for i in range(metadata.total_episodes)]


def dataset_image(index):
    image = dataset[index]["observation.images.cam_1"]  # CHW float [0, 1]
    return (image.permute(1, 2, 0).numpy() * 255).round().astype(np.uint8)


first_images = np.stack([dataset_image(s) for s in starts]).astype(np.float32)
run_mean = images.reshape(len(images), -1, 3).mean(axis=(0, 1))
data_mean = first_images.reshape(len(first_images), -1, 3).mean(axis=(0, 1))
print("\n2. Couleur moyenne des images (R, G, B ou B, G, R selon la caméra, 0-255) :")
print(f"   essai   : {run_mean.round(1)}")
print(f"   dataset : {data_mean.round(1)}  (premières images des {len(starts)} épisodes)")
if np.abs(run_mean - data_mean).max() > 25:
    print("   -> ÉCART NET : éclairage, exposition ou ordre des canaux différents de l'enregistrement.")


# ============================================================
# 3. DÉMO LA PLUS PROCHE
# ============================================================

image_dist = ((first_images - images[0].astype(np.float32)) ** 2).mean(axis=(1, 2, 3))
state_std = np.asarray(metadata.stats["observation.state"]["std"])
first_states = np.stack([dataset[s]["observation.state"].numpy() for s in starts])
state_dist = (((first_states - states[0]) / state_std) ** 2).mean(axis=1)
nearest = int(np.argmin(image_dist / image_dist.mean() + state_dist / max(state_dist.mean(), 1e-6)))
demo_actions = np.stack([dataset[i]["action"].numpy() for i in range(starts[nearest], ends[nearest])])
demo_states = np.stack([dataset[i]["observation.state"].numpy() for i in range(starts[nearest], ends[nearest])])
print(f"\n3. Démo la plus proche (image de départ + état) : épisode {nearest}")
print(f"   état de départ essai : {states[0].round(1)}")
print(f"   état de départ démo  : {demo_states[0].round(1)}")

# rejeu du modèle sur la démo la plus proche : ce qu'il « devrait » faire dans une situation connue
demo_images = np.stack([dataset_image(i) for i in range(starts[nearest], ends[nearest])])
demo_replayed = run_policy(demo_images, demo_states)


# ============================================================
# 4. SUIVI DU FOLLOWER
# ============================================================

lag = 3  # le servo a besoin de quelques pas pour rejoindre la consigne
tracking = np.abs(actions[:-lag] - states[lag:])
print(f"\n4. Suivi : écart moyen / max entre consigne et position atteinte {lag} pas plus tard (°) :")
print("   " + "  ".join(f"{j}: {m:.1f}/{x:.1f}" for j, m, x in zip(JOINTS, tracking.mean(0), tracking.max(0))))

action_min = np.asarray(metadata.stats["action"]["min"])
action_max = np.asarray(metadata.stats["action"]["max"])
outside = (actions < action_min - 2) | (actions > action_max + 2)
if outside.any():
    print("   Actions hors de la plage des démos : "
          + ", ".join(f"{JOINTS[j]} ({outside[:, j].sum()} pas)" for j in range(5) if outside[:, j].any()))


# ============================================================
# FIGURES
# ============================================================

fig, axes = plt.subplots(5, 1, figsize=(12, 14), sharex=True)
demo_t = np.arange(len(demo_actions)) / fps
for j, ax in enumerate(axes):
    ax.plot(demo_t, demo_actions[:, j], color="0.6", lw=2, label=f"démo ép. {nearest} (action)")
    ax.plot(demo_t, demo_replayed[:, j], color="0.6", ls=":", label="modèle sur cette démo")
    ax.plot(times, actions[:, j], color="tab:red", label="essai : action envoyée")
    ax.plot(times, states[:, j], color="tab:blue", label="essai : état mesuré")
    ax.plot(times, replayed[:, j], color="k", ls="--", lw=0.8, label="essai : rejeu hors ligne")
    for t in times[new_chunk]:
        ax.axvline(t, color="tab:red", alpha=0.15, lw=0.8)
    ax.set_ylabel(JOINTS[j])
    ax.grid(alpha=0.3)
axes[0].legend(fontsize=8, ncol=3, loc="upper left")
axes[-1].set_xlabel("temps (s) — traits verticaux : nouveau chunk")
fig.suptitle(f"{log_path.stem} — {meta.get('note', '')}")
fig.tight_layout()
out_traj = log_path.with_name(log_path.stem + "_trajectoires.png")
fig.savefig(out_traj, dpi=90)

moments = np.linspace(0, len(images) - 1, 6).astype(int)
fig, axes = plt.subplots(2, len(moments), figsize=(3 * len(moments), 5.5))
for k, i in enumerate(moments):
    axes[0, k].imshow(images[i])
    axes[0, k].set_title(f"essai t={times[i]:.1f}s", fontsize=9)
    d = min(i, len(demo_images) - 1)
    axes[1, k].imshow(demo_images[d])
    axes[1, k].set_title(f"démo {nearest} t={d / fps:.1f}s", fontsize=9)
for ax in axes.flat:
    ax.axis("off")
fig.tight_layout()
out_img = log_path.with_name(log_path.stem + "_images.png")
fig.savefig(out_img, dpi=80)

print(f"\nFigures : {out_traj.name}, {out_img.name}")
