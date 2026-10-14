"""
Inférence ACT pas à pas sur le robot MIR
Environnement : Conda robot312
LeRobot : 0.5.1

À lancer depuis bras_leader_follower_cam.

Mode test :
- ACT propose une action.
- L'action est affichée.
- Entrée l'envoie au follower.
- r abandonne l'essai courant.
- q quitte le programme.

Par sécurité, EXECUTE_ACTIONS vaut False par défaut :
les actions ACT sont calculées et affichées, mais ne sont pas envoyées.
"""

from pathlib import Path
import time

import cv2
import numpy as np
import torch

from mir_robot.mir_robot import mirRobot, mirRobotConfig
from lerobot.datasets import LeRobotDatasetMetadata
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.act.processor_act import make_act_pre_post_processors


# ============================================================
# PARAMÈTRES À RÉGLER
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATASET_REPO_ID = "local/mir_4ddl_cam_dice"
DATASET_ROOT = BASE_DIR / "dataset_dice"

# Le script cherche config.json dans ce dossier ou dans son
# sous-dossier pretrained_model.
CHECKPOINT_ROOT = (
    BASE_DIR
    / "outputs"
    / "train"
    / "act_mir_experiment_V2"
    / "checkpoints"
    / "last"
)

LEADER_CONFIG = BASE_DIR / "bras_leader.json"
FOLLOWER_CONFIG = BASE_DIR / "bras_follower_cam.json"

DEVICE = torch.device("mps")

FPS = 20
EPISODE_TIME = 6
NUM_STEPS = FPS * EPISODE_TIME  # 120 actions validables au maximum

# Nombre d'actions exploitées avant de renouveler le chunk ACT.
# Cette valeur doit rester cohérente avec le comportement du modèle.
N_ACTION_STEPS = 10

# False : affiche les actions sans les envoyer.
# True : envoie réellement les actions validées au follower.
EXECUTE_ACTIONS = True

# À activer uniquement si les images du dataset ont été tournées de 180°.
ROTATE_IMAGE_180 = False


# ============================================================
# VALIDATION ET REPÉRAGE DU CHECKPOINT
# ============================================================

print("ÉTAPE 1 : démarrage du script", flush=True)

if not DATASET_ROOT.is_dir():
    raise FileNotFoundError(f"Dataset introuvable : {DATASET_ROOT}")

if not LEADER_CONFIG.is_file():
    raise FileNotFoundError(f"Configuration leader introuvable : {LEADER_CONFIG}")

if not FOLLOWER_CONFIG.is_file():
    raise FileNotFoundError(f"Configuration follower introuvable : {FOLLOWER_CONFIG}")

# Selon la structure du checkpoint, config.json peut se trouver
# directement dans last/ ou dans last/pretrained_model/.
possible_model_roots = [
    CHECKPOINT_ROOT,
    CHECKPOINT_ROOT / "pretrained_model",
]

MODEL_ROOT = next(
    (path for path in possible_model_roots if (path / "config.json").is_file()),
    None,
)

if MODEL_ROOT is None:
    searched = "\n".join(str(p) for p in possible_model_roots)
    raise FileNotFoundError(
        "Impossible de trouver config.json dans le checkpoint ACT.\n"
        f"Dossiers vérifiés :\n{searched}\n"
        "Vérifie la structure de outputs/train/act_mir_experiment_V2."
    )

print(f"Checkpoint utilisé : {MODEL_ROOT}", flush=True)


# ============================================================
# MÉTADONNÉES DU DATASET
# ============================================================

print("ÉTAPE 2 : chargement des métadonnées du dataset", flush=True)

dataset_metadata = LeRobotDatasetMetadata(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT,
)

print("Fréquence du dataset :", dataset_metadata.fps)
print("Features du dataset :")
for key, feature in dataset_metadata.features.items():
    print(f"  {key}: {feature}")


# ============================================================
# CHARGEMENT DE LA POLITIQUE ACT ET DES PROCESSEURS
# ============================================================

print("ÉTAPE 3 : chargement de la politique ACT", flush=True)

policy = ACTPolicy.from_pretrained(str(MODEL_ROOT))
policy = policy.to(DEVICE)
policy.eval()

# Paramètre de sélection des actions, réglable en tête de script.
policy.config.n_action_steps = N_ACTION_STEPS

preprocessor, postprocessor = make_act_pre_post_processors(
    policy.config,
    dataset_stats=dataset_metadata.stats,
)

print("Politique ACT chargée.")
print("Device :", DEVICE)
print("Chunk size :", policy.config.chunk_size)
print("N_ACTION_STEPS demandé :", N_ACTION_STEPS)
print("N_ACTION_STEPS dans la config :", policy.config.n_action_steps)


# ============================================================
# CONNEXION AUX ROBOTS MIR
# ============================================================

print("ÉTAPE 4 : connexion au leader", flush=True)

leader_config = mirRobotConfig.load(str(LEADER_CONFIG))
follower_config = mirRobotConfig.load(str(FOLLOWER_CONFIG))

leader = mirRobot(leader_config)
follower = mirRobot(follower_config)

leader.connect()
leader.configure()
leader.enable_all_observations()

print("ÉTAPE 5 : connexion au follower", flush=True)

follower.connect()
follower.configure()
follower.enable_all_observations()


# ============================================================
# CONSTRUCTION DE L'OBSERVATION ACT
# ============================================================

def build_observation(observation):
    """
    Convertit les observations MIR vers les clés utilisées
    par le dataset LeRobot.

    Hypothèses à confirmer avec meta/info.json :
      - image : observation.images.cam_1
      - état : observation.state avec 5 positions articulaires
    """

    image = observation["cam_1"]

    if ROTATE_IMAGE_180:
        image = cv2.rotate(image, cv2.ROTATE_180)

    # OpenCV fournit normalement une image HWC, BGR.
    # LeRobot attend généralement un tenseur image CHW.
    # On ne convertit pas en float et on ne normalise pas ici :
    # le préprocesseur ACT prend en charge le traitement prévu
    # par la configuration de la politique.
    image_tensor = torch.from_numpy(
        np.ascontiguousarray(image)
    ).permute(2, 0, 1)

    state = torch.tensor(
        [
            observation[f"joint_{j}.position"]
            for j in range(1, 6)
        ],
        dtype=torch.float32,
    )

    return {
        "observation.images.cam_1": image_tensor,
        "observation.state": state,
    }


# ============================================================
# PRÉDICTION D'UNE ACTION
# ============================================================

def predict_action(observation):
    observation_frame = build_observation(observation)
    observation_processed = preprocessor(observation_frame)

    with torch.inference_mode():
        action_processed = policy.select_action(observation_processed)

    action_unprocessed = postprocessor(action_processed)

    # Le postprocesseur ACT standard renvoie généralement un tenseur.
    # On accepte aussi un dictionnaire si le pipeline en renvoie un.
    if isinstance(action_unprocessed, dict):
        if "action" not in action_unprocessed:
            raise KeyError(
                "Le postprocesseur a renvoyé un dictionnaire sans clé 'action'. "
                f"Clés reçues : {list(action_unprocessed.keys())}"
            )
        action_tensor = action_unprocessed["action"]
    else:
        action_tensor = action_unprocessed

    if not isinstance(action_tensor, torch.Tensor):
        raise TypeError(
            "Type d'action inattendu après post-traitement : "
            f"{type(action_tensor)}"
        )

    action_values = (
        action_tensor.detach()
        .to("cpu")
        .reshape(-1)
        .numpy()
    )

    if len(action_values) != 5:
        raise RuntimeError(
            f"Dimension d'action inattendue : {len(action_values)} au lieu de 5. "
            "Vérifie output_features dans le checkpoint et le dataset."
        )

    if not np.isfinite(action_values).all():
        raise RuntimeError("ACT a produit une action non finie.")

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

    return state, action


# ============================================================
# TEST INTERACTIF PAS À PAS
# ============================================================

try:
    print("\n=== TEST INTERACTIF ACT ===")
    print(f"Nombre maximal d'actions par essai : {NUM_STEPS}")
    print("Entrée : commencer / valider l'action affichée")
    print("r      : abandonner l'essai courant")
    print("q      : quitter")
    print("Mode :", "ENVOI ACTIF" if EXECUTE_ACTIONS else "SIMULATION SANS ENVOI")
    print(
        "\nAttention : en mode simulation, les observations du follower "
        "ne changent pas sous l'effet des actions ACT."
    )

    while True:
        command = input(
            "\nEntrée pour commencer un essai, q pour quitter : "
        ).strip().lower()

        if command == "q":
            break

        if EXECUTE_ACTIONS:
            print("\nMise en position initiale du follower...")
            initial_observation = leader.get_observation()
            follower.send_action(initial_observation)
            input(
                "Position initiale envoyée. "
                "Vérifie la zone de travail, puis Entrée pour commencer..."
            )

        # Réinitialise le cache d'actions ACT au début de chaque essai.
        policy.reset()

        for step in range(NUM_STEPS):
            observation = follower.get_observation()
            state, action = predict_action(observation)

            print("\n" + "=" * 55)
            print(f"ÉTAPE {step + 1}/{NUM_STEPS}")
            print("=" * 55)

            print("\nÉtat articulaire observé :")
            for j, value in enumerate(state, start=1):
                print(f"  joint_{j}.position : {value:.4f}")

            print("\nAction proposée par ACT :")
            for name, value in action.items():
                print(f"  {name} : {value:.4f}")

            command = input(
                "\nEntrée = valider | r = abandonner l'essai | q = quitter : "
            ).strip().lower()

            if command == "q":
                raise KeyboardInterrupt

            if command == "r":
                print("Essai abandonné.")
                break

            if EXECUTE_ACTIONS:
                follower.send_action(action)
                print("Action envoyée au follower.")
            else:
                print("Simulation : action non envoyée (EXECUTE_ACTIONS=False).")

        else:
            print(f"\nFin de l'essai : {NUM_STEPS} étapes traitées.")

finally:
    print("\nFin du test interactif.")
    print("Vérifie l'état des moteurs et applique la procédure habituelle d'arrêt du MIR.")
