"""
Essais : solliciter un actionneur (échelon, rampe, sinus...), enregistrer sa réponse, puis l'analyser.

    from mir_robot.essai import lancer_essai
    from mir_robot.commandes.sollicitations import Echelon   # ou via decouvrir_commandes(familles=("essai",))

    essai = lancer_essai(robot, Echelon(actionneur="joint_1.position", initiale=0, finale=30, duree=3))
    essai.t, essai.consigne, essai.mesure, essai["joint_1.current"]
    essai.enregistrer("mon_essai.npz") ; Essai.charger("mon_essai.npz")

Le même essai fonctionne sur le robot réel et sur le robot simulé : on peut comparer les deux réponses.
Les conditions de l'essai (robot, réel ou simulé, sollicitation, réglages du moteur, date) sont enregistrées avec
les mesures.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any, Callable
import numpy as np
from mir_devices.mir_device import ObservablePropertyFloat, ObservablePropertyConverter
from mir_utils.metrics import DataRecorder
from mir_utils.period_waiters import PeriodWaiterExact
from mir_robot.commande import Commande, Parametre, verifier_action

DOSSIER_ANALYSES_FOURNIES = Path(__file__).parent / "analyses"
DOSSIER_ANALYSES_UTILISATEUR = Path(__file__).parent.parent / "mir_user_scripts" / "analyses"
CONSIGNE = "consigne"           # nom de la série de la consigne dans un essai
PREPARATION_MAX_S = 3.0         # durée maximale pour amener l'actionneur à sa consigne initiale
PREPARATION_TOLERANCE = 1.0     # écart accepté avec la consigne initiale (unité de l'actionneur)


class Sollicitation(Commande):
    """Commande d'essai : la consigne d'UN actionneur est une fonction du temps, consigne(t), sur une durée donnée.
    Les sollicitations fournies sont dans mir_robot/commandes/sollicitations.py ; pour en écrire une, définir
    consigne(self, t) et, si besoin, des paramètres en plus de ceux-ci."""
    famille = "essai"
    parametres = {
        "duree": Parametre(3.0, "s", "Durée de l'essai"),
    }

    def __init__(self, actionneur: str | None = None, **valeurs: Any):
        super().__init__(**valeurs)
        self.actionneur = actionneur     # nom de l'action sollicitée, ex. "joint_1.position"

    def consigne(self, t: float) -> float:
        """Consigne à l'instant t (en s, 0 au début de l'essai)."""
        raise NotImplementedError(f"{type(self).__name__} doit définir la méthode consigne(self, t)")

    # utilisable aussi comme une commande ordinaire (monitor, executer)
    def demarrer(self, robot):
        if self.actionneur is None:
            self.actionneur = next(iter(robot.actions))
        self._debut = time.perf_counter()

    def action(self, observation):
        t = time.perf_counter() - self._debut
        if t >= self.duree:
            self.terminer()
        return {self.actionneur: self.consigne(min(t, self.duree))}

    def decrire(self) -> dict[str, Any]:
        """Description de la sollicitation, enregistrée avec l'essai."""
        return {"nom": self.nom_affiche(), "actionneur": self.actionneur,
                "parametres": {nom: getattr(self, nom) for nom in self.parametres}}


class Essai:
    """Résultat d'un essai : séries temporelles (mesures et consigne) et conditions."""

    def __init__(self, series: dict[str, np.ndarray], conditions: dict[str, Any], proprietes: dict[str, dict[str, Any]]):
        self.t: np.ndarray = series.pop("__timestamps__")
        self._series = series
        self.conditions = conditions
        self.proprietes = proprietes            # unité, plage... de chaque série
        self.chemin: Path | None = None

    @property
    def actionneur(self) -> str:
        return self.conditions.get("sollicitation", {}).get("actionneur", "")

    @property
    def consigne(self) -> np.ndarray:
        return self._series[CONSIGNE]

    @property
    def mesure(self) -> np.ndarray | None:
        """Mesure de la grandeur sollicitée (ex. joint_1.position pour une consigne joint_1.position), si observée."""
        return self._series.get(self.actionneur)

    @property
    def noms(self) -> list[str]:
        return list(self._series)

    def unite(self, nom: str) -> str:
        return self.proprietes.get(nom, {}).get("unit", "")

    def __getitem__(self, nom: str) -> np.ndarray:
        return self._series[nom]

    def __contains__(self, nom: str) -> bool:
        return nom in self._series

    def titre(self) -> str:
        c = self.conditions
        mode = "simulé" if c.get("simulation") else "réel"
        return f"{c.get('date', '')} · {c.get('sollicitation', {}).get('nom', '')} · {self.actionneur} · {mode}"

    def enregistrer(self, chemin: str | Path) -> None:
        recorder = DataRecorder({nom: {**self.proprietes.get(nom, {}), "type": "float",
                                       "dtype": self._series[nom].dtype} for nom in self._series}, len(self.t))
        for i in range(len(self.t)):
            recorder.append({nom: serie[i] for nom, serie in self._series.items()})
        recorder._data["__timestamps__"][: len(self.t)] = self.t
        recorder.save(chemin, self.conditions)
        self.chemin = Path(chemin)

    @staticmethod
    def charger(chemin: str | Path) -> Essai:
        series, proprietes = DataRecorder.load(chemin)
        essai = Essai(series, DataRecorder.load_conditions(chemin), proprietes)
        essai.chemin = Path(chemin)
        return essai


def lancer_essai(robot, sollicitation: Sollicitation, fps: float = 50, observations: list[str] | None = None,
                 conditions: dict[str, Any] | None = None,
                 progression: Callable[[float, dict[str, Any], float], None] | None = None,
                 arret: Callable[[], bool] | None = None) -> Essai:
    """Fait l'essai sur un robot connecté et configuré (réel ou simulé).
    1. préparation : l'actionneur est amené à la consigne initiale (non enregistré) ;
    2. essai : la consigne suit la sollicitation pendant sa durée ; consigne et mesures sont enregistrées.
    observations : grandeurs enregistrées (par défaut, toutes celles du moteur sollicité) ;
    progression(t, observation, consigne) : appelée à chaque mesure ; arret() : True pour interrompre l'essai."""
    actions = robot.action_features
    actionneur = sollicitation.actionneur
    if actionneur not in actions:
        raise KeyError(f"actionneur inconnu : {actionneur}. Actionneurs possibles : {', '.join(actions)}")
    observables = robot.get_observables()
    if observations is None:
        moteur = actionneur.split(".")[0]
        observations = [nom for nom in observables if nom.split(".")[0] == moteur]
    floats = {nom: observables[nom] for nom in observations if isinstance(observables.get(nom), ObservablePropertyFloat)}
    robot.enable_observations(floats)

    proprietes = ObservablePropertyConverter.observables_to_dict(floats)
    unite = actions[actionneur].get_unit()
    proprietes[CONSIGNE] = {"type": "float", "dtype": np.dtype(np.float32), "unit": unite,
                            "min_value": None, "max_value": None}
    duree = float(sollicitation.duree)

    # 1. préparation : rejoindre la consigne initiale et attendre la stabilisation
    initiale = verifier_action({actionneur: sollicitation.consigne(0.0)}, actions)
    robot.send_action(initiale)
    debut = time.perf_counter()
    while actionneur in floats and time.perf_counter() - debut < PREPARATION_MAX_S:
        if arret is not None and arret():
            break
        if abs(robot.get_observation()[actionneur] - initiale[actionneur]) < PREPARATION_TOLERANCE:
            break
        time.sleep(0.02)

    # 2. essai
    recorder = DataRecorder(proprietes, int(duree * fps * 1.2) + 10)
    periode = PeriodWaiterExact(1 / fps)
    recorder.start()
    debut = time.perf_counter()
    try:
        while True:
            t = time.perf_counter() - debut
            if t > duree or (arret is not None and arret()):
                break
            consigne = sollicitation.consigne(t)
            robot.send_action(verifier_action({actionneur: consigne}, actions))
            observation = robot.get_observation()
            recorder.append({**observation, CONSIGNE: consigne})
            if progression is not None:
                progression(t, observation, consigne)
            periode.wait()
    finally:
        robot.motors_stop()

    series = {nom: recorder.get(nom).copy() for nom in proprietes}
    series["__timestamps__"] = recorder.get("__timestamps__").copy()
    tout = {"date": time.strftime("%Y-%m-%d %H:%M:%S"), "fps": fps, "sollicitation": sollicitation.decrire()}
    tout.update(conditions or {})
    return Essai(series, tout, {nom: {k: v for k, v in p.items() if k != "dtype"} for nom, p in proprietes.items()})


class Analyse:
    """Classe de base des analyses d'essai. MIR les trouve dans mir_robot/analyses/ (fournies) et
    mir_user_scripts/analyses/ (utilisateur).

        class MonAnalyse(Analyse):
            nom = "Mon analyse"
            def analyser(self, essai):
                return {"Valeur finale": (essai.mesure[-1], "°")}     # nom : valeur, ou (valeur, unité)
    """
    nom: str = ""
    description: str = ""

    def analyser(self, essai: Essai) -> dict[str, Any]:
        raise NotImplementedError(f"{type(self).__name__} doit définir la méthode analyser(self, essai)")

    def reperes(self, essai: Essai, resultats: dict[str, Any]) -> list[tuple[str, float]]:
        """Facultatif : instants remarquables à tracer sur les courbes, [(libellé, t en s)]."""
        return []

    @classmethod
    def nom_affiche(cls) -> str:
        return cls.nom or cls.__name__


def decouvrir_analyses(dossiers: list[Path] | None = None):
    """Analyses disponibles (fournies et utilisateur), même fonctionnement que decouvrir_commandes."""
    from mir_robot.commande import decouvrir_commandes
    return decouvrir_commandes(dossiers or [DOSSIER_ANALYSES_FOURNIES, DOSSIER_ANALYSES_UTILISATEUR], classe_base=Analyse)
