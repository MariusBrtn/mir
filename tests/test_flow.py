"""MIR Flow : graphe, flux exécutés sur le robot simulé (logique, perception, actions), outils appelés par un LLM,
contexte du robot. Le LLM est factice : aucun appel à OpenAI."""
import json
import time
from types import SimpleNamespace
import numpy as np
import pytest
from openai.types.chat import ChatCompletionMessage
from mir_flow import perception
from mir_flow.agent import FlowAgent
from mir_flow.graph import (EDGE_TOOL, KIND_SCRIPT, NODE_ACTION, NODE_CONDITION, NODE_CONTINUOUS,
                            NODE_END, NODE_MEASURE, NODE_MESSAGE, NODE_SCOPE, NODE_SCRIPT, NODE_START, NODE_TRIGGER, NODE_VISION,
                            Graph)
from mir_flow.robot_context import describe_robot, drive_presets
from mir_flow.runner import FlowData, FlowRunner, evaluate, fill


class LLMFactice:
    """Remplace l'API OpenAI : renvoie l'un après l'autre les messages prévus par le test, et garde les requêtes."""

    def __init__(self, messages: list[ChatCompletionMessage]):
        self.messages = list(messages)
        self.requetes: list[dict] = []

    def create(self, **kwargs):
        self.requetes.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=self.messages.pop(0))])


def appel(i: int, nom: str) -> dict:
    return {"id": f"appel_{i}", "type": "function", "function": {"name": nom, "arguments": "{}"}}


DISTANCE_DEVANT = """import numpy as np


def traiter(entree, donnees):
    angles, distances = entree["points"][:, 0], entree["points"][:, 1]
    devant = ((angles <= 30) | (angles >= 330)) & (distances > 0)
    return {"devant": float(distances[devant].min()) if devant.any() else 1200.0}
"""


def lidar_et_distance(graphe: Graph):
    """Lidar brut, puis un script qui calcule la distance devant (le traitement est dans un nœud Script)."""
    lidar = graphe.add_node(NODE_MEASURE)
    lidar.config.update(name="lidar", source="lidar_1")
    distance = graphe.add_node(NODE_SCRIPT)
    distance.config.update(name="distance", code=DISTANCE_DEVANT)
    return lidar, distance


def avancer(graphe: Graph, robot, duree: float):
    action = graphe.add_node(NODE_ACTION)
    action.config.update(name="avancer", description="Fait avancer le robot", duration_s=duree,
                         setpoint=drive_presets(robot._config, robot.get_actions())["Avancer"])
    return action


# ---------------------------------------------------------------------- graphe
def test_graphe_enregistre_et_relu(tmp_path):
    graphe = Graph.new()
    action = graphe.add_node(NODE_ACTION, 10, 200)
    assert graphe.connect_tool(action.id, graphe.llm().id)
    assert graphe.connect_main(graphe.start().id, "suite", action.id)
    assert graphe.add_node(NODE_ACTION).name == "action_2"                   # noms uniques
    with pytest.raises(ValueError):
        graphe.add_node(NODE_START)                                          # un seul Départ
    graphe.save(tmp_path / "flow.json")
    relu = Graph.load(tmp_path / "flow.json")
    assert [t.id for t in relu.tools_of(relu.llm().id)] == [action.id]
    assert relu.next_node(relu.start().id, "suite").id == action.id
    action.config["name"] = "pas de espace"
    assert graphe.problems()


def test_ancien_graphe_relu():
    """Les premiers graphes (avant les liens d'exécution) n'avaient que des liens d'outils, sans « kind »."""
    ancien = {"nodes": [{"id": "llm_1", "type": "llm", "config": {"model": "gpt-4.1-mini"}},
                        {"id": "action_1", "type": "action", "config": {"name": "reculer"}}],
              "edges": [{"from": "action_1", "to": "llm_1"}]}
    graphe = Graph.from_dict(ancien)
    assert graphe.edges[0].kind == EDGE_TOOL and graphe.tools_of("llm_1")[0].name == "reculer"


# ---------------------------------------------------------------------- expressions et perception
def test_expressions_et_textes():
    data = FlowData(lidar={"devant": 42.0}, score=3)
    assert evaluate("lidar.devant < 50 and score == 3", data)
    assert evaluate("entree.x == 2", data, {"x": 2})                      # résultat du nœud précédent
    assert evaluate("inconnue + 1", data) == 1                              # variable pas encore définie : 0
    assert fill("Devant : {lidar.devant} cm, score {score}, {absent.x}", data) == "Devant : 42.0 cm, score 3, ?"
    with pytest.raises(ValueError):
        evaluate("lidar.derriere > 1", data)


# ---------------------------------------------------------------------- flux sur le robot simulé
def test_flux_avance_jusqu_au_mur(robot_simule):
    """Départ → Lidar → Script distance → Si entree.devant > 60 : oui → avancer 0,3 s → Lidar ; non → Message → Fin."""
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    lidar, distance = lidar_et_distance(graphe)
    si = graphe.add_node(NODE_CONDITION)
    si.config["expression"] = "entree.devant > 60"
    action = avancer(graphe, robot, 0.3)
    message = graphe.add_node(NODE_MESSAGE)
    message.config["text"] = "Mur à {distance.devant} cm"
    fin = graphe.add_node(NODE_END)
    for a, port, b in [(graphe.start(), "suite", lidar), (lidar, "suite", distance), (distance, "suite", si),
                       (si, "oui", action),
                       (action, "suite", lidar), (si, "non", message), (message, "suite", fin)]:
        assert graphe.connect_main(a.id, port, b.id)
    evenements = []
    runner = FlowRunner(robot, graphe, on_event=evenements.append)
    assert runner.run() == "fin"
    messages = [e.text for e in evenements if e.kind == "message"]
    assert len(messages) == 1
    assert runner.ctx.data["lidar"]["points"].shape == (400, 2)              # le lidar donne ses points bruts
    assert 40 < runner.ctx.data["distance"]["devant"] <= 60                  # il s'est arrêté près du mur
    assert sum(1 for e in evenements if e.kind == "node" and e.text == "avancer") >= 3


def test_camera_brute(robot_simule):
    robot = robot_simule("bras_4ddl_cam_V2")
    graphe = Graph.new()
    camera = graphe.add_node(NODE_MEASURE)
    camera.config.update(name="camera", source="cam_1")
    taille = graphe.add_node(NODE_SCRIPT)
    taille.config["code"] = "def traiter(entree, donnees):\n    return {'pixels': entree['image'].shape[0] * entree['image'].shape[1]}\n"
    graphe.connect_main(graphe.start().id, "suite", camera.id)
    graphe.connect_main(camera.id, "suite", taille.id)
    runner = FlowRunner(robot, graphe)
    runner.run()
    image = runner.ctx.data["camera"]["image"]
    assert image.ndim == 3 and image.dtype == np.uint8
    assert runner.ctx.data["script"]["pixels"] == image.shape[0] * image.shape[1]


def test_flux_arrete(robot_simule):
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    action = avancer(graphe, robot, 5.0)
    graphe.connect_main(graphe.start().id, "suite", action.id)
    runner = FlowRunner(robot, graphe)
    import threading
    threading.Timer(0.3, runner.stop).start()
    debut = time.perf_counter()
    assert runner.run() == "arrêté"
    assert time.perf_counter() - debut < 1.5


def test_en_continu_et_declencheur(robot_simule):
    """En continu : Lidar → distance (10 Hz). Flux : Départ → avancer 30 s. Quand distance.devant < 60 : le flux est
    interrompu et continue par Message → Fin."""
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    continu = graphe.add_node(NODE_CONTINUOUS)
    lidar, distance = lidar_et_distance(graphe)
    graphe.connect_main(continu.id, "suite", lidar.id)
    graphe.connect_main(lidar.id, "suite", distance.id)
    action = avancer(graphe, robot, 30.0)
    graphe.connect_main(graphe.start().id, "suite", action.id)
    quand = graphe.add_node(NODE_TRIGGER)
    quand.config["expression"] = "distance.devant < 60"
    message = graphe.add_node(NODE_MESSAGE)
    message.config["text"] = "Obstacle à {distance.devant} cm"
    fin = graphe.add_node(NODE_END)
    graphe.connect_main(quand.id, "suite", message.id)
    graphe.connect_main(message.id, "suite", fin.id)
    assert not graphe.problems()
    evenements = []
    debut = time.perf_counter()
    runner = FlowRunner(robot, graphe, on_event=evenements.append)
    assert runner.run() == "fin"
    assert time.perf_counter() - debut < 25         # bien avant la fin des 30 s d'avance
    assert [e.text for e in evenements if e.kind == "trigger"]                # le déclencheur a interrompu le flux
    assert 30 < runner.ctx.data["distance"]["devant"] < 60


def test_arreter_quand_sur_donnees_en_continu(robot_simule):
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    continu = graphe.add_node(NODE_CONTINUOUS)
    lidar, distance = lidar_et_distance(graphe)
    graphe.connect_main(continu.id, "suite", lidar.id)
    graphe.connect_main(lidar.id, "suite", distance.id)
    action = avancer(graphe, robot, 10.0)
    action.config["until"] = "distance.devant < 60"                         # sans nœud à surveiller
    graphe.connect_main(graphe.start().id, "suite", action.id)
    runner = FlowRunner(robot, graphe)
    runner.run()
    assert runner.ctx.data["avancer"]["interrompu"]


def test_en_continu_refuse_les_actions(robot_simule):
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    continu = graphe.add_node(NODE_CONTINUOUS)
    action = avancer(graphe, robot, 1.0)
    graphe.connect_main(continu.id, "suite", action.id)
    assert any("en continu" in p for p in graphe.problems())


def test_une_seule_boucle_lit_le_robot(robot_simule):
    import threading
    robot = robot_simule("test_mobile")
    fils = set()
    lire = robot.get_observation
    robot.get_observation = lambda: (fils.add(threading.current_thread().name), lire())[1]
    graphe = Graph.new()
    continu = graphe.add_node(NODE_CONTINUOUS)
    lidar, distance = lidar_et_distance(graphe)
    graphe.connect_main(continu.id, "suite", lidar.id)
    graphe.connect_main(lidar.id, "suite", distance.id)
    action = avancer(graphe, robot, 0.5)
    graphe.connect_main(graphe.start().id, "suite", action.id)
    FlowRunner(robot, graphe).run()
    FlowRunner(robot, graphe).run()           # relancer : la boucle reprend le même fil (contexte OpenGL de la caméra)
    assert len(fils) == 1 and next(iter(fils)).startswith("boucle robot")


def test_mesure_des_servos(robot_simule):
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    codeurs = graphe.add_node(NODE_MEASURE)
    codeurs.config.update(name="codeurs", source="servos", quantities=["position", "vitesse"])
    graphe.connect_main(graphe.start().id, "suite", codeurs.id)
    runner = FlowRunner(robot, graphe)
    runner.run()
    mesure = runner.ctx.data["codeurs"]
    assert set(mesure["position"]) == {"roue_avant_gauche", "roue_arriere_gauche", "roue_arriere_droite",
                                       "roue_avant_droite"}
    assert set(mesure["vitesse"]) == set(mesure["position"]) and mesure["temps"] > 0


def test_scope_transparent(robot_simule):
    """Le Scope envoie sa valeur à afficher ; sa sortie est cette valeur."""
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    lidar = graphe.add_node(NODE_MEASURE)
    lidar.config.update(name="lidar", source="lidar_1")
    scope = graphe.add_node(NODE_SCOPE)
    scope.config["expression"] = "lidar.points"
    apres = graphe.add_node(NODE_SCRIPT)
    apres.config["code"] = "def traiter(entree, donnees):\n    return {'n': len(entree['valeur'])}\n"
    for a, b in ((graphe.start(), lidar), (lidar, scope), (scope, apres)):
        graphe.connect_main(a.id, "suite", b.id)
    evenements = []
    runner = FlowRunner(robot, graphe, on_event=evenements.append)
    runner.run()
    affiche = [e for e in evenements if e.kind == "scope"]
    assert affiche and affiche[0].data["value"].shape == (400, 2)
    assert runner.ctx.data["script"]["n"] == 400


def test_anciens_noeuds_camera_et_lidar():
    ancien = {"nodes": [{"id": "camera_1", "type": "camera", "config": {"name": "camera", "sensor": "cam_1"}},
                        {"id": "lidar_1", "type": "lidar", "config": {"name": "lidar", "sensor": ""}}], "edges": []}
    graphe = Graph.from_dict(ancien)
    assert [(n.type, n.config["source"]) for n in graphe.nodes] == [("measure", "cam_1"), ("measure", "lidar")]


def test_vision(robot_simule):
    robot = robot_simule("bras_4ddl_cam_V2")
    graphe = Graph.new()
    camera = graphe.add_node(NODE_MEASURE)
    camera.config.update(name="camera", source="cam_1")
    vision = graphe.add_node(NODE_VISION)
    vision.config["classes"] = ""                                           # tous les objets
    graphe.connect_main(graphe.start().id, "suite", camera.id)
    graphe.connect_main(camera.id, "suite", vision.id)
    runner = FlowRunner(robot, graphe)
    runner.run()
    resultat = runner.ctx.data["vision"]
    assert resultat["nombre"] == len(resultat["detections"])
    for d in resultat["detections"]:
        assert set(d) == {"classe", "score", "x", "y", "largeur", "hauteur"}


# ---------------------------------------------------------------------- LLM et outils
def test_outils_du_llm(robot_simule):
    robot = robot_simule("test_mobile")
    graphe = Graph.new()
    llm = graphe.llm()
    action = avancer(graphe, robot, 0.3)
    script = graphe.add_node(NODE_ACTION)
    script.config.update(name="tourner_un_peu", kind=KIND_SCRIPT, script=(
        "from mir_robot.commande import Commande\n"
        "class Tourne(Commande):\n"
        "    def demarrer(self, robot):\n"
        "        self.n = 0\n"
        "    def action(self, observation):\n"
        "        self.n += 1\n"
        "        if self.n > 3:\n"
        "            self.terminer()\n"
        "        return {nom: 30.0 for nom in ['roue_avant_gauche.velocity', 'roue_avant_droite.velocity']}\n"))
    lidar = graphe.add_node(NODE_MEASURE)
    lidar.config.update(name="lidar", source="lidar_1")
    for noeud in (action, script, lidar):
        graphe.connect_tool(noeud.id, llm.id)
    evenements = []
    agent = FlowAgent(robot, api_key="sk-test", on_event=evenements.append)
    faux = LLMFactice([
        ChatCompletionMessage(role="assistant", tool_calls=[appel(1, "avancer")]),
        ChatCompletionMessage(role="assistant", tool_calls=[appel(2, "tourner_un_peu")]),
        ChatCompletionMessage(role="assistant", tool_calls=[appel(3, "lidar")]),
        ChatCompletionMessage(role="assistant", content="Fait."),
    ])
    agent._client = SimpleNamespace(chat=SimpleNamespace(completions=faux))
    agent.configure(graphe, None)
    assert agent.send("avance un peu") == "Fait."
    # le LLM ne voit que les outils branchés sous lui, sans paramètre : tout est réglé dans les nœuds
    outils = {t["function"]["name"]: t["function"] for t in faux.requetes[0]["tools"]}
    assert set(outils) == {"avancer", "tourner_un_peu", "lidar"}
    assert all(not o["parameters"]["properties"] for o in outils.values())
    assert "0.3 s" in outils["avancer"]["description"]
    resultats = [e.text for e in evenements if e.kind == "result"]
    assert resultats[0].startswith("Done: ran for")
    assert resultats[1].startswith("Done: finished by itself")                # le script a appelé terminer()
    assert len(json.loads(resultats[2])["points"]) == 400                   # points du lidar, en liste pour le LLM
    assert len(agent.flow_data["lidar"]["points"]) == 400                    # rangé dans les données du flux


# ---------------------------------------------------------------------- contexte du robot
def test_contexte_robot_mobile(robot_simule):
    robot = robot_simule("test_mobile")
    contexte = describe_robot(robot._config, robot.get_actions(), robot.get_observables())
    assert "mobile" in contexte and "lidar_1" in contexte
    # mêmes sens que la téléop au clavier : roues de gauche positives et de droite négatives pour avancer
    avance = drive_presets(robot._config, robot.get_actions())["Avancer"]
    assert all(v > 0 for k, v in avance.items() if "gauche" in k)
    assert all(v < 0 for k, v in avance.items() if "droite" in k)


def test_contexte_bras(robot_simule):
    robot = robot_simule("bras_4ddl_cam_V2")
    contexte = describe_robot(robot._config, robot.get_actions(), robot.get_observables())
    assert "fixed to the table" in contexte
    assert "This is the gripper: a higher angle closes it." in contexte
    assert "`cam_1`: camera, mounted on pince_joint_5" in contexte
    assert drive_presets(robot._config, robot.get_actions()) == {}
