"""
bras_leader : téléopération écrite par l'utilisateur.

MIR appelle demarrer() une fois, puis action(observation) à chaque tour de boucle, puis arreter().
action() renvoie l'action à envoyer au robot, par exemple {"joint_1.position": 30.0}, ou None pour ne rien envoyer.
Les touches sont celles pressées dans la fenêtre de MIR pendant que la commande tourne.
"""
from mir_robot.commande import Commande, Parametre
from mir_utils.keyboard_listener import Key


class BrasLeader(Commande):
    nom = "bras_leader"
    description = "Flèches gauche et droite : tourner l'articulation choisie · Échap : terminer"
    famille = "teleop"
    parametres = {
        "articulation": Parametre("joint_1.position", "", "Articulation pilotée"),
        "pas": Parametre(5.0, "°", "Pas"),
    }

    def demarrer(self, robot):
        # robot.actions : les actions acceptées par le robot (noms, unités, plages)
        # robot.clavier : get_key() renvoie la prochaine touche pressée (ou None), is_pressed(Key.Left) si elle est enfoncée
        self.consigne = None
        self.clavier = robot.clavier

    def action(self, observation):
        if self.consigne is None:
            # on part de la position mesurée
            self.consigne = observation.get(self.articulation, 0.0)
        touche = self.clavier.get_key()
        if touche == Key.Esc:
            self.terminer()
            return None
        if touche == Key.Left:
            self.consigne -= self.pas
        elif touche == Key.Right:
            self.consigne += self.pas
        else:
            return None
        return {self.articulation: self.consigne}
