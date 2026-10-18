"""
Édition à la souris de la structure d'un robot (section "structure" de la configuration).

La liste de gauche contient :
  - les modules détectés de la configuration, chacun une seule fois (bijection) : un module motorisé par moteur
    du bus (servo, pince...), un module caméra par caméra ;
  - les modules du catalogue qui portent un moteur ou un capteur, utilisables autant de fois que nécessaire :
    chaque module déposé crée un nouveau moteur ou capteur (conception d'un robot sans matériel) ;
  - les blocs de structure inertes du catalogue (socle, jonction...), utilisables autant de fois que nécessaire.
On les dépose dans la vue 3D : la position est entièrement déterminée par le connecteur choisi (pas de
placement libre). Le socle est toujours présent (bâti par défaut). Le catalogue n'est pas modifiable ici.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any
import mujoco
import numpy as np
from PySide6.QtCore import Signal
from mir_robot.mir_robot_config import mirRobotConfig
from mir_sim.model_builder import (MATING_GENDERS, ROOT_TYPE, BuiltModel, ModelBuilder, StructureError, check_structure,
                                   hardware_module_name, load_catalog, module_sensor_key, motor_module_types,
                                   motor_params_from_config, sensor_module_types)
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import VMAction, ViewModelBase
from mir_utils.ui import theme
from mir_robot_editor.robot_model.joint_sliders_widget import JointSlider

MARKER_RGBA = theme.MARKER_FREE_RGBA                    # connecteur libre
MARKER_COMPATIBLE_RGBA = theme.MARKER_COMPATIBLE_RGBA   # connecteur où le module en cours de placement peut se brancher
MARKER_DIMMED_RGBA = theme.MARKER_DIMMED_RGBA           # connecteur libre mais incompatible
SELECTION_RGBA = np.array(theme.SELECTION_RGBA)
SELECTION_BLEND = 0.55


class StructureEditorVMAction(Enum):
    UNDO = auto()
    REDO = auto()
    CHANGE_CONNECTOR = auto()
    DELETE = auto()
    ZERO_POSE = auto()
    ACCEPT = auto()
    CANCEL = auto()


@dataclass
class PaletteItem:
    """Élément de la liste de gauche."""
    key: str                    # "unplaced:<module>", "motor:joint_1", "sensor:cam_1", "new:mir_servo" ou "block:mir_jonction"
    label: str
    types: list[str]            # types de module possibles (plusieurs : choix au dépôt, ex. servo ou pince)
    placed_as: str | None       # module de la structure qui le représente déjà (modules détectés seulement)
    is_block: bool
    is_new: bool = False        # module du catalogue : crée un nouveau moteur ou capteur


@dataclass
class ModuleInfo:
    """Ce que le panneau latéral affiche du module sélectionné."""
    name: str
    type: str
    description: str
    is_root: bool
    fixed: bool
    attached_to: str                 # "module.connecteur" du parent ("" pour la racine)
    connector: str                   # connecteur de ce module utilisé pour le branchement
    hardware: str                    # moteur ou capteur de la configuration représenté ("" pour un bloc)
    has_joint: bool
    direction: int


class StructureEditorViewModel(ViewModelBase[StructureEditorVMAction]):
    model_changed = Signal(object, object, list)   # MjModel, MjData, list[JointSlider]
    model_message = Signal(str)                     # texte à afficher quand il n'y a pas de modèle
    palette_changed = Signal(list)                  # list[PaletteItem]
    selection_changed = Signal(object)              # ModuleInfo | None
    status_changed = Signal(str)
    errors_changed = Signal(list)
    redraw_required = Signal()
    closed = Signal()

    def __init__(self, dialogProvider: IDialogProvider, config: mirRobotConfig):
        super().__init__(dialogProvider)
        self._config = config
        self._catalog = load_catalog()
        self._structure: dict[str, Any] = deepcopy(config.structure) if config.structure else {"modules": {}}
        self._structure.setdefault("modules", {})
        self._structure.setdefault("unplaced", {})   # modules détectés pas encore branchés
        self._motors = list(config.motor_bus.motors) if config.motor_bus is not None else []
        self._sensors = list(config.sensors)
        # moteurs et capteurs créés dans cet éditeur par les modules du catalogue (pas encore dans la configuration)
        self._created_motors: list[str] = []
        self._created_sensors: list[str] = []
        self._motor_params = motor_params_from_config(config)
        self._built: BuiltModel | None = None
        self._data: mujoco.MjData | None = None
        self._base_rgba: np.ndarray | None = None
        self._selected: str | None = None
        self._placing: tuple[str, str] | None = None     # (élément de la liste, type de module) en attente d'un connecteur
        self._joint_values: dict[str, float] = {}
        self._undo: list[tuple] = []     # instantanés de _snapshot()
        self._redo: list[tuple] = []
        self._accepted = False
        add = self._actions.__setitem__
        add(StructureEditorVMAction.UNDO, VMAction("Annuler l'action", "Annuler la dernière modification de la structure"))
        add(StructureEditorVMAction.REDO, VMAction("Rétablir", "Rétablir la modification annulée"))
        add(StructureEditorVMAction.CHANGE_CONNECTOR, VMAction(
            "Changer de connecteur", "Brancher le module sélectionné par un autre de ses connecteurs"))
        add(StructureEditorVMAction.DELETE, VMAction("Supprimer", "Supprimer le module sélectionné et les modules branchés dessus"))
        add(StructureEditorVMAction.ZERO_POSE, VMAction("Pose zéro", "Remettre toutes les articulations à 0°"))
        add(StructureEditorVMAction.ACCEPT, VMAction("Valider", "Enregistrer la structure dans la configuration", enabled=True))
        add(StructureEditorVMAction.CANCEL, VMAction("Fermer sans enregistrer", "Fermer sans modifier la configuration", enabled=True))

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, traceback):
        pass

    # ------------------------------------------------------------------ accès
    @property
    def modules(self) -> dict[str, dict[str, Any]]:
        return self._structure["modules"]

    @property
    def unplaced(self) -> dict[str, dict[str, Any]]:
        return self._structure["unplaced"]

    def catalog(self) -> dict[str, dict[str, Any]]:
        return self._catalog

    def start(self) -> None:
        """À appeler une fois la vue prête : socle par défaut si la structure est vide, puis modèle initial."""
        if not self.modules and ROOT_TYPE in self._catalog:
            self.modules[self._unique_name("socle")] = {"type": ROOT_TYPE, "fixed": True}
        self._rebuild()
        self._update_status()

    def accepted(self) -> bool:
        return self._accepted

    def get_structure(self) -> dict[str, Any] | None:
        if not self.modules:
            return None
        structure = deepcopy(self._structure)
        if not structure["unplaced"]:
            del structure["unplaced"]
        return structure

    # ------------------------------------------------------------------ liste de gauche
    def palette(self) -> list[PaletteItem]:
        """Un élément par moteur et par caméra de la configuration (bijection), puis les blocs de structure.
        Le module qui représente un matériel vient de la découverte ("unplaced", type déjà choisi) ; à défaut
        (configuration plus ancienne), le type est demandé au dépôt."""
        items: list[PaletteItem] = []
        hardware = [(f"motor:{motor}", self._motor_label(motor), {"motor": motor}, motor_module_types(self._catalog))
                    for motor in self._motors if motor not in self._created_motors]
        for sensor in self._sensors:
            if sensor in self._created_sensors:
                continue
            types = sensor_module_types(self._catalog, self._config.sensors[sensor].sensor_type)
            if types:
                hardware.append((f"sensor:{sensor}", sensor, {"sensor": sensor}, types))
        for fallback_key, label, match, types in hardware:
            placed = next((name for name, inst in self.modules.items() if self._carries(inst, match)), None)
            waiting = next((name for name, inst in self.unplaced.items() if self._carries(inst, match)), None)
            if placed is not None:
                items.append(PaletteItem(f"placed:{placed}", label, [self.modules[placed]["type"]], placed, False))
            elif waiting is not None:
                module_type = self.unplaced[waiting]["type"]
                items.append(PaletteItem(f"unplaced:{waiting}", f"{label} · {module_type.removeprefix('mir_')}",
                                         [module_type], None, False))
            else:
                items.append(PaletteItem(fallback_key, label, types, None, False))
        for module_type, module in self._catalog.items():
            if not module.get("leader_only") and (module.get("joints") or module.get("sensors")):
                items.append(PaletteItem(f"new:{module_type}", module_type.removeprefix("mir_"), [module_type], None,
                                         False, is_new=True))
        for module_type, module in self._catalog.items():
            if not module.get("leader_only") and (not module.get("joints") and not module.get("sensors")):
                items.append(PaletteItem(f"block:{module_type}", module_type.removeprefix("mir_"), [module_type], None, True))
        return items

    def _motor_label(self, motor: str) -> str:
        if self._config.motor_bus is None or motor not in self._config.motor_bus.motors:
            return motor
        return f"{motor}  (ID {self._config.motor_bus.motors[motor].id})"

    @staticmethod
    def _carries(inst: dict[str, Any], match: dict[str, str]) -> bool:
        if "motor" in match:
            return inst.get("motor") == match["motor"] or match["motor"] in inst.get("motors", {}).values()
        return match["sensor"] in inst.get("sensors", {}).values()

    def _palette_item(self, key: str) -> PaletteItem:
        return next(item for item in self.palette() if item.key == key)

    # ------------------------------------------------------------------ dépôt d'un module
    def compatible_targets(self, module_type: str) -> list[str]:
        """Connecteurs libres sur lesquels un module de ce type peut se brancher."""
        genders = {conn["gender"] for conn in self._catalog[module_type].get("connectors", {}).values()}
        return [key for key in self._free_connectors()
                if any((gender, self._connector(key)["gender"]) in MATING_GENDERS for gender in genders)]

    def preview_targets(self, item_key: str) -> None:
        """Pendant un glisser : allume les connecteurs où l'élément peut se brancher."""
        item = self._palette_item(item_key)
        targets = set().union(*(self.compatible_targets(t) for t in item.types)) if item.types else set()
        self._color_markers(targets)

    def end_preview(self) -> None:
        if self._placing is None:
            self._color_markers(None)

    def can_drop(self, item_key: str) -> str | None:
        """None si l'élément peut être déposé, sinon la raison."""
        item = self._palette_item(item_key)
        if item.placed_as is not None:
            return f"{item.label.split()[0]} est déjà placé ({item.placed_as})"
        if not any(self.compatible_targets(t) for t in item.types):
            return "aucun connecteur libre ne peut le recevoir"
        return None

    def drop(self, item_key: str, module_type: str, target_geom: int = -1) -> None:
        """Dépose un module de la liste. Sur une pastille compatible : branché dessus. Ailleurs : branché
        directement s'il n'y a qu'une possibilité, sinon on demande de cliquer le point de connexion."""
        reason = self.can_drop(item_key)
        if reason is not None:
            self._dialogProvider.information("Impossible d'ajouter ce module", reason[0].upper() + reason[1:] + ".")
            self.end_preview()
            return
        targets = self.compatible_targets(module_type)
        target = self._built.connector_markers.get(target_geom) if self._built is not None else None
        if target in targets:
            self._place(item_key, module_type, target)
        elif len(targets) == 1:
            self._place(item_key, module_type, targets[0])
        elif not targets:
            self._dialogProvider.information("Impossible d'ajouter ce module",
                                             f"Aucun connecteur libre ne peut recevoir un module {module_type}.")
            self.end_preview()
        else:
            self._placing = (item_key, module_type)
            self._color_markers(set(targets))
            self._update_status()

    def cancel_placing(self) -> None:
        if self._placing is not None:
            self._placing = None
            self._color_markers(None)
            self._update_status()

    def click_geom(self, geom_id: int) -> None:
        if self._built is None:
            return
        target = self._built.connector_markers.get(geom_id)
        if self._placing is not None:
            item_key, module_type = self._placing
            if target is not None and target in self.compatible_targets(module_type):
                self._place(item_key, module_type, target)
            return
        if target is not None:
            self.status_changed.emit(f"Connecteur libre {target} : glissez un module de la liste dessus pour l'y brancher.")
            return
        body = int(self._built.model.geom_bodyid[geom_id]) if geom_id >= 0 else -1
        self._select(self._built.body_module.get(body))

    def _place(self, item_key: str, module_type: str, target: str) -> None:
        self._push_undo()
        target_gender = self._connector(target)["gender"]
        connector = next(name for name, conn in self._catalog[module_type]["connectors"].items()
                         if (conn["gender"], target_gender) in MATING_GENDERS)
        kind, _, ref = item_key.partition(":")
        instance: dict[str, Any] = {"type": module_type}
        if kind == "unplaced":
            # module détecté, type choisi à la découverte du matériel
            name = ref
            instance.update(self.unplaced.pop(ref))
        elif kind == "motor":
            name = self._unique_name(hardware_module_name(module_type, ref))
            instance["motor"] = ref
        elif kind == "sensor":
            name = self._unique_name(hardware_module_name(module_type, ref))
            instance["sensors"] = {module_sensor_key(self._catalog[module_type], self._config.sensors[ref].sensor_type): ref}
        elif kind == "new":
            # module du catalogue : nouveau moteur (une articulation) ou nouveaux capteurs
            module = self._catalog[module_type]
            if len(module.get("joints", {})) == 1:
                joint = next(iter(module["joints"].values()))
                # une roue (articulation asservie en vitesse) s'appelle roue_N, une articulation joint_N
                motor = self._new_hardware_name("roue" if joint.get("mode") == "velocity" else "joint", self._motors)
                self._motors.append(motor)
                self._created_motors.append(motor)
                instance["motor"] = motor
                name = self._unique_name(hardware_module_name(module_type, motor))
            else:
                name = self._unique_name(module_type.removeprefix("mir_"))
            sensors = {}
            for key, sensor in module.get("sensors", {}).items():
                prefixe = {"camera": "cam", "lidar": "lidar"}.get(sensor.get("type", ""), key)
                sensor_name = self._new_hardware_name(prefixe, self._sensors)
                self._sensors.append(sensor_name)
                self._created_sensors.append(sensor_name)
                sensors[key] = sensor_name
            if sensors:
                instance["sensors"] = sensors
                if "motor" not in instance:
                    name = self._unique_name(hardware_module_name(module_type, next(iter(sensors.values()))))
        else:
            name = self._unique_name(module_type.removeprefix("mir_"))
        instance.update({"on": target, "connector": connector})
        self._set_default_direction(instance)
        self.modules[name] = instance
        self._placing = None
        self._selected = name
        self._rebuild()
        self._update_status()

    def _free_connectors(self) -> list[str]:
        used = set()
        for name, inst in self.modules.items():
            if "on" in inst:
                used.update({str(inst["on"]), f"{name}.{inst['connector']}"})
        return [f"{name}.{conn}" for name, inst in self.modules.items()
                for conn in self._catalog[inst["type"]].get("connectors", {}) if f"{name}.{conn}" not in used]

    def _connector(self, key: str) -> dict[str, Any]:
        name, _, conn = key.partition(".")
        return self._catalog[self.modules[name]["type"]]["connectors"][conn]

    def _new_hardware_name(self, base: str, taken: list[str]) -> str:
        """joint_1, joint_2... : premier nom libre parmi les moteurs (ou capteurs) existants."""
        index = 1
        while f"{base}_{index}" in taken:
            index += 1
        return f"{base}_{index}"

    def _unique_name(self, base: str) -> str:
        taken = set(self.modules) | set(self.unplaced)
        if base not in taken:
            return base
        index = 2
        while f"{base}_{index}" in taken:
            index += 1
        return f"{base}_{index}"

    # ------------------------------------------------------------------ module sélectionné
    def _select(self, name: str | None) -> None:
        self._selected = name
        self._update_selection_tint()
        self._emit_selection()

    def change_connector(self) -> None:
        """Branche le module sélectionné par son connecteur compatible suivant (ex. servo par le rotor ou le stator)."""
        choices = self._connector_choices(self._selected)
        if self._selected is None or len(choices) < 2:
            return
        self._push_undo()
        inst = self.modules[self._selected]
        inst["connector"] = choices[(choices.index(inst["connector"]) + 1) % len(choices)]
        self._set_default_direction(inst)
        self._rebuild()

    def _set_default_direction(self, inst: dict[str, Any]) -> None:
        """Sens par défaut d'un module à moteur : inversé quand il est branché par sa pièce entraînée (servo posé
        rotor en premier), c'est ce que le guide de montage constate à chaque fois. Modifiable ensuite (sens inversé)."""
        module = self._catalog[inst["type"]]
        joints = module.get("joints", {})
        if len(joints) != 1 or "connector" not in inst:
            return
        part = module["connectors"][inst["connector"]]["part"]
        if part == next(iter(joints.values()))["child"]:
            inst["direction"] = -1
        else:
            inst.pop("direction", None)

    def _connector_choices(self, name: str | None) -> list[str]:
        if name is None or "on" not in self.modules.get(name, {}):
            return []
        inst = self.modules[name]
        parent_gender = self._connector(str(inst["on"]))["gender"]
        used_by_children = {str(child["on"]).partition(".")[2] for child in self.modules.values()
                            if str(child.get("on", "")).partition(".")[0] == name}
        return [conn_name for conn_name, conn in self._catalog[inst["type"]]["connectors"].items()
                if (conn["gender"], parent_gender) in MATING_GENDERS and conn_name not in used_by_children]

    def set_direction_inverted(self, inverted: bool) -> None:
        inst = self._selected_instance()
        if inst is None or (int(inst.get("direction", 1)) < 0) == inverted:
            return
        self._push_undo()
        if inverted:
            inst["direction"] = -1
        else:
            inst.pop("direction", None)
        self._rebuild()

    def set_fixed(self, fixed: bool) -> None:
        inst = self._selected_instance()
        if inst is None or "on" in inst or bool(inst.get("fixed", False)) == fixed:
            return
        self._push_undo()
        inst["fixed"] = fixed
        self._rebuild()

    def rename(self, new_name: str) -> bool:
        old = self._selected
        new_name = new_name.strip()
        if old is None or new_name == old:
            return True
        if not new_name or "." in new_name or new_name in self.modules or new_name in self.unplaced:
            self._dialogProvider.information("Nom invalide", "Le nom doit être unique, non vide et sans point.")
            self._emit_selection()
            return False
        self._push_undo()
        self._structure["modules"] = {(new_name if name == old else name): inst for name, inst in self.modules.items()}
        for inst in self.modules.values():
            parent, _, conn = str(inst.get("on", "")).partition(".")
            if parent == old:
                inst["on"] = f"{new_name}.{conn}"
        self._selected = new_name
        self._rebuild()
        return True

    def delete_selected(self) -> None:
        if self._selected is None or "on" not in self.modules[self._selected]:
            return
        removed = self._descendants(self._selected)
        if len(removed) > 1 and not self._dialogProvider.question_yes_no(
                "Supprimer", f"Supprimer {self._selected} et les modules branchés dessus ({', '.join(removed[1:])}) ?"):
            return
        self._push_undo()
        for name in removed:
            inst = self.modules.pop(name)
            self._joint_values.pop(inst.get("motor"), None)
            if self._forget_created(inst):
                continue    # créé dans cet éditeur : il disparaît avec son module
            if "motor" in inst or "motors" in inst or "sensors" in inst:
                # module qui représente du matériel détecté : il retourne dans la liste, avec son type
                self.unplaced[name] = {k: v for k, v in inst.items() if k not in ("on", "connector")}
        self._selected = None
        self._rebuild()
        self._update_status()

    def _forget_created(self, inst: dict[str, Any]) -> bool:
        """Retire les moteurs et capteurs créés dans cet éditeur par ce module ; True si le module en avait créé."""
        motors = ([inst["motor"]] if "motor" in inst else []) + list(inst.get("motors", {}).values())
        sensors = list(inst.get("sensors", {}).values())
        created = [m for m in motors if m in self._created_motors] + [c for c in sensors if c in self._created_sensors]
        if not created:
            return False
        for motor in motors:
            if motor in self._created_motors:
                self._created_motors.remove(motor)
                self._motors.remove(motor)
        for sensor in sensors:
            if sensor in self._created_sensors:
                self._created_sensors.remove(sensor)
                self._sensors.remove(sensor)
        return True

    def _descendants(self, name: str) -> list[str]:
        result = [name]
        for child, inst in self.modules.items():
            if str(inst.get("on", "")).partition(".")[0] == name:
                result += self._descendants(child)
        return result

    def _selected_instance(self) -> dict[str, Any] | None:
        return self.modules.get(self._selected) if self._selected is not None else None

    # ------------------------------------------------------------------ annuler / rétablir
    def _snapshot(self) -> tuple:
        return (deepcopy(self._structure), self._selected, list(self._motors), list(self._sensors),
                list(self._created_motors), list(self._created_sensors))

    def _push_undo(self) -> None:
        self._undo.append(self._snapshot())
        self._redo.clear()

    def undo(self) -> None:
        self._restore(self._undo, self._redo)

    def redo(self) -> None:
        self._restore(self._redo, self._undo)

    def _restore(self, source: list, target: list) -> None:
        if not source:
            return
        target.append(self._snapshot())
        (self._structure, self._selected, self._motors, self._sensors,
         self._created_motors, self._created_sensors) = source.pop()
        self._placing = None
        self._rebuild()
        self._update_status()

    # ------------------------------------------------------------------ articulations
    def set_joint(self, motor: str, motor_deg: float) -> None:
        self._joint_values[motor] = motor_deg
        self._apply_joint(motor)
        if self._built is not None and self._data is not None:
            mujoco.mj_forward(self._built.model, self._data)
        self.redraw_required.emit()

    def _apply_joint(self, motor: str) -> None:
        if self._built is None or self._data is None or motor not in self._built.joints:
            return
        info = self._built.joints[motor]
        joint_id = self._built.model.joint(info.joint_name).id
        lo, hi = self._built.model.jnt_range[joint_id]
        self._data.qpos[self._built.model.jnt_qposadr[joint_id]] = np.clip(
            info.motor_to_sim_rad(self._joint_values.get(motor, 0.0)), lo, hi)

    def joint_values(self) -> dict[str, float]:
        return dict(self._joint_values)

    # ------------------------------------------------------------------ validation
    def accept(self) -> None:
        errors = check_structure(self._structure, self._catalog, self._motors, self._sensors) if self.modules else []
        if errors:
            self._dialogProvider.warning("Structure invalide", "La structure ne peut pas être enregistrée :\n\n" + "\n".join(errors))
            return
        missing = [item.label.split()[0] for item in self.palette()
                   if not item.is_block and not item.is_new and item.placed_as is None]
        # les modules non placés restent dans la configuration ("unplaced") : on pourra les placer plus tard
        if missing and not self._dialogProvider.question_yes_no(
                "Modules non placés",
                f"Ces modules détectés ne sont pas placés : {', '.join(missing)}.\nEnregistrer quand même ?"):
            return
        self._accepted = True
        self.closed.emit()

    def cancel(self) -> None:
        self.closed.emit()

    # ------------------------------------------------------------------ modèle 3D
    def _rebuild(self) -> None:
        if self._selected is not None and self._selected not in self.modules:
            self._selected = None
        self._actions[StructureEditorVMAction.UNDO].set_enabled(bool(self._undo))
        self._actions[StructureEditorVMAction.REDO].set_enabled(bool(self._redo))
        self.palette_changed.emit(self.palette())
        self.errors_changed.emit(check_structure(self._structure, self._catalog, self._motors, self._sensors)
                                 if self.modules else [])
        if not self.modules:
            self._built, self._data = None, None
            self.model_message.emit("Aucun module")
            self._emit_selection()
            return
        try:
            # construction tolérante (moteurs et capteurs vérifiés à part) pour voir le robot pendant l'édition
            self._built = ModelBuilder(self._structure, self._motor_params, connector_markers=True).build()
        except StructureError as e:
            self._built, self._data = None, None
            self.model_message.emit("Structure invalide :\n\n" + "\n".join(e.errors))
            self._emit_selection()
            return
        self._data = mujoco.MjData(self._built.model)
        self._base_rgba = self._built.model.geom_rgba.copy()
        for motor in self._built.joints:
            self._apply_joint(motor)
        mujoco.mj_forward(self._built.model, self._data)
        self._color_markers(None)
        self._update_selection_tint()
        joints = [JointSlider(motor, *info.range_deg) for motor, info in self._built.joints.items()]
        self.model_changed.emit(self._built.model, self._data, joints)
        self._actions[StructureEditorVMAction.ZERO_POSE].set_enabled(bool(joints))
        self._emit_selection()

    def _color_markers(self, highlighted: set[str] | None) -> None:
        """highlighted : connecteurs à allumer en vert (les autres sont estompés) ; None : tous en bleu."""
        if self._built is None:
            return
        for geom_id, key in self._built.connector_markers.items():
            if highlighted is None:
                rgba = MARKER_RGBA
            else:
                rgba = MARKER_COMPATIBLE_RGBA if key in highlighted else MARKER_DIMMED_RGBA
            self._built.model.geom_rgba[geom_id] = rgba
        self.redraw_required.emit()

    def _update_selection_tint(self) -> None:
        if self._built is None or self._base_rgba is None:
            return
        model = self._built.model
        for geom_id in range(model.ngeom):
            if geom_id in self._built.connector_markers:
                continue
            rgba = self._base_rgba[geom_id]
            if self._selected is not None and self._built.body_module.get(int(model.geom_bodyid[geom_id])) == self._selected:
                rgba = (1 - SELECTION_BLEND) * rgba + SELECTION_BLEND * SELECTION_RGBA
            model.geom_rgba[geom_id] = rgba
        self.redraw_required.emit()

    def _emit_selection(self) -> None:
        inst = self._selected_instance()
        self._actions[StructureEditorVMAction.DELETE].set_enabled(inst is not None and "on" in inst)
        self._actions[StructureEditorVMAction.CHANGE_CONNECTOR].set_enabled(len(self._connector_choices(self._selected)) > 1)
        if inst is None or self._selected is None:
            self.selection_changed.emit(None)
            return
        module = self._catalog[inst["type"]]
        hardware = [inst["motor"]] if "motor" in inst else list(inst.get("motors", {}).values())
        hardware += list(inst.get("sensors", {}).values())
        if "motor" in inst and self._config.motor_bus is not None and inst["motor"] in self._config.motor_bus.motors:
            hardware[0] += f" (ID {self._config.motor_bus.motors[inst['motor']].id})"
        elif "motor" in inst and inst["motor"] in self._created_motors:
            hardware[0] += " (nouveau)"
        self.selection_changed.emit(ModuleInfo(
            name=self._selected, type=inst["type"], description=module.get("description", ""),
            is_root="on" not in inst, fixed=bool(inst.get("fixed", False)),
            attached_to=str(inst.get("on", "")), connector=inst.get("connector", ""),
            hardware=", ".join(hardware), has_joint=len(module.get("joints", {})) == 1,
            direction=int(inst.get("direction", 1))))

    def _update_status(self) -> None:
        if self._placing is not None:
            self.status_changed.emit("Plusieurs points de connexion possibles : cliquez la pastille verte où brancher "
                                     f"{self._placing[1].removeprefix('mir_')} (Échap pour annuler).")
        else:
            self.status_changed.emit("Glissez un module de la liste dans la vue 3D (sur une pastille pour choisir où le "
                                     "brancher). Cliquez un module pour le régler.")
