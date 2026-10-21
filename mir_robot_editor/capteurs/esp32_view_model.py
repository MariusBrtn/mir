"""
Module capteur ESP32 (lidar, météo...) : installer le firmware et le faire passer sur un autre réseau Wi-Fi.

S'appuie sur l'outil mir_esp_deploy et sur le firmware esp32_sensor sans les modifier : mêmes fichiers bin/,
même protocole série (EspSensor) et même provisioning Bluetooth (BleProvisioner). En plus de l'outil d'origine :
- le réseau Wi-Fi est mémorisé sur ce PC, on ne le saisit qu'une fois ;
- par câble, l'ancien réseau passe en secours (AP2) et l'IP fixe de l'ancien réseau est remise en automatique ;
- après le redémarrage du module, on vérifie qu'il répond bien sur le réseau (découverte UDP).
"""
from __future__ import annotations
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from PySide6.QtCore import Signal
import mir_esp_deploy
from mir_utils.concurrency import BackgroundWorker
from mir_utils.persistence import Preferences
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import ViewModelBase
from mir_devices.communication_ports import find_usb_serial_ports
from mir_devices.discovery_scanner import DiscoveryScanner, DISCOVERY_PORT, REPLY_PORT, MAGIC

BIN_DIR = Path(mir_esp_deploy.__file__).resolve().parent / "bin"
# (adresse, fichier) flashés par esptool, comme dans mir_esp_deploy
IMAGES = (("0x1000", "bootloader.bin"), ("0x8000", "partitions.bin"),
          ("0xe000", "boot_app0.bin"), ("0x10000", "firmware.bin"))
FLASH_BAUD = 921600                 # carte ESP32-WROOM (DevKit)
TYPES_CAPTEUR = {"Lidar": "esp_lidar", "Météo": "esp_wheather", "Simulation": "esp_simulation"}
ATTENTE_RESEAU = 30.0               # temps laissé au module pour redémarrer et rejoindre le Wi-Fi
ATTENTE_BLUETOOTH = 90.0


def chercher_modules(timeout: float = 2.0) -> list[dict]:
    """Modules MIR qui répondent sur le réseau : [{"id", "type", "ip"}]."""
    reception = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    reception.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    reception.bind(("", REPLY_PORT))
    reception.settimeout(0.25)
    envoi = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    envoi.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    trouves: dict[str, dict] = {}
    try:
        for adresse in DiscoveryScanner().get_broadcast_addresses():
            envoi.sendto(MAGIC, (adresse, DISCOVERY_PORT))
        fin = time.time() + timeout
        while time.time() < fin:
            try:
                data, (ip, _) = reception.recvfrom(4096)
                module = json.loads(data.decode())
                trouves[module.get("ip", ip)] = module
            except (socket.timeout, ValueError):
                pass
    finally:
        envoi.close()
        reception.close()
    return list(trouves.values())


class LiaisonSerie:
    """Le module branché en USB : commandes texte du firmware (voir doc/esp32/esp_sensors_protocol.md)."""

    def __init__(self, port: str):
        from mir_devices.esp_sensors import EspSensor, EspSensorSimulationConfiguration
        self._capteur = EspSensor("esp32", EspSensorSimulationConfiguration(sensor_type="esp_simulation", ip="0.0.0.0"))
        self._capteur.mir_connect_serial(port, enable_rts_dtr=True)

    def fermer(self):
        self._capteur.mir_disconnect()

    def _repeter(self, commande, duree: float = 20.0):
        # à l'ouverture du port le module peut redémarrer : il ne répond qu'après ses essais de connexion Wi-Fi
        fin = time.time() + duree
        while True:
            reponse = commande()
            if reponse or time.time() > fin:
                return reponse
            time.sleep(0.5)

    def lire_wifi(self) -> dict[str, str]:
        reponse = self._repeter(self._capteur.read_ap_configuration)
        if not reponse:
            raise ConnectionError("le module ne répond pas : est-ce bien un module capteur MIR, avec son firmware ?")
        return reponse

    def lire_configuration(self) -> dict[str, str]:
        return self._repeter(self._capteur.read_configuration, 5.0) or {}

    def ecrire_wifi(self, reglages: dict[str, str]):
        if not self._capteur.write_ap_configuration(reglages):
            raise ConnectionError("le module n'a pas confirmé l'enregistrement du réseau Wi-Fi")

    def ecrire_configuration(self, reglages: dict[str, str]):
        if not self._capteur.write_configuration(reglages):
            raise ConnectionError("le module n'a pas confirmé l'enregistrement de sa configuration")

    def redemarrer(self):
        self._capteur._send_command("reboot")


class Esp32ViewModel(ViewModelBase):
    """Deux opérations : envoyer le réseau Wi-Fi (câble ou Bluetooth) et installer le firmware (câble)."""
    changed = Signal()
    log = Signal(str)

    def __init__(self, dialogProvider: IDialogProvider, serie=LiaisonSerie, chercher=chercher_modules):
        super().__init__(dialogProvider)
        self._serie = serie
        self._chercher = chercher
        self._worker = BackgroundWorker()
        self._preferences = Preferences("esp32")
        self.ssid: str = self._preferences.get("wifi_ssid", "")
        self.mot_de_passe: str = self._preferences.get("wifi_pwd", "")
        self.occupe = False
        self.message = "Renseignez le réseau Wi-Fi, choisissez la liaison, puis cliquez sur Envoyer le réseau Wi-Fi."

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, traceback):
        self._worker.shutdown()

    def ports(self) -> list[str]:
        return find_usb_serial_ports()

    def firmware_present(self) -> bool:
        return all((BIN_DIR / fichier).is_file() for _, fichier in IMAGES)

    # ------------------------------------------------------------------ déroulement
    def _lancer(self, fonction, message: str):
        self.occupe = True
        self.message = message
        self.changed.emit()
        self._worker.run(fonction, self._fin, self._echec)

    def _fin(self, message: str):
        self.occupe = False
        self.message = message
        self.changed.emit()

    def _echec(self, ex: Exception):
        self.occupe = False
        self.message = f"✗ {ex}"
        self.log.emit(f"échec : {ex}")
        self.changed.emit()

    def _etape(self, message: str):
        # appelé depuis le thread de travail : le message suit l'avancement
        self.message = message
        self.log.emit(message)
        self.changed.emit()

    def _memoriser(self, ssid: str, mot_de_passe: str) -> bool:
        ssid = ssid.strip()
        if not ssid:
            self._dialogProvider.information("Réseau Wi-Fi", "Saisissez le nom du réseau Wi-Fi.")
            return False
        if any(c in ssid + mot_de_passe for c in ";="):
            # le protocole série sépare les réglages par « ; » et « = »
            self._dialogProvider.information("Réseau Wi-Fi", "Le nom et le mot de passe ne doivent pas contenir « ; » ni « = ».")
            return False
        self.ssid, self.mot_de_passe = ssid, mot_de_passe
        self._preferences["wifi_ssid"] = ssid
        self._preferences["wifi_pwd"] = mot_de_passe
        return True

    # ------------------------------------------------------------------ réseau Wi-Fi
    def envoyer_wifi(self, ssid: str, mot_de_passe: str, port: str | None):
        """port : liaison par câble USB ; None : par Bluetooth."""
        if not self._memoriser(ssid, mot_de_passe):
            return
        if port:
            self._lancer(lambda: self._wifi_par_cable(port), "Connexion au module par le câble…")
        else:
            if not self.mot_de_passe:
                self._dialogProvider.information("Réseau Wi-Fi", "Par Bluetooth, le mot de passe est obligatoire. "
                                                                 "Pour un réseau ouvert, passez par le câble USB.")
                return
            self._lancer(self._wifi_par_bluetooth,
                         "Éteignez puis rallumez le module (ou appuyez sur son bouton RST) : "
                         "MIR le cherche en Bluetooth pendant 90 s…")

    def _wifi_par_cable(self, port: str) -> str:
        liaison = self._serie(port)
        try:
            self._etape("Lecture de la configuration du module…")
            ancien = liaison.lire_wifi()
            configuration = liaison.lire_configuration()
            nom = configuration.get("sensor_id", "")
            self._etape(f"Module {nom} : réseau actuel « {ancien.get('ap1_ssid', '')} ». Envoi du nouveau réseau…")
            wifi = {"ap1_ssid": self.ssid, "ap1_pwd": self.mot_de_passe}
            reglages = {}
            if ancien.get("ap1_ssid") and ancien["ap1_ssid"] != self.ssid:
                # l'ancien réseau reste en secours : le module marche encore là-bas
                wifi |= {"ap2_ssid": ancien["ap1_ssid"], "ap2_pwd": ancien.get("ap1_pwd", "")}
                reglages["ap2_ip"] = configuration.get("ap1_ip", "auto")
            if configuration.get("ap1_ip", "auto") != "auto":
                self._etape(f"IP fixe {configuration['ap1_ip']} de l'ancien réseau remplacée par une IP automatique.")
            reglages["ap1_ip"] = "auto"
            liaison.ecrire_wifi({k: v for k, v in wifi.items() if v})
            liaison.ecrire_configuration(reglages)
            liaison.redemarrer()
        finally:
            liaison.fermer()
        return self._verifier_reseau(nom)

    def _wifi_par_bluetooth(self) -> str:
        from mir_esp_deploy.ble_provisioning import BleProvisioner
        prov = BleProvisioner()
        try:
            try:
                adresse = prov.connect(timeout=ATTENTE_BLUETOOTH)
            except RuntimeError:
                raise RuntimeError("aucun module trouvé en Bluetooth. Il n'est visible que pendant 60 s après "
                                   "son démarrage : rallumez-le puis recommencez.")
            self._etape(f"Module trouvé en Bluetooth ({adresse}). Envoi du réseau Wi-Fi…")
            if not prov.set_ap(self.ssid, self.mot_de_passe):
                raise ConnectionError(f"le module n'a pas confirmé le réseau (état : {prov.last_status})")
        finally:
            try:
                prov.disconnect()
            except Exception:
                pass                # le module redémarre : la déconnexion peut échouer, c'est normal
        return self._verifier_reseau("", bluetooth=True)

    def _verifier_reseau(self, nom: str, bluetooth: bool = False) -> str:
        self._etape(f"Le module redémarre et rejoint « {self.ssid} »…")
        fin = time.time() + ATTENTE_RESEAU
        while time.time() < fin:
            modules = [m for m in self._chercher(2.0) if not nom or m.get("id") == nom]
            if modules:
                m = modules[0]
                return f"✓ Module {m.get('id', '')} ({m.get('type', '')}) connecté à « {self.ssid} », IP {m.get('ip', '')}."
        conseil = ("vérifiez le mot de passe ; si l'ancien réseau utilisait une IP fixe, passez par le câble USB"
                   if bluetooth else "vérifiez le nom et le mot de passe du réseau")
        return (f"✗ Réseau enregistré, mais le module ne répond pas sur « {self.ssid} » : {conseil}. "
                "Le PC doit être sur le même réseau.")

    # ------------------------------------------------------------------ firmware
    def installer_firmware(self, ssid: str, mot_de_passe: str, port: str, type_capteur: str, nom: str):
        if not self._memoriser(ssid, mot_de_passe):
            return
        nom = nom.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,31}", nom):
            self._dialogProvider.information("Installer le firmware", "Le nom du module : lettres, chiffres, - et _ "
                                                                      "(sans espace, 31 caractères au plus).")
            return
        if not self.firmware_present():
            self._dialogProvider.error("Installer le firmware", f"Firmware introuvable dans {BIN_DIR}")
            return
        self._lancer(lambda: self._installer(port, TYPES_CAPTEUR[type_capteur], nom),
                     "Installation du firmware (une minute environ)…")

    def _installer(self, port: str, type_capteur: str, nom: str) -> str:
        commande = [sys.executable, "-m", "esptool", "--chip", "esp32", "--port", port, "--baud", str(FLASH_BAUD),
                    "--before", "default-reset", "--after", "hard-reset",
                    "write-flash", "-z", "--flash-mode", "dio", "--flash-freq", "40m", "--flash-size", "4MB"]
        for adresse, fichier in IMAGES:
            commande += [adresse, str(BIN_DIR / fichier)]
        processus = subprocess.Popen(commande, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for ligne in processus.stdout:
            ligne = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", ligne).strip()
            if ligne:
                self.log.emit(ligne)
        if processus.wait() != 0:
            raise RuntimeError("l'installation a échoué (voir le journal) : vérifiez le câble USB (pas un câble de "
                               "charge seule) et fermez tout autre logiciel qui utilise ce port")
        self._etape("Firmware installé. Réglage du module…")
        time.sleep(2.0)
        liaison = self._serie(port)
        try:
            liaison.lire_wifi()             # attend que le module ait fini de démarrer
            liaison.ecrire_configuration({"sensor_type": type_capteur, "sensor_id": nom, "ap1_ip": "auto"})
            wifi = {"ap1_ssid": self.ssid, "ap1_pwd": self.mot_de_passe}
            liaison.ecrire_wifi({k: v for k, v in wifi.items() if v})
            liaison.redemarrer()
        finally:
            liaison.fermer()
        return self._verifier_reseau(nom)
