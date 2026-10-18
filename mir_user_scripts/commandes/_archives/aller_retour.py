"""
Exemple de commande écrite par l'utilisateur.
Chaque fichier .py de ce dossier peut définir une ou plusieurs commandes : MIR les trouve tout seul.
"""
import time
from mir_robot.commande import Commande


class AllerRetour(Commande):
    nom = "Aller-retour"
    description = "Toutes les articulations en position vont de -30° à +30° et reviennent, toutes les 2 s"

    def demarrer(self, robot):
        # robot.actions : les actions que le robot accepte, ex. "joint_1.position"
        self.articulations = [nom for nom in robot.actions if nom.endswith(".position")]
        self.debut = time.perf_counter()

    def action(self, observation):
        # observation : les mesures du robot, ex. observation["joint_1.position"]
        t = time.perf_counter() - self.debut
        cible = 30.0 if int(t / 2) % 2 == 0 else -30.0
        return {nom: cible for nom in self.articulations}
