"""Sollicitations fournies pour les essais : la consigne d'un actionneur en fonction du temps."""
import math
from mir_robot.commande import Parametre
from mir_robot.essai import Sollicitation


class Echelon(Sollicitation):
    nom = "Échelon"
    description = "La consigne passe brusquement de la valeur initiale à la valeur finale."
    parametres = {
        "initiale": Parametre(0.0, "", "Valeur initiale"),
        "finale": Parametre(30.0, "", "Valeur finale"),
        "instant": Parametre(0.5, "s", "Instant de l'échelon"),
        **Sollicitation.parametres,
    }

    def consigne(self, t):
        return self.initiale if t < self.instant else self.finale


class Rampe(Sollicitation):
    nom = "Rampe"
    description = "La consigne passe de la valeur initiale à la valeur finale à vitesse constante."
    parametres = {
        "initiale": Parametre(0.0, "", "Valeur initiale"),
        "finale": Parametre(30.0, "", "Valeur finale"),
        "instant": Parametre(0.5, "s", "Début de la rampe"),
        "montee": Parametre(1.0, "s", "Durée de la montée"),
        **Sollicitation.parametres,
    }

    def consigne(self, t):
        if t < self.instant:
            return self.initiale
        avancement = min(1.0, (t - self.instant) / self.montee) if self.montee > 0 else 1.0
        return self.initiale + avancement * (self.finale - self.initiale)


class Sinus(Sollicitation):
    nom = "Sinus"
    description = "La consigne oscille autour d'une valeur centrale."
    parametres = {
        "centre": Parametre(0.0, "", "Valeur centrale"),
        "amplitude": Parametre(20.0, "", "Amplitude"),
        "periode": Parametre(2.0, "s", "Période"),
        **Sollicitation.parametres,
        "duree": Parametre(6.0, "s", "Durée de l'essai"),
    }

    def consigne(self, t):
        return self.centre + self.amplitude * math.sin(2 * math.pi * t / self.periode)


class Creneau(Sollicitation):
    nom = "Créneau"
    description = "La consigne alterne entre deux valeurs (échelons montants et descendants répétés)."
    parametres = {
        "basse": Parametre(0.0, "", "Valeur basse"),
        "haute": Parametre(30.0, "", "Valeur haute"),
        "periode": Parametre(2.0, "s", "Période"),
        **Sollicitation.parametres,
        "duree": Parametre(6.0, "s", "Durée de l'essai"),
    }

    def consigne(self, t):
        return self.haute if (t % self.periode) >= self.periode / 2 else self.basse
