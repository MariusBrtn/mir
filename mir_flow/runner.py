"""
Exécution d'un MIR Flow : on part du nœud Départ et on suit les liens d'exécution. Chaque nœud fait son travail
(action sur le robot, lecture d'un capteur, traitement, condition, attente, question au LLM…), range son résultat
sous son nom dans les données du flux, puis désigne sa sortie (« suite », ou « oui » / « non » pour un Si…).
Le flux s'arrête sur un nœud Fin, sur une sortie qui ne mène nulle part, ou quand on clique sur Arrêter.

Entrée d'un nœud : le résultat du nœud précédent (« entree »), comme dans n8n. Toutes les données du flux restent
lisibles par leur nom (« donnees », ou lidar.points dans une expression).

Les nœuds outils (actions, capteurs, perception) s'exécutent de la même façon quand un LLM les appelle.

Utilisable aussi en script :
    runner = FlowRunner(robot, Graph.load(flow_path(dossier_robot)), dossier_robot, api_key=get_api_key())
    runner.run()
"""
from __future__ import annotations
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable
import numpy as np
from loguru import logger
from mir_flow import perception
from mir_flow.graph import (CONTINUOUS_OK, NODE_ACTION, NODE_CONDITION, NODE_CONTINUOUS, NODE_END,
                            NODE_LLM, NODE_MEASURE, NODE_MESSAGE, NODE_SCOPE, QUANTITIES, SOURCE_SERVOS, NODE_REPEAT, NODE_SCRIPT, NODE_START, NODE_TRIGGER,
                            NODE_VISION, NODE_WAIT, Graph, Node)
from mir_flow.robot_loop import RobotLoop
from mir_flow.tools import ActionTool, StopRequested, jpeg_data_url

MIN_STEP_S = 0.01               # pause minimale entre deux nœuds (une boucle sans action ne bloque pas l'ordinateur)
SAFE_BUILTINS = {"abs": abs, "min": min, "max": max, "round": round, "len": len, "int": int, "float": float,
                 "str": str, "bool": bool, "True": True, "False": False, "None": None}
BITMAP, POLAR = "ObservablePropertyBitmap", "ObservablePropertyPolar"


@dataclass
class FlowEvent:
    """Ce qui se passe pendant un flux ou une discussion, pour l'affichage."""
    kind: str               # "node" (nœud en cours), "step" (résultat d'un nœud), "io" (entrée et sortie d'un
    #                         nœud), "scope" (valeur à afficher), "message", "call", "result", "reply", "trigger",
    #                         "error", "end"
    text: str
    data: dict[str, Any] = field(default_factory=dict)


class FlowData(dict):
    """Les données du flux : résultat de chaque nœud (sous son nom) et variables (nœud Calculer).
    Une variable pas encore définie vaut 0 dans les expressions."""

    def __missing__(self, key):
        return 0


@dataclass
class RunContext:
    """Ce dont un nœud a besoin pour s'exécuter."""
    robot: Any
    graph: Graph
    robot_dir: Path | None = None
    api_key: str | None = None
    should_stop: Callable[[], bool] = lambda: False
    on_event: Callable[[FlowEvent], None] = lambda e: None
    data: FlowData = field(default_factory=FlowData)
    images: list[tuple[str, str]] | None = None         # images à joindre (appel d'outil par un LLM), sinon None
    counters: dict[str, int] = field(default_factory=dict)
    agents: dict[str, Any] = field(default_factory=dict)
    entree: dict[str, Any] = field(default_factory=dict)        # résultat du nœud précédent
    observation: dict[str, Any] | None = None           # surveillance : observation fournie
    loop: RobotLoop | None = None                       # la boucle robot : seule à lire et commander le robot
    detectors: dict[Any, Any] = field(default_factory=dict)
    _client: Any = None

    def client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("pas de clé OpenAI : connectez votre compte (bouton « Compte »)")
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, timeout=60)
        return self._client

    def sleep(self, seconds: float):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            if self.should_stop():
                raise StopRequested
            time.sleep(min(0.02, max(0.0, end - time.perf_counter())))


# ---------------------------------------------------------------------- expressions et textes
def namespace(data: FlowData, entree: dict[str, Any] | None = None) -> FlowData:
    """Les résultats des nœuds deviennent des objets : lidar.points, camera.image, entree.valeur…"""
    ns = FlowData({k: SimpleNamespace(**v) if isinstance(v, dict) else v for k, v in data.items()})
    ns["entree"] = SimpleNamespace(**(entree or {}))
    return ns


def evaluate(expression: str, data: FlowData, entree: dict[str, Any] | None = None) -> Any:
    try:
        return eval(compile(expression, "<expression>", "eval"), {"__builtins__": SAFE_BUILTINS},
                    namespace(data, entree))
    except SyntaxError as e:
        raise ValueError(f"expression mal écrite « {expression} » : {e.msg}") from None
    except AttributeError as e:
        raise ValueError(f"« {expression} » : {e} (le nœud a-t-il déjà tourné ? son nom est-il bon ?)") from None


class _Template(dict):
    def __missing__(self, key):
        return "?"


def fill(text: str, data: FlowData, entree: dict[str, Any] | None = None) -> str:
    """Remplace les {nom} et {noeud.champ} d'un texte par les données du flux."""
    ns = _Template(namespace(data, entree))

    def one(match):
        try:
            return str(("{" + match.group(1) + "}").format_map(ns))
        except (AttributeError, KeyError, IndexError, ValueError):
            return "?"
    return re.sub(r"\{([^{}]+)\}", one, text)


def load_process(code: str, name: str = "script") -> Callable:
    """La fonction traiter(entree, donnees) d'un nœud Script."""
    module = ModuleType(f"mir_flow_process_{name}")
    exec(compile(code, f"<{name}>", "exec"), module.__dict__)
    function = module.__dict__.get("traiter")
    if not callable(function):
        raise ValueError("le script doit définir une fonction traiter(entree, donnees)")
    return function


# ---------------------------------------------------------------------- capteurs
def measure_source(node: Node, robot) -> tuple[str, str | None]:
    """Source d'un nœud Mesure : ("camera" | "lidar" | "servos", nom du capteur). Une source « camera » ou « lidar »
    sans nom (anciens graphes) désigne le premier capteur de ce type."""
    source = node.config.get("source") or ""
    if source == SOURCE_SERVOS:
        return SOURCE_SERVOS, None
    kinds = {n: type(o).__name__ for n, o in robot.get_observables().items()}
    if source in kinds:
        return ("camera" if kinds[source] == BITMAP else "lidar" if kinds[source] == POLAR else "autre"), source
    wanted = {"camera": BITMAP, "lidar": POLAR}.get(source)
    first = next((n for n, k in kinds.items() if k == wanted), None) if wanted else None
    if first is None:
        raise ValueError(f"source « {source or '(aucune)'} » absente du robot : choisissez-la dans les réglages")
    return source, first


def servo_names(node: Node, robot) -> list[tuple[str, str, str]]:
    """(grandeur, servo, observation) lus par un nœud Mesure de source « servos »."""
    observables = robot.get_observables()
    motors = sorted({n.rsplit(".", 1)[0] for n in observables if "." in n})
    result = []
    for quantity in node.config.get("quantities") or ["position"]:
        suffix = QUANTITIES.get(quantity, (quantity, ""))[0]
        result += [(quantity, m, f"{m}.{suffix}") for m in motors if f"{m}.{suffix}" in observables]
    return result


def observations_of(node: Node, robot) -> list[str]:
    """Observations dont un nœud a besoin (activées dans la boucle robot)."""
    if node.type == NODE_MEASURE:
        try:
            kind, sensor = measure_source(node, robot)
        except ValueError:
            return []
        return [o for _, _, o in servo_names(node, robot)] if kind == SOURCE_SERVOS else [sensor]
    return []


def read_measure(node: Node, ctx: RunContext) -> dict[str, Any]:
    """Un nœud Mesure : la dernière observation de la boucle robot, pour la source choisie."""
    kind, sensor = measure_source(node, ctx.robot)
    names = observations_of(node, ctx.robot)
    observation = ctx.observation if ctx.observation is not None else ctx.loop.read(names)
    # temps écoulé depuis le lancement (s), à l'instant de la mesure : pour calculer des intervalles (odométrie…)
    temps = round(ctx.loop.latest_time - ctx.loop.start_time, 3) if ctx.loop is not None else 0.0
    if kind == SOURCE_SERVOS:
        result: dict[str, Any] = {}
        for quantity, motor, name in servo_names(node, ctx.robot):
            value = observation.get(name)
            result.setdefault(quantity, {})[motor] = round(float(value), 2) if value is not None else None
        result["temps"] = temps
        return result
    value = observation.get(sensor)
    if value is None:
        raise ValueError(f"pas de mesure de {sensor}")
    if kind == "camera":
        if ctx.images is not None:              # appel par un LLM : l'image lui est jointe
            ctx.images.append((node.name, jpeg_data_url(value)))
        return {"image": value, "largeur": int(value.shape[1]), "hauteur": int(value.shape[0]), "temps": temps}
    if kind == "lidar":
        return {"points": np.asarray(value, dtype=float), "temps": temps}
    return {"valeur": value, "temps": temps}


# ---------------------------------------------------------------------- surveillance d'une action
def stop_condition(node: Node, ctx: RunContext) -> Callable[[], bool] | None:
    """La condition « Arrêter quand » d'une action, évaluée à chaque tour de la boucle robot sur les données du flux
    (que les chaînes « En continu » tiennent à jour)."""
    until = (node.config.get("until") or "").strip()
    if not until:
        return None
    try:
        compile(until, "<condition>", "eval")
    except SyntaxError as e:
        raise ValueError(f"« Arrêter quand » : condition mal écrite ({e.msg})") from None

    def condition() -> bool:
        # une donnée pas encore calculée (chaîne en continu qui démarre) : la condition est fausse
        try:
            return bool(evaluate(until, ctx.data))
        except ValueError:
            return False
    return condition


# ---------------------------------------------------------------------- nœuds
def execute_node(node: Node, ctx: RunContext) -> tuple[str | None, dict[str, Any]]:
    """Exécute un nœud. Renvoie (sortie choisie ou None pour arrêter le flux, résultat)."""
    c, t, robot = node.config, node.type, ctx.robot
    if t in (NODE_START, NODE_CONTINUOUS, NODE_TRIGGER):
        return "suite", {}
    if t == NODE_END:
        return None, {}
    if t == NODE_ACTION:
        result = ActionTool(node, ctx.robot_dir).execute(ctx.loop, ctx.should_stop, stop_condition(node, ctx))
        return ("interrompu" if result["interrompu"] else "suite"), result
    if t == NODE_MEASURE:
        return "suite", read_measure(node, ctx)
    if t == NODE_VISION:
        image = ctx.entree.get("image")
        if not isinstance(image, np.ndarray) or image.ndim != 3:
            raise ValueError("pas d'image en entrée : placez juste avant un nœud Mesure dont la source est une caméra")
        unknown = perception.unknown_labels((c.get("classes") or "").split(","))
        if unknown:
            raise ValueError(f"objet inconnu {', '.join(unknown)}")
        key = (node.id, min(1.0, float(c.get("score_min") or 0.5)), int(c.get("max_results") or 10))
        if key not in ctx.detectors:
            ctx.detectors[key] = perception.ObjectDetector(key[1], key[2])
        detections = ctx.detectors[key].detect(image, (c.get("classes") or "").split(","))
        return "suite", {"detections": detections, "nombre": len(detections)}
    if t == NODE_SCRIPT:
        result = load_process(c.get("code", ""), node.name)(dict(ctx.entree), ctx.data)
        return "suite", result if isinstance(result, dict) else {"valeur": result}
    if t == NODE_CONDITION:
        ok = bool(evaluate(c.get("expression") or "False", ctx.data, ctx.entree))
        return ("oui" if ok else "non"), {"resultat": ok}
    if t == NODE_REPEAT:
        done = ctx.counters.get(node.id, 0)
        if done < int(c.get("count") or 0):
            ctx.counters[node.id] = done + 1
            return "encore", {"tour": done + 1}
        ctx.counters[node.id] = 0           # la boucle pourra resservir
        return "fini", {"tour": done}
    if t == NODE_WAIT:
        ctx.sleep(float(c.get("duration_s") or 0))
        return "suite", {}
    if t == NODE_SCOPE:
        expression = (c.get("expression") or "entree").strip()
        temps = round(ctx.loop.latest_time - ctx.loop.start_time, 3) if ctx.loop is not None else time.time()
        try:
            value = evaluate(expression, ctx.data, ctx.entree)
        except Exception as e:          # un affichage ne doit pas arrêter le programme : l'erreur est montrée
            message = str(e) if isinstance(e, ValueError) else f"{type(e).__name__} : {e}"
            ctx.on_event(FlowEvent("scope", node.name, {"id": node.id, "value": None, "temps": temps,
                                                        "erreur": f"« {expression} » : {message}"}))
            return "suite", {"valeur": None}
        if isinstance(value, SimpleNamespace):
            value = vars(value)
        ctx.on_event(FlowEvent("scope", node.name, {"id": node.id, "value": value, "temps": temps}))
        return "suite", {"valeur": value}
    if t == NODE_MESSAGE:
        text = fill(c.get("text", ""), ctx.data, ctx.entree)
        ctx.on_event(FlowEvent("message", text))
        return "suite", {"texte": text}
    if t == NODE_LLM:
        from mir_flow.agent import FlowAgent
        agent = ctx.agents.get(node.id)
        if agent is None:
            agent = ctx.agents[node.id] = FlowAgent(robot, ctx.api_key, on_event=ctx.on_event)
            agent.configure(ctx.graph, ctx.robot_dir, node.id)
        agent.flow_data = ctx.data
        reply = agent.send(fill(c.get("prompt") or "Continue.", ctx.data, ctx.entree), stop=ctx.should_stop,
                           loop=ctx.loop)
        return "suite", {"reponse": reply}
    raise ValueError(f"type de nœud inconnu : {t}")


def tool_schema(node: Node, robot_dir: Path | None) -> dict[str, Any]:
    """Comment un LLM voit un nœud outil : son nom, sa description (aucun paramètre : tout est réglé dans le nœud)."""
    if node.type == NODE_ACTION:
        description = ActionTool(node, robot_dir).full_description()
    else:
        description = node.config.get("description") or node.spec.help
        if node.type == NODE_MEASURE:
            source = node.config.get("source") or ""
            if source == SOURCE_SERVOS:
                description += (" Returns the servo measurements " + ", ".join(node.config.get("quantities") or [])
                                + " as {servo: value}.")
            elif "lidar" in source:
                description += (" Returns lidar points: [angle_deg, distance_cm], angle 0 = robot front, increasing "
                                "clockwise (90 = right); distance 0 = nothing measured.")
            else:
                description += " Returns the camera image (attached)."
        elif node.spec.outputs_help:
            description += " Returns: " + node.spec.outputs_help.replace(f"{node.spec.default_name}.", "")
    return {"type": "function", "function": {"name": node.name, "description": description,
                                             "parameters": {"type": "object", "properties": {}, "required": []}}}


def _for_llm(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return "image attached" if value.ndim == 3 else np.round(value, 1).tolist()
    return value


def io_event(node: Node, entree: dict[str, Any], sortie: dict[str, Any], port: str | None) -> FlowEvent:
    """Entrée et sortie d'un nœud à son dernier passage (affichées dans ses réglages, comme dans n8n)."""
    return FlowEvent("io", node.name, {"id": node.id, "entree": dict(entree), "sortie": dict(sortie), "port": port,
                                       "time": time.time()})


def run_tool(node: Node, ctx: RunContext) -> str:
    """Un LLM appelle ce nœud : il s'exécute, son résultat va aussi dans les données du flux."""
    port, result = execute_node(node, ctx)
    ctx.data[node.name] = result
    ctx.on_event(io_event(node, ctx.entree, result, port))
    if node.type == NODE_ACTION:
        if result["interrompu"]:
            return f"Interrupted after {result['duree']:g} s: the stop condition became true."
        return f"Done: {'finished by itself after' if result['fini_seul'] else 'ran for'} {result['duree']:g} s."
    return json.dumps({k: _for_llm(v) for k, v in result.items()}, separators=(",", ":"), ensure_ascii=False,
                      default=str)


# ---------------------------------------------------------------------- flux
def short(result: dict[str, Any]) -> str:
    """Résumé d'un résultat pour l'affichage (pas les images ni les longues listes)."""
    parts = []
    for k, v in result.items():
        if isinstance(v, np.ndarray):
            parts.append(f"{k} = tableau {' × '.join(map(str, v.shape))}")
        elif not isinstance(v, (list, dict)):
            parts.append(f"{k} = {round(v, 2) if isinstance(v, float) else v}")
    text = ", ".join(parts)
    return text if len(text) < 160 else text[:160] + " …"


class FlowRunner:
    """Fait tourner un flux : une seule boucle robot, la chaîne principale (depuis Départ), les chaînes « En continu »
    (perception, dans des fils à part) et les déclencheurs « Quand » (qui interrompent la chaîne principale)."""

    def __init__(self, robot, graph: Graph, robot_dir: str | Path | None = None, api_key: str | None = None,
                 on_event: Callable[[FlowEvent], None] | None = None):
        self._stop = False
        self._finished = False
        self._interrupt: Node | None = None          # déclencheur qui vient de se déclencher
        self.error: Exception | None = None          # erreur dans une chaîne en continu ou un déclencheur
        self.ctx = RunContext(robot, graph, Path(robot_dir) if robot_dir is not None else None, api_key,
                              should_stop=lambda: self._stop or self._interrupt is not None,
                              on_event=on_event or (lambda e: None))

    def stop(self):
        self._stop = True

    # ------------------------------------------------------------------ flux
    def run(self) -> str:
        """Fait tourner le flux. Renvoie la raison de l'arrêt."""
        ctx, graph = self.ctx, self.ctx.graph
        main = graph.start()
        continuous = [n for n in graph.nodes if n.type == NODE_CONTINUOUS]
        triggers = [n for n in graph.nodes if n.type == NODE_TRIGGER]
        if main is None and not triggers:
            raise ValueError("ajoutez un nœud Départ (ou un déclencheur « Quand »)")
        for trigger in triggers:            # les fautes de frappe se voient tout de suite
            try:
                compile(trigger.config.get("expression") or "False", "<condition>", "eval")
            except SyntaxError as e:
                raise ValueError(f"« {trigger.name} » : condition mal écrite ({e.msg})") from None
        ctx.loop = RobotLoop(ctx.robot)
        reason = "fin"
        threads: list[threading.Thread] = []
        try:
            ctx.loop.start()
            ctx.loop.require([o for n in graph.nodes for o in observations_of(n, ctx.robot)])
            threads = [threading.Thread(target=self._continuous, args=(n,), name=n.name, daemon=True)
                       for n in continuous]
            if triggers:
                threads.append(threading.Thread(target=self._watch_triggers, args=(triggers,), name="déclencheurs",
                                                daemon=True))
            for thread in threads:
                thread.start()
            node = main
            while True:
                try:
                    if node is None:            # pas de Départ : on attend un déclencheur
                        while True:
                            ctx.sleep(1)
                    reason = self._chain(node)
                    break
                except StopRequested:
                    if self._stop or self._interrupt is None:
                        reason = "arrêté"
                        break
                    node, self._interrupt = self._interrupt, None
                    ctx.on_event(FlowEvent("trigger", f"{node.name} : {node.config.get('expression', '')}",
                                           {"id": node.id}))
            if self.error is not None:
                raise self.error
        except StopRequested:
            reason = "arrêté"
        except Exception:
            reason = "erreur"
            raise
        finally:
            self._finished = True
            for thread in threads:
                thread.join(2)
            ctx.loop.stop()             # arrête l'action en cours, puis les moteurs
            perception.close_detectors(ctx.detectors)
            ctx.on_event(FlowEvent("end", reason))
        return reason

    def _chain(self, node: Node | None) -> str:
        """La chaîne principale, depuis ce nœud. Renvoie la raison de sa fin."""
        ctx, graph = self.ctx, self.ctx.graph
        while node is not None:
            if ctx.should_stop():
                raise StopRequested
            if self.error is not None:
                raise self.error
            ctx.on_event(FlowEvent("node", node.name, {"id": node.id}))
            try:
                port, result = execute_node(node, ctx)
            except StopRequested:
                raise
            except Exception as e:
                logger.exception(node.name)
                raise RuntimeError(f"nœud « {node.name} » : {e}") from None
            ctx.data[node.name] = result
            ctx.on_event(io_event(node, ctx.entree, result, port))
            ctx.entree = result
            if node.type not in (NODE_START, NODE_TRIGGER, NODE_MESSAGE, NODE_LLM, NODE_SCOPE):
                port_text = f" → {port}" if port and len(node.outputs) > 1 else ""
                ctx.on_event(FlowEvent("step", f"{node.name}{port_text}  {short(result)}".rstrip(),
                                       {"id": node.id, "port": port}))
            if port is None:
                return "fin"
            following = graph.next_node(node.id, port)
            if following is None:
                return f"la sortie « {port} » de {node.name} ne mène nulle part"
            node = following
            time.sleep(MIN_STEP_S)
        return "fin"

    # ------------------------------------------------------------------ à côté de la chaîne principale
    def _continuous(self, start: Node):
        """Une chaîne « En continu » : tourne en boucle à sa fréquence, tant que le flux tourne."""
        ctx = replace(self.ctx, should_stop=lambda: self._finished or self._stop, counters={}, entree={})
        period = 1 / max(0.1, float(start.config.get("rate_hz") or 10))
        node = start
        try:
            while not self._finished and not self._stop:
                begin = time.perf_counter()
                entree: dict[str, Any] = {}
                node = ctx.graph.next_node(start.id, "suite")
                seen: set[str] = set()
                while node is not None and node.id not in seen:
                    if node.type not in CONTINUOUS_OK:
                        raise ValueError(f"le nœud « {node.name} » n'a pas sa place dans une chaîne en continu")
                    seen.add(node.id)
                    ctx.entree = entree
                    port, result = execute_node(node, ctx)
                    self.ctx.data[node.name] = result
                    self.ctx.on_event(io_event(node, entree, result, port))
                    entree = result
                    node = ctx.graph.next_node(node.id, port) if port else None
                time.sleep(max(0.0, period - (time.perf_counter() - begin)))
        except StopRequested:
            pass
        except Exception as e:
            logger.exception(start.name)
            where = f", nœud « {node.name} »" if node is not None and node is not start else ""
            self.error = RuntimeError(f"« {start.name} » (en continu){where} : {e}")
            self._stop = True

    def _watch_triggers(self, triggers: list[Node]):
        """Les déclencheurs « Quand » : quand une condition devient vraie, la chaîne principale est interrompue.
        Une condition qui ne peut pas encore être évaluée (donnée pas encore calculée) compte comme fausse."""
        before = {t.id: False for t in triggers}
        while not self._finished and not self._stop:
            for trigger in triggers:
                try:
                    now = bool(evaluate(trigger.config.get("expression") or "False", self.ctx.data))
                except Exception:
                    now = False
                if now and not before[trigger.id] and self._interrupt is None:
                    self._interrupt = trigger
                before[trigger.id] = now
            time.sleep(0.05)
