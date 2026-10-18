"""
Changer l'ID d'un servo branché seul sur le bus, sans robot ni configuration : remettre en ordre un servo dont on ne
connaît pas l'ID (servo neuf, réutilisé, ou resté sur un ID réservé du guide de montage).
"""
from __future__ import annotations
import time
from typing import Protocol
from PySide6.QtCore import Signal
from mir_utils.concurrency import BackgroundWorker
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import ViewModelBase
from mir_robot_editor.assemblage.bus import ID_DE_COTE, ports_disponibles

BAUDRATE = 1_000_000
ID_MIN, ID_MAX = 1, 253
REG_ID, REG_LOCK = 5, 55        # registres du STS3215 (EEPROM : ID, verrou)


class BusServos(Protocol):
    def ouvrir(self, port: str) -> None: ...
    def fermer(self) -> None: ...
    def ids_presents(self) -> list[int]: ...                    # tous les ID qui répondent (0 à 253)
    def changer_id(self, ancien_id: int, nouvel_id: int) -> None: ...


class BusServosFeetech:
    """Accès direct aux servos (SDK Feetech) : un ping par ID, puis écriture de l'ID registre déverrouillé."""

    def __init__(self):
        self._port = None
        self._paquets = None

    def ouvrir(self, port: str) -> None:
        import scservo_sdk as scs
        self._port = scs.PortHandler(port)
        self._paquets = scs.PacketHandler(0)
        if not self._port.openPort():
            self._port = None
            raise ConnectionError(f"impossible d'ouvrir {port} : le port est peut-être utilisé par le robot connecté")
        self._port.setBaudRate(BAUDRATE)

    def fermer(self) -> None:
        if self._port is not None:
            self._port.closePort()
            self._port = None

    def ids_presents(self) -> list[int]:
        import scservo_sdk as scs
        return [i for i in range(ID_MAX + 1) if self._paquets.ping(self._port, i)[1] == scs.COMM_SUCCESS]

    def changer_id(self, ancien_id: int, nouvel_id: int) -> None:
        self._ecrire(ancien_id, REG_LOCK, 0)
        # le servo prend son nouvel ID tout de suite et répond sous ce nouvel ID : attendre une réponse de
        # l'ancien ID échouerait (« no status packet ») alors que l'ID a bien changé. On n'attend donc pas.
        self._paquets.write1ByteTxOnly(self._port, ancien_id, REG_ID, nouvel_id)
        time.sleep(0.05)
        # reverrouiller sous le nouvel ID vérifie aussi que le changement a eu lieu
        try:
            self._ecrire(nouvel_id, REG_LOCK, 1)
        except ConnectionError as e:
            raise ConnectionError(f"le servo ne répond pas sous son nouvel ID {nouvel_id} : {e}") from e

    def _ecrire(self, servo: int, registre: int, valeur: int) -> None:
        import scservo_sdk as scs
        comm, erreur = self._paquets.write1ByteTxRx(self._port, servo, registre, valeur)
        if comm != scs.COMM_SUCCESS:
            raise ConnectionError(f"écriture refusée par le servo (ID {servo}) : {self._paquets.getTxRxResult(comm)}")


class ServoIdViewModel(ViewModelBase):
    """Étapes : choisir le port, chercher (un seul servo branché), saisir le nouvel ID, écrire puis vérifier."""
    changed = Signal()

    def __init__(self, dialogProvider: IDialogProvider, ids_du_robot: dict[str, int] | None = None,
                 bus: BusServos | None = None):
        super().__init__(dialogProvider)
        self._bus = bus or BusServosFeetech()
        self._worker = BackgroundWorker()
        self.ids_du_robot = ids_du_robot or {}      # aide au choix du nouvel ID : {moteur: ID} du robot ouvert
        self.occupe = False
        self.trouves: list[int] | None = None       # None : pas encore cherché
        self.message = "Branchez un seul servo, puis cliquez sur Chercher."

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, traceback):
        self._worker.shutdown()
        self._bus.fermer()

    def ports(self) -> list[str]:
        return ports_disponibles()

    def id_trouve(self) -> int | None:
        return self.trouves[0] if self.trouves is not None and len(self.trouves) == 1 else None

    def _lancer(self, fonction, fin, message: str):
        self.occupe = True
        self.message = message
        self.changed.emit()
        self._worker.run(fonction, lambda r: self._fin(fin, r), self._echec)

    def _fin(self, fin, resultat):
        self.occupe = False
        fin(resultat)
        self.changed.emit()

    def _echec(self, ex: Exception):
        self.occupe = False
        self.trouves = None
        self.message = f"✗ {ex}"
        self.changed.emit()

    # ------------------------------------------------------------------ chercher
    def chercher(self, port: str):
        def chercher():
            self._bus.fermer()
            self._bus.ouvrir(port)
            return self._bus.ids_presents()
        self._lancer(chercher, self._fin_recherche, "Recherche du servo… (une dizaine de secondes)")

    def _fin_recherche(self, trouves: list[int]):
        self.trouves = trouves
        if not trouves:
            self.message = "✗ Aucun servo ne répond : vérifiez l'alimentation, le câble et le port choisi."
        elif len(trouves) > 1:
            self.message = (f"✗ Plusieurs servos répondent (ID {', '.join(map(str, trouves))}) : "
                            "n'en laissez qu'un seul branché, puis cherchez à nouveau.")
        else:
            self.message = f"Servo trouvé : ID {trouves[0]}" + \
                (" (ID réservé du guide de montage)" if trouves[0] >= ID_DE_COTE else "") + \
                ". Saisissez le nouvel ID puis cliquez sur Écrire."

    # ------------------------------------------------------------------ écrire
    def ecrire(self, nouvel_id: int):
        ancien_id = self.id_trouve()
        if ancien_id is None:
            return
        if not ID_MIN <= nouvel_id <= ID_MAX:
            self._dialogProvider.information("Changer l'ID", f"L'ID doit être compris entre {ID_MIN} et {ID_MAX}.")
            return
        if nouvel_id == ancien_id:
            self._dialogProvider.information("Changer l'ID", "Le servo a déjà cet ID.")
            return
        if nouvel_id >= ID_DE_COTE and not self._dialogProvider.question_yes_no(
                "Changer l'ID", f"Les ID à partir de {ID_DE_COTE} sont réservés au guide de montage.\r\n"
                                "Utiliser quand même cet ID ?"):
            return
        def ecrire():
            self._bus.changer_id(ancien_id, nouvel_id)
            return self._bus.ids_presents()
        self._lancer(ecrire, lambda trouves: self._fin_ecriture(nouvel_id, trouves),
                     f"Écriture de l'ID {nouvel_id}, puis vérification…")

    def _fin_ecriture(self, nouvel_id: int, trouves: list[int]):
        self.trouves = trouves
        if trouves == [nouvel_id]:
            self.message = f"✓ Le servo répond maintenant à l'ID {nouvel_id}. Vous pouvez brancher le servo suivant."
        else:
            self.message = (f"✗ Vérification : le servo ne répond pas à l'ID {nouvel_id} "
                            f"(ID qui répondent : {', '.join(map(str, trouves)) or 'aucun'}).")
