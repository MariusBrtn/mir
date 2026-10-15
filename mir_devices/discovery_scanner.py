import time
import json
import socket
from typing import Callable, Optional
import itertools
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
import ipaddress
import psutil
from dataclasses import dataclass
from lerobot.motors import MotorNormMode
from mir_devices.mir_feetech_motor_bus import mirFeetechMotorsBus, mirMotorBusConfiguration, mirMotor
from mir_devices.mir_sensor import (mirPiCameraConfiguration,
                                    mirSensorConfiguration, 
                                    EspSensorSimulationConfiguration, 
                                    EspSensorWheatherConfiguration, 
                                    EspSensorLidarConfiguration)

DISCOVERY_PORT = 5679           # port d'écoute des équipements
REPLY_PORT     = 5678           # port sur lequel le PC reçoit les réponses
MAGIC          = b"mir_discover_request\n"

"""
un équipement répond à un requête de découverte avec :
un identificateur de type (par exemple pi_camera, esp_weather, esp_lidar, esp_simulation, pi_lidar)
les identificateurs précisent <type_d_hote>_<type_de_capteur>
par exemple pi_lidar est un capteur lidar embarqué dans un raspberry pi zero 2w
esp_lidar est un capteur lidar embarqué dans un esp32
pi_camera est une caméra embarquée dans un raspberry pi zero 2w
cet identifiant servira à construire la bonne instance de classe, héritant de miSensor, par exemple PiCamera pour pi_camera
son id (exemple camera_front, simulation, ...)
l'id sera la clé du dictionnaire de mirSensor accédée par le robot
"""

@dataclass
class DiscoveryScannerResult:
    sensors:dict[str, mirSensorConfiguration]
    motor_buses:list[mirMotorBusConfiguration]

class DiscoveryScanner():
    def __init__(self):
        self._future = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        
    # ─── Scanner ─────────────────────────────────────────────────────────────────
    def _parse_ip_response(self, ip: str, data: bytes) -> tuple[str | None, mirSensorConfiguration | None]:
        try:
            payload = json.loads(data.decode())
            device_type = payload["type"]
            if device_type == mirPiCameraConfiguration.SENSOR_TYPE:
                self._cam_id += 1
                return f"cam_{self._cam_id}", mirPiCameraConfiguration(
                    sensor_type=device_type,
                    ip=ip,
                    width=payload["width"],
                    height=payload["height"],
                    fps=int(1000000/payload["fps"])
                )
            elif device_type == "pi_lidar":
                logger.warning("pi_lidar non implémenté")    
            elif device_type == EspSensorLidarConfiguration.SENSOR_TYPE:
                self._esp_lidar_id += 1
                return f"esp_lidar_{self._esp_lidar_id}", EspSensorLidarConfiguration(
                    sensor_type=device_type,
                    ip=ip,
                )
            elif device_type == EspSensorWheatherConfiguration.SENSOR_TYPE:
                self._esp_wheather_id += 1
                return f"esp_wheather_{self._esp_wheather_id}", EspSensorWheatherConfiguration(
                    sensor_type=device_type,
                    ip=ip,
                )
            elif device_type == EspSensorSimulationConfiguration.SENSOR_TYPE:
                self._esp_simulation_id += 1
                return f"esp_simulation_{self._esp_simulation_id}", EspSensorSimulationConfiguration(
                    sensor_type=device_type,
                    ip=ip,
                )
            return None, None
        except Exception as e:
            logger.warning(f"[Scanner] Parse échoué pour {ip} : {e!r}")
            return None, None

    def get_broadcast_addresses(self) -> list[str]:
        """Renvoie la liste des adresses de broadcast dirigé pour toutes
        les interfaces IPv4 actives (hors loopback). Compatible Linux, Windows et macOS."""
        broadcasts: set[str] = set()
        try:
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
        except Exception as e:
            logger.warning(f"Erreur lors de la lecture des interfaces réseau : {e}")
            return ["255.255.255.255"]

        for ifname, net_stats in stats.items():
            if not net_stats.isup:
                continue
            if ifname not in addrs:
                continue

            for addr in addrs[ifname]:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    if addr.broadcast:
                        broadcasts.add(addr.broadcast)
                    elif addr.netmask:
                        try:
                            net = ipaddress.IPv4Network(f"{addr.address}/{addr.netmask}", strict=False)
                            broadcasts.add(str(net.broadcast_address))
                        except ValueError as e:
                            logger.warning(f"Impossible de calculer le broadcast pour {ifname} ({addr.address}): {e}")

        if not broadcasts:
            broadcasts.add("255.255.255.255")

        return list(broadcasts)

    def _scan_ip_devices(self) -> dict[str, mirSensorConfiguration]:
        self._stop_scan = False
        broadcasts = self.get_broadcast_addresses()
        if not broadcasts:
            message = "Aucune interface réseau active trouvée pour le scan."
            logger.warning(message)
            self._result_info += message
            return {}

        devices: dict[str, mirSensorConfiguration] = {}
        seen: set[str] = set()

        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        recv_sock.bind(("", REPLY_PORT))
        recv_sock.settimeout(0.25)

        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        send_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        try:
            for broadcast in broadcasts:
                try:
                    send_sock.sendto(MAGIC, (broadcast, DISCOVERY_PORT))
                except OSError as e:
                    logger.warning(f"Échec d'envoi sur {broadcast}: {e}")

            deadline = time.time() + self._timeout
            while time.time() < deadline and not self._stop_scan:
                try:
                    data, (ip, _) = recv_sock.recvfrom(4096)
                    if data == MAGIC:
                        continue
                    device_id, device = self._parse_ip_response(ip, data)
                    if device and device_id:
                        if device_id in devices:
                            logger.warning(f"Device {device_id} already exists, skipping")
                            continue
                        seen.add(ip)
                        devices[device_id] = device
                        if self._progress_callback is not None:
                            self._progress_callback(device)
                except socket.timeout:
                    pass
        except Exception as e:
            message = f"Le scan des appareils réseau a échoué : {e}\r\n"
            logger.error(message)
            self._result_info += message
        finally:
            send_sock.close()
            recv_sock.close()

        return devices         
    
    def stop_scan(self):
        self._stop_scan = True
        
    def _scan_motors(self) -> list[mirMotorBusConfiguration]:
        buses = []
        for port, motors_ids in mirFeetechMotorsBus.mir_scan_motor_buses():
            motors = {f"joint_{index+1}": mirMotor(id=id, model="sts3215", norm_mode=MotorNormMode.DEGREES) for index, id in enumerate(motors_ids)}        
            cfg = mirMotorBusConfiguration(motor_port=port, motors=motors, calibration={})
            if self._progress_callback is not None:
                self._progress_callback(cfg)
            buses.append(cfg)
        return buses
    
    def _execute_all_scans(self) -> DiscoveryScannerResult:
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_wifi   = ex.submit(self._scan_ip_devices)
            f_motors = ex.submit(self._scan_motors)
            return DiscoveryScannerResult(f_wifi.result(), f_motors.result())  

    def run(self, 
            on_done_callback: Optional[Callable] = None, 
            timeout:float = 3.0,  
            progress_callback: Callable[[mirSensorConfiguration|mirMotorBusConfiguration], None]|None=None) -> None:
    
        if self._future is not None and not self._future.done():
            raise RuntimeError("Un scan est déjà en cours. Attendez la fin ou appelez stop_scan() avant de relancer.")
        self._timeout = timeout
        self._cam_id = 0
        self._esp_lidar_id = 0
        self._esp_wheather_id = 0
        self._esp_simulation_id = 0
        self._progress_callback = progress_callback
        self._result_info = ""
        self._future = self._executor.submit(self._execute_all_scans)
        if on_done_callback:
            def callback_wrapper(f):
                try:
                    # Tente de récupérer le résultat filtré
                    res = self._full_result()
                    on_done_callback(res)
                except Exception as e:
                    # Passe l'exception si le scan ou le filtrage a échoué
                    on_done_callback(e)
            self._future.add_done_callback(callback_wrapper)


    def _full_result(self, timeout=None) -> tuple[DiscoveryScannerResult, str]:
        if self._future is None: 
            raise RuntimeError("La tâche n'a pas été lancée. Appelez run() d'abord")
        devices: DiscoveryScannerResult = self._future.result(timeout=timeout)
        return (devices, self._result_info)
    
    def wait(self, timeout: Optional[float] = None) -> tuple[DiscoveryScannerResult, str]:
        if self._future is None: 
            raise RuntimeError("La tâche n'a pas été lancée. Appelez run() d'abord")
        return self._full_result(timeout)    

    def done(self) -> bool:
        if self._future is None:
            raise RuntimeError("La tâche n'a pas été lancée. Appelez run() d'abord")
        return self._future.done()

    def result(self)  -> tuple[DiscoveryScannerResult, str]:
        if self._future is None: 
            raise RuntimeError("La tâche n'a pas été lancée. Appelez run() d'abord")
        if not self._future.done():
            raise RuntimeError("La tâche n'est pas encore terminée")
        return self._full_result()    
    
def animate(interval=0.1):
    n = 0
    try:
        for c in itertools.cycle(r'\|/|'):
            t = '.' * n + ' ' * (10 - n)
            n = (n + 1) % 11
            print(f"\r{c} recherche en cours{t}", end = ' ', flush=True)
            time.sleep(0.1)
            yield
    finally:
        print(f"\r{' ' * 40}\r", end=' ', flush=True)

if __name__ == "__main__":
    def callback(device: mirMotorBusConfiguration|mirSensorConfiguration):
        print(f"Device found: {str(device)}")

    scanner = DiscoveryScanner()
    print("Recherche en cours...\r\n")
    scanner.run()
    while not scanner.done():
        time.sleep(0.5)
    print("Recherche terminée.")        
    result, message = scanner.result()
    print("\r\n=== équipements découverts ===")
    for device_id, device in result.sensors.items():
        print(f"{device_id} : {str(device)}")
    for motor_bus in result.motor_buses:
        print(f"moteurs : {str(motor_bus)}")

