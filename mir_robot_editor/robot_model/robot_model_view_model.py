from __future__ import annotations
from enum import Enum, auto
import mujoco
import numpy as np
from PySide6.QtCore import Signal
from mir_robot.mir_robot_config import mirRobotConfig
from mir_sim.model_builder import BuiltModel, StructureError, build_model
from mir_utils.concurrency import BackgroundWorker
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import VMAction, ViewModelBase
from mir_robot_editor.robot_model.joint_sliders_widget import JointSlider


class RobotModelVMAction(Enum):
    ZERO_POSE = auto()
    CLOSE = auto()


class RobotModelViewModel(ViewModelBase[RobotModelVMAction]):
    """Modèle 3D (lecture seule) du robot décrit par la section "structure" de la configuration."""
    model_ready = Signal(object, object, list)   # MjModel, MjData, list[JointSlider]
    load_failed = Signal(str)
    pose_changed = Signal()
    closed = Signal()

    def __init__(self, dialogProvider: IDialogProvider, config: mirRobotConfig):
        super().__init__(dialogProvider)
        self._config = config
        self._built: BuiltModel | None = None
        self._data: mujoco.MjData | None = None
        self._worker = BackgroundWorker()
        self._actions[RobotModelVMAction.ZERO_POSE] = VMAction("Pose zéro", "Remettre toutes les articulations à 0°")
        self._actions[RobotModelVMAction.CLOSE] = VMAction("Fermer", "Fermer la fenêtre", enabled=True)

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, traceback):
        self._worker.shutdown()

    # ------------------------------------------------------------------ chargement
    def load(self) -> None:
        """Construit le modèle en arrière-plan (lecture des STL : quelques secondes)."""
        self._worker.run(build_model, self._on_model_built, self._on_build_failed, fn_args=(self._config,))

    def _on_model_built(self, built: BuiltModel) -> None:
        self._built = built
        self._data = mujoco.MjData(built.model)
        mujoco.mj_forward(built.model, self._data)
        sliders = [JointSlider(motor, *info.range_deg) for motor, info in built.joints.items()]
        self._actions[RobotModelVMAction.ZERO_POSE].set_enabled(True)
        self.model_ready.emit(built.model, self._data, sliders)

    def _on_build_failed(self, error: Exception) -> None:
        if isinstance(error, StructureError):
            self.load_failed.emit("Structure du robot invalide :\n\n" + "\n".join(error.errors))
        else:
            self.load_failed.emit(f"Impossible de construire le modèle du robot :\n\n{error}")

    # ------------------------------------------------------------------ pose
    def set_joint(self, motor: str, motor_deg: float) -> None:
        if self._built is None or self._data is None:
            return
        info = self._built.joints[motor]
        joint_id = self._built.model.joint(info.joint_name).id
        lo, hi = self._built.model.jnt_range[joint_id]
        self._data.qpos[self._built.model.jnt_qposadr[joint_id]] = np.clip(info.motor_to_sim_rad(motor_deg), lo, hi)
        mujoco.mj_forward(self._built.model, self._data)
        self.pose_changed.emit()

    def zero_pose(self) -> None:
        if self._built is None:
            return
        for motor in self._built.joints:
            self.set_joint(motor, 0.0)

    def close(self) -> None:
        self.closed.emit()
