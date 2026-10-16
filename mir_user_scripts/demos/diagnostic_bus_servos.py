"""
Diagnostic du bus des servos, EN LECTURE SEULE : rien n'est écrit dans les servos.
Interroge chaque ID (0 à 253) un par un et affiche ceux qui répondent, avec leur position.
L'application MIR doit être fermée (elle garde le port ouvert).

  python diagnostic_bus_servos.py                     # premier port trouvé, 1 Mbit/s
  python diagnostic_bus_servos.py /dev/cu.usbmodemXXX  # port choisi
  python diagnostic_bus_servos.py /dev/cu.usbmodemXXX --tous-baudrates   # les 8 vitesses du STS3215 (≈ 70 s)

Brancher UN SEUL module à la fois pour savoir quel ID porte son servo : deux servos avec le même ID répondent
ensemble et rendent tout le bus illisible.
"""
import argparse
import time
import scservo_sdk as scs
from mir_devices.communication_ports import find_acm_serial_ports

BAUDRATES = (1_000_000, 500_000, 250_000, 128_000, 115_200, 76_800, 57_600, 38_400)
PRESENT_POSITION, LOCK = 56, 55

parser = argparse.ArgumentParser()
parser.add_argument("port", nargs="?")
parser.add_argument("--tous-baudrates", action="store_true")
args = parser.parse_args()
port = args.port or next(iter(find_acm_serial_ports()), None)
if port is None:
    raise SystemExit("aucun port série trouvé")

ph = scs.PortHandler(port)
pk = scs.PacketHandler(0)
if not ph.openPort():
    raise SystemExit(f"impossible d'ouvrir {port} (application MIR encore ouverte ?)")
print(f"port {port}")
trouves = []
for baud in (BAUDRATES if args.tous_baudrates else BAUDRATES[:1]):
    ph.setBaudRate(baud)
    t0 = time.time()
    for i in range(254):
        _, comm, _ = pk.ping(ph, i)
        if comm == scs.COMM_SUCCESS:
            pos, c1, _ = pk.read2ByteTxRx(ph, i, PRESENT_POSITION)
            lock, c2, _ = pk.read1ByteTxRx(ph, i, LOCK)
            trouves.append((baud, i))
            print(f"  ID {i:3d} à {baud} bit/s · position {pos if c1 == 0 else '?'} · Lock {lock if c2 == 0 else '?'}")
    print(f"{baud} bit/s : balayé en {time.time() - t0:.1f} s")
ph.closePort()
print(f"{len(trouves)} servo(s) trouvé(s)" if trouves else "aucun servo ne répond")
