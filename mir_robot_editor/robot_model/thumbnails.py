"""Miniatures des modules du catalogue, rendues par MuJoCo (à appeler depuis le thread de l'interface)."""
from __future__ import annotations
import mujoco
import numpy as np
from mir_sim.model_builder import ModelBuilder


def render_module_thumbnail(module_type: str, size: int = 96) -> np.ndarray:
    """Image RGB (size x size) du module seul, articulations à zéro, sans le sol."""
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
