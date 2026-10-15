from PySide6.QtCore import Signal
from mir_robot.mir_robot import mirRobotConfig, mirRobot
from mir_robot_editor.motor_configuration.motor_configuration_view_model import MotorConfigurationViewModel
from mir_robot_editor.scan_devices_view_model import ScanDevicesViewModel
from mir_robot_editor.robot_monitor_view_model import RobotMonitorViewModel
from mir_robot_editor.edit_configuration_view_model import EditConfigurationViewModel
from mir_robot_editor.robot_model.robot_model_view_model import RobotModelViewModel
from mir_robot_editor.robot_model.structure_editor_view_model import StructureEditorViewModel
from mir_utils.ui.dialogs import DialogResult
from mir_utils.ui.view_model_base import VMAction, ViewModelBase
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.concurrency import BackgroundWorker

from enum import Enum, auto
import os

class MainVMAction(Enum):
    NEW = auto()
    SAVE = auto()
    SAVE_AS = auto()
    OPEN = auto()
    CONNECT = auto()
    DISCONNECT = auto()
    SCAN = auto()
    EDIT_CONFIGURATION = auto()
    MOTOR_CFG = auto()
    ROBOT_MODEL = auto()
    STRUCTURE = auto()
    QUIT = auto()

class MainViewModelState(Enum):
    INIT = 1
    LOADED = 2
    CONNECTED = 3
    RUNNING = 4,

class MainViewModel(ViewModelBase[MainVMAction]):
    state_changed = Signal(MainViewModelState, str)
    title_changed = Signal(str)
    _state_description = {
        MainViewModelState.INIT: "Prêt, vous pouvez charger une configuration",
        MainViewModelState.LOADED: "Configuration chargée, vous pouvez connecter le robot",
        MainViewModelState.CONNECTED: "Robot connecté",
        MainViewModelState.RUNNING: "Robot connecté, observations en cours...",
    }
    def __init__(self, dialogProvider: IDialogProvider):
        super().__init__(dialogProvider)
        self._actions[MainVMAction.NEW] = VMAction("Configuration vide", "Démarrer sur une configuration vide")
        self._actions[MainVMAction.SAVE] = VMAction("Sauver", "Sauvegarder la configuration robot dans le fichier courant")
        self._actions[MainVMAction.SAVE_AS] = VMAction("Sauver sous...", "Sauvegarder la configuration robot sous...")
        self._actions[MainVMAction.OPEN] = VMAction("Charger...", "Charger une configuration robot")
        self._actions[MainVMAction.CONNECT] = VMAction("Connecter", "Connecter le robot")
        self._actions[MainVMAction.DISCONNECT] = VMAction("Déconnecter", "Déconnecter le robot")
        self._actions[MainVMAction.SCAN] = VMAction("Découvrir les appareils...", "Ouvrir la fenêtre de découverte des appareils")
        self._actions[MainVMAction.EDIT_CONFIGURATION] = VMAction("Éditer la configuration...", "Ouvrir la fenêtre d'édition de la configuration du robot")
        self._actions[MainVMAction.MOTOR_CFG] = VMAction("Configuration moteurs...", "Ouvrir la fenêtre de configuration des moteurs")
        self._actions[MainVMAction.STRUCTURE] = VMAction("Structure du robot...", "Assembler les modules du robot (modèle numérique utilisé en simulation)")
        self._actions[MainVMAction.ROBOT_MODEL] = VMAction("Modèle 3D...", "Afficher le modèle 3D du robot décrit par la structure de la configuration")
        self._actions[MainVMAction.QUIT] = VMAction("Quitter", "Quitter l'application")
        self._robot: mirRobot | None = None
        self._current_configuration: mirRobotConfig | None = None
        self._robot_monitor_view_model = RobotMonitorViewModel(dialogProvider)
        self._robot_monitor_view_model.busy_state_changed.connect(self.on_observations_vm_busy_state_changed)
        self._worker = BackgroundWorker()
        self.set_title()
        self._set_state(MainViewModelState.INIT)
        self._configuration_dirty = False

    def set_title(self):
        if self._current_configuration is None or self._current_configuration.path is None:
            self.title_changed.emit("MirRobotEditor")
        else:
            filename = os.path.basename(self._current_configuration.path)
            self.title_changed.emit(f"MirRobotEditor - {filename}")

    def quit(self):
        if self._robot is not None:
            self._robot.disconnect()

    def update_state_notifications(self):
        self._set_state(self._state)

    def new(self):
        if self._state == MainViewModelState.LOADED:
            if self._configuration_dirty and self._current_configuration is not None:
                result = self._dialogProvider.question_yes_no_cancel("Configuration modifiée", "La configuration a été modifiée\r\nSouhaitez-vous la sauvegarder maintenant?")
                if result == DialogResult.YES:
                    if not self.save():
                        return
                elif result == DialogResult.CANCEL:
                    return
            self._set_state(MainViewModelState.INIT)

    def load_configuration(self):
        try:
            if self._configuration_dirty and self._current_configuration is not None:
                result = self._dialogProvider.question_yes_no_cancel("Configuration modifiée", "La configuration a été modifiée\r\nSouhaitez-vous la sauvegarder maintenant?")
                if result == DialogResult.YES:
                    if not self.save():
                        return
                elif result == DialogResult.CANCEL:
                    return
            path = self._dialogProvider.open_file("Charger une configuration robot", self.get_data_directory(), "Fichier de configuration robot (*.json)")
            if path is None or path.strip() == "":
                return
            self._current_configuration = mirRobotConfig.load(path)
            self.set_title()

        except ValueError as e:
            self._dialogProvider.information("Erreur chargement de la configuration", str(e))
            return
        self._set_state(MainViewModelState.LOADED)

    def save(self) -> bool:
        if self._current_configuration is None:
            return False
        if self._current_configuration.path is None:
            return self.save_as()
        else:
            self._current_configuration.save()
            self._configuration_dirty = False
            return True

    def save_as(self) -> bool:
        try:
            if self._current_configuration is None:
                raise RuntimeError("aucune configuration chargée")
            default_dir = self._current_configuration.get_dir_of_file()
            if default_dir is None:
                try_use_last_directory = True
                default_dir = self.get_data_directory()
            else:
                try_use_last_directory = False
            path = self._dialogProvider.save_file("Sauver la configuration robot",
                                                  default_dir,
                                                  "Fichier de configuration robot (*.json)",
                                                  try_use_last_directory=try_use_last_directory)
            if not path:
                return False
            if not path.endswith(".json"):
                path += ".json"
            self._current_configuration.save_as(path)
            self.set_title()
            self._configuration_dirty = False
            return True
        except ValueError as e:
            self._dialogProvider.information("Erreur sauvegarde de la configuration", str(e))
            return False

    def connect_robot(self):
        try:
            if self._current_configuration is None:
                raise RuntimeError("Aucune configuration chargée")
            self._robot = mirRobot(self._current_configuration)
            self._robot.connect()
            self._robot.configure()
            if not self._robot.is_calibrated:
                self._dialogProvider.warning("Calibration invalide ou absente",
                                             "La configuration active ne contient pas de calibration, \r\nou les moteurs ne sont pas calibrés,\r\nou les calibrations ne correspondent pas")
                self.disconnect_robot()
                return
            self._robot_monitor_view_model.connect_to_robot(self._robot)
            self._set_state(MainViewModelState.CONNECTED)
        except (ConnectionError, RuntimeError, ValueError, TimeoutError) as e:
            self._dialogProvider.information("La connexion a échoué", str(e))
            self.disconnect_robot()
        except Exception as e:
            self._dialogProvider.exception(e)
            self.disconnect_robot()

    def disconnect_robot(self):
        if self._robot is not None:
            self._robot.disconnect()
        self._robot_monitor_view_model.disconnect_from_robot()
        self._set_state(MainViewModelState.LOADED)

    def execute_scan_devices(self, open_view):
        try:
            vm = ScanDevicesViewModel(self._dialogProvider)
            with vm:
                open_view(vm)
            accepted_configuration = vm.get_accepted_configuration()
            if accepted_configuration is not None:
                self._current_configuration = accepted_configuration
                self._configuration_dirty = True
                if self._dialogProvider.question_yes_no("Configuration modifiée", "Souhaitez-vous sauvegarder la nouvelle configuration maintenant?"):
                    self._configuration_dirty = not self.save()
                self.set_title()
                self._set_state(MainViewModelState.LOADED)

        except BaseException as e:
            self._dialogProvider.exception(e)

    def execute_motor_configuration(self, open_view):
        try :
            if self._current_configuration is None:
                raise RuntimeError("aucune configuration chargée")
            if self._current_configuration.motor_bus is None:
                self._dialogProvider.information("Configuration moteurs", "La configuration active ne contient pas de définition du bus moteur")
                return
            current_configuration_copy = self._current_configuration.get_deep_copy()
            vm = MotorConfigurationViewModel(self._dialogProvider, self._current_configuration)
            with vm:
                open_view(vm)
            if not self._current_configuration.is_equal(current_configuration_copy):
                if self._dialogProvider.question_yes_no("Configuration modifiée", "La configuration a été modifiée\r\nSouhaitez-vous la sauvegarder maintenant?"):
                    self._configuration_dirty = not self.save()
                else:
                    self._configuration_dirty = True
                self._set_state(MainViewModelState.LOADED)
        except (ConnectionError, RuntimeError) as e:
            self._dialogProvider.error("Echec ouverture configuration", str(e))
        except BaseException as e:
            self._dialogProvider.exception(e)
    
    def execute_edit_configuration(self, open_view):
        try:
            if self._current_configuration is None:
                raise RuntimeError("Aucune configuration chargée")
            vm = EditConfigurationViewModel(self._dialogProvider, self._current_configuration.get_deep_copy())
            with vm:
                open_view(vm)
            new_configuration: mirRobotConfig = vm.get_current_configuration()
            if not self._current_configuration.is_equal(new_configuration):
                self._current_configuration = new_configuration
                self._set_state(self._state)
                if self._dialogProvider.question_yes_no("Configuration modifiée", "La configuration a été modifiée\r\nSouhaitez-vous la sauvegarder maintenant?"):
                    self._configuration_dirty = not self.save()
                else:
                    self._configuration_dirty = True
        except BaseException as e:
            self._dialogProvider.exception(e)

    def execute_robot_model(self, open_view):
        try:
            if self._current_configuration is None:
                raise RuntimeError("Aucune configuration chargée")
            if not self._current_configuration.structure:
                self._dialogProvider.information("Modèle 3D", "La configuration active ne contient pas de structure du robot")
                return
            vm = RobotModelViewModel(self._dialogProvider, self._current_configuration.get_deep_copy())
            with vm:
                open_view(vm)
        except BaseException as e:
            self._dialogProvider.exception(e)

    def execute_structure_editor(self, open_view):
        try:
            if self._current_configuration is None:
                raise RuntimeError("Aucune configuration chargée")
            vm = StructureEditorViewModel(self._dialogProvider, self._current_configuration.get_deep_copy())
            with vm:
                open_view(vm)
            if not vm.accepted():
                return
            new_structure = vm.get_structure()
            if new_structure == self._current_configuration.structure:
                return
            self._current_configuration.structure = new_structure
            self._set_state(self._state)   # « Modèle 3D » dépend de la présence d'une structure
            if self._dialogProvider.question_yes_no("Configuration modifiée", "La structure du robot a été modifiée\r\nSouhaitez-vous sauvegarder la configuration maintenant?"):
                self._configuration_dirty = not self.save()
            else:
                self._configuration_dirty = True
        except BaseException as e:
            self._dialogProvider.exception(e)

    def get_robot_monitor_view_model(self):
        return self._robot_monitor_view_model

    def get_actions_state(self):
        return self._actions

    def get_data_directory(self):
        return str(mirRobot.get_data_directory())

    def on_observations_vm_busy_state_changed(self, is_busy:bool):
        if is_busy and self._state == MainViewModelState.CONNECTED:
            self._set_state(MainViewModelState.RUNNING)
        elif not is_busy and self._state == MainViewModelState.RUNNING:
            self._set_state(MainViewModelState.CONNECTED)
        else:
            raise RuntimeError(f"l'état actuel est invalide _state :{self._state}, is_busy:{is_busy}")

    def _set_state(self, state: MainViewModelState):
        self._state = state
        self.state_changed.emit(state, self._state_description[state])
        self._actions[MainVMAction.NEW].set_enabled(self._state == MainViewModelState.LOADED)
        self._actions[MainVMAction.SAVE_AS].set_enabled(self._state == MainViewModelState.LOADED)
        self._actions[MainVMAction.SAVE].set_enabled(self._state == MainViewModelState.LOADED)
        self._actions[MainVMAction.OPEN].set_enabled(self._state == MainViewModelState.INIT or
                                            self._state == MainViewModelState.LOADED)
        self._actions[MainVMAction.CONNECT].set_enabled(self._state == MainViewModelState.LOADED)
        self._actions[MainVMAction.DISCONNECT].set_enabled(self._state == MainViewModelState.CONNECTED)
        self._actions[MainVMAction.SCAN].set_enabled(self._state == MainViewModelState.INIT)
        self._actions[MainVMAction.MOTOR_CFG].set_enabled(self._state ==  MainViewModelState.LOADED)
        self._actions[MainVMAction.EDIT_CONFIGURATION].set_enabled(self._state == MainViewModelState.LOADED)
        self._actions[MainVMAction.STRUCTURE].set_enabled(self._state == MainViewModelState.LOADED)
        has_structure = self._current_configuration is not None and bool(self._current_configuration.structure)
        self._actions[MainVMAction.ROBOT_MODEL].set_enabled(has_structure and self._state in (MainViewModelState.LOADED,
                                                                                              MainViewModelState.CONNECTED,
                                                                                              MainViewModelState.RUNNING))
        self._actions[MainVMAction.QUIT].set_enabled(self._state not in (MainViewModelState.CONNECTED, 
                                                                        MainViewModelState.RUNNING))
