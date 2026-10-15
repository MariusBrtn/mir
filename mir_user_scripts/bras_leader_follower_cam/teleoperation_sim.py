"""
Téléopération du bras simulé.

  python teleoperation_sim.py              # bras leader réel -> follower simulé
  python teleoperation_sim.py --sliders    # sans matériel : curseurs à l'écran

Fenêtre : vue d'ensemble à gauche, caméra cam_1 simulée à droite. 'q' pour quitter, 'r' pour réinitialiser.
"""
import argparse
from pathlib import Path
import cv2
import numpy as np
from mir_robot.mir_robot import mirRobot, mirRobotConfig
from mir_sim.sim_devices_factory import SimDevicesFactory
from mir_utils.period_waiters import PeriodWaiterExact

HERE = Path(__file__).parent
WINDOW = "Simulation (q: quitter, r: reset)"

parser = argparse.ArgumentParser()
parser.add_argument("--sliders", action="store_true", help="piloter avec des curseurs au lieu du bras leader")
parser.add_argument("--scene", default=str(HERE / "scene_de.json"), help="scène simulée (table, objets, caméras fixes)")
parser.add_argument("--hz", type=float, default=30.0)
args = parser.parse_args()

follower_config = mirRobotConfig.load(str(HERE / "bras_follower_cam.json"))
# le bras simulé est construit à partir de la section "structure" de la config du follower
factory = SimDevicesFactory(scene=args.scene)
follower = mirRobot(follower_config, devices_factory=factory)
follower.connect()
follower.configure()
follower.enable_all_observations()
world = factory.world
assert world is not None
motors = list(follower_config.motor_bus.motors) if follower_config.motor_bus else []

cv2.namedWindow(WINDOW)
leader = None
if args.sliders:
    for m in motors:
        lo, hi = world.joints[m].range_deg
        cv2.createTrackbar(m, WINDOW, int(-lo), int(hi - lo), lambda _: None)
else:
    leader_config = mirRobotConfig.load(str(HERE / "bras_leader.json"))
    leader = mirRobot(leader_config)
    leader.connect()
    leader.configure()
    leader.enable_all_observations()


def read_sliders() -> dict[str, float]:
    action = {}
    for m in motors:
        lo, _ = world.joints[m].range_deg
        action[f"{m}.position"] = cv2.getTrackbarPos(m, WINDOW) + lo
    return action


waiter = PeriodWaiterExact(1.0 / args.hz)
try:
    while True:
        if leader is not None:
            leader_obs = leader.get_observation()
            action = {k: v for k, v in leader_obs.items() if k in follower.action_features}
        else:
            action = read_sliders()
        follower.send_action(action)
        observation = follower.get_observation()

        overview = world.render("overview", 640, 480)
        cam = observation["cam_1"]
        view = cv2.cvtColor(np.hstack([overview, cam]), cv2.COLOR_RGB2BGR)
        cv2.imshow(WINDOW, cv2.resize(view, (1280 * 3 // 4, 480 * 3 // 4), interpolation=cv2.INTER_AREA))
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            world.reset()
        waiter.wait()
finally:
    follower.disconnect()
    if leader is not None:
        leader.disconnect()
    cv2.destroyAllWindows()
