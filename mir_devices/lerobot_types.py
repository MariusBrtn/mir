"""
Types du bus moteur de LeRobot utilisés hors de mir_devices.

Le reste de MIR (éditeur, simulation) les importe d'ici plutôt que de LeRobot : si LeRobot les déplace ou les
renomme dans une nouvelle version, seul ce fichier change. Version de LeRobot figée dans requirements.txt.
"""
from lerobot.motors import Motor, MotorCalibration, MotorNormMode
from lerobot.motors.feetech import FeetechMotorsBus, OperatingMode

__all__ = ["FeetechMotorsBus", "Motor", "MotorCalibration", "MotorNormMode", "OperatingMode"]
