from mir_robot.mir_robot import mirRobot, mirRobotConfig

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.feature_utils import build_dataset_frame
from lerobot.utils.constants import ACTION, OBS_STR
from mir_utils.period_waiters import PeriodWaiterExact
import time

import cv2


# Paramètres

FPS = 20
TASK = "bras_4ddl_cam"

DATASET_REPO_ID = "local/mir_4ddl_cam_dice"
DATASET_ROOT = "/Users/marius/Documents/Atelier Vectoriel/MIR/MIR-software/mir/mir_user_scripts/bras_leader_follower_cam/dataset_dice"

NUM_EPISODES = 30
EPISODE_TIME = 6

JOINT_NAMES = [


    "joint_1.position",
    "joint_2.position",
    "joint_3.position",
    "joint_4.position",
    "joint_5.position"
]

FEATURES = {
    "observation.state": {
        "dtype": "float32",
        "shape": (len(JOINT_NAMES),),
        "names": JOINT_NAMES,
    },

    "observation.images.cam_1": {
        "dtype": "video",
        "shape": (240, 320, 3),
        "names": ["height", "width", "channels"],
    },

    "action": {
        "dtype": "float32",
        "shape": (len(JOINT_NAMES),),
        "names": JOINT_NAMES,
    },
}


# Initialisation des deux bras

# Configuration du bras leader
leader_config = mirRobotConfig.load("/Users/marius/Documents/Atelier Vectoriel/MIR/MIR-software/mir/mir_user_scripts/bras_leader_follower_cam/bras_leader.json")

# Configuration du bras follower
follower_config = mirRobotConfig.load("/Users/marius/Documents/Atelier Vectoriel/MIR/MIR-software/mir/mir_user_scripts/bras_leader_follower_cam/bras_follower_cam.json")

leader = mirRobot(leader_config)
follower = mirRobot(follower_config)

# Connexion et configuration
leader.connect()
leader.configure()
leader.enable_all_observations()

follower.connect()
follower.configure()
follower.enable_all_observations()

period_waiter = PeriodWaiterExact(1/20)

# Création du dataset


dataset = LeRobotDataset.create(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT,
    fps=FPS,
    features=FEATURES,
    robot_type="mir_robot",
    vcodec="h264",
    batch_encoding_size=1,
)

# Enregistrement des épisodes

RESET_TIME = 5  # temps pour remettre le leader en position initiale

print()
print("========================================")
print("     ENREGISTREMENT DU DATASET MIR")
print("========================================")
print(f"Nombre d'épisodes : {NUM_EPISODES}")
print(f"Durée d'un épisode : {EPISODE_TIME} s")
print(f"Fréquence : {FPS} Hz")
print()

for episode_idx in range(NUM_EPISODES):

    print(
        f"Épisode {episode_idx + 1}/{NUM_EPISODES} "
        f"— placez le leader en position initiale "
        f"pendant les {RESET_TIME} prochaines secondes..."
    )
    # Phase de remise en position : non enregistrée
    for _ in range(RESET_TIME * FPS):

        action = leader.get_observation()
        follower.send_action(action)

        time.sleep(1/FPS)
        print('SB')

    print("Enregistrement en cours...")
    period_waiter.start()
    # Enregistrement de la démonstration
    for _ in range(EPISODE_TIME * FPS):


        observation = follower.get_observation()
        observation["cam_1"] = cv2.rotate(
            observation["cam_1"],
            cv2.ROTATE_180
        )
        observation["cam_1"] = cv2.resize(
        observation["cam_1"],
        (320, 240),
        interpolation=cv2.INTER_AREA
        )
        cv2.imshow("Camera", observation["cam_1"])
        action = leader.get_observation()

        follower.send_action(action)

        observation_frame = build_dataset_frame(
            dataset.features,
            observation,
            prefix=OBS_STR,
        )

        action_frame = build_dataset_frame(
            dataset.features,
            action,
            prefix=ACTION,
        )

        dataset.add_frame({
            **observation_frame,
            **action_frame,
            "task": TASK,
        })

        period_waiter.wait()

    dataset.save_episode()


    print(f"Épisode {episode_idx + 1}/{NUM_EPISODES} terminé.")

    if episode_idx < NUM_EPISODES - 1:
        input("Appuyez sur Entrée pour préparer l'épisode suivant...")

    print()

dataset.finalize()