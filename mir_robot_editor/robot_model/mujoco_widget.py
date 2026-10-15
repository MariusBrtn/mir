"""
Widget Qt affichant un modèle MuJoCo (rendu hors écran de MuJoCo, affiché comme une image).

Souris : glisser (bouton gauche) pour tourner, bouton droit pour déplacer, molette pour zoomer.
Un clic gauche sans glisser émet geom_clicked(id de la géométrie sous la souris, -1 si aucune).
"""
from __future__ import annotations
import mujoco
import numpy as np
from PySide6.QtCore import Qt, QPointF, QTimer, Signal
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QWidget


CLICK_MAX_MOVE_PX = 4


class MujocoWidget(QWidget):
    geom_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        # groupes de géométries affichés (et sélectionnables) : modifiable par l'appelant
        self.scene_option = mujoco.MjvOption()
        self._press_pos: QPointF | None = None
        self._camera_moved_by_user = False
        self.setMinimumSize(320, 240)
        self._model: mujoco.MjModel | None = None
        self._data: mujoco.MjData | None = None
        self._renderer: mujoco.Renderer | None = None
        self._renderer_size: tuple[int, int] = (0, 0)
        self._camera = mujoco.MjvCamera()
        self._message = ""
        self._last_mouse: QPointF | None = None
        self._mouse_button = Qt.MouseButton.NoButton
        # recréer le rendu à la nouvelle taille seulement une fois le redimensionnement terminé
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._recreate_renderer)

    # ------------------------------------------------------------------ contenu
    def set_model(self, model: mujoco.MjModel, data: mujoco.MjData, keep_camera: bool = False) -> None:
        """keep_camera : garder le point de vue choisi par l'utilisateur (modèle reconstruit après une modification) ;
        tant qu'il n'a pas bougé la caméra, le modèle est recadré."""
        self._close_renderer()
        self._model, self._data = model, data
        self._message = ""
        if not (keep_camera and self._camera_moved_by_user):
            self.reset_camera()
        self.update()

    def has_model(self) -> bool:
        return self._model is not None

    def show_message(self, message: str) -> None:
        """Affiche un texte à la place du modèle (chargement, erreur...)."""
        self._close_renderer()
        self._model, self._data = None, None
        self._message = message
        self.update()

    def reset_camera(self) -> None:
        """Cadre l'ensemble des corps (sans le sol, qui fausserait l'étendue du modèle)."""
        self._camera_moved_by_user = False
        if self._model is None or self._data is None:
            return
        self._camera.type = mujoco.mjtCamera.mjCAMERA_FREE
        mujoco.mj_kinematics(self._model, self._data)
        points = self._data.xpos[1:] if self._model.nbody > 1 else self._data.xpos
        low, high = points.min(axis=0), points.max(axis=0)
        self._camera.lookat[:] = (low + high) / 2
        self._camera.distance = 2.5 * max(float(np.max(high - low)), 0.1)
        self._camera.azimuth = -135.0
        self._camera.elevation = -20.0
        self.update()

    def close(self) -> bool:
        self._close_renderer()
        return super().close()

    # ------------------------------------------------------------------ rendu
    def _render_size(self) -> tuple[int, int]:
        ratio = self.devicePixelRatioF()
        return max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio))

    def _recreate_renderer(self) -> None:
        self._close_renderer()
        self.update()

    def _close_renderer(self) -> None:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    def _ensure_renderer(self) -> None:
        if self._renderer is not None or self._model is None:
            return
        width, height = self._render_size()
        # le tampon hors écran du modèle doit être au moins aussi grand que l'image demandée
        self._model.vis.global_.offwidth = max(self._model.vis.global_.offwidth, width)
        self._model.vis.global_.offheight = max(self._model.vis.global_.offheight, height)
        self._renderer = mujoco.Renderer(self._model, height, width)
        self._renderer_size = (width, height)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.darkGray)
        if self._model is None or self._data is None:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message)
            return
        self._ensure_renderer()
        assert self._renderer is not None
        self._renderer.update_scene(self._data, self._camera, self.scene_option)
        pixels = np.ascontiguousarray(self._renderer.render())
        height, width = pixels.shape[:2]
        image = QImage(pixels.data, width, height, 3 * width, QImage.Format.Format_RGB888)
        # l'image garde sa résolution pendant un redimensionnement : elle est étirée en attendant le nouveau rendu
        painter.drawImage(self.rect(), image)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._renderer is not None and self._render_size() != self._renderer_size:
            self._resize_timer.start()

    # ------------------------------------------------------------------ souris
    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last_mouse = event.position()
        self._press_pos = event.position()
        self._mouse_button = event.button()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        is_click = (self._mouse_button == Qt.MouseButton.LeftButton and self._press_pos is not None
                    and (event.position() - self._press_pos).manhattanLength() <= CLICK_MAX_MOVE_PX)
        self._last_mouse = None
        self._press_pos = None
        self._mouse_button = Qt.MouseButton.NoButton
        if is_click:
            self.geom_clicked.emit(self.pick(event.position()))

    def pick(self, position: QPointF) -> int:
        """Géométrie visible sous ce point du widget (-1 si aucune)."""
        if self._renderer is None or self._model is None or self._data is None:
            return -1
        selpnt = np.zeros(3)
        geomid, flexid, skinid = np.array([-1], np.int32), np.array([-1], np.int32), np.array([-1], np.int32)
        mujoco.mjv_select(self._model, self._data, self.scene_option, self.width() / self.height(),
                          position.x() / self.width(), 1.0 - position.y() / self.height(),
                          self._renderer.scene, selpnt, geomid, flexid, skinid)
        return int(geomid[0])

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._last_mouse is None or self._renderer is None or self._model is None:
            return
        delta = event.position() - self._last_mouse
        self._last_mouse = event.position()
        if self._mouse_button == Qt.MouseButton.LeftButton:
            action = mujoco.mjtMouse.mjMOUSE_ROTATE_V
        elif self._mouse_button == Qt.MouseButton.RightButton:
            action = mujoco.mjtMouse.mjMOUSE_MOVE_V
        else:
            action = mujoco.mjtMouse.mjMOUSE_ZOOM
        mujoco.mjv_moveCamera(self._model, action, delta.x() / self.height(), delta.y() / self.height(),
                              self._renderer.scene, self._camera)
        self._camera_moved_by_user = True
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._renderer is None or self._model is None:
            return
        steps = event.angleDelta().y() / 120.0
        mujoco.mjv_moveCamera(self._model, mujoco.mjtMouse.mjMOUSE_ZOOM, 0, -0.05 * steps,
                              self._renderer.scene, self._camera)
        self._camera_moved_by_user = True
        self.update()
