"""Lecteur d'un épisode : ce que voyaient les capteurs, et les courbes des grandeurs et des consignes, avec un curseur
de temps. Sert à revoir une démonstration avant de la valider, et les épisodes déjà enregistrés."""
from __future__ import annotations
from typing import Any
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget
from mir_robot_editor.observations_widget import PolarWidget
from mir_utils.ui.view_base import ViewBase

COULEURS = ["#00B4FF", "#FF8C1A", "#3CCB5A", "#E04BD8", "#F2D13A", "#9A7BFF", "#E05050", "#50C8C8"]


class EpisodeView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._episode: dict[str, Any] | None = None
        self._fps = 20.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.titre = QLabel()
        self.titre.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self.titre)

        self._capteurs = QHBoxLayout()
        self._capteurs.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(self._capteurs)
        self._images: dict[str, QLabel] = {}
        self._polaires: dict[str, PolarWidget] = {}

        self._courbes = pg.GraphicsLayoutWidget()
        self._courbes.setBackground("w")
        layout.addWidget(self._courbes, 1)
        self._lignes: list[pg.InfiniteLine] = []

        controle = QHBoxLayout()
        self.btn_lecture = QPushButton(ViewBase.find_icon("play"), "")
        self.btn_lecture.setToolTip("Lire / mettre en pause")
        self.btn_lecture.clicked.connect(self._lecture)
        controle.addWidget(self.btn_lecture)
        self.curseur = QSlider(Qt.Orientation.Horizontal)
        self.curseur.valueChanged.connect(self._afficher)
        controle.addWidget(self.curseur, 1)
        self.lbl_temps = QLabel("0.00 s")
        self.lbl_temps.setMinimumWidth(70)
        controle.addWidget(self.lbl_temps)
        layout.addLayout(controle)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._image_suivante)

    def montrer(self, episode: dict[str, Any], titre: str, fps: float):
        self._timer.stop()
        self._episode, self._fps = episode, fps
        self.titre.setText(titre)
        fmt = episode["format"]
        for w in list(self._images.values()) + list(self._polaires.values()):
            self._capteurs.removeWidget(w)
            w.deleteLater()
        self._images, self._polaires = {}, {}
        for nom in fmt.images:
            label = QLabel()
            label.setFixedSize(320, 240)
            label.setScaledContents(True)
            self._images[nom] = label
            self._capteurs.addWidget(label)
        for nom in fmt.tableaux:
            polaire = PolarWidget(nom, 600, size=240)
            self._polaires[nom] = polaire
            self._capteurs.addWidget(polaire)

        # une courbe par grandeur : la mesure (trait plein) et la consigne de même nom (pointillés)
        self._courbes.clear()
        self._lignes = []
        t = episode["t"]
        noms = list(dict.fromkeys(fmt.etat + fmt.actions))
        premier = None
        for row, nom in enumerate(noms):
            plot = self._courbes.addPlot(row=row, col=0, title=nom)
            plot.showGrid(x=True, y=True, alpha=0.3)
            couleur = COULEURS[row % len(COULEURS)]
            if nom in fmt.etat:
                plot.plot(t, episode["etat"][:, fmt.etat.index(nom)], pen=pg.mkPen(couleur, width=2))
            if nom in fmt.actions:
                plot.plot(t, episode["actions"][:, fmt.actions.index(nom)],
                          pen=pg.mkPen(couleur, width=1.5, style=Qt.PenStyle.DashLine))
            if premier is None:
                premier = plot
            else:
                plot.setXLink(premier)
            ligne = pg.InfiniteLine(0, angle=90, pen=pg.mkPen("#888888", width=1))
            plot.addItem(ligne)
            self._lignes.append(ligne)
        self._courbes.setMinimumHeight(110 * len(noms))
        self.curseur.blockSignals(True)
        self.curseur.setRange(0, max(0, len(t) - 1))
        self.curseur.setValue(0)
        self.curseur.blockSignals(False)
        self._afficher(0)

    def _afficher(self, k: int):
        if self._episode is None or len(self._episode["t"]) == 0:
            return
        t = float(self._episode["t"][k])
        self.lbl_temps.setText(f"{t:.2f} s")
        for ligne in self._lignes:
            ligne.setValue(t)
        for nom, label in self._images.items():
            image = np.ascontiguousarray(self._episode["images"][nom][k])
            h, w, _ = image.shape
            label.setPixmap(QPixmap.fromImage(QImage(image.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()))
        for nom, polaire in self._polaires.items():
            polaire.update_plot(np.asarray(self._episode["tableaux"][nom][k]))

    def _lecture(self):
        if self._timer.isActive():
            self._timer.stop()
            return
        if self.curseur.value() >= self.curseur.maximum():
            self.curseur.setValue(0)
        self._timer.start(int(1000 / self._fps))

    def _image_suivante(self):
        if self.curseur.value() >= self.curseur.maximum():
            self._timer.stop()
        else:
            self.curseur.setValue(self.curseur.value() + 1)

    def arreter(self):
        self._timer.stop()
