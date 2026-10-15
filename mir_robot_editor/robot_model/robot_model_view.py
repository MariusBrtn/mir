from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolBar, QVBoxLayout, QWidget
from mir_robot_editor.robot_model.joint_sliders_widget import JointSlider, JointSlidersWidget
from mir_robot_editor.robot_model.mujoco_widget import MujocoWidget
from mir_robot_editor.robot_model.robot_model_view_model import RobotModelViewModel, RobotModelVMAction
from mir_utils.ui.view_base import ViewBase
from mir_utils.ui.widgets import DialogBase


class RobotModelView(DialogBase, ViewBase[RobotModelViewModel, RobotModelVMAction]):
    def __init__(self, parent, view_model: RobotModelViewModel):
        super().__init__(parent, default_width=1000, default_height=700, view_model=view_model)
        self.setWindowTitle("Modèle 3D du robot")
        self._view_model.model_ready.connect(self._on_model_ready)
        self._view_model.load_failed.connect(self._on_load_failed)
        self._view_model.pose_changed.connect(self._on_pose_changed)
        self._view_model.closed.connect(self.close)

        self._viewport = MujocoWidget(self)
        self._viewport.show_message("Construction du modèle...")

        self._joints_panel = JointSlidersWidget()
        self._joints_panel.joint_changed.connect(self._view_model.set_joint)
        help_label = QLabel("Souris : glisser pour tourner, clic droit pour déplacer, molette pour zoomer.")
        help_label.setWordWrap(True)

        side_layout = QVBoxLayout()
        side_layout.addWidget(QLabel("<b>Articulations</b> (degrés moteur)"))
        side_layout.addWidget(self._joints_panel)
        side_layout.addStretch()
        side_layout.addWidget(help_label)
        side = QWidget()
        side.setLayout(side_layout)
        side.setFixedWidth(280)

        content = QHBoxLayout()
        content.addWidget(self._viewport, stretch=1)
        content.addWidget(side)

        toolbar = QToolBar()
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._zero_pose_action = self._make_action(RobotModelVMAction.ZERO_POSE, self._on_zero_pose, "robot", toolbar=toolbar)
        self._close_action = self._make_action(RobotModelVMAction.CLOSE, self._view_model.close, "close", toolbar=toolbar)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(content, stretch=1)
        main_layout.addWidget(toolbar)

        self._view_model.load()

    def _on_model_ready(self, model, data, sliders: list[JointSlider]) -> None:
        self._viewport.set_model(model, data)
        self._joints_panel.set_joints(sliders)

    def _on_load_failed(self, message: str) -> None:
        self._viewport.show_message(message)

    def _on_zero_pose(self) -> None:
        self._joints_panel.set_all_zero()

    def _on_pose_changed(self) -> None:
        self._viewport.update()

    def done(self, result):
        self._viewport.close()
        super().done(result)
