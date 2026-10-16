import numpy as np
from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QIcon, QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QToolBar, QToolButton, QVBoxLayout, QWidget)
from mir_sim.model_builder import CONNECTOR_MARKER_GROUP
from mir_robot_editor.robot_model.joint_sliders_widget import JointSlidersWidget
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_robot_editor.robot_model.structure_editor_view_model import (ModuleInfo, PaletteItem, StructureEditorViewModel,
                                                                      StructureEditorVMAction)
from mir_robot_editor.robot_model.thumbnails import render_module_thumbnail
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui.widgets import DialogBase
from mir_utils.ui import theme

THUMBNAIL_SIZE = 56
PALETTE_MIME = "application/x-mir-palette-item"
KEY_ROLE = Qt.ItemDataRole.UserRole


class PaletteList(QListWidget):
    """Liste de gauche : les éléments se glissent vers la vue 3D (ou se cliquent)."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.setFixedWidth(220)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None or not item.data(KEY_ROLE):
            return
        mime = QMimeData()
        mime.setData(PALETTE_MIME, item.data(KEY_ROLE).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(item.icon().pixmap(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        drag.exec(Qt.DropAction.CopyAction)


class DropViewport(MujocoWidget):
    """Vue 3D qui accepte les éléments glissés depuis la liste."""
    drag_entered = Signal(str)
    drag_left = Signal()
    dropped = Signal(str, QPoint)   # élément, position dans le widget

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(PALETTE_MIME):
            event.acceptProposedAction()
            self.drag_entered.emit(bytes(event.mimeData().data(PALETTE_MIME)).decode())

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(PALETTE_MIME):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self.drag_left.emit()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(PALETTE_MIME):
            event.acceptProposedAction()
            self.dropped.emit(bytes(event.mimeData().data(PALETTE_MIME)).decode(), event.position().toPoint())


class StructureEditorView(DialogBase, ViewBase[StructureEditorViewModel, StructureEditorVMAction]):
    def __init__(self, parent, view_model: StructureEditorViewModel):
        super().__init__(parent, default_width=1200, default_height=760, disable_esc=True, view_model=view_model)
        self.setWindowTitle("Structure du robot")
        vm = self._view_model
        vm.model_changed.connect(self._on_model_changed)
        vm.model_message.connect(self._on_model_message)
        vm.palette_changed.connect(self._on_palette_changed)
        vm.selection_changed.connect(self._on_selection_changed)
        vm.status_changed.connect(lambda text: self._status.setText(text))
        vm.errors_changed.connect(self._on_errors_changed)
        vm.redraw_required.connect(lambda: self._viewport.update())
        vm.closed.connect(self.close)
        self._thumbnails: dict[str, QIcon] = {}
        self._palette_items: dict[str, PaletteItem] = {}

        # liste des modules
        self._palette = PaletteList()
        self._palette.itemClicked.connect(self._on_palette_clicked)
        palette_box = QVBoxLayout()
        palette_box.addWidget(QLabel("<b>Modules</b> (à glisser dans la vue)"))
        palette_box.addWidget(self._palette)

        # vue 3D
        self._viewport = DropViewport(self)
        self._viewport.scene_option.geomgroup[CONNECTOR_MARKER_GROUP] = 1
        self._viewport.geom_clicked.connect(vm.click_geom)
        self._viewport.drag_entered.connect(vm.preview_targets)
        self._viewport.drag_left.connect(vm.end_preview)
        self._viewport.dropped.connect(self._on_dropped)
        self._status = QLabel()
        self._status.setWordWrap(True)
        center = QVBoxLayout()
        center.addWidget(self._viewport, stretch=1)
        center.addWidget(self._status)
        center.addWidget(QLabel("Souris : glisser pour tourner, clic droit pour déplacer, molette pour zoomer."))

        # module sélectionné
        self._module_box = QGroupBox()
        form = QFormLayout(self._module_box)
        self._name_edit = QLineEdit()
        self._name_edit.editingFinished.connect(lambda: vm.rename(self._name_edit.text()))
        self._type_label = QLabel()
        self._type_label.setWordWrap(True)
        self._hardware_label = QLabel()
        self._attach_label = QLabel()
        self._attach_label.setWordWrap(True)
        self._change_connector = QToolButton()
        self._fixed_check = QCheckBox("Bâti (fixé au monde)")
        self._fixed_check.toggled.connect(vm.set_fixed)
        self._direction_check = QCheckBox("Sens de rotation inversé")
        self._direction_check.toggled.connect(vm.set_direction_inverted)
        self._delete_button = QToolButton()
        self._delete_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        form.addRow("Nom", self._name_edit)
        form.addRow("Type", self._type_label)
        form.addRow("Matériel", self._hardware_label)
        form.addRow("Branché sur", self._attach_label)
        form.addRow("", self._change_connector)
        form.addRow("", self._fixed_check)
        form.addRow("", self._direction_check)
        form.addRow("", self._delete_button)

        self._joints = JointSlidersWidget()
        self._joints.joint_changed.connect(vm.set_joint)
        self._errors = QLabel()
        self._errors.setWordWrap(True)
        self._errors.setStyleSheet(f"color: {theme.ERROR}")
        side = QVBoxLayout()
        side.addWidget(self._module_box)
        side.addWidget(QLabel("<b>Articulations</b> (degrés moteur)"))
        side.addWidget(self._joints)
        side.addStretch()
        side.addWidget(self._errors)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(320)

        content = QHBoxLayout()
        content.addLayout(palette_box)
        content.addLayout(center, stretch=1)
        content.addWidget(side_widget)

        # actions
        self._change_connector_action = self._make_action(StructureEditorVMAction.CHANGE_CONNECTOR, vm.change_connector)
        self._change_connector.setDefaultAction(self._change_connector_action)
        self._delete_action = self._make_action(StructureEditorVMAction.DELETE, vm.delete_selected, "remove")
        self._delete_button.setDefaultAction(self._delete_action)
        toolbar = QToolBar()
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._undo_action = self._make_action(StructureEditorVMAction.UNDO, vm.undo, "", "Ctrl+Z", toolbar=toolbar)
        self._redo_action = self._make_action(StructureEditorVMAction.REDO, vm.redo, "", "Ctrl+Shift+Z", toolbar=toolbar)
        toolbar.addSeparator()
        self._reframe_action = QAction(self._icon("select_all"), "Recadrer", self)
        self._reframe_action.setToolTip("Recadrer la vue sur tout le robot")
        self._reframe_action.triggered.connect(self._viewport.reset_camera)
        toolbar.addAction(self._reframe_action)
        self._zero_action = self._make_action(StructureEditorVMAction.ZERO_POSE, self._joints.set_all_zero, "robot", toolbar=toolbar)
        toolbar.addSeparator()
        self._accept_action = self._make_action(StructureEditorVMAction.ACCEPT, vm.accept, "apply", toolbar=toolbar)
        self._cancel_action = self._make_action(StructureEditorVMAction.CANCEL, vm.cancel, "close", toolbar=toolbar)
        for action in (self._undo_action, self._redo_action):
            self.addAction(action)   # raccourcis actifs dans toute la fenêtre

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(content, stretch=1)
        main_layout.addWidget(toolbar)

        self._on_selection_changed(None)
        vm.start()
        # miniatures après l'affichage de la fenêtre (rendu MuJoCo de chaque type de module)
        QTimer.singleShot(0, self._load_thumbnails)

    # ------------------------------------------------------------------ liste des modules
    def _load_thumbnails(self) -> None:
        for module_type in self._view_model.catalog():
            try:
                pixels = np.ascontiguousarray(render_module_thumbnail(module_type, THUMBNAIL_SIZE * 2))
            except Exception:
                continue
            image = QImage(pixels.data, pixels.shape[1], pixels.shape[0], 3 * pixels.shape[1], QImage.Format.Format_RGB888)
            self._thumbnails[module_type] = QIcon(QPixmap.fromImage(image.copy()))
        self._on_palette_changed(self._view_model.palette())

    def _on_palette_changed(self, items: list[PaletteItem]) -> None:
        self._palette_items = {item.key: item for item in items}
        self._palette.clear()
        detected = [item for item in items if not item.is_block and not item.is_new]
        new = [item for item in items if item.is_new]
        blocks = [item for item in items if item.is_block]
        groups = [("Modules du catalogue", new), ("Blocs de structure", blocks)]
        if detected:
            # matériel détecté par la découverte des appareils (absent d'un robot conçu sans matériel)
            groups.insert(0, ("Modules détectés", detected))
        for title, group in groups:
            header = QListWidgetItem(title)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setForeground(QColor(theme.TEXT_MUTED))
            self._palette.addItem(header)
            if not group:
                empty = QListWidgetItem("  (aucun)")
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                self._palette.addItem(empty)
            for item in group:
                widget_item = QListWidgetItem(item.label if item.placed_as is None else f"{item.label}\n→ {item.placed_as}")
                widget_item.setData(KEY_ROLE, item.key)
                icon = self._thumbnails.get(item.types[0]) if item.types else None
                if icon is not None:
                    widget_item.setIcon(icon)
                if item.placed_as is not None:
                    widget_item.setFlags(Qt.ItemFlag.ItemIsEnabled)   # visible mais ni sélectionnable ni glissable
                    widget_item.setForeground(QColor(theme.TEXT_DISABLED))
                    widget_item.setToolTip(f"Déjà placé : {item.placed_as}")
                else:
                    widget_item.setToolTip("Glissez dans la vue 3D, ou cliquez pour l'ajouter")
                self._palette.addItem(widget_item)

    def _on_palette_clicked(self, widget_item: QListWidgetItem) -> None:
        key = widget_item.data(KEY_ROLE)
        if key and self._palette_items[key].placed_as is None:
            self._drop(key, -1, self._palette.mapToGlobal(self._palette.visualItemRect(widget_item).center()))

    def _on_dropped(self, key: str, position: QPoint) -> None:
        self._drop(key, self._viewport.pick(position.toPointF()), self._viewport.mapToGlobal(position))

    def _drop(self, key: str, target_geom: int, menu_position: QPoint) -> None:
        item = self._palette_items[key]
        module_type = item.types[0] if len(item.types) == 1 else self._ask_type(item, menu_position)
        if module_type is None:
            self._view_model.end_preview()
            return
        self._view_model.drop(key, module_type, target_geom)
        self._palette.clearSelection()

    def _ask_type(self, item: PaletteItem, position: QPoint) -> str | None:
        """Un moteur peut être celui d'un servo ou d'une pince : le bus ne permet pas de le savoir."""
        menu = QMenu(self)
        menu.addSection(f"{item.label.split()[0]} est le moteur de :")
        for module_type in item.types:
            action = menu.addAction(module_type.removeprefix("mir_"))
            action.setData(module_type)
            if module_type in self._thumbnails:
                action.setIcon(self._thumbnails[module_type])
        chosen = menu.exec(position)
        return chosen.data() if chosen is not None else None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._view_model.cancel_placing()
            self._palette.clearSelection()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------ modèle
    def _on_model_changed(self, model, data, joints) -> None:
        self._viewport.set_model(model, data, keep_camera=self._viewport.has_model())
        self._joints.set_joints(joints, self._view_model.joint_values())

    def _on_model_message(self, message: str) -> None:
        self._viewport.show_message(message)
        self._joints.set_joints([])

    def _on_errors_changed(self, errors: list[str]) -> None:
        self._errors.setText("\n".join(f"• {e}" for e in errors))

    # ------------------------------------------------------------------ module sélectionné
    def _on_selection_changed(self, info: ModuleInfo | None) -> None:
        self._module_box.setEnabled(info is not None)
        widgets = (self._name_edit, self._fixed_check, self._direction_check)
        for widget in widgets:
            widget.blockSignals(True)
        if info is None:
            self._module_box.setTitle("Module sélectionné (cliquez un module)")
            for label in (self._name_edit, self._type_label, self._hardware_label, self._attach_label):
                label.clear()
            self._fixed_check.setVisible(False)
            self._direction_check.setVisible(False)
        else:
            self._module_box.setTitle(f"Module sélectionné : {info.name}")
            self._name_edit.setText(info.name)
            self._type_label.setText(info.type.removeprefix("mir_"))
            self._type_label.setToolTip(info.description)
            self._hardware_label.setText(info.hardware or "— (bloc de structure)")
            self._attach_label.setText("— (module de départ)" if info.is_root
                                       else f"{info.attached_to}, par son connecteur « {info.connector} »")
            self._fixed_check.setVisible(info.is_root)
            self._fixed_check.setChecked(info.fixed)
            self._direction_check.setVisible(info.has_joint)
            self._direction_check.setChecked(info.direction < 0)
        for widget in widgets:
            widget.blockSignals(False)

    def done(self, result):
        self._viewport.close()
        super().done(result)
