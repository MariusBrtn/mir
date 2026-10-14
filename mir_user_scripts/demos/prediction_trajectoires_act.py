
import numpy as np
import matplotlib.pyplot as plt
import torch

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors


# --------------------------------------------------
# Configuration
# --------------------------------------------------

dataset_id = "MariusBrtn/MIR_picking_dice"

# À adapter au chemin de ton checkpoint à 5000 étapes
checkpoint = (
    "/Users/marius/Documents/Atelier Vectoriel/MIR/MIR-software/outputs/train/act_mir_5000/checkpoints/005000/pretrained_model"
    
)

N = 120
EPISODE = 0

joint_names = [
    "Joint 1", "Joint 2", "Joint 3",
    "Joint 4", "Joint 5"
]


# --------------------------------------------------
# Chargement du dataset et du modèle
# --------------------------------------------------

dataset = LeRobotDataset(
    dataset_id,
    video_backend="pyav",
)

policy = ACTPolicy.from_pretrained(checkpoint)
policy.eval()

preprocessor, postprocessor = make_pre_post_processors(
    policy.config,
    pretrained_path=checkpoint,
)

print("Modèle chargé sur :", next(policy.parameters()).device)


# --------------------------------------------------
# Sélection des frames de l'épisode
# --------------------------------------------------

indices = [
    i for i in range(len(dataset))
    if int(dataset[i]["episode_index"]) == EPISODE
]

indices = indices[:N]

if not indices:
    raise RuntimeError(f"Aucune frame pour l'épisode {EPISODE}")

print(f"Épisode {EPISODE} : {len(indices)} frames")


# --------------------------------------------------
# Prédictions
# --------------------------------------------------

states = []
targets = []
predictions = []
timestamps = []

policy.reset()

with torch.inference_mode():
    for i in indices:
        sample = dataset[i]

        batch = {
            "observation.state":
                sample["observation.state"].unsqueeze(0),
            "observation.images.cam_1":
                sample["observation.images.cam_1"].unsqueeze(0),
        }

        batch = preprocessor(batch)
        action = policy.select_action(batch)
        action = postprocessor(action)

        states.append(
            sample["observation.state"].cpu().numpy()
        )
        targets.append(
            sample["action"].cpu().numpy()
        )
        predictions.append(
            action[0].detach().cpu().numpy()
        )
        timestamps.append(
            float(sample["timestamp"])
        )

states = np.asarray(states)
targets = np.asarray(targets)
predictions = np.asarray(predictions)
timestamps = np.asarray(timestamps)

# Temps relatif au début de la séquence
time_s = timestamps - timestamps[0]


# --------------------------------------------------
# Erreurs
# --------------------------------------------------

mae_act = np.mean(np.abs(predictions - targets), axis=0)
mae_baseline = np.mean(np.abs(states - targets), axis=0)

print("\nMAE ACT par articulation :")
for name, value in zip(joint_names, mae_act):
    print(f"{name}: {value:.3f}")

print("\nMAE baseline (état courant) :")
for name, value in zip(joint_names, mae_baseline):
    print(f"{name}: {value:.3f}")


# --------------------------------------------------
# Tracé des trajectoires
# --------------------------------------------------

fig, axes = plt.subplots(
    5, 1,
    figsize=(13, 14),
    sharex=True
)

for j, ax in enumerate(axes):
    ax.plot(
        time_s, targets[:, j],
        label="Action cible",
        linewidth=2
    )
    ax.plot(
        time_s, predictions[:, j],
        label="Action prédite ACT",
        linestyle="--",
        linewidth=1.5
    )
    ax.plot(
        time_s, states[:, j],
        label="État courant",
        linestyle=":",
        linewidth=1
    )

    ax.set_ylabel(f"{joint_names[j]}\n(unités dataset)")
    ax.grid(True, alpha=0.3)

    if j == 0:
        ax.legend(loc="best")

axes[-1].set_xlabel("Temps (s)")
fig.suptitle(
    f"ACT — trajectoires prédites et cibles, épisode {EPISODE}",
    fontsize=14
)

fig.tight_layout()
fig.savefig("act_trajectories.png", dpi=160)
plt.show()

print("\nFigure enregistrée : act_trajectories.png")

