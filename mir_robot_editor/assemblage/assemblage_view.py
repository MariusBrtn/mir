from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)
from mir_utils.ui.widgets import DialogBase
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_robot_editor.assemblage.assemblage_view_model import AssemblageViewModel, AssemblageVMAction, Phase
from mir_robot_editor.assemblage.bus import BusFeetech, BusSimule, ports_disponibles
from mir_utils.ui import theme

ICONES_ETAT = {"à faire": "○", "en cours": "▶", "fait": "✓"}


class AssemblageView(DialogBase):
    """Fenêtre du guide de montage."""

    def __init__(self, parent, view_model: AssemblageViewModel, essai_sans_materiel: bool = False):
        super().__init__(parent, default_width=1200, default_height=760)
        self.setWindowTitle(view_model.titre())
        self._vm = view_model
        self._essai_sans_materiel = essai_sans_materiel
        view_model.changed.connect(self._refresh)
        view_model.model_changed.connect(lambda model, data: self._viewport.set_model(model, data, keep_camera=True))
        view_model.redraw_required.connect(lambda: self._viewport.update())

        root = QHBoxLayout(self)
        self._viewport = MujocoWidget()
        root.addWidget(self._viewport, 1)

        right = QVBoxLayout()
        self._pages = QStackedWidget()
        self._pages.addWidget(self._make_start_page())
        self._pages.addWidget(self._make_step_page())
        right.addWidget(self._pages, 1)
        panel = QWidget()
        panel.setLayout(right)
        panel.setFixedWidth(420)
        root.addWidget(panel)
        self._viewport.show_message("Le robot apparaîtra ici, module par module.")

    # ------------------------------------------------------------------ page de départ
    def _make_start_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel(self._vm.titre())
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        texte = QLabel("Le guide montre, module après module, où poser chaque module. Les servos sont détectés et "
                       "reçoivent leur ID dès qu'on les branche, puis on les calibre à la main.\n\n"
                       "Branchez le câble USB du bus des servos, choisissez son port, puis cliquez sur Commencer. "
                       "Partez d'un robot démonté : on branche les modules un par un.")
        texte.setWordWrap(True)
        layout.addWidget(texte)
        row = QHBoxLayout()
        row.addWidget(QLabel("Port des servos"))
        self.cb_port = QComboBox()
        row.addWidget(self.cb_port, 1)
        btn_refresh = QPushButton("Actualiser")
        btn_refresh.clicked.connect(self._fill_ports)
        row.addWidget(btn_refresh)
        layout.addLayout(row)
        self.btn_start = QPushButton("Commencer")
        self.btn_start.setStyleSheet("font-weight: bold; padding: 6px;")
        self.btn_start.clicked.connect(self._on_start)
        layout.addWidget(self.btn_start)
        self.lbl_start_error = QLabel()
        self.lbl_start_error.setWordWrap(True)
        self.lbl_start_error.setStyleSheet(f"color: {theme.ERROR};")
        layout.addWidget(self.lbl_start_error)
        layout.addStretch(1)
        self._fill_ports()
        return page

    def _fill_ports(self):
        self.cb_port.clear()
        if self._essai_sans_materiel:
            self.cb_port.addItem("(bus simulé)")
            return
        ports = ports_disponibles()
        self.cb_port.addItems(ports)
        current = self._vm.configuration().motor_bus.motor_port if self._vm.configuration().motor_bus else ""
        if current in ports:
            self.cb_port.setCurrentText(current)
        self.btn_start.setEnabled(bool(ports) or self._vm.configuration().motor_bus is None)
        self.lbl_start_error.setText("" if ports else "Aucun port série trouvé : branchez le câble USB des servos.")

    def _on_start(self):
        try:
            if self._essai_sans_materiel:
                self._vm.demarrer(BusSimule(), None)
            else:
                port = self.cb_port.currentText() or None
                self._vm.demarrer(BusFeetech(port) if port else BusSimule(), port)
        except Exception as e:
            self.lbl_start_error.setText(f"Impossible d'ouvrir le bus : {e}")
            return
        self._pages.setCurrentIndex(1)
        self._refresh()

    # ------------------------------------------------------------------ étapes
    def _make_step_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.lbl_step = QLabel()
        self.lbl_step.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(self.lbl_step)
        self.lbl_consigne = QLabel()
        self.lbl_consigne.setWordWrap(True)
        self.lbl_consigne.setStyleSheet("font-size: 14px; padding: 8px; background: palette(alternate-base);")
        self.lbl_consigne.setMinimumHeight(110)
        self.lbl_consigne.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.lbl_consigne)
        self.lbl_detection = QLabel()
        self.lbl_detection.setStyleSheet(f"color: {theme.OK};")
        layout.addWidget(self.lbl_detection)
        self.lbl_info = QLabel()
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(self.lbl_info)

        self.sens_box = QWidget()
        sens = QHBoxLayout(self.sens_box)
        sens.setContentsMargins(0, 0, 0, 0)
        btn_oui = QPushButton("Oui, même sens")
        btn_oui.clicked.connect(lambda: self._vm.sens(True))
        sens.addWidget(btn_oui)
        btn_non = QPushButton("Non, sens inverse")
        btn_non.clicked.connect(lambda: self._vm.sens(False))
        sens.addWidget(btn_non)
        layout.addWidget(self.sens_box)

        buttons = QHBoxLayout()
        self.btn_recommencer = QPushButton("Recommencer ce module")
        self.btn_recommencer.clicked.connect(self._vm.recommencer)
        buttons.addWidget(self.btn_recommencer)
        self.btn_suivant = QPushButton("Suivant")
        self.btn_suivant.setStyleSheet("font-weight: bold;")
        self.btn_suivant.clicked.connect(self._on_suivant)
        buttons.addWidget(self.btn_suivant)
        layout.addLayout(buttons)

        layout.addWidget(QLabel("Modules"))
        self.list_steps = QListWidget()
        self.list_steps.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.list_steps, 1)
        return page

    def _on_suivant(self):
        if self._vm.termine():
            if self._vm.finaliser():
                self.accept()
        else:
            self._vm.suivant()

    def _refresh(self):
        vm = self._vm
        e = vm.etape()
        total = len(vm.etapes)
        self.lbl_step.setText("Montage terminé" if e is None else f"Module {vm.index + 1} / {total} · {e.titre()}")
        self.lbl_consigne.setText(vm.consigne())
        self.lbl_detection.setText(vm.detection)
        self.lbl_info.setText(vm.info)
        self.sens_box.setVisible(e is not None and vm.phase == Phase.SENS)
        self.btn_suivant.setText(vm.texte_suivant())
        self.btn_suivant.setEnabled(vm.termine() or vm.get_action(AssemblageVMAction.SUIVANT).enabled)
        self.btn_suivant.setVisible(e is None or vm.phase != Phase.SENS)
        self.btn_recommencer.setEnabled(e is not None)
        self.list_steps.clear()
        for etape in vm.etapes:
            item = QListWidgetItem(f"{ICONES_ETAT[etape.etat]}  {etape.titre()}")
            if etape.etat == "en cours":
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.list_steps.addItem(item)

    def done(self, result):
        self._viewport.show_message("")     # libère le rendu OpenGL
        super().done(result)
