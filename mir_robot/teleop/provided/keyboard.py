"""
Clavier : téléopération fournie avec MIR, pour n'importe quel robot.

1 à 9 choisissent l'actionneur ; tant que ← ou → est enfoncée, sa consigne diminue ou augmente.
"""
from mir_robot.teleop import KeyboardTeleoperator

POSITION_SPEED = 30.0       # °/s : vitesse de la consigne de position tant que la flèche est enfoncée
VELOCITY_STEP = 20.0        # °/s : consigne de vitesse quand la flèche est enfoncée (0 sinon)


class Keyboard(KeyboardTeleoperator):
    name = "Clavier"
    description = ("1 à 9 : choisir l'actionneur · ← → : diminuer/augmenter la consigne (tant que la touche est "
                   "enfoncée) · Échap : terminer")

    def connect(self):
        super().connect()
        self.names = list(self.actions)
        if not self.names:
            raise ValueError("le robot n'a aucune action")
        self.selected = self.names[0]
        self.targets = {}

    def get_action(self, observation):
        keys = self.read()
        for i, name in enumerate(self.names[:9]):
            if keys[str(i + 1)]:
                self.selected = name

        name = self.selected
        direction = keys["right"] - keys["left"]        # +1, -1 ou 0
        if name.endswith(".velocity"):
            return {name: direction * VELOCITY_STEP}
        if name not in self.targets:
            # on part de la position mesurée, puis la consigne évolue seule (sans dériver avec la mesure)
            self.targets[name] = observation.get(name, 0.0)
        if direction == 0:
            return None
        self.targets[name] += direction * POSITION_SPEED / self.fps
        value_range = self.actions[name].get_range()
        if value_range is not None:
            # la consigne reste dans la plage, sinon il faudrait « revenir » avant que le moteur ne bouge
            self.targets[name] = min(max(self.targets[name], value_range[0]), value_range[1])
        return {name: self.targets[name]}
