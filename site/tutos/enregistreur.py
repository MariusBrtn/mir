"""
Filme la vraie application MIR, pilotée par un scénario (voir enregistrer_tuto.py).

Chaque image est une capture de la fenêtre principale, avec par-dessus les fenêtres ouvertes (éditeur de structure,
petites fenêtres de saisie...), un faux curseur et une légende. Le temps est « virtuel » (30 images/s, la vidéo est
fluide même si le rendu est lent), sauf quand le robot bouge (essai, script) : on suit alors le temps réel.
"""
from __future__ import annotations
import shutil
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QLineEdit, QMessageBox, QPlainTextEdit,
                               QToolBar, QWidget)

from mir_robot_editor.robot_model.structure_editor_view import KEY_ROLE, StructureEditorView
from mir_utils.ui import theme
from mir_utils.ui.dialogs import QtDialogProvider
from mir_utils.ui.widgets import AskDialog

FPS = 30


def lisse(t: float) -> float:
    """Départ et arrivée en douceur."""
    return t * t * (3 - 2 * t)


class Enregistreur:
    """Pilote la fenêtre principale (et les fenêtres ouvertes par-dessus) et capture chaque image."""

    def __init__(self, app: QApplication, fenetre: QWidget, dossier_images: Path):
        self.app = app
        self.principale = fenetre
        self.dossier = dossier_images
        self.n_images = 0
        self.fenetres: list[QWidget] = []        # fenêtres ouvertes par-dessus la principale, la dernière devant
        self.coins: dict[QWidget, QPoint] = {}  # fenêtres placées ailleurs qu'au centre
        self.curseur = QPointF(fenetre.width() * 0.55, fenetre.height() * 0.45)
        self.vignette: QPixmap | None = None     # module en cours de glisser
        self.legende = ""
        self.touche = ""                         # touche du clavier affichée (ex. « R »)
        self.onde: tuple[QPointF, float] | None = None   # clic : position, avancement 0..1
        self.reponses: list[tuple[str, object]] = []     # réponses prévues aux fenêtres de MIR : (titre, réponse)
        self.vue: StructureEditorView | None = None      # éditeur de structure ouvert
        self.filme = True                        # False : les gestes sont joués sans être filmés
        self.curseur_visible = True
        self.carte: tuple[str, str, float] | None = None  # carte de titre : titre, sous-titre, opacité 0..1

    # ------------------------------------------------------------------ capture
    def _position(self, fenetre: QWidget) -> QPoint:
        """Coin haut gauche d'une fenêtre ouverte par-dessus : centrée sur la fenêtre principale, sauf si placée."""
        if fenetre in self.coins:
            return self.coins[fenetre]
        return QPoint((self.principale.width() - fenetre.width()) // 2,
                      (self.principale.height() - fenetre.height()) // 2)

    def image(self) -> None:
        self.app.processEvents()
        if not self.filme:
            return
        image = self.principale.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for fenetre in self.fenetres:
            if fenetre not in self.coins:          # fenêtre modale : le reste est assombri
                painter.fillRect(image.rect(), QColor(20, 20, 23, 70))
            coin = self._position(fenetre)
            ombre = QPainterPath()
            ombre.addRoundedRect(QRectF(coin.x() + 2, coin.y() + 6, fenetre.width(), fenetre.height()), 10, 10)
            painter.fillPath(ombre, QColor(0, 0, 0, 60))
            painter.drawPixmap(coin, fenetre.grab())
        self._dessiner_surimpression(painter)
        painter.end()
        image.save(str(self.dossier / f"{self.n_images:05d}.png"), "PNG", 100)
        self.n_images += 1

    def _repeter_image(self) -> None:
        if not self.filme:
            return
        shutil.copy(self.dossier / f"{self.n_images - 1:05d}.png", self.dossier / f"{self.n_images:05d}.png")
        self.n_images += 1

    def _dessiner_surimpression(self, p: QPainter) -> None:
        if self.onde is not None:
            centre, t = self.onde
            p.setPen(QPen(QColor(90, 107, 133, int(220 * (1 - t))), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(centre, 8 + 22 * t, 8 + 22 * t)
        if self.vignette is not None:
            p.setOpacity(0.85)
            p.drawPixmap(self.curseur + QPointF(10, 10), self.vignette)
            p.setOpacity(1)
        # flèche de souris
        x, y = self.curseur.x(), self.curseur.y()
        fleche = QPolygonF([QPointF(x, y), QPointF(x, y + 20), QPointF(x + 5, y + 15), QPointF(x + 9, y + 23),
                            QPointF(x + 12, y + 21), QPointF(x + 8, y + 14), QPointF(x + 14, y + 14)])
        if self.curseur_visible:
            p.setPen(QPen(QColor(theme.INK), 1.4))
            p.setBrush(QColor("white"))
            p.drawPolygon(fleche)
        if self.carte is not None:
            self._carte(p, *self.carte)
            return
        if self.legende:
            self._bulle(p, self.legende)
        if self.touche:
            self._touche(p, self.touche)

    def _bulle(self, p: QPainter, texte: str) -> None:
        font = QFont(theme.first_family(theme.FONT_FAMILIES) or "", 17)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        largeur = p.fontMetrics().horizontalAdvance(texte) + 40
        rect = QRectF((self.principale.width() - largeur) / 2, self.principale.height() - 78, largeur, 48)
        chemin = QPainterPath()
        chemin.addRoundedRect(rect, 10, 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(chemin, QColor(20, 20, 23, 230))
        p.setPen(QColor(theme.SAND))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, texte)

    def _carte(self, p: QPainter, titre: str, sous_titre: str, opacite: float) -> None:
        """Carte de titre : fond noir sur toute l'image, titre en sable."""
        p.setOpacity(opacite)
        p.fillRect(QRectF(0, 0, self.principale.width(), self.principale.height()), QColor(theme.INK))
        haut = QRectF(0, 0, self.principale.width(), self.principale.height() / 2 + 10)
        font = QFont(theme.first_family(theme.FONT_FAMILIES) or "", 54)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor(theme.SAND))
        p.drawText(haut, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, titre)
        bas = QRectF(0, self.principale.height() / 2 + 30, self.principale.width(), 80)
        font.setPointSize(22)
        font.setWeight(QFont.Weight.Normal)
        p.setFont(font)
        p.setPen(QColor("#F2EDE4"))
        p.drawText(bas, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, sous_titre)
        p.setOpacity(1)

    def carte_titre(self, titre: str, sous_titre: str, secondes: float, fondu_entree: bool = True,
                    fondu_sortie: bool = True, fondu_s: float = 0.5) -> None:
        """Affiche une carte de titre, avec fondu à l'entrée et à la sortie."""
        n_fondu = round(fondu_s * FPS)
        if fondu_entree:
            for i in range(1, n_fondu + 1):
                self.carte = (titre, sous_titre, i / n_fondu)
                self.image()
        self.carte = (titre, sous_titre, 1.0)
        self.attendre(secondes)
        if fondu_sortie:
            for i in range(n_fondu - 1, -1, -1):
                self.carte = (titre, sous_titre, i / n_fondu)
                self.image()
        self.carte = None

    def _touche(self, p: QPainter, texte: str) -> None:
        coin = self._vers_image(self.vue._viewport, QPoint(20, 20)) if self.vue is not None else QPointF(20, 90)
        rect = QRectF(coin.x(), coin.y(), 54, 54)
        p.setPen(QPen(QColor(theme.INK), 2))
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(rect, 9, 9)
        font = QFont(theme.first_family(theme.FONT_FAMILIES) or "", 24)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, texte)

    # ------------------------------------------------------------------ coordonnées
    def _vers_image(self, widget: QWidget, point: QPoint | None = None) -> QPointF:
        """Point de l'image où apparaît ce point du widget (par défaut son centre)."""
        point = widget.rect().center() if point is None else point
        fenetre = widget.window()
        local = widget.mapTo(fenetre, point) if widget is not fenetre else point
        if fenetre in self.fenetres:
            local += self._position(fenetre)
        return QPointF(local)

    def _depuis_image(self, widget: QWidget, point: QPointF) -> QPointF:
        """Point du widget qui apparaît à ce point de l'image."""
        fenetre = widget.window()
        local = point.toPoint()
        if fenetre in self.fenetres:
            local -= self._position(fenetre)
        return QPointF(widget.mapFrom(fenetre, local) if widget is not fenetre else local)

    # ------------------------------------------------------------------ gestes
    def attendre(self, secondes: float) -> None:
        for _ in range(round(secondes * FPS)):
            self.image()

    def attendre_que(self, condition: Callable[[], bool], max_s: float = 60.0, apres_s: float = 0.0) -> None:
        """Filme en temps réel (le robot bouge) jusqu'à ce que la condition soit vraie, puis encore apres_s."""
        debut = time.perf_counter()
        n0 = self.n_images
        fin: float | None = None
        while True:
            maintenant = time.perf_counter() - debut
            if fin is None and (condition() or maintenant > max_s):
                fin = maintenant + apres_s
            if fin is not None and maintenant >= fin:
                break
            self.image()
            # capture plus lente que le temps réel : on répète l'image pour rester à la bonne vitesse
            while self.filme and self.n_images < n0 + int((time.perf_counter() - debut) * FPS):
                self._repeter_image()

    def deplacer(self, vers: QPointF, secondes: float) -> None:
        depart = QPointF(self.curseur)
        n = max(1, round(secondes * FPS))
        for i in range(1, n + 1):
            self.curseur = depart + (vers - depart) * lisse(i / n)
            self.image()

    def clic(self) -> None:
        for i in range(8):
            self.onde = (QPointF(self.curseur), i / 8)
            self.image()
        self.onde = None

    def cliquer(self, widget: QWidget, duree: float = 0.6, point: QPoint | None = None) -> None:
        """Amène le curseur sur le widget et clique (l'action est faite par l'appelant, sauf pour un bouton)."""
        self.deplacer(self._vers_image(widget, point), duree)
        self.clic()

    def appuyer(self, bouton: QAbstractButton, duree: float = 0.6) -> None:
        """Clic sur un bouton : le bouton réagit comme à la souris."""
        self.cliquer(bouton, duree)
        bouton.click()
        self.attendre(0.1)

    def choisir(self, liste: QComboBox, texte: str, duree: float = 0.6) -> None:
        """Choisit un élément d'une liste déroulante (la liste ouverte n'est pas montrée)."""
        self.cliquer(liste, duree)
        index = liste.findText(texte, Qt.MatchFlag.MatchStartsWith)
        if index < 0:
            raise KeyError(f"« {texte} » n'est pas dans la liste ({[liste.itemText(i) for i in range(liste.count())]})")
        liste.setCurrentIndex(index)
        self.attendre(0.3)

    def saisir(self, champ, valeur, duree: float = 0.5) -> None:
        """Clic dans un champ numérique, puis nouvelle valeur."""
        self.cliquer(champ, duree)
        champ.setValue(valeur)
        self.attendre(0.4)

    def taper(self, champ: QLineEdit, texte: str, par_seconde: float = 14) -> None:
        champ.clear()
        for i in range(1, len(texte) + 1):
            champ.setText(texte[:i])
            for _ in range(max(1, round(FPS / par_seconde))):
                self.image()

    def taper_code(self, editeur: QPlainTextEdit, code: str, lignes_par_seconde: float = 6) -> None:
        """Écrit le code ligne par ligne dans l'éditeur, comme s'il était tapé."""
        curseur = editeur.textCursor()
        curseur.movePosition(curseur.MoveOperation.End)
        for ligne in code.splitlines(keepends=True):
            curseur.insertText(ligne)
            editeur.setTextCursor(curseur)
            editeur.ensureCursorVisible()
            for _ in range(max(1, round(FPS / lignes_par_seconde)) if ligne.strip() else 1):
                self.image()

    @staticmethod
    def bouton_action(conteneur: QWidget, action) -> QWidget:
        """Bouton d'une barre d'outils qui déclenche cette action."""
        barre = next(b for b in conteneur.findChildren(QToolBar) if action in b.actions())
        return barre.widgetForAction(action)

    # ------------------------------------------------------------------ fenêtres par-dessus
    def ouvrir(self, fenetre: QWidget) -> None:
        fenetre.show()
        for _ in range(3):
            self.app.processEvents()
        self.fenetres.append(fenetre)

    def suivre_fenetres(self, coin: QPoint) -> None:
        """Les fenêtres que l'appli vient d'ouvrir d'elle-même (ex. les scopes de MIR Flow) sont filmées, en cascade
        à partir de ce coin."""
        for w in self.app.topLevelWidgets():
            if w.isVisible() and w is not self.principale and w not in self.fenetres and w.width() > 100 \
                    and w.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog, Qt.WindowType.Tool):
                self.coins[w] = coin + QPoint(28, 28) * len(self.coins)
                self.fenetres.append(w)

    def fermer(self, fenetre: QWidget) -> None:
        self.fenetres.remove(fenetre)
        self.coins.pop(fenetre, None)
        fenetre.hide()
        fenetre.deleteLater()

    def reponse_prevue(self, titre: str):
        if not self.reponses:
            raise RuntimeError(f"fenêtre « {titre} » sans réponse prévue dans le scénario")
        attendu, reponse = self.reponses.pop(0)
        if attendu != titre:
            raise RuntimeError(f"fenêtre « {titre} » ouverte, « {attendu} » attendue")
        return reponse

    def filmer_saisie(self, titre: str, label: str, defaut: str = "", items: list[str] | None = None,
                      subtitle: str = "", icon: str = "", accept_text: str = "Valider") -> str | None:
        """Petite fenêtre de saisie ou de choix de MIR : on la remplit et on valide."""
        valeur = str(self.reponse_prevue(titre))
        dialogue = AskDialog(None, titre, label, subtitle, icon, items=items, default=defaut, accept_text=accept_text)
        dialogue.adjustSize()
        self.ouvrir(dialogue)
        self.attendre(0.5)
        champ = dialogue._field
        if isinstance(champ, QLineEdit):
            self.cliquer(champ, 0.5)
            self.taper(champ, valeur)
        else:
            self.choisir(champ, valeur)
        self.attendre(0.3)
        self.cliquer(dialogue._ok, 0.5)
        self.fermer(dialogue)
        return valeur

    def filmer_question(self, titre: str, texte: str) -> bool:
        """Question Oui / Non de MIR : on clique la réponse prévue."""
        oui = bool(self.reponse_prevue(titre))
        boite = QMessageBox(QMessageBox.Icon.Question, titre, texte,
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        boite.adjustSize()
        self.ouvrir(boite)
        self.attendre(0.7)
        bouton = boite.button(QMessageBox.StandardButton.Yes if oui else QMessageBox.StandardButton.No)
        self.cliquer(bouton, 0.5)
        self.fermer(boite)
        return oui

    # ------------------------------------------------------------------ éditeur de structure
    def _point_liste(self, cle: str) -> QPointF:
        liste = self.vue._palette
        for i in range(liste.count()):
            item = liste.item(i)
            if item.data(KEY_ROLE) == cle:
                liste.scrollToItem(item)
                self.app.processEvents()
                return self._vers_image(liste.viewport(), liste.visualItemRect(item).center())
        raise KeyError(cle)

    def _point_connecteur(self, connecteur: str) -> tuple[int, QPointF]:
        """Pastille du connecteur : identifiant de la géométrie et position à l'écran (projection de la caméra)."""
        vm = self.vue._view_model
        geom = next(g for g, cle in vm._built.connector_markers.items() if cle == connecteur)
        return geom, self._projeter(vm._data.geom_xpos[geom])

    def _projeter(self, position: np.ndarray) -> QPointF:
        """Point de l'image où apparaît ce point du monde."""
        vue3d = self.vue._viewport
        camera = __import__("mujoco").mjv_averageCamera(vue3d._renderer.scene.camera[0], vue3d._renderer.scene.camera[1])
        avant, haut = np.array(camera.forward), np.array(camera.up)
        droite = np.cross(avant, haut)
        v = position - np.array(camera.pos)
        profondeur = v @ avant
        x = (v @ droite) * camera.frustum_near / profondeur
        y = (v @ haut) * camera.frustum_near / profondeur
        demi_largeur = 0.5 * vue3d.width() / vue3d.height() * (camera.frustum_top - camera.frustum_bottom)
        relx = ((x - camera.frustum_center) / demi_largeur + 1) / 2
        rely = (y - camera.frustum_bottom) / (camera.frustum_top - camera.frustum_bottom)
        return self._vers_image(vue3d, QPoint(round(relx * vue3d.width()), round((1 - rely) * vue3d.height())))

    def _mettre_a_jour_scene(self) -> None:
        """Rendu de la vue 3D : la scène (caméra comprise) utilisée par pick et par la projection est à jour."""
        self.vue._viewport.grab()

    def _sous_le_curseur(self, point: QPointF) -> int:
        """Géométrie que l'éditeur trouverait sous ce point de l'image (même sélection que pour un vrai dépôt)."""
        vue3d = self.vue._viewport
        self._mettre_a_jour_scene()
        return vue3d.pick(self._depuis_image(vue3d, point))

    def _pastille_visible(self, connecteur: str) -> bool:
        self._mettre_a_jour_scene()
        geom, point = self._point_connecteur(connecteur)
        return self._sous_le_curseur(point) == geom

    def cliquer_module(self, module: str, duree: float = 0.6) -> None:
        """Clic sur un module dans la vue 3D : il est sélectionné, comme à la souris."""
        vm = self.vue._view_model
        built = vm._built
        corps = next(b for b, nom in built.body_module.items() if nom == module)
        self._mettre_a_jour_scene()
        point = self._projeter(vm._data.xpos[corps])
        self.deplacer(point, duree)
        geom = self._sous_le_curseur(point)
        if geom < 0 or built.body_module.get(int(built.model.geom_bodyid[geom])) != module:
            raise RuntimeError(f"le module {module} n'est pas sous le curseur")
        self.clic()
        vm.click_geom(geom)

    def _bouton_barre(self, action):
        return self.bouton_action(self.vue, action)

    def recadrer(self) -> None:
        """Bouton « Recadrer » de la barre d'outils."""
        self.cliquer(self._bouton_barre(self.vue._reframe_action), 0.5)
        self.vue._reframe_action.trigger()
        self.attendre(0.3)

    def rendre_visible(self, connecteur: str, duree: float = 1.0) -> None:
        """Si la pastille est cachée, tourne la vue (glisser dans la vue 3D) jusqu'à ce qu'elle apparaisse."""
        if self._pastille_visible(connecteur):
            return
        camera = self.vue._viewport._camera
        depart = (camera.azimuth, camera.elevation)
        # le plus petit changement de point de vue (azimut, puis élévation) qui montre la pastille
        essais = sorted(((da, de) for da in range(-180, 181, 15) for de in (0, -20, 20, -40, 40, -60)),
                        key=lambda r: abs(r[0]) + 2 * abs(r[1]))
        rotation = None
        for da, de in essais:
            camera.azimuth, camera.elevation = depart[0] + da, max(-85, min(85, depart[1] + de))
            if self._pastille_visible(connecteur):
                rotation = (da, camera.elevation - depart[1])
                break
        camera.azimuth, camera.elevation = depart
        if rotation is None:
            raise RuntimeError(f"pastille {connecteur} invisible quel que soit le point de vue")
        # geste réel : glisser dans la vue 3D avec le bouton gauche
        vue3d = self.vue._viewport
        self.deplacer(self._vers_image(vue3d), duree * 0.4)
        vue3d._camera_moved_by_user = True     # l'éditeur garde désormais ce point de vue
        depart_curseur = QPointF(self.curseur)
        n = max(1, round(duree * FPS))
        for i in range(1, n + 1):
            t = lisse(i / n)
            camera.azimuth, camera.elevation = depart[0] + rotation[0] * t, depart[1] + rotation[1] * t
            self.curseur = depart_curseur + QPointF(rotation[0] * 2.2 * t, -rotation[1] * 2.2 * t)
            self.image()
        self.attendre(0.15)

    def glisser(self, cle: str, connecteur: str, duree: float = 1.2) -> str:
        """Glisse un élément de la liste sur un connecteur libre ; renvoie le nom du module créé."""
        vm = self.vue._view_model
        legende = self.legende
        if not self._pastille_visible(connecteur):
            self.legende = "Tourner la vue pour voir la pastille"
            self.rendre_visible(connecteur, duree)
            self.legende = legende
        self.deplacer(self._point_liste(cle), duree * 0.6)
        item = self.vue._palette_items[cle]
        self.vignette = self.vue._thumbnails[item.types[0]].pixmap(56, 56)
        vm.preview_targets(cle)       # pastilles compatibles en vert, comme pendant un vrai glisser
        self.attendre(0.15)
        self._mettre_a_jour_scene()
        geom, cible = self._point_connecteur(connecteur)
        self.deplacer(cible, duree)
        self.attendre(0.2)
        self.vignette = None
        # dépôt comme dans l'éditeur : ce qui est sous la souris, et rien d'autre
        sous_curseur = self._sous_le_curseur(cible)
        if sous_curseur != geom:
            raise RuntimeError(f"la pastille {connecteur} n'est pas sous le curseur au moment du dépôt")
        self.vue._drop(cle, sous_curseur, QPoint())
        self.clic()
        return vm._selected

    def brancher_par(self, module: str, connecteur: str, duree: float = 0.8) -> None:
        """Touche R jusqu'à ce que le module soit branché par ce connecteur."""
        vm = self.vue._view_model
        while vm.modules[module]["connector"] != connecteur:
            self.touche = "R"
            self.attendre(duree * 0.4)
            vm.change_connector()
            self.attendre(duree * 0.6)
            self.touche = ""

    def tourner_camera(self, degres: float, secondes: float) -> None:
        camera = self.vue._viewport._camera
        depart = camera.azimuth
        n = round(secondes * FPS)
        for i in range(1, n + 1):
            camera.azimuth = depart + degres * lisse(i / n)
            self.vue._viewport.update()
            self.image()

    def valider_structure(self) -> None:
        """Bouton « Valider » de l'éditeur de structure."""
        self.cliquer(self._bouton_barre(self.vue._accept_action), 0.6)
        self.vue._accept_action.trigger()


class DialoguesFilmes(QtDialogProvider):
    """Fenêtres de MIR pendant un tuto : montrées dans la vidéo et remplies avec les réponses prévues."""

    def __init__(self, enregistreur: Enregistreur | None = None):
        super().__init__()
        self.e = enregistreur

    def choose_item(self, title, label, items, current=None, parent=None):
        return self.e.filmer_saisie(title, label, items=items)

    def ask_text(self, title, label, default="", parent=None):
        return self.e.filmer_saisie(title, label, default)

    def question_yes_no(self, title, text, parent=None):
        return self.e.filmer_question(title, text)

    def save_file(self, title, init_directory, filters="", parent=None, try_use_last_directory=True):
        chemin = self.e.reponse_prevue(title)
        return init_directory if chemin is None else chemin      # None : le fichier proposé par MIR

    def information(self, title, text, parent=None):
        raise RuntimeError(f"message inattendu pendant le tuto : {title} : {text}")

    warning = error = information

    def exception(self, exc, title="Une erreur est survenue", parent=None, traceback_str=None):
        raise RuntimeError(f"erreur pendant le tuto : {title}") from exc
