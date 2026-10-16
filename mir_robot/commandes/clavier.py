from mir_robot.commande import Commande, Parametre
from mir_utils.keyboard_listener import Key

CHIFFRES = [Key.Digit1, Key.Digit2, Key.Digit3, Key.Digit4, Key.Digit5, Key.Digit6, Key.Digit7, Key.Digit8, Key.Digit9]


class Clavier(Commande):
    nom = "Clavier"
    description = ("1 à 9 : choisir l'actionneur · ← → : diminuer/augmenter la consigne · "
                   "espace : consigne de vitesse à 0 · Échap : terminer")
    famille = "teleop"
    parametres = {
        "pas_position": Parametre(5.0, "°", "Pas en position"),
        "pas_vitesse": Parametre(20.0, "°/s", "Pas en vitesse"),
    }

    def demarrer(self, robot):
        self.actions = robot.actions
        self.noms = list(robot.actions)
        if not self.noms:
            raise ValueError("le robot n'a aucune action")
        self.choisi = self.noms[0]
        self.consignes = {}
        self.clavier = robot.clavier     # touches pressées (fenêtre de l'application, ou clavier en script)

    def action(self, observation):
        touche = self.clavier.get_key()
        if touche is None:
            return None
        if touche == Key.Esc:
            self.terminer()
            return None
        if touche in CHIFFRES:
            i = CHIFFRES.index(touche)
            if i < len(self.noms):
                self.choisi = self.noms[i]
            return None

        nom = self.choisi
        en_vitesse = nom.endswith(".velocity")
        if nom not in self.consignes:
            # on part de la valeur mesurée si elle est observée, sinon de 0
            self.consignes[nom] = 0.0 if en_vitesse else observation.get(nom, 0.0)
        pas = self.pas_vitesse if en_vitesse else self.pas_position
        if touche == Key.Left:
            self.consignes[nom] -= pas
        elif touche == Key.Right:
            self.consignes[nom] += pas
        elif touche == Key.Space and en_vitesse:
            self.consignes[nom] = 0.0
        else:
            return None
        plage = self.actions[nom].get_range()
        if plage is not None:
            # la consigne reste dans la plage, sinon il faudrait « revenir » avant que le moteur ne bouge
            self.consignes[nom] = min(max(self.consignes[nom], plage[0]), plage[1])
        return {nom: self.consignes[nom]}
