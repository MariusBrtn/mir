"""
Exemple d'analyse écrite par l'utilisateur.
Chaque fichier .py de ce dossier peut définir une ou plusieurs analyses : MIR les trouve tout seul.
"""
import numpy as np
from mir_robot.essai import Analyse


class EcartDeSuivi(Analyse):
    nom = "Écart de suivi"
    description = "Écart entre la consigne et la mesure : utile pour une rampe ou un sinus."

    def analyser(self, essai):
        # essai.t : temps (s) ; essai.consigne ; essai.mesure : la grandeur sollicitée ; essai["joint_1.current"]...
        ecart = essai.consigne - essai.mesure
        unite = essai.unite(essai.actionneur)
        return {
            "Écart maximal": (float(np.max(np.abs(ecart))), unite),
            "Écart moyen": (float(np.mean(np.abs(ecart))), unite),
        }
