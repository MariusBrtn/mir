
from mir_robot.mir_robot import mirRobot, mirRobotConfig
from mir_utils.period_waiters import PeriodWaiterExact

import torch
import torch.nn as nn
import cv2
import time

from torchvision.models import resnet18


# ============================================================
# CONFIGURATION DES BRAS
# ============================================================

leader_config = mirRobotConfig.load(
    "/home/michel/Documents/projets/mir/"
    "mir_user_scripts/demos/bras_leader_follower_cam/"
    "bras_leader.json"
)

follower_config = mirRobotConfig.load(
    "/home/michel/Documents/projets/mir/"
    "mir_user_scripts/demos/bras_leader_follower_cam/"
    "bras_follower_cam.json"
)

leader = mirRobot(leader_config)
follower = mirRobot(follower_config)


# ============================================================
# CONNEXION ET CONFIGURATION
# ============================================================

leader.connect()
leader.configure()
leader.enable_all_observations()

follower.connect()
follower.configure()
follower.enable_all_observations()


# ============================================================
# PARAMÈTRES TEMPORELS
# ============================================================

FPS = 20
EPISODE_TIME = 6
NUM_STEPS = FPS * EPISODE_TIME

period_waiter = PeriodWaiterExact(1 / FPS)


# ============================================================
# MODÈLE RESNET-18 + ÉTAT ARTICULAIRE + MLP
# ============================================================

class ResNetPolicy(nn.Module):

    def __init__(self):
        super().__init__()

        # ResNet-18 sans sa couche de classification finale.
        # Les poids appris sont chargés depuis notre checkpoint.
        self.cnn = resnet18(weights=None)
        self.cnn.fc = nn.Identity()

        # Encodeur de l'état articulaire : 5 -> 32
        self.state_encoder = nn.Sequential(
            nn.Linear(5, 32),
            nn.ReLU()
        )

        # Fusion des 512 caractéristiques visuelles et des
        # 32 caractéristiques articulaires : 544 -> 5 actions
        self.mlp = nn.Sequential(
            nn.Linear(544, 128),
            nn.ReLU(),

            nn.Linear(128, 64),
            nn.ReLU(),

            nn.Linear(64, 5)
        )

    def forward(self, image, state):

        # Extraction des caractéristiques visuelles
        visual_features = self.cnn(image)

        # Encodage de l'état articulaire
        state_features = self.state_encoder(state)

        # Fusion des deux sources d'information
        features = torch.cat(
            [visual_features, state_features],
            dim=1
        )

        # Prédiction des cinq positions articulaires
        return self.mlp(features)


# ============================================================
# CHARGEMENT DU MODÈLE ENTRAÎNÉ
# ============================================================

MODEL_PATH = (
    "/home/michel/Documents/projets/mir/"
    "mir_user_scripts/demos/bras_leader_follower_cam/"
    "model_resnet18_frozen.pth"
)

device = torch.device("cpu")

model = ResNetPolicy().to(device)

model.load_state_dict(
    torch.load(
        MODEL_PATH,
        map_location=device,
        weights_only=True
    )
)

model.eval()

print("Modèle ResNet-18 chargé.")
print(f"Fréquence cible : {FPS} Hz")
print(f"Durée d'un essai : {EPISODE_TIME} s")
print(f"Nombre d'itérations : {NUM_STEPS}")


# ============================================================
# NORMALISATION DES IMAGES
# ============================================================

# Statistiques ImageNet : identiques à celles de l'entraînement
IMAGE_MEAN = torch.tensor(
    [0.485, 0.456, 0.406],
    dtype=torch.float32
).view(3, 1, 1)

IMAGE_STD = torch.tensor(
    [0.229, 0.224, 0.225],
    dtype=torch.float32
).view(3, 1, 1)


# ============================================================
# INFÉRENCE
# ============================================================

def get_action_from_observation(observation):

    # --------------------------------------------------------
    # Image
    # --------------------------------------------------------

    image = observation["cam_1"]

    # Même rotation que lors de la création du dataset
    image = cv2.rotate(
        image,
        cv2.ROTATE_180
    )

    image = cv2.resize(
    image,
    (320, 240),
    interpolation=cv2.INTER_AREA
    )

    # (H, W, C) -> (C, H, W)
    image = torch.from_numpy(
        image.copy()
    ).float()

    image = image.permute(2, 0, 1)

    # Passage dans [0, 1]
    image = image / 255.0

    # Normalisation ImageNet
    image = (image - IMAGE_MEAN) / IMAGE_STD

    # Ajout de la dimension batch
    image = image.unsqueeze(0).to(device)

    # --------------------------------------------------------
    # État articulaire
    # --------------------------------------------------------

    state = torch.tensor(
        [
            observation["joint_1.position"],
            observation["joint_2.position"],
            observation["joint_3.position"],
            observation["joint_4.position"],
            observation["joint_5.position"]
        ],
        dtype=torch.float32
    ).unsqueeze(0).to(device)

    # --------------------------------------------------------
    # Prédiction
    # --------------------------------------------------------

    with torch.inference_mode():
        action_tensor = model(image, state)[0]

    if not torch.isfinite(action_tensor).all():
        raise RuntimeError(
            "Le modèle a produit une action non finie."
        )

    action_values = action_tensor.cpu().tolist()

    action = {
        f"joint_{j}.position": action_values[j - 1]
        for j in range(1, 6)
    }

    return state[0].cpu().numpy(), action


# ============================================================
# EXÉCUTION DES ESSAIS
# ============================================================

try:

    # --------------------------------------------------------
    # Position initiale : leader -> follower
    # --------------------------------------------------------

    print("\nMise en position initiale du follower...")

    observations_leader = leader.get_observation()
    follower.send_action(observations_leader)

    time.sleep(2)

    print("Position initiale établie.")

    # --------------------------------------------------------
    # Boucle des essais
    # --------------------------------------------------------

    while True:

        commande = input(
            "\nAppuyez sur Entrée pour lancer un mouvement "
            "de 6 secondes, ou tapez q pour quitter : "
        )

        if commande.strip().lower() == "q":
            break

        # Réinitialisation à la position du leader
        print("\nMise en position initiale...")

        observations_leader = leader.get_observation()
        follower.send_action(observations_leader)

        time.sleep(2)

        print("Mouvement en cours...")

        debut_essai = time.perf_counter()
        period_waiter.start()
        for i in range(NUM_STEPS):

            # Observation du follower
            observation = follower.get_observation()

            # Prédiction de l'action
            state, action = get_action_from_observation(
                observation
            )

            # Affichage de progression une fois par seconde
            if i % FPS == 0:
                print(
                    f"Temps : {i / FPS:.0f} s / "
                    f"{EPISODE_TIME} s"
                )
                print("État :", state)
                print("Action :", list(action.values()))

            # Commande du follower
            follower.send_action(action)

            # Synchronisation temporelle
            #period_waiter.wait()

        duree = time.perf_counter() - debut_essai

        print(
            f"Mouvement terminé en {duree:.2f} s "
            f"(durée cible : {EPISODE_TIME} s)."
        )

finally:

    print("Fin du programme.")