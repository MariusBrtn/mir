from __future__ import annotations
from typing import Any
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QSpinBox, QSplitter, QToolBar, QVBoxLayout, QWidget)
from mir_robot.essai import CONSIGNE, Essai
from mir_robot_editor.essais.essais_view_model import REGLAGES_MOTEUR, EssaisViewModel, EssaisVMAction
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui.widgets import CarteRepliable, ToolButton, mono_font
from mir_utils.ui import theme

COULEURS = theme.COURBES        # une couleur par essai superposé
FREQUENCE_SIMULATION = 500  # Hz, fréquence d'acquisition des essais en simulation (sans réglage ; réglable en réel)
HAUTEUR_COURBE = 90         # hauteur minimale de chaque courbe (px) : cinq courbes tiennent sous la 3D sans défiler


UNITES_AFFICHEES = {"deg": "°", "rpm": "tr/min"}


def _unite_affichee(unite: str) -> str:
    return UNITES_AFFICHEES.get(unite, unite)


def _titre_courbe(nom: str, unite: str) -> str:
    unite = _unite_affichee(unite)
    return f"{nom} ({unite})" if unite else nom


PID = ("P", "I", "D")
LIMITES = ("position_mode_velocity", "torque_limit")      # non simulées : seule la tension (12 V) sature


def _titre_court(essai: Essai) -> str:
    """Ex. « Échelon 0 → 30° · P=16 I=0 D=32 » ; * devant : pas encore enregistré. Le reste est dans l'infobulle."""
    reglages = essai.conditions.get("reglages_moteur") or {}
    pid = " ".join(f"{k}={reglages[k]:g}" for k in ("P", "I", "D") if k in reglages)
    non_enregistre = "* " if essai.chemin is None else ""
    return non_enregistre + " · ".join(m for m in (essai.resume_sollicitation(), pid) if m)


def _infobulle(essai: Essai) -> str:
    c = essai.conditions
    reglages = c.get("reglages_moteur") or {}
    lignes = [str(c.get("date", "")), f"Actionneur : {essai.actionneur}",
              f"{'Simulé' if c.get('simulation') else 'Réel'}" + (f", {c['fps']:g} Hz" if c.get("fps") else "")]
    if "position_mode_velocity" in reglages:
        lignes.append(f"Vitesse max : {reglages['position_mode_velocity']} tr/min")
    if "torque_limit" in reglages:
        lignes.append(f"Couple max : {reglages['torque_limit']} ‰")
    lignes.append(str(essai.chemin) if essai.chemin else "Pas encore enregistré")
    return "\n".join(lignes)


def _en_escalier(t, valeurs) -> tuple[np.ndarray, np.ndarray]:
    """Consigne tenue jusqu'à l'envoi suivant (comme elle est appliquée) : un échelon est tracé vertical, pas
    comme un segment oblique entre deux mesures."""
    t, valeurs = np.asarray(t, float), np.asarray(valeurs, float)
    if len(t) < 2:
        return t, valeurs
    return np.repeat(t, 2)[1:], np.repeat(valeurs, 2)[:-1]


# étendue minimale de l'axe vertical, par unité : en dessous, une courbe est vue comme plate (pas de zoom sur un
# écart de 1e-4° ou sur le bruit de calcul, 1e-14 au lieu de 0)
ETENDUE_MIN = {"deg": 1.0, "rpm": 1.0, "mA": 10.0, "%": 1.0}


def _cadrer_y(plot) -> None:
    """Axe vertical adapté aux données, mais jamais plus serré que l'étendue minimale de la grandeur."""
    valeurs = [item.yData for item in plot.listDataItems() if item.yData is not None and len(item.yData)]
    if not valeurs:
        return
    y = np.concatenate(valeurs)
    y = y[np.isfinite(y)]
    if not len(y):
        return
    bas, haut = float(y.min()), float(y.max())
    etendue = getattr(plot, "etendue_min", 1.0)
    if haut - bas < etendue:
        centre = (bas + haut) / 2
        if abs(centre) < etendue / 2:
            centre = 0.0            # courbe presque nulle : un vrai 0 au milieu
        plot.setYRange(centre - etendue / 2, centre + etendue / 2, padding=0.05)
    else:
        plot.enableAutoRange(axis="y")


def _pastille(couleur: str) -> QIcon:
    """Carré de la couleur des courbes de l'essai : la légende est dans la liste, pas sur les courbes."""
    pixmap = QPixmap(14, 14)
    pixmap.fill(QColor(couleur))
    return QIcon(pixmap)


class EssaisView(QWidget, ViewBase[EssaisViewModel, EssaisVMAction]):
    def __init__(self, parent, view_model: EssaisViewModel):
        super().__init__(parent, view_model=view_model)  # type: ignore
        vm = self._view_model
        vm.robot_changed.connect(self._on_robot_changed)
        vm.briques_changed.connect(self._on_briques_changed)
        vm.essais_changed.connect(self._on_essais_changed)
        vm.essai_termine.connect(self._on_essai_termine)
        vm.busy_state_changed.connect(self._on_busy_changed)
        self._param_widgets: dict[str, QDoubleSpinBox] = {}
        self._reglage_widgets: dict[str, QDoubleSpinBox] = {}
        self._grandeur_boxes: dict[str, QCheckBox] = {}
        self._grandeurs_decochees: set[str] = set()     # gardées quand le robot est reconstruit (réglage modifié)
        self._simulation = False
        self._actionneur_choisi: str | None = None     # conservé quand le robot est reconstruit
        self._sollicitation_affichee: str | None = None

        root = QHBoxLayout(self)
        root.addWidget(self._make_left(), 0)
        root.addWidget(self._make_center(), 1)
        self._right_panel = self._make_right()
        root.addWidget(self._right_panel, 0)

        # en simulation : la vue 3D du robot simulé, rafraîchie en continu, au-dessus des courbes
        self._timer_3d = QTimer(self)
        self._timer_3d.setInterval(33)
        self._timer_3d.timeout.connect(self._viewport.update)
        # en simulation : courbes tracées pendant l'essai
        self._timer_direct = QTimer(self)
        self._timer_direct.setInterval(50)
        self._timer_direct.timeout.connect(self._tracer_en_direct)
        self._courbes_direct: dict[str, Any] = {}
        self._graphes_direct: list[Any] = []

        self._on_briques_changed()
        self._on_robot_changed()

    # ------------------------------------------------------------------ construction
    def _make_left(self) -> QWidget:
        # cartes repliables (état retenu) ; Lancer / Arrêter fixés en bas, hors de la zone qui défile
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        self.essai_box = CarteRepliable("Essai", ouverte=True, cle="essais/essai")
        form = QFormLayout(self.essai_box.contenu)
        self.cb_actionneur = QComboBox()
        self.cb_actionneur.currentIndexChanged.connect(self._on_actionneur_changed)
        form.addRow("Actionneur", self.cb_actionneur)
        sollicitation_row = QHBoxLayout()
        self.cb_sollicitation = QComboBox()
        self.cb_sollicitation.currentIndexChanged.connect(self._on_sollicitation_changed)
        sollicitation_row.addWidget(self.cb_sollicitation, 1)
        sollicitation_row.addWidget(ToolButton("scan", self._view_model.refresh_briques, True,
                                               "Relire les fichiers de sollicitations"))
        form.addRow("Sollicitation", sollicitation_row)
        self.lbl_sollicitation = QLabel()
        self.lbl_sollicitation.setWordWrap(True)
        self.lbl_sollicitation.setStyleSheet("color: palette(placeholder-text);")
        form.addRow(self.lbl_sollicitation)
        layout.addWidget(self.essai_box)

        self.params_box = CarteRepliable("Paramètres de la sollicitation", ouverte=True, cle="essais/parametres")
        self.params_form = QFormLayout(self.params_box.contenu)
        layout.addWidget(self.params_box)

        self.reglages_box = CarteRepliable("Réglages du moteur", ouverte=False, cle="essais/reglages")
        reglages_form = QFormLayout(self.reglages_box.contenu)
        self._reglages_form = reglages_form
        for attr, (libelle, mini, maxi) in REGLAGES_MOTEUR.items():
            spin = QDoubleSpinBox()          # décimales pour le PID simulé ; entiers (registres) en réel
            spin.setDecimals(0)
            spin.setRange(mini, maxi)
            spin.valueChanged.connect(lambda _: self._maj_resumes())
            self._reglage_widgets[attr] = spin
            reglages_form.addRow(libelle, spin)
        self.lbl_reglages = QLabel()
        self.lbl_reglages.setWordWrap(True)
        self.lbl_reglages.setStyleSheet("color: palette(placeholder-text); font-style: italic;")
        reglages_form.addRow(self.lbl_reglages)
        layout.addWidget(self.reglages_box)

        self.grandeurs_box = CarteRepliable("Grandeurs enregistrées", ouverte=False, cle="essais/grandeurs")
        grandeurs = QVBoxLayout(self.grandeurs_box.contenu)
        self.grandeurs_layout = QVBoxLayout()           # une case par grandeur (refaite quand l'actionneur change)
        grandeurs.addLayout(self.grandeurs_layout)
        # fréquence d'acquisition : réglable en réel ; en simulation, toujours FREQUENCE_SIMULATION
        self._fps_widget = QWidget()
        fps_row = QHBoxLayout(self._fps_widget)
        fps_row.setContentsMargins(0, 6, 0, 0)
        fps_row.addWidget(QLabel("Fréquence d'acquisition"))
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(10, 500)
        self.sp_fps.setValue(50)
        self.sp_fps.setSuffix(" Hz")
        self.sp_fps.valueChanged.connect(lambda _: self._maj_resumes())
        fps_row.addWidget(self.sp_fps)
        grandeurs.addWidget(self._fps_widget)
        layout.addWidget(self.grandeurs_box)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(4, 6, 4, 4)
        self.btn_lancer = QPushButton(self._icon("play"), "Lancer l'essai")
        self.btn_lancer.setIconSize(QSize(24, 24))
        self.btn_lancer.clicked.connect(self._on_lancer)
        self._view_model.get_action(EssaisVMAction.LANCER).action_state_changed.connect(self.btn_lancer.setEnabled)
        self.btn_lancer.setEnabled(self._view_model.get_action(EssaisVMAction.LANCER).enabled)
        buttons.addWidget(self.btn_lancer)
        self.btn_arreter = QPushButton(self._icon("stop"), "Arrêter")
        self.btn_arreter.setIconSize(QSize(24, 24))
        self.btn_arreter.clicked.connect(self._view_model.arreter)
        self._view_model.get_action(EssaisVMAction.ARRETER).action_state_changed.connect(self.btn_arreter.setEnabled)
        self.btn_arreter.setEnabled(False)
        buttons.addWidget(self.btn_arreter)

        colonne = QWidget()
        colonne.setFixedWidth(330)
        colonne_layout = QVBoxLayout(colonne)
        colonne_layout.setContentsMargins(0, 0, 0, 0)
        colonne_layout.setSpacing(0)
        colonne_layout.addWidget(scroll, 1)
        colonne_layout.addLayout(buttons)
        return colonne

    def _maj_resumes(self):
        """Résumés affichés dans le titre des cartes repliées."""
        if not hasattr(self, "grandeurs_box"):
            return
        actionneur = self._actionneur()
        self.essai_box.set_resume(" · ".join(m for m in (actionneur.split(".")[0], self.cb_sollicitation.currentText())
                                             if m))
        duree = self._param_widgets.get("duree")
        self.params_box.set_resume(f"durée {duree.value():g} s" if duree is not None else "")
        pid = " ".join(f"{k}={self._reglage_widgets[k].value():g}" for k in PID)
        self.reglages_box.set_resume(pid)
        n = sum(box.isChecked() for box in self._grandeur_boxes.values())
        self.grandeurs_box.set_resume(f"{n} grandeur{'s' if n > 1 else ''} · {self._frequence()} Hz")

    def _frequence(self) -> int:
        return FREQUENCE_SIMULATION if self._simulation else self.sp_fps.value()

    def _make_center(self) -> QWidget:
        self._center = QSplitter(Qt.Orientation.Vertical)
        self._viewport = MujocoWidget()
        self._center.addWidget(self._viewport)           # robot simulé : vue 3D
        self._plots_widget = pg.GraphicsLayoutWidget()
        self._plots_widget.setBackground(theme.COURBES_FOND)
        self._plots: dict[str, pg.PlotItem] = {}
        # une courbe par grandeur, chacune assez haute pour être lisible : on fait défiler s'il y en a beaucoup
        self._plots_scroll = QScrollArea()
        self._plots_scroll.setWidgetResizable(True)
        self._plots_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._plots_scroll.setWidget(self._plots_widget)
        self._center.addWidget(self._plots_scroll)       # courbes de mesure
        self._center.setSizes([260, 540])         # en simulation : la 3D au-dessus, les courbes ont la plus grande part
        return self._center

    def _make_right(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        title = QLabel("Essais")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        hint = QLabel("Cochez les essais à superposer ; l'essai sélectionné est en trait épais. "
                      "Maj ou Cmd + clic : sélectionner plusieurs essais. * : essai pas encore enregistré.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(hint)
        self.list_essais = QListWidget()
        # sélection multiple (Maj / Cmd + clic) : retirer plusieurs essais d'un coup
        self.list_essais.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_essais.itemChanged.connect(lambda _: self._redraw())
        self.list_essais.currentRowChanged.connect(lambda _: self._redraw())
        layout.addWidget(self.list_essais, 1)
        cle = QLabel("Sur les courbes : couleur = essai (pastille ci-dessus) ; trait plein = mesure, "
                     "pointillés = consigne.")
        cle.setWordWrap(True)
        cle.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(cle)
        toolbar = QToolBar(iconSize=QSize(20, 20))
        self._action_ouvrir = self._make_action(EssaisVMAction.OUVRIR, self._view_model.ouvrir, "folder-open", toolbar=toolbar)
        self._action_enregistrer = self._make_action(
            EssaisVMAction.ENREGISTRER, lambda: self._view_model.enregistrer(self.list_essais.currentRow()), "save",
            toolbar=toolbar)
        btn_retirer = QPushButton("Retirer de la liste")
        btn_retirer.clicked.connect(lambda: self._view_model.retirer(
            [self.list_essais.row(item) for item in self.list_essais.selectedItems()]))
        toolbar.addWidget(btn_retirer)
        layout.addWidget(toolbar)
        return panel

    # ------------------------------------------------------------------ robot et briques
    def set_simulation(self, simulation: bool):
        self._simulation = simulation
        self._viewport.setVisible(simulation)
        # en simulation, le servo est un PID dont seule la tension sature : pas de vitesse ni de couple max ;
        # ses gains peuvent être décimaux (les registres du servo réel sont des entiers)
        for attr in LIMITES:
            self._reglages_form.setRowVisible(self._reglage_widgets[attr], not simulation)
        self._fps_widget.setVisible(not simulation)
        self._maj_resumes()
        for attr in PID:
            self._reglage_widgets[attr].setDecimals(2 if simulation else 0)
            self._reglage_widgets[attr].setSingleStep(0.1 if simulation else 1)
        self._update_3d()
        self.lbl_reglages.setText("En simulation, le servo est un PID pur : seule la tension du moteur (12 V) est "
                                  "limitée. Ce PID n'est modifié que le temps des essais (il reprend son réglage par "
                                  "défaut en les quittant) ; il n'est pas celui du servo réel." if simulation else
                                  "Les réglages modifiés sont écrits dans le moteur au lancement de l'essai, le temps des essais : "
                                  "MIR remet les siens en quittant les essais.")

    def _update_3d(self):
        world = self._view_model.sim_world() if self._simulation else None
        if world is None:
            self._timer_3d.stop()
            self._viewport.show_message("Le robot simulé apparaît ici dès qu'un robot avec une structure est ouvert."
                                        if self._simulation else "")
            return
        self._viewport.set_sim_world(world)
        self._timer_3d.start()

    def close_3d(self):
        self._timer_3d.stop()
        self._viewport.show_message("")

    def _on_robot_changed(self):
        self._update_3d()
        actionneurs = self._view_model.actionneurs()
        current = self._actionneur_choisi
        self.cb_actionneur.blockSignals(True)
        self.cb_actionneur.clear()
        for nom, unite in actionneurs.items():
            self.cb_actionneur.addItem(f"{nom}  ({unite})", nom)
        index = self.cb_actionneur.findData(current)
        self.cb_actionneur.setCurrentIndex(max(index, 0))
        self.cb_actionneur.blockSignals(False)
        self._on_actionneur_changed()

    def _on_briques_changed(self):
        for combo, disponibles in ((self.cb_sollicitation, self._view_model.sollicitations),):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            for nom in disponibles.commandes:
                combo.addItem(nom)
            index = combo.findText(current)
            combo.setCurrentIndex(max(index, 0))
            combo.blockSignals(False)
        self._on_sollicitation_changed()
        self._redraw()

    def _actionneur(self) -> str:
        return self.cb_actionneur.currentData() or ""

    def _on_actionneur_changed(self, *_):
        actionneur = self._actionneur()
        if actionneur:
            self._actionneur_choisi = actionneur
        for attr, valeur in self._view_model.reglages(actionneur).items():
            if attr in self._reglage_widgets:
                self._reglage_widgets[attr].setValue(float(valeur))
        while self.grandeurs_layout.count():
            item = self.grandeurs_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._grandeur_boxes = {}
        for nom in self._view_model.grandeurs(actionneur):
            box = QCheckBox(nom)
            box.setChecked(nom not in self._grandeurs_decochees)
            box.toggled.connect(lambda coche, nom=nom: (self._grandeurs_decochees.discard if coche
                                                         else self._grandeurs_decochees.add)(nom))
            box.toggled.connect(lambda _: self._redraw())       # graphes prévus : ceux des grandeurs cochées
            box.toggled.connect(lambda _: self._maj_resumes())
            self._grandeur_boxes[nom] = box
            self.grandeurs_layout.addWidget(box)
        self._on_sollicitation_changed()

    def _on_sollicitation_changed(self, *_):
        nom_sollicitation = self.cb_sollicitation.currentText()
        classe = self._view_model.sollicitations.commandes.get(nom_sollicitation)
        # les valeurs saisies sont gardées pour la même sollicitation (changement d'actionneur, robot reconstruit)
        previous = {nom: w.value() for nom, w in self._param_widgets.items()} \
            if nom_sollicitation == self._sollicitation_affichee else {}
        self._sollicitation_affichee = nom_sollicitation
        while self.params_form.rowCount():
            self.params_form.removeRow(0)
        self._param_widgets = {}
        if classe is None:
            self.lbl_sollicitation.setText("")
            self._redraw()
            return
        self.lbl_sollicitation.setText(classe.description)
        unite_actionneur = self._view_model.actionneurs().get(self._actionneur(), "")
        plage = self._view_model.plage(self._actionneur())
        for nom, parametre in classe.parametres.items():
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            unite = parametre.unite or unite_actionneur   # sans unité : unité de l'actionneur
            if parametre.unite == "" and plage is not None:
                spin.setRange(float(plage[0]), float(plage[1]))
            else:
                spin.setRange(0.0, 600.0)
            spin.setSuffix(f" {unite}" if unite else "")
            spin.setValue(previous.get(nom, float(parametre.defaut)))
            if nom == "periode":
                spin.setMinimum(0.1)        # une période nulle n'a pas de sens (et la consigne ne se calcule pas)
            if nom == "duree":
                spin.valueChanged.connect(lambda _: self._redraw())     # axe du temps des graphes prévus
                spin.valueChanged.connect(lambda _: self._maj_resumes())
            self._param_widgets[nom] = spin
            self.params_form.addRow(parametre.libelle or nom, spin)
        self._maj_resumes()
        self._redraw()

    # ------------------------------------------------------------------ essai
    def _on_lancer(self):
        self._view_model.lancer(
            self.cb_sollicitation.currentText(), self._actionneur(),
            {nom: w.value() for nom, w in self._param_widgets.items()},
            [nom for nom, box in self._grandeur_boxes.items() if box.isChecked()],
            self._frequence(),
            {attr: w.value() for attr, w in self._reglage_widgets.items()
             if not (self._simulation and attr in LIMITES)})        # en simulation : seulement le PID

    def _on_busy_changed(self, busy: bool):
        # pendant l'essai, on ne change ni l'essai ni ce qu'on mesure ; les cartes restent repliables
        for w in (self.cb_actionneur, self.cb_sollicitation, self.params_box.contenu, self.grandeurs_box.contenu):
            w.setEnabled(not busy)
        if busy and self._simulation:
            self._demarrer_en_direct()
        elif busy:
            # robot réel : pas de courbe pendant l'essai, l'affichage ralentirait l'acquisition ; elles viennent à la fin
            self._message_courbes("Essai en cours… les courbes s'afficheront à la fin.")
        else:
            self._timer_direct.stop()
            self._courbes_direct = {}

    def _demarrer_en_direct(self):
        """Simulation : les courbes de l'essai en cours, mises à jour pendant le mouvement."""
        actionneur = self._actionneur()
        plots = self._graphes_prevus()
        self._graphes_direct = list(plots.values())     # l'axe vertical suit les mesures ; l'axe du temps reste fixe
        couleur = COULEURS[len(self._view_model.essais) % len(COULEURS)]     # celle que prendra l'essai
        self._courbes_direct = {nom: plot.plot(pen=pg.mkPen(couleur, width=3)) for nom, plot in plots.items()}
        if actionneur in plots:
            self._courbes_direct[CONSIGNE] = plots[actionneur].plot(
                pen=pg.mkPen(couleur, width=1, style=Qt.PenStyle.DashLine))
        self._timer_direct.start()

    def _tracer_en_direct(self):
        mesures = self._view_model.mesures_en_direct()
        if not mesures:
            return
        t = [m[0] for m in mesures]
        for nom, courbe in self._courbes_direct.items():
            if nom == CONSIGNE:
                courbe.setData(*_en_escalier(t, [m[2] for m in mesures]))
            else:
                courbe.setData(t, [m[1].get(nom, float("nan")) for m in mesures])
        for plot in self._graphes_direct:
            _cadrer_y(plot)

    def _on_essai_termine(self, essai: Essai):
        # le nouvel essai est sélectionné, et seul coché avec ceux déjà cochés
        self.list_essais.setCurrentRow(self.list_essais.count() - 1)
        self._redraw()

    def _on_essais_changed(self):
        coches = {self.list_essais.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list_essais.count())
                  if self.list_essais.item(i).checkState() == Qt.CheckState.Checked}
        ajoute = len(self._view_model.essais) > self.list_essais.count()
        self.list_essais.blockSignals(True)
        self.list_essais.clear()
        for essai in self._view_model.essais:
            item = QListWidgetItem(_pastille(self._couleur(essai)), _titre_court(essai))
            item.setToolTip(_infobulle(essai))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # un nouvel essai est affiché seul : les autres se recochent pour les superposer
            nouveau = ajoute and essai is self._view_model.essais[-1]
            coche = nouveau or (not ajoute and id(essai) in coches)
            item.setCheckState(Qt.CheckState.Checked if coche else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, id(essai))
            self.list_essais.addItem(item)
        self.list_essais.blockSignals(False)
        if self.list_essais.currentRow() < 0 and self.list_essais.count():
            self.list_essais.setCurrentRow(self.list_essais.count() - 1)
        self._redraw()

    def _couleur(self, essai: Essai) -> str:
        """Couleur d'un essai : fixée par sa place dans la liste (la même dans la liste et sur les courbes)."""
        index = next((i for i, e in enumerate(self._view_model.essais) if e is essai), 0)
        return COULEURS[index % len(COULEURS)]

    def _essai_at(self, row: int) -> Essai | None:
        if 0 <= row < len(self._view_model.essais):
            return self._view_model.essais[row]
        return None

    # ------------------------------------------------------------------ courbes
    def _message_courbes(self, texte: str):
        self._plots_widget.clear()
        self._set_plots_height(0)
        self._plots_widget.addLabel(texte, color=theme.TEXT_MUTED, size="10pt")

    def _graphes_prevus(self) -> dict[str, Any]:
        """Les graphes de l'essai tel qu'il est réglé (grandeurs cochées, durée), encore vides ; la grandeur
        sollicitée en premier. Axe du temps : la durée de l'essai ; axe vertical : les bornes de la grandeur."""
        actionneur = self._actionneur()
        noms = [nom for nom, box in self._grandeur_boxes.items() if box.isChecked()]
        noms.sort(key=lambda nom: nom != actionneur)
        if not noms:
            self._message_courbes("Cochez les grandeurs à enregistrer : leurs courbes s'afficheront ici."
                                  if self._grandeur_boxes else "Les courbes des essais s'afficheront ici.")
            return {}
        self._plots_widget.clear()
        plots = self._creer_graphes([(nom, self._view_model.unite(nom)) for nom in noms])
        if plots and "duree" in self._param_widgets:
            next(iter(plots.values())).setXRange(0, self._param_widgets["duree"].value(), padding=0.02)
        for nom, plot in plots.items():
            plage = self._view_model.plage(nom) if nom == actionneur else self._view_model.plage_grandeur(nom)
            if plage is not None:
                plot.setYRange(*plage, padding=0.05)
        return plots

    def _redraw(self):
        if self._view_model.is_running():
            return
        self._plots_widget.clear()
        self._set_plots_height(0)
        selection = self._essai_at(self.list_essais.currentRow())
        affiches = [self._essai_at(i) for i in range(self.list_essais.count())
                    if self.list_essais.item(i).checkState() == Qt.CheckState.Checked]
        affiches = [e for e in affiches if e is not None]
        if selection is not None and selection not in affiches:
            affiches.insert(0, selection)
        if not affiches:
            self._graphes_prevus()        # avant toute mesure : les axes de l'essai prévu
            return
        # une courbe par grandeur ; la grandeur sollicitée (et la consigne) en premier
        noms: list[str] = []
        for essai in affiches:
            principal = [essai.actionneur] if essai.actionneur in essai else []
            for nom in principal + [n for n in essai.noms if n != CONSIGNE]:
                if nom not in noms:
                    noms.append(nom)
        plots = self._creer_graphes([(nom, next((e.unite(nom) for e in affiches if nom in e and e.unite(nom)), ""))
                                     for nom in noms])
        for essai in affiches:
            couleur = self._couleur(essai)
            largeur = 3 if essai is selection else 1.5
            for nom, plot in plots.items():
                if nom not in essai:
                    continue
                plot.plot(essai.t, essai[nom], pen=pg.mkPen(couleur, width=largeur))
                if nom == essai.actionneur:
                    plot.plot(*_en_escalier(essai.t, essai.consigne),
                              pen=pg.mkPen(couleur, width=1, style=Qt.PenStyle.DashLine))
        for plot in plots.values():
            _cadrer_y(plot)

    def _creer_graphes(self, grandeurs: list[tuple[str, str]]) -> dict[str, Any]:
        """Un graphe par grandeur (nom, unité), empilés, avec le même axe du temps."""
        plots: dict[str, Any] = {}
        premier = None
        for row, (nom, unite) in enumerate(grandeurs):
            plot = self._plots_widget.addPlot(row=row, col=0)
            plot.etendue_min = ETENDUE_MIN.get(unite, 1.0)
            # style Atelier : graphe en carte claire, titre en Plex Sans, valeurs des axes en Plex Mono
            plot.setTitle(_titre_courbe(nom, unite), size="9pt", color=theme.TEXT)
            plot.getViewBox().setBackgroundColor(theme.COURBES_GRAPHE)
            plot.getViewBox().setBorder(pg.mkPen(theme.BORDER))
            plot.showGrid(x=True, y=True, alpha=0.5)
            for cote in ("left", "bottom"):
                axe = plot.getAxis(cote)
                axe.setPen(pg.mkPen(theme.COURBES_GRILLE))
                axe.setTextPen(pg.mkPen(theme.TEXT_MUTED))
                axe.setStyle(tickFont=mono_font(9))
            # même temps pour toutes les courbes : l'axe du temps seulement sous la dernière, pour gagner de la place
            if row == len(grandeurs) - 1:
                plot.setLabel("bottom", "t", "s")
            else:
                plot.getAxis("bottom").setStyle(showValues=False)
            if premier is None:
                premier = plot
            else:
                plot.setXLink(premier)
            plots[nom] = plot
        self._set_plots_height(len(plots))
        return plots

    def _set_plots_height(self, n: int):
        self._plots_widget.setMinimumHeight(n * HAUTEUR_COURBE)
