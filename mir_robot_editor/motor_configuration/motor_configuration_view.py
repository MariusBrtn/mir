from PySide6 import QtWidgets, QtCore
from PySide6.QtWidgets import QLabel, QPushButton, QGridLayout, QVBoxLayout, QLineEdit, QHBoxLayout, QToolButton
from mir_robot_editor.motor_configuration.registers_view import RegistersView
from mir_robot_editor.motor_configuration.calibration_view import CalibrationView
from mir_robot_editor.motor_configuration.motor_configuration_view_model import MotorConfigurationViewModel, MotorConfigurationViewModel_MotorData
from mir_utils.ui.widgets import stylesheets, DialogBase
from mir_utils.ui.view_model_base import VMAction
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui import theme


class MotorConfigurationView(DialogBase, ViewBase[MotorConfigurationViewModel, VMAction]):
   
    def __init__(self, parent, view_model:MotorConfigurationViewModel):
        super().__init__(parent, view_model=view_model)
        self._btn_move = []
        self._view_model.property_changed.connect(self.on_property_changed)
        self.setup_ui()
        self.fill_grid_motors(self._view_model.motors_data)
        self.on_property_changed("is_calibrated", self._view_model.is_calibrated)
        
    def setup_ui(self):
        self.setWindowTitle("Réglages des moteurs")
        main_layout = QVBoxLayout(self)
        #toolbar
        toolbar = QHBoxLayout()

        btnCalibrate = QToolButton()
        btnCalibrate.setIcon(ViewBase.find_icon("calibration"))
        btnCalibrate.setText("Calibrer les moteurs...")
        btnCalibrate.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btnCalibrate.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        btnCalibrate.clicked.connect(self.calibrate_motors)
        # la calibration se fait au montage (guide), ou moteur par moteur (« Recalibrer un moteur »)
        btnCalibrate.setVisible(False)
        toolbar.addWidget(btnCalibrate)

        btnCalibrateFromMotors = QToolButton()
        btnCalibrateFromMotors.setIcon(ViewBase.find_icon("folder-open"))
        btnCalibrateFromMotors.setText("Charger la calibration depuis les moteurs...")
        btnCalibrateFromMotors.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btnCalibrateFromMotors.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        btnCalibrateFromMotors.clicked.connect(self.calibrate_from_motors)
        toolbar.addWidget(btnCalibrateFromMotors)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)
        
        #moteurs
        self.gridMotors = QGridLayout()
        main_layout.addLayout(self.gridMotors)

        #emergency stop
        self.btn_emergency_stop = QToolButton()
        self.btn_emergency_stop.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self.btn_emergency_stop.setIcon(self._icon("emergency_stop"))
        self.btn_emergency_stop.setToolTip("Arrêt d'urgence")
        self.btn_emergency_stop.setIconSize(QtCore.QSize(48, 48))
        self.btn_emergency_stop.clicked.connect(lambda : self._view_model.emergency_stop())
        main_layout.addWidget(self.btn_emergency_stop, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)        

        self.lbl_is_calibrated = QLabel("")

        main_layout.addWidget(self.lbl_is_calibrated)

        main_layout.addStretch()

    def calibrate_motors(self):
        self._view_model.execute_calibration_view_model(lambda vm : CalibrationView(self, vm).exec())

    def calibrate_from_motors(self):
        self._view_model.calibrate_from_motors()
        
    def show_registers(self, name:str):
        self._view_model.execute_registers_viewmodel(lambda vm: RegistersView(self, vm).exec(), name)

    def fill_grid_motors(self, motors_data: dict[str, MotorConfigurationViewModel_MotorData]):
        def addHeader(text, col):
            label = QLabel(text, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(stylesheets.header_style)
            self.gridMotors.addWidget(label, 0, col)    
        while self.gridMotors.count():
            item = self.gridMotors.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.pos_fields: dict[str, QLineEdit]= {}
        self.target_fields : dict[str, QLineEdit] = {}
        self.goal_vel_fields : dict[str, QLineEdit] = {}
        self.torque_fields = {}
        self.moving_fields = {}

        addHeader("Motor", 0)
        addHeader("Present POS", 1)
        addHeader("Action", 2)
        addHeader("Goal POS", 3)
        addHeader("Goal VEL", 4)

        if motors_data is None:
            return
        for r, (name, motor_data) in enumerate(motors_data.items()):
            row = r + 1
            #nom du moteur
            self.gridMotors.addWidget(QLabel(f"{name} ID={motor_data.motor.id}"), row, 0)
            #position
            pos_field = QtWidgets.QLineEdit()
            pos_field.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
            pos_field.setReadOnly(True)
            pos_field.setFixedWidth(80)
            pos_field.setStyleSheet(stylesheets.labels_style)
            pos_field.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            pos_field.setText(str(motor_data.pos))
            self.gridMotors.addWidget(pos_field, row, 1)
            self.pos_fields[name] = pos_field
            #move
            btnMove = QPushButton("Déplacer")
            self.gridMotors.addWidget(btnMove, row, 2)
            btnMove.clicked.connect(lambda _, n = name: self.move_to(n))            
            btnMove.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
            tbPos = QLineEdit()
            tbPos.setFixedWidth(80)
            tbPos.setText(str(motor_data.pos))
            tbPos.setEnabled(motor_data.can_set_pos())
            self.target_fields[name] = tbPos
            self.gridMotors.addWidget(tbPos, row, 3)
            tbVel = QLineEdit()
            tbVel.setFixedWidth(80)
            tbVel.setText(str(motor_data.vel))
            self.goal_vel_fields[name] = tbVel
            self.gridMotors.addWidget(tbVel, row, 4)

            btnStop = QPushButton()
            btnStop.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
            btnStop.setIcon(self._icon("stop"))
            self.gridMotors.addWidget(btnStop, row, 5)
            btnStop.clicked.connect(lambda _,n=name : self._view_model.stop_motor(n))
            #Registres
            btnRegisters = QPushButton("Registres...")
            btnRegisters.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
            btnRegisters.clicked.connect(lambda _, n = name: self.show_registers(n))
            self.gridMotors.addWidget(btnRegisters, row, 6)
            
        self.gridMotors.setColumnStretch(7, 1)                    

    def move_to(self, name:str):
        pos = self.target_fields[name].text()
        vel = self.goal_vel_fields[name].text()
        self._view_model.move_motor(name, float(pos), int(vel))
        
    def on_motor_data_changed(self, motors_dict: dict[str, MotorConfigurationViewModel_MotorData]):
        for key, motor_data in motors_dict.items():
            self.pos_fields[key].setText(str(motor_data.pos))

    def on_property_changed(self, property_name :str, property_value: object):
        if property_name == "is_calibrated":
            self.lbl_is_calibrated.setText("Moteurs calibrés, positions normalisées." if property_value else "Moteurs non calibrés, positions brutes")
            style_sheet = "font-size: 14px;"  
            if property_value:
                style_sheet += f"color: {theme.OK};"
            else:
                style_sheet += f"color: {theme.WARNING};"
            self.lbl_is_calibrated.setStyleSheet(style_sheet)
            motors_data = self._view_model.motors_data
            for key, tb in self.target_fields.items():
                tb.setText(str(motors_data[key].pos))
        elif property_name == "motors_data":
            for key, motor_data in property_value.items():
                self.pos_fields[key].setText(str(motor_data.pos))
            

