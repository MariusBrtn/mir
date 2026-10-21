"""
Exécution d'un nœud Action, et mise en forme des observations pour un LLM.

Une action est toujours une Commande de MIR (consigne fixe, mini script ou politique entraînée), exécutée dans la
boucle habituelle (ExecutionCommande) : à chaque tour, robot.get_observation() -> commande.action() ->
robot.send_action(). Les consignes sont bornées aux plages des moteurs, et les moteurs s'arrêtent à la fin.
"""
from __future__ import annotations
import base64
import io
import types
from pathlib import Path
from typing import Any, Callable
import numpy as np
from mir_flow.graph import KIND_POLICY, KIND_SCRIPT, KIND_SETPOINT, Node
from mir_flow.robot_loop import StopRequested       # même exception partout
from mir_robot.commande import Commande

IMAGE_WIDTH = 512               # images envoyées au modèle (moins cher, assez pour décrire une scène)




class Setpoint(Commande):
    """Consigne fixe : les mêmes valeurs à chaque tour de boucle."""
    nom = "Consigne"

    def __init__(self, values: dict[str, float]):
        super().__init__()
        self.values = dict(values)

    def action(self, observation):
        return self.values


def load_script(code: str, name: str = "script") -> type[Commande]:
    """La classe Commande définie par un mini script."""
    module = types.ModuleType(f"mir_flow_script_{name}")
    exec(compile(code, f"<{name}>", "exec"), module.__dict__)
    classes = [c for c in module.__dict__.values()
               if isinstance(c, type) and issubclass(c, Commande) and c is not Commande and c.__module__ == module.__name__]
    if not classes:
        raise ValueError("le script doit définir une classe dérivée de Commande, avec une méthode action(self, observation)")
    return classes[0]


class ActionTool:
    """Un nœud Action prêt à tourner sur le robot."""

    def __init__(self, node: Node, robot_dir: Path | None):
        self.node = node
        self.robot_dir = robot_dir
        c = node.config
        self.kind = c.get("kind", KIND_SETPOINT)
        self.duration_s = float(c.get("duration_s") or 2.0)        # réglée dans le nœud, pas par le LLM

    def full_description(self) -> str:
        end = f"It stops by itself when done, at most after {self.duration_s:g} s." if self.kind != KIND_SETPOINT \
            else f"It runs for {self.duration_s:g} s, then the motors stop."
        c = self.node.config
        if (c.get("until") or "").strip():
            end += f" It stops earlier as soon as this condition is true: {c['until']}."
        return f"{c.get('description') or self.node.name}. {end}"

    def make_command(self) -> tuple[Commande, float, list[str]]:
        """(commande, fréquence de la boucle, observations dont elle a besoin)."""
        c = self.node.config
        if self.kind == KIND_SETPOINT:
            return Setpoint({k: float(v) for k, v in (c.get("setpoint") or {}).items()}), float(c.get("fps") or 20), []
        if self.kind == KIND_SCRIPT:
            return load_script(c.get("script", ""), self.node.name)(), float(c.get("fps") or 20), []
        if self.kind == KIND_POLICY:
            from mir_robot.training import load_policy, model_info
            if not c.get("policy"):
                raise ValueError("aucune politique choisie dans ce nœud")
            folder = Path(c["policy"]) if self.robot_dir is None else self.robot_dir / c["policy"]
            policy = load_policy(folder)
            fps = float(model_info(folder).get("fps") or c.get("fps") or 20)
            return policy, fps, list(policy.observations()) if hasattr(policy, "observations") else []
        raise ValueError(f"sorte d'action inconnue : {self.kind}")

    def execute(self, loop, should_stop: Callable[[], bool], until: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Fait tourner l'action dans la boucle robot pendant sa durée, jusqu'à ce qu'elle s'arrête d'elle-même, ou
        jusqu'à ce que until() soit vrai (« Arrêter quand »)."""
        command, fps, needed = self.make_command()
        result = loop.run_command(command, fps, self.duration_s, should_stop, until, needed)
        return {k: result[k] for k in ("duree", "fini_seul", "interrompu")}


def jpeg_data_url(image: np.ndarray) -> str:
    from PIL import Image
    picture = Image.fromarray(np.ascontiguousarray(image).astype(np.uint8))
    if picture.width > IMAGE_WIDTH:
        picture = picture.resize((IMAGE_WIDTH, round(picture.height * IMAGE_WIDTH / picture.width)))
    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
