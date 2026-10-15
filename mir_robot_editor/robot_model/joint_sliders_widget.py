from __future__ import annotations
from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QSlider, QWidget

SLIDER_STEPS_PER_DEG = 10


@dataclass
class JointSlider:
    """Articulation pilotable, en degrés moteur (comme sur le robot réel : 0° = milieu de la plage calibrée)."""
    motor: str
    min_deg: float
    max_deg: float


class JointSlidersWidget(QWidget):
    """Un curseur par moteur ; émet joint_changed(moteur, degrés)."""
    joint_changed = Signal(str, float)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._sliders: dict[str, tuple[QSlider, QLabel]] = {}

    def set_joints(self, joints: list[JointSlider], values: dict[str, float] | None = None) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                # retrait immédiat (deleteLater laisserait l'ancien widget affiché jusqu'au prochain tour de boucle)
                item.widget().setParent(None)
        self._sliders.clear()
        values = values or {}
        for row, joint in enumerate(joints):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(int(joint.min_deg * SLIDER_STEPS_PER_DEG), int(joint.max_deg * SLIDER_STEPS_PER_DEG))
            value = QLabel()
            value.setFixedWidth(50)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._layout.addWidget(QLabel(joint.motor), row, 0)
            self._layout.addWidget(slider, row, 1)
            self._layout.addWidget(value, row, 2)
            self._sliders[joint.motor] = (slider, value)
            deg = values.get(joint.motor, 0.0)
            slider.setValue(int(round(deg * SLIDER_STEPS_PER_DEG)))
            value.setText(f"{deg:.1f}°")
            slider.valueChanged.connect(lambda v, m=joint.motor: self._on_slider(m, v))
        if not joints:
            self._layout.addWidget(QLabel("Aucune articulation motorisée"), 0, 0)

    def set_all_zero(self) -> None:
        for slider, _ in self._sliders.values():
            slider.setValue(0)

    def _on_slider(self, motor: str, value: int) -> None:
        deg = value / SLIDER_STEPS_PER_DEG
        self._sliders[motor][1].setText(f"{deg:.1f}°")
        self.joint_changed.emit(motor, deg)
