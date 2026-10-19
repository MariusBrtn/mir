"""
Piloter → IA : à gauche le modèle entraîné et ses réglages, au centre le robot simulé en 3D, à droite ce que voit le
modèle (ses caméras), en direct.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)
from mir_robot_editor.ia.ia_view_model import IAViewModel, IAVMAction
from mir_robot_editor.observations_widget import VideoWidget
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_utils.ui.view_base import ViewBase


class IAView(QWidget, ViewBase[IAViewModel, IAVMAction]):
    def __init__(self, parent, view_model: IAViewModel):
        super().__init__(parent, view_model=view_model)  # type: ignore
        vm = self._view_model
        vm.robot_changed.connect(self._on_robot_changed)
        vm.modeles_changed.connect(self._remplir_modeles)
        vm.busy_state_changed.connect(lambda _: self._update_buttons())
        vm.observation_ready.connect(self._on_observation)
        vm.etat_changed.connect(self.lbl_etat_set)
        self._simulation = False
        self._cameras: dict[str, VideoWidget] = {}

        root = QHBoxLayout(self)
        root.addWidget(self._make_left(), 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viewport = MujocoWidget()
        splitter.addWidget(self._viewport)
        vues = QWidget()
        self._vues_layout = QVBoxLayout(vues)
        self._vues_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._vues_aide = QLabel("Ce que voit le modèle (ses caméras) s'affiche ici pendant qu'il pilote le robot.")
        self._vues_aide.setWordWrap(True)
        self._vues_aide.setObjectName("Muted")
        self._vues_layout.addWidget(self._vues_aide)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(vues)
        scroll.setMinimumWidth(350)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        root.addWidget(splitter, 1)

        self._timer_3d = QTimer(self)
        self._timer_3d.setInterval(33)
        self._timer_3d.timeout.connect(self._viewport.update)
        self._remplir_modeles()
        self._on_robot_changed()

    # ------------------------------------------------------------------ construction
    def _make_left(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        titre = QLabel("Modèle entraîné")
        titre.setStyleSheet("font-weight: bold;")
        layout.addWidget(titre)
        aide = QLabel("Entraînés dans l'étape « Entraîner un modèle ».")
        aide.setObjectName("Muted")
        aide.setWordWrap(True)
        layout.addWidget(aide)
        self.list_modeles = QListWidget()
        self.list_modeles.currentItemChanged.connect(lambda *_: self._on_modele_choisi())
        layout.addWidget(self.list_modeles, 1)
        self.lbl_modele = QLabel()
        self.lbl_modele.setWordWrap(True)
        self.lbl_modele.setObjectName("Muted")
        layout.addWidget(self.lbl_modele)

        form = QFormLayout()
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(1, 100)
        self.sp_fps.setSuffix(" Hz")
        self.sp_fps.setToolTip("Fréquence de la boucle : celle des démonstrations du dataset d'entraînement, en général")
        form.addRow("Fréquence", self.sp_fps)
        self.sp_duree = QDoubleSpinBox()
        self.sp_duree.setRange(0, 600)
        self.sp_duree.setDecimals(1)
        self.sp_duree.setSuffix(" s")
        self.sp_duree.setSpecialValueText("jusqu'à Arrêter")
        self.sp_duree.setValue(5.0)
        self.sp_duree.setToolTip("Durée d'un essai (0 : le modèle pilote jusqu'à « Arrêter »)")
        form.addRow("Durée", self.sp_duree)
        layout.addLayout(form)
        self.cb_replacer = QCheckBox("Replacer la scène avant chaque essai")
        self.cb_replacer.setChecked(True)
        self.cb_replacer.setToolTip("En simulé : robot en posture de départ, objets de la scène replacés "
                                    "(au hasard s'ils ont des règles de placement)")
        layout.addWidget(self.cb_replacer)

        boutons = QHBoxLayout()
        self.btn_demarrer = QPushButton(self._icon("play"), "Démarrer")
        self.btn_demarrer.setIconSize(QSize(22, 22))
        self.btn_demarrer.clicked.connect(self._on_demarrer)
        boutons.addWidget(self.btn_demarrer)
        self.btn_arreter = QPushButton(self._icon("stop"), "Arrêter")
        self.btn_arreter.setIconSize(QSize(22, 22))
        self.btn_arreter.clicked.connect(self._view_model.arreter)
        boutons.addWidget(self.btn_arreter)
        layout.addLayout(boutons)
        self.lbl_etat = QLabel()
        self.lbl_etat.setWordWrap(True)
        layout.addWidget(self.lbl_etat)
        return panel

    def lbl_etat_set(self, texte: str):
        self.lbl_etat.setText(texte)

    # ------------------------------------------------------------------ robot et simulation
    def set_simulation(self, simulation: bool):
        self._simulation = simulation
        self.cb_replacer.setVisible(simulation)
        self._update_3d()

    def _update_3d(self):
        world = self._view_model.sim_world() if self._simulation else None
        self._viewport.setVisible(world is not None)
        if world is None:
            self._timer_3d.stop()
            return
        self._viewport.set_sim_world(world)
        self._timer_3d.start()

    def close_3d(self):
        self._timer_3d.stop()
        self._viewport.show_message("")

    def _on_robot_changed(self):
        self._update_3d()
        self._update_buttons()

    # ------------------------------------------------------------------ modèles
    def _remplir_modeles(self):
        courant = self._modele_choisi()
        self.list_modeles.clear()
        for info in self._view_model.modeles():
            texte = f"{info['name']} · {info.get('kind', '?')}\n{info['date']}"
            item = QListWidgetItem(self._icon("robot"), texte)
            item.setData(Qt.ItemDataRole.UserRole, info)
            item.setToolTip(info["folder"])
            self.list_modeles.addItem(item)
            if info["folder"] == courant:
                self.list_modeles.setCurrentItem(item)
        if self.list_modeles.currentItem() is None and self.list_modeles.count():
            self.list_modeles.setCurrentRow(0)
        if not self.list_modeles.count():
            self.lbl_modele.setText("Aucun modèle entraîné pour ce robot.")
        self._update_buttons()

    def _info(self) -> dict | None:
        item = self.list_modeles.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _modele_choisi(self) -> str | None:
        info = self._info() if hasattr(self, "list_modeles") else None
        return info["folder"] if info else None

    def _on_modele_choisi(self):
        info = self._info()
        if info is None:
            self._update_buttons()
            return
        lignes = []
        if info.get("dataset"):
            lignes.append(f"dataset : {info['dataset'].rstrip('/').split('/')[-1]}")
        if info.get("inputs"):
            lignes.append(f"voit : {', '.join(info['inputs'])}")
        if info.get("actions"):
            lignes.append(f"commande : {', '.join(a.split('.')[0] for a in info['actions'])}")
        if info.get("error"):
            lignes.append(f"⚠ {info['error']}")
        self.lbl_modele.setText("\n".join(lignes))
        self.sp_fps.setValue(int(round(info.get("fps") or 20)))
        self._update_buttons()

    # ------------------------------------------------------------------ pilotage
    def _on_demarrer(self):
        info = self._info()
        if info is None:
            return
        self._installer_cameras(info.get("images", []))
        duree = self.sp_duree.value() or None
        self._view_model.demarrer(info["folder"], self.sp_fps.value(), duree,
                                  self._simulation and self.cb_replacer.isChecked())

    def _installer_cameras(self, noms: list[str]):
        for w in self._cameras.values():
            self._vues_layout.removeWidget(w)
            w.deleteLater()
        self._cameras = {}
        for nom in noms:
            w = VideoWidget(nom, width=320, height=240)
            w.init_plot()
            self._cameras[nom] = w
            self._vues_layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._vues_aide.setVisible(not self._cameras)

    def _on_observation(self, observation: dict):
        for nom, w in self._cameras.items():
            if observation.get(nom) is not None:
                w.update_plot(observation[nom])

    def _update_buttons(self):
        if not hasattr(self, "btn_demarrer"):
            return
        vm = self._view_model
        busy = vm.is_running()
        self.btn_demarrer.setEnabled(not busy and vm.has_robot() and self._info() is not None)
        self.btn_demarrer.setToolTip("Le modèle choisi pilote le robot" if vm.has_robot() else
                                     "Pas de robot : connectez le robot réel, ou utilisez le robot simulé")
        self.btn_arreter.setEnabled(busy)
        self.list_modeles.setEnabled(not busy)
