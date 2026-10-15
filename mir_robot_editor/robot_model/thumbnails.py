"""Miniatures des modules du catalogue, rendues par MuJoCo (à appeler depuis le thread de l'interface)."""
from __future__ import annotations
import mujoco
import numpy as np
from mir_sim.model_builder import ModelBuilder


_CACHE: dict[tuple[str, int], np.ndarray] = {}


def render_module_thumbnail(module_type: str, size: int = 96) -> np.ndarray:
    """Image RGB (size x size) du module seul, articulations à zéro, sans le sol (mise en cache)."""
    if (module_type, size) not in _CACHE:
        _CACHE[(module_type, size)] = _render(module_type, size)
    return _CACHE[(module_type, size)]


def _render(module_type: str, size: int) -> np.ndarray:
    built = ModelBuilder({"modules": {"module": {"type": module_type, "fixed": True}}}).build()
    model = built.model
    model.geom_rgba[model.geom("table").id][3] = 0.0
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    visible = [g for g in range(model.ngeom) if model.geom_group[g] < 3 and model.geom_rgba[g][3] > 0]
    center = np.mean([data.geom_xpos[g] for g in visible], axis=0)
    camera = mujoco.MjvCamera()
    camera.lookat[:] = center
    camera.distance = 2.2 * max(float(np.max(model.geom_rbound[visible])), 0.03)
    camera.azimuth, camera.elevation = -135.0, -25.0
    with mujoco.Renderer(model, size, size) as renderer:
        renderer.update_scene(data, camera)
        return renderer.render().copy()


def module_icon(module_type: str, size: int = 56):
    """QIcon de la miniature (None si le module ne peut pas être rendu)."""
    from PySide6.QtGui import QIcon, QImage, QPixmap
    try:
        pixels = np.ascontiguousarray(render_module_thumbnail(module_type, size * 2))
    except Exception:
        return None
    image = QImage(pixels.data, pixels.shape[1], pixels.shape[0], 3 * pixels.shape[1], QImage.Format.Format_RGB888)
    return QIcon(QPixmap.fromImage(image.copy()))

