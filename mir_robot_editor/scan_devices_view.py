from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QCheckBox,
    QProgressBar,
    QPushButton,
    QToolButton,
    QGridLayout,
    QScrollArea,
)
from mir_robot_editor.scan_devices_view_model import ScanDevicesViewModel, DiscoveredDeviceViewModel, ScanDevicesVMAction
from mir_utils.ui.widgets import DialogBase, ToolButton
from mir_utils.ui.view_base import ViewBase
from mir_robot_editor.sensor_configuration_view import SensorConfigurationView
from mir_robot_editor.scan_devices_view_model import DiscoveredMotorBusViewModel, DiscoveredSensorViewModel
from mir_robot_editor.motor_configuration.motor_configure_IDs_view import MotorConfigureIDsView
from mir_robot_editor.scan_devices_view_model import ObservationsSelectionViewModel
from mir_devices.mir_device import ObservableProperty
from mir_robot_editor.robot_model.thumbnails import module_icon

THUMBNAIL_SIZE = 40

class ObservationsSelectionView(DialogBase):
    def __init__(self, parent, view_model:ObservationsSelectionViewModel):
        super().__init__(parent)
        self._view_model = view_model
        self.setWindowTitle("Sélection des observations")
        observables: dict[str, dict[str, ObservableProperty]] = view_model.get_observables()

        # Layout principal de la boîte de dialogue
        main_layout = QVBoxLayout(self)

        # Barre supérieure avec boutons Tout sélectionner / Tout déselectionner
        top_bar = QHBoxLayout()
        top_bar.addWidget(ToolButton("select_all", lambda: self.select(True), enabled=True, border=False, size=24))
        top_bar.addWidget(ToolButton("unselect_all", lambda: self.select(False), enabled=True, border=False, size=24))
        top_bar.addStretch()
        main_layout.addLayout(top_bar)

        # Zone centrale listant les observables sous forme de cases à cocher
        center_frame = QFrame(self)
        grid = QGridLayout(center_frame)
        grid.setContentsMargins(4, 4,4,4)
        grid.setSpacing(4)

        # Stocker les checkboxes pour opérations globales
        self._checkboxes: list[QCheckBox] = []

        row = 0
        col_count = 2

        for group, items in observables.items():
            # Titre de groupe (nom du device/source) avec columnSpan = 2
            lbl_group = QLabel(group)
            lbl_group.setStyleSheet("font-weight: bold; margin-top:8px;")
            grid.addWidget(lbl_group, row, 0, 1, col_count)
            row += 1

            # Ajouter les observables de cette source dans la grille unique
            for prop_key, prop in items.items():
                cb = QCheckBox(prop_key)
                cb.setChecked(True)
                self._checkboxes.append(cb)
                grid.addWidget(cb, row, 0)
                grid.addWidget(QLabel(str(prop.stype)))
                row += 1

        grid.setRowStretch(row, 1)

        scroll_area = QScrollArea()
        scroll_area.setWidget(center_frame)
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)

        # Barre inférieure avec Appliquer / Annuler
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        btn_apply = QPushButton("Appliquer")
        btn_cancel = QPushButton("Annuler")
        bottom_bar.addWidget(btn_apply)
        bottom_bar.addWidget(btn_cancel)
        main_layout.addLayout(bottom_bar)
        btn_cancel.clicked.connect(self._view_model.cancel)
        btn_apply.clicked.connect(self.on_apply)

        view_model.close_required.connect(self.close)

        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen:
            available_geometry = screen.availableGeometry()
            self.setMaximumSize(available_geometry.width() * 0.75,available_geometry.height() * 0.8)
            self.move(available_geometry.center() - self.rect().center())

    def select(self, select:bool):
        for cb in self._checkboxes:
            cb.setChecked(select)

    def on_apply(self):
        # Propager la sélection vers le view_model si méthode prévue
        selected = [cb.text() for cb in self._checkboxes if cb.isChecked()]
        self._view_model.set_selected_observables(selected)


class ScanDevicesView(DialogBase, ViewBase[ScanDevicesViewModel, ScanDevicesVMAction]):
    def __init__(self, parent, view_model:ScanDevicesViewModel):
        super().__init__(parent, view_model=view_model)
        self.setWindowTitle("Recherche des appareils")

        # Layout principal
        main_layout = QVBoxLayout(self)

        #barre supérieure
        top_bar = QHBoxLayout()
        btn_scan = QToolButton()
        btn_stop = QToolButton()
        self._scan_action = self._make_action(ScanDevicesVMAction.SCAN, self.btn_scan_clicked, "")
        self._accept_action = self._make_action(ScanDevicesVMAction.ACCEPT, self.btn_accept_clicked, "")
        self._cancel_action = self._make_action(ScanDevicesVMAction.CANCEL, view_model.cancel, "")
        self._stop_action = self._make_action(ScanDevicesVMAction.STOP, self.btn_stop_clicked, "")
        self._configure_device_action = self._make_action(ScanDevicesVMAction.CONFIGURE_DEVICE, None, "")
        btn_scan.setDefaultAction(self._scan_action)
        btn_stop.setDefaultAction(self._stop_action)
        top_bar.addWidget(btn_scan)
        top_bar.addWidget(btn_stop)

        self.bar_inprogress = QProgressBar()
        self.bar_inprogress.setVisible(False)
        self._lbl_status = QLabel("")
        top_bar.addWidget(self._lbl_status)        
        top_bar.addWidget(self.bar_inprogress)        
        top_bar.addStretch()

        main_layout.addLayout(top_bar)
        main_layout.addSpacing(10)

        # grille des appareils découverts
        self.frame = QFrame()
        self.frame.setFrameShape(QFrame.Shape.NoFrame)
        # sélecteur explicite : sans lui, le style s'appliquerait aussi aux listes déroulantes (texte illisible sur macOS)
        self.frame.setObjectName("devicesFrame")
        self.frame.setStyleSheet("QFrame#devicesFrame { background-color: #f8f8f8 }")
        self.devices_layout = QGridLayout(self.frame)
        self.devices_layout.setSpacing(10)  # Espace entre les blocs d'éléments
        self.devices_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addWidget(self.frame)
        main_layout.addStretch()

        #status
        self.lblStatus = QLabel("")
        main_layout.addWidget(self.lblStatus, stretch=1)
        
        #barre inférieure
        bottom_bar = QHBoxLayout()
        btn_accept = QToolButton()
        btn_accept.setDefaultAction(self._accept_action)
        bottom_bar.addWidget(btn_accept)
        

        btn_cancel = QToolButton()
        btn_cancel.setDefaultAction(self._cancel_action)
        bottom_bar.addWidget(btn_cancel)
        btn_cancel.clicked.connect(self._view_model.cancel)
        bottom_bar.addStretch()

        main_layout.addLayout(bottom_bar)

        self._view_model.progress_changed.connect(self.on_progress_changed)
        self._view_model.scan_completed.connect(self.on_scan_completed)
        self._view_model.status_changed.connect(self.on_status_changed)
        self._view_model.close_required.connect(self.close)

    def set_data(self, data: list[DiscoveredDeviceViewModel] | None, enable_configure:bool) -> None:
        
        while self.devices_layout.count() > 0:
            item = self.devices_layout.takeAt(0)
            widget = item.widget() # type: ignore
            if widget is not None:
                widget.deleteLater()
                
        # Génération dynamique des widgets
        # colonnes : 0 avertissement | 1 case à cocher (type) | 2 miniature | 3 identifiant | 4 description | 5 configurer
        if data is not None:
            row = 0
            for device in data:
                #warning
                warning = device.get_warning()
                if warning != "":
                    lbl_warning = QLabel("⚠️")
                    lbl_warning.setToolTip(warning)
                    self.devices_layout.addWidget(lbl_warning, row, 0)
                #checkbox
                checkbox = QCheckBox(device.type())
                checkbox.setChecked(device.get_selected())
                checkbox.setEnabled(warning == "")
                checkbox.toggled.connect(lambda checked, d=device: d.set_selected(checked))
                self.devices_layout.addWidget(checkbox, row, 1)
                if isinstance(device, DiscoveredMotorBusViewModel):
                    #port du bus, puis une ligne par moteur
                    self.devices_layout.addWidget(QLabel(device.port()), row, 3, 1, 2)
                else:
                    self.devices_layout.addWidget(self._thumbnail(device.module_type()), row, 2)
                    self.devices_layout.addWidget(QLabel(device.key()), row, 3)
                    self.devices_layout.addWidget(QLabel(device.info()), row, 4)
                #button
                if enable_configure and warning == "":
                    button = QToolButton(self)
                    self.devices_layout.addWidget(button, row, 5)
                    button.setDefaultAction(self._configure_device_action)
                    button.clicked.connect(lambda *_, d=device: self._on_configure_clicked(d))
                row += 1
                if isinstance(device, DiscoveredMotorBusViewModel):
                    row = self._add_motor_rows(device, row)
            self.devices_layout.setColumnStretch(6, 1)
            self.devices_layout.setRowStretch(row, 1)

    def _add_motor_rows(self, bus: DiscoveredMotorBusViewModel, row: int) -> int:
        """Une ligne par moteur : miniature du module, ID, et le module qui le contient (servo, pince...)."""
        choices = bus.module_type_choices()
        for motor, motor_id in bus.motors():
            thumbnail = self._thumbnail(bus.motor_type(motor))
            self.devices_layout.addWidget(thumbnail, row, 2)
            self.devices_layout.addWidget(QLabel(f"ID {motor_id}"), row, 3)
            combo = QComboBox()
            for module_type in choices:
                combo.addItem(module_type.removeprefix("mir_"), module_type)
            combo.setCurrentIndex(max(0, combo.findData(bus.motor_type(motor))))
            combo.setToolTip(f"Module qui contient le moteur {motor}")
            combo.currentIndexChanged.connect(
                lambda _, m=motor, c=combo, t=thumbnail: self._on_motor_type_changed(bus, m, c.currentData(), t))
            line = QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(QLabel(motor))
            line.addWidget(combo)
            line.addStretch()
            cell = QFrame()
            cell.setLayout(line)
            self.devices_layout.addWidget(cell, row, 4)
            row += 1
        return row

    def _on_motor_type_changed(self, bus: DiscoveredMotorBusViewModel, motor: str, module_type: str, thumbnail: QLabel):
        bus.set_motor_type(motor, module_type)
        icon = module_icon(module_type, THUMBNAIL_SIZE)
        if icon is not None:
            thumbnail.setPixmap(icon.pixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE))

    @staticmethod
    def _thumbnail(module_type: str | None) -> QLabel:
        label = QLabel()
        label.setFixedSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon = module_icon(module_type, THUMBNAIL_SIZE) if module_type else None
        if icon is not None:
            label.setPixmap(icon.pixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
            label.setToolTip(module_type.removeprefix("mir_"))
        return label

    def _on_configure_clicked(self, device: DiscoveredDeviceViewModel):
        if isinstance(device, DiscoveredSensorViewModel):
            self._view_model.execute_configure_device(lambda vm: SensorConfigurationView(self, vm).exec(), device)
        elif isinstance(device, DiscoveredMotorBusViewModel):
            self._view_model.execute_configure_device(lambda vm: MotorConfigureIDsView(self, vm).exec(), device)

    def on_status_changed(self, status:str):
        self._lbl_status.setText(status)

    def on_progress_changed(self, value:int, devices:list[DiscoveredDeviceViewModel]):
        self.bar_inprogress.setValue(value)
        self.bar_inprogress.setVisible(True)
        self.set_data(devices, False)

    def on_scan_completed(self, result:list[DiscoveredDeviceViewModel]):
        self.bar_inprogress.setVisible(False)
        self.set_data(result, True)

    def btn_scan_clicked(self):
        self.set_data(None, False)
        self._view_model.scan_devices()

    def btn_accept_clicked(self):
        if self._view_model.accept():
            self._view_model.execute_observations_selection(lambda vm:ObservationsSelectionView(self, vm).exec())

    def btn_stop_clicked(self):
        self._view_model.stop_scan()
        