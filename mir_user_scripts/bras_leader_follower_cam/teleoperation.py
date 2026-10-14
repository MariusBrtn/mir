from mir_robot.mir_robot import mirRobot, mirRobotConfig
import cv2
from mir_utils.period_waiters import PeriodWaiterExact

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

while True:
    # Lecture de l'observation du bras leader
    observations_leader = leader.get_observation()
    follower.send_action(observations_leader)
    observations_follower = follower.get_observation()
    image = observations_follower["cam_1"]
    image = cv2.rotate(image, cv2.ROTATE_180)
        # Redimensionnement en 320 x 240
    image = cv2.resize(
        image,
        (320, 240),
        interpolation=cv2.INTER_AREA
    )
    image = cv2.cvtColor(image, cv2. COLOR_RGB2BGR)
    print(observations_follower)

    cv2.imshow("Camera", image)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cv2.destroyAllWindows()