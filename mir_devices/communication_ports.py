import platform
from serial import Serial
import threading
import time
from queue import Queue
from PySide6.QtCore import QObject
import socket
from concurrent.futures import Future
from pathlib import Path

# Préfixes des ports série selon le type d'adaptateur USB :
#   ACM : périphérique USB CDC (carte des servos Feetech) -> Linux /dev/ttyACM*, macOS /dev/cu.usbmodem*
#   USB : convertisseur USB-série (FTDI, CP210x, CH340 : ESP32) -> Linux /dev/ttyUSB*, macOS /dev/cu.usbserial-*...
# Sur macOS on prend les /dev/cu.* : l'ouverture d'un /dev/tty.* attend le signal DCD et peut bloquer.
ACM_PORT_PREFIXES = ("/dev/ttyACM", "/dev/cu.usbmodem")
USB_PORT_PREFIXES = ("/dev/ttyUSB", "/dev/cu.usbserial", "/dev/cu.wchusbserial", "/dev/cu.SLAB_USBtoUART")

def find_available_ports(filter: str|None = None):
    from serial.tools import list_ports  # Part of pyserial library

    if platform.system() == "Windows":
        # List COM ports using pyserial
        ports = [port.device for port in list_ports.comports()]
    else:  # Linux/macOS
        # List /dev/tty* (et /dev/cu* sur macOS) ports for Unix-based systems
        ports = [str(path) for path in Path("/dev").glob("tty*")]
        ports += [str(path) for path in Path("/dev").glob("cu.*")]
    return sorted(ports)

def find_usb_serial_ports():
    if platform.system() == "Windows":
        return find_available_ports()
    return [port for port in find_available_ports() if port.startswith(USB_PORT_PREFIXES)]

def find_acm_serial_ports():
    if platform.system() == "Windows":
        return find_available_ports()
    return [port for port in find_available_ports() if port.startswith(ACM_PORT_PREFIXES)]

def find_all_serial_ports():
    if platform.system() == "Windows":
        return find_available_ports()
    return [port for port in find_available_ports() if port.startswith(ACM_PORT_PREFIXES + USB_PORT_PREFIXES)]

def serial_get_available_ports() -> list[str]:
    return find_all_serial_ports()

class CommPort(QObject):
    def __init__(self, end_of_line:str="\n", command_prefix="#", connect_timeout=5.0, command_timeout=1.0):
        self._end_of_line = end_of_line
        self._end_of_line_bytes = bytes(end_of_line, 'utf-8')
        self._connect_timeout = connect_timeout
        self._command_timeout = command_timeout
        self._command_prefix = command_prefix
        self._queue = Queue()
        self._thread = None
        self._stop = threading.Event()

    def _open(self):
        pass
    
    def _close(self):
        pass

    def open(self):
        self._open()
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        self._queue.put(None)  # débloquer le worker
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        self._close()

    def write_line(self, command: str):
        pass

    def read_line(self) -> str:
        return ""

    def _worker_loop(self):
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:  # signal d'arrêt
                break
            command, future = item
            try:
                result = self._execute_command(command)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)

    def _execute_command(self, command: str) -> str:
        self.write_line(command)
        return self.read_line()

    def send_command(self, command: str) -> str:
        """Bloquant — pour les appels ponctuels (connect, config...)"""
        #return self.submit_command(command).result(timeout=self._timeout + 0.5)
        return self._execute_command(command)
    
    def submit_command(self, command: str) -> Future:
        """Non bloquant — retourne un Future immédiatement"""
        if not self._thread or not self._thread.is_alive():
            raise ConnectionError("Non connecté")
        future = Future()
        self._queue.put((command, future))
        return future

#========= Serie ===========================================================
class SerialPort(CommPort):
    
    def __init__(self, port, baudrate=115200, end_of_line:str="\n", command_prefix="#", 
                 connect_timeout:float=5.0, command_timeout:float=1.0, enable_rts_dtr=True, empty_loop:bool=False):
        super().__init__(end_of_line, command_prefix=command_prefix, connect_timeout=connect_timeout, command_timeout=command_timeout)
        self.ser = Serial()
        self.ser.port = port
        self.ser.baudrate = baudrate
        self._enable_rts_dtr = enable_rts_dtr
        self._empty_loop = empty_loop
        
    # --- Ouverture / Fermeture ------------------------------------------------
    def _open(self):
        if self.ser.is_open:
            return
        self.ser.timeout = self._connect_timeout
        self.ser.dtr = self._enable_rts_dtr
        self.ser.rts = self._enable_rts_dtr
        self.ser.open()
        if self._empty_loop:        
            self.ser.timeout = 1.0
            start = time.time()
            quiet_time = 0
            while time.time() - start < 15.0:     # timeout de sécurité 10s
                time.sleep(0.1)
                if self.ser.in_waiting == 0:
                    quiet_time += 0.1
                    if quiet_time >= 1.0:        # 1s de silence → on considère que c’est fini
                        break
                else:
                    bytes = self.ser.read(self.ser.in_waiting)
                    str = bytes.decode('utf-8')
                    print(f"{str}", end="", flush=True)
                    quiet_time = 0
            time.sleep(0.1)
            self.ser.reset_input_buffer()
        self.ser.timeout = self._command_timeout
            
    def _close(self):
        if self.ser.is_open:
            self.ser.close()  # débloque read()

    # --- API utilisateur -------------------------------------------------------

    #génère une exception sur time out
    def read_line(self)->str:
        bytes = self.ser.read_until(self._end_of_line_bytes)
        str = bytes.decode('utf-8')
        str = str.strip()
        return str

    def write_line(self, command: str):
        command += self._end_of_line
        data = command.encode()
        self.ser.write(data)


#========= TCP ===========================================================
class TcpPort(CommPort):
    def __init__(self, host: str, port: int, end_of_line: str = "\n", command_prefix: str = "#", 
                 connect_timeout: float = 5.0, command_timeout: float = 0.25):
        super().__init__(end_of_line, command_prefix=command_prefix, connect_timeout=connect_timeout, command_timeout=command_timeout)
        self.host = host
        self.port = port
        self.sock = None

    def _open(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self._connect_timeout)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(self._command_timeout)

    def _close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def write_line(self, command: str):
        if not self.sock:
            raise ConnectionError("Non connecté")
        message = command.strip() + self._end_of_line
        self.sock.sendall(message.encode("utf-8"))

    def read_line(self) -> str:
        if not self.sock:
            raise ConnectionError("Non connecté")
        data = b""
        while True:
            chunk = self.sock.recv(256)
            if not chunk:
                raise ConnectionError("Connexion fermée par le capteur")
            data += chunk
            if self._end_of_line_bytes in data:
                line, _, _ = data.partition(self._end_of_line_bytes)
                return line.decode("utf-8").strip()

if __name__ == '__main__':
    print("===== opening port...")
    #esp32-wroom enable_rts_dtr = True, empty_loop = False
    #esp32-cam enable_rts_dtr = False, empty_loop = True
    serial = SerialPort("/dev/ttyUSB0", baudrate=115200, enable_rts_dtr=False, empty_loop=True)
    serial.open()
    print("\r\n\r\n====== port opened, reading configuration")
    serial.write_line("get_configuration")
    line = serial.read_line()
    print(line)

