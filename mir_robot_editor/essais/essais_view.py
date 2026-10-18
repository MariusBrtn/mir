from __future__ import annotations
from typing import Any
import pyqtgraph as pg
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea,
                               QSpinBox, QStackedWidget, QToolBar, QVBoxLayout, QWidget)
from mir_robot.essai import CONSIGNE, Essai
from mir_robot_editor.essais.essais_view_model import REGLAGES_MOTEUR, EssaisViewModel, EssaisVMAction
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui.widgets import ToolButton
from mir_utils.ui import theme

# couleurs des essais superposés (le premier est l'essai sélectionné)
COULEURS = ["#00B4FF", "#FF8C1A", "#3CCB5A", "#E04BD8", "#F2D13A", "#9A7BFF"]
COULEUR_CONSIGNE = "#BBBBBB"
HAUTEUR_COURBE = 180        # hauteur minimale de chaque courbe (px)


UNITES_AFFICHEES = {"deg": "°", "rpm": "tr/min"}


def _unite_affichee(unite: str) -> str:
    return UNITES_AFFICHEES.get(unite, unite)


def _titre_courbe(nom: str, unite: str) -> str:
    unite = _unite_affichee(unite)
    return f"{nom} ({unite})" if unite else nom


PID = ("P", "I", "D")
FPS_SIMULATION = 50         # en simulation, l'essai ne fait qu'animer le robot : pas de fréquence à choisir


def _titre_court(essai: Essai) -> str:
    """Ex. « Échelon 0 → 30° · P=16 I=0 D=32 » ; * devant : pas encore enregistré. Le reste est dans l'infobulle."""
    reglages = essai.conditions.get("reglages_moteur") or {}
    pid = " ".join(f"{k}={reglages[k]}" for k in ("P", "I", "D") if k in reglages)
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
        self._reglage_widgets: dict[str, QSpinBox] = {}
        self._grandeur_boxes: dict[str, QCheckBox] = {}
        self._simulation = False
        self._actionneur_choisi: str | None = None     # conservé quand le robot est reconstruit
        self._sollicitation_affichee: str | None = None

        root = QHBoxLayout(self)
        root.addWidget(self._make_left(), 0)
        root.addWidget(self._make_center(), 1)
        self._right_panel = self._make_right()
        root.addWidget(self._right_panel, 0)

        # en simulation : la vue 3D du robot simulé, rafraîchie en continu, remplace les courbes
        self._timer_3d = QTimer(self)
        self._timer_3d.setInterval(33)
        self._timer_3d.timeout.connect(self._viewport.update)

        self._on_briques_changed()
        self._on_robot_changed()

    # ------------------------------------------------------------------ construction
    def _make_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        self.lbl_mode = QLabel()
        self.lbl_mode.setWordWrap(True)
        self.lbl_mode.setStyleSheet(f"background: {theme.SIM}; color: white; padding: 8px 10px; border-radius: 8px;")
        self.lbl_mode.setText("En simulation, on visualise le mouvement du robot. Les mesures se font sur le robot réel.")
        self.lbl_mode.setVisible(False)
        layout.addWidget(self.lbl_mode)

        essai_box = QGroupBox("Essai")
        form = QFormLayout(essai_box)
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
        layout.addWidget(essai_box)

        self.params_box = QGroupBox("Paramètres de la sollicitation")
        self.params_form = QFormLayout(self.params_box)
        layout.addWidget(self.params_box)

        reglages_box = QGroupBox("Réglages du moteur")
        reglages_form = QFormLayout(reglages_box)
        self._reglages_form = reglages_form
        for attr, (libelle, mini, maxi) in REGLAGES_MOTEUR.items():
            spin = QSpinBox()
            spin.setRange(mini, maxi)
            self._reglage_widgets[attr] = spin
            reglages_form.addRow(libelle, spin)
        self.lbl_reglages = QLabel()
        self.lbl_reglages.setWordWrap(True)
        self.lbl_reglages.setStyleSheet("color: palette(placeholder-text); font-style: italic;")
        reglages_form.addRow(self.lbl_reglages)
        layout.addWidget(reglages_box)

        self.grandeurs_box = QGroupBox("Grandeurs enregistrées")
        self.grandeurs_layout = QVBoxLayout(self.grandeurs_box)
        layout.addWidget(self.grandeurs_box)

        self._fps_widget = QWidget()
        fps_row = QHBoxLayout(self._fps_widget)
        fps_row.setContentsMargins(0, 0, 0, 0)
        fps_row.addWidget(QLabel("Fréquence d'acquisition"))
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(10, 500)
        self.sp_fps.setValue(50)
        self.sp_fps.setSuffix(" Hz")
        fps_row.addWidget(self.sp_fps)
        layout.addWidget(self._fps_widget)

        buttons = QHBoxLayout()
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
        layout.addLayout(buttons)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setFixedWidth(330)
        return scroll

    def _make_center(self) -> QWidget:
        self._center = QStackedWidget()
        self._plots_widget = pg.GraphicsLayoutWidget()
        self._plots: dict[str, pg.PlotItem] = {}
        # une courbe par grandeur, chacune assez haute pour être lisible : on fait défiler s'il y en a beaucoup
        self._plots_scroll = QScrollArea()
        self._plots_scroll.setWidgetResizable(True)
        self._plots_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._plots_scroll.setWidget(self._plots_widget)
        self._center.addWidget(self._plots_scroll)       # robot réel : courbes de mesure
        self._viewport = MujocoWidget()
        self._center.addWidget(self._viewport)           # robot simulé : vue 3D
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
                      "* : essai pas encore enregistré.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(hint)
        self.list_essais = QListWidget()
        self.list_essais.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
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
        btn_retirer.clicked.connect(lambda: self._view_model.retirer(self.list_essais.currentRow()))
        toolbar.addWidget(btn_retirer)
        layout.addWidget(toolbar)
        return panel

    # ------------------------------------------------------------------ robot et briques
    def set_simulation(self, simulation: bool):
        self._simulation = simulation
        self._center.setCurrentIndex(1 if simulation else 0)
        self._right_panel.setVisible(not simulation)
        self.grandeurs_box.setVisible(not simulation)
        self.lbl_mode.setVisible(simulation)
        # en simulation, rien n'est mesuré et l'asservissement est idéal : ni PID ni fréquence d'acquisition
        self._fps_widget.setVisible(not simulation)
        for attr in PID:
            self._reglages_form.setRowVisible(self._reglage_widgets[attr], not simulation)
        self._update_3d()
        self.lbl_reglages.setText("En simulation, l'asservissement est idéal : seuls la vitesse et le couple max "
                                  "sont simulés." if simulation else
                                  "Les réglages modifiés sont écrits dans le moteur au lancement de l'essai, le temps des essais : "
                                  "MIR remet les siens en quittant les essais.")

    def _update_3d(self):
        world = self._view_model.sim_world() if self._simulation else None
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
                self._reglage_widgets[attr].setValue(int(valeur))
        while self.grandeurs_layout.count():
            item = self.grandeurs_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._grandeur_boxes = {}
        for nom in self._view_model.grandeurs(actionneur):
            box = QCheckBox(nom)
            box.setChecked(True)
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
            self._param_widgets[nom] = spin
            self.params_form.addRow(parametre.libelle or nom, spin)

    # ------------------------------------------------------------------ essai
    def _on_lancer(self):
        self._view_model.lancer(
            self.cb_sollicitation.currentText(), self._actionneur(),
            {nom: w.value() for nom, w in self._param_widgets.items()},
            [nom for nom, box in self._grandeur_boxes.items() if box.isChecked()],
            FPS_SIMULATION if self._simulation else self.sp_fps.value(),
            {attr: w.value() for attr, w in self._reglage_widgets.items()})

    def _on_busy_changed(self, busy: bool):
        for w in (self.cb_actionneur, self.cb_sollicitation, self.params_box, self.grandeurs_box, self.sp_fps):
            w.setEnabled(not busy)
        if busy and not self._simulation:
            # pas de courbe pendant l'essai : l'affichage ralentirait l'acquisition ; les courbes viennent à la fin
            self._plots_widget.clear()
            self._set_plots_height(0)
            self._plots_widget.addLabel("Essai en cours… les courbes s'afficheront à la fin.")

    def _on_essai_termine(self, essai: Essai):
        # le nouvel essai est sélectionné, et seul coché avec ceux déjà cochés
        self.list_essais.setCurrentRow(self.list_essais.count() - 1)
        self._redraw()

    def _on_essais_changed(self):
        coches = {id(self._essai_at(i)) for i in range(self.list_essais.count())
                  if self.list_essais.item(i).checkState() == Qt.CheckState.Checked}
        self.list_essais.blockSignals(True)
        self.list_essais.clear()
        for essai in self._view_model.essais:
            item = QListWidgetItem(_pastille(self._couleur(essai)), _titre_court(essai))
            item.setToolTip(_infobulle(essai))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            nouveau = id(essai) not in coches and essai is self._view_model.essais[-1]
            item.setCheckState(Qt.CheckState.Checked if id(essai) in coches or nouveau else Qt.CheckState.Unchecked)
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
            return
        # une courbe par grandeur ; la grandeur sollicitée (et la consigne) en premier
        noms: list[str] = []
        for essai in affiches:
            principal = [essai.actionneur] if essai.actionneur in essai else []
            for nom in principal + [n for n in essai.noms if n != CONSIGNE]:
                if nom not in noms:
                    noms.append(nom)
        plots: dict[str, Any] = {}
        premier = None
        for row, nom in enumerate(noms):
            unite = next((e.unite(nom) for e in affiches if nom in e and e.unite(nom)), "")
            plot = self._plots_widget.addPlot(row=row, col=0, title=_titre_courbe(nom, unite))
            plot.showGrid(x=True, y=True)
            plot.setLabel("bottom", "t", "s")
            if premier is None:
                premier = plot
            else:
                plot.setXLink(premier)
            plots[nom] = plot
        for essai in affiches:
            couleur = self._couleur(essai)
            largeur = 3 if essai is selection else 1.5
            for nom, plot in plots.items():
                if nom not in essai:
                    continue
                plot.plot(essai.t, essai[nom], pen=pg.mkPen(couleur, width=largeur))
                if nom == essai.actionneur:
                    plot.plot(essai.t, essai.consigne, pen=pg.mkPen(couleur, width=1, style=Qt.PenStyle.DashLine))
        self._set_plots_height(len(plots))

    def _set_plots_height(self, n: int):
        self._plots_widget.setMinimumHeight(n * HAUTEUR_COURBE)
