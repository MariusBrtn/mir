
from PySide6.QtWidgets import QScrollArea
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QCheckBox, QToolBar, QLineEdit, QGridLayout, QToolButton, QFrame,
    QComboBox, QStackedWidget
)
from PySide6.QtCore import Qt, QSize
from mir_robot_editor.robot_monitor_view_model import ( 
                                                      RobotMonitorViewModel, 
                                                      RobotMonitorVMAction)
from mir_robot_editor.observations_widget import ObservationsWidget
from mir_utils.ui.view_base import ViewBase
from mir_robot_editor.actions_widget import MotorActionWidget
from mir_utils.ui.widgets import ToolButton, StateSavedView
from mir_devices.mir_device import ( ObservableProperty, 
                                  ObservationValue, 
                                  DeviceAction, 
                                  ObservablePropertyFloat, 
                                  ObservablePropertyBitmap, 
                                  ObservablePropertyPolar)
from mir_utils.ui import theme

class RobotMonitorView(QWidget, ViewBase[RobotMonitorViewModel, RobotMonitorVMAction]):

    def __init__(self, parent, viewmodel: RobotMonitorViewModel, state_saved_view: StateSavedView):
        super().__init__(parent, view_model = viewmodel) # type: ignore
        self._state_saved_view = state_saved_view
        self._view_model = viewmodel
        self._view_model.observations_list_changed.connect(self.on_observations_list_changed)
        self._view_model.actions_list_changed.connect(self.on_actions_list_changed)
        self._view_model.observation_ready.connect(self.on_observation_ready)
        self._view_model.observations_accepted.connect(self.on_features_accepted)
        self._view_model.fps_changed.connect(self.on_fps_changed)
        self._view_model.commandes_list_changed.connect(self.on_commandes_list_changed)
        self._view_model.commande_running_changed.connect(self.on_commande_running_changed)
        toolbar = QToolBar(iconSize=QSize(32, 32))
        
        self._action_apply =   self._make_action(RobotMonitorVMAction.APPLY, self.on_apply_clicked, "apply", toolbar=toolbar)
        self._action_start = self._make_action(RobotMonitorVMAction.START, self.on_start_clicked, "play", toolbar=toolbar)
        self._action_stop = self._make_action(RobotMonitorVMAction.STOP,  self.on_stop_clicked, "stop", toolbar=toolbar)
        self._action_action =   self._make_action(RobotMonitorVMAction.ACTION, self.on_apply_clicked, "")
        self._action_action.enabledChanged.connect(self.on_action_enabled_changed)
        self._action_apply.enabledChanged.connect(self.on_apply_enabled_changed)
        
        self._view_model
        # --- Barre de gauche, liste des observations ---
        left_bar = QVBoxLayout()
        left_bar_title = QLabel("Observations")
        left_bar_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        left_bar_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        left_bar.addWidget(left_bar_title)
        left_bar_toolbar = QHBoxLayout()
        self.btn_select_all = ToolButton("select_all", lambda: self.on_select_all_features_clicked(True), False, "Sélectionner tout")
        left_bar_toolbar.addWidget(self.btn_select_all)
        self.btn_deselect_all = ToolButton("unselect_all", lambda: self.on_select_all_features_clicked(False), False, "Désélectionner tout")
        left_bar_toolbar.addWidget(self.btn_deselect_all)
        left_bar_toolbar.addStretch()
        _checked_btn_style = f"QToolButton:checked {{ background-color: {theme.SAND}; border-radius: 6px; }}"
        self.btn_record = QToolButton()
        self.btn_record.setIcon(self._icon("record"))
        #self.btn_record.toggled.connect(self.on_record_toggled)
        self.btn_record.setCheckable(True)
        self.btn_record.setEnabled(False)
        self.btn_record.setStyleSheet(_checked_btn_style)
        left_bar_toolbar.addWidget(self.btn_record)
        left_bar.addLayout(left_bar_toolbar)

        self.options_layout = QVBoxLayout()
        self.options_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_content = QWidget()
        scroll_content.setLayout(self.options_layout)
        scroll_area = QScrollArea()
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumWidth(170)
        left_bar.addWidget(scroll_area, 1)

        fps_edit = QHBoxLayout()
        self.tb_fps = QLineEdit("50")
        self.tb_fps.setFixedWidth(40)
        self.tb_fps.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.tb_fps.setEnabled(False)
        self.btn_show_fps = QToolButton()
        self.btn_show_fps.setIcon(self._icon("stats"))
        self.btn_show_fps.toggled.connect(self.on_show_fps_toggled)
        self.btn_show_fps.setCheckable(True)
        self.btn_show_fps.setEnabled(False)
        self.btn_show_fps.setStyleSheet(_checked_btn_style)
        fps_edit.addWidget(QLabel("fps cible"))
        fps_edit.addWidget(self.tb_fps)
        fps_edit.addWidget(self.btn_show_fps)

        self._lbl_fps = QLabel("0")

        self.fps_frame = QFrame()
        fps_grid = QGridLayout(self.fps_frame)
        fps_grid.setContentsMargins(0, 0, 0, 0)
        fps_grid.addWidget(QLabel("fps"), 1, 0)
        fps_grid.addWidget(self._lbl_fps, 1, 1)
        self._lbl_fps_avg = QLabel("0")
        fps_grid.addWidget(QLabel("fps moy."), 2, 0)
        fps_grid.addWidget(self._lbl_fps_avg, 2, 1)
        self._lbl_period_avg = QLabel("0")
        fps_grid.addWidget(QLabel("p moy."), 3, 0)
        fps_grid.addWidget(self._lbl_period_avg, 3, 1)
        self._lbl_period_min = QLabel("0")
        fps_grid.addWidget(QLabel("p min."), 4, 0)
        fps_grid.addWidget(self._lbl_period_min, 4, 1)
        self._lbl_period_max = QLabel("0")
        fps_grid.addWidget(QLabel("p max."), 5, 0)
        fps_grid.addWidget(self._lbl_period_max, 5, 1)
        self._lbl_period_std = QLabel("0")
        fps_grid.addWidget(QLabel("p std."), 6, 0)
        fps_grid.addWidget(self._lbl_period_std, 6, 1)
        self.fps_frame.setVisible(False)

        left_bar.addWidget(toolbar)
        left_bar.addLayout(fps_edit)
        left_bar.addWidget(self.fps_frame)


        # --- au centre les graphiques des observations  ---
        self.observations_widgets = ObservationsWidget(self._state_saved_view)

        # --- Barre de droite, les actions ---
        right_bar = QVBoxLayout()
        right_bar_title = QLabel("Commande")
        right_bar_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_bar_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        right_bar.addWidget(right_bar_title)

        # choix de la commande : consigne manuelle ou une commande trouvée dans les dossiers de commandes
        choice_layout = QHBoxLayout()
        self.cb_commande = QComboBox()
        self.cb_commande.setMinimumWidth(170)
        self.cb_commande.currentIndexChanged.connect(self.on_commande_selected)
        choice_layout.addWidget(self.cb_commande, 1)
        self.btn_refresh_commandes = ToolButton("scan", self.on_refresh_commandes_clicked, True, "Relire les fichiers de commandes")
        choice_layout.addWidget(self.btn_refresh_commandes)
        right_bar.addLayout(choice_layout)

        self.commande_stack = QStackedWidget()
        # page 0 : consigne manuelle
        self.action_widget = MotorActionWidget(self)
        self.action_widget.motor_action_changed.connect(self.on_motor_action_changed)
        self.commande_stack.addWidget(self.action_widget)
        # page 1 : commande choisie dans la liste
        commande_page = QWidget()
        commande_layout = QVBoxLayout(commande_page)
        commande_layout.setContentsMargins(8, 8, 8, 8)
        self.lbl_commande_description = QLabel()
        self.lbl_commande_description.setWordWrap(True)
        self.lbl_commande_description.setMaximumWidth(220)
        commande_layout.addWidget(self.lbl_commande_description)
        commande_toolbar = QToolBar(iconSize=QSize(32, 32))
        # références conservées : sinon les QAction sont libérées et disparaissent de la barre
        self._action_commande_start = self._make_action(RobotMonitorVMAction.COMMANDE_START, lambda: self._view_model.start_commande(), "play", toolbar=commande_toolbar)
        self._action_commande_stop = self._make_action(RobotMonitorVMAction.COMMANDE_STOP, lambda: self._view_model.stop_commande(), "stop", toolbar=commande_toolbar)
        commande_layout.addWidget(commande_toolbar)
        self.lbl_commande_state = QLabel()
        commande_layout.addWidget(self.lbl_commande_state)
        commande_layout.addStretch()
        self.commande_stack.addWidget(commande_page)
        right_bar.addWidget(self.commande_stack)

        # l'arrêt d'urgence reste visible quelle que soit la commande
        self.btn_emergency_stop = QToolButton()
        self.btn_emergency_stop.setIcon(self._icon("emergency_stop"))
        self.btn_emergency_stop.setToolTip("Arrêt d'urgence")
        self.btn_emergency_stop.setIconSize(QSize(30, 30))
        self.btn_emergency_stop.setEnabled(False)
        self.btn_emergency_stop.clicked.connect(self.on_emergency_stop_clicked)
        right_bar.addWidget(self.btn_emergency_stop, alignment=Qt.AlignmentFlag.AlignCenter)
        right_bar.addStretch()
        self.on_commandes_list_changed([])

        # layout principal
        main_layout = QHBoxLayout(self)
        main_layout.addLayout(left_bar, 0)
        main_layout.addWidget(self.observations_widgets, 1)
        main_layout.addLayout(right_bar, 0)

    def restore_state(self):
        self.observations_widgets.restore_state()

    def save_state(self):
        self.observations_widgets.save_state()
        
    def select_all_observations_and_apply(self):
        """Coche toutes les observations et les applique : prêt à démarrer les mesures."""
        self.on_select_all_features_clicked(True)
        self.on_apply_clicked()

    def on_select_all_features_clicked(self, select: bool):
        #select all checkboxes in options_layout
        for i in range(self.options_layout.count()):
            item = self.options_layout.itemAt(i)
            widget = item.widget() # type: ignore
            if isinstance(widget, QCheckBox):
                widget.setChecked(select)
        
    def on_show_fps_toggled(self, checked: bool):
        self.fps_frame.setVisible(checked)

    def on_observations_list_changed(self, obs: list[str]):
        # 1. Vider uniquement la zone des cases à cocher
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            widget = item.widget() # type: ignore
            if widget is not None:
                widget.deleteLater()

        # 2. Recréer les cases à cocher
        for name in obs:
            self.options_layout.addWidget(QCheckBox(name))

    def on_actions_list_changed(self, motor_actions: dict[str, DeviceAction]):            
        self.action_widget.build_ui(motor_actions)

    def on_fps_changed(self, fps: float,stats:dict):
        self._lbl_fps.setText(f"{fps:.1f}")
        self._lbl_fps_avg.setText(f"{1.0/stats['mean']:.1f}")
        self._lbl_period_avg.setText(f"{stats['mean']*1000:.1f}")        
        self._lbl_period_min.setText(f"{stats['min']*1000:.1f}")
        self._lbl_period_max.setText(f"{stats['max']*1000:.1f}")
        self._lbl_period_std.setText(f"{stats['std']*1000:.2f}")

    def on_observation_ready(self, observations: dict[str, ObservationValue]):
        for key, data in observations.items():
            self.observations_widgets.get_plot(key).update_plot(data)

    def on_features_accepted(self, observable_properties :dict[str, ObservableProperty]):
        self._lbl_fps_avg.setText("")
        self.observations_widgets.clear()
        for name, prop in observable_properties.items():
            if isinstance(prop, ObservablePropertyFloat):
                self.observations_widgets.add_scope(name, prop.min_value, prop.max_value, prop.unit)
            elif isinstance(prop, ObservablePropertyBitmap):
                self.observations_widgets.add_video(name)                
            elif isinstance(prop, ObservablePropertyPolar):
                self.observations_widgets.add_polar(name, prop.max_range, False, False)                
            
    def on_apply_clicked(self):
        self.observations_widgets.restore_state()

        checked: list[str] = []

        for i in range(self.options_layout.count()):
            item = self.options_layout.itemAt(i)
            widget = item.widget() # type: ignore
            if isinstance(widget, QCheckBox) and widget.isChecked():
                checked.append(widget.text())

        # transmettre au view_model
        self._view_model.apply_observations(checked)

    def on_start_clicked(self):
        self._view_model.start(self.tb_fps.text(), self.btn_show_fps.isChecked(), self.btn_record.isChecked())
        self._last_timestamp = 0

    def on_stop_clicked(self):
        self._view_model.stop()
        self.save_state()
    
    def on_emergency_stop_clicked(self):
        self._view_model.on_emergency_stop_clicked()

    def on_motor_action_changed(self, motor_action: DeviceAction):
        self._view_model.on_motor_action_changed(motor_action)

    def on_action_enabled_changed(self, is_enabled:bool): 
        self.action_widget.set_enabled(is_enabled)
        self.btn_emergency_stop.setEnabled(is_enabled)

    def on_commandes_list_changed(self, commandes: list[tuple[str, str]]):
        previous = self.cb_commande.currentData()
        self.cb_commande.blockSignals(True)
        self.cb_commande.clear()
        self.cb_commande.addItem("Consigne manuelle", None)
        for nom, description in commandes:
            self.cb_commande.addItem(nom, nom)
            self.cb_commande.setItemData(self.cb_commande.count() - 1, description, Qt.ItemDataRole.ToolTipRole)
        index = self.cb_commande.findData(previous)
        self.cb_commande.setCurrentIndex(max(index, 0))
        self.cb_commande.blockSignals(False)
        self.on_commande_selected(self.cb_commande.currentIndex())

    def on_commande_selected(self, index: int):
        nom = self.cb_commande.itemData(index)
        self._view_model.select_commande(nom)
        self.commande_stack.setCurrentIndex(0 if nom is None else 1)
        self.lbl_commande_description.setText(self.cb_commande.itemData(index, Qt.ItemDataRole.ToolTipRole) or "")

    def on_refresh_commandes_clicked(self):
        self._view_model.refresh_commandes()

    def on_commande_running_changed(self, running: bool):
        self.cb_commande.setEnabled(not running)
        self.btn_refresh_commandes.setEnabled(not running)
        self.lbl_commande_state.setText("En cours…" if running else "")

    def on_apply_enabled_changed(self, is_enabled:bool):
        self.tb_fps.setEnabled(is_enabled)
        self.btn_show_fps.setEnabled(is_enabled)
        self.btn_select_all.setEnabled(is_enabled)
        self.btn_deselect_all.setEnabled(is_enabled)
        self.btn_record.setEnabled(is_enabled)
        