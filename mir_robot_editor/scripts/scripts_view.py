"""
Étape Piloter → Scripts : un petit environnement de programmation. À gauche les scripts du robot et les noms de ses
mesures et consignes, au centre l'éditeur et la console, à droite le robot simulé en 3D.
"""
from __future__ import annotations
import re
from pathlib import Path
from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QImage, QKeySequence, QPixmap, QShortcut, QTextCharFormat,
                           QTextCursor)
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QSplitter, QTabBar, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_robot_editor.scripts.scripts_view_model import ScriptsViewModel, ScriptsVMAction
from mir_utils.ui.code_editor import PythonCodeEditor
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui.widgets import ToolButton
from mir_utils.ui import theme

LIGNE_TRACEBACK = re.compile(r'File "([^"]+)", line (\d+)')


class ImageFigure(QLabel):
    """Une figure matplotlib du script, réduite si besoin pour tenir dans la zone (proportions gardées)."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(100, 80)
        self._pixmap: QPixmap | None = None

    def pixmap_complet(self) -> QPixmap | None:
        return self._pixmap

    def set_image(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._ajuster()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajuster()

    def _ajuster(self):
        if self._pixmap is None:
            return
        ratio = self._pixmap.devicePixelRatio()
        taille = self._pixmap.size() / ratio
        if taille.width() <= self.width() and taille.height() <= self.height():
            self.setPixmap(self._pixmap)
            return
        cible = taille.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio) * ratio
        reduite = self._pixmap.scaled(cible, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        reduite.setDevicePixelRatio(ratio)
        self.setPixmap(reduite)


class ZoneFigures(QTabWidget):
    """Les figures du script (plt.plot...), une par onglet."""

    def __init__(self, dossier):
        super().__init__()
        self.setDocumentMode(True)
        self._dossier = dossier         # dossier proposé pour enregistrer une figure
        self._figures: dict[int, ImageFigure] = {}
        self._btn_enregistrer = ToolButton("save", self._enregistrer, False, "Enregistrer la figure affichée (image PNG)",
                                           size=20)
        self.setCornerWidget(self._btn_enregistrer, Qt.Corner.TopRightCorner)
        self.currentChanged.connect(lambda _: self._btn_enregistrer.setEnabled(
            isinstance(self.currentWidget(), ImageFigure)))
        self._vide = QLabel("Les figures du script (plt.plot, plt.imshow…) s'affichent ici\n"
                            "avec plt.show(), plt.pause(…) ou à la fin du script.")
        self._vide.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vide.setWordWrap(True)
        self._vide.setStyleSheet("color: palette(placeholder-text);")
        self.effacer()

    def effacer(self):
        self.clear()
        for figure in self._figures.values():
            figure.deleteLater()
        self._figures = {}
        self.addTab(self._vide, "Figures")

    def afficher(self, numero: int, titre: str, largeur: int, hauteur: int, rgba: bytes):
        image = QImage(rgba, largeur, hauteur, 4 * largeur, QImage.Format.Format_RGBA8888).copy()
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        figure = self._figures.get(numero)
        if figure is None:
            if self.indexOf(self._vide) >= 0:
                self.removeTab(self.indexOf(self._vide))
            figure = self._figures[numero] = ImageFigure()
            self.setCurrentIndex(self.addTab(figure, titre))
        self.setTabText(self.indexOf(figure), titre)
        figure.set_image(pixmap)
        self._btn_enregistrer.setEnabled(isinstance(self.currentWidget(), ImageFigure))

    def _enregistrer(self):
        figure = self.currentWidget()
        if not isinstance(figure, ImageFigure) or figure.pixmap_complet() is None:
            return
        titre = re.sub(r"[^\w\- ]+", "_", self.tabText(self.currentIndex())).strip() or "figure"
        dossier = self._dossier()
        defaut = str(dossier / f"{titre}.png") if dossier is not None else f"{titre}.png"
        chemin, _ = QFileDialog.getSaveFileName(self, "Enregistrer la figure", defaut, "Image PNG (*.png)")
        if chemin:
            figure.pixmap_complet().save(chemin if chemin.lower().endswith(".png") else chemin + ".png", "PNG")


class ScriptsView(QWidget, ViewBase[ScriptsViewModel, ScriptsVMAction]):
    def __init__(self, parent, view_model: ScriptsViewModel):
        super().__init__(parent, view_model=view_model)  # type: ignore
        vm = self._view_model
        vm.busy_state_changed.connect(self._on_busy_changed)
        vm.robot_changed.connect(self._on_robot_changed)
        vm.dossier_changed.connect(self._on_dossier_changed)
        vm.sortie.connect(self._ecrire)
        vm.script_termine.connect(self._on_script_termine)
        vm.figure_recue.connect(lambda *args: self.figures.afficher(*args))
        self._editeurs: dict[Path, PythonCodeEditor] = {}
        self._erreurs = ""              # sortie d'erreur du script en cours, pour retrouver la ligne en cause
        self._tampon: list[tuple[str, bool]] = []       # texte du script pas encore affiché dans la console
        self._timer_console = QTimer(self)
        self._timer_console.setSingleShot(True)
        self._timer_console.setInterval(50)
        self._timer_console.timeout.connect(self._vider_tampon)
        self._simulation = False
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _: self._remplir_fichiers())
        self._watcher.fileChanged.connect(self._on_fichier_modifie_ailleurs)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.addWidget(self._make_left())
        self._splitter.addWidget(self._make_center())
        droite = QSplitter(Qt.Orientation.Vertical)
        self._viewport = MujocoWidget()
        droite.addWidget(self._viewport)                         # robot simulé : vue 3D
        self.figures = ZoneFigures(self._view_model.dossier)
        droite.addWidget(self.figures)                           # figures du script
        droite.setStretchFactor(0, 2)
        droite.setStretchFactor(1, 3)
        droite.setSizes([400, 600])
        self._splitter.addWidget(droite)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([250, 650, 550])
        root.addWidget(self._splitter)
        self._timer_3d = QTimer(self)
        self._timer_3d.setInterval(33)
        self._timer_3d.timeout.connect(self._viewport.update)

        save = QShortcut(QKeySequence.StandardKey.Save, self, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        save.activated.connect(self.enregistrer)

        self._on_dossier_changed()
        self._on_robot_changed()
        self._on_busy_changed(False)

    # ------------------------------------------------------------------ construction
    def _make_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        titre = QHBoxLayout()
        label = QLabel("Scripts du robot")
        label.setStyleSheet("font-weight: bold;")
        titre.addWidget(label, 1)
        titre.addWidget(ToolButton("folder-open", self._ouvrir_dossier, True,
                                   "Ouvrir le dossier des scripts (pour les modifier aussi avec un autre éditeur)"))
        layout.addLayout(titre)
        self.list_fichiers = QListWidget()
        self.list_fichiers.itemActivated.connect(lambda item: self.ouvrir(Path(item.data(Qt.ItemDataRole.UserRole))))
        self.list_fichiers.itemClicked.connect(lambda item: self.ouvrir(Path(item.data(Qt.ItemDataRole.UserRole))))
        layout.addWidget(self.list_fichiers, 1)
        self.btn_nouveau = QPushButton(self._icon("new"), "Nouveau script…")
        self.btn_nouveau.clicked.connect(self._on_nouveau)
        layout.addWidget(self.btn_nouveau)

        label = QLabel("Nom des variables")
        label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(label)
        aide = QLabel("Double-clic : insérer le nom dans le script.")
        aide.setWordWrap(True)
        aide.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(aide)
        self.tree_noms = QTreeWidget()
        self.tree_noms.setHeaderHidden(True)
        self.tree_noms.itemDoubleClicked.connect(self._inserer_nom)
        layout.addWidget(self.tree_noms, 1)
        return panel

    def _make_center(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)
        barre = QHBoxLayout()
        self.btn_lancer = QPushButton(self._icon("play"), "Lancer")
        self.btn_lancer.setIconSize(QSize(22, 22))
        self.btn_lancer.setToolTip("Enregistrer puis lancer le script affiché")
        self.btn_lancer.clicked.connect(self._on_lancer)
        barre.addWidget(self.btn_lancer)
        self.btn_arreter = QPushButton(self._icon("stop"), "Arrêter")
        self.btn_arreter.setIconSize(QSize(22, 22))
        self.btn_arreter.clicked.connect(self._view_model.arreter)
        barre.addWidget(self.btn_arreter)
        barre.addStretch(1)
        self.btn_enregistrer = QPushButton(self._icon("save"), "Enregistrer")
        self.btn_enregistrer.setToolTip("Enregistrer le script affiché (Ctrl+S)")
        self.btn_enregistrer.clicked.connect(self.enregistrer)
        barre.addWidget(self.btn_enregistrer)
        layout.addLayout(barre)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._fermer_onglet)
        self.tabs.currentChanged.connect(lambda _: self._update_buttons())
        self._accueil = QLabel("Choisissez un script dans la liste à gauche, ou créez-en un avec « Nouveau script… ».")
        self._accueil.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._accueil.setStyleSheet("color: palette(placeholder-text);")
        self.tabs.addTab(self._accueil, "Bienvenue")
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        splitter.addWidget(self.tabs)

        console = QWidget()
        console_layout = QVBoxLayout(console)
        console_layout.setContentsMargins(0, 0, 0, 0)
        entete = QHBoxLayout()
        label = QLabel("Console")
        label.setStyleSheet("font-weight: bold;")
        entete.addWidget(label, 1)
        entete.addWidget(ToolButton("remove", lambda: self.console.clear(), True, "Effacer la console", size=18))
        console_layout.addLayout(entete)
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(5000)        # un print dans une boucle rapide ne doit pas saturer l'appli
        font = QFont()
        font.setFamilies(theme.MONO_FAMILIES)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.console.setFont(font)
        console_layout.addWidget(self.console)
        splitter.addWidget(console)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        return panel

    # ------------------------------------------------------------------ robot et simulation
    def set_simulation(self, simulation: bool):
        self._simulation = simulation
        self._update_3d()

    def _update_3d(self):
        world = self._view_model.sim_world() if self._simulation else None
        self._viewport.setVisible(self._simulation)
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
        observations, actions = self._view_model.noms()
        self.tree_noms.clear()
        for titre, noms, tip in (("Mesures : robot.get_observation(…)", observations, "mesure"),
                                 ("Consignes : robot.send_action({…})", actions, "consigne")):
            parent = QTreeWidgetItem([titre])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for nom in noms:
                item = QTreeWidgetItem([nom])
                item.setToolTip(0, f"{tip} : double-clic pour insérer \"{nom}\"")
                parent.addChild(item)
            self.tree_noms.addTopLevelItem(parent)
            parent.setExpanded(True)
        if not observations and not actions:
            self.tree_noms.clear()
            self.tree_noms.addTopLevelItem(QTreeWidgetItem(["Pas de robot connecté"]))
        self._update_buttons()

    def _inserer_nom(self, item: QTreeWidgetItem, _column: int):
        editeur = self._editeur_courant()
        if editeur is None or item.parent() is None:
            return
        editeur.textCursor().insertText(f'"{item.text(0)}"')
        editeur.setFocus()

    # ------------------------------------------------------------------ fichiers
    def _on_dossier_changed(self):
        self.enregistrer_tout()         # autre robot : ses scripts remplacent ceux ouverts
        for chemin in list(self._editeurs):
            self._fermer_onglet(self.tabs.indexOf(self._editeurs[chemin]), forcer=True)
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        dossier = self._view_model.dossier()
        if dossier is not None:
            dossier.mkdir(parents=True, exist_ok=True)
            self._watcher.addPath(str(dossier))
        self._remplir_fichiers()
        self._update_buttons()

    def _remplir_fichiers(self):
        self.list_fichiers.clear()
        if self._view_model.dossier() is None:
            item = QListWidgetItem("Enregistrez le robot pour écrire des scripts")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_fichiers.addItem(item)
            return
        for fichier in self._view_model.fichiers():
            item = QListWidgetItem(self._icon("execute"), fichier.name)
            item.setData(Qt.ItemDataRole.UserRole, str(fichier))
            item.setToolTip(str(fichier))
            self.list_fichiers.addItem(item)

    def _ouvrir_dossier(self):
        dossier = self._view_model.dossier()
        if dossier is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dossier)))

    def _on_nouveau(self):
        nom, ok = QInputDialog.getText(self, "Nouveau script", "Nom du script (ex. « Asservissement en position ») :")
        if not ok or not nom.strip():
            return
        fichier = self._view_model.nouveau(nom.strip())
        if fichier is not None:
            self._remplir_fichiers()
            self.ouvrir(fichier)

    def ouvrir(self, fichier: Path) -> PythonCodeEditor | None:
        if fichier in self._editeurs:
            self.tabs.setCurrentWidget(self._editeurs[fichier])
            return self._editeurs[fichier]
        try:
            texte = fichier.read_text(encoding="utf-8")
        except OSError as e:
            self._ecrire(f"Impossible d'ouvrir {fichier.name} : {e}\n", True)
            return None
        editeur = PythonCodeEditor()
        editeur.setTheme("light")
        editeur.setLineWrapMode(PythonCodeEditor.LineWrapMode.NoWrap)     # numéros de ligne = lignes du fichier
        editeur.setPlainText(texte)
        editeur.document().setModified(False)
        editeur.textChanged.connect(editeur.clearErrorLine)
        editeur.document().modificationChanged.connect(lambda _: self._update_titre(fichier))
        self._editeurs[fichier] = editeur
        if self.tabs.indexOf(self._accueil) >= 0:
            self.tabs.removeTab(self.tabs.indexOf(self._accueil))
        index = self.tabs.addTab(editeur, fichier.name)
        self.tabs.setTabToolTip(index, str(fichier))
        self.tabs.setCurrentIndex(index)
        self._watcher.addPath(str(fichier))
        return editeur

    def _update_titre(self, fichier: Path):
        editeur = self._editeurs.get(fichier)
        if editeur is not None:
            modifie = "● " if editeur.document().isModified() else ""
            self.tabs.setTabText(self.tabs.indexOf(editeur), modifie + fichier.name)

    def _fichier_courant(self) -> Path | None:
        widget = self.tabs.currentWidget()
        return next((f for f, e in self._editeurs.items() if e is widget), None)

    def _editeur_courant(self) -> PythonCodeEditor | None:
        fichier = self._fichier_courant()
        return self._editeurs.get(fichier) if fichier is not None else None

    def _enregistrer_fichier(self, fichier: Path) -> bool:
        editeur = self._editeurs[fichier]
        if not editeur.document().isModified():
            return True
        try:
            fichier.write_text(editeur.toPlainText(), encoding="utf-8")
        except OSError as e:
            self._ecrire(f"Impossible d'enregistrer {fichier.name} : {e}\n", True)
            return False
        editeur.document().setModified(False)
        return True

    def enregistrer(self):
        fichier = self._fichier_courant()
        if fichier is not None:
            self._enregistrer_fichier(fichier)

    def _fermer_onglet(self, index: int, forcer: bool = False):
        widget = self.tabs.widget(index)
        fichier = next((f for f, e in self._editeurs.items() if e is widget), None)
        if fichier is None:
            return
        if not forcer and widget.document().isModified():
            reponse = self._view_model._dialogProvider.question_yes_no(
                "Fermer le script", f"{fichier.name} a été modifié.\r\nEnregistrer les modifications ?")
            if reponse and not self._enregistrer_fichier(fichier):
                return
        self.tabs.removeTab(index)
        del self._editeurs[fichier]
        self._watcher.removePath(str(fichier))
        widget.deleteLater()
        if self.tabs.count() == 0:
            self.tabs.addTab(self._accueil, "Bienvenue")
            self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)

    def _on_fichier_modifie_ailleurs(self, chemin: str):
        """Fichier modifié avec un autre éditeur : relu s'il n'a pas de modification en cours ici."""
        fichier = Path(chemin)
        editeur = self._editeurs.get(fichier)
        if editeur is None:
            return
        if not fichier.exists():
            return
        self._watcher.addPath(chemin)       # certains éditeurs remplacent le fichier : il faut le resurveiller
        texte = fichier.read_text(encoding="utf-8")
        if texte == editeur.toPlainText():
            return
        if editeur.document().isModified():
            self._ecrire(f"{fichier.name} a été modifié en dehors de MIR, mais vos modifications ici n'ont pas été "
                         f"enregistrées : il n'a pas été relu.\n", True)
            return
        position = editeur.textCursor().position()
        editeur.setPlainText(texte)
        editeur.document().setModified(False)
        cursor = editeur.textCursor()
        cursor.setPosition(min(position, len(texte)))
        editeur.setTextCursor(cursor)

    # ------------------------------------------------------------------ exécution
    def _on_lancer(self):
        fichier = self._fichier_courant()
        if fichier is None:
            return
        for f in list(self._editeurs):
            if not self._enregistrer_fichier(f):
                return
        for editeur in self._editeurs.values():
            editeur.clearErrorLine()
        self.console.clear()
        self._tampon = []
        self._erreurs = ""
        self._ecrire_info(f"▶ {fichier.name} ({'robot simulé' if self._simulation else 'robot réel'})")
        self.figures.effacer()
        # figures à la taille de la zone qui les affiche, nettes sur un écran haute définition
        zone = self.figures.size()
        ratio = self.devicePixelRatioF()
        self._view_model.lancer(fichier, (zone.width() - 10, zone.height() - 40), 100 * ratio)

    def _on_script_termine(self, message: str):
        self._ecrire_info(f"■ {message}")
        self._montrer_ligne_erreur()

    def _montrer_ligne_erreur(self):
        """Erreur dans un des scripts du robot : on ouvre le fichier sur la ligne en cause."""
        dossier = self._view_model.dossier()
        if not self._erreurs or dossier is None:
            return
        for chemin, ligne in reversed(LIGNE_TRACEBACK.findall(self._erreurs)):
            fichier = Path(chemin)
            if fichier.exists() and fichier.resolve().parent == dossier.resolve():
                editeur = self.ouvrir(fichier)
                if editeur is None:
                    return
                editeur.setErrorLine(int(ligne))
                bloc = editeur.document().findBlockByNumber(int(ligne) - 1)
                cursor = editeur.textCursor()
                cursor.setPosition(bloc.position())
                editeur.setTextCursor(cursor)
                editeur.centerCursor()
                return

    def _ecrire(self, texte: str, erreur: bool):
        """Texte du script : regroupé et affiché 20 fois par seconde (un print à chaque tour d'une boucle
        rapide saturerait l'interface)."""
        if erreur:
            self._erreurs += texte
        if self._tampon and self._tampon[-1][1] == erreur:
            self._tampon[-1] = (self._tampon[-1][0] + texte, erreur)
        else:
            self._tampon.append((texte, erreur))
        if not self._timer_console.isActive():
            self._timer_console.start()

    def _vider_tampon(self):
        tampon, self._tampon = self._tampon, []
        if not tampon:
            return
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for texte, erreur in tampon:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(theme.ERROR if erreur else theme.TEXT))
            cursor.insertText(texte, fmt)
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    def _ecrire_info(self, texte: str):
        self._vider_tampon()
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(theme.SLATE))
        if not self.console.document().isEmpty() and not self.console.toPlainText().endswith("\n"):
            cursor.insertText("\n")
        cursor.insertText(texte + "\n", fmt)
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    def _on_busy_changed(self, busy: bool):
        self._update_buttons()

    def _update_buttons(self):
        busy = self._view_model.is_running()
        a_un_script = self._fichier_courant() is not None
        self.btn_lancer.setEnabled(not busy and a_un_script and self._view_model.has_robot())
        self.btn_lancer.setToolTip("Enregistrer puis lancer le script affiché" if self._view_model.has_robot() else
                                   "Pas de robot : connectez le robot réel, ou utilisez le robot simulé")
        self.btn_arreter.setEnabled(busy)
        self.btn_nouveau.setEnabled(self._view_model.dossier() is not None)
        self.btn_enregistrer.setEnabled(a_un_script)

    def a_des_modifications(self) -> bool:
        return any(e.document().isModified() for e in self._editeurs.values())

    def enregistrer_tout(self):
        for fichier in list(self._editeurs):
            self._enregistrer_fichier(fichier)
