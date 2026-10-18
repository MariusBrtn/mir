from mir_devices.lerobot_types import FeetechMotorsBus
from PySide6 import QtCore
from mir_devices.mir_feetech_motor_bus import sts3215_registers, Register
from mir_utils.ui.view_model_base import ViewModelBase

class RegistersViewModel(ViewModelBase):

    def __init__(self, bus: FeetechMotorsBus, motor_name: str):
        self._bus = bus
        self._motor_name = motor_name
        self._registers = sts3215_registers
        self._rows: list[Register] = list(self._registers.values())
        self._rows_sorted_by_name = sorted(self._rows, key=lambda x: x.name)
        self.callback = None
        self.timer = QtCore.QTimer()

    def _enter_context(self):
        self.timer.timeout.connect(self.update_fields)
        
    def _exit_context(self, exc_type, exc_value, traceback): 
        self.timer.stop()
           
    def set_update_callback(self, callback):
        self.callback = callback
        self.timer.start(500)

    def get_title(self):
        return f"Registres de {self._motor_name}"

    def get_columns_names(self):
        return ["Description", "Address", "Size", "Current value"]

    def get_rows(self, sort_by_name=True):
        rows = self._rows_sorted_by_name if sort_by_name else self._rows
        for row in rows:
            try:
                value = self._bus.read(row.name, self._motor_name, normalize=False)
                row.set_value(str(value))
            except Exception:
                row.set_value("error")
        return rows

    def update_fields(self, read_all=False):
        self._check_initialized()
        for reg in self._rows:
            if read_all or reg.read_only:
                value = self._bus.read(reg.name, self._motor_name, normalize=False)
                reg.set_value(str(value))
                self.callback(reg)
            
    def write(self, reg_name:str, value):
        reg = self._registers[reg_name]
        self._bus.write(reg_name, self._motor_name, value, normalize=False)
        value = self._bus.read(reg_name, self._motor_name, normalize=False)
        reg.set_value(str(value))   
        self.update_fields(read_all=True)
        