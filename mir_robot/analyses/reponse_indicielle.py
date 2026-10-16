import numpy as np
from mir_robot.essai import Analyse


class ReponseIndicielle(Analyse):
    nom = "Réponse indicielle"
    description = ("Pour un échelon : valeur finale, erreur statique, dépassement, temps de montée (10 % → 90 %) "
                   "et temps de réponse à 5 %, mesurés depuis l'instant de l'échelon.")

    def analyser(self, essai):
        t, c, y = essai.t, essai.consigne, essai.mesure
        if y is None:
            raise ValueError(f"la grandeur sollicitée ({essai.actionneur}) n'a pas été mesurée")
        sauts = np.flatnonzero(np.abs(np.diff(c)) > 1e-9)
        if len(sauts) == 0:
            raise ValueError("la consigne ne contient pas d'échelon")
        i0 = sauts[0] + 1                       # premier échantillon après l'échelon
        t0, c_finale = float(t[i0]), float(c[i0])
        y0 = float(y[i0 - 1])
        fin = y[int(len(y) * 0.9):]             # 10 % finaux : régime établi
        y_finale = float(np.mean(fin))
        delta = y_finale - y0
        unite = essai.unite(essai.actionneur)
        resultats = {
            "Instant de l'échelon": (t0, "s"),
            "Valeur finale": (y_finale, unite),
            "Erreur statique": (c_finale - y_finale, unite),
        }
        if abs(delta) < 1e-6:
            return resultats
        apres_t, apres_y = t[i0:] - t0, (y[i0:] - y0) / delta      # réponse réduite : 0 → 1
        resultats["Dépassement"] = (max(0.0, float(np.max(apres_y)) - 1.0) * 100, "%")
        t10, t90 = _premier_passage(apres_t, apres_y, 0.1), _premier_passage(apres_t, apres_y, 0.9)
        if t10 is not None and t90 is not None:
            resultats["Temps de montée (10-90 %)"] = (t90 - t10, "s")
        hors_bande = np.flatnonzero(np.abs(apres_y - 1.0) > 0.05)
        if len(hors_bande) == 0:
            resultats["Temps de réponse à 5 %"] = (0.0, "s")
        elif hors_bande[-1] + 1 < len(apres_t):
            resultats["Temps de réponse à 5 %"] = (float(apres_t[hors_bande[-1] + 1]), "s")
        else:
            resultats["Temps de réponse à 5 %"] = ("non atteint pendant l'essai", "")
        return resultats

    def reperes(self, essai, resultats):
        t0 = resultats["Instant de l'échelon"][0]
        reperes = [("échelon", t0)]
        t5 = resultats.get("Temps de réponse à 5 %", (None,))[0]
        if isinstance(t5, float):
            reperes.append(("t5%", t0 + t5))
        return reperes


def _premier_passage(t, y, seuil):
    indices = np.flatnonzero(y >= seuil)
    return float(t[indices[0]]) if len(indices) else None
