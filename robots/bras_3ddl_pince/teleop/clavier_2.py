"""
Clavier_2 : téléopération au clavier.

À chaque tour de boucle, MIR appelle get_action(observation) puis envoie au robot ce qu'elle renvoie.
  self.read()  : l'état des touches, True si elle est enfoncée : keys["left"], keys["right"], keys["up"],
                 keys["down"], keys["space"], keys["a"], keys["1"]...
  observation  : les mesures du robot, ex. observation["joint_1.position"]
  self.fps     : tours de boucle par seconde
get_action renvoie l'action envoyée au robot, par exemple {"joint_1.position": 30.0}, ou None pour ne rien envoyer.
Les touches sont celles pressées dans la fenêtre de MIR. Échap arrête la téléopération.
"""
from mir_robot.teleop import KeyboardTeleoperator

SPEED = 30.0        # °/s tant que la flèche est enfoncée


class Clavier2(KeyboardTeleoperator):
    name = "Clavier_2"
    description = "← → : tourner l'articulation 1"

    def connect(self):
        super().connect()
        self.target = None

    def get_action(self, observation):
        keys = self.read()
        if self.target is None:
            self.target = observation["joint_1.position"]     # on part de la position mesurée
        if keys["right"]:
            self.target += SPEED / self.fps
        if keys["left"]:
            self.target -= SPEED / self.fps
        return {"joint_1.position": self.target}
