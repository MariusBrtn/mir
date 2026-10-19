"""
Étape « Collecter des données » : à gauche le dataset et les réglages, au centre la vue en direct (ou la démonstration
à revoir), à droite les épisodes du dataset.
"""
from __future__ import annotations
import re
from typing import Any
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QSpinBox, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget)
from mir_devices.mir_device import ObservablePropertyBitmap, ObservablePropertyPolar
from mir_robot.donnees import DatasetMIR, FormatDataset
from mir_robot_editor.collecte.collecte_view_model import CollecteViewModel, CollecteVMAction, Phase, est_capteur
from mir_robot_editor.collecte.episode_view import EpisodeView
from mir_robot_editor.observations_widget import PolarWidget, VideoWidget
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_robot_editor.teleop.teleop_view import key_from_qt
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui import theme

NOUVEAU = "Nouveau dataset…"


def nom_valide(nom: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", nom.strip()).strip("_")


class CollecteView(QWidget, ViewBase[CollecteViewModel, CollecteVMAction]):
    def __init__(self, parent, view_model: CollecteViewModel):
        super().__init__(parent, view_model=view_model)  # type: ignore
        vm = self._view_model
        vm.robot_changed.connect(self._on_robot_changed)
        vm.datasets_changed.connect(self._remplir_datasets)
        vm.phase_changed.connect(self._on_phase)
        vm.busy_state_changed.connect(lambda _: self._update_buttons())
        vm.observation_ready.connect(self._on_observation)
        vm.episode_a_revoir.connect(self._on_episode_a_revoir)
        vm.sauvegarde_changed.connect(lambda _: self._update_buttons())
        self._simulation = False
        self._boxes: dict[str, QCheckBox] = {}
        self._capteurs: dict[str, Any] = {}
        self._nouveau: DatasetMIR | None = None        # dataset créé ici, pas encore sur le disque

        root = QHBoxLayout(self)
        root.addWidget(self._make_left(), 0)
        self._center = QStackedWidget()
        self._center.addWidget(self._make_direct())
        self._center.addWidget(self._make_revue())
        root.addWidget(self._center, 1)
        root.addWidget(self._make_right(), 0)

        self._timer_3d = QTimer(self)
        self._timer_3d.setInterval(33)
        self._timer_3d.timeout.connect(self._viewport.update)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._on_robot_changed()
        self._on_phase(Phase.ARRET, 0)

    # ------------------------------------------------------------------ clavier (téléopérations au clavier)
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        if not self._view_model.is_running() or not self.isVisible() or not self.window().isActiveWindow():
            return False
        key = key_from_qt(event)
        if key is None:
            return False
        if event.type() == QEvent.Type.KeyPress:
            self._view_model.keyboard.press(key)
        elif not event.isAutoRepeat():
            self._view_model.keyboard.release(key)
        return True

    # ------------------------------------------------------------------ construction
    def _make_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        box = QGroupBox("Dataset")
        form = QFormLayout(box)
        self.cb_dataset = QComboBox()
        self.cb_dataset.activated.connect(self._on_dataset_choisi)
        form.addRow(self.cb_dataset)
        self.lbl_dataset = QLabel()
        self.lbl_dataset.setWordWrap(True)
        self.lbl_dataset.setStyleSheet("color: palette(placeholder-text);")
        form.addRow(self.lbl_dataset)
        layout.addWidget(box)

        box = QGroupBox("Démonstrations")
        form = QFormLayout(box)
        self.cb_teleop = QComboBox()
        form.addRow("Téléopération", self.cb_teleop)
        self.sp_duree = QDoubleSpinBox()
        self.sp_duree.setRange(1, 120)
        self.sp_duree.setValue(6)
        self.sp_duree.setSuffix(" s")
        form.addRow("Durée", self.sp_duree)
        self.sp_fps = QSpinBox()
        self.sp_fps.setRange(5, 60)
        self.sp_fps.setValue(20)
        self.sp_fps.setSuffix(" Hz")
        form.addRow("Fréquence", self.sp_fps)
        self.ed_tache = QLineEdit()
        self.ed_tache.setPlaceholderText("ex. mettre le dé dans la boîte")
        self.ed_tache.setToolTip("Ce que montre la démonstration, en une phrase (utile aux modèles qui comprennent le langage)")
        form.addRow("Tâche", self.ed_tache)
        layout.addWidget(box)

        box = QGroupBox("Observations enregistrées")
        box_layout = QVBoxLayout(box)
        self.lbl_obs = QLabel("Les consignes enregistrées sont celles de la téléopération.")
        self.lbl_obs.setWordWrap(True)
        self.lbl_obs.setStyleSheet("color: palette(placeholder-text);")
        box_layout.addWidget(self.lbl_obs)
        contenu = QWidget()
        self._obs_layout = QVBoxLayout(contenu)
        self._obs_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(contenu)
        box_layout.addWidget(scroll)
        layout.addWidget(box, 1)

        boutons = QHBoxLayout()
        self.btn_demarrer = QPushButton(self._icon("play"), "Démarrer")
        self.btn_demarrer.setToolTip("Démarrer la téléopération, sans enregistrer : mettez le robot en position")
        self.btn_demarrer.clicked.connect(self._on_demarrer)
        boutons.addWidget(self.btn_demarrer)
        self.btn_arreter = QPushButton(self._icon("stop"), "Arrêter")
        self.btn_arreter.clicked.connect(self._view_model.arreter)
        boutons.addWidget(self.btn_arreter)
        layout.addLayout(boutons)
        self.btn_demo = QPushButton(self._icon("record"), "Démonstration")
        self.btn_demo.setIconSize(QSize(24, 24))
        self.btn_demo.setToolTip(f"Enregistrer une démonstration, après un compte à rebours")
        self.btn_demo.clicked.connect(self._view_model.demonstration)
        layout.addWidget(self.btn_demo)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.setFixedWidth(320)
        return scroll

    def _make_direct(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_etat = QLabel()
        self.lbl_etat.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_etat.setWordWrap(True)
        layout.addWidget(self.lbl_etat)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viewport = MujocoWidget()
        splitter.addWidget(self._viewport)
        capteurs = QWidget()
        self._capteurs_layout = QVBoxLayout(capteurs)
        self._capteurs_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._capteurs_scroll = QScrollArea()
        self._capteurs_scroll.setWidgetResizable(True)
        self._capteurs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._capteurs_scroll.setWidget(capteurs)
        self._capteurs_scroll.setMinimumWidth(350)
        splitter.addWidget(self._capteurs_scroll)
        splitter.setStretchFactor(0, 1)
        layout.addWidget(splitter, 1)
        return page

    def _make_revue(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.episode_view = EpisodeView()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.episode_view)
        layout.addWidget(scroll, 1)
        boutons = QHBoxLayout()
        self.btn_valider = QPushButton(self._icon("apply"), "Valider")
        self.btn_valider.setToolTip("Ajouter cette démonstration au dataset")
        self.btn_valider.clicked.connect(self._on_valider)
        boutons.addWidget(self.btn_valider)
        self.btn_recommencer = QPushButton(self._icon("remove"), "Recommencer")
        self.btn_recommencer.setToolTip("Ne pas garder cette démonstration ; la téléopération continue pour la refaire")
        self.btn_recommencer.clicked.connect(self._on_recommencer)
        boutons.addWidget(self.btn_recommencer)
        self.btn_fermer_revue = QPushButton(self._icon("close"), "Fermer")
        self.btn_fermer_revue.clicked.connect(self._fermer_revue)
        boutons.addWidget(self.btn_fermer_revue)
        boutons.addStretch(1)
        layout.addLayout(boutons)
        return page

    def _make_right(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(260)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        titre = QLabel("Épisodes")
        titre.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(titre)
        self.list_episodes = QListWidget()
        self.list_episodes.itemDoubleClicked.connect(lambda _: self._revoir())
        self.list_episodes.currentRowChanged.connect(lambda _: self._update_buttons())
        layout.addWidget(self.list_episodes, 1)
        self.lbl_sauvegarde = QLabel("Enregistrement de l'épisode…")
        self.lbl_sauvegarde.setStyleSheet(f"color: {theme.SLATE};")
        layout.addWidget(self.lbl_sauvegarde)
        self.btn_revoir = QPushButton(self._icon("eye_on"), "Revoir")
        self.btn_revoir.clicked.connect(self._revoir)
        layout.addWidget(self.btn_revoir)
        self.btn_supprimer = QPushButton(self._icon("remove"), "Supprimer")
        self.btn_supprimer.clicked.connect(self._supprimer)
        layout.addWidget(self.btn_supprimer)
        self.btn_visualiseur = QPushButton("Visualiseur LeRobot…")
        self.btn_visualiseur.setToolTip("Ouvrir l'épisode dans le visualiseur officiel de LeRobot (Rerun)")
        self.btn_visualiseur.clicked.connect(self._visualiseur)
        layout.addWidget(self.btn_visualiseur)
        return panel

    # ------------------------------------------------------------------ robot, simulation
    def set_simulation(self, simulation: bool):
        self._simulation = simulation
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
        current = self.cb_teleop.currentText()
        self.cb_teleop.clear()
        self.cb_teleop.addItems(self._view_model.teleops())
        self.cb_teleop.setCurrentIndex(max(0, self.cb_teleop.findText(current)))
        self._remplir_observations()
        self._remplir_datasets()

    def _remplir_observations(self, fmt: FormatDataset | None = None):
        """Cases des observations ; fmt : celles d'un dataset existant (imposées, non modifiables)."""
        while self._obs_layout.count():
            item = self._obs_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)       # retiré tout de suite (sinon visible jusqu'à sa destruction)
                item.widget().deleteLater()
        self._boxes = {}
        observables = self._view_model.observables()
        imposees = set(fmt.etat) | set(fmt.images) | set(fmt.tableaux) if fmt is not None else None
        # moteurs commandés en vitesse (roues) : c'est leur vitesse qui compte, pas leur position (sur un tour)
        en_vitesse = {a.rsplit(".", 1)[0] for a in self._view_model.actions() if a.endswith(".velocity")}
        for nom, prop in observables.items():
            box = QCheckBox(nom)
            if imposees is not None:
                box.setChecked(nom in imposees)
                box.setEnabled(False)
            else:
                # par défaut : les angles (vitesses des roues) et les capteurs installés (caméra, lidar)
                moteur, _, grandeur = nom.rpartition(".")
                attendu = "velocity" if moteur in en_vitesse else "position"
                box.setChecked(grandeur == attendu or est_capteur(prop))
            self._boxes[nom] = box
            self._obs_layout.addWidget(box)

    # ------------------------------------------------------------------ datasets
    def _dataset(self) -> DatasetMIR | None:
        return self.cb_dataset.currentData()

    def _remplir_datasets(self, choisir: str | None = None):
        courant = choisir or (self._dataset().nom if self._dataset() is not None else None)
        datasets = self._view_model.datasets()
        if self._nouveau is not None and all(d.nom != self._nouveau.nom for d in datasets):
            datasets.append(self._nouveau)
        self.cb_dataset.blockSignals(True)
        self.cb_dataset.clear()
        for ds in datasets:
            self.cb_dataset.addItem(ds.nom, ds)
        self.cb_dataset.addItem(NOUVEAU, None)
        index = next((i for i in range(self.cb_dataset.count() - 1) if self.cb_dataset.itemText(i) == courant), 0)
        self.cb_dataset.setCurrentIndex(index if datasets else -1)
        self.cb_dataset.blockSignals(False)
        self._on_dataset_change()

    def _on_dataset_choisi(self, index: int):
        if self.cb_dataset.itemText(index) != NOUVEAU:
            self._on_dataset_change()
            return
        nom, ok = QInputDialog.getText(self, "Nouveau dataset", "Nom du dataset (ex. de_dans_la_boite) :")
        nom = nom_valide(nom) if ok else ""
        ds = self._view_model.nouveau_dataset(nom) if nom else None
        if ds is not None:
            self._nouveau = ds
        self._remplir_datasets(ds.nom if ds is not None else None)

    def _on_dataset_change(self):
        ds = self._dataset()
        if ds is not None and ds.existe():
            episodes = ds.episodes()
            self.sp_fps.setValue(ds.fps())
            self.sp_fps.setEnabled(False)
            self._remplir_observations(ds.format())
            self.lbl_dataset.setText(f"{len(episodes)} épisode(s), {ds.fps()} Hz. Les observations et la fréquence "
                                     f"sont celles du dataset.\n{ds.dossier}")
            if episodes and not self.ed_tache.text():
                self.ed_tache.setText(episodes[-1].tache)
        else:
            episodes = []
            self.sp_fps.setEnabled(True)
            self._remplir_observations()
            self.lbl_dataset.setText("Nouveau dataset : choisissez les observations et la fréquence."
                                     if ds is not None else "Créez un dataset pour enregistrer des démonstrations.")
        self.list_episodes.clear()
        for e in episodes:
            reel = "simulé" if e.conditions.get("simulation") else "réel"
            item = QListWidgetItem(f"{e.index + 1}.  {e.duree_s:.1f} s · {reel}")
            item.setToolTip(f"{e.tache}\n{e.conditions.get('date', '')}\nTéléopération : {e.conditions.get('teleoperation', '?')}")
            self.list_episodes.addItem(item)
        self._update_buttons()

    def _format(self) -> FormatDataset:
        choisies = [nom for nom, box in self._boxes.items() if box.isChecked()]
        return FormatDataset.depuis_robot(self._view_model.observables(), choisies, self._view_model.actions())

    # ------------------------------------------------------------------ démonstrations
    def _on_demarrer(self):
        if self._dataset() is None:
            self._view_model._dialogProvider.information("Collecter des données", "Choisissez ou créez d'abord un dataset.")
            return
        self._installer_capteurs()
        self._view_model.demarrer(self.cb_teleop.currentText(), self._format(), self.sp_fps.value(), self.sp_duree.value())

    def _installer_capteurs(self):
        for w in self._capteurs.values():
            self._capteurs_layout.removeWidget(w)
            w.deleteLater()
        self._capteurs = {}
        for nom, prop in self._view_model.observables().items():
            if not (nom in self._boxes and self._boxes[nom].isChecked()):
                continue
            if isinstance(prop, ObservablePropertyBitmap):
                w = VideoWidget(nom, width=320, height=240)
                w.init_plot()
            elif isinstance(prop, ObservablePropertyPolar):
                w = PolarWidget(nom, prop.max_range, size=320)
            else:
                continue
            self._capteurs[nom] = w
            self._capteurs_layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._capteurs_scroll.setVisible(bool(self._capteurs))

    def _on_observation(self, observation: dict):
        for nom, w in self._capteurs.items():
            if observation.get(nom) is not None:
                w.update_plot(observation[nom])

    def _on_phase(self, phase: Phase, temps: float):
        textes = {
            Phase.ARRET: ("Démarrez la téléopération, mettez le robot en position de départ, puis ● Démonstration.", theme.TEXT_MUTED),
            Phase.LIBRE: ("Téléopération en cours, rien n'est enregistré : mettez le robot en position de départ, "
                          "puis ● Démonstration.", theme.SLATE),
            Phase.DECOMPTE: (f"Prêt… la démonstration commence dans {max(temps, 0):.0f} s", theme.WARNING),
            Phase.ENREGISTREMENT: (f"● ENREGISTREMENT   {temps:.1f} / {self.sp_duree.value():.0f} s", theme.REAL),
            Phase.REVUE: ("Démonstration terminée : revoyez-la, puis Valider ou Recommencer.", theme.SLATE),
        }
        texte, couleur = textes[phase]
        self.lbl_etat.setText(texte)
        self.lbl_etat.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {couleur}; padding: 6px;")
        self._update_buttons()

    def _on_episode_a_revoir(self, episode: dict):
        titre = "Démonstration à valider"
        if episode.get("manquees"):
            titre += (f"  ⚠ {episode['manquees']} mesure(s) ratée(s), remplacée(s) par la précédente : "
                      "recommencez si c'est trop")
        self.episode_view.montrer(episode, titre, self.sp_fps.value())
        self._mode_revue(nouvelle=True)

    def _mode_revue(self, nouvelle: bool):
        self.btn_valider.setVisible(nouvelle)
        self.btn_recommencer.setVisible(nouvelle)
        self.btn_fermer_revue.setVisible(not nouvelle)
        self._center.setCurrentIndex(1)

    def _fermer_revue(self):
        self.episode_view.arreter()
        self._center.setCurrentIndex(0)

    def _on_valider(self):
        ds = self._dataset()
        if ds is None:
            return
        self._view_model.valider(ds, self.ed_tache.text().strip() or "démonstration")
        if self._nouveau is not None and ds.nom == self._nouveau.nom:
            self._nouveau = None            # il existe maintenant sur le disque
        self._fermer_revue()

    def _on_recommencer(self):
        self._view_model.recommencer()
        self._fermer_revue()

    # ------------------------------------------------------------------ épisodes enregistrés
    def _revoir(self):
        ds, index = self._dataset(), self.list_episodes.currentRow()
        if ds is None or index < 0:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            episode = self._view_model.charger_episode(ds, index)
        finally:
            QApplication.restoreOverrideCursor()
        if episode is not None:
            self.episode_view.montrer(episode, f"{ds.nom} : épisode {index + 1}", ds.fps())
            self._mode_revue(nouvelle=False)

    def _supprimer(self):
        ds, index = self._dataset(), self.list_episodes.currentRow()
        if ds is None or index < 0:
            return
        dernier = self.list_episodes.count() == 1
        question = (f"Supprimer l'épisode {index + 1} ?" + ("\r\nC'est le dernier : le dataset entier sera supprimé."
                                                            if dernier else ""))
        if self._view_model._dialogProvider.question_yes_no("Supprimer un épisode", question):
            self._view_model.supprimer_episode(ds, index)

    def _visualiseur(self):
        ds, index = self._dataset(), self.list_episodes.currentRow()
        if ds is not None and index >= 0:
            self._view_model.ouvrir_visualiseur(ds, index)

    # ------------------------------------------------------------------ boutons
    def _update_buttons(self):
        vm = self._view_model
        en_cours = vm.is_running()
        phase = vm.phase()
        sauvegarde = vm.sauvegarde_en_cours()
        self.btn_demarrer.setEnabled(not en_cours and vm.has_robot() and self.cb_teleop.count() > 0
                                     and phase != Phase.REVUE)
        self.btn_arreter.setEnabled(en_cours)
        self.btn_demo.setEnabled(en_cours and phase == Phase.LIBRE and not sauvegarde)
        self.btn_valider.setEnabled(not sauvegarde)
        for w in (self.cb_dataset, self.cb_teleop, self.sp_duree, self.ed_tache):
            w.setEnabled(not en_cours and phase != Phase.REVUE)
        if en_cours or phase == Phase.REVUE:
            self.sp_fps.setEnabled(False)
            for box in self._boxes.values():
                box.setEnabled(False)
        elif self._dataset() is None or not self._dataset().existe():
            self.sp_fps.setEnabled(True)
            for box in self._boxes.values():
                box.setEnabled(True)
        a_un_episode = self.list_episodes.currentRow() >= 0
        for w in (self.btn_revoir, self.btn_supprimer, self.btn_visualiseur):
            w.setEnabled(a_un_episode and not sauvegarde)
        self.btn_supprimer.setEnabled(a_un_episode and not sauvegarde and not en_cours)
        self.lbl_sauvegarde.setVisible(sauvegarde)
