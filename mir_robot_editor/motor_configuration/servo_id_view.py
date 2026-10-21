from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout
from mir_utils.ui.widgets import DialogBase, DialogFooter, DialogHeader, MessageLabel, Section, dialog_frame
from mir_robot_editor.motor_configuration.servo_id_view_model import ServoIdViewModel, ID_MIN, ID_MAX


class ServoIdView(DialogBase):
    def __init__(self, parent, view_model: ServoIdViewModel):
        super().__init__(parent, default_width=560, default_height=420)
        self._vm = view_model
        self.setWindowTitle("Changer l'ID d'un servo")
        footer = DialogFooter()
        footer.add_button("Fermer", self.close)
        layout = dialog_frame(self, DialogHeader("Changer l'ID d'un servo",
                                                 "Lire l'ID d'un servo branché seul et lui en donner un nouveau.",
                                                 icon="servo_id"), footer)

        intro = QLabel("Branchez <b>un seul servo</b> sur le câble USB des servos : s'il y en a plusieurs, l'outil "
                       "refuse d'écrire. Changer l'ID d'un servo déjà monté sur un robot oblige à refaire "
                       "sa configuration.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        section = Section("Servo branché")
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)
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
        self._btn_ecrire.setObjectName("Primary")
        self._btn_ecrire.clicked.connect(lambda: self._vm.ecrire(self._nouvel_id.value()))
        id_line.addWidget(self._btn_ecrire)
        id_line.addStretch(1)
        form.addRow("Nouvel ID", id_line)
        section.body.addLayout(form)
        layout.addWidget(section)

        if self._vm.ids_du_robot:
            ids = ", ".join(f"{moteur} = {i}" for moteur, i in self._vm.ids_du_robot.items())
            rappel = QLabel(f"ID prévus par le robot ouvert : {ids}")
            rappel.setWordWrap(True)
            rappel.setObjectName("Muted")
            layout.addWidget(rappel)

        self._message = MessageLabel()
        layout.addWidget(self._message)
        layout.addStretch(1)

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
        self._message.set_message(message)

    def closeEvent(self, event):
        if self._vm.occupe:
            event.ignore()      # on n'interrompt pas une écriture en cours
            return
        super().closeEvent(event)

    def reject(self):
        if not self._vm.occupe:
            super().reject()
