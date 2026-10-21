"""
Icônes et couleurs des nœuds de MIR Flow : une couleur par catégorie, une petite icône par nœud, dessinées au
pinceau (nettes à toutes les tailles, de la couleur voulue).
"""
from __future__ import annotations
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from mir_flow.graph import (NODE_ACTION, NODE_CONDITION, NODE_CONTINUOUS, NODE_END,
                            NODE_LLM, NODE_MEASURE, NODE_MESSAGE, NODE_SCOPE, NODE_REPEAT, NODE_SCRIPT, NODE_START, NODE_TRIGGER, NODE_VISION,
                            NODE_WAIT)
from mir_utils.ui import theme

# une teinte assourdie par catégorie (theme.py) ; les couleurs vives restent réservées aux états (nœud en cours,
# lien aimanté)
CATEGORY_COLORS = {"Déroulement": theme.FLOW_STEPS, "Percevoir": theme.FLOW_PERCEIVE, "Décider": theme.FLOW_DECIDE,
                   "Agir": theme.FLOW_ACT, "Communiquer": theme.FLOW_COMMUNICATE}
ICON_ON_LIGHT: set[str] = set()     # catégories à pastille claire (icône noire)


def icon_color(category: str) -> str:
    return theme.INK if category in ICON_ON_LIGHT else theme.SURFACE


def draw_icon(painter: QPainter, node_type: str, rect: QRectF, color: QColor | str) -> None:
    """Dessine l'icône du nœud dans le carré rect."""
    color = QColor(color)
    s = min(rect.width(), rect.height())
    c = rect.center()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, max(1.2, s / 12), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def p(x: float, y: float) -> QPointF:            # coordonnées de -1 à 1 dans le carré
        return QPointF(c.x() + x * s / 2, c.y() + y * s / 2)

    def poly(points, fill=False):
        polygon = QPolygonF([p(x, y) for x, y in points])
        if fill:
            painter.setBrush(color)
        painter.drawPolygon(polygon)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    t = node_type
    if t == NODE_START:
        poly([(-0.45, -0.6), (0.6, 0), (-0.45, 0.6)], fill=True)
    elif t == NODE_END:
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(p(-0.5, -0.5), p(0.5, 0.5)), s * 0.08, s * 0.08)
    elif t == NODE_CONTINUOUS:                       # infini : tourne sans s'arrêter
        path = QPainterPath()
        for i in range(61):
            u = 2 * math.pi * i / 60
            d = 1 + math.sin(u) ** 2
            point = p(0.85 * math.cos(u) / d, 0.85 * math.sin(u) * math.cos(u) / d * 1.3)
            path.moveTo(point) if i == 0 else path.lineTo(point)
        painter.drawPath(path)
    elif t == NODE_TRIGGER:                          # éclair
        poly([(0.15, -0.8), (-0.45, 0.1), (-0.02, 0.1), (-0.15, 0.8), (0.45, -0.1), (0.02, -0.1)], fill=True)
    elif t == NODE_REPEAT:                           # deux flèches en boucle
        r = QRectF(p(-0.62, -0.5), p(0.62, 0.5))
        painter.drawArc(r, 20 * 16, 140 * 16)
        painter.drawArc(r, 200 * 16, 140 * 16)
        painter.setBrush(color)
        for (x, y), d in (((0.55, -0.2), 1), ((-0.55, 0.2), -1)):
            painter.drawPolygon(QPolygonF([p(x - 0.2 * d, y), p(x + 0.2 * d, y), p(x, y + 0.25 * d)]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    elif t == NODE_WAIT:                             # horloge
        painter.drawEllipse(QRectF(p(-0.7, -0.7), p(0.7, 0.7)))
        painter.drawLine(p(0, 0), p(0, -0.45))
        painter.drawLine(p(0, 0), p(0.32, 0.12))
    elif t == NODE_MEASURE:                          # cadran avec son aiguille
        painter.drawArc(QRectF(p(-0.75, -0.6), p(0.75, 0.9)), 0, 180 * 16)
        painter.drawLine(p(-0.75, 0.15), p(0.75, 0.15))
        painter.drawLine(p(0, 0.15), p(0.42, -0.32))
        painter.setBrush(color)
        painter.drawEllipse(p(0, 0.15), s * 0.08, s * 0.08)
    elif t == NODE_VISION:                           # œil
        path = QPainterPath(p(-0.8, 0))
        path.quadTo(p(0, -0.75), p(0.8, 0))
        path.quadTo(p(0, 0.75), p(-0.8, 0))
        painter.drawPath(path)
        painter.setBrush(color)
        painter.drawEllipse(p(0, 0), s * 0.13, s * 0.13)
    elif t == NODE_CONDITION:                        # losange
        poly([(0, -0.75), (0.75, 0), (0, 0.75), (-0.75, 0)])
        painter.drawText(QRectF(p(-0.5, -0.5), p(0.5, 0.5)), Qt.AlignmentFlag.AlignCenter, "?")
    elif t == NODE_SCRIPT:                           # </>
        painter.drawPolyline(QPolygonF([p(-0.3, -0.5), p(-0.75, 0), p(-0.3, 0.5)]))
        painter.drawPolyline(QPolygonF([p(0.3, -0.5), p(0.75, 0), p(0.3, 0.5)]))
        painter.drawLine(p(0.12, -0.6), p(-0.12, 0.6))
    elif t == NODE_LLM:                              # étincelle
        path = QPainterPath(p(0, -0.8))
        for x, y in ((0.18, -0.18), (0.8, 0), (0.18, 0.18), (0, 0.8), (-0.18, 0.18), (-0.8, 0), (-0.18, -0.18),
                     (0, -0.8)):
            path.lineTo(p(x, y))
        painter.setBrush(color)
        painter.drawPath(path)
    elif t == NODE_ACTION:                           # engrenage
        painter.setBrush(color)
        teeth = 8
        outline = []
        for i in range(teeth * 2):
            radius = 0.75 if i % 2 == 0 else 0.55
            for da in (-0.17, 0.17):
                a = (i + 0.5 + da) * math.pi / teeth
                outline.append((radius * math.cos(a), radius * math.sin(a)))
        poly(outline, fill=True)
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawEllipse(p(0, 0), s * 0.13, s * 0.13)
    elif t == NODE_SCOPE:                            # écran d'oscilloscope avec une sinusoïde
        painter.drawRoundedRect(QRectF(p(-0.8, -0.6), p(0.8, 0.6)), s * 0.08, s * 0.08)
        path = QPainterPath(p(-0.6, 0))
        for i in range(1, 25):
            u = -0.6 + 1.2 * i / 24
            path.lineTo(p(u, -0.32 * math.sin(u * math.pi * 1.7)))
        painter.drawPath(path)
    elif t == NODE_MESSAGE:                          # bulle
        path = QPainterPath()
        path.addRoundedRect(QRectF(p(-0.8, -0.6), p(0.8, 0.35)), s * 0.12, s * 0.12)
        painter.drawPath(path)
        poly([(-0.35, 0.35), (-0.5, 0.75), (0.0, 0.35)], fill=True)
    painter.restore()


def icon_pixmap(node_type: str, size: int, color: QColor | str, background: QColor | str | None = None) -> QPixmap:
    pixmap = QPixmap(size * 2, size * 2)        # rendu net sur les écrans haute densité
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if background is not None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRectF(0, 0, size, size), size * 0.25, size * 0.25)
        draw_icon(painter, node_type, QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6), color)
    else:
        draw_icon(painter, node_type, QRectF(1, 1, size - 2, size - 2), color)
    painter.end()
    return pixmap
