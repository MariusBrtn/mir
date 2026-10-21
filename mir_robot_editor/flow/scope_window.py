"""
Fenêtre d'un nœud Scope de MIR Flow : affiche en direct la valeur reçue à chaque passage, sous la forme qui lui
convient — une image (la carte), un nuage lidar vu de dessus, des courbes dans le temps, une trajectoire (x, y).
Rafraîchie au plus 10 fois par seconde, quel que soit le rythme de la chaîne.
"""
from __future__ import annotations
from collections import deque
from typing import Any
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from mir_utils.ui import theme

COULEURS = [theme.FLOW_PERCEIVE, theme.FLOW_ACT, theme.FLOW_DECIDE, theme.FLOW_COMMUNICATE, theme.FLOW_STEPS,
            theme.SLATE, theme.SAND_DARK]
LIDAR_MAX_M = 6.0


def guess_display(value: Any) -> str:
    """Affichage automatique, d'après la forme de la valeur."""
    if isinstance(value, np.ndarray):
        if value.ndim == 3:
            return "image"
        if value.ndim == 2 and value.shape[1] == 2:
            return "lidar"
        if value.ndim == 2:
            return "image"
    if isinstance(value, dict) and "x" in value and "y" in value:
        return "trajectoire"
    if isinstance(value, (tuple, list)) and len(value) == 2 and all(isinstance(v, (int, float)) for v in value):
        return "trajectoire"
    return "courbes"


def numbers(value: Any, name: str) -> dict[str, float]:
    """Les nombres à tracer : un nombre, ou un dictionnaire de nombres (un par courbe)."""
    if isinstance(value, (bool, np.bool_)):
        return {name: float(value)}
    if isinstance(value, (int, float, np.number)):
        return {name: float(value)}
    if isinstance(value, dict):
        return {str(k): float(v) for k, v in value.items() if isinstance(v, (int, float, np.number))
                and not isinstance(v, bool)}
    return {}


class ScopeWindow(QWidget):
    def __init__(self, parent, title: str):
        super().__init__(parent, Qt.WindowType.Tool)
        self.setWindowTitle(title)
        self.resize(520, 440)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self.plot = self._new_plot()
        self._layout.addWidget(self.plot, 1)
        self.info = QLabel()
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        self._layout.addWidget(self.info)
        self._mode: str | None = None
        self._pending: tuple[Any, float, str, float] | None = None
        self._history: dict[str, deque] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._trajet: deque = deque()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    @staticmethod
    def _new_plot() -> pg.PlotWidget:
        plot = pg.PlotWidget(background=theme.SURFACE)
        plot.showGrid(x=True, y=True, alpha=0.2)
        return plot

    def _replace_plot(self):
        """Un graphique neuf : rien ne reste de l'affichage précédent (légende, image…)."""
        nouveau = self._new_plot()
        self._layout.replaceWidget(self.plot, nouveau)
        self.plot.deleteLater()
        self.plot = nouveau
        self._curves = {}

    def reset(self):
        """Nouveau lancement : on repart d'un affichage vide."""
        self._mode, self._pending = None, None
        self._history, self._curves = {}, {}
        self._trajet.clear()
        self._replace_plot()
        self.info.setText("")

    def show_error(self, text: str):
        self._pending = None
        self.info.setText(f"⚠ {text}")
        self.info.setStyleSheet(f"color: {theme.ERROR};")

    def push(self, value: Any, temps: float, display: str, history_s: float, name: str):
        self.info.setStyleSheet("")
        self._pending = (value, temps, display, history_s, name)
        for key, number in (numbers(value, name).items() if (display if display != "automatique"
                                                              else guess_display(value)) == "courbes" else []):
            buffer = self._history.setdefault(key, deque())
            buffer.append((temps, number))
            while buffer and buffer[0][0] < temps - history_s:
                buffer.popleft()
        mode = display if display != "automatique" else guess_display(value)
        if mode == "trajectoire":
            xy = (value.get("x"), value.get("y")) if isinstance(value, dict) else tuple(value)[:2]
            if all(isinstance(v, (int, float, np.number)) for v in xy):
                self._trajet.append((temps, float(xy[0]), float(xy[1])))
                while self._trajet and self._trajet[0][0] < temps - history_s:
                    self._trajet.popleft()

    # ------------------------------------------------------------------ affichage
    def _set_mode(self, mode: str):
        if mode == self._mode:
            return
        self._mode = mode
        self._replace_plot()
        self.plot.setAspectLocked(mode in ("image", "lidar", "trajectoire"))
        self.plot.getViewBox().invertY(mode == "image")
        labels = {"image": ("", ""), "lidar": ("droite (m)", "avant (m)"), "courbes": ("temps (s)", ""),
                  "trajectoire": ("x (m)", "y (m)")}[mode]
        self.plot.setLabel("bottom", labels[0])
        self.plot.setLabel("left", labels[1])
        if mode == "image":
            self._image = pg.ImageItem(axisOrder="row-major")
            self._cadre = None                  # taille de l'image sur laquelle la vue est cadrée
            self.plot.addItem(self._image)
        elif mode == "lidar":
            self._points = pg.ScatterPlotItem(size=3, pen=None, brush=pg.mkBrush(QColor(theme.INK)))
            self.plot.addItem(self._points)
            robot = pg.ScatterPlotItem([0], [0], size=10, symbol="t1", brush=pg.mkBrush(QColor(theme.FLOW_ACT)))
            self.plot.addItem(robot)
            self.plot.setRange(xRange=(-LIDAR_MAX_M, LIDAR_MAX_M), yRange=(-LIDAR_MAX_M, LIDAR_MAX_M), padding=0)
            self.plot.getViewBox().disableAutoRange()       # la vue ne bouge que si l'on zoome ou déplace
        elif mode == "courbes":
            self.plot.addLegend(offset=(10, 10))
        elif mode == "trajectoire":
            self._line = self.plot.plot([], [], pen=pg.mkPen(QColor(theme.FLOW_PERCEIVE), width=2))
            self._here = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(QColor(theme.FLOW_ACT)))
            self.plot.addItem(self._here)

    def _refresh(self):
        if self._pending is None or not self.isVisible():
            return
        value, temps, display, history_s, name = self._pending
        self._pending = None
        mode = display if display != "automatique" else guess_display(value)
        try:
            self._set_mode(mode)
            if mode == "image":
                image = np.asarray(value)
                if image.ndim not in (2, 3):
                    raise ValueError(f"ce n'est pas une image (tableau à {image.ndim} dimension(s))")
                if image.ndim == 2:                         # tableau 2D (ex. grille) : en niveaux de gris
                    lo, hi = float(np.min(image)), float(np.max(image))
                    image = ((image - lo) / (hi - lo or 1) * 255).astype(np.uint8)
                self._image.setImage(image, autoLevels=False, levels=(0, 255))
                if self._cadre != image.shape[:2]:
                    # cadrée une fois sur l'image, puis plus de recadrage automatique : sinon, après un zoom,
                    # chaque nouvelle image recadrerait l'axe resté automatique et la vue glisserait
                    self._cadre = image.shape[:2]
                    self.plot.setRange(xRange=(0, image.shape[1]), yRange=(0, image.shape[0]), padding=0.02)
                    self.plot.getViewBox().disableAutoRange()
                self.info.setText(f"image {image.shape[1]} × {image.shape[0]} · t = {temps:.1f} s")
            elif mode == "lidar":
                points = np.asarray(value, dtype=float)
                points = points[points[:, 1] > 0]
                a, d = np.radians(points[:, 0]), points[:, 1] / 100.0
                self._points.setData(d * np.sin(a), d * np.cos(a))      # angle 0 devant, sens horaire
                self.info.setText(f"{len(points)} points · avant vers le haut · t = {temps:.1f} s")
            elif mode == "courbes":
                if not self._history:
                    self.info.setText(f"Rien à tracer : {type(value).__name__} n'est ni un nombre ni un "
                                      f"dictionnaire de nombres.")
                    return
                for i, (key, buffer) in enumerate(self._history.items()):
                    if key not in self._curves:
                        self._curves[key] = self.plot.plot([], [], name=key,
                                                           pen=pg.mkPen(QColor(COULEURS[i % len(COULEURS)]), width=2))
                    t, v = zip(*buffer)
                    self._curves[key].setData(t, v)
                derniers = ", ".join(f"{k} = {b[-1][1]:.4g}" for k, b in self._history.items())
                self.info.setText(f"t = {temps:.1f} s · {derniers}")
            elif mode == "trajectoire":
                if self._trajet:
                    _, x, y = zip(*self._trajet)
                    self._line.setData(x, y)
                    self._here.setData([x[-1]], [y[-1]])
                    self.info.setText(f"x = {x[-1]:.2f} m, y = {y[-1]:.2f} m · t = {temps:.1f} s")
        except Exception as e:                              # une valeur qui ne se prête pas à cet affichage
            self.info.setText(f"Impossible d'afficher en « {mode} » : {type(e).__name__} : {e}")
