from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout)
from mir_utils.ui.widgets import DialogBase
from mir_utils.ui import theme
from mir_robot_editor.capteurs.esp32_view_model import Esp32ViewModel, TYPES_CAPTEUR


class Esp32View(DialogBase):
    def __init__(self, parent, view_model: Esp32ViewModel):
        super().__init__(parent, default_width=620, default_height=620)
        self._vm = view_model
        self.setWindowTitle("Module capteur ESP32")
        layout = QVBoxLayout(self)

        intro = QLabel("Les capteurs ESP32 (lidar, météo…) communiquent avec MIR en Wi-Fi. Le module doit connaître "
                       "le réseau Wi-Fi du PC : on le lui envoie par le câble USB, ou sans câble en Bluetooth "
                       "juste après l'avoir allumé.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # --- réseau Wi-Fi, mémorisé sur ce PC
        reseau = QGroupBox("Réseau Wi-Fi du PC")
        form = QFormLayout(reseau)
        self._ssid = QLineEdit(self._vm.ssid)
        self._ssid.setPlaceholderText("nom du réseau")
        form.addRow("Nom", self._ssid)
        pwd_line = QHBoxLayout()
        self._pwd = QLineEdit(self._vm.mot_de_passe)
        self._pwd.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_line.addWidget(self._pwd, 1)
        voir = QPushButton("Afficher")
        voir.setCheckable(True)
        voir.toggled.connect(lambda v: self._pwd.setEchoMode(QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        pwd_line.addWidget(voir)
        form.addRow("Mot de passe", pwd_line)
        note = QLabel("Mémorisé sur ce PC pour les prochains modules.")
        note.setObjectName("Muted")
        form.addRow("", note)
        layout.addWidget(reseau)

        # --- liaison avec le module
        liaison = QGroupBox("Liaison avec le module")
        lay = QVBoxLayout(liaison)
        self._cable = QRadioButton("Câble USB (conseillé : garde l'ancien réseau en secours)")
        self._bluetooth = QRadioButton("Bluetooth, sans câble (dans les 60 s après l'allumage du module)")
        groupe = QButtonGroup(self)
        groupe.addButton(self._cable)
        groupe.addButton(self._bluetooth)
        lay.addWidget(self._cable)
        port_line = QHBoxLayout()
        port_line.addSpacing(24)
        self._ports = QComboBox()
        port_line.addWidget(self._ports, 1)
        self._btn_ports = QPushButton("Rafraîchir")
        self._btn_ports.clicked.connect(self._remplir_ports)
        port_line.addWidget(self._btn_ports)
        lay.addLayout(port_line)
        lay.addWidget(self._bluetooth)
        self._cable.toggled.connect(self._update)
        layout.addWidget(liaison)

        self._btn_wifi = QPushButton("Envoyer le réseau Wi-Fi")
        self._btn_wifi.clicked.connect(self._envoyer_wifi)
        layout.addWidget(self._btn_wifi)

        # --- firmware (câble uniquement)
        firmware = QGroupBox("Installer le firmware (module neuf ou mise à jour, câble USB)")
        form_fw = QFormLayout(firmware)
        self._type = QComboBox()
        self._type.addItems(TYPES_CAPTEUR)
        form_fw.addRow("Capteur", self._type)
        self._nom = QLineEdit("lidar")
        self._nom.setToolTip("Nom du module sur le réseau (sensor_id)")
        form_fw.addRow("Nom du module", self._nom)
        self._btn_firmware = QPushButton("Installer le firmware et envoyer le réseau Wi-Fi")
        self._btn_firmware.clicked.connect(self._installer)
        form_fw.addRow(self._btn_firmware)
        layout.addWidget(firmware)

        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        self._journal = QPlainTextEdit()
        self._journal.setReadOnly(True)
        self._journal.setMaximumBlockCount(2000)
        self._journal.setPlaceholderText("Journal")
        layout.addWidget(self._journal, 1)
        btn_fermer = QPushButton("Fermer")
        btn_fermer.clicked.connect(self.close)
        layout.addWidget(btn_fermer)

        self._vm.changed.connect(self._update)
        self._vm.log.connect(self._journal.appendPlainText)
        self._remplir_ports()

    def _remplir_ports(self):
        self._ports.clear()
        self._ports.addItems(self._vm.ports())
        # par défaut le câble s'il y a un module branché, sinon le Bluetooth
        (self._cable if self._ports.count() else self._bluetooth).setChecked(True)
        self._update()

    def _port(self) -> str | None:
        return self._ports.currentText() if self._cable.isChecked() else None

    def _envoyer_wifi(self):
        self._vm.envoyer_wifi(self._ssid.text(), self._pwd.text(), self._port())

    def _installer(self):
        self._journal.clear()
        self._vm.installer_firmware(self._ssid.text(), self._pwd.text(), self._ports.currentText(),
                                    self._type.currentText(), self._nom.text())

    def _update(self):
        occupe = self._vm.occupe
        cable = self._cable.isChecked()
        a_port = self._ports.count() > 0
        for w in (self._ssid, self._pwd, self._cable, self._bluetooth, self._type, self._nom):
            w.setEnabled(not occupe)
        self._ports.setEnabled(not occupe and cable)
        self._btn_ports.setEnabled(not occupe)
        self._btn_wifi.setEnabled(not occupe and (a_port or not cable))
        self._btn_firmware.setEnabled(not occupe and cable and a_port and self._vm.firmware_present())
        message = self._vm.message
        if cable and not a_port and not occupe:
            message = "✗ Aucun module branché en USB : vérifiez le câble (un câble de données, pas de charge seule), puis Rafraîchir."
        color = theme.OK if message.startswith("✓") else theme.ERROR if message.startswith("✗") else theme.TEXT
        self._message.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._message.setText(message)

    def closeEvent(self, event):
        if self._vm.occupe:
            event.ignore()      # on n'interrompt pas une installation en cours
            return
        super().closeEvent(event)

    def reject(self):
        if not self._vm.occupe:
            super().reject()
