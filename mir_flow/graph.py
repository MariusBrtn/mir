"""
Le graphe d'un MIR Flow.

Deux sortes de liens :
  - les liens d'exécution (« main ») : de la sortie d'un nœud (à droite) à l'entrée du suivant (à gauche). Le flux part
    du nœud Départ et suit ces liens ; un nœud à plusieurs sorties (Si : oui / non) choisit la sienne. Relier une
    sortie à un nœud précédent fait une boucle ;
  - les liens d'outils (« tool ») : d'un nœud outil (action, capteurs, perception) au port « Outils » d'un nœud LLM,
    comme les outils d'un agent dans n8n. Le LLM appelle ces outils quand il le juge utile.

Chaque nœud a un nom ; son résultat est rangé sous ce nom dans les données du flux (ex. lidar.points), où les
nœuds suivants le lisent (conditions, messages, questions au LLM).

Le graphe est enregistré dans le dossier du robot : robots/<robot>/flows/flow.json.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FLOWS_DIR = "flows"
FLOW_FILE = "flow.json"

NODE_START, NODE_END = "start", "end"
NODE_CONTINUOUS, NODE_TRIGGER, NODE_WAIT, NODE_REPEAT = "continuous", "trigger", "wait", "repeat"
NODE_MEASURE, NODE_VISION = "measure", "vision"
OLD_CAMERA, OLD_LIDAR = "camera", "lidar"          # anciens nœuds, devenus des nœuds Mesure (graphes du 20/10)
SOURCE_SERVOS = "servos"
# grandeurs des servos : nom dans les données du flux -> (suffixe de l'observation, unité)
QUANTITIES = {"position": ("position", "°"), "vitesse": ("velocity", "tr/min"), "courant": ("current", "mA"),
              "temperature": ("temperature", "°C"), "charge": ("load", "%")}
NODE_CONDITION, NODE_SCRIPT, NODE_LLM = "condition", "script", "llm"
NODE_ACTION, NODE_MESSAGE, NODE_SCOPE = "action", "message", "scope"
STARTS = (NODE_START, NODE_CONTINUOUS, NODE_TRIGGER)       # nœuds par où commence une chaîne
# nœuds qui ont besoin d'un capteur du robot : proposés seulement si le robot l'a
NEEDS_CAMERA = (NODE_VISION,)
NEEDS_LIDAR: tuple[str, ...] = ()
# nœuds permis dans une chaîne « En continu » : ils lisent et calculent, ils ne commandent pas le robot
CONTINUOUS_OK = (NODE_MEASURE, NODE_VISION, NODE_SCRIPT, NODE_CONDITION, NODE_SCOPE)
EDGE_MAIN, EDGE_TOOL = "main", "tool"

KIND_SETPOINT, KIND_SCRIPT, KIND_POLICY = "setpoint", "script", "policy"
KINDS = {KIND_SETPOINT: "Consigne", KIND_SCRIPT: "Mini script", KIND_POLICY: "Politique entraînée"}

NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")      # nom de nœud : un nom de variable Python (et d'outil OpenAI)
TOOL_NAME = NAME

SCRIPT_TEMPLATE = '''from mir_robot.commande import Commande


class Action(Commande):
    def demarrer(self, robot):
        # robot.actions : consignes possibles ; robot.observations ; robot.fps
        self.t = 0

    def action(self, observation):
        # appelée à chaque tour de boucle : renvoie les consignes à envoyer au robot
        self.t += 1
        return {}
'''

PROCESS_TEMPLATE = '''import numpy as np


def traiter(entree, donnees):
    # entree : résultat du nœud précédent, ex. entree["image"] (Caméra) ou entree["points"] (Lidar)
    # donnees : toutes les données du flux, ex. donnees["lidar"]["points"], donnees["score"]
    # renvoie un dictionnaire : il devient le résultat de ce nœud (ex. script.valeur)
    return {"valeur": 0}
'''


@dataclass
class Field:
    """Un réglage d'un nœud, présenté dans un formulaire. kind : text, multiline, number, int, bool, choice,
    expression, camera, lidar, model, code, classes (objets reconnus par la vision)."""
    key: str
    label: str
    kind: str
    default: Any = None
    unit: str = ""
    choices: list[str] = field(default_factory=list)
    help: str = ""
    minimum: float = 0.0
    maximum: float = 100000.0
    step: float = 1.0


@dataclass
class NodeSpec:
    label: str                              # nom affiché
    category: str                           # voir CATEGORIES
    summary: str                            # une ligne, dans la bibliothèque de nœuds
    default_name: str
    has_input: bool = True
    outputs: list[str] = field(default_factory=lambda: ["suite"])
    tool: bool = False                      # peut être branché comme outil sous un LLM
    fields: list[Field] = field(default_factory=list)
    help: str = ""
    outputs_help: str = ""                  # ce que le nœud range dans les données du flux


SPECS: dict[str, NodeSpec] = {
    # ------------------------------------------------------------------ Déroulement
    NODE_START: NodeSpec("Départ", "Déroulement", "Le programme commence ici", "depart", has_input=False,
                         help="Le programme principal commence ici quand on clique sur « Lancer ». Il passe d'un "
                              "nœud au suivant quand le précédent a fini."),
    NODE_CONTINUOUS: NodeSpec("En continu", "Déroulement", "Une chaîne qui tourne en boucle, à côté", "en_continu",
                              has_input=False, fields=[Field("rate_hz", "Fréquence", "number", 5.0, "Hz",
                                                             minimum=0.5, maximum=30, step=0.5)],
                              help="Pendant tout le programme, la chaîne qui part d'ici tourne en boucle à la fréquence "
                                   "choisie, à côté du flux principal : pour percevoir (caméra, lidar, vision, "
                                   "scripts), jamais pour agir. Ses résultats sont à jour à tout moment."),
    NODE_TRIGGER: NodeSpec("Interruption", "Déroulement", "Interrompt tout dès qu'une condition devient vraie",
                           "interruption",
                           has_input=False, fields=[
                               Field("expression", "Condition", "expression", "",
                                     help="Ex. vision.nombre > 0. Vérifiée en permanence pendant le flux.")],
                           help="Dès que la condition devient vraie, le programme principal est interrompu (l'action en "
                                "cours s'arrête) et continue par la chaîne qui part d'ici."),
    NODE_WAIT: NodeSpec("Attendre", "Déroulement", "Fait une pause", "attendre",
                        fields=[Field("duration_s", "Durée", "number", 1.0, "s", minimum=0, maximum=3600, step=0.5)]),
    NODE_REPEAT: NodeSpec("Répéter", "Déroulement", "Une boucle : refait N fois", "repeter", outputs=["encore", "fini"],
                          fields=[Field("count", "Nombre de fois", "int", 3, minimum=1, maximum=100000)],
                          help="Sort par « encore » les N premières fois, puis par « fini » (et pourra resservir). "
                               "Reliez la fin des étapes à répéter à l'entrée de ce nœud.",
                          outputs_help="repeter.tour (1, 2, 3…)"),
    NODE_END: NodeSpec("Fin", "Déroulement", "Le programme s'arrête ici", "fin", outputs=[]),
    # ------------------------------------------------------------------ Percevoir
    NODE_MEASURE: NodeSpec("Mesure", "Percevoir", "Une mesure du robot : caméra, lidar ou servos", "mesure", tool=True,
                           fields=[Field("source", "Source", "source", ""),
                                   Field("quantities", "Grandeurs", "quantities", ["position", "vitesse"])],
                           help="Les mesures brutes d'un capteur du robot, telles que les lit la boucle robot (un seul "
                                "get_observation pour tout le programme). Pour les traiter : un nœud Vision ou Script "
                                "juste après.",
                           outputs_help="caméra : mesure.image (tableau numpy hauteur × largeur × 3, RGB) ; lidar : "
                                        "mesure.points (tableau numpy N × 2 : angle en degrés, 0 devant, croissant vers "
                                        "la droite ; distance en cm, 0 = rien mesuré) ; servos : mesure.position, "
                                        "mesure.vitesse… ({servo: valeur}) ; toujours mesure.temps (s écoulées depuis le "
                                        "lancement, à l'instant de la mesure)"),
    NODE_VISION: NodeSpec("Vision", "Percevoir", "Reconnaît des objets dans l'image", "vision", tool=True, fields=[
        Field("classes", "Objets cherchés", "classes", "person",
              help="À choisir dans la liste (noms anglais) ; vide : tous les objets"),
        Field("score_min", "Confiance minimale", "number", 0.5, minimum=0.05, maximum=1.0, step=0.05,
              help="De 0 à 1 : une détection moins sûre est ignorée")],
        help="Reconnaît les objets courants (personne, balle, tasse…) dans l'image du nœud Mesure (caméra) placé juste avant. "
             "Modèle de MediaPipe (Google, licence Apache-2.0).",
        outputs_help="vision.nombre, vision.detections (liste : classe, score, x, y, largeur, hauteur en pixels)"),
    # ------------------------------------------------------------------ Décider
    NODE_CONDITION: NodeSpec("Condition", "Décider", "Choisit un chemin : oui ou non", "condition",
                             outputs=["oui", "non"],
                             fields=[Field("expression", "Condition", "expression", "vision.nombre > 0",
                                           help="Avec les données du flux, ex. vision.nombre > 0")],
                             help="Continue par « oui » si la condition est vraie, sinon par « non »."),
    NODE_SCRIPT: NodeSpec("Script Python", "Décider", "Un calcul en Python", "script",
                          fields=[Field("code", "Code", "code", PROCESS_TEMPLATE)],
                          help="La fonction traiter(entree, donnees) reçoit le résultat du nœud précédent et toutes "
                               "les données du flux, et renvoie un dictionnaire.",
                          outputs_help="script.<clé> pour chaque clé du dictionnaire renvoyé"),
    NODE_LLM: NodeSpec("LLM", "Décider", "Un modèle de langage, avec des outils", "llm",
                       help="Dans la discussion, il répond à vos messages ; dans le flux, il reçoit son message "
                            "« Dans le flux ». Il agit à travers les outils branchés sous lui (losange).",
                       outputs_help="llm.reponse"),
    # ------------------------------------------------------------------ Agir
    NODE_ACTION: NodeSpec("Action", "Agir", "Une compétence du robot : consigne, script ou politique apprise", "action",
                          tool=True,
                          help="Le robot exécute une compétence : une consigne fixe, un mini script, ou une politique "
                               "apprise (RL, ACT…) qui choisit elle-même ses mouvements d'après ce qu'elle observe. "
                               "Elle s'arrête quand elle a fini, quand la condition « Arrêter quand » devient vraie, "
                               "ou au bout de la durée maximale.",
                          outputs_help="action.duree (s), action.interrompu (vrai si « Arrêter quand » l'a arrêtée)"),
    # ------------------------------------------------------------------ Communiquer
    NODE_MESSAGE: NodeSpec("Message", "Communiquer", "Écrit un message", "message", fields=[
        Field("text", "Texte", "multiline", "Bonjour !", help="Les {…} sont remplacés, ex. {vision.nombre}")],
        help="Écrit un message dans la discussion."),
    NODE_SCOPE: NodeSpec("Scope", "Communiquer", "Affiche une donnée en direct : image, lidar, courbe…", "scope",
                         fields=[Field("expression", "Afficher", "expression", "entree",
                                       help="Ex. carte.image, lidar.points, odometrie.cap, codeurs.position ; "
                                            "entree : le résultat du nœud précédent"),
                                 Field("history_s", "Historique", "number", 30.0, "s", minimum=2, maximum=600,
                                       step=5, help="Durée gardée pour les courbes et la trajectoire")],
                         help="Affiche en direct, dans une fenêtre à part, la valeur choisie à chaque passage. "
                              "L'affichage s'adapte à la valeur : une image (ex. une carte), des points lidar "
                              "[angle, distance] vus de dessus, une trajectoire (x et y), des courbes (des nombres).",
                         outputs_help="scope.valeur : la valeur affichée"),
}

CATEGORIES = ["Déroulement", "Percevoir", "Décider", "Agir", "Communiquer"]


def default_config(node_type: str) -> dict[str, Any]:
    spec = SPECS.get(node_type)
    if spec is None:
        raise ValueError(f"type de nœud inconnu : {node_type}")
    config: dict[str, Any] = {"name": spec.default_name, "description": ""}
    for f in spec.fields:
        config[f.key] = f.default
    if node_type == NODE_LLM:
        config.update(model="gpt-4.1-mini", describe_robot=True,
                      instructions="Tu pilotes le robot avec les outils qui te sont donnés. Réponds brièvement.",
                      prompt="")
    elif node_type == NODE_ACTION:
        config.update(kind=KIND_SETPOINT, setpoint={}, script=SCRIPT_TEMPLATE, policy="", fps=20, duration_s=2.0,
                      until="")
    return config


@dataclass
class Node:
    id: str
    type: str
    x: float = 0.0
    y: float = 0.0
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def spec(self) -> NodeSpec:
        return SPECS[self.type]

    @property
    def name(self) -> str:
        return self.config.get("name", self.id)

    @property
    def is_tool(self) -> bool:
        return self.spec.tool

    @property
    def outputs(self) -> list[str]:
        """Sorties du nœud : une action surveillée (« Arrêter quand ») a en plus la sortie « interrompu »."""
        if self.type == NODE_ACTION and (self.config.get("until") or "").strip():
            return ["suite", "interrompu"]
        return self.spec.outputs


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: str = EDGE_MAIN
    port: str = "suite"         # sortie du nœud de départ (liens d'exécution)


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    # ------------------------------------------------------------------ nœuds
    def node(self, node_id: str) -> Node | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def llms(self) -> list[Node]:
        return [n for n in self.nodes if n.type == NODE_LLM]

    def llm(self) -> Node | None:
        return next(iter(self.llms()), None)

    def start(self) -> Node | None:
        return next((n for n in self.nodes if n.type == NODE_START), None)

    def chain(self, first: Node | None) -> list[Node]:
        """Les nœuds atteignables depuis ce nœud par les liens d'exécution (chaque nœud une fois)."""
        seen: list[Node] = []
        todo = [first] if first else []
        while todo:
            node = todo.pop(0)
            if node in seen:
                continue
            seen.append(node)
            todo += [n for p in node.outputs if (n := self.next_node(node.id, p))]
        return seen

    def add_node(self, node_type: str, x: float = 0.0, y: float = 0.0) -> Node:
        if node_type == NODE_START and self.start() is not None:
            raise ValueError("un seul nœud Départ par flow")
        n = 1
        while self.node(f"{node_type}_{n}"):
            n += 1
        node = Node(f"{node_type}_{n}", node_type, x, y, default_config(node_type))
        node.config["name"] = self.unique_name(node.config["name"])
        self.nodes.append(node)
        return node

    def remove_node(self, node_id: str) -> None:
        self.nodes = [n for n in self.nodes if n.id != node_id]
        self.edges = [e for e in self.edges if node_id not in (e.src, e.dst)]

    def unique_name(self, name: str, ignore: str | None = None) -> str:
        names = {n.name for n in self.nodes if n.id != ignore}
        if name not in names:
            return name
        i = 2
        while f"{name}_{i}" in names:
            i += 1
        return f"{name}_{i}"

    # ------------------------------------------------------------------ liens
    def tools_of(self, llm_id: str) -> list[Node]:
        return [n for e in self.edges if e.kind == EDGE_TOOL and e.dst == llm_id and (n := self.node(e.src))]

    def next_node(self, node_id: str, port: str) -> Node | None:
        """Le nœud qui suit cette sortie (None : le flux s'arrête)."""
        edge = next((e for e in self.edges if e.kind == EDGE_MAIN and e.src == node_id and e.port == port), None)
        return self.node(edge.dst) if edge else None

    def connect_tool(self, tool_id: str, llm_id: str) -> bool:
        tool, llm = self.node(tool_id), self.node(llm_id)
        edge = Edge(tool_id, llm_id, EDGE_TOOL, "")
        if tool is None or llm is None or not tool.is_tool or llm.type != NODE_LLM or edge in self.edges:
            return False
        self.edges.append(edge)
        return True

    def connect_main(self, src_id: str, port: str, dst_id: str) -> bool:
        """Relie une sortie à l'entrée d'un nœud ; une sortie ne mène qu'à un seul nœud (l'ancien lien est remplacé)."""
        src, dst = self.node(src_id), self.node(dst_id)
        if src is None or dst is None or port not in src.outputs or not dst.spec.has_input or src_id == dst_id:
            return False
        self.edges = [e for e in self.edges if not (e.kind == EDGE_MAIN and e.src == src_id and e.port == port)]
        self.edges.append(Edge(src_id, dst_id, EDGE_MAIN, port))
        return True

    def remove_edge(self, edge: Edge) -> None:
        self.edges = [e for e in self.edges if e != edge]

    def prune_edges(self) -> None:
        """Retire les liens partant d'une sortie qui n'existe plus (ex. « interrompu » sans surveillance)."""
        self.edges = [e for e in self.edges
                      if e.kind != EDGE_MAIN or (n := self.node(e.src)) is not None and e.port in n.outputs]

    # ------------------------------------------------------------------ vérifications
    def problems(self) -> list[str]:
        """Ce qui est mal réglé, en clair."""
        problems = []
        names = [n.name for n in self.nodes]
        for node in self.nodes:
            if not NAME.match(node.name or ""):
                problems.append(f"Nom invalide « {node.name} » : lettres, chiffres ou _, sans espace ni accent, "
                                f"sans chiffre au début.")
            elif names.count(node.name) > 1:
                problems.append(f"Deux nœuds s'appellent « {node.name} ».")
            if node.type == NODE_CONTINUOUS:
                bad = [n.name for n in self.chain(node)[1:] if n.type not in CONTINUOUS_OK]
                if bad:
                    problems.append(f"« {node.name} » (en continu) ne peut contenir que de la lecture et du calcul, "
                                    f"pas : {', '.join(bad)}.")
            for f in node.spec.fields:
                value = node.config.get(f.key)
                if f.kind in ("number", "int") and isinstance(value, (int, float)) and \
                        not f.minimum <= value <= f.maximum:
                    problems.append(f"« {node.name} » : {f.label.lower()} = {value:g}, doit être entre "
                                    f"{f.minimum:g} et {f.maximum:g}.")
            if node.type == NODE_VISION:
                from mir_flow.perception import unknown_labels
                unknown = unknown_labels((node.config.get("classes") or "").split(","))
                if unknown:
                    problems.append(f"« {node.name} » : objet inconnu {', '.join(unknown)}.")
            if node.type == NODE_TRIGGER and not node.config.get("expression", "").strip():
                problems.append(f"« {node.name} » : écrivez la condition qui déclenche la chaîne.")
        return list(dict.fromkeys(problems))

    # ------------------------------------------------------------------ fichier
    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [{"id": n.id, "type": n.type, "x": round(n.x, 1), "y": round(n.y, 1), "config": n.config}
                          for n in self.nodes],
                "edges": [{"from": e.src, "to": e.dst, "kind": e.kind, "port": e.port} for e in self.edges]}

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Graph:
        graph = Graph()
        for d in data.get("nodes", []):
            if d["type"] in (OLD_CAMERA, OLD_LIDAR):       # Caméra et Lidar sont devenus des nœuds Mesure
                d = dict(d, type=NODE_MEASURE, config=dict(d.get("config", {}),
                                                           source=d.get("config", {}).get("sensor") or d["type"]))
            if d["type"] not in SPECS:
                continue
            config = default_config(d["type"])
            config.update(d.get("config", {}))
            graph.nodes.append(Node(d["id"], d["type"], d.get("x", 0.0), d.get("y", 0.0), config))
        for e in data.get("edges", []):
            if graph.node(e["from"]) and graph.node(e["to"]):
                kind = e.get("kind", EDGE_TOOL)         # premiers graphes : seulement des liens d'outils
                graph.edges.append(Edge(e["from"], e["to"], kind, e.get("port", "" if kind == EDGE_TOOL else "suite")))
        return graph

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> Graph:
        return Graph.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    @staticmethod
    def new() -> Graph:
        """Flow de départ : un nœud Départ et un nœud LLM."""
        graph = Graph()
        graph.add_node(NODE_START, -300, -100)
        graph.add_node(NODE_LLM, 0, -100)
        return graph


def flow_path(robot_dir: str | Path) -> Path:
    return Path(robot_dir) / FLOWS_DIR / FLOW_FILE
