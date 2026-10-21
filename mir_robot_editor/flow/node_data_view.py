"""
Données d'entrée ou de sortie d'un nœud à son dernier passage, affichées dans sa fenêtre de réglages (comme dans
n8n) : chaque valeur sous son nom ; les images en vignette, les tableaux avec leur taille et leurs premières lignes.
"""
from __future__ import annotations
import json
import time
from typing import Any
import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QImage, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget
from mir_utils.ui import theme

THUMB_WIDTH = 220
TEXT_MAX = 1500


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def _value_widget(value: Any) -> QWidget:
    if isinstance(value, np.ndarray) and value.ndim == 3 and value.shape[2] in (3, 4):
        image = np.ascontiguousarray(value[:, :, :3], dtype=np.uint8)
        h, w = image.shape[:2]
        qimage = QImage(image.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        label = QLabel()
        label.setPixmap(QPixmap.fromImage(qimage).scaledToWidth(THUMB_WIDTH, Qt.TransformationMode.SmoothTransformation))
        label.setToolTip(f"image {w} × {h}")
        return label
    if isinstance(value, dict) and any(isinstance(v, (np.ndarray, dict)) for v in value.values()):
        # dictionnaire qui contient des images ou des tableaux : une ligne par clé, chacune affichée à sa façon
        box = QWidget()
        lignes_box = QVBoxLayout(box)
        lignes_box.setContentsMargins(10, 0, 0, 0)
        for key, sub in value.items():
            nom = QLabel(str(key))
            nom.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            lignes_box.addWidget(nom)
            lignes_box.addWidget(_value_widget(sub))
        return box
    if isinstance(value, np.ndarray):
        lignes = np.array2string(value[:8], precision=1, suppress_small=True, max_line_width=60)
        text = f"tableau {' × '.join(map(str, value.shape))}\n{lignes}" + ("\n…" if len(value) > 8 else "")
    elif isinstance(value, (dict, list, tuple)):
        text = json.dumps(value, ensure_ascii=False, indent=1, default=str)
    elif isinstance(value, float):
        text = f"{value:.6g}"
    else:
        text = str(value)
    if len(text) > TEXT_MAX:
        text = text[:TEXT_MAX] + "\n…"
    label = QLabel(text)
    label.setFont(QFont(theme.MONO_FAMILIES[0]))
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setWordWrap(True)
    return label


class NodeDataView(QScrollArea):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(240)
        self.show_data(None, None)

    def show_data(self, data: dict[str, Any] | None, info: dict[str, Any] | None, empty: str = ""):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        titre = QLabel(self.title)
        titre.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(titre)
        if data is None:
            layout.addWidget(_muted(empty or "Lancez le programme : les données du dernier passage dans ce nœud "
                                             "s'afficheront ici."))
        else:
            if info:
                age = time.time() - info.get("time", time.time())
                quand = "à l'instant" if age < 2 else f"il y a {age:.0f} s" if age < 120 else f"il y a {age / 60:.0f} min"
                details = f"Dernier passage : {quand}"
                if info.get("port") and info.get("multiple_outputs"):
                    details += f" · sortie « {info['port']} »"
                layout.addWidget(_muted(details))
            if not data:
                layout.addWidget(_muted("(rien)"))
            for key, value in data.items():
                nom = QLabel(key)
                nom.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-weight: bold; margin-top: 6px;")
                layout.addWidget(nom)
                layout.addWidget(_value_widget(value))
        layout.addStretch(1)
        self.setWidget(page)


def describe(value: Any) -> str:
    """Le type d'une donnée, en quelques mots (dans la liste des données disponibles)."""
    if isinstance(value, np.ndarray):
        if value.ndim == 3:
            return f"image {value.shape[1]} × {value.shape[0]}"
        return f"tableau {' × '.join(map(str, value.shape))}"
    if isinstance(value, bool):
        return "vrai / faux"
    if isinstance(value, (int, float, np.number)):
        return f"nombre ({value:.4g})"
    if isinstance(value, dict):
        return f"dictionnaire ({', '.join(list(map(str, value))[:4])}{'…' if len(value) > 4 else ''})"
    if isinstance(value, (list, tuple)):
        return f"liste de {len(value)}"
    if isinstance(value, str):
        return "texte"
    return type(value).__name__


class DataCatalog(QWidget):
    """Les données du flux qu'un nœud peut utiliser (comme la colonne d'entrée de n8n) : chaque nœud et ses clés.
    Un double-clic insère le nom à l'endroit du curseur, dans la bonne forme (expression ou script)."""
    chosen = Signal(str, str)               # nœud, clé

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 0)
        titre = QLabel("Données disponibles")
        titre.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(titre)
        layout.addWidget(_muted("Double-clic : insère le nom là où se trouve le curseur (carte.image dans une "
                                "expression, donnees[\"carte\"][\"image\"] dans un script)."))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree, 1)
        self._signature = None

    def set_entries(self, entries: list[tuple[str, dict[str, str] | None]]):
        """entries : [(nom du nœud, {clé: type} ou None s'il n'a pas encore tourné)]."""
        signature = repr(entries)
        if signature == self._signature:
            return
        self._signature = signature
        ouverts = {self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount())
                   if self.tree.topLevelItem(i).isExpanded()}
        self.tree.clear()
        for name, keys in entries:
            item = QTreeWidgetItem([name, "" if keys else "pas encore exécuté"])
            item.setData(0, Qt.ItemDataRole.UserRole, (name, ""))
            for key, kind in (keys or {}).items():
                child = QTreeWidgetItem([f"{name}.{key}", kind])
                child.setData(0, Qt.ItemDataRole.UserRole, (name, key))
                child.setToolTip(0, f"expression : {name}.{key}\nscript : donnees[\"{name}\"][\"{key}\"]")
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            item.setExpanded(name in ouverts or name == "entree" or not ouverts)
        self.tree.resizeColumnToContents(0)

    def _on_double_click(self, item, column):
        name, key = item.data(0, Qt.ItemDataRole.UserRole)
        self.chosen.emit(name, key)
