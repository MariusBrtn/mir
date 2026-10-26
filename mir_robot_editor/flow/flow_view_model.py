"""
MIR Flow : un graphe (un nœud LLM et les outils branchés dessous : actions, lectures de capteurs), et la discussion
avec le LLM, qui pilote le robot réel ou simulé à travers ces outils.

Le graphe est celui du robot ouvert (robots/<robot>/flows/flow.json), enregistré à chaque modification.
Le robot est utilisé pendant que le modèle traite un message : une seule activité à la fois sur le robot, arrêt
d'urgence commun.
"""
from __future__ import annotations
from enum import Enum
from pathlib import Path
from loguru import logger
from PySide6.QtCore import Signal
from mir_flow import credentials
from mir_flow.agent import FlowAgent
from mir_flow.graph import NODE_START, Graph, flow_path
from mir_flow.runner import FlowEvent, FlowRunner
from mir_flow.robot_context import default_observation_names, describe_robot, drive_presets
from mir_robot.mir_robot import mirRobot
from mir_utils.concurrency import BackgroundWorker
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import ViewModelBase


class FlowVMAction(Enum):
    pass


class FlowViewModel(ViewModelBase[FlowVMAction]):
    busy_state_changed = Signal(bool)
    robot_changed = Signal()
    graph_loaded = Signal()                 # autre robot : autre graphe
    account_changed = Signal()
    event = Signal(object)                  # FlowEvent, émis depuis le thread du flux ou du modèle
    io_changed = Signal(str)                # id du nœud dont on connaît un nouveau passage (entrée / sortie)
    _fin = Signal()                         # émis depuis le thread du modèle

    def __init__(self, dialog_provider: IDialogProvider, other_busy=None, sim_world=None):
        super().__init__(dialog_provider)
        self._other_busy = other_busy or (lambda: False)
        self._sim_world = sim_world or (lambda: None)
        self._robot: mirRobot | None = None
        self._lists: dict | None = None
        self._dossier_robot: Path | None = None
        self.graph = Graph.new()
        self._agent: FlowAgent | None = None
        self._runner: FlowRunner | None = None
        self.chat_llm_id: str | None = None          # le LLM avec qui on discute (None : le premier)
        self._worker = BackgroundWorker()
        self._en_cours = False
        self._account: tuple[str | None, str | None] | None = None     # (clé, source), lu à la première demande
        self._fin.connect(self._on_fin)
        self.last_io: dict[str, dict] = {}       # id du nœud -> son dernier passage (entree, sortie, port, time)
        self.event.connect(self._on_event)

    # ------------------------------------------------------------------ robot
    def set_other_busy(self, other_busy):
        self._other_busy = other_busy

    def connect_to_robot(self, robot: mirRobot):
        self._robot = robot
        self._lists = None
        self._agent = None              # autre robot (ou robot reconstruit) : nouvelle discussion
        self.robot_changed.emit()

    def disconnect_from_robot(self):
        if self._en_cours:
            raise RuntimeError("Le modèle pilote le robot")
        self._robot = None
        self._lists = None
        self._agent = None
        self.robot_changed.emit()

    def has_robot(self) -> bool:
        return self._robot is not None

    def sim_world(self):
        return self._sim_world()

    def robot_context(self) -> str:
        """Ce que le modèle sait du robot : instructions du nœud LLM et description générée."""
        if self._robot is None:
            return ""
        llm = self.graph.llm()
        if llm is None:
            return ""
        if not llm.config.get("describe_robot", True):
            return "(description du robot désactivée dans le nœud LLM)"
        return describe_robot(self._robot._config, self._robot.get_actions(), self._robot.get_observables())

    def inspector_lists(self, refresh: bool = False) -> dict:
        """Consignes, observations, politiques et préréglages proposés dans les réglages des nœuds. Gardés en mémoire :
        les calculer demande de relire les modèles entraînés et de construire le modèle MuJoCo du robot."""
        if refresh or self._lists is None:
            self._lists = self._compute_lists()
        return self._lists

    def _compute_lists(self) -> dict:
        from mir_robot.training import model_info, trained_models
        lists: dict = {"actions": {}, "observables": [], "default_observables": [], "policies": [], "presets": {},
                       "cameras": [], "lidars": []}
        if self._robot is not None:
            actions = self._robot.get_actions()
            observables = self._robot.get_observables()
            kinds = {n: type(o).__name__ for n, o in observables.items()}
            lists.update(actions=actions, observables=list(observables),
                         default_observables=default_observation_names(list(observables)),
                         cameras=[n for n, k in kinds.items() if k == "ObservablePropertyBitmap"],
                         lidars=[n for n, k in kinds.items() if k == "ObservablePropertyPolar"])
            try:
                lists["presets"] = drive_presets(self._robot._config, actions)
            except Exception as e:
                logger.warning(f"préréglages des roues : {e}")
        if self._dossier_robot is not None:
            for folder in trained_models(self._dossier_robot):
                info = model_info(folder)
                info["path"] = str(Path(folder).relative_to(self._dossier_robot))
                lists["policies"].append(info)
        return lists

    # ------------------------------------------------------------------ graphe
    def set_dossier_robot(self, dossier: Path | None):
        """Robot ouvert (ou enregistré) : son graphe, ou un graphe de départ."""
        if dossier == self._dossier_robot:
            return
        self._dossier_robot = dossier
        self._lists = None
        self.graph = Graph.new()
        if dossier is not None and flow_path(dossier).exists():
            try:
                self.graph = Graph.load(flow_path(dossier))
            except Exception as e:
                self._dialogProvider.information("MIR Flow", f"Graphe illisible ({flow_path(dossier)}) : {e}")
        if self.graph.start() is None:          # graphes d'avant les flux : on ajoute le Départ
            x = min((n.x for n in self.graph.nodes), default=0) - 320
            self.graph.add_node(NODE_START, x, min((n.y for n in self.graph.nodes), default=0) - 160)
        self._agent = None
        self.chat_llm_id = None
        self.last_io = {}
        self.graph_loaded.emit()

    def save_graph(self):
        if self._dossier_robot is None:
            return          # robot pas encore enregistré : le graphe reste en mémoire
        try:
            self.graph.save(flow_path(self._dossier_robot))
        except Exception as e:
            logger.error(f"enregistrement du graphe : {e}")

    def problems(self) -> list[str]:
        """Problèmes du graphe, et nœuds dont le capteur n'est pas sur le robot."""
        from mir_flow.graph import NEEDS_CAMERA, NEEDS_LIDAR
        problems = self.graph.problems()
        if self._robot is not None:
            lists = self.inspector_lists()
            available = set(lists["cameras"]) | set(lists["lidars"]) | {"servos"}
            for node in self.graph.nodes:
                if node.type == "measure":
                    source = node.config.get("source") or ""
                    if not source:
                        problems.append(f"« {node.name} » : choisissez la source de la mesure (double-clic).")
                    elif source not in available and not (source == "camera" and lists["cameras"]) \
                            and not (source == "lidar" and lists["lidars"]):
                        problems.append(f"« {node.name} » : la source « {source} » n'est pas sur ce robot.")
                elif node.type in NEEDS_CAMERA and not lists["cameras"]:
                    problems.append(f"« {node.name} » : ce robot n'a pas de caméra.")
        return problems

    # ------------------------------------------------------------------ compte OpenAI
    # le trousseau n'est lu qu'une fois, et seulement quand MIR Flow en a besoin : sur macOS, chaque lecture peut
    # faire demander le mot de passe de session
    def _api_key(self) -> str | None:
        if self._account is None:
            self._account = credentials.read_api_key()
        return self._account[0]

    def _key_source(self) -> str | None:
        self._api_key()
        return self._account[1]

    def has_api_key(self) -> bool:
        return self._api_key() is not None

    def account_text(self) -> str:
        source = self._key_source()
        if source is None:
            return "Pas de compte OpenAI"
        where = "variable OPENAI_API_KEY" if source == "environment" else "trousseau du système"
        return f"Clé {credentials.masked(self._api_key())} ({where})"

    def key_from_environment(self) -> bool:
        return self._key_source() == "environment"

    def save_api_key(self, key: str) -> str | None:
        """Vérifie la clé auprès d'OpenAI puis la range dans le trousseau. None si c'est fait, sinon l'erreur."""
        key = key.strip()
        if not key:
            return "Collez votre clé API."
        error = credentials.check_api_key(key)
        if error is None:
            try:
                credentials.save_api_key(key)
            except Exception as e:
                return f"Impossible d'enregistrer la clé dans le trousseau : {e}"
            self._account = None
            self._agent = None
            self.account_changed.emit()
        return error

    def delete_api_key(self):
        credentials.delete_api_key()
        self._account = None
        self._agent = None
        self.account_changed.emit()

    # ------------------------------------------------------------------ discussion
    def is_running(self) -> bool:
        return self._en_cours

    def new_conversation(self):
        if self._agent is not None and not self._en_cours:
            self._agent.reset()

    def send(self, text: str) -> bool:
        """Envoie un message au LLM, qui appelle ses outils puis répond. False si c'est impossible maintenant."""
        text = text.strip()
        if not text or self._en_cours:
            return False
        if self._robot is None:
            self._dialogProvider.information("MIR Flow", "Pas de robot : connectez le robot réel, ou utilisez le "
                                                         "robot simulé.")
            return False
        if self._other_busy():
            self._dialogProvider.information("MIR Flow", "Arrêtez d'abord le mouvement en cours.")
            return False
        key = self._api_key()
        if key is None:
            self._dialogProvider.information("MIR Flow", "Connectez d'abord votre compte OpenAI (bouton « Compte »).")
            return False
        try:
            if self._agent is None:
                self._agent = FlowAgent(self._robot, api_key=key, on_event=self.event.emit)
            llm_id = self.chat_llm_id if self.graph.node(self.chat_llm_id or "") else None
            self._agent.configure(self.graph, self._dossier_robot, llm_id)     # le graphe tel qu'il est maintenant
        except Exception as e:
            self._dialogProvider.information("MIR Flow", f"Le flow ne peut pas tourner : {e}")
            return False
        self._en_cours = True
        self.busy_state_changed.emit(True)
        self._worker.run(lambda: self._tourner(text), lambda _: None, lambda _: None)
        return True

    def _tourner(self, text: str):
        try:
            self._agent.send(text)
        except Exception as e:
            logger.exception("MIR Flow")
            self.event.emit(FlowEvent("error", _message_erreur(e)))
        finally:
            self._fin.emit()

    def set_chat_llm(self, llm_id: str | None):
        if llm_id != self.chat_llm_id:
            self.chat_llm_id = llm_id
            self._agent = None          # autre LLM : autre discussion

    # ------------------------------------------------------------------ flux
    def run_flow(self) -> bool:
        """Lance le flux depuis le nœud Départ."""
        if self._en_cours:
            return False
        if self._robot is None:
            self._dialogProvider.information("MIR Flow", "Pas de robot : connectez le robot réel, ou utilisez le "
                                                         "robot simulé.")
            return False
        if self._other_busy():
            self._dialogProvider.information("MIR Flow", "Arrêtez d'abord le mouvement en cours.")
            return False
        from mir_flow.graph import NODE_TRIGGER
        problems = self.problems()
        has_trigger = any(n.type == NODE_TRIGGER for n in self.graph.nodes)
        if (self.graph.start() is None and not has_trigger) or problems:
            self._dialogProvider.information("MIR Flow", " ".join(problems) or "Ajoutez un nœud Départ.")
            return False
        self._runner = FlowRunner(self._robot, self.graph, self._dossier_robot, self._api_key(),
                                  on_event=self.event.emit)
        self._en_cours = True
        self.busy_state_changed.emit(True)
        self._worker.run(self._tourner_flux, lambda _: None, lambda _: None)
        return True

    def _tourner_flux(self):
        try:
            self._runner.run()
        except Exception as e:
            logger.exception("MIR Flow")
            self.event.emit(FlowEvent("error", _message_erreur(e)))
        finally:
            self._fin.emit()

    def _on_event(self, event: FlowEvent):
        if event.kind == "io":
            self.last_io[event.data["id"]] = event.data
            self.io_changed.emit(event.data["id"])

    def _on_fin(self):
        self._runner = None
        self._en_cours = False
        self.busy_state_changed.emit(False)

    def arreter(self):
        if self._agent is not None:
            self._agent.stop()
        if self._runner is not None:
            self._runner.stop()

    def arret_urgence(self):
        self.arreter()
        if self._robot is not None:
            try:
                self._robot.motors_emergency_stop()
            except Exception as e:
                logger.error(f"arrêt d'urgence : {e}")

    def quit(self):
        self.arreter()
        self.save_graph()


def _message_erreur(e: Exception) -> str:
    """Les erreurs d'OpenAI les plus courantes, dites simplement."""
    nom = type(e).__name__
    if nom == "AuthenticationError":
        return "Clé API refusée par OpenAI : vérifiez votre compte (bouton « Compte »)."
    if nom == "RateLimitError":
        return "OpenAI refuse la demande : limite atteinte ou crédit épuisé sur votre compte."
    if isinstance(e, RuntimeError) and "nœud" in str(e):
        return f"Erreur dans le {e}"
    if nom == "NotFoundError":
        return f"Modèle inconnu ou non accessible avec votre compte : {e}"
    if nom in ("APIConnectionError", "APITimeoutError"):
        return "Impossible de joindre OpenAI : vérifiez la connexion à internet."
    return f"Erreur : {nom} : {e}"
