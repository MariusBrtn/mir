
"""
Behavior Cloning visuel pour le robot MIR.
CNN ResNet-18 + état articulaire + MLP.

Environnement : robot312
LeRobot : 0.5.1

Lancer depuis bras_leader_follower_cam :
python train_resnet18_mir.py
"""

from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from torch.utils.data import DataLoader, Subset
from torchvision.models import resnet18, ResNet18_Weights

from lerobot.datasets import LeRobotDataset


# ============================================================
# PARAMÈTRES
# ============================================================

DATASET_REPO_ID = "local/mir_4ddl_cam_dice"

DATASET_ROOT = Path(
    "/Users/marius/Documents/Atelier Vectoriel/MIR/"
    "MIR-software/mir/mir_user_scripts/"
    "bras_leader_follower_cam/dataset_dice"
)

OUTPUT_DIR = Path("outputs/train/resnet18_mir")
MODEL_PATH = OUTPUT_DIR / "model_resnet18_best.pth"

BATCH_SIZE = 8
NUM_EPOCHS = 20

LR_BACKBONE = 1e-5
LR_HEAD = 1e-3
WEIGHT_DECAY = 1e-4

VAL_FRACTION = 0.2
SEED = 42
NUM_WORKERS = 0


# ============================================================
# PÉRIPHÉRIQUE
# ============================================================

device = torch.device(
    "mps" if torch.backends.mps.is_available()
    else "cuda" if torch.cuda.is_available()
    else "cpu"
)

print("Périphérique :", device)


# ============================================================
# MODÈLE
# ============================================================

class ResNetPolicy(nn.Module):

    def __init__(self):
        super().__init__()

        self.cnn = resnet18(
            weights=ResNet18_Weights.DEFAULT
        )
        self.cnn.fc = nn.Identity()  # 512 caractéristiques

        # Geler le backbone, puis dégeler layer3 et layer4.
        for param in self.cnn.parameters():
            param.requires_grad = False

        for param in self.cnn.layer3.parameters():
            param.requires_grad = True

        for param in self.cnn.layer4.parameters():
            param.requires_grad = True

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

        features = torch.cat(
            [visual_features, state_features],
            dim=1,
        )

        return self.mlp(features)


# ============================================================
# NORMALISATION IMAGE
# ============================================================

image_mean = torch.tensor(
    [0.485, 0.456, 0.406],
    device=device,
).view(1, 3, 1, 1)

image_std = torch.tensor(
    [0.229, 0.224, 0.225],
    device=device,
).view(1, 3, 1, 1)


def prepare_batch(batch):
    state = batch["observation.state"].float().to(device)

    image = batch["observation.images.cam_1"].float().to(device)

    if image.ndim != 4:
        raise ValueError(
            f"Dimensions d'image inattendues : {tuple(image.shape)}"
        )

    # Conversion BHWC -> BCHW si nécessaire.
    if image.shape[-1] == 3:
        image = image.permute(0, 3, 1, 2)

    if image.shape[1] != 3:
        raise ValueError(
            f"Nombre de canaux incorrect : {tuple(image.shape)}"
        )

    if image.max().item() > 1.5:
        image = image / 255.0

    image = (image - image_mean) / image_std

    action = batch["action"].float().to(device)

    return image, state, action


# ============================================================
# DATASET
# ============================================================

if not DATASET_ROOT.is_dir():
    raise FileNotFoundError(DATASET_ROOT)

dataset = LeRobotDataset(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT,
    video_backend="pyav",
)

episode_column = np.asarray(
    dataset.hf_dataset["episode_index"]
)

episodes = np.unique(episode_column)

if len(episodes) < 2:
    raise ValueError(
        "Il faut au moins deux épisodes pour séparer "
        "entraînement et validation."
    )

rng = np.random.default_rng(SEED)
shuffled_episodes = rng.permutation(episodes)

n_val = max(
    1,
    int(round(len(episodes) * VAL_FRACTION)),
)
n_val = min(n_val, len(episodes) - 1)

val_episodes = np.sort(shuffled_episodes[:n_val])
train_episodes = np.sort(shuffled_episodes[n_val:])

train_indices = np.flatnonzero(
    np.isin(episode_column, train_episodes)
).tolist()

val_indices = np.flatnonzero(
    np.isin(episode_column, val_episodes)
).tolist()

train_dataset = Subset(dataset, train_indices)
val_dataset = Subset(dataset, val_indices)

train_loader = DataLoader(
    train_dataset,
    batch_size=BATCH_SIZE,
    shuffle=True,
    num_workers=NUM_WORKERS,
)

val_loader = DataLoader(
    val_dataset,
    batch_size=BATCH_SIZE,
    shuffle=False,
    num_workers=NUM_WORKERS,
)

print("Nombre de frames :", len(dataset))
print("Épisodes entraînement :", train_episodes.tolist())
print("Épisodes validation :", val_episodes.tolist())
print("Frames entraînement :", len(train_dataset))
print("Frames validation :", len(val_dataset))


# ============================================================
# INITIALISATION
# ============================================================

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

model = ResNetPolicy().to(device)

total_params = sum(p.numel() for p in model.parameters())
trainable_params = sum(
    p.numel()
    for p in model.parameters()
    if p.requires_grad
)

print(f"Paramètres totaux : {total_params:,}")
print(f"Paramètres entraînables : {trainable_params:,}")

criterion = nn.MSELoss()

optimizer = torch.optim.AdamW(
    [
        {
            "params": model.cnn.layer3.parameters(),
            "lr": LR_BACKBONE,
        },
        {
            "params": model.cnn.layer4.parameters(),
            "lr": LR_BACKBONE,
        },
        {
            "params": model.state_encoder.parameters(),
            "lr": LR_HEAD,
        },
        {
            "params": model.mlp.parameters(),
            "lr": LR_HEAD,
        },
    ],
    weight_decay=WEIGHT_DECAY,
)


# ============================================================
# ENTRAÎNEMENT ET VALIDATION
# ============================================================

train_history = []
val_history = []

best_val_loss = float("inf")

for epoch in range(NUM_EPOCHS):

    model.train()

    # Stabiliser les BatchNorm du backbone préentraîné.
    model.cnn.eval()

    total_loss = 0.0
    total_samples = 0

    for batch in train_loader:

        image, state, action = prepare_batch(batch)

        prediction = model(image, state)
        loss = criterion(prediction, action)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        n = state.shape[0]
        total_loss += loss.item() * n
        total_samples += n

    train_loss = total_loss / total_samples

    # Validation sans calcul de gradients.
    model.eval()

    total_val_loss = 0.0
    total_val_samples = 0

    with torch.inference_mode():
        for batch in val_loader:

            image, state, action = prepare_batch(batch)
            prediction = model(image, state)
            loss = criterion(prediction, action)

            n = state.shape[0]
            total_val_loss += loss.item() * n
            total_val_samples += n

    val_loss = total_val_loss / total_val_samples

    train_history.append(train_loss)
    val_history.append(val_loss)

    print(
        f"Époque {epoch + 1:02d}/{NUM_EPOCHS} | "
        f"train MSE = {train_loss:.4f} | "
        f"val MSE = {val_loss:.4f}"
    )

    # Conserver le meilleur modèle selon les épisodes de validation.
    if val_loss < best_val_loss:
        best_val_loss = val_loss

        torch.save(
            {
                "model_state_dict": model.state_dict(),
                "epoch": epoch + 1,
                "train_loss": train_loss,
                "val_loss": val_loss,
                "train_episodes": train_episodes.tolist(),
                "val_episodes": val_episodes.tolist(),
                "image_mean": [0.485, 0.456, 0.406],
                "image_std": [0.229, 0.224, 0.225],
            },
            MODEL_PATH,
        )

        print("  -> Meilleur modèle sauvegardé.")


# ============================================================
# COURBES D'APPRENTISSAGE
# ============================================================

fig, ax = plt.subplots(figsize=(9, 5))

ax.plot(
    range(1, NUM_EPOCHS + 1),
    train_history,
    label="Entraînement",
)

ax.plot(
    range(1, NUM_EPOCHS + 1),
    val_history,
    label="Validation",
)

ax.set_xlabel("Époque")
ax.set_ylabel("MSE sur les actions")
ax.set_title("Behavior Cloning — ResNet-18 + état articulaire")
ax.grid(True, alpha=0.3)
ax.legend()

fig.tight_layout()

loss_path = OUTPUT_DIR / "loss_resnet18.png"
fig.savefig(loss_path, dpi=150)
plt.close(fig)

print("\nEntraînement terminé.")
print("Meilleur modèle :", MODEL_PATH.resolve())
print("Meilleure MSE validation :", best_val_loss)
print("Courbe :", loss_path.resolve())
