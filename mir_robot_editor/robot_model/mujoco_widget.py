"""
Widget Qt affichant un modèle MuJoCo (rendu hors écran de MuJoCo, affiché comme une image).

Souris : glisser (bouton gauche) pour tourner, bouton droit pour déplacer, molette pour zoomer.
Un clic gauche sans glisser émet geom_clicked(id de la géométrie sous la souris, -1 si aucune).
Robot simulé (set_sim_world) : les objets libres de la scène se déplacent à la souris, glisser un objet le fait glisser
sur la table et la molette sur un objet le fait tourner.
"""
from __future__ import annotations
import math
import mujoco
import numpy as np
from PySide6.QtCore import Qt, QPointF, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QWidget
from mir_utils.ui import theme


CLICK_MAX_MOVE_PX = 4
ROTATION_PAR_CRAN_DEG = 15.0        # molette sur un objet de la scène


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
        self._lock = None      # verrou du monde simulé, quand la physique tourne dans un autre thread
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
        self._world = None              # monde simulé dont les objets se déplacent à la souris
        self._drag: tuple[str, float, np.ndarray] | None = None     # objet saisi : nom, hauteur, décalage souris -> objet

    # ------------------------------------------------------------------ contenu
    def set_model(self, model: mujoco.MjModel, data: mujoco.MjData, keep_camera: bool = False, lock=None) -> None:
        """keep_camera : garder le point de vue choisi par l'utilisateur (modèle reconstruit après une modification) ;
        tant qu'il n'a pas bougé la caméra, le modèle est recadré.
        lock : verrou à prendre pour lire data (robot simulé dont la physique tourne en temps réel)."""
        self._close_renderer()
        self._model, self._data = model, data
        self._lock = lock
        self._message = ""
        if not (keep_camera and self._camera_moved_by_user):
            self.reset_camera()
        self.update()

    def set_sim_world(self, world) -> None:
        """Affiche le robot simulé (SimWorld) ; les objets libres de sa scène se déplacent à la souris."""
        self._world = world
        self._drag = None
        self.setMouseTracking(True)         # curseur « main » au-dessus d'un objet déplaçable
        self.set_model(world.model, world.data, keep_camera=True, lock=world.lock)

    def has_model(self) -> bool:
        return self._model is not None

    def show_message(self, message: str) -> None:
        """Affiche un texte à la place du modèle (chargement, erreur...)."""
        self._close_renderer()
        self._model, self._data, self._lock = None, None, None
        self._world, self._drag = None, None
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
        painter.fillRect(self.rect(), QColor(theme.PANEL))
        if self._model is None or self._data is None:
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message)
            return
        self._ensure_renderer()
        assert self._renderer is not None
        if self._lock is not None:
            with self._lock:
                self._renderer.update_scene(self._data, self._camera, self.scene_option)
        else:
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
        if event.button() == Qt.MouseButton.LeftButton:
            self._saisir(event.position())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None:
            self._drag = None
            self._last_mouse = self._press_pos = None
            self._mouse_button = Qt.MouseButton.NoButton
            self._update_cursor(event.position())
            return
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
        if self._drag is not None:
            self._glisser(event.position())
            return
        if self._last_mouse is None:
            self._update_cursor(event.position())
            return
        if self._renderer is None or self._model is None:
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
        objet = self._objet_sous(event.position())
        if objet is not None:
            self._tourner(objet, steps * ROTATION_PAR_CRAN_DEG)
            return
        mujoco.mjv_moveCamera(self._model, mujoco.mjtMouse.mjMOUSE_ZOOM, 0, -0.05 * steps,
                              self._renderer.scene, self._camera)
        self._camera_moved_by_user = True
        self.update()

    # ------------------------------------------------------------------ objets de la scène (robot simulé)
    def _objet_sous(self, position: QPointF) -> str | None:
        """Objet libre de la scène sous la souris (son nom), ou None."""
        if self._world is None or self._model is None:
            return None
        geom = self.pick(position)
        if geom < 0:
            return None
        corps = self._model.body(int(self._model.body_rootid[self._model.geom_bodyid[geom]])).name
        try:
            self._model.joint(f"{corps}_free")       # objet libre de la scène (pas le robot)
        except KeyError:
            return None
        return corps

    def _rayon(self, position: QPointF) -> tuple[np.ndarray, np.ndarray]:
        """Rayon (origine, direction) partant de la caméra et passant par ce point du widget (comme mjv_select)."""
        scene = self._renderer.scene
        camera = mujoco.mjv_averageCamera(scene.camera[0], scene.camera[1])
        avant, haut = np.array(camera.forward), np.array(camera.up)
        droite = np.cross(avant, haut)
        relx, rely = position.x() / self.width(), 1.0 - position.y() / self.height()
        demi_largeur = 0.5 * self.width() / self.height() * (camera.frustum_top - camera.frustum_bottom)
        x = camera.frustum_center + (2 * relx - 1) * demi_largeur
        y = camera.frustum_bottom + rely * (camera.frustum_top - camera.frustum_bottom)
        direction = avant * camera.frustum_near + droite * x + haut * y
        return np.array(camera.pos), direction / np.linalg.norm(direction)

    def _sur_le_plan(self, position: QPointF, hauteur: float) -> np.ndarray | None:
        """Point (x, y) du plan horizontal z = hauteur sous la souris, ou None (souris au-dessus de l'horizon)."""
        origine, direction = self._rayon(position)
        if abs(direction[2]) < 1e-6:
            return None
        t = (hauteur - origine[2]) / direction[2]
        return (origine + t * direction)[:2] if t > 0 else None

    def _saisir(self, position: QPointF) -> None:
        objet = self._objet_sous(position)
        if objet is None:
            return
        centre = self._world.get_object_position(objet)
        point = self._sur_le_plan(position, centre[2])
        if point is None:
            return
        self._drag = (objet, float(centre[2]), centre[:2] - point)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _glisser(self, position: QPointF) -> None:
        objet, hauteur, decalage = self._drag
        point = self._sur_le_plan(position, hauteur)
        if point is None:
            return
        x, y = point + decalage
        self._world.set_object_pose(objet, [x, y, hauteur], self._lacet(objet))
        self.update()

    def _tourner(self, objet: str, angle_deg: float) -> None:
        centre = self._world.get_object_position(objet)
        self._world.set_object_pose(objet, centre, self._lacet(objet) + angle_deg)
        self.update()

    def _lacet(self, objet: str) -> float:
        """Orientation (°) de l'objet autour de la verticale."""
        with self._world.lock:
            w, x, y, z = self._world.data.xquat[self._model.body(objet).id]
        return math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))

    def _update_cursor(self, position: QPointF) -> None:
        if self._world is None:
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._objet_sous(position) is not None
                       else Qt.CursorShape.ArrowCursor)
