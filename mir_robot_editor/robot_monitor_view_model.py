from loguru import logger
import traceback
from enum import Enum, auto
from typing import Any
import time
from pathlib import Path
from threading import Lock
from PySide6.QtCore import Signal
from mir_devices.mir_device import DeviceAction, ObservablePropertyFloat, ObservablePropertyConverter
from mir_utils.metrics import SimpleMovingAverage, Stats, DataRecorder
from mir_utils.period_waiters import PeriodWaiterExact
from mir_utils.concurrency import BackgroundWorker
from mir_robot.mir_robot import mirRobot
from mir_robot.commande import Commande, CommandesDisponibles, ExecutionCommande, decouvrir_commandes, verifier_action
from mir_utils.keyboard_listener import KeyQueue
from mir_devices.mir_device import ActionValue
from mir_utils.ui.view_model_base import VMAction, ViewModelBase

class RobotMonitorVMAction(Enum):
    APPLY = auto()
    START = auto()
    STOP = auto()
    ACTION = auto()
    COMMANDE_START = auto()
    COMMANDE_STOP = auto()

class FpsStats:
    def __init__(self, parent):
        self.parent = parent
        self.avg = SimpleMovingAverage(50)
        self.last_time_sent_stats = 0.0
        self.stats = Stats()

    def update(self, t0: float, t:float):
        self.avg.add(1/(t-t0))
        self.stats.add(t-t0)
        if (t - self.last_time_sent_stats) >= 0.1:  # Envoyer les statistiques toutes les secondes
            self.parent.fps_changed.emit(self.avg.average(), self.stats.get())
            self.last_time_sent_stats = t

class RobotMonitorViewModel(ViewModelBase[RobotMonitorVMAction]):
    observations_list_changed = Signal(list)
    actions_list_changed = Signal(dict)
    observation_ready = Signal(dict) #clé, dictionnaire d'observations, timestamp en sec
    observations_accepted = Signal(dict)
    busy_state_changed = Signal(bool)
    fps_changed = Signal(float,dict)
    commandes_list_changed = Signal(list)       # [(nom, description)]
    commande_running_changed = Signal(bool)
    _commande_failed = Signal(str)              # émis depuis la boucle, traité dans le thread de l'interface

    def __init__(self, dialog_provider):
        super().__init__(dialog_provider)
        self._observation_recorder : DataRecorder | None = None
        self._worker = BackgroundWorker()
        self._last_action_lock = Lock()
        self._last_action : dict[str, Any ] | None = None
        self._stop_loop = False
        self._robot: mirRobot | None = None
        self._is_loop_running = False
        self._actions[RobotMonitorVMAction.APPLY] = VMAction("Appliquer", "Appliquer les observations à activer")
        self._actions[RobotMonitorVMAction.START] = VMAction("Démarrer les observations", "Démarrer les observations")
        self._actions[RobotMonitorVMAction.STOP] = VMAction("Arrêter les observations", "Arrêter les observations")
        self._actions[RobotMonitorVMAction.ACTION] = VMAction("", "")
        self._actions[RobotMonitorVMAction.COMMANDE_START] = VMAction("Démarrer la commande", "Démarrer la commande choisie")
        self._actions[RobotMonitorVMAction.COMMANDE_STOP] = VMAction("Arrêter la commande", "Arrêter la commande en cours")
        # commandes : None = consigne manuelle
        self._commandes = CommandesDisponibles()
        self._commande_choisie: str | None = None
        self._commande_lock = Lock()
        self._commande_a_demarrer: Commande | None = None
        self._arreter_commande = False
        self._urgence = False
        self._execution: ExecutionCommande | None = None
        self.commande_running_changed.connect(self._update_commande_actions)
        self._commande_failed.connect(self._on_commande_failed)
        self._other_busy = lambda: False
        # touches de la fenêtre de l'application, transmises aux commandes (robot.clavier)
        self.keyboard = KeyQueue()

    def set_other_busy(self, other_busy):
        """other_busy() : True quand une autre activité (un essai) utilise le robot."""
        self._other_busy = other_busy

    def is_running(self) -> bool:
        return self._is_loop_running

    def is_commande_running(self) -> bool:
        return self._execution is not None

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, traceback):
        self._worker.shutdown()

    def get_robot_action(self)-> dict[str, ActionValue] | None:
        with self._last_action_lock:
            if self._last_action:
                last_action = self._last_action.copy()
                self._last_action = None
                return last_action
            return None
        
    def set_robot_action(self, action: dict[str, ActionValue]):
        with self._last_action_lock:
            self._last_action = action.copy()

    def _loop(self)->None:
        if self._robot is None:
            raise RuntimeError("Le robot n'est pas connecté, impossible de démarrer la boucle")
        self.busy_state_changed.emit(True)
        fps_stats : FpsStats | None = FpsStats(self) if self._fps_stats_enabled else None
        t0 = time.perf_counter()
        PERIOD = 1/self._fps
        time.sleep(PERIOD)
        period_waiter = PeriodWaiterExact(PERIOD)
        try:
            while not self._stop_loop:
                t = time.perf_counter()
                if fps_stats is not None: 
                    fps_stats.update(t0, t)
                t0 = t
                observations: dict[str, Any] = self._robot.get_observation()
                if self._observation_recorder is not None:
                    self._observation_recorder.append(observations)
                self.observation_ready.emit(observations)
                if not self._tour_commande(observations):
                    action:dict[str, ActionValue]|None = self.get_robot_action()
                    if action:
                        # consigne manuelle (curseurs) : bornée aux butées, comme celles des commandes
                        self._robot.send_action(verifier_action(action, self._robot.action_features))
                period_waiter.wait()
        finally:
            if self._execution is not None:
                self._fin_commande()

    def _tour_commande(self, observations: dict[str, Any]) -> bool:
        """Exécuté dans la boucle. Renvoie True si une commande est en cours (elle décide alors de l'action)."""
        with self._commande_lock:
            a_demarrer, self._commande_a_demarrer = self._commande_a_demarrer, None
            arreter, self._arreter_commande = self._arreter_commande, False
            urgence, self._urgence = self._urgence, False
        if a_demarrer is not None:
            try:
                self._execution = ExecutionCommande(self._robot, a_demarrer, self._fps, clavier=self.keyboard)
            except Exception as e:
                self._commande_failed.emit(self._error_text(e))
                self.commande_running_changed.emit(False)     # la commande n'a pas pu démarrer
                return False
            self.commande_running_changed.emit(True)
        if self._execution is None:
            return False
        if arreter:
            self._fin_commande(arreter_moteurs=not urgence)
            return True
        try:
            continuer = self._execution.tour(observations)
        except Exception as e:
            self._fin_commande(e)
            return True
        if not continuer:
            self._fin_commande()
        return True

    def _fin_commande(self, erreur: BaseException | None = None, arreter_moteurs: bool = True):
        execution, self._execution = self._execution, None
        if execution is not None:
            try:
                execution.arreter(arreter_moteurs)
            except Exception as e:
                erreur = erreur or e
        if erreur is not None:
            self._commande_failed.emit(self._error_text(erreur))
        self.commande_running_changed.emit(False)

    @staticmethod
    def _error_text(error: BaseException) -> str:
        # le message d'abord (ce que l'élève doit lire), la pile d'appels ensuite
        return f"{type(error).__name__} : {error}\r\n\r\n" + "".join(traceback.format_exception(error))

    def _on_commande_failed(self, traceback_str: str):
        logger.error(traceback_str)
        self._dialogProvider.error("La commande a échoué", traceback_str)

    def _update_commande_actions(self, *_):
        running = self._execution is not None
        self._actions[RobotMonitorVMAction.COMMANDE_START].set_enabled(
            self._is_loop_running and self._commande_choisie is not None and not running)
        self._actions[RobotMonitorVMAction.COMMANDE_STOP].set_enabled(running)

    def refresh_commandes(self):
        """Relit les fichiers de commandes (fournies et utilisateur)."""
        # téléopération et commandes générales (les sollicitations sont dans l'onglet Essais)
        self._commandes = decouvrir_commandes(familles=("teleop", ""))
        self.commandes_list_changed.emit(
            [(nom, classe.description) for nom, classe in self._commandes.commandes.items()])
        if self._commandes.erreurs:
            details = "\r\n\r\n".join(f"{fichier} :\r\n{erreur}" for fichier, erreur in self._commandes.erreurs.items())
            self._dialogProvider.warning("Commandes non chargées", details)

    def select_commande(self, nom: str | None):
        """Choisit la commande à démarrer ; None pour la consigne manuelle."""
        if self._execution is not None:
            raise RuntimeError("Une commande est en cours d'exécution")
        self._commande_choisie = nom
        self._update_commande_actions()

    def get_commandes(self):
        return self._commandes

    def start_commande(self, parametres: dict[str, Any] | None = None):
        if not self._is_loop_running or self._commande_choisie is None:
            return
        try:
            commande = self._commandes.commandes[self._commande_choisie](**(parametres or {}))
        except Exception as e:
            self._dialogProvider.exception(e, "Impossible de créer la commande")
            return
        with self._commande_lock:
            self._commande_a_demarrer = commande
            self._arreter_commande = False
            self._urgence = False
        self._actions[RobotMonitorVMAction.COMMANDE_START].set_enabled(False)

    def stop_commande(self, urgence: bool = False):
        with self._commande_lock:
            self._commande_a_demarrer = None
            self._arreter_commande = True
            self._urgence = urgence
            
    def _on_loop_finished(self, result:None):
        try:
            if self._robot is not None:
                self._robot.motors_stop()
            self._save_recording()
        finally:
            # quoi qu'il arrive, l'interface doit sortir de l'état « mesures en cours »
            self._is_loop_running = False
            self._actions[RobotMonitorVMAction.APPLY].set_enabled(True)   
            self._actions[RobotMonitorVMAction.START].set_enabled(True)   
            self._actions[RobotMonitorVMAction.STOP].set_enabled(False)   
            self._actions[RobotMonitorVMAction.ACTION].set_enabled(False)   
            self._update_commande_actions()
            self.busy_state_changed.emit(False)

    def _save_recording(self):
        recorder, self._observation_recorder = self._observation_recorder, None
        if recorder is None:
            return
        # un fichier par enregistrement, pour ne pas écraser le précédent
        directory = Path(__file__).parent.parent / "data" / "essais"
        path = directory / f"essai_{time.strftime('%Y-%m-%d_%H-%M-%S')}.npz"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            recorder.save(path)
        except Exception as e:
            self._dialogProvider.exception(e, "L'enregistrement des mesures a échoué")
            return
        self._dialogProvider.information("Mesures enregistrées", f"{len(recorder)} mesures enregistrées dans :\r\n{path}")

    def _on_loop_failed(self, error: Exception):
        self._is_loop_running = False
        traceback_str = "".join(traceback.format_exception(error))
        logger.error(error)
        logger.error(traceback_str)
        self._actions[RobotMonitorVMAction.APPLY].set_enabled(True)   
        self._actions[RobotMonitorVMAction.START].set_enabled(True)   
        self._actions[RobotMonitorVMAction.STOP].set_enabled(False)   
        self._actions[RobotMonitorVMAction.ACTION].set_enabled(False)   
        self._update_commande_actions()
        self.busy_state_changed.emit(False)

    def connect_to_robot(self, robot : mirRobot):
        self._robot = robot
        self._observables = robot.get_observables()
        self._selected_observables = {}
        actions = robot.get_actions()
        for action in actions.values():
            action.set_value(round(action.get_value(), 2))
        self.actions_list_changed.emit(actions)
        
        self.observations_list_changed.emit([key for key in robot.observation_features.keys()])
        self._actions[RobotMonitorVMAction.APPLY].set_enabled(True)
        self._actions[RobotMonitorVMAction.ACTION].set_enabled(False)   
        self.refresh_commandes()

    def disconnect_from_robot(self):
        if self._is_loop_running is True:
            raise RuntimeError("La boucle de lecture est en cours d'exécution")
        for action in self._actions.values():
            action.set_enabled(False)
        self._robot = None
        self._selected_observables = {}
        self.observations_accepted.emit(self._selected_observables)     
        self.observations_list_changed.emit([])
        self.actions_list_changed.emit({})
        self._actions[RobotMonitorVMAction.APPLY].set_enabled(False)   
        self._actions[RobotMonitorVMAction.START].set_enabled(False)   
        self._actions[RobotMonitorVMAction.STOP].set_enabled(False)   
        self._actions[RobotMonitorVMAction.ACTION].set_enabled(False)   

    def apply_observations(self, selected_observables_keys: list[str]):
        self._selected_observables = {name: self._observables[name] for name in selected_observables_keys}
        self.observations_accepted.emit(self._selected_observables)   
        if self._robot is None:
            raise RuntimeError("Le robot n'a pas été créé")  
        self._robot.enable_observations(self._selected_observables)        
        self._actions[RobotMonitorVMAction.START].set_enabled(True)   
        
    def stop(self):
        if self._is_loop_running is True:
            self._stop_loop = True
        self._actions[RobotMonitorVMAction.ACTION].set_enabled(False)    
           

    def start(self, fps_str: str, fps_stats_enabled: bool, observations_recording_enabled: bool):
        if self._is_loop_running is True:
            return              
        if self._other_busy():
            self._dialogProvider.information("Mesures impossibles", "Un essai est en cours.")
            return
        self._fps_stats_enabled = fps_stats_enabled
        try:  
            self._fps = int(fps_str)
            if self._fps < 10 or self._fps > 1000:
                raise ValueError()
        except Exception:
            self._dialogProvider.warning("Valeur fps invalide", "La valeur de fps doit être un entier entre 10 et 1000")
            return
        self._observations_recording_enabled = observations_recording_enabled
        self._observation_recorder = None
        if observations_recording_enabled:
            record_max_duration = 600
            observables = {name:prop for name,prop in self._observables.items() if isinstance(prop, ObservablePropertyFloat)}
            total_size = 0
            capacity = record_max_duration * self._fps
            for obs in observables.values():
                float_size = obs.dtype.itemsize 
                total_size += float_size * capacity
            self._observation_recorder = DataRecorder(ObservablePropertyConverter.observables_to_dict(self._selected_observables), capacity)
        self._stop_loop = False
        self._is_loop_running = True
        self._actions[RobotMonitorVMAction.APPLY].set_enabled(False)   
        self._actions[RobotMonitorVMAction.START].set_enabled(False)   
        self._actions[RobotMonitorVMAction.STOP].set_enabled(True)   
        self._actions[RobotMonitorVMAction.ACTION].set_enabled(True)   
        self._worker.run(self._loop, self._on_loop_finished, self._on_loop_failed, self)
        self._update_commande_actions()
        
    def on_emergency_stop_clicked(self):
        if self._robot is None:
            raise RuntimeError("Le robot n'a pas été créé")  
        # la commande en cours ne doit plus envoyer de consignes
        self.stop_commande(urgence=True)
        self._robot.motors_emergency_stop()

    def on_motor_action_changed(self, motor_actions: DeviceAction | list[DeviceAction]):
        if isinstance(motor_actions, list):
            action = {
                f"{motor_action.device_name}.{motor_action.action_name}": motor_action.get_value()
                for motor_action in motor_actions
            }
        elif isinstance(motor_actions, DeviceAction):
            action = {f"{motor_actions.device_name}.{motor_actions.action_name}": motor_actions.get_value()}
        self.set_robot_action(action)

