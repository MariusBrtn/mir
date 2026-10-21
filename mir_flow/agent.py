"""
Un nœud LLM d'un MIR Flow : un modèle de langage (OpenAI) qui appelle les outils branchés sous lui dans le graphe
(actions, capteurs, perception). Il sert dans la discussion (il répond aux messages de l'utilisateur) et dans un
flux (il reçoit son message « Dans le flux » quand le flux arrive sur lui).

À chaque message, le modèle appelle ses outils autant de fois qu'il le faut, puis répond. À la fin de chaque
message, les moteurs s'arrêtent (roues à l'arrêt, articulations tenues).

Utilisable aussi en script :
    agent = FlowAgent(robot, api_key=get_api_key())
    agent.configure(Graph.load(flow_path(dossier_robot)), dossier_robot)
    print(agent.send("avance pendant 3 secondes"))
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable
from loguru import logger
from mir_flow.graph import Graph, Node
from mir_flow.robot_context import describe_robot
from mir_flow.robot_loop import RobotLoop
from mir_flow.runner import FlowData, FlowEvent, RunContext, observations_of, run_tool, tool_schema
from mir_flow.tools import StopRequested

DEFAULT_MODEL = "gpt-4.1-mini"
MODELS = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o", "gpt-5-mini", "gpt-5"]
MAX_STEPS = 40                  # appels d'outils au plus par message (le modèle ne tourne pas sans fin)
AgentEvent = FlowEvent          # ancien nom


class FlowAgent:
    def __init__(self, robot, api_key: str | None, on_event: Callable[[FlowEvent], None] | None = None):
        from openai import OpenAI
        self.robot = robot
        self.api_key = api_key
        self.model = DEFAULT_MODEL
        self._client = OpenAI(api_key=api_key, timeout=60)
        self._on_event = on_event or (lambda e: None)
        self._stop = False
        self.graph: Graph | None = None
        self.robot_dir: Path | None = None
        self.tools: dict[str, Node] = {}
        self.flow_data = FlowData()             # données du flux : les résultats des outils y sont aussi rangés
        self.detectors: dict = {}               # détecteurs de vision, chargés une fois par message
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": ""}]

    # ------------------------------------------------------------------ configuration (graphe)
    def configure(self, graph: Graph, robot_dir: str | Path | None, llm_id: str | None = None) -> None:
        """Prend un nœud LLM du graphe (le premier si llm_id est None) et les outils branchés dessous.
        La discussion en cours continue."""
        problems = graph.problems()
        if problems:
            raise ValueError(" ".join(problems))
        llm = graph.node(llm_id) if llm_id else graph.llm()
        if llm is None:
            raise ValueError("ajoutez un nœud LLM")
        self.graph = graph
        self.robot_dir = Path(robot_dir) if robot_dir is not None else None
        self.model = llm.config.get("model") or DEFAULT_MODEL
        self.tools = {n.name: n for n in graph.tools_of(llm.id)}
        self.messages[0] = {"role": "system", "content": self.system_prompt(llm.config)}

    def system_prompt(self, config: dict[str, Any]) -> str:
        parts = [config.get("instructions", "").strip()]
        if self.tools:
            parts.append("Use only the tools you are given to act on the robot or read its sensors. "
                         "Answer in the user's language.")
        else:
            parts.append("You have no tool: you cannot move the robot nor read its sensors. Say so if asked.")
        if config.get("describe_robot", True):
            parts.append(describe_robot(self.robot._config, self.robot.get_actions(), self.robot.get_observables()))
        return "\n\n".join(p for p in parts if p)

    # ------------------------------------------------------------------ discussion
    def reset(self) -> None:
        self.messages = self.messages[:1]

    def stop(self) -> None:
        """Demande l'arrêt (bouton Arrêter) : l'outil en cours est interrompu."""
        self._stop = True

    def send(self, text: str, stop: Callable[[], bool] | None = None, loop: RobotLoop | None = None) -> str:
        """Un message : le modèle appelle ses outils, puis répond. Renvoie sa réponse.
        stop : arrêt demandé par ailleurs (le flux qui contient ce nœud) ; loop : la boucle robot du flux (sinon le
        nœud a la sienne, le temps du message)."""
        self._stop = False
        own_loop = loop is None
        if own_loop:
            loop = RobotLoop(self.robot).start()
            loop.require([o for n in self.tools.values() for o in observations_of(n, self.robot)])
        should_stop = (lambda: self._stop or stop()) if stop else (lambda: self._stop)
        self.messages.append({"role": "user", "content": text})
        schemas = [tool_schema(n, self.robot_dir) for n in self.tools.values()]
        try:
            for _ in range(MAX_STEPS):
                if should_stop():
                    raise StopRequested
                kwargs: dict[str, Any] = {"model": self.model, "messages": self.messages}
                if schemas:
                    kwargs["tools"] = schemas
                message = self._client.chat.completions.create(**kwargs).choices[0].message
                self.messages.append(message.model_dump(exclude_none=True))
                if not message.tool_calls:
                    reply = message.content or ""
                    self._on_event(FlowEvent("reply", reply))
                    return reply
                ctx = RunContext(self.robot, self.graph, self.robot_dir, self.api_key, should_stop=should_stop,
                                 on_event=self._on_event, data=self.flow_data, images=[], loop=loop,
                                 detectors=self.detectors)
                for call in message.tool_calls:
                    result = self._call(call.function.name, ctx)
                    self.messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
                if ctx.images:
                    # les images ne peuvent pas être dans le résultat d'un outil : elles suivent, comme un message
                    content: list[dict[str, Any]] = [{"type": "text", "text": "Camera images from the tools:"}]
                    for name, url in ctx.images:
                        content += [{"type": "text", "text": name}, {"type": "image_url", "image_url": {"url": url}}]
                    self.messages.append({"role": "user", "content": content})
            reply = f"(arrêt : plus de {MAX_STEPS} appels pour ce message)"
            self._on_event(FlowEvent("reply", reply))
            return reply
        except StopRequested:
            self._answer_pending_calls()
            if stop and stop():
                raise               # c'est le flux qui s'arrête
            self._on_event(FlowEvent("reply", "(arrêté)"))
            return "(arrêté)"
        finally:
            if own_loop:
                loop.stop()             # arrête les moteurs
            from mir_flow.perception import close_detectors
            close_detectors(self.detectors)

    def _answer_pending_calls(self) -> None:
        """Après un arrêt, la discussion doit rester valable : chaque appel d'outil doit avoir son résultat."""
        answered = {m.get("tool_call_id") for m in self.messages if m.get("role") == "tool"}
        for m in list(self.messages):
            for call in m.get("tool_calls") or []:
                if call["id"] not in answered:
                    self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": "Stopped by the user."})
                    answered.add(call["id"])

    def _call(self, name: str, ctx: RunContext) -> str:
        self._on_event(FlowEvent("call", name, {"name": name}))
        node = self.tools.get(name)
        try:
            result = run_tool(node, ctx) if node else f"Error: unknown tool {name}."
        except StopRequested:
            raise
        except Exception as e:
            logger.exception(name)
            result = f"Error: {type(e).__name__}: {e}"
        self._on_event(FlowEvent("result", result, {"name": name}))
        return result
