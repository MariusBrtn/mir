from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout
from mir_utils.ui.widgets import DialogBase
from mir_utils.ui import theme
from mir_robot_editor.motor_configuration.servo_id_view_model import ServoIdViewModel, ID_MIN, ID_MAX


class ServoIdView(DialogBase):
    def __init__(self, parent, view_model: ServoIdViewModel):
        super().__init__(parent, default_width=520, default_height=320)
        self._vm = view_model
        self.setWindowTitle("Changer l'ID d'un servo")
        layout = QVBoxLayout(self)

        intro = QLabel("Branchez <b>un seul servo</b> sur le câble USB des servos : s'il y en a plusieurs, l'outil "
                       "refuse d'écrire. Changer l'ID d'un servo déjà monté sur un robot oblige à refaire "
                       "sa configuration.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        port_line = QHBoxLayout()
        self._ports = QComboBox()
        self._ports.addItems(self._vm.ports())
        port_line.addWidget(self._ports, 1)
        self._btn_chercher = QPushButton("Chercher")
        self._btn_chercher.clicked.connect(lambda: self._vm.chercher(self._ports.currentText()))
        port_line.addWidget(self._btn_chercher)
        form.addRow("Port", port_line)

        id_line = QHBoxLayout()
        self._nouvel_id = QSpinBox()
        self._nouvel_id.setRange(ID_MIN, ID_MAX)
        id_line.addWidget(self._nouvel_id)
        self._btn_ecrire = QPushButton("Écrire")
        self._btn_ecrire.clicked.connect(lambda: self._vm.ecrire(self._nouvel_id.value()))
        id_line.addWidget(self._btn_ecrire)
        id_line.addStretch(1)
        form.addRow("Nouvel ID", id_line)
        layout.addLayout(form)

        if self._vm.ids_du_robot:
            ids = ", ".join(f"{moteur} = {i}" for moteur, i in self._vm.ids_du_robot.items())
            rappel = QLabel(f"ID prévus par le robot ouvert : {ids}")
            rappel.setWordWrap(True)
            rappel.setObjectName("Muted")
            layout.addWidget(rappel)

        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        layout.addStretch(1)
        btn_fermer = QPushButton("Fermer")
        btn_fermer.clicked.connect(self.close)
        layout.addWidget(btn_fermer)

        self._vm.changed.connect(self._update)
        self._update()

    def _update(self):
        occupe = self._vm.occupe
        self._btn_chercher.setEnabled(not occupe and self._ports.count() > 0)
        self._ports.setEnabled(not occupe)
        trouve = self._vm.id_trouve()
        self._nouvel_id.setEnabled(not occupe and trouve is not None)
        self._btn_ecrire.setEnabled(not occupe and trouve is not None)
        message = self._vm.message if self._ports.count() else "✗ Aucun port série trouvé : branchez le câble USB des servos."
        color = theme.OK if message.startswith("✓") else theme.ERROR if message.startswith("✗") else theme.TEXT
        self._message.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._message.setText(message)

    def closeEvent(self, event):
        if self._vm.occupe:
            event.ignore()      # on n'interrompt pas une écriture en cours
            return
        super().closeEvent(event)

    def reject(self):
        if not self._vm.occupe:
            super().reject()
