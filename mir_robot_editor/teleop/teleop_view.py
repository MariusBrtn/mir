"""
Étape Piloter → Téléopération : une commande Python (clavier, joystick, second robot... ou écrite par l'élève)
pilote le robot. En simulation, on voit le robot simulé en 3D ; avec le robot réel, on suit les grandeurs choisies.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable
from PySide6.QtCore import QEvent, QObject, Qt, QSize, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)
from mir_devices.mir_device import (ObservableProperty, ObservablePropertyBitmap, ObservablePropertyFloat,
                                    ObservablePropertyPolar, ObservationValue)
from mir_robot.teleop.loading import PROVIDED_DIR
from mir_robot_editor.observations_widget import ObservationsWidget, PolarWidget, VideoWidget
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_robot_editor.robot_monitor_view_model import RobotMonitorViewModel, RobotMonitorVMAction
from mir_robot_editor.teleop.commande_editor import (MODELE_BRAS_LEADER, MODELE_CLAVIER, CommandeEditorDialog, nom_de_classe,
                                                     nom_de_fichier)
from mir_utils.keyboard_listener import Key, key_from_char
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui.widgets import StateSavedView, ToolButton
from mir_utils.ui import theme

PAR_DEFAUT = "Clavier"


def est_capteur(prop: ObservableProperty | None) -> bool:
    """Caméra ou lidar : affichés d'office pendant la téléopération (en simulation comme en réel)."""
    return isinstance(prop, (ObservablePropertyBitmap, ObservablePropertyPolar))
QT_KEYS = {
    Qt.Key.Key_Left: Key.Left, Qt.Key.Key_Right: Key.Right, Qt.Key.Key_Up: Key.Up, Qt.Key.Key_Down: Key.Down,
    Qt.Key.Key_Space: Key.Space, Qt.Key.Key_Return: Key.Enter, Qt.Key.Key_Enter: Key.Enter, Qt.Key.Key_Tab: Key.Tab,
    Qt.Key.Key_Backspace: Key.Backspace, Qt.Key.Key_Delete: Key.Delete, Qt.Key.Key_Escape: Key.Esc,
}


def key_from_qt(event) -> Key | None:
    key = QT_KEYS.get(Qt.Key(event.key()))
    return key if key is not None else key_from_char(event.text())


class TeleopView(QWidget, ViewBase[RobotMonitorViewModel, RobotMonitorVMAction]):
    def __init__(self, parent, view_model: RobotMonitorViewModel, state_saved_view: StateSavedView,
                 sim_world: Callable[[], Any]):
        super().__init__(parent, view_model=view_model)  # type: ignore
        vm = self._view_model
        self._sim_world = sim_world
        self._simulation = False
        self._param_widgets: dict[str, QWidget] = {}
        self._observation_boxes: dict[str, QCheckBox] = {}
        self._commande_affichee: str | None = None
        self._actions: list[str] = []
        vm.observations_list_changed.connect(self._on_observations_list_changed)
        vm.actions_list_changed.connect(self._on_actions_list_changed)
        vm.observations_accepted.connect(self._on_observations_accepted)
        vm.observation_ready.connect(self._on_observation_ready)
        vm.commandes_list_changed.connect(self._on_commandes_list_changed)
        vm.commande_running_changed.connect(self._on_commande_running_changed)
        vm.busy_state_changed.connect(self._on_busy_changed)

        root = QHBoxLayout(self)
        root.addWidget(self._make_left(), 0)
        self._center = QStackedWidget()
        self._center.addWidget(self._make_measures(state_saved_view))   # robot réel : grandeurs choisies
        self._center.addWidget(self._make_simulation())                  # robot simulé : vue 3D et capteurs
        root.addWidget(self._center, 1)
        self._timer_3d = QTimer(self)
        self._timer_3d.setInterval(33)
        self._timer_3d.timeout.connect(self._viewport.update)
        self._on_commandes_list_changed([])
        self._on_busy_changed(False)
        # touches de la fenêtre -> robot.clavier des commandes (pendant qu'une commande tourne)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if not self._view_model.is_commande_running() or not self.window().isActiveWindow():
            return False
        key = key_from_qt(event)
        if key is None:
            return False
        if event.type() == QEvent.Type.KeyPress:
            self._view_model.keyboard.press(key)        # répétition automatique : la touche est renvoyée
        elif not event.isAutoRepeat():
            self._view_model.keyboard.release(key)
        return True                                      # la touche pilote le robot, pas l'interface

    # ------------------------------------------------------------------ construction
    def _make_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        self.commande_box = QGroupBox("Téléopération")
        form = QVBoxLayout(self.commande_box)
        row = QHBoxLayout()
        self.cb_commande = QComboBox()
        self.cb_commande.currentIndexChanged.connect(self._on_commande_selected)
        row.addWidget(self.cb_commande, 1)
        row.addWidget(ToolButton("scan", self._view_model.refresh_commandes, True, "Relire les fichiers de commandes"))
        form.addLayout(row)
        self.lbl_description = QLabel()
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet("color: palette(placeholder-text);")
        form.addWidget(self.lbl_description)
        self.params_form = QFormLayout()
        form.addLayout(self.params_form)
        code_row = QHBoxLayout()
        self.btn_nouvelle = QPushButton(self._icon("new"), "Nouvelle…")
        self.btn_nouvelle.setToolTip("Écrire une nouvelle téléopération en Python, à partir d'un modèle")
        self.btn_nouvelle.clicked.connect(self._on_nouvelle)
        code_row.addWidget(self.btn_nouvelle)
        self.btn_code = QPushButton(self._icon("edit"), "Voir le code…")
        self.btn_code.setToolTip("Voir (et modifier, pour celles du robot) le code Python de la téléopération")
        self.btn_code.clicked.connect(self._on_voir_code)
        code_row.addWidget(self.btn_code)
        form.addLayout(code_row)
        # bras : son bras leader se construit ici ; la téléopération « Bras leader » apparaît dès qu'il est construit
        self.btn_leader = QPushButton(self._icon("construire"), "Créer le bras leader…")
        self.btn_leader.setVisible(False)
        form.addWidget(self.btn_leader)
        layout.addWidget(self.commande_box)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("Fréquence de la boucle"))
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(10, 200)
        self.sp_fps.setValue(30)
        self.sp_fps.setSuffix(" Hz")
        fps_row.addWidget(self.sp_fps)
        layout.addLayout(fps_row)

        buttons = QHBoxLayout()
        self.btn_start = QPushButton(self._icon("play"), "Démarrer")
        self.btn_start.setIconSize(QSize(24, 24))
        self.btn_start.clicked.connect(self._on_start)
        buttons.addWidget(self.btn_start)
        self.btn_stop = QPushButton(self._icon("stop"), "Arrêter")
        self.btn_stop.setIconSize(QSize(24, 24))
        self.btn_stop.clicked.connect(self._on_stop)
        buttons.addWidget(self.btn_stop)
        layout.addLayout(buttons)
        self.btn_emergency = QToolButton()
        self.btn_emergency.setIcon(self._icon("emergency_stop"))
        self.btn_emergency.setIconSize(QSize(30, 30))
        self.btn_emergency.setToolTip("Arrêt d'urgence")
        self.btn_emergency.clicked.connect(self._view_model.on_emergency_stop_clicked)
        layout.addWidget(self.btn_emergency, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setFixedWidth(340)
        return scroll

    def _make_measures(self, state_saved_view: StateSavedView) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        title = QLabel("Grandeurs suivies")
        title.setStyleSheet("font-weight: bold;")
        left.addWidget(title)
        self.observations_layout = QVBoxLayout()
        self.observations_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        content = QWidget()
        content.setLayout(self.observations_layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setFixedWidth(210)
        left.addWidget(scroll, 1)
        layout.addLayout(left)
        self.observations_widget = ObservationsWidget(state_saved_view)
        layout.addWidget(self.observations_widget, 1)
        return page

    def _make_simulation(self) -> QWidget:
        """Robot simulé : la vue 3D, et à côté ce que voient ses capteurs (caméra, lidar)."""
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viewport = MujocoWidget()
        splitter.addWidget(self._viewport)
        panel = QWidget()
        self._sensors_layout = QVBoxLayout(panel)
        self._sensors_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._sensors_hint = QLabel("La vue des capteurs (caméra, lidar) apparaît au démarrage de la téléopération.")
        self._sensors_hint.setWordWrap(True)
        self._sensors_hint.setStyleSheet("color: palette(placeholder-text);")
        self._sensors_layout.addWidget(self._sensors_hint)
        self._sensors_scroll = QScrollArea()
        self._sensors_scroll.setWidgetResizable(True)
        self._sensors_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._sensors_scroll.setWidget(panel)
        self._sensors_scroll.setMinimumWidth(350)
        splitter.addWidget(self._sensors_scroll)
        splitter.setStretchFactor(0, 1)
        self._sensor_plots: dict[str, Any] = {}
        return splitter

    def _capteurs(self) -> list[str]:
        observables = self._view_model.get_observables()
        return [nom for nom in self._observation_boxes if est_capteur(observables.get(nom))]

    def _afficher_capteurs_simules(self, observables: dict[str, ObservableProperty]):
        for widget in self._sensor_plots.values():
            self._sensors_layout.removeWidget(widget)
            widget.deleteLater()
        self._sensor_plots = {}
        for name, prop in observables.items():
            if isinstance(prop, ObservablePropertyBitmap):
                widget = VideoWidget(name, width=320, height=240)
                widget.init_plot()
            elif isinstance(prop, ObservablePropertyPolar):
                widget = PolarWidget(name, prop.max_range, size=320)
            else:
                continue
            self._sensor_plots[name] = widget
            self._sensors_layout.addWidget(widget, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._sensors_hint.setVisible(not self._sensor_plots)
        self._sensors_scroll.setVisible(bool(self._sensor_plots) or bool(self._capteurs()))

    def set_leader_action(self, action):
        """Action « Créer le bras leader » : le bouton la déclenche et suit son état."""
        self._leader_action = action
        self.btn_leader.setToolTip(action.toolTip())
        self.btn_leader.clicked.connect(action.trigger)
        action.changed.connect(lambda: self.btn_leader.setEnabled(action.isEnabled()))
        self.btn_leader.setEnabled(action.isEnabled())

    def set_leader_state(self, arm: bool, built: bool):
        """Le bouton n'apparaît que pour un bras."""
        self.btn_leader.setVisible(arm)
        self.btn_leader.setText("Reconstruire le bras leader…" if built else "Créer le bras leader…")

    # ------------------------------------------------------------------ mode et robot
    def set_simulation(self, simulation: bool):
        self._simulation = simulation
        self._center.setCurrentIndex(1 if simulation else 0)
        self._update_3d()

    def _update_3d(self):
        world = self._sim_world() if self._simulation else None
        if world is None:
            self._timer_3d.stop()
            self._viewport.show_message("Le robot simulé apparaît ici dès qu'un robot avec une structure est ouvert."
                                        if self._simulation else "")
            return
        self._viewport.set_model(world.model, world.data, keep_camera=True, lock=world.lock)
        self._timer_3d.start()

    def close_3d(self):
        self._timer_3d.stop()
        self._viewport.show_message("")

    def restore_state(self):
        self.observations_widget.restore_state()

    def save_state(self):
        self.observations_widget.save_state()

    def _on_actions_list_changed(self, actions: dict):
        self._actions = list(actions)
        self._on_commande_selected()        # les listes d'articulations des paramètres dépendent du robot

    def _on_observations_list_changed(self, names: list[str]):
        self._update_3d()                    # robot connecté ou reconstruit
        while self.observations_layout.count():
            item = self.observations_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._observation_boxes = {}
        observables = self._view_model.get_observables()
        for name in names:
            box = QCheckBox(name)
            # positions (dont les téléopérations ont besoin) et capteurs (caméra, lidar) suivis par défaut
            box.setChecked(name.endswith(".position") or est_capteur(observables.get(name)))
            self._observation_boxes[name] = box
            self.observations_layout.addWidget(box)
        self._afficher_capteurs_simules({})
        self._on_busy_changed(self._view_model.is_running())

    def _on_observations_accepted(self, observables: dict[str, ObservableProperty]):
        self.observations_widget.clear()
        if self._simulation:
            self._afficher_capteurs_simules(observables)
            return
        for name, prop in observables.items():
            if isinstance(prop, ObservablePropertyFloat):
                self.observations_widget.add_scope(name, prop.min_value, prop.max_value, prop.unit)
            elif isinstance(prop, ObservablePropertyBitmap):
                self.observations_widget.add_video(name)
            elif isinstance(prop, ObservablePropertyPolar):
                self.observations_widget.add_polar(name, prop.max_range, False, False)

    def _on_observation_ready(self, observations: dict[str, ObservationValue]):
        if self._simulation:
            for key, data in observations.items():
                if key in self._sensor_plots and data is not None:
                    self._sensor_plots[key].update_plot(data)
            return
        for key, data in observations.items():
            self.observations_widget.get_plot(key).update_plot(data)

    # ------------------------------------------------------------------ commandes
    def _on_commandes_list_changed(self, commandes: list):
        current = self.cb_commande.currentText()
        self.cb_commande.blockSignals(True)
        self.cb_commande.clear()
        for nom, _description in commandes:
            self.cb_commande.addItem(nom)
        index = self.cb_commande.findText(current)
        if index < 0:
            index = self.cb_commande.findText(PAR_DEFAUT)
        self.cb_commande.setCurrentIndex(max(index, 0))
        self.cb_commande.blockSignals(False)
        self._on_commande_selected()

    def _classe(self):
        return self._view_model.get_commandes().commandes.get(self.cb_commande.currentText())

    def _on_commande_selected(self, *_):
        nom = self.cb_commande.currentText()
        classe = self._classe()
        aucune = classe is None
        self._view_model.select_commande(None if aucune else nom)
        self.btn_code.setEnabled(not aucune)
        self.lbl_description.setText("Aucune téléopération trouvée." if aucune else classe.description)
        previous = self._param_values() if nom == self._commande_affichee else {}
        if nom != self._commande_affichee and getattr(classe, "frequence", None):
            self.sp_fps.setValue(int(classe.frequence))     # fréquence proposée par le fichier
        self._commande_affichee = nom
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self._param_widgets = {}
        if aucune:
            return
        actions = self._actions
        for pnom, parametre in classe.parametres.items():
            valeur = previous.get(pnom, parametre.defaut)
            if isinstance(parametre.defaut, str):
                # texte : le plus souvent le nom d'une action du robot
                widget = QComboBox()
                widget.setEditable(True)
                widget.addItems(actions)
                widget.setCurrentText(str(valeur))
            elif isinstance(parametre.defaut, bool):
                widget = QCheckBox()
                widget.setChecked(bool(valeur))
            elif isinstance(parametre.defaut, int):
                widget = QSpinBox()
                widget.setRange(-100000, 100000)
                widget.setValue(int(valeur))
                widget.setSuffix(f" {parametre.unite}" if parametre.unite else "")
            else:
                widget = QDoubleSpinBox()
                widget.setDecimals(2)
                widget.setRange(-100000.0, 100000.0)
                widget.setValue(float(valeur))
                widget.setSuffix(f" {parametre.unite}" if parametre.unite else "")
            self._param_widgets[pnom] = widget
            self.params_form.addRow(parametre.libelle or pnom, widget)

    def _param_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for nom, widget in self._param_widgets.items():
            if isinstance(widget, QComboBox):
                values[nom] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                values[nom] = widget.isChecked()
            else:
                values[nom] = widget.value()    # type: ignore[attr-defined]
        return values

    # ------------------------------------------------------------------ code python
    def _on_nouvelle(self):
        dossier = self._view_model.get_teleop_dir()
        if dossier is None:
            self._view_model._dialogProvider.information("Nouvelle téléopération", "Enregistrez d'abord le robot : ses "
                                                         "téléopérations sont rangées dans son dossier.")
            return
        nom, ok = QInputDialog.getText(self, "Nouvelle téléopération", "Nom de la téléopération (ex. « Ma téléop ») :")
        if not ok or not nom.strip():
            return
        nom = nom.strip()
        choix = ["Clavier", "Bras leader"]
        peripherique, ok = QInputDialog.getItem(self, "Nouvelle téléopération", "Périphérique :", choix, 0, False)
        if not ok:
            return
        fichier = dossier / nom_de_fichier(nom)
        if fichier.exists():
            self._view_model._dialogProvider.information("Nouvelle téléopération", f"Le fichier {fichier.name} existe déjà : "
                                                         "choisissez-la dans la liste et cliquez sur « Voir le code ».")
            return
        modele = MODELE_CLAVIER if peripherique == "Clavier" else MODELE_BRAS_LEADER
        contenu = modele.format(nom=nom.replace('"', "'"), classe=nom_de_classe(nom))
        dialog = CommandeEditorDialog(self, fichier, contenu)
        dialog.saved.connect(lambda _: self._reload(select=nom))
        dialog.enregistrer()        # le fichier existe tout de suite et la commande apparaît dans la liste
        dialog.exec()

    def _on_voir_code(self):
        nom = self.cb_commande.currentText()
        fichier = self._view_model.get_commandes().fichiers.get(nom)
        if fichier is None:
            return
        modifiable = Path(fichier).parent != PROVIDED_DIR
        dialog = CommandeEditorDialog(self, Path(fichier), modifiable=modifiable)
        dialog.saved.connect(lambda _: self._reload(select=nom))
        dialog.exec()

    def _reload(self, select: str | None = None):
        self._view_model.refresh_commandes()
        if select is not None and self.cb_commande.findText(select) >= 0:
            self.cb_commande.setCurrentIndex(self.cb_commande.findText(select))

    # ------------------------------------------------------------------ démarrer / arrêter
    def _on_start(self):
        vm = self._view_model
        if self._simulation:
            # positions (dont les téléopérations ont besoin) et capteurs, affichés à côté de la vue 3D
            observations = [n for n in self._observation_boxes if n.endswith(".position")] + self._capteurs()
        else:
            observations = [n for n, box in self._observation_boxes.items() if box.isChecked()]
        vm.apply_observations(observations)
        vm.start(str(self.sp_fps.value()), False, False)
        if self._classe() is not None and vm.is_running():
            vm.start_commande(self._param_values())

    def _on_stop(self):
        self._view_model.stop_commande()
        self._view_model.stop()

    def _on_commande_running_changed(self, running: bool):
        # la commande s'est terminée d'elle-même (ex. Échap) : la boucle s'arrête aussi
        if not running and self._view_model.is_running() and self._classe() is not None:
            self._view_model.stop()

    def _on_busy_changed(self, busy: bool):
        robot_ready = bool(self._observation_boxes) and self._classe() is not None
        self.btn_start.setEnabled(robot_ready and not busy)
        self.btn_stop.setEnabled(busy)
        self.btn_emergency.setEnabled(busy)
        for w in (self.cb_commande, self.btn_nouvelle, self.btn_code, self.sp_fps):
            w.setEnabled(not busy)
        for w in self._param_widgets.values():
            w.setEnabled(not busy)
        if not busy:
            self.btn_code.setEnabled(self._classe() is not None)
            self.btn_start.setEnabled(robot_ready)
