import torch
import torch.nn as nn
import torch.nn.functional as F
import matplotlib.pyplot as plt

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from torch.utils.data import DataLoader


# ============================================================
# PARAMÈTRES
# ============================================================

DATASET_REPO_ID = "local/mir_4ddl_cam"

DATASET_ROOT = (
    "/home/michel/Documents/projets/mir/"
    "mir_user_scripts/demos/bras_leader_follower_cam/dataset"
)

BATCH_SIZE = 32
NUM_EPOCHS = 20
LEARNING_RATE = 1e-3


# ============================================================
# SPATIAL SOFTMAX
# ============================================================
#
# Transforme chaque carte de caractéristiques en une
# position (x, y) dans l'image.
#
# Entrée :
#     (B, C, H, W)
#
# Sortie :
#     (B, 2*C)
#
# ============================================================

class SpatialSoftmax(nn.Module):

    def __init__(self, height, width):

        super().__init__()

        self.height = height
        self.width = width

        # ----------------------------------------------------
        # Coordonnées normalisées dans [-1 ; 1]
        # ----------------------------------------------------

        pos_x, pos_y = torch.meshgrid(
            torch.linspace(-1.0, 1.0, width),
            torch.linspace(-1.0, 1.0, height),
            indexing="xy"
        )

        self.register_buffer(
            "pos_x",
            pos_x.reshape(height * width)
        )

        self.register_buffer(
            "pos_y",
            pos_y.reshape(height * width)
        )


    def forward(self, feature_map):

        # feature_map :
        # (B, C, H, W)

        B, C, H, W = feature_map.shape

        # ----------------------------------------------------
        # On transforme chaque carte en vecteur
        #
        # (B, C, H*W)
        # ----------------------------------------------------

        feature_map = feature_map.reshape(
            B,
            C,
            H * W
        )

        # ----------------------------------------------------
        # Softmax spatial
        # ----------------------------------------------------

        attention = F.softmax(
            feature_map,
            dim=-1
        )

        # ----------------------------------------------------
        # Position moyenne de l'activation
        # ----------------------------------------------------

        expected_x = torch.sum(
            attention * self.pos_x,
            dim=-1
        )

        expected_y = torch.sum(
            attention * self.pos_y,
            dim=-1
        )

        # ----------------------------------------------------
        # Pour chaque feature :
        #
        #     feature → (x, y)
        #
        # C features → 2*C valeurs
        # ----------------------------------------------------

        features = torch.cat(
            [
                expected_x,
                expected_y
            ],
            dim=1
        )

        return features


# ============================================================
# MODÈLE CNN + SPATIAL SOFTMAX + MLP
# ============================================================

class CNNPolicy(nn.Module):

    def __init__(self):

        super().__init__()


        # ====================================================
        # CNN
        # ====================================================
        #
        # Image :
        #
        # (B, 3, 480, 640)
        #
        # On réduit progressivement la résolution.
        #
        # ====================================================

        self.cnn = nn.Sequential(

            # ------------------------------------------------
            # 480 × 640
            # → 240 × 320
            # ------------------------------------------------

            nn.Conv2d(
                in_channels=3,
                out_channels=32,
                kernel_size=5,
                stride=2,
                padding=2
            ),

            nn.ReLU(),


            # ------------------------------------------------
            # 240 × 320
            # → 120 × 160
            # ------------------------------------------------

            nn.Conv2d(
                in_channels=32,
                out_channels=64,
                kernel_size=5,
                stride=2,
                padding=2
            ),

            nn.ReLU(),


            # ------------------------------------------------
            # 120 × 160
            # → 60 × 80
            # ------------------------------------------------

            nn.Conv2d(
                in_channels=64,
                out_channels=128,
                kernel_size=3,
                stride=2,
                padding=1
            ),

            nn.ReLU(),


            # ------------------------------------------------
            # 60 × 80
            # → 30 × 40
            # ------------------------------------------------

            nn.Conv2d(
                in_channels=128,
                out_channels=256,
                kernel_size=3,
                stride=2,
                padding=1
            ),

            nn.ReLU()
        )


        # ====================================================
        # SPATIAL SOFTMAX
        # ====================================================
        #
        # Après le CNN :
        #
        # (B, 256, 30, 40)
        #
        # Chaque feature map est transformée en (x,y).
        #
        # 256 × 2 = 512 valeurs
        #
        # ====================================================

        self.spatial_softmax = SpatialSoftmax(
            height=30,
            width=40
        )


        # ====================================================
        # ENCODAGE VISUEL
        # ====================================================
        #
        # 512
        # ↓
        # 128
        #
        # ====================================================

        self.visual_encoder = nn.Sequential(

            nn.Linear(
                256 * 2,
                128
            ),

            nn.ReLU()
        )


        # ====================================================
        # ENCODAGE ARTICULAIRE
        # ====================================================
        #
        # 5 articulations
        # ↓
        # 32 features
        #
        # ====================================================

        self.state_encoder = nn.Sequential(

            nn.Linear(
                5,
                32
            ),

            nn.ReLU()
        )


        # ====================================================
        # FUSION + MLP
        # ====================================================
        #
        # 128 features visuelles
        # +
        # 32 features articulaires
        #
        # = 160
        #
        # ====================================================

        self.mlp = nn.Sequential(

            nn.Linear(
                128 + 32,
                128
            ),

            nn.ReLU(),

            nn.Linear(
                128,
                64
            ),

            nn.ReLU(),

            nn.Linear(
                64,
                5
            )
        )


    # ========================================================
    # FORWARD
    # ========================================================

    def forward(self, image, state):


        # ====================================================
        # CNN
        # ====================================================

        features = self.cnn(image)

        # (B, 256, 30, 40)


        # ====================================================
        # SPATIAL SOFTMAX
        # ====================================================

        features = self.spatial_softmax(
            features
        )

        # (B, 512)


        # ====================================================
        # ENCODAGE VISUEL
        # ====================================================

        visual_features = self.visual_encoder(
            features
        )

        # (B, 128)


        # ====================================================
        # ENCODAGE ÉTAT ARTICULAIRE
        # ====================================================

        state_features = self.state_encoder(
            state
        )

        # (B, 32)


        # ====================================================
        # FUSION
        # ====================================================

        observation = torch.cat(
            [
                visual_features,
                state_features
            ],
            dim=1
        )

        # (B, 160)


        # ====================================================
        # PRÉDICTION
        # ====================================================

        action = self.mlp(
            observation
        )

        return action


# ============================================================
# CRÉATION DU MODÈLE
# ============================================================

model = CNNPolicy()

print(model)


# ============================================================
# DATASET
# ============================================================

dataset = LeRobotDataset(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT
)


loader = DataLoader(
    dataset,
    batch_size=BATCH_SIZE,
    shuffle=True
)


# ============================================================
# APPRENTISSAGE
# ============================================================

criterion = nn.MSELoss()


optimizer = torch.optim.Adam(
    model.parameters(),
    lr=LEARNING_RATE
)


loss_history = []


model.train()


for epoch in range(NUM_EPOCHS):

    total_loss = 0.0


    for batch in loader:


        # ====================================================
        # ÉTAT ARTICULAIRE
        # ====================================================

        state = batch[
            "observation.state"
        ].float()

        # (B, 5)


        # ====================================================
        # IMAGE
        # ====================================================

        image = batch[
            "observation.images.cam_1"
        ].float()

        # (B, 3, 480, 640)


        # ====================================================
        # NORMALISATION IMAGE
        # ====================================================

        image = image / 255.0


        # ====================================================
        # ACTION CIBLE
        # ====================================================

        action = batch[
            "action"
        ].float()

        # (B, 5)


        # ====================================================
        # PRÉDICTION
        # ====================================================

        prediction = model(
            image,
            state
        )


        # ====================================================
        # LOSS
        # ====================================================

        loss = criterion(
            prediction,
            action
        )


        # ====================================================
        # DESCENTE DE GRADIENT
        # ====================================================

        optimizer.zero_grad()

        loss.backward()

        optimizer.step()


        # ====================================================
        # ACCUMULATION
        # ====================================================

        total_loss += (
            loss.item() * len(state)
        )


    # ========================================================
    # LOSS MOYENNE
    # ========================================================

    mean_loss = total_loss / len(dataset)

    loss_history.append(mean_loss)


    print(
        f"Epoch {epoch + 1}/{NUM_EPOCHS} "
        f"- Loss: {mean_loss:.6f}"
    )


# ============================================================
# SAUVEGARDE
# ============================================================

torch.save(
    model.state_dict(),
    "model_cnn_spatial.pth"
)

print(
    "\nModèle sauvegardé dans "
    "model_cnn_spatial.pth"
)


# ============================================================
# COURBE D'APPRENTISSAGE
# ============================================================

plt.plot(
    loss_history
)

plt.xlabel("Epoch")
plt.ylabel("MSE")

plt.title(
    "Training loss - CNN + Spatial Softmax"
)

plt.grid()

plt.show()