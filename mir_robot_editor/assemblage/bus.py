"""
Accès au matériel pendant le guide de montage : un bus de servos (détecter, changer l'ID, calibrer) et la recherche
des capteurs réseau. BusFeetech parle aux vrais servos ; BusSimule permet de dérouler le guide sans matériel (tests).
"""
from __future__ import annotations
import threading
from functools import wraps
from typing import Protocol
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from mir_devices.communication_ports import find_acm_serial_ports

ID_SERVO_NEUF = 1           # ID d'un servo sortant d'usine
# pendant le montage, les servos déjà montés sont « mis de côté » sur des ID réservés (200, 201...), qu'aucun robot
# n'utilise : un servo qu'on branche (neuf, ou réutilisé avec n'importe quel ancien ID) ne peut pas avoir le même ID
# qu'un servo déjà monté. Ils reçoivent leur ID définitif à la fin du montage.
ID_DE_COTE = 200
MILIEU = 2047               # position brute au milieu de la course, après la mise à zéro (encodeur 12 bits)
PAS_PAR_TOUR = 4096


class BusAssemblage(Protocol):
    def ouvrir(self, moteurs: dict[str, int]) -> None: ...     # {nom du moteur: ID attendu}
    def fermer(self) -> None: ...
    def ids_presents(self, candidats: set[int]) -> set[int]: ...    # parmi ces ID, ceux qui répondent
    def changer_id(self, moteur: str, ancien_id: int, nouvel_id: int) -> None: ...
    def debut_calibration(self, moteur: str) -> None: ...      # couple coupé, calibration remise à zéro
    def mettre_au_milieu(self, moteur: str) -> int: ...        # position actuelle = milieu ; renvoie l'offset
    def position(self, moteur: str) -> int: ...                # position brute
    def fin_calibration(self, moteur: str, offset: int, mini: int, maxi: int) -> None: ...
    def ecrire_reglages(self, moteur: str, reglages: dict[str, int]) -> None: ...  # registres : mode, P, I, D, couple


def ports_disponibles() -> list[str]:
    return find_acm_serial_ports()


def _verrouille(methode):
    """Un seul échange à la fois sur le port série (la recherche des servos tourne en arrière-plan)."""
    @wraps(methode)
    def appel(self, *args, **kwargs):
        with self._verrou:
            return methode(self, *args, **kwargs)
    return appel


class BusFeetech:
    """Servos STS3215 via LeRobot. Les écritures en EEPROM (ID, calibration) sont faites registre déverrouillé.

    Les servos sont cherchés un par un (ping de chaque ID) : avec un ping général (broadcast), tous les servos
    répondent en même temps et leurs réponses se mélangent dès qu'il y en a plusieurs."""

    def __init__(self, port: str):
        self._port = port
        self._bus = None
        self._ids: dict[str, int] = {}
        self._verrou = threading.RLock()

    @_verrouille
    def ouvrir(self, moteurs: dict[str, int]) -> None:
        from lerobot.motors.feetech import FeetechMotorsBus
        self._ids = dict(moteurs)
        self._bus = FeetechMotorsBus(self._port, {nom: Motor(i, "sts3215", MotorNormMode.DEGREES)
                                                  for nom, i in moteurs.items()})
        self._bus.connect(handshake=False)      # les moteurs ne sont pas encore branchés

    @_verrouille
    def fermer(self) -> None:
        if self._bus is not None and self._bus.is_connected:
            self._bus.disconnect(disable_torque=False)
        self._bus = None

    def ids_presents(self, candidats: set[int]) -> set[int]:
        presents = set()
        for i in sorted(candidats):
            with self._verrou:          # verrou pris ID par ID : la lecture des positions n'attend pas toute la recherche
                if self._bus is None:
                    break
                if self._bus.ping(i) is not None:
                    presents.add(i)
        return presents

    @_verrouille
    def changer_id(self, moteur: str, ancien_id: int, nouvel_id: int) -> None:
        # setup_motor écrit dans le servo l'ID de la table des moteurs du bus
        self._bus.motors[moteur].id = nouvel_id
        self._ids[moteur] = nouvel_id
        self._bus.setup_motor(moteur, initial_baudrate=self._bus.default_baudrate, initial_id=ancien_id)
        # setup_motor laisse l'EEPROM déverrouillée : chaque réglage écrit ensuite (à chaque connexion) l'userait
        self._bus.write("Lock", moteur, 1)

    @_verrouille
    def debut_calibration(self, moteur: str) -> None:
        self._bus.write("Torque_Enable", moteur, 0)
        self._bus.write("Lock", moteur, 0)
        self._bus.write("Operating_Mode", moteur, 0)
        self._bus.reset_calibration([moteur])

    @_verrouille
    def mettre_au_milieu(self, moteur: str) -> int:
        return int(self._bus.set_half_turn_homings([moteur])[moteur])

    @_verrouille
    def position(self, moteur: str) -> int:
        return int(self._bus.read("Present_Position", moteur, normalize=False))

    @_verrouille
    def fin_calibration(self, moteur: str, offset: int, mini: int, maxi: int) -> None:
        self._bus.write_calibration({moteur: MotorCalibration(id=self._ids[moteur], drive_mode=0, homing_offset=offset,
                                                              range_min=mini, range_max=maxi)}, cache=False)

    @_verrouille
    def ecrire_reglages(self, moteur: str, reglages: dict[str, int]) -> None:
        """Écrit les réglages (registres) puis reverrouille l'EEPROM : ils sont conservés hors tension."""
        for registre, valeur in reglages.items():
            self._bus.write(registre, moteur, int(valeur))
        self._bus.write("Lock", moteur, 1)


class BusSimule:
    """Bus fictif pour dérouler le guide sans matériel : brancher() simule l'ajout d'un servo neuf,
    tourner() simule le mouvement à la main."""

    def __init__(self):
        self._ids: dict[str, int] = {}
        self.servos: dict[int, int] = {}       # ID présent sur le bus -> position brute
        self._offsets: dict[int, int] = {}
        self.calibrations: dict[str, tuple[int, int, int]] = {}

    def brancher(self, id_servo: int = ID_SERVO_NEUF, position: int = 3000) -> None:
        self.servos[id_servo] = position

    def tourner(self, moteur: str, position: int) -> None:
        self.servos[self._ids[moteur]] = position + self._offsets.get(self._ids[moteur], 0)

    def ouvrir(self, moteurs: dict[str, int]) -> None:
        self._ids = dict(moteurs)

    def fermer(self) -> None:
        pass

    synchrone = True    # pas de recherche en arrière-plan (tests)

    def ids_presents(self, candidats: set[int]) -> set[int]:
        return set(self.servos) & set(candidats)

    def changer_id(self, moteur: str, ancien_id: int, nouvel_id: int) -> None:
        self.servos[nouvel_id] = self.servos.pop(ancien_id)
        self._offsets[nouvel_id] = self._offsets.pop(ancien_id, 0)
        self._ids[moteur] = nouvel_id

    def debut_calibration(self, moteur: str) -> None:
        self._offsets[self._ids[moteur]] = 0

    def mettre_au_milieu(self, moteur: str) -> int:
        i = self._ids[moteur]
        self._offsets[i] = self.servos[i] - MILIEU
        return self._offsets[i]

    def position(self, moteur: str) -> int:
        i = self._ids[moteur]
        return self.servos[i] - self._offsets.get(i, 0)

    def fin_calibration(self, moteur: str, offset: int, mini: int, maxi: int) -> None:
        self.calibrations[moteur] = (offset, mini, maxi)

    def ecrire_reglages(self, moteur: str, reglages: dict[str, int]) -> None:
        self.reglages = getattr(self, "reglages", {})
        self.reglages[moteur] = dict(reglages)


def chercher_cameras(timeout: float = 2.0) -> dict[str, str]:
    """Caméras réseau qui répondent : {identifiant: adresse IP}."""
    from mir_devices.discovery_scanner import DiscoveryScanner
    from mir_devices.mir_sensor import mirPiCameraConfiguration
    scanner = DiscoveryScanner()
    # mêmes réglages que DiscoveryScanner.run(), mais sans le scan des ports série (le bus du guide est ouvert)
    scanner._timeout = timeout
    scanner._cam_id = scanner._esp_lidar_id = scanner._esp_wheather_id = scanner._esp_simulation_id = 0
    scanner._progress_callback = None
    scanner._result_info = ""
    return {cle: cfg.ip for cle, cfg in scanner._scan_ip_devices().items()
            if isinstance(cfg, mirPiCameraConfiguration) and cfg.ip}
