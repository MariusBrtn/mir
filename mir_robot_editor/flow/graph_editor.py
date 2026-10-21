"""
Éditeur du graphe d'un MIR Flow.

  - liens d'exécution : on tire un lien d'une sortie (rond à droite d'un nœud) vers l'entrée d'un autre (rond à
    gauche) ; le lien s'aimante au port le plus proche quand on s'en approche ;
  - liens d'outils : du losange en haut d'un outil vers le losange « Outils » d'un LLM ;
  - un lien qui revient en arrière (boucle) passe sous les nœuds, en U.
Suppr efface la sélection ; Ctrl + molette ou pincement : zoom ; glisser le fond : déplacer la vue. Les nœuds de la
bibliothèque se déposent sur le graphe. Pendant un flux, le nœud en cours est entouré de vert.
"""
from __future__ import annotations
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView
from mir_flow.graph import EDGE_MAIN, EDGE_TOOL, NODE_ACTION, NODE_LLM, NODE_MEASURE, SOURCE_SERVOS, Edge, Graph, Node
from mir_robot_editor.flow.node_icons import CATEGORY_COLORS, draw_icon, icon_color
from mir_robot_editor.flow.node_palette import MIME
from mir_utils.ui import theme

PORT_R = 7
GRID = 20
W, H = 200, 64
MAGNET_PX = 40              # distance (à l'écran) à laquelle un lien s'aimante à un port
ZOOM_MIN, ZOOM_MAX = 0.3, 2.0

IN, OUT, TOOL, TOOLS = "in", "out", "tool", "tools"


def node_subtitle(node: Node) -> str:
    c, t = node.config, node.type
    if t == NODE_LLM:
        return c.get("model", "")
    if t == NODE_ACTION:
        duree = float(c.get('duration_s') or 0)
        sorte = {"setpoint": "Consigne", "script": "Script", "policy": "Politique"}.get(c.get("kind", ""), "")
        text = f"{sorte} · " + (f"{duree:g} s" if c.get("kind") == "setpoint" else f"max {duree:g} s")
        return text + (" · arrêt si…" if (c.get("until") or "").strip() else "")
    if t == NODE_MEASURE:
        source = c.get("source") or "source à choisir"
        if source == SOURCE_SERVOS:
            return "servos : " + ", ".join(c.get("quantities") or [])
        return source
    for key in ("expression", "classes", "text"):
        if c.get(key):
            text = str(c[key]).replace("\n", " ")
            return text if len(text) < 30 else text[:29] + "…"
    if c.get("count"):
        return f"{c['count']} fois"
    if c.get("rate_hz"):
        return f"{float(c['rate_hz']):g} fois par seconde"
    if c.get("duration_s"):
        return f"{float(c['duration_s']):g} s"
    return ""


class PortItem(QGraphicsItem):
    def __init__(self, node_item: NodeItem, kind: str, name: str = ""):
        super().__init__(node_item)
        self.node_item, self.kind, self.name = node_item, kind, name
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(2)
        self.highlight = False

    def boundingRect(self) -> QRectF:
        return QRectF(-PORT_R - 3, -PORT_R - 3, 2 * PORT_R + 6, 2 * PORT_R + 6)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = PORT_R + (2 if self.highlight else 0)
        painter.setPen(QPen(QColor(theme.OK if self.highlight else theme.INK), 2 if self.highlight else 1.5))
        painter.setBrush(QColor(theme.SAND if self.highlight else theme.SURFACE))
        if self.kind in (TOOL, TOOLS):         # losange : liens d'outils, comme les sous-ports d'un agent dans n8n
            path = QPainterPath()
            path.moveTo(0, -r)
            path.lineTo(r, 0)
            path.lineTo(0, r)
            path.lineTo(-r, 0)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            painter.drawEllipse(QPointF(0, 0), r - 1, r - 1)

    def accepts(self, other: PortItem) -> bool:
        return {self.kind, other.kind} in ({OUT, IN}, {TOOL, TOOLS}) and self.node_item is not other.node_item

    def set_highlight(self, on: bool):
        if on != self.highlight:
            self.highlight = on
            self.update()

    def hoverEnterEvent(self, event):
        self.set_highlight(True)

    def hoverLeaveEvent(self, event):
        self.set_highlight(False)


class NodeItem(QGraphicsItem):
    def __init__(self, node: Node, editor: GraphEditor):
        super().__init__()
        self.node = node
        self.editor = editor
        self.active = False
        llm = node.type == NODE_LLM
        self.w, self.h = (240, 76) if llm else (W, H)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(node.x, node.y)
        self.setZValue(1)
        spec = node.spec
        self.ports: dict[tuple[str, str], PortItem] = {}
        if spec.has_input:
            self._port(IN, "", -self.w / 2, 0)
        n = len(node.outputs)
        for i, name in enumerate(node.outputs):
            self._port(OUT, name, self.w / 2, (i + 1) * self.h / (n + 1) - self.h / 2)
        if spec.tool:
            self._port(TOOL, "", 0, -self.h / 2)
        if llm:
            self._port(TOOLS, "", 0, self.h / 2)

    def _port(self, kind: str, name: str, x: float, y: float):
        port = PortItem(self, kind, name)
        port.setPos(x, y)
        self.ports[(kind, name)] = port

    def boundingRect(self) -> QRectF:
        return QRectF(-self.w / 2 - 4, -self.h / 2 - 4, self.w + 80, self.h + 8)     # + noms des sorties

    def shape(self) -> QPainterPath:
        """Zone de clic : le nœud seul (pas les noms des sorties), pour pouvoir cliquer les liens qui en partent."""
        path = QPainterPath()
        path.addRoundedRect(QRectF(-self.w / 2, -self.h / 2, self.w, self.h), 10, 10)
        return path

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(-self.w / 2, -self.h / 2, self.w, self.h)
        llm = self.node.type == NODE_LLM
        spec = self.node.spec
        couleur = QColor(CATEGORY_COLORS.get(spec.category, theme.INK))
        fond = QColor(theme.INK) if llm else QColor(theme.SURFACE)
        texte = QColor(theme.SAND) if llm else QColor(theme.TEXT)
        if self.active:
            painter.setPen(QPen(QColor(theme.OK), 4))
        else:
            bord = QColor(theme.SLATE) if self.isSelected() else QColor(theme.INK if llm else theme.BORDER_STRONG)
            painter.setPen(QPen(bord, 2.5 if self.isSelected() else 1.2))
        painter.setBrush(fond)
        painter.drawRoundedRect(rect, 10, 10)
        # pastille de la couleur de la catégorie, avec l'icône du nœud
        pastille = QRectF(rect.left() + 10, rect.center().y() - 18, 36, 36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SAND) if llm else couleur)
        painter.drawRoundedRect(pastille, 9, 9)
        draw_icon(painter, self.node.type, pastille.adjusted(8, 8, -8, -8), theme.INK if llm else icon_color(spec.category))
        x = pastille.right() + 10
        largeur = rect.right() - x - 8
        font = QFont(painter.font())
        font.setPointSizeF(8)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(theme.SAND) if llm else QColor(theme.TEXT_MUTED))
        painter.drawText(QPointF(x, rect.top() + 17), spec.label.upper())
        font.setPointSizeF(11.5)
        painter.setFont(font)
        painter.setPen(texte)
        painter.drawText(QRectF(x, rect.top() + 21, largeur, 20), Qt.AlignmentFlag.AlignLeft, self.node.name)
        font.setBold(False)
        font.setPointSizeF(9)
        painter.setFont(font)
        painter.setPen(QColor(theme.SAND) if llm else QColor(theme.TEXT_MUTED))
        painter.drawText(QRectF(x, rect.top() + 41, largeur, 18), Qt.AlignmentFlag.AlignLeft,
                         node_subtitle(self.node))
        # noms des sorties quand il y en a plusieurs (oui / non…)
        if len(self.node.outputs) > 1:
            font.setPointSizeF(8)
            painter.setFont(font)
            painter.setPen(QColor(theme.TEXT_MUTED))
            for (kind, name), port in self.ports.items():
                if kind == OUT:
                    painter.drawText(QPointF(rect.right() + 12, port.pos().y() - 6), name)
        if llm:
            painter.setPen(QColor(theme.SAND))
            font.setPointSizeF(8)
            painter.setFont(font)
            painter.drawText(QRectF(-40, rect.bottom() - 17, 80, 14), Qt.AlignmentFlag.AlignCenter, "Outils")

    def set_active(self, active: bool):
        self.active = active
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            value = QPointF(round(value.x() / GRID) * GRID, round(value.y() / GRID) * GRID)     # sur la grille
        elif change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.node.x, self.node.y = self.pos().x(), self.pos().y()
            self.editor.update_edges()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        self._start = self.pos()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.editor.node_double_clicked.emit(self.node)         # ouvre ses réglages

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if getattr(self, "_start", None) is not None and self.pos() != self._start:
            self.editor.graph_changed.emit()        # position enregistrée (et annulable)


def edge_path(a: QPointF, b: QPointF, kind: str, below: float | None = None) -> QPainterPath:
    """Tracé d'un lien. Lien d'exécution vers l'avant : courbe en S ; vers l'arrière (boucle) : U sous les nœuds,
    à la hauteur below."""
    path = QPainterPath(a)
    if kind == EDGE_TOOL:           # vertical : de l'outil (en bas) au LLM (au-dessus)
        dy = max(abs(b.y() - a.y()) / 2, 40)
        path.cubicTo(QPointF(a.x(), a.y() - dy), QPointF(b.x(), b.y() + dy), b)
        return path
    if b.x() >= a.x() + 40:         # vers l'avant
        dx = max((b.x() - a.x()) / 2, 40)
        path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
        return path
    # vers l'arrière : sort à droite, passe à la hauteur y en revenant vers la gauche, rentre par la gauche.
    # Nœuds sur deux rangées : y entre les deux (un S) ; sur la même rangée (boucle) : y sous les nœuds (un U)
    r = 52.0
    if below is None:
        below = (a.y() + b.y()) / 2 if abs(b.y() - a.y()) > H + 20 else max(a.y(), b.y()) + H / 2 + 40
    y = below
    path.cubicTo(QPointF(a.x() + r, a.y()), QPointF(a.x() + r, y), QPointF(a.x(), y))
    path.lineTo(QPointF(b.x(), y))
    path.cubicTo(QPointF(b.x() - r, y), QPointF(b.x() - r, b.y()), b)
    return path


class EdgeItem(QGraphicsPathItem):
    def __init__(self, edge: Edge, start: PortItem, end: PortItem):
        super().__init__()
        self.edge, self.start, self.end = edge, start, end
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(0)
        self.update_path()

    def update_path(self):
        below = None
        a, b = self.start.scenePos(), self.end.scenePos()
        if self.edge.kind == EDGE_MAIN and b.x() < a.x() + 40:
            n1, n2 = self.start.node_item, self.end.node_item
            haut1, bas1 = n1.y() - n1.h / 2, n1.y() + n1.h / 2
            haut2, bas2 = n2.y() - n2.h / 2, n2.y() + n2.h / 2
            if bas1 + 10 < haut2 or bas2 + 10 < haut1:
                below = (max(haut1, haut2) + min(bas1, bas2)) / 2     # deux rangées : le S passe entre elles
            else:
                below = max(bas1, bas2) + 30                        # même rangée : la boucle passe dessous
        self.setPath(edge_path(a, b, self.edge.kind, below))

    def shape(self):
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path())

    def paint(self, painter, option, widget=None):
        tool = self.edge.kind == EDGE_TOOL
        couleur = theme.SLATE if self.isSelected() else (theme.TEXT_MUTED if tool else theme.INK)
        self.setPen(QPen(QColor(couleur), 3 if self.isSelected() else 2,
                         Qt.PenStyle.DashLine if tool else Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        super().paint(painter, option, widget)


class GraphEditor(QGraphicsView):
    selection_changed = Signal(object)          # nœud choisi (Node) ou None
    graph_changed = Signal()                    # à enregistrer (et annulable)
    node_dropped = Signal(str, str, QPointF)    # nœud de la bibliothèque déposé : type, capteur, position
    node_double_clicked = Signal(object)        # Node : ouvrir ses réglages
    scope_requested = Signal(object)            # Node (Scope) : afficher sa fenêtre

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-4000, -4000, 8000, 8000)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(theme.WINDOW)))
        self.setAcceptDrops(True)
        self.graph: Graph | None = None
        self._items: dict[str, NodeItem] = {}
        self._edges: list[EdgeItem] = []
        self._drag_from: PortItem | None = None
        self._drag_line: QGraphicsPathItem | None = None
        self._snap: PortItem | None = None
        self._active: str | None = None
        self._fitted = False
        self.read_only = False                      # pendant l'exécution : on regarde, on ne modifie pas
        self._scene.selectionChanged.connect(self._on_selection)

    # ------------------------------------------------------------------ graphe
    def set_graph(self, graph: Graph | None, keep_view: bool = False, select: str | None = None):
        self._scene.blockSignals(True)
        self._scene.clear()
        self._items, self._edges, self._active = {}, [], None
        self.graph = graph
        if graph is not None:
            for node in graph.nodes:
                self._add_item(node)
            self._rebuild_edges()
            if select in self._items:
                self._items[select].setSelected(True)
        self._scene.blockSignals(False)
        if graph is not None and not keep_view:
            self.fit()
        self._on_selection()

    def set_read_only(self, read_only: bool):
        """Lecture seule (programme en cours) : sélection, réglages (double-clic), vue et zoom restent possibles ;
        déplacer, relier, supprimer ou ajouter ne l'est plus."""
        self.read_only = read_only
        for item in self._items.values():
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not read_only)

    def _add_item(self, node: Node) -> NodeItem:
        item = NodeItem(node, self)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, not self.read_only)
        self._scene.addItem(item)
        self._items[node.id] = item
        return item

    def _rebuild_edges(self):
        for edge in self._edges:
            self._scene.removeItem(edge)
        self._edges = []
        for edge in self.graph.edges:
            a, b = self._items.get(edge.src), self._items.get(edge.dst)
            if a is None or b is None:
                continue
            start = a.ports.get((OUT, edge.port) if edge.kind == EDGE_MAIN else (TOOL, ""))
            end = b.ports.get((IN, "") if edge.kind == EDGE_MAIN else (TOOLS, ""))
            if start is not None and end is not None:
                item = EdgeItem(edge, start, end)
                self._scene.addItem(item)
                self._edges.append(item)

    def update_edges(self):
        for edge in self._edges:
            edge.update_path()

    def refresh_node(self, node_id: str):
        """Après un réglage : texte du nœud, et ses ports si ses sorties ont changé (« Arrêter quand »)."""
        item = self._items.get(node_id)
        if item is None:
            return
        outputs = [name for kind, name in item.ports if kind == OUT]
        if outputs == item.node.outputs:
            item.update()
            return
        self.graph.prune_edges()
        selected = item.isSelected()
        self._scene.removeItem(item)
        item = self._add_item(item.node)
        self._rebuild_edges()
        if selected:
            self._scene.blockSignals(True)
            item.setSelected(True)
            self._scene.blockSignals(False)

    def set_active(self, node_id: str | None):
        """Nœud en cours d'exécution (entouré de vert)."""
        if self._active in self._items:
            self._items[self._active].set_active(False)
        self._active = node_id
        if node_id in self._items:
            self._items[node_id].set_active(True)

    def add_node(self, node_type: str, at: QPointF | None = None) -> Node | None:
        """Nouveau nœud. Sans position : à droite du nœud choisi, relié à sa première sortie libre."""
        if self.graph is None:
            return None
        selected = self.selected_node() if at is None else None
        if at is not None:
            x, y = at.x(), at.y()
        elif selected is not None:
            x, y = selected.x + 260, selected.y
        else:
            rect = self._scene.itemsBoundingRect()
            x, y = (rect.right() + 140 if self._items else 0), (rect.center().y() if self._items else 0)
        if at is None:
            while any(abs(n.x - x) < W + 30 and abs(n.y - y) < H + 40 for n in self.graph.nodes):
                y += 120                # pas par-dessus un autre nœud
        node = self.graph.add_node(node_type, x, y)
        if selected is not None and node.spec.has_input:
            libre = next((p for p in selected.outputs if self.graph.next_node(selected.id, p) is None), None)
            if libre is not None:
                self.graph.connect_main(selected.id, libre, node.id)
        elif selected is not None and selected.type == NODE_LLM and node.is_tool:
            node.x, node.y = selected.x, selected.y + 180
            self.graph.connect_tool(node.id, selected.id)
        item = self._add_item(node)
        self._rebuild_edges()
        self._scene.clearSelection()
        item.setSelected(True)
        self.ensureVisible(item, 60, 60)
        self.graph_changed.emit()
        return node

    def selected_node(self) -> Node | None:
        nodes = [i for i in self._scene.selectedItems() if isinstance(i, NodeItem)]
        return nodes[0].node if len(nodes) == 1 else None

    def delete_selection(self):
        if self.graph is None or self.read_only:
            return
        changed = False
        for item in self._scene.selectedItems():
            if isinstance(item, EdgeItem):
                self.graph.remove_edge(item.edge)
                changed = True
        for item in self._scene.selectedItems():
            if isinstance(item, NodeItem):
                self.graph.remove_node(item.node.id)
                self._scene.removeItem(item)
                del self._items[item.node.id]
                changed = True
        if changed:
            self._rebuild_edges()
            self.graph_changed.emit()
            self._on_selection()

    # ------------------------------------------------------------------ zoom
    def zoom(self, factor: float):
        current = self.transform().m11()
        factor = max(ZOOM_MIN / current, min(ZOOM_MAX / current, factor))
        self.scale(factor, factor)

    def fit(self):
        """Tout le graphe visible, centré, sans grossir au-delà de 100 %."""
        self.resetTransform()
        if not self._items:
            self.centerOn(0, 0)
            return
        rect = self._scene.itemsBoundingRect().adjusted(-50, -50, 50, 50)
        if rect.width() > self.viewport().width() or rect.height() > self.viewport().height():
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.centerOn(rect.center())

    def showEvent(self, event):
        super().showEvent(event)
        if self.graph is not None and not self._fitted:
            self._fitted = True
            self.fit()                  # la taille de la vue n'est connue qu'à l'affichage

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            return
        super().wheelEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.NativeGesture and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom(1 + event.value())            # pincement sur le pavé tactile
            return True
        return super().viewportEvent(event)

    # ------------------------------------------------------------------ souris et clavier
    def _on_selection(self):
        self.selection_changed.emit(self.selected_node())

    def _port_at(self, pos) -> PortItem | None:
        return next((i for i in self.items(pos) if isinstance(i, PortItem)), None)

    def _nearest_port(self, scene_pos: QPointF) -> PortItem | None:
        """Le port compatible le plus proche (aimant), à moins de MAGNET_PX à l'écran."""
        best, best_d = None, MAGNET_PX / self.transform().m11()
        for item in self._items.values():
            for port in item.ports.values():
                if not self._drag_from.accepts(port):
                    continue
                d = (port.scenePos() - scene_pos).manhattanLength()
                if d < best_d:
                    best, best_d = port, d
        return best

    def mousePressEvent(self, event):
        port = None if self.read_only else self._port_at(event.position().toPoint())
        if port is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = port
            self._drag_line = QGraphicsPathItem()
            self._drag_line.setPen(QPen(QColor(theme.SLATE), 2, Qt.PenStyle.DashLine))
            self._drag_line.setZValue(3)
            self._scene.addItem(self._drag_line)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_from is not None:
            a = self._drag_from.scenePos()
            b = self.mapToScene(event.position().toPoint())
            snap = self._nearest_port(b)
            if snap is not self._snap:
                if self._snap is not None:
                    self._snap.set_highlight(False)
                if snap is not None:
                    snap.set_highlight(True)
                self._snap = snap
            if snap is not None:
                b = snap.scenePos()                 # le lien colle au port
            kind = EDGE_TOOL if self._drag_from.kind in (TOOL, TOOLS) else EDGE_MAIN
            forward = self._drag_from.kind in (OUT, TOOL)
            self._drag_line.setPath(edge_path(a, b, kind) if forward else edge_path(b, a, kind))
            self._drag_line.setPen(QPen(QColor(theme.OK if snap else theme.SLATE), 2.5 if snap else 2,
                                        Qt.PenStyle.SolidLine if snap else Qt.PenStyle.DashLine))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_from is not None:
            self._scene.removeItem(self._drag_line)
            start, target = self._drag_from, self._snap
            self._drag_from, self._drag_line, self._snap = None, None, None
            if target is not None:
                target.set_highlight(False)
                a, b = (start, target) if start.kind in (OUT, TOOL) else (target, start)
                if a.kind == OUT:
                    ok = self.graph.connect_main(a.node_item.node.id, a.name, b.node_item.node.id)
                else:
                    ok = self.graph.connect_tool(a.node_item.node.id, b.node_item.node.id)
                if ok:
                    self._rebuild_edges()
                    self.graph_changed.emit()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selection()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        """Clic droit : réglages ou suppression du nœud / du lien sous la souris."""
        from PySide6.QtWidgets import QMenu
        item = next((i for i in self.items(event.pos()) if isinstance(i, (NodeItem, EdgeItem))), None)
        menu = QMenu(self)
        if isinstance(item, NodeItem):
            self._scene.clearSelection()
            item.setSelected(True)
            menu.addAction("Réglages…", lambda: self.node_double_clicked.emit(item.node))
            if item.node.type == "scope":
                menu.addAction("Afficher le scope", lambda: self.scope_requested.emit(item.node))
            if not self.read_only:
                menu.addAction("Supprimer le nœud", self.delete_selection)
        elif isinstance(item, EdgeItem) and not self.read_only:
            self._scene.clearSelection()
            item.setSelected(True)
            menu.addAction("Supprimer le lien", self.delete_selection)
        else:
            menu.addAction("Voir tout le graphe", self.fit)
        menu.exec(event.globalPos())

    # ------------------------------------------------------------------ dépôt depuis la bibliothèque
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MIME) or self.read_only:
            return super().dropEvent(event)
        node_type, _, sensor = bytes(event.mimeData().data(MIME)).decode().partition("|")
        pos = self.mapToScene(event.position().toPoint())
        self.node_dropped.emit(node_type, sensor, QPointF(round(pos.x() / GRID) * GRID, round(pos.y() / GRID) * GRID))
        event.acceptProposedAction()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor(theme.BORDER), 1.5))
        left = int(rect.left()) - int(rect.left()) % GRID
        top = int(rect.top()) - int(rect.top()) % GRID
        points = [QPointF(x, y) for x in range(left, int(rect.right()), GRID) for y in range(top, int(rect.bottom()), GRID)]
        painter.drawPoints(points)
