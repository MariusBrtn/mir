from enum import Enum, auto
from pathlib import Path
import os
import re
import subprocess
import sysconfig
from typing_extensions import override
from PySide6.QtCore import Signal
from dataclasses import dataclass
from mir_utils.ui.view_model_base import VMAction, ViewModelBase
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.concurrency import BackgroundWorker
from mir_devices.communication_ports import find_usb_serial_ports
from mir_devices.esp_sensors import EspSensor, EspSensorSimulationConfiguration
from mir_esp_deploy.ble_provisioning import BleProvisioner

# Chemin par défaut du firmware.
DEFAULT_FIRMWARE_PATH: Path = (
    Path(__file__).resolve().parent.parent
    / "esp32_sensor"
    / ".pio"
    / "build"
    / "esp32dev"
    / "firmware.bin"
)

AP_KEYS: tuple[str, ...] = ("ap1_ssid", "ap1_pwd", "ap2_ssid", "ap2_ssid")

AVAILABLE_BAUD_RATES: list[int] = [921600, 1000000]


class DeployVMAction(Enum):
    FLASH = auto()
    READ_CFG = auto()
    WRITE_CFG = auto()
    REFRESH_PORTS = auto()

class DeployMode(Enum):
    SERIAL = auto()
    BLE = auto()

@dataclass
class SerialConfig:
    flash_baud_rate : int
    enable_rts_dtr: bool
    empty_loop: bool
    read_write_baud_rate: int = 115200

class Esp32DeployViewModel(ViewModelBase[DeployVMAction]):
    status_changed = Signal(str)               # message d'état
    config_loaded = Signal(dict)               # configuration AP lue
    log_added = Signal(str)                    # logs
    busy_changed = Signal(bool)                # état occupé
    mode_changed = Signal(int)          # mode de connexion
    
    def __init__(self, dialogProvider: IDialogProvider):
        super().__init__(dialogProvider)
        self._selected_port: str = ""
        self._firmware_path: str = str(DEFAULT_FIRMWARE_PATH)
        self._available_ports: list[str] = []
        self._busy: bool = False
        self._worker = BackgroundWorker()
        self._bin_dir = Path(__file__).parent / "bin"
        # Actions exposées à la vue
        self._actions[DeployVMAction.FLASH] = VMAction(
            "Flasher le firmware",
            "Flash le firmware via esptool sur le port sélectionné",
        )
        self._actions[DeployVMAction.READ_CFG] = VMAction(
            "Lire la configuration Wi-Fi",
            "Lit la configuration des identifiants Wi-Fi depuis l'ESP32",
        )
        self._actions[DeployVMAction.WRITE_CFG] = VMAction(
            "Appliquer la configuration Wi-Fi",
            "Envoie la configuration des identifiants Wi-Fi à l'ESP32",
        )
        self._actions[DeployVMAction.REFRESH_PORTS] = VMAction(
            "Rafraîchir les ports",
            "Recherche les ports série disponibles",
        )
   
        self._serial_configurations : dict[str, SerialConfig] = {
            "esp32-wroom" : SerialConfig(921600, enable_rts_dtr=True, empty_loop=False),
            "esp32-cam" : SerialConfig(1000000, enable_rts_dtr=False, empty_loop=True)
        }
        self._serial_configuration_key: str = "esp32-wroom"
        self._mode = DeployMode.SERIAL
        self._refresh_action_state()

    @override
    def _enter_context(self):
        pass

    @override
    def _exit_context(self, exc_type, exc_value, traceback):
        self._worker.shutdown()

    # --------------------------------------------------------------- propriétés
    def get_selected_port(self) -> str:
        return self._selected_port

    def set_selected_port(self, port: str):
        self._selected_port = port or ""
        self._refresh_action_state()


    def set_mode(self, mode: DeployMode):
        self._mode = mode
        self.mode_changed.emit(mode.value)
        self._refresh_action_state()

    def get_mode(self):
        return self._mode

    def get_busy(self)->bool:
        return self._busy
        
    # ---------------------------------------------------------------- ports série
    def scan_ports(self) -> list[str]:
        try:
            return find_usb_serial_ports()
        except Exception:
            return []

    # ------------------------------------------------------------ vitesse flash
    def get_serial_configurations(self) -> dict[str, SerialConfig]:
        return self._serial_configurations

    def get_serial_configuration(self) -> str:
        return self._serial_configuration_key

    def set_serial_configuration(self, serial_configuration_key: str):
        self._serial_configuration_key = serial_configuration_key

    # ---------------------------------------------------------- helpers EspSensor
    def _create_serial_sensor(self) -> EspSensor:
        return EspSensor(
            "deploy",
            EspSensorSimulationConfiguration(sensor_type="esp_simulation", ip="0.0.0.0"),
        )

    # ------------------------------------------------------------ rafraîchir états
    def _set_busy(self, busy: bool):
        self._busy = busy
        self.busy_changed.emit(busy)
        self._refresh_action_state()

    def _refresh_action_state(self):
        has_port = bool(self._selected_port)
        has_firmware = bool(self._firmware_path) and Path(self._firmware_path).is_file()

        self._actions[DeployVMAction.FLASH].set_enabled(
            (not self._busy) and has_port and has_firmware
        )
        self._actions[DeployVMAction.READ_CFG].set_enabled(
            (not self._busy) and has_port
        )
        self._actions[DeployVMAction.WRITE_CFG].set_enabled(
            (not self._busy) and has_port
        )
        self._actions[DeployVMAction.REFRESH_PORTS].set_enabled(not self._busy)

    # ------------------------------------------------------------------- flash
    def flash_firmware(self):
        if not self._selected_port:
            self._dialogProvider.warning("Port non sélectionné", "Veuillez choisir un port série.")
            return
        if not self._firmware_path:
            self._dialogProvider.warning("Firmware", "Veuillez spécifier un chemin de firmware.")
            return
        bootloader = os.path.join(self._bin_dir, "bootloader.bin")
        partitions = os.path.join(self._bin_dir, "partitions.bin")
        boot_app0 = os.path.join(self._bin_dir, "boot_app0.bin")
        firmware = os.path.join(self._bin_dir, "firmware.bin")            
        if not Path(bootloader).is_file():
            self._dialogProvider.error(
                "Bootloader introuvable",
                f"Le fichier bootloader n'a pas été trouvé :\n{bootloader}",
            )
            return
        if not Path(partitions).is_file():
            self._dialogProvider.error(
                "Partitions introuvable",
                f"Le fichier partitions n'a pas été trouvé :\n{partitions}",
            )
            return
        if not Path(boot_app0).is_file():
            self._dialogProvider.error(
                "Boot app0 introuvable",
                f"Le fichier boot_app0 n'a pas été trouvé :\n{boot_app0}",
            )
            return
        if not Path(firmware).is_file():
            self._dialogProvider.error(
                "Firmware introuvable",
                f"Le fichier firmware n'a pas été trouvé :\n{self._firmware_path}",
            )
            return

        port = self._selected_port
        
        self._set_busy(True)
        self.status_changed.emit("Flash en cours...")
        flash_baud_rate = self._serial_configurations[self._serial_configuration_key].flash_baud_rate
        self._worker.run(
            lambda: self._do_flash(port, flash_baud_rate, bootloader, partitions, boot_app0, firmware),
            self._on_flash_finished,
            self._on_flash_failed,
            guard_flag_owner=self,
            guard_flag="_flash_in_progress",
        )
    
    def build_flash_command(self, port: str, baud_rate, bootloader, partitions, boot_app0, firmware) -> list[str]:
        return [
            # esptool de l'environnement de MIR (lancé depuis un raccourci, il n'est pas forcément dans le PATH)
            str(Path(sysconfig.get_path("scripts")) / "esptool"), "--chip", "esp32", "--port", port, "--baud", str(baud_rate),
            "--before", "default-reset", "--after", "hard-reset",
            "write-flash", "-z", "--flash-mode", "dio", "--flash-freq", "40m", "--flash-size", "4MB",
            "0x1000", bootloader,
            "0x8000", partitions,
            "0xe000", boot_app0,
            "0x10000", firmware,
        ]
     
    def _do_flash(self, port: str, baud_rate, bootloader, partitions, boot_app0, firmware) -> int:
        ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
        def clean_line(line: str) -> str:
            return ANSI_ESCAPE.sub('', line).strip()

        cmd = self.build_flash_command(port, baud_rate, bootloader, partitions, boot_app0, firmware)
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        if process is None or process.stdout is None:
            return -1
        for line in process.stdout:
            cleaned = clean_line(line)
            if cleaned:  # évite d'émettre des lignes vides après nettoyage
                self.log_added.emit(cleaned)
        process.wait()
        return process.returncode

        # return full_output

    def _on_flash_finished(self, output: int):
        self.log_added.emit(str(output))
        message = "Le firmware a été flashé avec succès" if output == 0 else f"Le processus a retourné une erreur : {output}"
        self.status_changed.emit(message)
        self._dialogProvider.information("Flash terminé", message)
        self._set_busy(False)

    def _on_flash_failed(self, error: Exception):
        msg = str(error)
        self.log_added.emit(msg)
        self.status_changed.emit("Échec du flash")
        self._dialogProvider.error("Échec du flash", f"Erreur : {error}")
        self._set_busy(False)

    # ---------------------------------------------------------- lecture config AP
    def read_ap_configuration(self):
        if not self._selected_port:
            self._dialogProvider.warning("Port non sélectionné", "Veuillez choisir un port série.")
            return
        self._set_busy(True)
        self.status_changed.emit("Lecture de la configuration Wi-Fi...")
        cfg = self._serial_configurations[self._serial_configuration_key]
        self._worker.run(
            lambda: self._read_ap_configuration(self._selected_port, cfg.enable_rts_dtr, cfg.empty_loop),
            self._on_read_ap_finished,
            self._on_read_ap_failed,
            guard_flag_owner=self,
            guard_flag="_read_ap_in_progress",
        )

    def _read_ap_configuration(self, port, enable_rts_dtr, empty_loop) -> dict[str, str] | None:
        self.log_added.emit(f"Connexion port série en cours : {port=}, {enable_rts_dtr=}, {empty_loop=}")
        try:
            sensor = self._create_serial_sensor()
            sensor.mir_connect_serial(port, enable_rts_dtr=enable_rts_dtr, empty_loop=empty_loop)
            self.log_added.emit("Lecture configuration ap...")
            config = sensor.read_ap_configuration()
        finally:
            return config
    
    def _on_read_ap_finished(self, output: dict[str, str] | None):
        self.log_added.emit("Lecture ap configuration terminée")
        if not output:
            self.status_changed.emit("Lecture : aucune configuration reçue")
            self._dialogProvider.warning("Lecture configuration", "L'ESP32 n'a pas renvoyé de configuration valide.")
        else:
            self.status_changed.emit("Configuration Wi-Fi lue depuis l'ESP32")
            self.config_loaded.emit(output)
            self._dialogProvider.information("Lecture configuration", "Configuration Wi-Fi lue avec succès.")        
        self._set_busy(False)

    def _on_read_ap_failed(self, error: Exception):
        msg = str(error)
        self.log_added.emit(msg)
        self.status_changed.emit("Échec lecture ap configuration")
        self._dialogProvider.error("Échec lecture ap configuration", f"Erreur : {error}")
        self._set_busy(False)

    # ---------------------------------------------------------- écriture config AP
    def write_ap_configuration(self, config: dict[str, str]):
        if not self._selected_port:
            self._dialogProvider.warning("Port non sélectionné", "Veuillez choisir un port série.")
            return
        if not config:
            self._dialogProvider.warning("Configuration vide", "Aucun identifiant Wi-Fi n'a été saisi.")
            return
        self._set_busy(True)
        self.status_changed.emit("Ecriture de la configuration Wi-Fi...")
        cfg = self._serial_configurations[self._serial_configuration_key]
        port = self._selected_port
        self._worker.run(
            lambda: self._write_ap_configuration(config, port, cfg.enable_rts_dtr, cfg.empty_loop),
            self._on_write_ap_finished,
            self._on_write_ap_failed,
            guard_flag_owner=self,
            guard_flag="_read_ap_in_progress",
        )

    def _write_ap_configuration(self, config, port, enable_rts_dtr, empty_loop):
        if self._mode == DeployMode.SERIAL:
            return self._write_ap_configuration_serial(config, port, enable_rts_dtr, empty_loop)
        else:
            return self._write_ap_configuration_ble(config)

    def _on_write_ap_finished(self, success):
        self.log_added.emit("Ecriture ap configuration terminée")
        if success:
            self.status_changed.emit("Configuration Wi-Fi envoyée à l'ESP32")
            self._dialogProvider.information("Envoi configuration", "Les identifiants Wi-Fi ont été écrits sur l'ESP32.")
        else:
            self.status_changed.emit("Échec de l'écriture de la configuration Wi-Fi")
            self._dialogProvider.error("Échec écriture", "L'ESP32 n'a pas confirmé l'écriture.")
        self._set_busy(False)

    def _on_write_ap_failed(self, error:Exception):
        msg = str(error)
        self.log_added.emit(msg)
        self.status_changed.emit("Échec écriture ap configuration")
        self._dialogProvider.error("Échec écriture ap configuration", f"Erreur : {error}")
        self._set_busy(False)

    def _write_ap_configuration_serial(self, config, port, enable_rts_dtr, empty_loop):
        self.log_added.emit(f"Connexion port série en cours : {port=}, {enable_rts_dtr=}, {empty_loop=}")
        try:
            sensor = self._create_serial_sensor()
            sensor.mir_connect_serial(port, enable_rts_dtr=enable_rts_dtr, empty_loop=empty_loop)
            self.log_added.emit("Ecriture configuration ap...")
            success = sensor.write_ap_configuration(config)
        finally:
            return success        

    def _write_ap_configuration_ble(self, config):
        ssid = config["ap1_ssid"]
        pwd = config["ap1_pwd"]
        if not ssid or not pwd or len(ssid.strip()) == 0 or len(pwd.strip()) == 0:
            raise ValueError("Configuration Wi-Fi invalide")
            
        with BleProvisioner() as prov:
            self.log_added.emit(f"Connexion BLE en cours...")
            prov.connect()
            self.log_added.emit("Ecriture configuration ap...")
            return prov.set_ap(ssid, pwd)
