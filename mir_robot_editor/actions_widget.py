from __future__ import annotations
from PySide6 import QtCore
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QLayout
)
from mir_devices.mir_device import DeviceAction
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui.widgets import DoubleLineEdit

class MotorBlock(QFrame):
    motor_action_changed = Signal(object) 

    def __init__(self, action_data:DeviceAction, parent: MotorActionWidget) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.full_name = action_data.full_name()
        self._action_data = action_data

        self.setObjectName("MotorBlock")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        root = QVBoxLayout(self)
        root.setContentsMargins(4,4,4,4)
        root.setSpacing(2)

        #===== header    
        header_layout = QHBoxLayout()
        title = QLabel(f"{self._action_data.device_name}", self)
        title.setStyleSheet("font-weight: bold;")
        title.setObjectName("MotorTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
       
        header_layout.addWidget(title)

        self._btn_add = QToolButton(self)
        self._btn_add.setIcon(ViewBase.find_icon("add"))
        self._btn_add.setIconSize(QSize(14, 14))
        self._btn_add.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        header_layout.addWidget(self._btn_add)
        self._btn_add.clicked.connect(self.btn_add_clicked)
        self._btn_remove = QToolButton(self)
        self._btn_remove.setIcon(ViewBase.find_icon("remove"))
        self._btn_remove.setIconSize(QSize(14, 14))
        self._btn_remove.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        header_layout.addWidget(self._btn_remove)
        self._btn_remove.clicked.connect(self.btn_remove_clicked)

        root.addLayout(header_layout)

        #===== grid ====
        grid = QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)

        grid.addWidget(QLabel(self._action_data.action_name, self), 0, 0)
        self.target_value=DoubleLineEdit(action_data.get_value(), width=70)
        grid.addWidget(self.target_value, 0, 1)
        grid.addWidget(QLabel(self._action_data.get_unit()), 0, 2)
        root.addLayout(grid)

        #===== toolbar =======
        toolbar = QHBoxLayout()
        toolbar.setSpacing(0)
        self._btn_apply = QToolButton(self)
        self._btn_apply.setIcon(ViewBase.find_icon("execute"))
        self._btn_apply.setIconSize(QSize(24, 24))
        self._btn_apply.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        toolbar.addWidget(self._btn_apply)
        self._btn_apply.clicked.connect(self.btn_apply_clicked)
        toolbar.addStretch()

        root.addLayout(toolbar)

    def btn_apply_clicked(self):
        value = self.target_value()
        if value is not None:
            self._action_data.set_value(value)
            self.motor_action_changed.emit(self._action_data)

    def btn_add_clicked(self):
        self.parent_widget.add_to_group(self)

    def btn_remove_clicked(self):
        self.parent_widget.remove_from_group(self)

    def set_enabled(self, is_enabled: bool):
        self.target_value.setEnabled(is_enabled)
        self._btn_add.setEnabled(is_enabled)
        self._btn_remove.setEnabled(is_enabled)
        self._btn_apply.setEnabled(is_enabled)

    def make_action(self):
        value = self.target_value()
        if value is None:
            return None
        self._action_data.set_value(value)
        return self._action_data
    
class MotorActionWidget(QWidget):
    motor_action_changed = Signal(object)
    def __init__(
        self, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._blocks: dict[str, MotorBlock] = {}
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(10)

    def add_to_group(self, block: MotorBlock):
        if block.full_name in self._actions_group_dict:
            return
        lbl_action =QLabel(block.full_name)
        self._actions_group.addWidget(lbl_action)
        self._actions_group_dict[block.full_name] = lbl_action
        self._btn_execute_group.setEnabled(len(self._actions_group_dict)>0)

    def remove_from_group(self, block: MotorBlock):
        if block.full_name not in self._actions_group_dict:
            return
        lbl = self._actions_group_dict[block.full_name]
        self._actions_group.removeWidget(lbl)
        lbl.deleteLater()
        del self._actions_group_dict[block.full_name]
        self._btn_execute_group.setEnabled(len(self._actions_group_dict)>0)

    def make_groups_layout(self):
        self._actions_group = QVBoxLayout()
        self._actions_group_dict = {}
        groups_layout = QVBoxLayout()
        groups_layout_title = QLabel("Groupe d'actions")
        groups_layout_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        groups_layout.addWidget(groups_layout_title)
        groups_layout.addLayout(self._actions_group)
        self._btn_execute_group = QToolButton()
        self._btn_execute_group.setIcon(ViewBase.find_icon("execute"))
        self._btn_execute_group.setIconSize(QSize(24, 24))
        self._btn_execute_group.clicked.connect(self.btn_execute_group_clicked)
        self._btn_execute_group.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self._btn_execute_group.setEnabled(False)
        groups_layout.addWidget(self._btn_execute_group)
        return groups_layout

    def btn_execute_group_clicked(self):
        actions = []
        for key in self._actions_group_dict:
            block = self._blocks.get(key)
            if block:
                act = block.make_action()
                if act is None:
                    return
                actions.append(act)
        self.motor_action_changed.emit(actions)

    def build_ui(self, actions:dict[str, DeviceAction] | None = None) -> None:
        self._clear()
        if actions is None or len(actions) == 0:
            self._is_empty = True
            return
        self._is_empty = False        
        for key, action in actions.items():
            block = MotorBlock(action, self)
            block.motor_action_changed.connect(self.motor_action_changed)
            self._blocks[key] = block
            self._layout.addWidget(block)
        self._layout.addLayout(self.make_groups_layout())

        self._layout.addStretch(1)
        self.set_enabled(False)

    def _clear(self) -> None:
        """Retire et détruit tous les éléments du layout principal."""
        self._blocks.clear()

        def clear_layout(layout: QLayout):
            while layout.count():
                item = layout.takeAt(0)
                if item is None:
                    continue
                # Cas 1 : c'est un widget
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                    continue

                # Cas 2 : c'est un sous-layout
                sublayout = item.layout()
                if sublayout is not None:
                    clear_layout(sublayout)
                    # Très important : détruire le layout lui-même
                    sublayout.deleteLater()

        clear_layout(self._layout)

    def set_enabled(self, is_enabled: bool):
        if self._is_empty:
            return
        for block in self._blocks.values():
            block.set_enabled(is_enabled)
        self._btn_execute_group.setEnabled(is_enabled and len(self._actions_group_dict) > 0)

