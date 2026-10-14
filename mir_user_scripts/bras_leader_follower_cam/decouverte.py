from mir_robot.mir_robot import mirRobot, mirRobotConfig
import time 
config = mirRobotConfig.load("/home/michel/Documents/projets/mir/mir_user_scripts/demos/bras_leader_follower/bras_follower.json") 

robot_follower = mirRobot(config)

robot_follower.connect()
robot_follower.configure()
robot_follower.enable_all_observations()

robot_follower.send_action({
"joint_1.position": 0.0,
"joint_2.position": 80.0,
"joint_3.position": 0.0,
"joint_4.position": 0.0,
"joint_5.position": 0.0,
})

time.sleep(2)


import matplotlib.pyplot as plt

duree = 2          
dt = 0.01         

temps = []
consignes = []
positions = []

t0 = time.time()
action = {"joint_1.position": 30}
robot_follower.send_action(action)

while time.time() - t0 < duree:


    t = time.time() - t0


    observation = robot_follower.get_observation()
    position = observation["joint_1.position"]

    temps.append(t)
    consignes.append(30)
    positions.append(position)

    time.sleep(dt)


plt.plot(temps, consignes, label="Consigne")
plt.plot(temps, positions, label="Position")

plt.xlabel("Temps (s)")
plt.ylabel("Position (°)")
plt.legend()
plt.grid()
plt.show()