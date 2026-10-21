from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout
from mir_utils.ui.widgets import (ChoiceCard, DialogBase, DialogFooter, DialogHeader, MessageLabel, Section,
                                  dialog_frame, mono_font, overline)
from mir_robot_editor.capteurs.esp32_view_model import Esp32ViewModel, TYPES_CAPTEUR


def _champ(libelle: str, widget) -> QVBoxLayout:
    """Un champ avec son libellé au-dessus."""
    colonne = QVBoxLayout()
    colonne.setSpacing(4)
    label = QLabel(libelle)
    label.setObjectName("Muted")
    label.setBuddy(widget)
    colonne.addWidget(label)
    colonne.addWidget(widget)
    return colonne


class Esp32View(DialogBase):
    def __init__(self, parent, view_model: Esp32ViewModel):
        super().__init__(parent, default_width=640, default_height=800)
        self._vm = view_model
        self.setWindowTitle("Module capteur ESP32")
        footer = DialogFooter()
        footer.add_button("Fermer", self.close)
        layout = dialog_frame(self, DialogHeader("Module capteur ESP32",
                                                 "Lidar, météo… : installer le firmware ou changer de réseau Wi-Fi.",
                                                 icon="esp_sensors"), footer)

        # --- 1. réseau Wi-Fi, mémorisé sur ce PC
        reseau = Section("Réseau Wi-Fi du PC", 1)
        grille = QGridLayout()
        grille.setHorizontalSpacing(12)
        grille.setVerticalSpacing(8)
        self._ssid = QLineEdit(self._vm.ssid)
        self._ssid.setPlaceholderText("nom du réseau")
        grille.addWidget(QLabel("Nom"), 0, 0)
        grille.addWidget(self._ssid, 0, 1)
        pwd_line = QHBoxLayout()
        self._pwd = QLineEdit(self._vm.mot_de_passe)
        self._pwd.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_line.addWidget(self._pwd, 1)
        voir = QPushButton("Afficher")
        voir.setCheckable(True)
        voir.toggled.connect(lambda v: self._pwd.setEchoMode(QLineEdit.EchoMode.Normal if v else QLineEdit.EchoMode.Password))
        pwd_line.addWidget(voir)
        grille.addWidget(QLabel("Mot de passe"), 1, 0)
        grille.addLayout(pwd_line, 1, 1)
        note = QLabel("Mémorisé sur ce PC pour les prochains modules.")
        note.setObjectName("Muted")
        grille.addWidget(note, 2, 1)
        grille.setColumnStretch(1, 1)
        reseau.body.addLayout(grille)
        layout.addWidget(reseau)

        # --- 2. liaison avec le module
        liaison = Section("Liaison avec le module", 2)
        choix = QHBoxLayout()
        choix.setSpacing(10)
        self._cable = ChoiceCard("Câble USB (conseillé)", "Garde l'ancien réseau en secours")
        self._bluetooth = ChoiceCard("Bluetooth", "Dans les 60 s après l'allumage")
        ChoiceCard.group(self._cable, self._bluetooth)
        choix.addWidget(self._cable, 1)
        choix.addWidget(self._bluetooth, 1)
        liaison.body.addLayout(choix)
        port_line = QHBoxLayout()
        self._ports = QComboBox()
        self._ports.setFont(mono_font())
        port_line.addWidget(self._ports, 1)
        self._btn_ports = QPushButton("Rafraîchir")
        self._btn_ports.clicked.connect(self._remplir_ports)
        port_line.addWidget(self._btn_ports)
        liaison.body.addLayout(port_line)
        self._cable.toggled.connect(self._update)
        action = QHBoxLayout()
        action.addStretch(1)
        self._btn_wifi = QPushButton("Envoyer le réseau Wi-Fi")
        self._btn_wifi.setObjectName("Primary")
        self._btn_wifi.setAutoDefault(False)
        self._btn_wifi.clicked.connect(self._envoyer_wifi)
        action.addWidget(self._btn_wifi)
        liaison.body.addLayout(action)
        layout.addWidget(liaison)

        # --- 3. firmware (câble uniquement)
        firmware = Section("Installer le firmware", 3, "module neuf ou mise à jour, câble USB")
        champs = QHBoxLayout()
        champs.setSpacing(10)
        self._type = QComboBox()
        self._type.addItems(TYPES_CAPTEUR)
        champs.addLayout(_champ("Capteur", self._type), 1)
        self._nom = QLineEdit("lidar")
        self._nom.setFont(mono_font())
        self._nom.setToolTip("Nom du module sur le réseau (sensor_id)")
        champs.addLayout(_champ("Nom du module", self._nom), 1)
        firmware.body.addLayout(champs)
        action_fw = QHBoxLayout()
        action_fw.addStretch(1)
        self._btn_firmware = QPushButton("Installer et envoyer le réseau")
        self._btn_firmware.setObjectName("Primary")
        self._btn_firmware.setAutoDefault(False)
        self._btn_firmware.clicked.connect(self._installer)
        action_fw.addWidget(self._btn_firmware)
        firmware.body.addLayout(action_fw)
        layout.addWidget(firmware)

        self._message = MessageLabel()
        layout.addWidget(self._message)
        layout.addWidget(overline("Journal"))
        self._journal = QPlainTextEdit()
        self._journal.setObjectName("Journal")
        self._journal.setFont(mono_font(12))
        self._journal.setReadOnly(True)
        self._journal.setMaximumBlockCount(2000)
        self._journal.setMinimumHeight(70)
        layout.addWidget(self._journal, 1)

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
        self._ports.setVisible(cable)
        self._btn_ports.setVisible(cable)
        self._btn_ports.setEnabled(not occupe)
        self._btn_wifi.setEnabled(not occupe and (a_port or not cable))
        self._btn_firmware.setEnabled(not occupe and cable and a_port and self._vm.firmware_present())
        message = self._vm.message
        if cable and not a_port and not occupe:
            message = "✗ Aucun module branché en USB : vérifiez le câble (un câble de données, pas de charge seule), puis Rafraîchir."
        self._message.set_message(message)

    def closeEvent(self, event):
        if self._vm.occupe:
            event.ignore()      # on n'interrompt pas une installation en cours
            return
        super().closeEvent(event)

    def reject(self):
        if not self._vm.occupe:
            super().reject()
