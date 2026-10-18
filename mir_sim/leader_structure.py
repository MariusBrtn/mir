"""
Bras et bras leader.

Un robot est un bras dès que sa structure contient au moins deux modules servo en série : un servo porté,
directement ou à travers des blocs passifs (jonction...), par un autre servo.

Le bras leader d'un bras se construit avec la même structure, ce qui donne les mêmes noms d'articulations :
la téléopération peut recopier ses positions telles quelles. Seule la chaîne mécanique est gardée (les capteurs,
comme la caméra, sont retirés) et la pince est remplacée par la pince du leader.
"""
from __future__ import annotations
from copy import deepcopy
from typing import Any
from mir_sim.model_builder import load_catalog

SERVO_TYPE = "mir_servo"
LEADER_REPLACEMENTS = {"mir_pince": "mir_pince_teleop"}     # module du robot -> module du bras leader


def _parent(inst: dict[str, Any]) -> str | None:
    return str(inst["on"]).partition(".")[0] if "on" in inst else None


def is_arm(structure: dict[str, Any] | None) -> bool:
    """Au moins deux modules servo en série."""
    modules = (structure or {}).get("modules", {})
    for inst in modules.values():
        if inst.get("type") != SERVO_TYPE:
            continue
        parent = _parent(inst)
        while parent is not None and parent in modules:
            if modules[parent].get("type") == SERVO_TYPE:
                return True
            parent = _parent(modules[parent])
    return False


def leader_structure(structure: dict[str, Any], catalog: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Structure du bras leader : celle du robot, sans les modules capteurs (et ce qu'ils portent),
    avec la pince du leader à la place de la pince."""
    catalog = catalog or load_catalog()
    leader = deepcopy(structure)
    modules: dict[str, Any] = leader.get("modules", {})
    removed = {name for name, inst in modules.items() if catalog.get(inst.get("type", ""), {}).get("sensors")}
    changed = True
    while changed:      # ce que portent les modules retirés est retiré aussi
        changed = False
        for name, inst in modules.items():
            if name not in removed and _parent(inst) in removed:
                removed.add(name)
                changed = True
    for name in removed:
        del modules[name]
    for inst in modules.values():
        inst["type"] = LEADER_REPLACEMENTS.get(inst["type"], inst["type"])
        inst.pop("sensors", None)
    return leader
