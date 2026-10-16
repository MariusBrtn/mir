from __future__ import annotations
from typing_extensions import override
from typing import cast
from dataclasses import dataclass, field
from loguru import logger
from typing import Any
import time
import dacite
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode
from lerobot.motors import MotorCalibration, Motor
from mir_devices.mir_device import (mirDevice, 
                                    ActionValue, 
                                    ObservableProperty, 
                                    ObservationValue, 
                                    ObservablePropertyFloat, 
                                    ImirFeetechMotorBus, 
                                    DeviceAction,
                                    mirMotorCalibration)
from mir_utils.events import Event_
from mir_devices.communication_ports import find_acm_serial_ports

@dataclass
class Register():
    name: str
    address: int
    size: int
    read_only: bool = field(default=False)
    type: str = field(default="")
    value: str = field(default="")
    def set_value(self, value):
        self.value = str(value)

sts3215_registers: dict[str, Register] = {
    "Firmware_Major_Version": Register(name="Firmware_Major_Version", address=0, size=1, read_only=True, type="int"),
    "Firmware_Minor_Version": Register(name="Firmware_Minor_Version", address=1, size=1, read_only=True, type="int"),
    "Model_Number": Register(name="Model_Number", address=3, size=2, read_only=True, type="int"),
    "ID": Register(name="ID", address=5, size=1, read_only=False, type="int"),
    "Baud_Rate": Register(name="Baud_Rate", address=6, size=1, read_only=False, type="int"),
    "Return_Delay_Time": Register(name="Return_Delay_Time", address=7, size=1, read_only=False, type="int"),
    "Response_Status_Level": Register(name="Response_Status_Level", address=8, size=1, read_only=False, type="int"),
    "Min_Position_Limit": Register(name="Min_Position_Limit", address=9, size=2, read_only=False, type="int"),
    "Max_Position_Limit": Register(name="Max_Position_Limit", address=11, size=2, read_only=False, type="int"),
    "Max_Temperature_Limit": Register(name="Max_Temperature_Limit", address=13, size=1, read_only=False, type="int"),
    "Max_Voltage_Limit": Register(name="Max_Voltage_Limit", address=14, size=1, read_only=False, type="int"),
    "Min_Voltage_Limit": Register(name="Min_Voltage_Limit", address=15, size=1, read_only=False, type="int"),
    "Max_Torque_Limit": Register(name="Max_Torque_Limit", address=16, size=2, read_only=False, type="int"),
    "Phase": Register(name="Phase", address=18, size=1, read_only=False, type="int"),
    "Unloading_Condition": Register(name="Unloading_Condition", address=19, size=1, read_only=False, type="int"),
    "LED_Alarm_Condition": Register(name="LED_Alarm_Condition", address=20, size=1, read_only=False, type="int"),
    "P_Coefficient": Register(name="P_Coefficient", address=21, size=1, read_only=False, type="int"),
    "D_Coefficient": Register(name="D_Coefficient", address=22, size=1, read_only=False, type="int"),
    "I_Coefficient": Register(name="I_Coefficient", address=23, size=1, read_only=False, type="int"),
    "Minimum_Startup_Force": Register(name="Minimum_Startup_Force", address=24, size=2, read_only=False, type="int"),
    "CW_Dead_Zone": Register(name="CW_Dead_Zone", address=26, size=1, read_only=False, type="int"),
    "CCW_Dead_Zone": Register(name="CCW_Dead_Zone", address=27, size=1, read_only=False, type="int"),
    "Protection_Current": Register(name="Protection_Current", address=28, size=2, read_only=False, type="int"),
    "Angular_Resolution": Register(name="Angular_Resolution", address=30, size=1, read_only=False, type="int"),
    "Homing_Offset": Register(name="Homing_Offset", address=31, size=2, read_only=False, type="int"),
    "Operating_Mode": Register(name="Operating_Mode", address=33, size=1, read_only=False, type="int"),
    "Protective_Torque": Register(name="Protective_Torque", address=34, size=1, read_only=False, type="int"),
    "Protection_Time": Register(name="Protection_Time", address=35, size=1, read_only=False, type="int"),
    "Overload_Torque": Register(name="Overload_Torque", address=36, size=1, read_only=False, type="int"),
    "Velocity_closed_loop_P_proportional_coefficient": Register(name="Velocity_closed_loop_P_proportional_coefficient", address=37, size=1, read_only=False, type="int"),
    "Over_Current_Protection_Time": Register(name="Over_Current_Protection_Time", address=38, size=1, read_only=False, type="int"),
    "Velocity_closed_loop_I_integral_coefficient": Register(name="Velocity_closed_loop_I_integral_coefficient", address=39, size=1, read_only=False, type="int"),
    "Torque_Enable": Register(name="Torque_Enable", address=40, size=1, read_only=False, type="bool"),
    "Acceleration": Register(name="Acceleration", address=41, size=1, read_only=False, type="int"),
    "Goal_Position": Register(name="Goal_Position", address=42, size=2, read_only=False, type="int"),
    "Goal_Time": Register(name="Goal_Time", address=44, size=2, read_only=False, type="int"),
    "Goal_Velocity": Register(name="Goal_Velocity", address=46, size=2, read_only=False, type="int"),
    "Torque_Limit": Register(name="Torque_Limit", address=48, size=2, read_only=False, type="int"),
    "Lock": Register(name="Lock", address=55, size=1, read_only=False, type="bool"),
    "Present_Position": Register(name="Present_Position", address=56, size=2, read_only=True, type="int"),
    "Present_Velocity": Register(name="Present_Velocity", address=58, size=2, read_only=True, type="int"),
    "Present_Load": Register(name="Present_Load", address=60, size=2, read_only=True, type="int"),
    "Present_Voltage": Register(name="Present_Voltage", address=62, size=1, read_only=True, type="int"),
    "Present_Temperature": Register(name="Present_Temperature", address=63, size=1, read_only=True, type="int"),
    "Status": Register(name="Status", address=65, size=1, read_only=True, type="int"),
    "Moving": Register(name="Moving", address=66, size=1, read_only=True, type="bool"),
    "Present_Current": Register(name="Present_Current", address=69, size=2, read_only=True, type="int"),
    "Goal_Position_2": Register(name="Goal_Position_2", address=71, size=2, read_only=False, type="int"),
    "Moving_Velocity_Threshold": Register(name="Moving_Velocity_Threshold", address=80, size=1, read_only=False, type="int"),
    "DTs": Register(name="DTs", address=81, size=1, read_only=False, type="int"),
    "Velocity_Unit_factor": Register(name="Velocity_Unit_factor", address=82, size=1, read_only=False, type="int"),
    "Hts": Register(name="Hts", address=83, size=1, read_only=False, type="int"),
    "Maximum_Velocity_Limit": Register(name="Maximum_Velocity_Limit", address=84, size=1, read_only=False, type="int"),
    "Maximum_Acceleration": Register(name="Maximum_Acceleration", address=85, size=1, read_only=False, type="int"),
    "Acceleration_Multiplier ": Register(name="Acceleration_Multiplier ", address=86, size=1, read_only=False, type="int")
}

RPM_PER_UNIT = 0.732
# adresses des mesures dans le STS3215 (lues d'un bloc par _read_observations_block)
BLOCK_START = POSITION_ADDR = 56
VELOCITY_ADDR, LOAD_ADDR, TEMPERATURE_ADDR, CURRENT_ADDR = 58, 60, 63, 69


@dataclass
class mirMotor(Motor):
    operating_mode: OperatingMode = OperatingMode.POSITION
    P:int = 16
    I:int = 0 #noqa E741
    D:int = 32
    position_mode_velocity: int = 100 #vitesse max en mode POSITION, en tr/min (convertie en unités STS de 0.732 tr/min)
    torque_limit: int = 250 #couple maximum en 0.1% 


@dataclass
class mirMotorBusConfiguration:
    motor_port: str
    motors: dict[str, mirMotor]
    calibration: dict[str, mirMotorCalibration]

    @staticmethod
    def create_motor_bus_from_dict(data: dict[str, Any], dacite_config: dacite.Config) -> mirMotorBusConfiguration:
        motor_port = data.get("motor_port", "")
        calibration_dict = data.get("calibration", {})
        calibration = {k: dacite.from_dict(mirMotorCalibration, v, dacite_config) for k, v in calibration_dict.items()}        
        motors_dict = data.get("motors", {})
        motors = {k: dacite.from_dict(mirMotor, v, dacite_config) for k, v in motors_dict.items()}
        return mirMotorBusConfiguration(motor_port=motor_port, motors=motors, calibration=calibration)

    def __str__(self) -> str:
        ids= ", ".join([f"{key}:ID={motor.id} " for key, motor in self.motors.items()])
        return f"{self.motor_port}. {ids}"


POSITION_SUFFIX = "position"
VELOCITY_SUFFIX = "velocity"
CURRENT_SUFFIX = "current"
TEMPERATURE_SUFFIX = "temperature"
LOAD_SUFFIX = "load"
ACTION_POSITION_SUFFIX = "position"
ACTION_VELOCITY_SUFFIX = "velocity"

class mirFeetechMotorsBus(FeetechMotorsBus, ImirFeetechMotorBus):
   
    _bus_connected : dict[str, bool] = {}
    
    def __init__(self, config: mirMotorBusConfiguration):
        mirDevice.__init__(self)
        self._config = config
        self._mir_motors = config.motors
        self._port = config.motor_port
        self._mir_calibration:dict[str, mirMotorCalibration] = config.calibration
        super().__init__(self._port, cast(dict[str, Motor], self._mir_motors),  cast(dict[str, MotorCalibration], self._mir_calibration))
        self._mir_is_calibrated_changed = Event_[[bool]]()
        self._sent_velocities: dict[str, int | float] = {}     # vitesse max (mode position) déjà écrite, par moteur
        self._mir_is_calibrated = False
        self._mir_is_ready = False
        for motor_name, motor_cfg in self._mir_motors.items():
            if motor_cfg.operating_mode == OperatingMode.POSITION:
                self._actions[f"{motor_name}.{ACTION_POSITION_SUFFIX}"] = DeviceAction(motor_name, ACTION_POSITION_SUFFIX, 0.0,'float', '°', None)
            elif motor_cfg.operating_mode == OperatingMode.VELOCITY:                        
                self._actions[f"{motor_name}.{ACTION_VELOCITY_SUFFIX}"] = DeviceAction(motor_name, ACTION_VELOCITY_SUFFIX, 0,'int', '°/s', None)

    @property
    def mir_is_calibrated_changed(self) -> Event_[bool]:
        """Implémentation de la propriété requise par l'interface ImirFeetechMotorBus"""
        return self._mir_is_calibrated_changed
    
    def mir_is_calibrated(self):
        return self._mir_is_calibrated

    def _set_is_calibrated(self, calibrated:bool):
        self._mir_is_calibrated = calibrated
        if self._mir_is_ready:
            self._update_action_ranges()        # les butées changent avec la calibration
        self.mir_is_calibrated_changed.fire(self._mir_is_calibrated)         

    def mir_uncalibrated_reason(self)->str:
        return self._mir_uncalibrated_reason if hasattr(self, "_mir_uncalibrated_reason") else "" # type: ignore
    
    def mir_get_motors(self)->dict[str, mirMotor]:
        return self._mir_motors

    @override
    def mir_read_calibration_from_motors(self) -> dict[str, mirMotorCalibration] | None:
        calibration = {key: mirMotorCalibration(id=cal.id, drive_mode=cal.drive_mode, homing_offset=cal.homing_offset, range_min=cal.range_min, range_max=cal.range_max) 
                for key, cal in self.read_calibration().items()}
        for c in calibration.values():
            if c.range_max <= c.range_min:
                return None
        return calibration                

    
    @property
    @override
    def is_calibrated(self) -> bool:
        """
        surcharge is_calibrated de FeetechMotorBus
        car sa fonction ne testait pas les IDs
        """
        motors_calibration = self.read_calibration()
        if set(motors_calibration) != set(self.calibration):
            return False

        same_ranges = all(
            self.calibration[motor].range_min == cal.range_min
            and self.calibration[motor].range_max == cal.range_max
            for motor, cal in motors_calibration.items()
        )
        same_ids = all(
            self.calibration[motor].id == cal.id
            for motor, cal in motors_calibration.items()
        )

        if self.protocol_version == 1:
            return same_ranges and same_ids
        same_offsets = all(
            self.calibration[motor].homing_offset == cal.homing_offset
            for motor, cal in motors_calibration.items()
        )
        return same_ranges and same_offsets and same_ids
    
    def mir_connect(self):
        if mirFeetechMotorsBus._bus_connected.get(self._config.motor_port, False):
            raise ConnectionError("Le bus est déjà connecté")
        try :
            super().connect(True)   
            self._mir_is_ready = True
            mirFeetechMotorsBus._bus_connected[self._config.motor_port] = True
            # calibration connue AVANT de lire les positions et de calculer les plages des consignes : sinon les
            # plages restaient celles d'un moteur non calibré (0 à 4095), et MIR ne bornait plus les consignes
            self._set_is_calibrated(self.is_calibrated)
            positions = self.mir_read_positions()
            velocities = self.mir_read_velocities()
            for motor_name, motor_cfg in self._mir_motors.items():
                if motor_cfg.operating_mode == OperatingMode.POSITION:
                    self._actions[f"{motor_name}.{ACTION_POSITION_SUFFIX}"].set_value(positions[motor_name])
                elif motor_cfg.operating_mode == OperatingMode.VELOCITY:
                    self._actions[f"{motor_name}.{ACTION_VELOCITY_SUFFIX}"].set_value(velocities[motor_name])
            self._update_action_ranges()
        except BaseException as e:
            self._mir_is_ready = False
            raise e

    def _update_action_ranges(self):
        """Plages des consignes (bornées par verifier_action) : les butées de la calibration."""
        for motor_name, motor_cfg in self._mir_motors.items():
            if motor_cfg.operating_mode == OperatingMode.POSITION:
                self._actions[f"{motor_name}.{ACTION_POSITION_SUFFIX}"].set_range(self.mir_get_motor_position_range(motor_name))
            elif motor_cfg.operating_mode == OperatingMode.VELOCITY:
                self._actions[f"{motor_name}.{ACTION_VELOCITY_SUFFIX}"].set_range(self.mir_get_motor_velocity_range(motor_name))
               
    def mir_disconnect(self):
        if self.is_connected:
            super().disconnect(False)
        mirFeetechMotorsBus._bus_connected[self._config.motor_port] = False

    def mir_is_connected(self) -> bool:
        return super().is_connected
    
    def _check_mir_is_ready(self):
        if not self._mir_is_ready:
            raise RuntimeError("Opération impossible, car le bus n'est pas prêt (non connecté ou la liste des moteurs n'est pas conforme)")

    def mir_read_register(self, data_name: str, motor: str, num_retry: int = 0) ->int:
        return int(self.read(data_name, motor, normalize=False, num_retry=num_retry))
    
    def mir_read_register_by_id(self, data_name: str, motor_id: int, num_retry: int = 0) ->int:
        reg = sts3215_registers[data_name]
        value,*_ = self._read(reg.address, reg.size,  motor_id, num_retry=num_retry)
        return value
    
    def mir_write_register_by_id(self, data_name: str, motor_id: int, value: int, num_retry: int = 0) ->None:
        reg = sts3215_registers[data_name]
        self._write(reg.address, reg.size,  motor_id, value, num_retry=num_retry)
                
    def mir_set_operating_mode(self, motor:str, operating_mode:OperatingMode):
        self._check_mir_is_ready()
        self.write("Operating_Mode", motor, operating_mode.value)
        self._mir_motors[motor].operating_mode = operating_mode

    def mir_disable_torques(self, motors: list[str] | None=None)->None:
        if motors is None:
            self.sync_write("Torque_Enable", 0)
        else:
            self.sync_write("Torque_Enable", {motor:0 for motor in motors})                        

    def mir_get_position_unit(self, motor: str) -> str:
        if self.mir_is_calibrated and self._mir_motors[motor].operating_mode == OperatingMode.POSITION:
            return "degrés"
        return "pas"
    
    def mir_get_velocity_unit(self) -> str:
        return 'RPM'

    def mir_emergency_stop(self) -> None:
        self.mir_disable_torques()
        self.mir_goal_velocities(0)
        for motor in self.motors:
            positions = self.mir_read_positions()
            self.mir_goal_positions(positions, None)
        self.mir_disable_torques()

    def mir_stop(self, name:str|list[str]|None):
        if name is None:
            self.mir_goal_velocities(0)
            positions = self.mir_read_positions()
            self.mir_goal_positions(positions, None)
        elif isinstance(name, str):
            self.mir_goal_velocities({name:0})
            positions = self.mir_read_positions([name])
            self.mir_goal_positions(positions, None)
        else:         
            self.mir_goal_velocities({name:0 for name in name})
            positions = self.mir_read_positions(name)
            self.mir_goal_positions(positions, None)

    def mir_goal_position(self, name: str, pos:int|float, vel:int|float):
        self._check_mir_is_ready()
        #self.mir_goal_velocity(name, vel)
        velocities : dict[str, int|float] = {name: vel}
        self.mir_goal_velocities(velocities)
        time.sleep(0.001)
        if self._mir_is_calibrated:
            self.write("Goal_Position", name, pos, normalize=True)
        else:
            self.write("Goal_Position", name, int(pos), normalize=False)
    
    def mir_goal_velocities(self, velocities:  int | dict[str, int|float]) -> None:
        """
        Déplace un ou plusieurs moteurs à des vitesses données.
        
        Args:
        dictionnaire ou valeur, les valeurs sont en RPM
        """
        self._check_mir_is_ready()
        #Les vitesses sont en RPM. Avec Phase=0 (forcé à dans configure), l'unité de vitesse est de 0.732RPM
        if isinstance(velocities, dict):
            for key in velocities:
                self._sent_velocities.pop(key, None)
            velocities = {key: int(val / RPM_PER_UNIT + 0.5) for key, val in velocities.items()}
        else:
            self._sent_velocities.clear()
            velocities = int(velocities / RPM_PER_UNIT + 0.5)
        """Déplace un ou plusieurs moteurs à des vitesses données."""
        self.sync_write("Goal_Velocity", velocities, normalize=False)

    def mir_goal_positions(self, positions:dict[str, int|float] | int | float, velocities: dict[str, int|float]|None):
        self._check_mir_is_ready()
        if velocities is not None:
            # la vitesse max n'est réécrite que si elle a changé : un échange (et 1 ms d'attente) de moins par pas
            changed = {m: v for m, v in velocities.items() if self._sent_velocities.get(m) != v}
            if changed:
                self.mir_goal_velocities(changed)
                self._sent_velocities.update(changed)
                time.sleep(0.001)
        if self._mir_is_calibrated:
            self.sync_write("Goal_Position", positions, normalize=True)
        else:
            self.sync_write("Goal_Position", positions, normalize=True)
    
    def mir_goal_velocity(self, name: str, velocity: int|float) -> None:
        self._check_mir_is_ready()
        velocity = int(velocity / RPM_PER_UNIT + 0.5)
        self._sent_velocities.pop(name, None)
        self.write("Goal_Velocity", name, velocity)

    @staticmethod
    def mir_normalize_motor_pos_for_velocity_mode(raw_position:int, calibration: mirMotorCalibration) -> float:
        raw_position -= calibration.homing_offset
        if raw_position < 0:
            raw_position = 4095 + raw_position
        elif raw_position > 4095:
            raw_position = raw_position - 4095
        mid = (calibration.range_min + calibration.range_max) / 2
        return (raw_position - mid) * 360 / 4095

    def mir_read_positions(self, motors: list[str]|None = None) -> dict[str, int|float]:
        self._check_mir_is_ready()
        if not self._mir_is_calibrated or self._mir_calibration is None:
            return self.sync_read("Present_Position", motors, normalize=False)
        if motors is None:
            motors_velocity = [motor for motor in self._mir_motors if self._mir_motors[motor].operating_mode == OperatingMode.VELOCITY]
            motors_positions = [motor for motor in self._mir_motors if self._mir_motors[motor].operating_mode == OperatingMode.POSITION]
        else:
            motors_velocity = [motor for motor in motors if self._mir_motors[motor].operating_mode == OperatingMode.VELOCITY]
            motors_positions = [motor for motor in motors if self._mir_motors[motor].operating_mode == OperatingMode.POSITION]
        if motors_positions is None or len(motors_positions) == 0:
            positions = {}
        else:
            positions = self.sync_read("Present_Position", motors_positions, normalize=True)
        if motors_velocity is not None and len(motors_velocity) > 0:            
            positions_velocity = self.sync_read("Present_Position", motors_velocity, normalize=False)
            for motor, pos in positions_velocity.items():
                positions[motor] = mirFeetechMotorsBus.mir_normalize_motor_pos_for_velocity_mode(
                                                        int(pos), 
                                                        self._mir_calibration[motor]
                                                    )            
        return positions

    def mir_read_raw_positions(self, motors: list[str]|None = None) -> dict[str, int|float]:
        self._check_mir_is_ready()
        return self.sync_read("Present_Position", motors, normalize=False)

    def mir_read_velocities(self, motors: list[str]|None = None) -> dict[str, int|float]:
        self._check_mir_is_ready()
        result = self.sync_read("Present_Velocity", motors)
        return {key: round(val * RPM_PER_UNIT, 2) for key, val in result.items()}

    def mir_read_currents(self, motors: list[str]|None = None) -> dict[str, int|float]:            
        self._check_mir_is_ready()
        raw_currents = self.sync_read("Present_Current", motors)
        return {key: round(val * 6.5, 1) for key, val in raw_currents.items()}      # 6.5 mA par unité
    
    def mir_read_loads(self, motors: list[str]|None = None) -> dict[str, int|float]:
        self._check_mir_is_ready()
        raw_loads = self.sync_read("Present_Load", motors, normalize=False)
        # 0.1 % par unité ; le bit 10 donne le sens (non décodé par LeRobot) : sinon, une charge dans l'autre sens
        # apparaissait comme 102,4 % et plus
        return {key: (-1 if int(val) & 0x400 else 1) * (int(val) & 0x3FF) / 10.0 for key, val in raw_loads.items()}
    
    def mir_read_temperatures(self, motors: list[str]|None = None) -> dict[str, int|float]:            
        self._check_mir_is_ready()
        return self.sync_read("Present_Temperature", motors)

    def mir_is_moving(self, motors:list[str]|None=None) -> bool:
        velocities = self.sync_read("Present_Velocity", motors)
        return any(v != 0 for v in velocities.values())

    def mir_reset_calibration(self, motors = None):
        self._check_mir_is_ready()
        super().reset_calibration(motors) 
        self._set_is_calibrated(False)    

    def mir_calibrate(self, homing_offsets: dict, range_mins: dict, range_maxes:dict) -> None: 
        self._check_mir_is_ready()
        self._mir_calibration = {}
        for motor, m in self.motors.items():
            self._mir_calibration[motor] = mirMotorCalibration(
                id=m.id,
                drive_mode=0,
                homing_offset=homing_offsets[motor],
                range_min=range_mins[motor],
                range_max=range_maxes[motor],
            )
        self.calibration = self._mir_calibration
        self.write_calibration(cast(dict[str, MotorCalibration], self.calibration))
        self._set_is_calibrated(self.is_calibrated)
        self._config.calibration = self._mir_calibration
        if not self._mir_is_calibrated:
            raise Exception("La calibration des moteurs ne correspond pas à la calibration réalisée")           
    
    def mir_calibrate_from_motors(self):
        self._check_mir_is_ready()
        cal_from_motors = self.mir_read_calibration_from_motors()
        if cal_from_motors is None:
            raise Exception("La calibration des moteurs n'est pas valide")
        self._mir_calibration = cal_from_motors
        self.calibration = self._mir_calibration
        self._set_is_calibrated(self.is_calibrated)
        self._config.calibration = self._mir_calibration
        if not self._mir_is_calibrated:
            raise Exception("La calibration des moteurs ne correspond pas à la calibration appliquée")           

    def mir_store_calibration(self):
        self._check_mir_is_ready()
        if not self.is_calibrated:
            self._stored_calibration = None
            return
        self._stored_calibration = self.calibration.copy()

    def mir_restore_calibration(self):
        self._check_mir_is_ready()
        if self._stored_calibration is None:
            return
        self.calibration = self._stored_calibration
        self.write_calibration(cast(dict[str, MotorCalibration], self.calibration))
        self._set_is_calibrated(self.is_calibrated)

    #TODO ajouter MotorNormMode
    def mir_configure_motors(self):
        self._check_mir_is_ready()
        super().configure_motors(return_delay_time=0)
        for motor_name, motor in self._mir_motors.items():
            self.write("Torque_Enable", motor_name, 0)
            self.write("Operating_Mode", motor_name, motor.operating_mode.value)
            self.write("P_Coefficient", motor_name, motor.P)
            self.write("I_Coefficient", motor_name, motor.I)
            self.write("D_Coefficient", motor_name, motor.D)
            self.write("Moving_Velocity_Threshold", motor_name, 0)
            self.write("Goal_Velocity", motor_name, 0)
            self._sent_velocities.pop(motor_name, None)
            self.write("Torque_Limit", motor_name, motor.torque_limit)
            phase = self.read("Phase", motor_name)
            if phase != 0:
                logger.warning(f"Remise à 0 du registre Phase du moteur {motor_name} qui était sur {phase}")
                self.write("Lock", motor_name, 0)
                self.write("Phase", motor_name, 0)
                self.write("Lock", motor_name, 1)
    
    def mir_get_motor_position_range(self, motor:str)->tuple[float, float]:
        if not self._mir_is_calibrated or self._mir_calibration is None:
            return (0, 4095)
        if self._mir_motors[motor].operating_mode == OperatingMode.VELOCITY:
            return (-180, 180)
        raw_values = {
            self._mir_motors[motor].id: self._mir_calibration[motor].range_min
        }
        res = self._normalize(raw_values)
        min_ = res[self._mir_motors[motor].id]
        raw_values = {
            self._mir_motors[motor].id: self._mir_calibration[motor].range_max
        }
        res = self._normalize(raw_values)
        max_ = res[self._mir_motors[motor].id]
                
        return (min_, max_)
    
    def mir_get_motor_velocity_range(self, motor:str)->tuple[float, float]:
        max_ = self.mir_read_register("Maximum_Velocity_Limit", motor)
        return (-max_, max_)
    
    def get_observation(self) -> dict[str, ObservationValue]:
        if len(self.subscribed_observations) == 0:
            return {}
        return self._read_observations_block()
    
    def _read_observations_block(self) -> dict[str, ObservationValue]:
        """Toutes les grandeurs abonnées en UN échange sur le bus : les registres Present_Position (56) à
        Present_Temperature (63), et Present_Current (69) si besoin, sont lus d'un bloc pour chaque moteur.
        Un échange par grandeur coûte un aller-retour USB de plus chacun."""
        self._check_mir_is_ready()
        voulues: dict[str, set[str]] = {}
        for feature in self.subscribed_observations:
            motor, _, suffix = feature.partition(".")
            if motor in self._mir_motors:
                voulues.setdefault(suffix, set()).add(motor)
        if not voulues:
            return {}
        motors = sorted(set().union(*voulues.values()))
        ids = [self.motors[m].id for m in motors]
        debut = BLOCK_START
        longueur = (CURRENT_ADDR + 2 if CURRENT_SUFFIX in voulues else TEMPERATURE_ADDR + 1) - debut
        self._sync_read(debut, longueur, ids, raise_on_error=True,
                        err_msg=f"Échec de la lecture des mesures des moteurs {motors}")
        def lire(motor: str, addr: int, size: int) -> int:
            return int(self.sync_reader.getData(self.motors[motor].id, addr, size))
        observation: dict[str, ObservationValue] = {}
        if POSITION_SUFFIX in voulues:
            raw = {m: lire(m, POSITION_ADDR, 2) for m in voulues[POSITION_SUFFIX]}
            observation.update({f"{m}.{POSITION_SUFFIX}": v for m, v in self._positions_from_raw(raw).items()})
        for m in voulues.get(VELOCITY_SUFFIX, ()):
            raw = lire(m, VELOCITY_ADDR, 2)
            vitesse = -(raw & 0x7FFF) if raw & 0x8000 else raw          # bit 15 : sens
            observation[f"{m}.{VELOCITY_SUFFIX}"] = round(vitesse * RPM_PER_UNIT, 2)
        for m in voulues.get(LOAD_SUFFIX, ()):
            raw = lire(m, LOAD_ADDR, 2)
            observation[f"{m}.{LOAD_SUFFIX}"] = (-1 if raw & 0x400 else 1) * (raw & 0x3FF) / 10.0   # bit 10 : sens
        for m in voulues.get(TEMPERATURE_SUFFIX, ()):
            observation[f"{m}.{TEMPERATURE_SUFFIX}"] = lire(m, TEMPERATURE_ADDR, 1)
        for m in voulues.get(CURRENT_SUFFIX, ()):
            observation[f"{m}.{CURRENT_SUFFIX}"] = round(lire(m, CURRENT_ADDR, 2) * 6.5, 1)     # 6.5 mA par unité
        return observation

    def _positions_from_raw(self, raw: dict[str, int]) -> dict[str, float]:
        """Positions brutes -> positions de MIR (même calcul que mir_read_positions)."""
        if not self._mir_is_calibrated or self._mir_calibration is None:
            return {m: float(v) for m, v in raw.items()}
        positions: dict[str, float] = {}
        en_position = {self.motors[m].id: v for m, v in raw.items()
                       if self._mir_motors[m].operating_mode != OperatingMode.VELOCITY}
        if en_position:
            normalized = self._normalize(self._decode_sign("Present_Position", en_position))
            positions.update({self._id_to_name(i): float(v) for i, v in normalized.items()})
        for m, v in raw.items():
            if self._mir_motors[m].operating_mode == OperatingMode.VELOCITY:
                positions[m] = mirFeetechMotorsBus.mir_normalize_motor_pos_for_velocity_mode(v, self._mir_calibration[m])
        return positions

    def get_observables(self) -> dict[str, ObservableProperty]:
        try:
            should_disconnect = False
            if not self.mir_is_connected():
                self.mir_connect()
                should_disconnect = True
            observables : dict[str, ObservableProperty] = {}
            for key, motor in self._mir_motors.items():
                min_pos, max_pos = self.mir_get_motor_position_range(key)
                observables[f"{key}.{POSITION_SUFFIX}"] = ObservablePropertyFloat(min_pos, max_pos, "deg")
                min_vel, max_vel = self.mir_get_motor_velocity_range(key)
                observables[f"{key}.{VELOCITY_SUFFIX}"] = ObservablePropertyFloat(min_vel, max_vel, "rpm")
                observables[f"{key}.{CURRENT_SUFFIX}"] = ObservablePropertyFloat(0, 2700, "mA")
                observables[f"{key}.{TEMPERATURE_SUFFIX}"] = ObservablePropertyFloat(0, 100, "°C")
                observables[f"{key}.{LOAD_SUFFIX}"] = ObservablePropertyFloat(-100, 100, "%")
            return observables
        finally:
            if should_disconnect and self.mir_is_connected():
                self.mir_disconnect()
    
    def send_action(self, actions:dict[str, ActionValue]) -> dict[str, ActionValue]:
        goal_positions = {key.split(".")[0]: val for key, val in actions.items() if key.endswith(f".{POSITION_SUFFIX}")}
        goal_velocities = {key.split(".")[0]: val for key, val in actions.items() if key.endswith(f".{VELOCITY_SUFFIX}")}
        if len(goal_velocities) > 0:
            self.mir_goal_velocities(goal_velocities)
        if len(goal_positions) > 0:
            goal_positions_velocities:dict[str, float] = {}
            for motor in goal_positions:
                goal_positions_velocities[motor] = self._config.motors[motor].position_mode_velocity
            self.mir_goal_positions(goal_positions, goal_positions_velocities)
        return actions
                    
    @staticmethod
    def mir_make_empty_bus(port : str) -> mirFeetechMotorsBus:
        return mirFeetechMotorsBus(mirMotorBusConfiguration(motor_port=port, motors={}, calibration={}))

    @staticmethod
    def mir_make_bus_from_motors(port: str, motors: dict[str, mirMotor]) -> mirFeetechMotorsBus:
        return mirFeetechMotorsBus(mirMotorBusConfiguration(motor_port=port, motors=motors, calibration={}))

    @staticmethod
    def mir_scan_motors(port:str) -> list[int]:
        if mirFeetechMotorsBus._bus_connected.get(port, False):
            raise ConnectionError("Le bus est déjà connecté")

        bus: mirFeetechMotorsBus | None = None
        try :
            bus = mirFeetechMotorsBus.mir_make_empty_bus(port)
            bus.connect(handshake=False)
            ping_res = bus.broadcast_ping()
            return list(result) if (result := ping_res) else []
        except Exception as e:
            logger.error(f"Erreur lors du scan des moteurs: {e}")
            raise ConnectionError()
        finally:    
            if bus is not None:
                bus.disconnect()

    @staticmethod
    def mir_scan_motor_buses() -> list[tuple[str, list[int]]]:
        """
        Scanne tous les ports série ACM disponibles pour chercher des bus Feetech
        (plusieurs robots branchés sur le même ordinateur).
        Retourne la liste des (port, IDs des moteurs) de chaque bus trouvé.
        """
        buses = []
        for port in find_acm_serial_ports():
            logger.info(f"scan du port {port}...")
            try:
                buses.append((port, mirFeetechMotorsBus.mir_scan_motors(port)))
            except ConnectionError:
                continue
        return buses

    @staticmethod
    def mir_scan_motors_on_all_ports() -> tuple[str, list[int]] | tuple[None, None]:
        """
        Scanne tous les ports série ACM disponibles pour chercher un bus Feetech 
        Retourne le premier port trouvé avec les IDs des moteurs, 
        sinon retourne (None, None)
        """
        buses = mirFeetechMotorsBus.mir_scan_motor_buses()
        return buses[0] if buses else (None, None)

        