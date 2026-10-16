from PySide6.QtCore import Signal
from mir_robot.mir_robot import mirRobotConfig, mirRobot, DOSSIER_ROBOTS
from mir_sim.sim_devices_factory import SimDevicesFactory
from mir_sim.config_from_structure import complete_config_from_structure
from mir_robot_editor.motor_configuration.motor_configuration_view_model import MotorConfigurationViewModel
from mir_robot_editor.motor_configuration.servo_id_view_model import ServoIdViewModel
from mir_robot_editor.scan_devices_view_model import ScanDevicesViewModel
from mir_robot_editor.robot_monitor_view_model import RobotMonitorViewModel
from mir_robot_editor.essais.essais_view_model import EssaisViewModel
from mir_robot_editor.assemblage.assemblage_view_model import AssemblageViewModel
from mir_robot_editor.edit_configuration_view_model import EditConfigurationViewModel
from mir_robot_editor.robot_model.robot_model_view_model import RobotModelViewModel
from mir_robot_editor.robot_model.structure_editor_view_model import StructureEditorViewModel
from mir_utils.ui.dialogs import DialogResult
from mir_utils.ui.view_model_base import VMAction, ViewModelBase
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.concurrency import BackgroundWorker

from contextlib import contextmanager
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
    SIMULATION = auto()
    RESET_SIMULATION = auto()
    ASSEMBLE = auto()
    RECALIBRATE = auto()
    ADVANCED = auto()
    SERVO_ID = auto()
    CLOSE = auto()
    QUIT = auto()

class MainViewModelState(Enum):
    INIT = 1
    LOADED = 2
    CONNECTED = 3
    RUNNING = 4

class MainViewModel(ViewModelBase[MainVMAction]):
    state_changed = Signal(MainViewModelState, str)
    title_changed = Signal(str)
    simulation_changed = Signal(bool)
    # En mode simulé, CONNECTED signifie « robot simulé construit » : il n'y a pas de connexion à faire,
    # le robot simulé est construit dès qu'un robot avec une structure est ouvert, et reconstruit après chaque modification.
    def __init__(self, dialogProvider: IDialogProvider):
        super().__init__(dialogProvider)
        self._actions[MainVMAction.NEW] = VMAction("Nouveau robot", "Concevoir un nouveau robot à partir des modules du catalogue")
        self._actions[MainVMAction.SAVE] = VMAction("Sauver", "Sauvegarder la configuration robot dans le fichier courant")
        self._actions[MainVMAction.SAVE_AS] = VMAction("Sauver sous...", "Sauvegarder la configuration robot sous...")
        self._actions[MainVMAction.OPEN] = VMAction("Ouvrir un robot...", "Ouvrir la configuration d'un robot")
        self._actions[MainVMAction.CONNECT] = VMAction("Connecter", "Connecter le robot")
        self._actions[MainVMAction.DISCONNECT] = VMAction("Déconnecter", "Déconnecter le robot")
        self._actions[MainVMAction.SCAN] = VMAction("Découvrir les appareils...", "Ouvrir la fenêtre de découverte des appareils")
        self._actions[MainVMAction.EDIT_CONFIGURATION] = VMAction("Éditer la configuration...", "Ouvrir la fenêtre d'édition de la configuration du robot")
        self._actions[MainVMAction.MOTOR_CFG] = VMAction("Réglages des moteurs...", "Mode, PID, vitesse et couple max des moteurs du robot branché")
        self._actions[MainVMAction.STRUCTURE] = VMAction("Structure du robot...", "Créer le robot, ou modifier celui qui est ouvert : modules et branchements")
        self._actions[MainVMAction.ROBOT_MODEL] = VMAction("Modèle 3D...", "Afficher le modèle 3D du robot décrit par la structure de la configuration")
        self._actions[MainVMAction.SIMULATION] = VMAction("Simulé", "Choisir entre le robot réel et le robot simulé (à faire avant la connexion)")
        self._actions[MainVMAction.ASSEMBLE] = VMAction("Assembler le robot...", "Guide de montage du robot physique, module par module")
        self._actions[MainVMAction.RECALIBRATE] = VMAction("Recalibrer un moteur...", "Refaire la calibration d'un servo du robot construit")
        self._actions[MainVMAction.ADVANCED] = VMAction("Paramètres avancés...", "Outils techniques : réglages des moteurs, ID des servos, fichier de configuration")
        self._actions[MainVMAction.SERVO_ID] = VMAction("Changer l'ID d'un servo...", "Donner un nouvel ID à un servo branché seul, même sans robot construit")
        self._actions[MainVMAction.CLOSE] = VMAction("Fermer ce robot", "Fermer le robot ouvert pour en créer ou en ouvrir un autre (rien n'est supprimé)")
        self._actions[MainVMAction.RESET_SIMULATION] = VMAction("Remettre à zéro", "Replacer le robot simulé dans sa position de départ")
        self._actions[MainVMAction.QUIT] = VMAction("Quitter", "Quitter l'application")
        self._simulation = False
        self._sim_factory: SimDevicesFactory | None = None
        # étape « Configurer le robot » : on décrit et règle le robot, sans choisir réel ou simulé ;
        # le robot (réel ou simulé) n'est utilisé qu'à partir de l'étape Piloter
        self._configuring = True
        self._robot: mirRobot | None = None
        self._current_configuration: mirRobotConfig | None = None
        self._robot_monitor_view_model = RobotMonitorViewModel(dialogProvider)
        self._robot_monitor_view_model.busy_state_changed.connect(self.on_observations_vm_busy_state_changed)
        self._essais_view_model = EssaisViewModel(dialogProvider, self._motor_settings, self._apply_motor_settings,
                                                  self._essai_conditions, other_busy=self._robot_monitor_view_model.is_running,
                                                  sim_world=lambda: self._sim_factory.world if self._sim_factory else None)
        self._essais_view_model.busy_state_changed.connect(self.on_observations_vm_busy_state_changed)
        self._robot_monitor_view_model.set_other_busy(self._essais_view_model.is_running)
        self._worker = BackgroundWorker()
        # réglages modifiés pendant les essais : temporaires, MIR remet les siens en quittant les essais
        self._essai_originaux: dict[str, dict[str, int]] = {}      # {moteur: {réglage: valeur de la configuration}}
        self.set_title()
        self._set_state(MainViewModelState.INIT)
        self._configuration_dirty = False

    def set_title(self):
        mode = "SIMULÉ" if self._simulation else "RÉEL"
        if self._current_configuration is None or self._current_configuration.path is None:
            self.title_changed.emit(f"MirRobotEditor [{mode}]")
        else:
            filename = os.path.basename(self._current_configuration.path)
            self.title_changed.emit(f"MirRobotEditor - {filename} [{mode}]")

    def get_robot_name(self) -> str | None:
        """Nom du robot ouvert (nom du fichier de configuration), None si aucun robot n'est ouvert."""
        if self._state == MainViewModelState.INIT or self._current_configuration is None:
            return None
        if self._current_configuration.path is None:
            return "nouveau robot"
        return os.path.splitext(os.path.basename(self._current_configuration.path))[0]

    @property
    def _configuration_dirty(self) -> bool:
        return getattr(self, "_dirty", False)

    @_configuration_dirty.setter
    def _configuration_dirty(self, dirty: bool):
        # l'en-tête indique les modifications non enregistrées
        self._dirty = dirty
        self.set_title()

    def is_dirty(self) -> bool:
        return self._configuration_dirty and self._state != MainViewModelState.INIT

    def get_state(self) -> MainViewModelState:
        return self._state

    def is_simulation(self) -> bool:
        return self._simulation

    def set_simulation(self, simulation: bool):
        """Choisit le robot réel ou le robot simulé : impossible avec le robot réel connecté ou pendant des mesures."""
        if self._state == MainViewModelState.RUNNING or (self._state == MainViewModelState.CONNECTED and not self._simulation):
            raise RuntimeError("Déconnecter le robot avant de changer de mode")
        if simulation == self._simulation:
            return
        self.restore_essai_settings()
        if not simulation and not self.is_built():
            raise RuntimeError("Le robot n'est pas construit : seul le robot simulé est disponible")
        self._stop_simulation()
        self._simulation = simulation
        self.set_title()
        self._set_state(self._state)   # certaines actions n'ont de sens qu'avec le robot réel
        self.simulation_changed.emit(simulation)
        self._start_simulation()

    def is_configuring(self) -> bool:
        return self._configuring

    def set_configuring(self, configuring: bool) -> bool:
        """Entrée dans l'étape « Configurer le robot » (le robot est libéré) ou sortie vers les étapes qui l'utilisent.
        False si c'est impossible (mesures en cours)."""
        if configuring == self._configuring:
            return True
        if configuring and self._state == MainViewModelState.RUNNING:
            return False
        self._configuring = configuring
        if configuring:
            self.restore_essai_settings()
        if configuring and self._state == MainViewModelState.CONNECTED:
            self.disconnect_robot()
        self._set_state(self._state)
        self._real_only_if_built()
        self._start_simulation()
        return True

    def _real_only_if_built(self):
        """Le robot réel n'est utilisable qu'une fois construit : sinon, on passe en simulé."""
        if not self._configuring and not self._simulation and not self.is_built() \
                and self._state in (MainViewModelState.INIT, MainViewModelState.LOADED):
            self.set_simulation(True)

    def has_structure(self) -> bool:
        return self._current_configuration is not None and bool(self._current_configuration.structure)

    # ------------------------------------------------------------------ robot simulé
    def _start_simulation(self):
        """Construit le robot simulé si on est en mode simulé avec un robot ouvert qui a une structure."""
        if not self._simulation or self._configuring or self._state != MainViewModelState.LOADED or not self.has_structure():
            return
        try:
            # même configuration que le robot réel, appareils simulés construits à partir de la structure
            self._sim_factory = SimDevicesFactory()
            self._robot = mirRobot(self._current_configuration, devices_factory=self._sim_factory)
            self._robot.connect()
            self._robot.configure()
            self._robot_monitor_view_model.connect_to_robot(self._robot)
            self._essais_view_model.connect_to_robot(self._robot)
            self._set_state(MainViewModelState.CONNECTED)
        except Exception as e:
            self._dialogProvider.information("Le robot simulé ne peut pas être construit", str(e))
            self.disconnect_robot()

    def _stop_simulation(self):
        if self._simulation and self._state == MainViewModelState.CONNECTED:
            self.disconnect_robot()

    @contextmanager
    def _configuration_change(self):
        """Autour d'une modification de la configuration : le robot simulé est arrêté puis reconstruit."""
        self._stop_simulation()
        try:
            yield
        finally:
            self._real_only_if_built()
            self._start_simulation()

    def reset_simulation(self):
        if self._sim_factory is not None and self._sim_factory.world is not None:
            self._sim_factory.world.reset()

    def _ask_save_if_dirty(self) -> bool:
        """Propose d'enregistrer une configuration modifiée ; False si l'utilisateur annule."""
        if not self._configuration_dirty or self._current_configuration is None:
            return True
        result = self._dialogProvider.question_yes_no_cancel("Configuration modifiée", "La configuration a été modifiée\r\nSouhaitez-vous la sauvegarder maintenant?")
        if result == DialogResult.YES:
            return self.save()
        return result != DialogResult.CANCEL

    def inform(self, title: str, text: str) -> None:
        self._dialogProvider.information(title, text)

    def confirm(self, title: str, text: str) -> bool:
        return self._dialogProvider.question_yes_no(title, text)

    def quit(self):
        if self._robot is not None:
            self._robot.disconnect()

    def update_state_notifications(self):
        self._set_state(self._state)

    def new(self) -> bool:
        """Nouveau robot, vide : sa structure est à concevoir. True si le robot a été créé."""
        if not self._ask_save_if_dirty():
            return False
        with self._configuration_change():
            self._current_configuration = mirRobotConfig()
            self._configuration_dirty = True
            self.set_title()
            self._set_state(MainViewModelState.LOADED)
        return True

    def close_robot(self) -> bool:
        """Ferme le robot ouvert : retour à « aucun robot ouvert ». Le fichier et les servos ne sont pas modifiés.
        False si l'utilisateur annule (modifications non enregistrées) ou si des mesures sont en cours."""
        if self._state == MainViewModelState.INIT or self._state == MainViewModelState.RUNNING:
            return False
        if not self._ask_save_if_dirty():
            return False
        self.restore_essai_settings()
        if self._state == MainViewModelState.CONNECTED:
            self.disconnect_robot()
        self._current_configuration = None
        self._configuration_dirty = False
        self.set_title()
        self._set_state(MainViewModelState.INIT)
        return True

    def load_configuration(self):
        if not self._ask_save_if_dirty():
            return
        path = self._dialogProvider.open_file("Ouvrir un robot", self.get_data_directory(), "Fichier de configuration robot (*.json)",
                                              try_use_last_directory=False)
        if path is None or path.strip() == "":
            return
        with self._configuration_change():
            try:
                self._current_configuration = mirRobotConfig.load(path)
            except ValueError as e:
                self._dialogProvider.information("Erreur chargement de la configuration", str(e))
                return
            self._configuration_dirty = False
            self.set_title()
            self._set_state(MainViewModelState.LOADED)

    def save(self) -> bool:
        if self._current_configuration is None:
            return False
        if self._current_configuration.path is None:
            return self.save_as()
        else:
            with self._reglages_mir():
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
            with self._reglages_mir():
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
            if self._simulation:
                return  # le robot simulé n'a pas de connexion : il est construit automatiquement
            self._robot = mirRobot(self._current_configuration)
            self._robot.connect()
            self._robot.configure()
            if not self._robot.is_calibrated:
                self._dialogProvider.warning("Calibration invalide ou absente",
                                             "La configuration active ne contient pas de calibration, \r\nou les moteurs ne sont pas calibrés,\r\nou les calibrations ne correspondent pas")
                self.disconnect_robot()
                return
            self._robot_monitor_view_model.connect_to_robot(self._robot)
            self._essais_view_model.connect_to_robot(self._robot)
            self._set_state(MainViewModelState.CONNECTED)
        except (ConnectionError, RuntimeError, ValueError, TimeoutError) as e:
            self._dialogProvider.information("La connexion a échoué", str(e))
            self.disconnect_robot()
        except Exception as e:
            self._dialogProvider.exception(e)
            self.disconnect_robot()

    def disconnect_robot(self):
        if self._robot is not None and not self._simulation:
            self.restore_essai_settings()       # le moteur réel garde les réglages de MIR
        if self._robot is not None:
            self._robot.disconnect()
            self._robot = None
        self._sim_factory = None
        self._robot_monitor_view_model.disconnect_from_robot()
        self._essais_view_model.disconnect_from_robot()
        self._set_state(MainViewModelState.LOADED)

    def execute_scan_devices(self, open_view):
        try:
            if not self._ask_save_if_dirty():
                return
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
    
    def execute_servo_id(self, open_view):
        try:
            bus = self._current_configuration.motor_bus if self._current_configuration is not None else None
            ids = {nom: m.id for nom, m in bus.motors.items()} if bus is not None else {}
            with ServoIdViewModel(self._dialogProvider, ids) as vm:
                open_view(vm)
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
                with self._configuration_change():
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

    def motor_modules(self) -> dict[str, str]:
        """Servos du robot : {moteur: module de la structure qui le porte}."""
        cfg = self._current_configuration
        if cfg is None or not cfg.structure or cfg.motor_bus is None:
            return {}
        result = {}
        for module, inst in cfg.structure.get("modules", {}).items():
            for motor in ([inst["motor"]] if "motor" in inst else []) + list(inst.get("motors", {}).values()):
                if motor in cfg.motor_bus.motors:
                    result[motor] = module
        return result

    def is_built(self) -> bool:
        """Robot construit : tous ses servos sont calibrés et toutes ses caméras ont une adresse (étape Construire faite)."""
        cfg = self._current_configuration
        if cfg is None or not cfg.structure:
            return False
        motors = self.motor_modules()
        cameras = [s for s in cfg.sensors.values() if getattr(s, "sensor_type", "") == "pi_camera"]
        return (cfg.motor_bus is None or all(m in cfg.motor_bus.calibration for m in motors)) \
            and all(getattr(c, "ip", None) for c in cameras)

    def robot_summary(self) -> dict[str, str]:
        """État des étapes de la configuration : « concevoir », « construire »."""
        cfg = self._current_configuration
        if cfg is None:
            return {}
        motors = self.motor_modules()
        cameras = [s for s in cfg.sensors.values() if getattr(s, "sensor_type", "") == "pi_camera"]
        if not cfg.structure:
            return {"concevoir": "○ à faire", "construire": "○ concevez d'abord la structure",
                    "regler": "○ construisez d'abord le robot"}
        parts = [f"{len(motors)} servo(s)"] + ([f"{len(cameras)} caméra(s)"] if cameras else [])
        calibrated = sum(1 for m in motors if cfg.motor_bus is not None and m in cfg.motor_bus.calibration)
        located = sum(1 for c in cameras if getattr(c, "ip", None))
        built = self.is_built()
        detail = f"{calibrated} / {len(motors)} servo(s) calibré(s)" + (f", {located} / {len(cameras)} caméra(s)" if cameras else "")
        return {"concevoir": "✓ " + ", ".join(parts), "construire": ("✓ " if built else "○ ") + detail,
                "regler": "" if built else "○ construisez d'abord le robot"}

    def execute_recalibration(self, motor: str, open_view):
        """Refaire la calibration d'un servo : le guide de montage, limité à ce servo."""
        self.execute_assemblage(open_view, modules=[self.motor_modules()[motor]])

    def execute_assemblage(self, open_view, modules: list[str] | None = None):
        """Guide de montage : la configuration est complétée (port, ID, calibrations, adresses des caméras, sens)."""
        try:
            if self._current_configuration is None or not self._current_configuration.structure:
                raise RuntimeError("Le robot n'a pas de structure : concevez-la d'abord (Structure du robot)")
            vm = AssemblageViewModel(self._dialogProvider, self._current_configuration, modules)
            with vm:
                accepted = bool(open_view(vm))
            if not accepted:
                return      # construction interrompue : la configuration n'est pas modifiée
            with self._configuration_change():
                path = self._current_configuration.path
                self._current_configuration = vm.configuration()
                self._current_configuration.path = path
                self._configuration_dirty = True
                self._set_state(self._state)
            if self._dialogProvider.question_yes_no("Configuration modifiée", "Le montage a complété la configuration "
                                                    "du robot.\r\nSouhaitez-vous la sauvegarder maintenant?"):
                self._configuration_dirty = not self.save()
        except BaseException as e:
            self._dialogProvider.exception(e)

    def execute_structure_editor(self, open_view):
        """Sans robot ouvert, la structure crée un nouveau robot ; sinon, elle modifie le robot ouvert."""
        try:
            nouveau = self._state == MainViewModelState.INIT or self._current_configuration is None
            config = mirRobotConfig() if nouveau else self._current_configuration
            vm = StructureEditorViewModel(self._dialogProvider, config.get_deep_copy())
            with vm:
                open_view(vm)
            if not vm.accepted():
                return
            if nouveau:
                self._current_configuration = config
                self.set_title()
                self._set_state(MainViewModelState.LOADED)
            new_structure = vm.get_structure()
            if new_structure == self._current_configuration.structure:
                return
            with self._configuration_change():
                self._current_configuration.structure = new_structure
                # moteurs et capteurs des modules ajoutés depuis le catalogue (robot conçu sans matériel)
                complete_config_from_structure(self._current_configuration)
                self._set_state(self._state)   # « Modèle 3D » dépend de la présence d'une structure
            if self._dialogProvider.question_yes_no("Configuration modifiée", "La structure du robot a été modifiée\r\nSouhaitez-vous sauvegarder la configuration maintenant?"):
                self._configuration_dirty = not self.save()
            else:
                self._configuration_dirty = True
        except BaseException as e:
            self._dialogProvider.exception(e)

    # ------------------------------------------------------------------ essais
    def get_sim_world(self):
        """Monde du robot simulé (vue 3D), None s'il n'est pas construit."""
        return self._sim_factory.world if self._sim_factory is not None else None

    def get_essais_view_model(self) -> EssaisViewModel:
        return self._essais_view_model

    def _motor_settings(self, motor: str) -> dict[str, int]:
        cfg = self._current_configuration
        if cfg is None or cfg.motor_bus is None or motor not in cfg.motor_bus.motors:
            return {}
        m = cfg.motor_bus.motors[motor]
        return {attr: int(getattr(m, attr)) for attr in ("P", "I", "D", "position_mode_velocity", "torque_limit")}

    def _apply_motor_settings(self, motor: str, settings: dict[str, int]):
        """Réglages modifiés depuis un essai : temporaires. Ils sont écrits dans le moteur réel (ou le robot simulé
        est reconstruit avec eux) ; la configuration enregistrée garde ceux de MIR, remis en quittant les essais."""
        cfg = self._current_configuration
        if cfg is None or cfg.motor_bus is None or motor not in cfg.motor_bus.motors:
            return
        m = cfg.motor_bus.motors[motor]
        self._essai_originaux.setdefault(motor, {attr: int(getattr(m, attr)) for attr in settings})
        with self._configuration_change():
            for attr, value in settings.items():
                setattr(m, attr, int(value))
        if not self._simulation and self._robot is not None:
            self._robot.configure()

    def _remettre_reglages(self) -> bool:
        """Remet dans la configuration les réglages de MIR ; False s'il n'y avait rien à remettre."""
        cfg = self._current_configuration
        originaux, self._essai_originaux = self._essai_originaux, {}
        if cfg is None or cfg.motor_bus is None or not originaux:
            return False
        for motor, reglages in originaux.items():
            if motor in cfg.motor_bus.motors:
                for attr, value in reglages.items():
                    setattr(cfg.motor_bus.motors[motor], attr, value)
        return True

    def restore_essai_settings(self):
        """En quittant les essais : les moteurs reprennent les réglages de MIR (registres réécrits)."""
        if not self._essai_originaux or self._essais_view_model.is_running():
            return
        if self._simulation:
            with self._configuration_change():
                self._remettre_reglages()
            return
        self._remettre_reglages()
        if self._robot is not None:
            try:
                self._robot.configure()
            except Exception as e:
                self._dialogProvider.warning("Réglages des moteurs", f"Les réglages de MIR n'ont pas pu être "
                                             f"réécrits dans les moteurs : {e}\r\nIls le seront à la prochaine connexion.")
        self._essais_view_model.robot_changed.emit()        # les champs reprennent les réglages de MIR

    @contextmanager
    def _reglages_mir(self):
        """Enregistrer : la configuration est écrite avec les réglages de MIR, pas ceux d'un essai en cours."""
        cfg = self._current_configuration
        temporaires = {motor: {attr: getattr(cfg.motor_bus.motors[motor], attr) for attr in reglages}
                       for motor, reglages in self._essai_originaux.items()}
        originaux = dict(self._essai_originaux)
        self._remettre_reglages()
        try:
            yield
        finally:
            self._essai_originaux = originaux
            for motor, reglages in temporaires.items():
                for attr, value in reglages.items():
                    setattr(cfg.motor_bus.motors[motor], attr, value)

    def _essai_conditions(self) -> dict:
        cfg = self._current_configuration
        return {"simulation": self._simulation, "robot": self.get_robot_name(),
                "configuration": cfg.path if cfg is not None else None}

    def get_robot_monitor_view_model(self):
        return self._robot_monitor_view_model

    def get_actions_state(self):
        return self._actions

    def get_data_directory(self):
        # les robots sont tous rangés au même endroit
        DOSSIER_ROBOTS.mkdir(parents=True, exist_ok=True)
        return str(DOSSIER_ROBOTS)

    def on_observations_vm_busy_state_changed(self, is_busy:bool):
        if is_busy and self._state == MainViewModelState.CONNECTED:
            self._set_state(MainViewModelState.RUNNING)
        elif not is_busy and self._state == MainViewModelState.RUNNING:
            self._set_state(MainViewModelState.CONNECTED)
        else:
            raise RuntimeError(f"l'état actuel est invalide _state :{self._state}, is_busy:{is_busy}")

    def get_state_description(self) -> str:
        state, sim = self._state, self._simulation
        if state == MainViewModelState.INIT:
            return "Aucun robot ouvert : créez-en un avec « Structure du robot », ou ouvrez-en un"
        if state == MainViewModelState.LOADED and self._configuring:
            return "Robot ouvert : configurez-le, puis passez à l'étape Piloter"
        if state == MainViewModelState.LOADED:
            if sim:
                return "Pas de structure : concevez-la (Configurer le robot → Structure du robot) pour simuler ce robot"
            return "Robot ouvert : Connecter pour utiliser le robot réel"
        if state == MainViewModelState.CONNECTED:
            return ("Simulation prête : allez dans Piloter pour faire bouger le robot simulé" if sim
                    else "Robot connecté : allez dans Piloter pour démarrer les mesures")
        return "Mouvement en cours (simulation)" if sim else "Mesures en cours"

    def _set_state(self, state: MainViewModelState):
        self._state = state
        sim = self._simulation
        connected = state in (MainViewModelState.CONNECTED, MainViewModelState.RUNNING)
        # robot ouvert et modifiable : chargé, ou robot simulé construit (il sera reconstruit après la modification)
        editable = state == MainViewModelState.LOADED or (sim and state == MainViewModelState.CONNECTED)
        has_structure = self.has_structure()
        a = self._actions
        a[MainVMAction.NEW].set_enabled(state == MainViewModelState.INIT or editable)
        a[MainVMAction.OPEN].set_enabled(state == MainViewModelState.INIT or editable)
        a[MainVMAction.SAVE].set_enabled(editable)
        a[MainVMAction.SAVE_AS].set_enabled(editable)
        a[MainVMAction.CLOSE].set_enabled(state != MainViewModelState.INIT and state != MainViewModelState.RUNNING)
        a[MainVMAction.STRUCTURE].set_enabled(state == MainViewModelState.INIT or editable)
        a[MainVMAction.EDIT_CONFIGURATION].set_enabled(editable)
        a[MainVMAction.ROBOT_MODEL].set_enabled(has_structure and state != MainViewModelState.INIT)
        # matériel (robot branché) : pendant la configuration, le robot n'est pas utilisé par ailleurs
        a[MainVMAction.SCAN].set_enabled(state in (MainViewModelState.INIT, MainViewModelState.LOADED))
        # régler n'a de sens qu'une fois le robot construit
        a[MainVMAction.MOTOR_CFG].set_enabled(state == MainViewModelState.LOADED and self.is_built())
        a[MainVMAction.ASSEMBLE].set_enabled(state == MainViewModelState.LOADED and has_structure)
        a[MainVMAction.RECALIBRATE].set_enabled(state == MainViewModelState.LOADED and self.is_built()
                                                and bool(self.motor_modules()))
        a[MainVMAction.ADVANCED].set_enabled(True)
        # le port des servos doit être libre : pas avec le robot réel connecté
        a[MainVMAction.SERVO_ID].set_enabled(not (connected and not sim))
        a[MainVMAction.CONNECT].set_enabled(state == MainViewModelState.LOADED and not sim and not self._configuring)
        a[MainVMAction.DISCONNECT].set_enabled(state == MainViewModelState.CONNECTED and not sim)
        a[MainVMAction.SIMULATION].set_enabled(state != MainViewModelState.RUNNING and not (connected and not sim))
        a[MainVMAction.RESET_SIMULATION].set_enabled(sim and connected)
        a[MainVMAction.QUIT].set_enabled(True)   # la fenêtre déconnecte le robot avant de quitter
        self.state_changed.emit(state, self.get_state_description())
