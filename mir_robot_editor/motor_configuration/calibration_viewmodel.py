from PySide6.QtCore import QTimer, Signal
from dataclasses import dataclass
from enum import Enum
from mir_devices.lerobot_types import OperatingMode
from contextlib import contextmanager
from mir_devices.mir_feetech_motor_bus import mirFeetechMotorsBus
from mir_utils.ui.view_model_base import ViewModelBase
from mir_utils.ui.dialogs import IDialogProvider

@dataclass
class CalibrationMotorData():
    min: int = 0
    home: int = 0
    max: int = 0
    min_checked : bool = False
    home_checked : bool = False
    max_checked : bool = False

class CalibrationStage(Enum):
    NoneStage = 0
    Homing = 1
    MinRange = 2
    MaxRange = 3

class CalibrationViewModel(ViewModelBase):
    pos_changed = Signal(dict)
    state_changed = Signal()
    completed = Signal()
    cancelled = Signal()


    def __init__(self, bus: mirFeetechMotorsBus, dialog_provider: IDialogProvider):
        super().__init__(dialog_provider)
        self._bus = bus
        self._stage = CalibrationStage.NoneStage
        self._timer = QTimer()
        self._timer.timeout.connect(self.update_positions)
        self._motors_list = list(self._bus.motors.keys())
        self._motors_data = {name : CalibrationMotorData() for name in self._motors_list}
        self._stage_captions = {
            CalibrationStage.Homing: "Homing Offset",
            CalibrationStage.MinRange: "Limite min des déplacements",
            CalibrationStage.MaxRange: "Limite max des déplacements"
        }            
        self._stage_descriptions = {
            CalibrationStage.Homing : "Déplacez les moteurs au milieu de leur plage de fonctionnement\r\nCliquez sur suivant lorsque tous les moteurs sont en place",
            CalibrationStage.MinRange : "Déplacez les moteurs sur la position minimale de fonctionnement\r\nCliquez sur Suivant lorsque la position min est atteinte.",
            CalibrationStage.MaxRange : "Déplacez les moteurs sur la position maximale de fonctionnement\r\nCliquez sur Terminer lorsque la position max est atteinte."            
        }
        self._do_not_update_positions = False
        self.is_bus_calibrated = False
        self._is_calibration_done = False
    
    def _enter_context(self):
        for motor in self._motors_list:
            self._bus.write("Torque_Enable", motor, 0)
            self._bus.write("Lock", motor, 0)
            self._bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
        self._bus.mir_store_calibration()
        self._bus.mir_reset_calibration()             
        self.enter_homing_stage()
        self._timer.start(100)

    def _exit_context(self, exc_type, exc_value, traceback):

        self._timer.stop()
        for motor in self._motors_list:
            self._bus.write("Lock", motor, 1)

    #TODO prendre en compte le mode VELOCITY pour les positions normalisées
    def update_positions(self):
        if self._do_not_update_positions:
            return
        positions= self._bus.sync_read("Present_Position", self._motors_list, normalize=self.is_bus_calibrated)
        if self._stage == CalibrationStage.Homing:
            for name, pos in positions.items():
                self._motors_data[name] = CalibrationMotorData(min=pos, home=pos, max=pos)  
        elif self._stage in (CalibrationStage.MinRange, CalibrationStage.MaxRange):
            if self._stage == CalibrationStage.MinRange:
                self._mins = positions.copy()
            else:
                self._maxes = positions.copy()
            for motor, data in self._motors_data.items():
                data.min  = self._mins[motor]
                data.home = self._start_positions[motor]
                data.max  = self._maxes[motor]
                data.home_checked = abs(self._start_positions[motor] - 2047) < 2
                data.min_checked  = (self._start_positions[motor] - self._mins[motor]) > 10
                if self._stage == CalibrationStage.MaxRange:
                    data.max_checked = (self._maxes[motor] - self._start_positions[motor]) > 10
        self.pos_changed.emit(self._motors_data)
        self.state_changed.emit()

    def get_motors(self):
        return self._bus.motors

    def enter_homing_stage(self):
        self._stage = CalibrationStage.Homing
        self.state_changed.emit()

    @contextmanager
    def _pause_updates(self):
        self._do_not_update_positions = True
        try:
            yield
        finally:
            self._do_not_update_positions = False

    def exit_homing_stage(self):
        with self._pause_updates():
            self._homing_offsets = self._bus.set_half_turn_homings()
            self._start_positions = self._bus.sync_read("Present_Position", self._motors_list, normalize=False)
            self._mins  = self._start_positions.copy()
            self._maxes = self._start_positions.copy()
            for data in self._motors_data.values():
                data.home_checked = True

    def enter_min_range_stage(self):
        self._stage = CalibrationStage.MinRange
        self.state_changed.emit()
    
    def enter_max_range_stage(self):
        self._stage = CalibrationStage.MaxRange
        self.state_changed.emit()        

    def prev(self):
        if self._stage == CalibrationStage.MinRange:
            self.enter_homing_stage()
        elif self._stage == CalibrationStage.MaxRange:
            self.enter_min_range_stage()

    def next(self):
        if self._stage == CalibrationStage.Homing:
            self.exit_homing_stage()
            self.enter_min_range_stage()
        elif self._stage == CalibrationStage.MinRange:
            self.enter_max_range_stage()

    def end(self):
        try:
            self._bus.mir_calibrate(self._homing_offsets, self._mins, self._maxes)
            self._dialogProvider.information("Calibration terminée", "La calibration est enregistrée dans les moteurs et dans la configuration courante")            
            self.completed.emit()
            self._is_calibration_done = True
        except Exception as e:
            self._dialogProvider.information("Echec calibration", f"La calibration a échoué : {e}")                        

    def cancel(self):
        self._bus.mir_restore_calibration()
        self.cancelled.emit()

    def can_prev(self):
        return self._stage == CalibrationStage.MinRange or self._stage == CalibrationStage.MaxRange
    
    def can_next(self):
        if self._stage == CalibrationStage.Homing:
            return True
        if self._stage == CalibrationStage.MinRange:
            return all(
                d.min_checked and d.home_checked
                for d in self._motors_data.values()
            )
        return False
    
    def can_end(self):
        return self._stage == CalibrationStage.MaxRange and all(
            d.max_checked for d in self._motors_data.values()
        )
    
    def can_cancel(self):
        return True    
    
    def stage_caption(self):
        return self._stage_captions[self._stage]
        
    def stage_description(self):
        return self._stage_descriptions[self._stage]
                
