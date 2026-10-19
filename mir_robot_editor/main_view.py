import time
from PySide6.QtCore import Signal, Qt, QSize
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
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
from mir_robot_editor.entrainement.entrainement_view import EntrainementView
from mir_robot_editor.ia.ia_view import IAView
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
STEP_ROBOT, STEP_PILOT, STEP_COLLECT, STEP_TRAIN = 0, 1, 2, 3
TAB_ESSAIS, TAB_TELEOP, TAB_SCRIPTS, TAB_POLITIQUE = 0, 1, 2, 3
# les façons de commander le robot dans Piloter : (titre, explication, icône, disponible)
MODALITES = [
    ("Essais", "Solliciter un moteur et mesurer sa réponse", "stats", True),
    ("Téléopération", "Piloter à la main : clavier, bras leader…", "actions", True),
    ("Scripts", "Programmer le robot en Python", "edit", True),
    ("IA", "Un modèle entraîné pilote le robot", "robot", True),
]
STEPS = [("Configurer le robot", True), ("Piloter", True), ("Collecter des données", True), ("Entraîner un modèle", True)]


class EtapesBar(QWidget):
    """Les étapes du parcours, dans l'en-tête (comme les espaces de travail d'un logiciel de CAO).
    Même usage qu'une liste : currentRow, setCurrentRow, signal currentRowChanged."""
    currentRowChanged = Signal(int)

    def __init__(self, etapes: list[tuple[str, bool]], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._noms = [nom for nom, _ in etapes]
        self._boutons: list[QPushButton] = []
        self._courante = -1
        for i, (nom, disponible) in enumerate(etapes):
            bouton = QPushButton(nom)
            bouton.setObjectName("Etape")
            bouton.setCheckable(True)
            bouton.setCursor(Qt.CursorShape.PointingHandCursor)
            bouton.clicked.connect(lambda _=False, i=i: self.setCurrentRow(i))
            self._boutons.append(bouton)
            layout.addWidget(bouton)
            self.set_enabled(i, disponible, "" if disponible else "À venir")

    def currentRow(self) -> int:
        return self._courante

    def setCurrentRow(self, row: int):
        changee = row != self._courante
        self._courante = row
        for i, bouton in enumerate(self._boutons):
            bouton.setChecked(i == row)
        if changee:
            self.currentRowChanged.emit(row)       # rien n'est émis si les signaux sont bloqués

    def set_enabled(self, i: int, enabled: bool, tooltip: str = ""):
        self._boutons[i].setEnabled(enabled)
        self._boutons[i].setToolTip(tooltip)

    def set_en_cours(self, i: int, en_cours: bool):
        self._boutons[i].setText(self._noms[i] + ("  ●" if en_cours else ""))


class ModaliteCard(QFrame):
    """Une modalité de Piloter : toute la carte est le bouton (icône, titre, explication) ; la choisie est en noir."""

    def __init__(self, titre: str, description: str, icone, icone_choisie, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Modalite")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icones = (icone, icone_choisie)
        self.on_click = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 9, 14, 9)
        layout.setSpacing(10)
        self._icone = QLabel()
        layout.addWidget(self._icone)
        textes = QVBoxLayout()
        textes.setSpacing(1)
        self._titre = QLabel(titre)
        self._titre.setObjectName("ModaliteTitre")
        textes.addWidget(self._titre)
        self._description = QLabel(description)
        self._description.setObjectName("ModaliteDescription")
        self._description.setWordWrap(True)        # passe à la ligne quand la fenêtre est étroite
        textes.addWidget(self._description)
        layout.addLayout(textes, 1)
        self._en_cours = QLabel("● en cours")
        self._en_cours.setObjectName("ModaliteEnCours")
        self._en_cours.setVisible(False)
        layout.addWidget(self._en_cours, alignment=Qt.AlignmentFlag.AlignTop)
        self.set_selected(False)

    def set_en_cours(self, en_cours: bool):
        """Cette modalité fait bouger le robot (une seule à la fois)."""
        self._en_cours.setVisible(en_cours)

    def set_selected(self, selected: bool):
        self.setProperty("selected", selected)
        self._icone.setPixmap(self._icones[1 if selected else 0])
        for w in (self, self._titre, self._description):     # le style dépend de la propriété : on le réapplique
            w.style().unpolish(w)
            w.style().polish(w)

    def mouseReleaseEvent(self, event):
        if self.isEnabled() and self.rect().contains(event.position().toPoint()) and self.on_click is not None:
            self.on_click()
        super().mouseReleaseEvent(event)


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
        self._view_model.scenes_changed.connect(self._remplir_scenes)
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
        self._pages = QStackedWidget()
        self._pages.addWidget(self._make_robot_page())
        self._pages.addWidget(self._make_pilot_page())
        self.collecte_view = CollecteView(self, self._view_model.get_collecte_view_model())
        self._pages.addWidget(self.collecte_view)
        self.collecte_view.revue_changed.connect(lambda _: self._update_header())
        self.entrainement_view = EntrainementView(self, self._view_model.get_entrainement_view_model())
        self._pages.addWidget(self.entrainement_view)
        # qui fait bouger le robot : repère « en cours » sur la modalité ou l'étape concernée
        vm = self._view_model
        self._activites = [(vm.get_essais_view_model(), STEP_PILOT, TAB_ESSAIS),
                           (vm.get_robot_monitor_view_model(), STEP_PILOT, TAB_TELEOP),
                           (vm.get_scripts_view_model(), STEP_PILOT, TAB_SCRIPTS),
                           (vm.get_ia_view_model(), STEP_PILOT, TAB_POLITIQUE),
                           (vm.get_collecte_view_model(), STEP_COLLECT, None),
                           (vm.get_entrainement_view_model(), STEP_TRAIN, None)]
        for activite, _, _ in self._activites:
            activite.busy_state_changed.connect(lambda _: self._update_activites())
        body.addWidget(self._pages, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self.statusBar().hide()      # l'état est dans l'en-tête

        self._make_menus()
        self._steps.setCurrentRow(STEP_ROBOT)
        self._on_simulation_changed(self._view_model.is_simulation())
        self._remplir_scenes()
        self._view_model.update_state_notifications()

    # ------------------------------------------------------------------ construction
    def _make_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        # robot ouvert : simple indication (ouvrir, créer, enregistrer : étape Configurer et menu Robot)
        self._robot_icon = QLabel()      # vert quand un robot est ouvert, gris sinon
        layout.addWidget(self._robot_icon)
        # le robot ouvert ; ses actions rares (ouvrir, créer, enregistrer, fermer) sont dans son menu
        self._robot_menu = QToolButton()
        self._robot_menu.setObjectName("RobotMenu")
        self._robot_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self._robot_menu)
        for action in (self._open_action, self._new_action, None, self._save_action, self._save_as_action, None,
                       self._close_action):
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)
        self._robot_menu.setMenu(menu)
        layout.addWidget(self._robot_menu)
        separateur = QFrame()
        separateur.setFrameShape(QFrame.Shape.VLine)
        separateur.setObjectName("SeparateurEntete")
        layout.addWidget(separateur)
        # les étapes du parcours (à la place de l'ancienne colonne de gauche)
        self._steps = EtapesBar(STEPS)
        self._steps.currentRowChanged.connect(self._on_step_changed)
        layout.addWidget(self._steps)
        layout.addStretch(1)

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
            button.setMinimumWidth(72)
            button.setToolTip("Choisir le robot réel ou le robot simulé (avant de connecter)")
            button.clicked.connect(lambda _=False, s=simulation: self._view_model.set_simulation(s))
            self._mode_group.addButton(button)
            mode_layout.addWidget(button)
        layout.addWidget(mode_box)

        # connexion : un seul bouton, dont le texte suit l'état
        self._btn_connect = QPushButton()
        self._btn_connect.setIconSize(QSize(20, 20))
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        layout.addWidget(self._btn_connect)
        # en simulé : la scène du robot (objets sur la table), qu'on peut replacer
        self._cb_scene = QComboBox()
        self._cb_scene.setMinimumWidth(150)
        self._cb_scene.activated.connect(self._on_scene_choisie)
        layout.addWidget(self._cb_scene)
        # en simulé, rien à connecter : le robot simulé est toujours prêt, on peut seulement le remettre à zéro
        self._btn_reset_sim = QPushButton("↺  Replacer la scène")
        self._btn_reset_sim.setToolTip(self._reset_sim_action.toolTip())
        self._btn_reset_sim.clicked.connect(self._reset_sim_action.trigger)
        layout.addWidget(self._btn_reset_sim)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._status_label)
        # un seul arrêt d'urgence, toujours au même endroit, quelle que soit l'activité qui fait bouger le robot
        self._btn_urgence = QPushButton(self._icon("emergency_stop"), "Arrêt d'urgence")
        self._btn_urgence.setObjectName("Urgence")
        self._btn_urgence.setIconSize(QSize(22, 22))
        self._btn_urgence.setToolTip("Coupe tout de suite le couple des moteurs et arrête l'activité en cours")
        self._btn_urgence.clicked.connect(self._view_model.arret_urgence)
        layout.addWidget(self._btn_urgence)
        self._header = header
        return header

    def _icone_coloree(self, nom: str, couleur: str, taille: int) -> QPixmap:
        """L'icône, entièrement de la couleur donnée (les icônes sont d'une seule couleur)."""
        pixmap = self._icon(nom).pixmap(taille, taille)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(couleur))
        painter.end()
        return pixmap

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
        # plusieurs façons de commander le robot (une seule activité à la fois) : une carte par modalité
        bandeau = QWidget()
        bandeau.setObjectName("Modalites")
        rangee = QHBoxLayout(bandeau)
        rangee.setContentsMargins(14, 12, 14, 12)
        rangee.setSpacing(10)
        self._modalites: list[ModaliteCard] = []
        for index, (titre, description, icone, disponible) in enumerate(MODALITES):
            carte = ModaliteCard(titre, description, self._icone_coloree(icone, theme.INK, 26),
                                 self._icone_coloree(icone, theme.SAND, 26))
            carte.setEnabled(disponible)
            carte.on_click = (lambda i: lambda: self._pilot_tabs.setCurrentIndex(i))(index)
            rangee.addWidget(carte, 1)
            self._modalites.append(carte)
        layout.addWidget(bandeau)
        self._pilot_tabs = QTabWidget()
        self._pilot_tabs.setDocumentMode(True)
        self._pilot_tabs.tabBar().hide()       # les cartes ci-dessus remplacent les onglets
        self.essais_view = EssaisView(self, self._view_model.get_essais_view_model())
        self._pilot_tabs.addTab(self.essais_view, "Essais")
        self.teleop_view = TeleopView(self, self._view_model.get_robot_monitor_view_model(), self,
                                      self._view_model.get_sim_world)
        self.teleop_view.restore_state()
        self.teleop_view.set_leader_action(self._build_leader_action)
        self._pilot_tabs.addTab(self.teleop_view, "Téléopération")
        self.scripts_view = ScriptsView(self, self._view_model.get_scripts_view_model())
        self._pilot_tabs.addTab(self.scripts_view, "Scripts")
        self.ia_view = IAView(self, self._view_model.get_ia_view_model())
        self._pilot_tabs.addTab(self.ia_view, "IA")
        self._pilot_tabs.currentChanged.connect(self._on_pilot_tab_changed)
        self._on_pilot_tab_changed(self._pilot_tabs.currentIndex())
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
        # configurer le robot ne dépend pas du mode : le choix réel / simulé n'apparaît qu'à partir de Piloter
        self._mode_box.setVisible(not configuring)
        name = self._view_model.get_robot_name()
        modifie = " • non enregistré" if name and self._view_model.is_dirty() else ""
        self._robot_menu.setText(f"{name}{modifie}  ▾" if name else "Aucun robot  ▾")
        self._robot_menu.setToolTip(f"Robot ouvert : {name}. Ouvrir, créer, enregistrer ou fermer un robot" if name
                                    else "Ouvrir ou créer un robot")
        # liseré sous l'en-tête : rouge = robot réel, ardoise = robot simulé (visible où que l'on regarde)
        liseré = theme.BORDER if configuring or not robot_ouvert else (COLOR_SIM if simulation else COLOR_REAL)
        epaisseur = 1 if configuring or not robot_ouvert else 4
        self._header.setStyleSheet(f"#Header {{ border-bottom: {epaisseur}px solid {liseré}; }}")
        # en simulé, rien de physique ne bouge : chaque modalité a son bouton Arrêter
        self._btn_urgence.setVisible(robot_ouvert and not configuring and not simulation)
        self._btn_urgence.setEnabled(state == MainViewModelState.RUNNING)

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
            # mode verrouillé (robot en mouvement) : le mode choisi reste lisible
            disabled = "color: rgba(255, 255, 255, 0.8);" if checked else "color: palette(placeholder-text);"
            button.setStyleSheet(f"QPushButton {{ {style} {radius} padding: 6px 14px; }}"
                                 f"QPushButton:disabled {{ {disabled} }}")
        self._btn_real.setToolTip("Choisir le robot réel" if built else
                                  "Le robot n'est pas encore construit : construisez-le dans « Configurer le robot » "
                                  "(étape 2) pour l'utiliser en réel")

        connected = state in (MainViewModelState.CONNECTED, MainViewModelState.RUNNING)
        robot_kind = "robot simulé" if simulation else "robot réel"
        self._btn_connect.setVisible(not simulation and not configuring)
        self._btn_reset_sim.setVisible(simulation and not configuring)
        # revoir un épisode dans Collecter : lecture seule, la scène n'a pas à changer
        en_revue = self._steps.currentRow() == STEP_COLLECT and self.collecte_view._en_revue() \
            if hasattr(self, "collecte_view") else False
        self._btn_reset_sim.setEnabled(self._reset_sim_action.isEnabled() and not en_revue)
        self._cb_scene.setVisible(simulation and not configuring and robot_ouvert)
        self._cb_scene.setEnabled(state != MainViewModelState.RUNNING and not en_revue)
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
            dot, text = COLOR_IDLE, ("Pas de structure" if simulation else "Non connecté")
        elif state == MainViewModelState.CONNECTED:
            dot, text = (COLOR_SIM, "Prêt") if simulation else (theme.OK, "Connecté")
        else:
            # en simulation, on ne parle pas de mesures : les mesures se font sur le robot réel
            dot, text = (COLOR_SIM, "En mouvement") if simulation else (COLOR_RUNNING, "En mouvement")
        self._status_label.setText(f"<span style='color:{dot}; font-size:16px;'>●</span>&nbsp;{text}")
        # en simulé, le robot est toujours prêt : l'état ne s'affiche que s'il y a un problème (pas de structure)
        if simulation and state != MainViewModelState.LOADED:
            self._status_label.setVisible(False)

    def _remplir_scenes(self):
        """Scènes du robot ouvert : « Table vide », puis robots/<robot>/scenes/*.json."""
        vm = self._view_model
        self._cb_scene.blockSignals(True)
        self._cb_scene.clear()
        for path in [None] + vm.get_scenes():
            self._cb_scene.addItem(f"Scène : {vm.scene_name(path)}", path)
            self._cb_scene.setItemData(self._cb_scene.count() - 1, vm.scene_description(path), Qt.ItemDataRole.ToolTipRole)
        # findData compare mal les objets Python (chemins) : on cherche nous-mêmes
        index = next((i for i in range(self._cb_scene.count()) if self._cb_scene.itemData(i) == vm.get_scene()), 0)
        self._cb_scene.setCurrentIndex(index)
        self._cb_scene.setToolTip(vm.scene_description(vm.get_scene()))
        self._cb_scene.blockSignals(False)

    def _on_scene_choisie(self, index: int):
        if not self._view_model.set_scene(self._cb_scene.itemData(index)):
            self._remplir_scenes()          # refusé (mouvement en cours) : on revient à la scène actuelle

    def _update_activites(self):
        etapes_occupees = set()
        for activite, etape, onglet in self._activites:
            en_cours = activite.is_running()
            if onglet is not None:
                self._modalites[onglet].set_en_cours(en_cours)
            if en_cours:
                etapes_occupees.add(etape)
        for i, (name, _) in enumerate(STEPS):
            self._steps.set_en_cours(i, i in etapes_occupees)

    def _on_pilot_tab_changed(self, index: int):
        for i, carte in enumerate(self._modalites):
            carte.set_selected(i == index)
        if index != TAB_ESSAIS:
            self._view_model.restore_essai_settings()     # réglages d'essai temporaires

    def _on_state_changed(self, state: MainViewModelState, description: str):
        if hasattr(self, "_card_concevoir"):
            self._update_summary()
        if hasattr(self, "teleop_view"):
            self.teleop_view.set_leader_state(self._view_model.is_arm(), self._view_model.has_leader_arm())
        previous = getattr(self, "_previous_state", None)
        self._previous_state = state
        self._update_header()
        # sans robot ouvert, il n'y a rien à piloter ni à collecter : ces étapes sont grisées
        if hasattr(self, "_steps"):
            avec_robot = state != MainViewModelState.INIT
            for step in (STEP_PILOT, STEP_COLLECT, STEP_TRAIN):
                self._steps.set_enabled(step, avec_robot, "" if avec_robot else
                                        "Ouvrez ou créez d'abord un robot (étape Configurer)")
            if not avec_robot and self._steps.currentRow() in (STEP_PILOT, STEP_COLLECT, STEP_TRAIN):
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
        self.ia_view.set_simulation(simulation)
        self.collecte_view.set_simulation(simulation)
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
                self._view_model.get_ia_view_model().arreter()
                deadline = time.perf_counter() + 3
                while self._view_model.get_state() == MainViewModelState.RUNNING and time.perf_counter() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.01)
            self._view_model.disconnect_robot()
        self.teleop_view.save_state()
        self.scripts_view.enregistrer_tout()
        self.entrainement_view.enregistrer_tout()
        self.scripts_view.close_3d()
        self.collecte_view.close_3d()
        self.essais_view.close_3d()     # libère les rendus OpenGL avant la sortie
        self.teleop_view.close_3d()
        self.ia_view.close_3d()
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

