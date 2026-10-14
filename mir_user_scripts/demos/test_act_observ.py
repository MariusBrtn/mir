import torch
import numpy as np

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors


# --------------------------------------------------
# Configuration
# --------------------------------------------------

dataset_id = "MariusBrtn/MIR_picking_dice"

checkpoint = (
    "/Users/marius/Documents/Atelier Vectoriel/MIR/MIR-software/outputs/train/act_mir_5000/checkpoints/005000/pretrained_model"
    
)


N = 200


# --------------------------------------------------
# Chargement
# --------------------------------------------------

dataset = LeRobotDataset(
    dataset_id,
    video_backend="pyav",
)

policy = ACTPolicy.from_pretrained(checkpoint)
policy.eval()

device = next(policy.parameters()).device

preprocessor, postprocessor = make_pre_post_processors(
    policy.config,
    pretrained_path=checkpoint,
)

print("Modèle :", device)
print("Frames du dataset :", len(dataset))


# --------------------------------------------------
# Sélection de 200 frames consécutives
# d'un même épisode
# --------------------------------------------------

# On prend l'épisode 0, en limitant le nombre de frames
episode_indices = [
    i for i in range(len(dataset))
    if int(dataset[i]["episode_index"]) == 0
]

indices = episode_indices[:N]

if not indices:
    raise RuntimeError("Aucune frame trouvée dans l'épisode 0.")

print("Nombre de frames évaluées :", len(indices))


# --------------------------------------------------
# Évaluation
# --------------------------------------------------

errors_act = []
errors_baseline = []

predictions = []
targets = []

current_episode = None

for i in indices:
    sample = dataset[i]
    episode = int(sample["episode_index"])

    # Réinitialiser la mémoire de chunks entre épisodes
    if episode != current_episode:
        policy.reset()
        current_episode = episode

    batch = {
        "observation.state": (
            sample["observation.state"].unsqueeze(0)
        ),
        "observation.images.cam_1": (
            sample["observation.images.cam_1"].unsqueeze(0)
        ),
    }

    target = sample["action"].float().cpu().numpy()

    with torch.inference_mode():
        processed_batch = preprocessor(batch)
        prediction = policy.select_action(processed_batch)
        prediction = postprocessor(prediction)

    prediction = prediction[0].detach().cpu().numpy()
    state = sample["observation.state"].float().cpu().numpy()

    predictions.append(prediction)
    targets.append(target)

    errors_act.append(np.abs(prediction - target))
    errors_baseline.append(np.abs(state - target))


# --------------------------------------------------
# Résultats
# --------------------------------------------------

errors_act = np.asarray(errors_act)
errors_baseline = np.asarray(errors_baseline)

predictions = np.asarray(predictions)
targets = np.asarray(targets)

names = ["Joint 1", "Joint 2", "Joint 3", "Joint 4", "Joint 5"]

print("\n===== ACT =====")
print("MAE globale :", errors_act.mean())
print("RMSE globale :", np.sqrt(((predictions - targets) ** 2).mean()))

print("\nMAE par articulation :")
for j, name in enumerate(names):
    print(f"{name}: {errors_act[:, j].mean():.3f}")

print("\n===== BASELINE : action = état courant =====")
print("MAE globale :", errors_baseline.mean())

print("\n===== Comparaison =====")
if errors_baseline.mean() > 0:
    gain = 100 * (
        1 - errors_act.mean() / errors_baseline.mean()
    )
    print(f"Réduction de MAE par ACT : {gain:.1f} %")
else:
    print("La baseline a une erreur nulle.")

print("\nPremière prédiction :", predictions[0])
print("Première cible      :", targets[0])

