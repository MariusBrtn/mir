"""
Conduite au clavier : téléopération du robot mobile à 4 roues.

Les deux roues d'un même côté reçoivent exactement la même consigne, et chaque roue tourne à sa vitesse
maximale dès qu'une flèche est enfoncée (0 dès qu'on la relâche) :
  ↑ / ↓  : avancer / reculer
  ← / →  : tourner sur place à gauche / à droite
  ↑ + ← (ou →) : virage (les roues du côté intérieur s'arrêtent)
Les roues de droite sont montées en miroir de celles de gauche : pour avancer, elles tournent dans l'autre sens.
Échap arrête la téléopération.
"""
from mir_robot.teleop import KeyboardTeleoperator

SENS = {"gauche": 1, "droite": -1}      # sens de rotation des roues de chaque côté pour avancer
VMAX_DEFAUT = 60.0                      # tr/min, si le robot ne donne pas la vitesse max de ses roues


class ConduiteClavier(KeyboardTeleoperator):
    name = "Conduite au clavier"
    description = "↑ ↓ : avancer / reculer · ← → : tourner · vitesse maximale dès qu'une flèche est enfoncée"

    def connect(self):
        super().connect()
        # roues de chaque côté, d'après le nom de leur consigne de vitesse (ex. roue_avant_gauche.velocity)
        self.roues = {cote: [nom for nom in self.actions if nom.endswith(".velocity") and cote in nom] for cote in SENS}
        if not self.roues["gauche"] or not self.roues["droite"]:
            raise ValueError("il faut des roues à gauche et à droite (consignes « ..._gauche.velocity » et "
                             "« ..._droite.velocity »)")
        # vitesse max commune à toutes les roues : les deux côtés reçoivent exactement la même consigne
        plages = [self.actions[nom].get_range() for roues in self.roues.values() for nom in roues]
        self.vmax = min(plage[1] for plage in plages) if all(plages) else VMAX_DEFAUT

    def get_action(self, observation):
        touches = self.read()
        avance = touches["up"] - touches["down"]          # +1, -1 ou 0
        rotation = touches["right"] - touches["left"]     # +1 : tourner à droite
        consigne = {
            "gauche": max(-1, min(1, avance + rotation)) * self.vmax,
            "droite": max(-1, min(1, avance - rotation)) * self.vmax,
        }
        return {nom: SENS[cote] * consigne[cote] for cote, roues in self.roues.items() for nom in roues}
