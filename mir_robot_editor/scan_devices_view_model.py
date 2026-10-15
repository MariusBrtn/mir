from typing import Callable
from enum import Enum
from typing_extensions import override
from PySide6.QtCore import Signal
import time
from mir_devices.mir_sensor import mirSensorConfiguration
from mir_devices.mir_device import ObservableProperty
from mir_devices.mir_feetech_motor_bus import mirMotorBusConfiguration
from mir_robot.mir_robot_config import mirRobotConfig
from mir_utils.concurrency import BackgroundWorker
from mir_robot_editor.sensor_configuration_view_model import SensorConfigurationViewModel
from mir_devices.mir_devices_factory import reset_sensors, DefaultDevicesFactory
from mir_robot_editor.motor_configuration.motor_configure_IDs_view_model import MotorConfigureIDsViewModel
from mir_devices.discovery_scanner import DiscoveryScanner, DiscoveryScannerResult
from mir_utils.ui.view_model_base import VMAction, ViewModelBase
from mir_utils.ui.dialogs import IDialogProvider
from mir_sim.model_builder import initial_structure, load_catalog, motor_module_types, sensor_module_types

DEFAULT_MOTOR_MODULE = "mir_servo"
_catalog: dict | None = None


def _get_catalog() -> dict:
    """Catalogue des modules MIR (simulation), lu une seule fois."""
    global _catalog
    if _catalog is None:
        _catalog = load_catalog()
    return _catalog

class DiscoveredDeviceViewModel():
    def __init__(self, key: str, device_cfg: mirSensorConfiguration|mirMotorBusConfiguration, warning: str=""):
        self._selected = False
        self._device = device_cfg
        self._key = key
        self._info = str(device_cfg)
        self._type = ""
        self._warning = warning

    def type(self) -> str:
        return self._type
    
    def key(self) -> str:
        return self._key

    def info(self) -> str:
        return self._info

    def device_configuration(self):
        return self._device

    def get_selected(self) -> bool:
        return self._selected
    
    def set_selected(self, value: bool):
        self._selected = value

    def get_warning(self):
        return self._warning

    def module_type(self) -> str | None:
        """Module MIR qui représente l'appareil (miniature 3D), None s'il n'y en a pas dans le catalogue."""
        return None

    def identity(self) -> str:
        """Ce qui identifie l'appareil d'une recherche à l'autre (IP, port...)."""
        return self._info

    def copy_choices_from(self, other: "DiscoveredDeviceViewModel") -> None:
        """Reprend les choix de l'utilisateur faits sur le même appareil pendant la recherche."""
        self._selected = other._selected

class DiscoveredSensorViewModel(DiscoveredDeviceViewModel):
    def __init__(self, key: str, device_cfg: mirSensorConfiguration):
        super().__init__(key, device_cfg)
        self._type = device_cfg.sensor_type
        types = sensor_module_types(_get_catalog(), device_cfg.sensor_type)
        self._module_type = types[0] if types else None

    def module_type(self) -> str | None:
        return self._module_type

class DiscoveredMotorBusViewModel(DiscoveredDeviceViewModel):
    def __init__(self, key: str, device_cfg: mirMotorBusConfiguration):
        warning = "Bus moteur sans aucun moteur connecté" if len(device_cfg.motors) == 0 else ""
        super().__init__(key, device_cfg, warning)
        self._type = "motors"
        choices = self.module_type_choices()
        default = DEFAULT_MOTOR_MODULE if DEFAULT_MOTOR_MODULE in choices else (choices[0] if choices else None)
        # module MIR de chaque moteur : le bus ne permet pas de distinguer un servo d'une pince
        self._motor_types: dict[str, str | None] = {motor: default for motor in device_cfg.motors}

    def motors(self) -> list[tuple[str, int]]:
        return [(name, motor.id) for name, motor in self._device.motors.items()]

    def port(self) -> str:
        return self._device.motor_port

    @staticmethod
    def module_type_choices() -> list[str]:
        return motor_module_types(_get_catalog())

    def motor_type(self, motor: str) -> str | None:
        return self._motor_types.get(motor)

    def set_motor_type(self, motor: str, module_type: str) -> None:
        self._motor_types[motor] = module_type

    def identity(self) -> str:
        return self._device.motor_port

    def copy_choices_from(self, other: DiscoveredDeviceViewModel) -> None:
        super().copy_choices_from(other)
        if isinstance(other, DiscoveredMotorBusViewModel):
            self._motor_types.update({m: t for m, t in other._motor_types.items() if m in self._motor_types})

class ScanDevicesVMAction(Enum):
    SCAN = 1
    ACCEPT = 2
    CANCEL = 3
    STOP = 4
    CONFIGURE_DEVICE = 5

class ScanDevicesViewModelState(Enum):
    INIT = 1
    SCANNING = 2
    SCAN_COMPLETED = 3
    RESET_SENSORS = 4

class ObservationsSelectionViewModel(ViewModelBase):
    close_required = Signal()

    def __init__(self, dialogProvider: IDialogProvider, config: mirRobotConfig):
        super().__init__(dialogProvider)
        self._accepted : bool = False
        devices = DefaultDevicesFactory().create_devices(config)
        self._observable_properties_by_device: dict[str, dict[str, ObservableProperty]] = {}
        self._observable_properties: dict[str, ObservableProperty] = {}
        for device_key, device in devices.devices.items():
            device_observables = device.get_observables()
            # Test des doublons de clés d'observables
            for prop_key in device_observables:
                if prop_key in self._observable_properties:
                    raise ValueError(
                        f"Doublon de clé d'observable : '{prop_key}' "
                        f"déjà défini par un autre device"
                    )
            # Ajout global
            self._observable_properties.update(device_observables)
            # Test doublon device_key
            if device_key in self._observable_properties_by_device:
                raise ValueError(f"La clé device '{device_key}' existe déjà")
            # Ajout par device
            self._observable_properties_by_device[device_key] = dict(device_observables)
            
    @override
    def _enter_context(self):
        pass

    @override
    def _exit_context(self, exc_type, exc_value, traceback):
        pass
    
    def get_observables(self) -> dict[str, dict[str, ObservableProperty]]:
        return self._observable_properties_by_device

    def set_selected_observables(self, selected_keys: list[str]):
        self._selected_observables =  { 
            key: self._observable_properties[key] 
            for key in selected_keys 
            if key in self._observable_properties
        }
        self._accepted = True
        self.close_required.emit()

    def get_selected_observables(self) -> dict[str, ObservableProperty]:
        return self._selected_observables        

    def cancel(self):
        self.close_required.emit()

    def accepted(self) -> bool:
        return self._accepted        

class ScanDevicesViewModel(ViewModelBase[ScanDevicesVMAction]):
    progress_changed = Signal(int, list)
    scan_completed = Signal(list)
    status_changed = Signal(str)
    close_required = Signal()

    def __init__(self, dialogProvider: IDialogProvider):
        super().__init__(dialogProvider)
        self._devices : list[DiscoveredDeviceViewModel] | None = None
        self._accepted_devices : list[DiscoveredDeviceViewModel] | None = None
        self._actions[ScanDevicesVMAction.SCAN] = VMAction("Rechercher les appareils", "Rechercher les appareils")
        self._actions[ScanDevicesVMAction.ACCEPT] = VMAction("Créer la configuration", "Créer la configuration à partir des appareils sélectionnés")
        self._actions[ScanDevicesVMAction.CANCEL] = VMAction("Fermer", "Fermer la fenêtre sans modifier la configuration")
        self._actions[ScanDevicesVMAction.STOP] = VMAction("Arrêter", "Arrêter le scan en cours")
        self._actions[ScanDevicesVMAction.CONFIGURE_DEVICE] = VMAction("Configurer l'appareil...", "Ouvrir la fenêtre de configuration de l'appareil")
        self._set_state(ScanDevicesViewModelState.INIT)
        self._worker = BackgroundWorker()
        self._worker_reset = BackgroundWorker()
        self._scanner = DiscoveryScanner()
        
    def _set_state(self, state: ScanDevicesViewModelState):
        self._state = state
        self._actions[ScanDevicesVMAction.SCAN].set_enabled(self._state in
             (ScanDevicesViewModelState.INIT, ScanDevicesViewModelState.SCAN_COMPLETED))
        self._actions[ScanDevicesVMAction.ACCEPT].set_enabled(self._state ==
             ScanDevicesViewModelState.SCAN_COMPLETED)
        self._actions[ScanDevicesVMAction.CANCEL].set_enabled(self._state in
             (ScanDevicesViewModelState.SCAN_COMPLETED, ScanDevicesViewModelState.INIT))
        self._actions[ScanDevicesVMAction.STOP].set_enabled(self._state ==
             ScanDevicesViewModelState.SCANNING)
        self._actions[ScanDevicesVMAction.CONFIGURE_DEVICE].set_enabled(self._state ==
             ScanDevicesViewModelState.SCAN_COMPLETED)

    @override
    def _enter_context(self):
        pass

    @override
    def _exit_context(self, exc_type, exc_value, traceback):
        self._worker.shutdown()

    def scan_devices(self):
        self._set_state(ScanDevicesViewModelState.SCANNING)
        self.status_changed.emit("Recherche en cours...")
        self._worker.run(self._do_scan, self._on_scan_finished, self._on_scan_failed, self)

    def stop_scan(self):
        self._scanner.stop_scan()
        
    def _do_scan(self) -> tuple[DiscoveryScannerResult, str]:
        found_devices : list[DiscoveredDeviceViewModel] = []
        # appareils affichés pendant la recherche : l'utilisateur peut déjà les cocher
        self._progress_devices = found_devices
        timeout = 5.0

        def callback(device:mirSensorConfiguration|mirMotorBusConfiguration):
            if isinstance(device, mirSensorConfiguration):
                found_devices.append(DiscoveredSensorViewModel("", device))
            elif isinstance(device, mirMotorBusConfiguration):
                found_devices.append(DiscoveredMotorBusViewModel("", device))
                
        self._scanner.run(timeout=timeout, progress_callback=callback)
        t0 = time.time()
        while not self._scanner.done():
            elapsed = max((time.time()-t0), 1e-9)
            self.progress_changed.emit(int(elapsed*100/timeout), found_devices)
            time.sleep(0.25)
        return self._scanner.result() 

    def _on_scan_finished(self, result: tuple[DiscoveryScannerResult, str]):
        scanner_result: DiscoveryScannerResult = result[0]
        scanner_info = result[1]
        self._devices = [DiscoveredSensorViewModel(key, sensor_cfg) for key, sensor_cfg in scanner_result.sensors.items()]
        for motor_bus in scanner_result.motor_buses:
            self._devices.append(DiscoveredMotorBusViewModel("", motor_bus))
        # reprendre les choix (cases cochées, servo/pince) faits sur les appareils affichés pendant la recherche
        previous = {device.identity(): device for device in getattr(self, "_progress_devices", [])}
        for device in self._devices:
            if device.identity() in previous:
                device.copy_choices_from(previous[device.identity()])
        
        self.scan_completed.emit(self._devices)
        if self._devices is not None and len(self._devices) > 0:
            n = len(self._devices)
            if n > 0:
                s = "appareils trouvés" if n > 1 else "appareil trouvé"
                self.status_changed.emit(f"{n} {s}")
                self._set_state(ScanDevicesViewModelState.SCAN_COMPLETED)
        else:
            self.status_changed.emit("Aucun appareil trouvé")
            self._set_state(ScanDevicesViewModelState.INIT)
        if scanner_info is not None and scanner_info != '':
            self._dialogProvider.warning("Une erreur s'est produite", scanner_info)

    def _on_scan_failed(self, error: Exception):
        self.status_changed.emit(f"Erreur lors du scan : {error}")
        self._set_state(ScanDevicesViewModelState.INIT)

    def cancel(self):
        self.close_required.emit()
        
    def accept(self) -> bool:
        if self._devices is None:
            return False
        accepted_devices = [device_cfg for device_cfg in self._devices if device_cfg.get_selected()]
        
        if len(accepted_devices) == 0:
            self._dialogProvider.information("Aucun appareil sélectionné", "Veuillez sélectionner au moins un appareil.")
            return False

        motor_bus = [discovered_device._device 
                        for discovered_device in accepted_devices 
                        if isinstance(discovered_device._device, mirMotorBusConfiguration)]
        if len(motor_bus) > 1:
            self._dialogProvider.information("Plusieurs ports moteurs sélectionnés",
                                             "Sélectionnez un seul port moteur.")
            return False
        self._accepted_config = mirRobotConfig()
        if len(motor_bus) == 1:
            self._accepted_config.motor_bus = motor_bus[0]
        sensors = {discovered_device._key : discovered_device._device 
                        for discovered_device in accepted_devices 
                        if isinstance(discovered_device._device, mirSensorConfiguration)}
        self._accepted_config.sensors = sensors    
        # ébauche de la structure du robot : socle + un module à placer par moteur et par caméra détectés
        motor_types = {motor: module_type
                       for device in accepted_devices if isinstance(device, DiscoveredMotorBusViewModel)
                       for motor, _ in device.motors() if (module_type := device.motor_type(motor)) is not None}
        sensor_types = {device.key(): (device.device_configuration().sensor_type, module_type)
                        for device in accepted_devices
                        if isinstance(device, DiscoveredSensorViewModel) and (module_type := device.module_type()) is not None}
        self._accepted_config.structure = initial_structure(_get_catalog(), motor_types, sensor_types)

        return True
        
    def execute_observations_selection(self, open_view: Callable):
        vm = ObservationsSelectionViewModel(self._dialogProvider, self._accepted_config)
        with vm:
            open_view(vm)
        if vm.accepted():   
            self._accepted_config.set_observations_from_observables(vm.get_selected_observables())
            self._accepted = True
            self.close_required.emit()

    def get_accepted_configuration(self) -> mirRobotConfig | None:
        if hasattr(self, "_accepted_config"):
            return self._accepted_config
        return None
            
    def execute_configure_device(self, open_view: Callable, device: DiscoveredDeviceViewModel):
        try:
            cfg = device.device_configuration()
            if isinstance(cfg, mirSensorConfiguration):
                vm = SensorConfigurationViewModel(self._dialogProvider, device.key(), cfg)
                with vm:
                    open_view(vm)
                    if vm.sensor_reset_required():
                        self._dialogProvider.information("Reset requis", "Le capteur va être réinitialisé pour prendre en compte les changements.\r\nUn scan sera ensuite relancé")
                        self._reset_sensors({device.key(): cfg})
            elif isinstance(cfg, mirMotorBusConfiguration):
                vm = MotorConfigureIDsViewModel(self._dialogProvider, cfg)
                with vm:
                    open_view(vm)
                if vm.has_id_changed():                    
                    self._dialogProvider.information("Changement ID", "Un ou plusieurs IDs moteurs ont été modifiés.\r\nUn scan va être relancé")
                    self.scan_devices()
        except Exception as e:
            self._dialogProvider.exception(e)

    def _reset_sensors(self, sensors: dict[str, mirSensorConfiguration]):
        self._set_state(ScanDevicesViewModelState.RESET_SENSORS)
        self.status_changed.emit("Réinitialisation capteur en cours...")
        self._worker_reset.run(
            lambda: self._do_reset_sensors(sensors),
            self._on_reset_sensors_finished,
            self._on_reset_sensors_failed,
        )

    def _do_reset_sensors(self, sensors : dict[str, mirSensorConfiguration]) -> None:
        reset_sensors(sensors, on_progress=lambda s: print(s))

    def _on_reset_sensors_finished(self, _) -> None:
        self.scan_devices()

    def _on_reset_sensors_failed(self, error: Exception) -> None:
        self._dialogProvider.error("Erreur reset capteurs", str(error))
        self._set_state(ScanDevicesViewModelState.SCAN_COMPLETED)