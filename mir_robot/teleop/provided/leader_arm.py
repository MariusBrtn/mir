"""
Bras leader : téléopération fournie avec MIR, proposée dès que le bras leader du robot est construit.

Le bras leader est construit avec la même structure que le robot : ses articulations ont les mêmes noms,
le robot recopie donc ses positions telles quelles.
"""
from mir_robot.teleop import LeaderArmTeleoperator


class LeaderArm(LeaderArmTeleoperator):
    name = "Bras leader"
    description = "Le robot recopie les positions du bras leader."

    def get_action(self, observation):
        return self.read()
