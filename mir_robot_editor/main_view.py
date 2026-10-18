import time
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QInputDialog, QMenu, QPushButton, QScrollArea, QStackedWidget, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)
from mir_utils.ui.widgets import MainWindowBase
from mir_robot_editor.motor_configuration.motor_configuration_view import MotorConfigurationView
from mir_robot_editor.edit_configuration_view import EditConfigurationView
from mir_robot_editor.motor_configuration.servo_id_view import ServoIdView
from mir_robot_editor.motor_configuration.motor_configuration_view_model import MotorConfigurationViewModel
from mir_robot_editor.main_viewmodel import MainViewModel, MainVMAction, MainViewModelState
from mir_robot_editor.teleop.teleop_view import TeleopView
from mir_robot_editor.essais.essais_view import EssaisView
from mir_robot_editor.scripts.scripts_view import ScriptsView
from mir_robot_editor.collecte.collecte_view import CollecteView
from mir_robot_editor.assemblage.assemblage_view import AssemblageView
from mir_robot_editor.robot_model.structure_editor_view import StructureEditorView
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui import theme

# couleurs du mode : on ne doit jamais confondre robot réel et robot simulé
COLOR_REAL = theme.REAL
COLOR_SIM = theme.SIM
COLOR_IDLE = theme.IDLE
COLOR_RUNNING = theme.RUNNING

# étapes du parcours (colonne de gauche)
STEP_ROBOT, STEP_PILOT, STEP_COLLECT = 0, 1, 2
TAB_ESSAIS, TAB_TELEOP, TAB_SCRIPTS = 0, 1, 2
STEPS = [("Configurer le robot", True), ("Piloter", True), ("Collecter des données", True), ("Apprendre", False), ("Évaluer", False)]


class ActionCard(QFrame):
    """Une action d'une page d'étape : toute la carte est le bouton (icône, titre, explication). Suit l'état de l'action."""

    def __init__(self, action: QAction, description: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ActionCard")
        self._action = action
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        self._icon = QLabel()
        self._icon.setObjectName("CardIcon")
        self._icon.setFixedSize(44, 44)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self._title = QLabel()
        self._title.setObjectName("CardTitle")
        texts.addWidget(self._title)
        self._description = QLabel(description)
        self._description.setObjectName("CardDescription")
        self._description.setWordWrap(True)
        texts.addWidget(self._description)
        layout.addLayout(texts, 1)
        self._status = QLabel()
        self._status.setObjectName("Muted")
        layout.addWidget(self._status)
        chevron = QLabel("›")
        chevron.setObjectName("CardChevron")
        layout.addWidget(chevron)
        action.changed.connect(self._sync)
        self._sync()

    def _sync(self):
        self._title.setText(self._action.text().replace("&", "").rstrip(".… "))
        self.setToolTip(self._action.toolTip())
        self.setEnabled(self._action.isEnabled())
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        self._icon.setPixmap(self._action.icon().pixmap(QSize(28, 28), mode))
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._action.trigger()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._action.trigger()
        else:
            super().keyPressEvent(event)

    def set_description(self, text: str):
        self._description.setText(text)

    def set_status(self, text: str):
        self._status.setText(text)
        done = text.startswith("✓")
        self._status.setStyleSheet(f"color: {theme.OK}; font-weight: bold;" if done else "")


class MainView(MainWindowBase, ViewBase[MainViewModel, MainVMAction]):
    def __init__(self, view_model: MainViewModel):
        super().__init__(parent=None, default_width=1100, default_height=700, view_model=view_model)
        self._view_model.state_changed.connect(self._on_state_changed)
        self._view_model.title_changed.connect(self._on_title_changed)
        self._view_model.simulation_changed.connect(self._on_simulation_changed)
        self.setWindowTitle("MIR")
        self._new_action = self._make_action(MainVMAction.NEW, self.on_action_new, "new", "Ctrl+N")
        self._save_action = self._make_action(MainVMAction.SAVE, self._view_model.save, "save", "Ctrl+S")
        self._save_as_action = self._make_action(MainVMAction.SAVE_AS, self._view_model.save_as, "save_as", "Ctrl+Shift+S")
        self._open_action = self._make_action(MainVMAction.OPEN, self._view_model.load_configuration, "folder-open", "Ctrl+O")
        self._connect_action = self._make_action(MainVMAction.CONNECT, self._view_model.connect_robot, "cable")
        self._disconnect_action = self._make_action(MainVMAction.DISCONNECT, self._view_model.disconnect_robot, "unplug")
        self._edit_configuration_action = self._make_action(MainVMAction.EDIT_CONFIGURATION, self.on_action_edit_configuration, "edit")
        self._motor_cfg_action = self._make_action(MainVMAction.MOTOR_CFG, self.on_action_motor_cfg, "reglages")
        self._assemble_action = self._make_action(MainVMAction.ASSEMBLE, self.on_action_assemble, "construire")
        self._build_leader_action = self._make_action(MainVMAction.BUILD_LEADER, self.on_action_build_leader, "construire")
        self._recalibrate_action = self._make_action(MainVMAction.RECALIBRATE, self.on_action_recalibrate, "calibration")
        self._structure_action = self._make_action(MainVMAction.STRUCTURE, self.on_action_structure, "structure")
        self._close_action = self._make_action(MainVMAction.CLOSE, self.on_action_close, "close")
        self._advanced_action = self._make_action(MainVMAction.ADVANCED, self.on_action_advanced, "gear")
        self._servo_id_action = self._make_action(MainVMAction.SERVO_ID, self.on_action_servo_id, "servo_id")
        self._reset_sim_action = self._make_action(MainVMAction.RESET_SIMULATION, self._view_model.reset_simulation, "")
        self._quit_action = self._make_action(MainVMAction.QUIT, self.close, "", "Ctrl+Q")
        self._simulation_vm_action = self._view_model.get_action(MainVMAction.SIMULATION)
        self._simulation_vm_action.action_state_changed.connect(self._update_header)
        for vm_action in (MainVMAction.CONNECT, MainVMAction.DISCONNECT, MainVMAction.RESET_SIMULATION):
            self._view_model.get_action(vm_action).action_state_changed.connect(self._update_header)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        self._steps = self._make_steps()
        body.addWidget(self._steps)
        self._pages = QStackedWidget()
        self._pages.addWidget(self._make_robot_page())
        self._pages.addWidget(self._make_pilot_page())
        self.collecte_view = CollecteView(self, self._view_model.get_collecte_view_model())
        self._pages.addWidget(self.collecte_view)
        body.addWidget(self._pages, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self._status_bar = self.statusBar()
        self._status_state = QLabel()
        self._status_bar.addWidget(self._status_state)

        self._make_menus()
        self._steps.setCurrentRow(STEP_ROBOT)
        self._on_simulation_changed(self._view_model.is_simulation())
        self._view_model.update_state_notifications()

    # ------------------------------------------------------------------ construction
    def _make_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        # robot ouvert : simple indication (ouvrir, créer, enregistrer : étape Configurer et menu Robot)
        self._robot_icon = QLabel()      # vert quand un robot est ouvert, gris sinon
        layout.addWidget(self._robot_icon)
        self._robot_label = QLabel()
        self._robot_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self._robot_label)
        # un seul robot ouvert à la fois : on le ferme pour en créer ou en ouvrir un autre
        self._btn_close = QPushButton(self._icon("close"), "Fermer ce robot")
        self._btn_close.setFlat(True)
        self._btn_close.setToolTip(self._close_action.toolTip())
        self._btn_close.clicked.connect(self._close_action.trigger)
        layout.addWidget(self._btn_close)

        # mode : un seul sélecteur à deux positions
        mode_box = QWidget()
        self._mode_box = mode_box
        mode_layout = QHBoxLayout(mode_box)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(0)
        self._btn_real = QPushButton("Réel")
        self._btn_sim = QPushButton("Simulé")
        self._mode_group = QButtonGroup(self)
        for button, simulation in ((self._btn_real, False), (self._btn_sim, True)):
            button.setCheckable(True)
            button.setMinimumWidth(90)
            button.setToolTip("Choisir le robot réel ou le robot simulé (avant de connecter)")
            button.clicked.connect(lambda _=False, s=simulation: self._view_model.set_simulation(s))
            self._mode_group.addButton(button)
            mode_layout.addWidget(button)
        layout.addWidget(mode_box)

        # connexion : un seul bouton, dont le texte suit l'état
        self._btn_connect = QPushButton()
        self._btn_connect.setMinimumWidth(130)
        self._btn_connect.setIconSize(QSize(20, 20))
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self._btn_connect)
        # en simulé, rien à connecter : le robot simulé est toujours prêt, on peut seulement le remettre à zéro
        self._btn_reset_sim = QPushButton("Remettre à zéro")
        self._btn_reset_sim.setMinimumWidth(130)
        self._btn_reset_sim.setToolTip(self._reset_sim_action.toolTip())
        self._btn_reset_sim.clicked.connect(self._reset_sim_action.trigger)
        layout.addWidget(self._btn_reset_sim)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._status_label)
        layout.addStretch(1)
        return header

    def _icone_coloree(self, nom: str, couleur: str, taille: int) -> QPixmap:
        """L'icône, entièrement de la couleur donnée (les icônes sont d'une seule couleur)."""
        pixmap = self._icon(nom).pixmap(taille, taille)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(couleur))
        painter.end()
        return pixmap

    def _make_steps(self) -> QListWidget:
        steps = QListWidget()
        steps.setFixedWidth(240)
        steps.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        steps.setObjectName("Steps")
        for i, (name, available) in enumerate(STEPS):
            item = QListWidgetItem(f"{i + 1}   {name}" + ("" if available else "   (à venir)"))
            if not available:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            steps.addItem(item)
        steps.currentRowChanged.connect(self._on_step_changed)
        return steps

    def _make_robot_page(self) -> QWidget:
        # accueil de l'étape, et sa page « Paramètres avancés »
        self._robot_pages = QStackedWidget()
        self._robot_pages.addWidget(self._make_robot_home())
        self._robot_pages.addWidget(self._make_advanced_page())
        return self._robot_pages

    @staticmethod
    def _make_cards_page(page: QWidget) -> tuple[QVBoxLayout, QScrollArea]:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(page)
        return layout, scroll

    def _make_robot_home(self) -> QWidget:
        page = QWidget()
        layout, scroll = self._make_cards_page(page)
        self._cards: list[ActionCard] = []

        def section(title: str, subtitle: str):
            label = QLabel(title)
            label.setObjectName("SectionTitle")
            layout.addWidget(label)
            if subtitle:
                sub = QLabel(subtitle)
                sub.setWordWrap(True)
                sub.setObjectName("Muted")
                layout.addWidget(sub)

        def card(action: QAction, description: str) -> ActionCard:
            c = ActionCard(action, description)
            self._cards.append(c)
            layout.addWidget(c)
            return c

        section("1  Concevoir", "Choisir les modules du robot et leurs branchements. La structure décrit à la fois le "
                                "robot réel et sa simulation : le robot simulé est utilisable dès cette étape.")
        self._card_concevoir = card(self._structure_action, "Concevoir module par module la structure du robot.")
        card(self._open_action, "Reprendre un robot déjà conçu.")
        section("2  Construire", "Monter le robot réel en suivant sa structure. Chaque module est détecté dès qu'on "
                                 "le branche ; chaque servo reçoit son ID et ses réglages, puis on le calibre.")
        self._card_construire = card(self._assemble_action, "Construction guidée du robot réel.")
        section("Avancé", "")
        card(self._advanced_action, "Changer l'ID d'un servo, recalibrer un servo, régler les servos, "
                                    "éditer la configuration.")
        layout.addStretch(1)
        return scroll

    def _make_advanced_page(self) -> QWidget:
        page = QWidget()
        layout, scroll = self._make_cards_page(page)
        back = QPushButton("‹  Retour")
        back.setFlat(True)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self._robot_pages.setCurrentIndex(0))
        layout.addWidget(back, alignment=Qt.AlignmentFlag.AlignLeft)
        title = QLabel("Paramètres avancés")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        sub = QLabel("Outils techniques pour régler ou dépanner le robot à la main.")
        sub.setWordWrap(True)
        sub.setObjectName("Muted")
        layout.addWidget(sub)
        for action, description in (
                (self._servo_id_action, "Brancher un servo seul, lire son ID et lui en donner un nouveau. "
                                        "Possible à tout moment, même si le robot n'est pas construit."),
                (self._recalibrate_action, "Refaire le milieu et les butées d'un servo du robot construit."),
                (self._motor_cfg_action, "Mode, PID, vitesse et couple max des servos du robot construit et branché."),
                (self._edit_configuration_action, "Modifier directement le fichier de configuration du robot.")):
            c = ActionCard(action, description)
            self._cards.append(c)
            layout.addWidget(c)
            if action is self._motor_cfg_action:
                self._card_reglages = c
            elif action is self._recalibrate_action:
                self._card_recalibrer = c
        layout.addStretch(1)
        return scroll

    def _make_pilot_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._pilot_hint = QLabel()
        self._pilot_hint.setWordWrap(True)
        self._pilot_hint.setObjectName("Hint")
        layout.addWidget(self._pilot_hint)
        # trois façons de piloter, une même boucle de mesures (une seule activité à la fois)
        self._pilot_tabs = QTabWidget()
        self._pilot_tabs.setDocumentMode(True)
        self.essais_view = EssaisView(self, self._view_model.get_essais_view_model())
        self._pilot_tabs.addTab(self.essais_view, "Essais")
        self.teleop_view = TeleopView(self, self._view_model.get_robot_monitor_view_model(), self,
                                      self._view_model.get_sim_world)
        self.teleop_view.restore_state()
        self.teleop_view.set_leader_action(self._build_leader_action)
        self._pilot_tabs.addTab(self.teleop_view, "Téléopération")
        self.scripts_view = ScriptsView(self, self._view_model.get_scripts_view_model())
        self._pilot_tabs.addTab(self.scripts_view, "Scripts")
        self._pilot_tabs.currentChanged.connect(self._on_pilot_tab_changed)
        layout.addWidget(self._pilot_tabs, 1)
        return page

    def _make_menus(self):
        menu = self.menuBar()
        file_menu = menu.addMenu("Robot")
        for action in (self._new_action, self._open_action, self._save_action, self._save_as_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self._connect_action)
        file_menu.addAction(self._disconnect_action)
        file_menu.addSeparator()
        file_menu.addAction(self._close_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

    # ------------------------------------------------------------------ mise à jour
    def _update_header(self, *_):
        state = self._view_model.get_state()
        simulation = self._view_model.is_simulation()
        configuring = self._view_model.is_configuring()
        # sans robot ouvert, la structure crée un robot ; sinon, elle modifie celui qui est ouvert
        robot_ouvert = state != MainViewModelState.INIT
        self._robot_icon.setPixmap(self._icone_coloree("robot", theme.OK if robot_ouvert else theme.TEXT_DISABLED, 24))
        self._btn_close.setVisible(robot_ouvert)
        self._btn_close.setEnabled(self._close_action.isEnabled())
        # configurer le robot ne dépend pas du mode : le choix réel / simulé n'apparaît qu'à partir de Piloter
        self._mode_box.setVisible(not configuring)
        name = self._view_model.get_robot_name()
        if name:
            pending = f" <span style='color: {theme.TEXT_MUTED};'>(modifications non enregistrées)</span>" \
                if self._view_model.is_dirty() else ""
            self._robot_label.setText(f"Robot : <b>{name}</b>{pending}")
        else:
            self._robot_label.setText(f"<span style='color: {theme.TEXT_MUTED};'>Aucun robot ouvert</span>")

        mode_enabled = self._simulation_vm_action.enabled
        built = self._view_model.is_built()
        for button, is_sim in ((self._btn_real, False), (self._btn_sim, True)):
            checked = is_sim == simulation
            button.setChecked(checked)
            # le robot réel n'est utilisable qu'une fois construit (étape Construire)
            button.setEnabled(mode_enabled and (is_sim or built))
            color = COLOR_SIM if is_sim else COLOR_REAL
            radius = "border-top-right-radius: 8px; border-bottom-right-radius: 8px;" if is_sim else \
                     "border-top-left-radius: 8px; border-bottom-left-radius: 8px;"
            if checked:
                style = f"background: {color}; color: white; font-weight: bold; border: 1px solid {color};"
            else:
                style = f"background: {theme.SURFACE}; color: {theme.TEXT_MUTED}; border: 1px solid {theme.BORDER_STRONG};"
            button.setStyleSheet(f"QPushButton {{ {style} {radius} padding: 6px 14px; }}"
                                 "QPushButton:disabled { color: palette(placeholder-text); }")
        self._btn_real.setToolTip("Choisir le robot réel" if built else
                                  "Le robot n'est pas encore construit : construisez-le dans « Configurer le robot » "
                                  "(étape 2) pour l'utiliser en réel")

        connected = state in (MainViewModelState.CONNECTED, MainViewModelState.RUNNING)
        robot_kind = "robot simulé" if simulation else "robot réel"
        self._btn_connect.setVisible(not simulation and not configuring)
        self._btn_reset_sim.setVisible(simulation and not configuring)
        self._btn_reset_sim.setEnabled(self._reset_sim_action.isEnabled())
        if connected:
            self._btn_connect.setText("Déconnecter")
            self._btn_connect.setIcon(self._icon("unplug"))
            self._btn_connect.setEnabled(self._disconnect_action.isEnabled())
            self._btn_connect.setToolTip("Arrêter les mesures avant de déconnecter" if state == MainViewModelState.RUNNING
                                         else f"Déconnecter le {robot_kind}")
        else:
            self._btn_connect.setText("Connecter")
            self._btn_connect.setIcon(self._icon("cable"))
            self._btn_connect.setEnabled(self._connect_action.isEnabled())
            self._btn_connect.setToolTip(f"Se connecter au {robot_kind}")

        # l'état de la connexion n'a de sens qu'à l'étape Piloter (en configuration, il répéterait l'en-tête)
        self._status_label.setVisible(state != MainViewModelState.INIT and not configuring)
        if state == MainViewModelState.INIT or configuring:
            dot, text = COLOR_IDLE, ""
        elif state == MainViewModelState.LOADED:
            dot, text = COLOR_IDLE, ("Pas de structure : simulation impossible" if simulation else "Non connecté")
        elif state == MainViewModelState.CONNECTED:
            dot, text = (COLOR_SIM, "Simulation prête") if simulation else (theme.OK, "Connecté au robot réel")
        else:
            # en simulation, on ne parle pas de mesures : les mesures se font sur le robot réel
            dot, text = (COLOR_SIM, "Mouvement en cours (simulation)") if simulation else \
                        (COLOR_RUNNING, "Mesures en cours sur le robot réel")
        self._status_label.setText(f"<span style='color:{dot}; font-size:16px;'>●</span>&nbsp;{text}")
        self._update_pilot_hint()

    def _update_pilot_hint(self):
        state = self._view_model.get_state()
        if state == MainViewModelState.INIT:
            text = "Créez un robot (<b>Concevoir la structure</b>) ou ouvrez-en un dans l'étape <b>Configurer le robot</b>."
        elif state == MainViewModelState.LOADED and self._view_model.is_simulation():
            text = ("Le robot simulé est construit à partir de la structure du robot : "
                    "concevez-la dans l'étape <b>Configurer le robot → Concevoir la structure</b>.")
        elif state == MainViewModelState.LOADED:
            text = "Connectez le robot réel (bouton <b>Connecter</b> en haut) pour faire des mesures et le commander."
        elif self._pilot_tabs.currentIndex() == TAB_ESSAIS and self._view_model.is_simulation():
            text = ("<b>Essais en simulation</b> : envoyez un échelon, une rampe ou un sinus et regardez le robot simulé "
                    "bouger. Les <b>mesures</b> se font sur le <b>robot réel</b>.")
        elif self._pilot_tabs.currentIndex() == TAB_ESSAIS:
            text = ("<b>Essais</b> : choisissez l'actionneur et la sollicitation, réglez-les, puis <b>▶ Lancer l'essai</b>. "
                    "Les essais sont enregistrés et peuvent être superposés à droite.")
        elif self._pilot_tabs.currentIndex() == TAB_SCRIPTS:
            text = ("<b>Scripts</b> : écrivez vos propres programmes Python qui commandent le robot "
                    "(<code>robot.get_observation()</code>, <code>robot.send_action()</code>), puis <b>▶ Lancer</b>. "
                    + "Les figures (<code>plt.plot</code>…) s'affichent à droite. "
                    + ("Le robot simulé bouge en 3D au-dessus." if self._view_model.is_simulation() else
                       "Ils commandent le <b>robot réel</b> : gardez l'arrêt d'urgence à portée de main."))
        elif self._view_model.is_simulation():
            text = ("<b>Téléopération en simulation</b> : choisissez une téléopération (ou écrivez la vôtre en Python avec "
                    "<b>Nouvelle…</b>), puis <b>▶ Démarrer</b>. Le robot simulé bouge en 3D.")
        else:
            text = ("<b>Téléopération</b> : choisissez une téléopération (ou écrivez la vôtre en Python avec <b>Nouvelle…</b>) "
                    "et les grandeurs à suivre, puis <b>▶ Démarrer</b>.")
        self._pilot_hint.setText(text)

    def _on_pilot_tab_changed(self, index: int):
        if index != TAB_ESSAIS:
            self._view_model.restore_essai_settings()     # réglages d'essai temporaires
        self._update_pilot_hint()

    def _on_state_changed(self, state: MainViewModelState, description: str):
        if hasattr(self, "_card_concevoir"):
            self._update_summary()
        if hasattr(self, "teleop_view"):
            self.teleop_view.set_leader_state(self._view_model.is_arm(), self._view_model.has_leader_arm())
        previous = getattr(self, "_previous_state", None)
        self._previous_state = state
        self._status_state.setText(description)
        self._update_header()
        # sans robot ouvert, il n'y a rien à piloter ni à collecter : ces étapes sont grisées
        if hasattr(self, "_steps"):
            avec_robot = state != MainViewModelState.INIT
            for step in (STEP_PILOT, STEP_COLLECT):
                item = self._steps.item(step)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable if avec_robot else Qt.ItemFlag.NoItemFlags)
                item.setToolTip("" if avec_robot else "Ouvrez ou créez d'abord un robot (étape Configurer le robot)")
            if not avec_robot and self._steps.currentRow() in (STEP_PILOT, STEP_COLLECT):
                self._steps.setCurrentRow(STEP_ROBOT)
        if state == MainViewModelState.CONNECTED and previous == MainViewModelState.LOADED:
            if not self._view_model.is_simulation() and self._steps.currentRow() == STEP_ROBOT:
                # le robot réel vient d'être connecté par l'utilisateur : on passe à l'étape Piloter
                self._steps.setCurrentRow(STEP_PILOT)

    def _on_title_changed(self, title: str):
        self.setWindowTitle(title)
        self._update_header()

    def _on_simulation_changed(self, simulation: bool):
        self.essais_view.set_simulation(simulation)
        self.teleop_view.set_simulation(simulation)
        self.scripts_view.set_simulation(simulation)
        self.collecte_view.set_simulation(simulation)
        self._update_pilot_hint()
        self._update_header()

    def _on_step_changed(self, row: int):
        if not (0 <= row < self._pages.count()):
            return
        configuring = row == STEP_ROBOT
        if configuring and self._view_model.get_state() == MainViewModelState.CONNECTED \
                and not self._view_model.is_simulation() \
                and not self._view_model.confirm("Configurer le robot", "Le robot réel est connecté.\r\nLe déconnecter pour configurer le robot ?"):
            self._revert_step()
            return
        if not self._view_model.set_configuring(configuring):
            self._view_model.inform("Configurer le robot", "Arrêtez d'abord le mouvement ou les mesures en cours.")
            self._revert_step()
            return
        self._pages.setCurrentIndex(row)
        self._robot_pages.setCurrentIndex(0)
        self._update_header()

    def _revert_step(self):
        self._steps.blockSignals(True)
        self._steps.setCurrentRow(self._pages.currentIndex())
        self._steps.blockSignals(False)

    def _on_connect_clicked(self):
        if self._view_model.get_state() in (MainViewModelState.CONNECTED, MainViewModelState.RUNNING):
            self._view_model.disconnect_robot()
        else:
            self._view_model.connect_robot()

    # ------------------------------------------------------------------ fermeture
    def closeEvent(self, event):
        state = self._view_model.get_state()
        if state in (MainViewModelState.CONNECTED, MainViewModelState.RUNNING):
            if not self._view_model.is_simulation() and \
                    not self._view_model.confirm("Quitter", "Le robot est connecté.\r\nLe déconnecter et quitter ?"):
                event.ignore()
                return
            if state == MainViewModelState.RUNNING:
                self._view_model.get_robot_monitor_view_model().stop()
                self._view_model.get_scripts_view_model().arreter()
                self._view_model.get_collecte_view_model().arreter()
                deadline = time.perf_counter() + 3
                while self._view_model.get_state() == MainViewModelState.RUNNING and time.perf_counter() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.01)
            self._view_model.disconnect_robot()
        self.teleop_view.save_state()
        self.scripts_view.enregistrer_tout()
        self.scripts_view.close_3d()
        self.collecte_view.close_3d()
        self.essais_view.close_3d()     # libère les rendus OpenGL avant la sortie
        self.teleop_view.close_3d()
        self._view_model.quit()
        super().closeEvent(event)

    # ------------------------------------------------------------------ fenêtres existantes
    def on_action_new(self):
        if self._view_model.new():
            # un nouveau robot commence par sa structure
            self._steps.setCurrentRow(STEP_ROBOT)
            self.on_action_structure()

    def on_action_edit_configuration(self):
        self._view_model.execute_edit_configuration(lambda vm: EditConfigurationView(self, vm).exec())

    def on_action_assemble(self):
        self._view_model.execute_assemblage(lambda vm: AssemblageView(self, vm).exec())
        self._update_summary()

    def on_action_build_leader(self):
        self._view_model.execute_build_leader(lambda vm: AssemblageView(self, vm).exec())

    def on_action_recalibrate(self):
        motors = list(self._view_model.motor_modules())
        motor, ok = QInputDialog.getItem(self, "Recalibrer un servo", "Servo à recalibrer :", motors, 0, False)
        if ok and motor:
            self._view_model.execute_recalibration(motor, lambda vm: AssemblageView(self, vm).exec())
            self._update_summary()

    def _update_summary(self):
        summary = self._view_model.robot_summary()
        self._card_concevoir.set_status(summary.get("concevoir", ""))
        self._card_construire.set_status(summary.get("construire", ""))
        self._card_reglages.set_status(summary.get("regler", ""))
        self._card_recalibrer.set_status(summary.get("regler", ""))


    def on_action_motor_cfg(self):
        def open_dialog(vm: MotorConfigurationViewModel):
            dlg = MotorConfigurationView(self, vm)
            return dlg.exec()
        self._view_model.execute_motor_configuration(open_dialog)

    def on_action_close(self):
        if self._view_model.close_robot():
            self._steps.setCurrentRow(STEP_ROBOT)
            self._robot_pages.setCurrentIndex(0)

    def on_action_advanced(self):
        self._steps.setCurrentRow(STEP_ROBOT)
        self._robot_pages.setCurrentIndex(1)

    def on_action_servo_id(self):
        self._view_model.execute_servo_id(lambda vm: ServoIdView(self, vm).exec())

    def on_action_structure(self):
        self._view_model.execute_structure_editor(lambda vm: StructureEditorView(self, vm).exec())

