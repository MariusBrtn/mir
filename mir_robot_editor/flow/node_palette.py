"""
Bibliothèque de nœuds de MIR Flow (colonne de gauche) : les nœuds rangés par catégorie (percevoir, décider, agir…),
avec une icône, un nom et une ligne d'explication. Un clic ajoute le nœud à côté du nœud choisi (et le relie à sa
sortie) ; on peut aussi le glisser sur le graphe.
Les nœuds qui demandent une caméra ou un lidar n'apparaissent que si le robot en a.
"""
from __future__ import annotations
from PySide6.QtCore import QByteArray, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from mir_flow.graph import CATEGORIES, NEEDS_CAMERA, NEEDS_LIDAR, NODE_START, SPECS
from mir_robot_editor.flow.node_icons import CATEGORY_COLORS, icon_color, icon_pixmap
from mir_utils.ui import theme

MIME = "application/x-mir-flow-node"         # contenu : "type" ou "type|capteur"


class PaletteItem(QFrame):
    clicked = Signal(str, str)              # type de nœud, capteur ("" : aucun)

    def __init__(self, node_type: str, label: str, sensor: str = ""):
        super().__init__()
        self.node_type, self.sensor = node_type, sensor
        spec = SPECS[node_type]
        self.setObjectName("PaletteItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip((spec.help or spec.summary) + "\n\nClic : ajouter à côté du nœud choisi · glisser : placer "
                                                      "sur le graphe")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        couleur = CATEGORY_COLORS.get(spec.category, theme.INK)
        icone = QLabel()
        icone.setPixmap(icon_pixmap(node_type, 26, icon_color(spec.category), couleur))
        layout.addWidget(icone)
        textes = QVBoxLayout()
        textes.setSpacing(0)
        titre = QLabel(label)
        titre.setStyleSheet("font-weight: bold;")
        textes.addWidget(titre)
        resume = QLabel(spec.summary)
        resume.setObjectName("Muted")
        resume.setWordWrap(True)
        resume.setStyleSheet("font-size: 11px;")
        textes.addWidget(resume)
        layout.addLayout(textes, 1)
        self._press: QPoint | None = None
        self.setStyleSheet(f"#PaletteItem {{ border-radius: 6px; }} #PaletteItem:hover {{ background: {theme.PANEL}; }}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()

    def mouseMoveEvent(self, event):
        if self._press is None or (event.position().toPoint() - self._press).manhattanLength() < 8:
            return
        self._press = None
        mime = QMimeData()
        mime.setData(MIME, QByteArray(f"{self.node_type}|{self.sensor}".encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        category = SPECS[self.node_type].category
        drag.setPixmap(icon_pixmap(self.node_type, 32, icon_color(category), CATEGORY_COLORS.get(category, theme.INK)))
        drag.exec(Qt.DropAction.CopyAction)

    def mouseReleaseEvent(self, event):
        if self._press is not None and self.isEnabled() and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.node_type, self.sensor)
        self._press = None


class NodePalette(QScrollArea):
    add_requested = Signal(str, str)        # type de nœud, capteur

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(190)
        self.setMaximumWidth(240)
        self.refresh([], [], False)

    def refresh(self, cameras: list[str], lidars: list[str], has_start: bool):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 2, 6, 2)
        layout.setSpacing(2)
        for category in CATEGORIES:
            entries = []
            for node_type, spec in SPECS.items():
                if spec.category != category:
                    continue
                sensors = cameras if node_type in NEEDS_CAMERA else lidars if node_type in NEEDS_LIDAR else None
                if sensors is None:
                    entries.append((node_type, spec.label, ""))
                elif sensors:
                    entries.append((node_type, spec.label, ""))
            if not entries:
                continue
            titre = QLabel(category.upper())
            titre.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-weight: bold; font-size: 11px; margin-top: 8px;")
            layout.addWidget(titre)
            for node_type, label, sensor in entries:
                item = PaletteItem(node_type, label, sensor)
                item.setEnabled(not (node_type == NODE_START and has_start))
                if node_type == NODE_START and has_start:
                    item.setToolTip("Il y a déjà un nœud Départ")
                item.clicked.connect(self.add_requested)
                layout.addWidget(item)
        if not cameras and not lidars:
            note = QLabel("Ce robot n'a ni caméra ni lidar.")
            note.setObjectName("Muted")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addStretch(1)
        self.setWidget(page)
