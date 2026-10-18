"""
script_test

robot.get_observation()                 toutes les mesures du robot (dictionnaire)
robot.get_observation("joint_1.position")   une seule mesure
robot.send_action({"joint_1.position": 30.0})   envoie une consigne
robot.observations, robot.actions       les noms disponibles (voir aussi la liste à gauche)
for t in boucle(frequence=50, duree=5):  boucle cadencée ; t = temps écoulé (s)
"""
from mir_robot.script import robot, boucle
import matplotlib.pyplot as plt

import time

"""
Réponse indicielle de joint_1 : échelon de 0° à 30°.
"""
import time
import matplotlib.pyplot as plt
from mir_robot.script import robot, boucle

ARTICULATION = "joint_1"
DEPART = 0.0        # °
ARRIVEE = 30.0      # °
FREQUENCE = 200     # Hz
DUREE = 2.0         # s

# 1. Se placer au point de départ et attendre que le moteur y soit
robot.send_action({f"{ARTICULATION}.position": DEPART})
time.sleep(1.5)
print(f"Position de départ : {robot.get_observation(f'{ARTICULATION}.position'):.1f}°")

# 2. Échelon : la consigne change une seule fois, à t = 0
temps, consignes, mesures = [], [], []
robot.send_action({f"{ARTICULATION}.position": ARRIVEE})
for t in boucle(frequence=FREQUENCE, duree=DUREE):
    temps.append(t)
    consignes.append(ARRIVEE)
    mesures.append(robot.get_observation(f"{ARTICULATION}.position"))


# 3. Figure finale
plt.figure("Réponse indicielle")
plt.plot(temps, consignes, "--", label="consigne")
plt.plot(temps, mesures, label="mesure")
plt.xlabel("t (s)")
plt.ylabel(f"position de {ARTICULATION} (°)")
plt.title(f"Échelon {DEPART:g}° → {ARRIVEE:g}°")
plt.legend()
plt.grid(True)
plt.show()

print(f"Valeur finale : {mesures[-1]:.1f}° ; erreur statique : {ARRIVEE - mesures[-1]:.1f}°")
