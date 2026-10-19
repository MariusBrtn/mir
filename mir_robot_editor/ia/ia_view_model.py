"""
Piloter → IA : un modèle entraîné (étape « Entraîner un modèle ») pilote le robot, réel ou simulé.
Même boucle que les autres modalités : à chaque tour, observation -> modèle -> action, cadencée par un PeriodWaiter ;
une seule activité à la fois sur le robot, arrêt d'urgence commun.
"""
from __future__ import annotations
import time
from enum import Enum
from pathlib import Path
from typing import Any
import numpy as np
from loguru import logger
from PySide6.QtCore import Signal
from mir_robot.commande import ExecutionCommande
from mir_robot.mir_robot import mirRobot
from mir_robot.training import load_policy, model_info, trained_models
from mir_utils.concurrency import BackgroundWorker
from mir_utils.keyboard_listener import KeyQueue
from mir_utils.period_waiters import PeriodWaiterSafeForJitter
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import ViewModelBase

AFFICHAGE_HZ = 15           # rafraîchissement de la vue en direct (ce que voit le modèle)


class IAVMAction(Enum):
    pass


class IAViewModel(ViewModelBase[IAVMAction]):
    busy_state_changed = Signal(bool)
    robot_changed = Signal()
    modeles_changed = Signal()
    observation_ready = Signal(dict)            # vue en direct
    etat_changed = Signal(str)                  # « chargement du modèle », « en cours : 3,2 s », temps d'inférence...
    _fin_boucle = Signal(str)                   # émis depuis la boucle : message de fin

    def __init__(self, dialog_provider: IDialogProvider, other_busy=None, sim_world=None, replacer_scene=None):
        super().__init__(dialog_provider)
        self._other_busy = other_busy or (lambda: False)
        self._sim_world = sim_world or (lambda: None)
        self._replacer_scene = replacer_scene or (lambda: None)
        self._robot: mirRobot | None = None
        self._dossier_robot: Path | None = None
        self.keyboard = KeyQueue()
        self._boucle = BackgroundWorker()
        self._en_cours = False
        self._arret = False
        self._urgence = False
        self._fin_boucle.connect(self._on_fin_boucle)

    # ------------------------------------------------------------------ robot et modèles
    def set_other_busy(self, other_busy):
        self._other_busy = other_busy

    def connect_to_robot(self, robot: mirRobot):
        self._robot = robot
        self.robot_changed.emit()

    def disconnect_from_robot(self):
        if self._en_cours:
            raise RuntimeError("Un modèle pilote le robot")
        self._robot = None
        self.robot_changed.emit()

    def has_robot(self) -> bool:
        return self._robot is not None

    def sim_world(self):
        return self._sim_world()

    def set_dossier_robot(self, dossier: Path | None):
        self._dossier_robot = dossier
        self.modeles_changed.emit()

    def modeles(self) -> list[dict[str, Any]]:
        return [model_info(d) for d in trained_models(self._dossier_robot)] if self._dossier_robot is not None else []

    # ------------------------------------------------------------------ pilotage
    def is_running(self) -> bool:
        return self._en_cours

    def demarrer(self, dossier_modele: str, fps: float, duree_s: float | None, replacer: bool):
        """Le modèle pilote le robot à fps Hz pendant duree_s secondes (None : jusqu'à Arrêter)."""
        if self._en_cours:
            return
        if self._robot is None:
            self._dialogProvider.information("IA", "Pas de robot : connectez le robot réel, ou utilisez le robot simulé.")
            return
        if self._other_busy():
            self._dialogProvider.information("IA", "Arrêtez d'abord le mouvement en cours.")
            return
        if replacer:
            self._replacer_scene()
        self._en_cours, self._arret, self._urgence = True, False, False
        self.busy_state_changed.emit(True)
        self._boucle.run(lambda: self._tourner(Path(dossier_modele), fps, duree_s), lambda _: None, lambda _: None)

    def arreter(self):
        self._arret = True

    def arret_urgence(self):
        self._urgence = True
        self._arret = True
        if self._robot is not None:
            try:
                self._robot.motors_emergency_stop()
            except Exception as e:
                logger.error(f"arrêt d'urgence : {e}")

    def _tourner(self, dossier: Path, fps: float, duree_s: float | None):
        """Boucle (thread de fond) : chargement du modèle, puis observation -> modèle -> action à chaque tour."""
        robot = self._robot
        message = ""
        execution = None
        try:
            self.etat_changed.emit("Chargement du modèle…")
            politique = load_policy(dossier)
            # seules les grandeurs utiles au modèle sont lues (une caméra lue pour rien ralentirait la boucle)
            observables = robot.get_observables()
            utiles = set(politique.observations()) | {n for n in observables if n.endswith(".position")}
            robot.enable_observations_by_name([n for n in observables if n in utiles])
            execution = ExecutionCommande(robot, politique, fps, clavier=self.keyboard)
            attente = PeriodWaiterSafeForJitter(1 / fps)
            debut = time.perf_counter()
            dernier_affichage = 0.0
            inferences: list[float] = []
            while not self._arret:
                maintenant = time.perf_counter()
                if duree_s is not None and maintenant - debut >= duree_s:
                    break
                observation = robot.get_observation()
                t0 = time.perf_counter()
                if not execution.tour(observation):
                    break
                inferences.append(time.perf_counter() - t0)
                if maintenant - dernier_affichage >= 1 / AFFICHAGE_HZ:
                    dernier_affichage = maintenant
                    self.observation_ready.emit(observation)
                    ms = np.median(inferences[-50:]) * 1000
                    self.etat_changed.emit(f"En cours : {maintenant - debut:.1f} s · inférence {ms:.0f} ms "
                                           f"(période {1000 / fps:.0f} ms)")
                attente.wait()
            duree = time.perf_counter() - debut
            if inferences:
                message = (f"Terminé au bout de {duree:.1f} s · inférence médiane "
                           f"{np.median(inferences) * 1000:.0f} ms, max {np.max(inferences) * 1000:.0f} ms")
        except Exception as e:
            logger.exception("IA")
            message = f"Erreur : {type(e).__name__} : {e}"
        finally:
            if execution is not None:
                try:
                    execution.arreter(arreter_moteurs=not self._urgence)
                except Exception as e:
                    message = message or f"Erreur à l'arrêt : {e}"
            if self._urgence:
                message = "Arrêt d'urgence : couple des moteurs coupé"
            self._fin_boucle.emit(message)

    def _on_fin_boucle(self, message: str):
        self._en_cours = False
        self.etat_changed.emit(message)
        self.busy_state_changed.emit(False)
        if message.startswith("Erreur"):
            self._dialogProvider.information("IA", message)

    def quit(self):
        self._arret = True
