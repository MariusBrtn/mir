"""
Bras leader : le robot recopie les positions du bras leader.

À chaque tour de boucle, MIR appelle get_action(observation) puis envoie au robot ce qu'elle renvoie.
  self.read()  : les positions du bras leader, ex. {"joint_1.position": 12.3, ...}
  observation  : les mesures du robot piloté, ex. observation["joint_1.position"]
Le bras leader est construit avec la même structure que le robot : ses articulations ont les mêmes noms.
Sa configuration est dans leader_arm.json (créée par « Créer le bras leader »).
"""
from mir_robot.teleop import LeaderArmTeleoperator


class LeaderArm(LeaderArmTeleoperator):
    name = "Bras leader"
    description = "Le robot recopie les positions du bras leader."

    def get_action(self, observation):
        leader = self.read()
        return leader
