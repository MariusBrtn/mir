"""
Étape « Entraîner un modèle » : à gauche le dataset, les scripts d'entraînement et les modèles entraînés ; au centre
l'éditeur et la console ; à droite les figures du script (courbes de loss). Même fonctionnement que Piloter → Scripts.
"""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)
from mir_robot_editor.entrainement.entrainement_view_model import (EntrainementViewModel, LEROBOT, PYTORCH, TYPES,
                                                                   besoin_dataset)
from mir_robot_editor.scripts.scripts_view import ScriptsView
from mir_utils.ui.widgets import ToolButton


class EntrainementView(ScriptsView):
    def __init__(self, parent, view_model: EntrainementViewModel):
        super().__init__(parent, view_model)
        view_model.datasets_changed.connect(self._remplir_datasets)
        view_model.modeles_changed.connect(self._remplir_modeles)
        self._viewport.setVisible(False)            # pas de robot ici : la colonne de droite est aux figures
        self.btn_lancer.setText("Entraîner")
        self._accueil.setText("Choisissez un script d'entraînement à gauche, ou créez-en un avec « Nouveau… ».")
        self._remplir_datasets()
        self._remplir_modeles()

    # ------------------------------------------------------------------ construction
    def _make_left(self) -> QWidget:
        panel = QWidget()
        colonne = QVBoxLayout(panel)
        colonne.setContentsMargins(10, 4, 6, 8)

        box = QGroupBox("Dataset")
        layout = QVBoxLayout(box)
        self.cb_dataset = QComboBox()
        self.cb_dataset.activated.connect(self._on_dataset_choisi)
        layout.addWidget(self.cb_dataset)
        self.lbl_dataset = QLabel()
        self.lbl_dataset.setWordWrap(True)
        self.lbl_dataset.setObjectName("Muted")
        layout.addWidget(self.lbl_dataset)
        colonne.addWidget(box)

        box = QGroupBox("Scripts d'entraînement")
        layout = QVBoxLayout(box)
        self.list_fichiers = QListWidget()
        self.list_fichiers.itemActivated.connect(lambda item: self.ouvrir(Path(item.data(Qt.ItemDataRole.UserRole))))
        self.list_fichiers.itemClicked.connect(lambda item: self.ouvrir(Path(item.data(Qt.ItemDataRole.UserRole))))
        layout.addWidget(self.list_fichiers, 1)
        ligne = QHBoxLayout()
        self.btn_nouveau = QPushButton(self._icon("new"), "Nouveau…")
        self.btn_nouveau.clicked.connect(self._on_nouveau)
        ligne.addWidget(self.btn_nouveau, 1)
        ligne.addWidget(ToolButton("folder-open", self._ouvrir_dossier, True,
                                   "Ouvrir le dossier des modèles (scripts et modèles entraînés)"))
        layout.addLayout(ligne)
        colonne.addWidget(box, 1)

        box = QGroupBox("Modèles entraînés")
        layout = QVBoxLayout(box)
        aide = QLabel("Ils se choisissent dans Piloter → IA.")
        aide.setObjectName("Muted")
        layout.addWidget(aide)
        self.list_modeles = QListWidget()
        self.list_modeles.currentItemChanged.connect(lambda *_: self._update_buttons())
        layout.addWidget(self.list_modeles, 1)
        boutons = QHBoxLayout()
        self.btn_dossier_modele = QPushButton(self._icon("folder-open"), "Dossier")
        self.btn_dossier_modele.setToolTip("Ouvrir le dossier du modèle (poids, préparation, copie du script)")
        self.btn_dossier_modele.clicked.connect(self._ouvrir_modele)
        boutons.addWidget(self.btn_dossier_modele)
        self.btn_supprimer_modele = QPushButton(self._icon("remove"), "Supprimer")
        self.btn_supprimer_modele.clicked.connect(self._supprimer_modele)
        boutons.addWidget(self.btn_supprimer_modele)
        layout.addLayout(boutons)
        colonne.addWidget(box, 1)
        return panel

    # ------------------------------------------------------------------ pas de robot ici
    def set_simulation(self, simulation: bool):
        pass

    def _update_3d(self):
        self._viewport.setVisible(False)

    def _on_robot_changed(self):
        self._update_buttons()

    # ------------------------------------------------------------------ datasets et modèles
    def _remplir_datasets(self):
        vm: EntrainementViewModel = self._view_model
        self.cb_dataset.clear()
        for ds in vm.datasets():
            self.cb_dataset.addItem(ds.nom)
        courant = vm.dataset()
        self.cb_dataset.setCurrentIndex(self.cb_dataset.findText(courant.nom) if courant is not None else -1)
        self.cb_dataset.setEnabled(self.cb_dataset.count() > 0)
        self.lbl_dataset.setText(vm.resume_dataset())
        self._update_buttons()

    def _on_dataset_choisi(self, index: int):
        self._view_model.set_dataset(self.cb_dataset.itemText(index))
        self.lbl_dataset.setText(self._view_model.resume_dataset())
        self._update_buttons()

    def _remplir_modeles(self):
        self.list_modeles.clear()
        for info in self._view_model.modeles():
            texte = f"{info['name']} · {info.get('kind', '?')}\n{info['date']}"
            if info.get("inputs"):
                texte += f" · {', '.join(info['inputs'])}"
            item = QListWidgetItem(self._icon("robot"), texte)
            item.setData(Qt.ItemDataRole.UserRole, info["folder"])
            item.setToolTip(f"{info['folder']}\ndataset : {info.get('dataset') or '?'}" +
                            (f"\n{info['error']}" if info.get("error") else ""))
            self.list_modeles.addItem(item)
        self._update_buttons()

    def _modele_choisi(self) -> str | None:
        item = self.list_modeles.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _ouvrir_modele(self):
        dossier = self._modele_choisi()
        if dossier is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(dossier))

    def _supprimer_modele(self):
        dossier = self._modele_choisi()
        if dossier is not None:
            self._view_model.supprimer_modele(dossier)

    # ------------------------------------------------------------------ scripts
    def _on_nouveau(self):
        types = list(TYPES.values())
        genre, ok = QInputDialog.getItem(self, "Nouveau script d'entraînement", "Modèle :", types, 0, False)
        if not ok:
            return
        nom, ok = QInputDialog.getText(self, "Nouveau script d'entraînement",
                                       "Nom du script (ex. « CNN ramassage », « ACT insertion ») :")
        if not ok or not nom.strip():
            return
        fichier = self._view_model.nouveau(nom.strip(), LEROBOT if genre == TYPES[LEROBOT] else PYTORCH)
        if fichier is not None:
            self._remplir_fichiers()
            self.ouvrir(fichier)

    def _on_lancer(self):
        dataset = self._view_model.dataset() if besoin_dataset(self._fichier_courant()) else None
        super()._on_lancer()
        if dataset is not None and self._view_model.is_running():
            self._ecrire_info(f"   dataset : {dataset.nom}")

    def _ecrire_info(self, texte: str):
        # l'onglet Scripts parle du robot réel ou simulé : ici, seul le dataset compte
        super()._ecrire_info(texte.replace(" (robot simulé)", "").replace(" (robot réel)", ""))

    def _update_buttons(self):
        if not hasattr(self, "list_modeles"):
            return          # appelé pendant la construction
        vm: EntrainementViewModel = self._view_model
        busy = vm.is_running()
        a_un_script = self._fichier_courant() is not None
        sans_dataset = a_un_script and not besoin_dataset(self._fichier_courant())
        self.btn_lancer.setEnabled(not busy and a_un_script and (sans_dataset or vm.dataset() is not None))
        self.btn_lancer.setToolTip("Enregistrer puis lancer l'entraînement affiché (en simulation, sans dataset)"
                                   if sans_dataset else
                                   "Enregistrer puis lancer l'entraînement affiché, sur le dataset choisi"
                                   if vm.dataset() is not None else "Choisissez d'abord un dataset")
        self.btn_arreter.setEnabled(busy)
        self.btn_nouveau.setEnabled(vm.dossier() is not None)
        self.btn_enregistrer.setEnabled(a_un_script)
        choisi = self._modele_choisi() is not None
        self.btn_dossier_modele.setEnabled(choisi)
        self.btn_supprimer_modele.setEnabled(choisi and not busy)
