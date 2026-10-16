"""
Étape Piloter → Essais : solliciter un actionneur, enregistrer et analyser sa réponse, comparer plusieurs essais
(par exemple le même essai sur le robot réel et sur le robot simulé).
"""
from __future__ import annotations
import time
import traceback
from enum import Enum, auto
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from loguru import logger
from PySide6.QtCore import Signal
from mir_devices.mir_device import ObservablePropertyFloat
from mir_robot.mir_robot import mirRobot
from mir_robot.commande import CommandesDisponibles, decouvrir_commandes
from mir_robot.essai import Essai, Sollicitation, decouvrir_analyses, lancer_essai
from mir_utils.concurrency import BackgroundWorker
from mir_utils.ui.view_model_base import VMAction, ViewModelBase

DOSSIER_ESSAIS = Path(__file__).parent.parent.parent / "data" / "essais"
# réglages du moteur modifiables dans un essai : attribut de mirMotor -> (libellé, min, max)
REGLAGES_MOTEUR = {
    "P": ("P", 0, 255),
    "I": ("I", 0, 255),
    "D": ("D", 0, 255),
    "position_mode_velocity": ("Vitesse max (unités STS)", 0, 3000),
    "torque_limit": ("Couple max (‰)", 0, 1000),
}


class EssaisVMAction(Enum):
    LANCER = auto()
    ARRETER = auto()
    OUVRIR = auto()


class EssaisViewModel(ViewModelBase[EssaisVMAction]):
    robot_changed = Signal()                 # actionneurs et grandeurs disponibles changés
    briques_changed = Signal()               # sollicitations ou analyses relues
    essais_changed = Signal()                # liste des essais changée
    essai_termine = Signal(object)           # Essai
    busy_state_changed = Signal(bool)
    _essai_echoue = Signal(str)

    def __init__(self, dialog_provider, motor_settings: Callable[[str], dict[str, int]] | None = None,
                 apply_motor_settings: Callable[[str, dict[str, int]], None] | None = None,
                 conditions: Callable[[], dict[str, Any]] | None = None,
                 other_busy: Callable[[], bool] | None = None, sim_world: Callable[[], Any] | None = None):
        super().__init__(dialog_provider)
        self._actions[EssaisVMAction.LANCER] = VMAction("Lancer l'essai", "Amener l'actionneur à sa valeur initiale puis appliquer la sollicitation")
        self._actions[EssaisVMAction.ARRETER] = VMAction("Arrêter", "Interrompre l'essai en cours")
        self._actions[EssaisVMAction.OUVRIR] = VMAction("Ouvrir un essai...", "Ajouter à la liste un essai enregistré", enabled=True)
        self._motor_settings = motor_settings or (lambda motor: {})
        self._apply_motor_settings = apply_motor_settings
        self._conditions = conditions or (lambda: {})
        self._other_busy = other_busy or (lambda: False)
        self._sim_world = sim_world or (lambda: None)
        self._robot: mirRobot | None = None
        self._worker = BackgroundWorker()
        self._running = False
        self._stop = False
        self._live_lock = Lock()
        self._live: dict[str, list[float]] = {}
        self.sollicitations = CommandesDisponibles()
        self.analyses = CommandesDisponibles()
        self.essais: list[Essai] = []
        self.refresh_briques()
        self._essai_echoue.connect(lambda tb: self._dialogProvider.error("L'essai a échoué", tb))

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, tb):
        self._worker.shutdown()

    # ------------------------------------------------------------------ robot
    def connect_to_robot(self, robot: mirRobot):
        self._robot = robot
        self._update_actions()
        self.robot_changed.emit()

    def disconnect_from_robot(self):
        if self._running:
            raise RuntimeError("Un essai est en cours")
        self._robot = None
        self._update_actions()
        self.robot_changed.emit()

    def is_simulation(self) -> bool:
        return bool(self._conditions().get("simulation"))

    def sim_world(self):
        """Monde simulé à afficher en 3D (None avec le robot réel)."""
        return self._sim_world() if self.is_simulation() else None

    def actionneurs(self) -> dict[str, str]:
        """Actionneurs sollicitables : nom de l'action -> unité."""
        if self._robot is None:
            return {}
        return {nom: action.get_unit() for nom, action in self._robot.action_features.items()}

    def grandeurs(self, actionneur: str) -> list[str]:
        """Grandeurs mesurables (scalaires) du moteur de l'actionneur."""
        if self._robot is None or not actionneur:
            return []
        moteur = actionneur.split(".")[0]
        return [nom for nom, prop in self._robot.get_observables().items()
                if isinstance(prop, ObservablePropertyFloat) and nom.split(".")[0] == moteur]

    def plage(self, actionneur: str) -> tuple[float, float] | None:
        if self._robot is None or actionneur not in self._robot.action_features:
            return None
        return self._robot.action_features[actionneur].get_range()

    def reglages(self, actionneur: str) -> dict[str, int]:
        return self._motor_settings(actionneur.split(".")[0]) if actionneur else {}

    # ------------------------------------------------------------------ briques
    def refresh_briques(self):
        self.sollicitations = decouvrir_commandes(familles=("essai",))
        self.analyses = decouvrir_analyses()
        erreurs = {**self.sollicitations.erreurs, **self.analyses.erreurs}
        if erreurs:
            details = "\r\n\r\n".join(f"{fichier} :\r\n{erreur}" for fichier, erreur in erreurs.items())
            self._dialogProvider.warning("Fichiers non chargés", details)
        self.briques_changed.emit()

    # ------------------------------------------------------------------ essai
    def lancer(self, sollicitation_nom: str, actionneur: str, parametres: dict[str, float],
               grandeurs: list[str], fps: int, reglages: dict[str, int] | None = None):
        if self._robot is None or self._running:
            return
        if self._other_busy():
            self._dialogProvider.information("Essai impossible", "Arrêtez d'abord les mesures en cours (Téléopération).")
            return
        moteur = actionneur.split(".")[0]
        if reglages and reglages != self.reglages(actionneur) and self._apply_motor_settings is not None:
            # réglages modifiés : appliqués au moteur (et à la configuration) avant l'essai
            self._apply_motor_settings(moteur, reglages)
            if self._robot is None:
                return
        try:
            sollicitation: Sollicitation = self.sollicitations.commandes[sollicitation_nom](actionneur=actionneur, **parametres)
        except Exception as e:
            self._dialogProvider.exception(e, "Impossible de créer la sollicitation")
            return
        if self.is_simulation():
            # en simulation, on visualise le mouvement : les mesures se font sur le robot réel
            grandeurs = [actionneur] if actionneur in self.grandeurs(actionneur) else []
        conditions = {**self._conditions(), "reglages_moteur": self.reglages(actionneur), "grandeurs": grandeurs}
        with self._live_lock:
            self._live = {"t": [], "consigne": [], **{nom: [] for nom in grandeurs}}
        self._stop = False
        self._running = True
        self._update_actions()
        self.busy_state_changed.emit(True)
        robot = self._robot
        self._worker.run(lambda: lancer_essai(robot, sollicitation, fps=fps, observations=grandeurs,
                                              conditions=conditions, progression=self._progression,
                                              arret=lambda: self._stop),
                         self._on_termine, self._on_echec, self)

    def arreter(self):
        self._stop = True

    def is_running(self) -> bool:
        return self._running

    def _progression(self, t: float, observation: dict[str, Any], consigne: float):
        with self._live_lock:
            self._live["t"].append(t)
            self._live["consigne"].append(consigne)
            for nom, valeurs in self._live.items():
                if nom not in ("t", "consigne") and nom in observation:
                    valeurs.append(float(observation[nom]))

    def live_data(self) -> dict[str, list[float]]:
        """Mesures de l'essai en cours (copie), pour l'affichage pendant l'essai."""
        with self._live_lock:
            return {nom: list(valeurs) for nom, valeurs in self._live.items()}

    def _fin(self):
        self._running = False
        self._update_actions()
        self.busy_state_changed.emit(False)

    def _on_termine(self, essai: Essai):
        self._fin()
        if essai.conditions.get("simulation"):
            return      # pas de mesures en simulation : rien à enregistrer ni à analyser
        try:
            DOSSIER_ESSAIS.mkdir(parents=True, exist_ok=True)
            mode = "simule" if essai.conditions.get("simulation") else "reel"
            nom = f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{essai.conditions['sollicitation']['nom']}_{essai.actionneur}_{mode}"
            essai.enregistrer(DOSSIER_ESSAIS / f"{nom}.npz")
        except Exception as e:
            logger.error(f"essai non enregistré : {e}")
            self._dialogProvider.exception(e, "L'essai n'a pas pu être enregistré")
        self.essais.append(essai)
        self.essais_changed.emit()
        self.essai_termine.emit(essai)

    def _on_echec(self, error: Exception):
        self._fin()
        self._essai_echoue.emit("".join(traceback.format_exception(error)))

    def _update_actions(self):
        self._actions[EssaisVMAction.LANCER].set_enabled(self._robot is not None and not self._running)
        self._actions[EssaisVMAction.ARRETER].set_enabled(self._running)

    # ------------------------------------------------------------------ liste des essais
    def ouvrir(self):
        chemin = self._dialogProvider.open_file("Ouvrir un essai", str(DOSSIER_ESSAIS), "Essai MIR (*.npz)")
        if not chemin:
            return
        try:
            self.essais.append(Essai.charger(chemin))
        except Exception as e:
            self._dialogProvider.exception(e, "Impossible d'ouvrir l'essai")
            return
        self.essais_changed.emit()

    def retirer(self, index: int):
        if 0 <= index < len(self.essais):
            del self.essais[index]
            self.essais_changed.emit()

    def analyser(self, analyse_nom: str, essai: Essai) -> tuple[dict[str, Any], list[tuple[str, float]]] | None:
        """Résultats et repères de l'analyse ; None (et message) si elle échoue."""
        classe = self.analyses.commandes.get(analyse_nom)
        if classe is None:
            return None
        try:
            analyse = classe()
            resultats = analyse.analyser(essai)
            return resultats, analyse.reperes(essai, resultats)
        except Exception as e:
            self._dialogProvider.information(f"Analyse « {analyse_nom} » impossible", str(e))
            return None
