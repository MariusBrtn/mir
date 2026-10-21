"""
La boucle robot d'un MIR Flow : le seul endroit qui parle au robot.

À fréquence fixe, elle appelle robot.get_observation() et publie la dernière observation, que lisent tous les nœuds
(capteurs, perception en continu, conditions, outils du LLM). L'action en cours (une Commande) est exécutée dans
cette même boucle : à chaque tour, observation -> commande.action() -> robot.send_action(). Tout le monde voit donc
la même observation, et le bus moteur n'est jamais interrogé par deux fils à la fois.

Seul l'arrêt d'urgence passe directement par le robot, sans attendre la boucle.

La boucle tourne toujours dans le même fil, réutilisé d'un flux à l'autre : le rendu de la caméra simulée garde un
contexte OpenGL verrouillé par le fil qui l'a créé (MuJoCo sur macOS) ; un nouveau fil qui retomberait sur ce rendu
resterait bloqué.
"""
from __future__ import annotations
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable
from loguru import logger
from mir_robot.commande import Commande, ExecutionCommande

BASE_FPS = 30.0             # fréquence de la boucle quand aucune action ne tourne
_executor: ThreadPoolExecutor | None = None


def _loop_executor() -> ThreadPoolExecutor:
    """Le fil unique des boucles robot (le même pour tous les flux et toutes les discussions)."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="boucle robot")
    return _executor


class StopRequested(Exception):
    pass


class _Command:
    """Une action en cours dans la boucle."""

    def __init__(self, command: Commande, fps: float, duration_s: float, until: Callable[[], bool] | None):
        self.command, self.fps, self.duration_s, self.until = command, fps, duration_s, until
        self.execution: ExecutionCommande | None = None
        self.start = 0.0
        self.cancel = False
        self.done = threading.Event()
        self.result: dict[str, Any] = {}
        self.error: BaseException | None = None


class RobotLoop:
    def __init__(self, robot, fps: float = BASE_FPS):
        self.robot = robot
        self.fps = fps
        self._wanted: set[str] = {n for n in robot.get_observables() if n.endswith(".position")}
        self._enabled: set[str] | None = None
        self._latest: dict[str, Any] = {}
        self.latest_time = 0.0                          # instant de la dernière observation (time.time())
        self.start_time = time.time()                   # lancement : les nœuds Mesure donnent le temps écoulé depuis
        self._latest_enabled: set[str] = set()         # observations activées pour la dernière observation
        self._seq = 0
        self._cond = threading.Condition()
        self._command: _Command | None = None
        self._calls: list[tuple[Callable[[], Any], threading.Event, list]] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._future: Future | None = None
        self.error: BaseException | None = None

    # ------------------------------------------------------------------ cycle de vie
    def start(self) -> RobotLoop:
        if not self._running:
            self.start_time = time.time()
            self._running = True
            self._future = _loop_executor().submit(self._loop)
            self.wait_observation()             # première observation disponible
        return self

    def stop(self):
        """Arrête l'action en cours, puis les moteurs, puis la boucle."""
        if not self._running:
            return
        command = self._command
        if command is not None:
            command.cancel = True
            command.done.wait(2)
        try:
            self.call(self.robot.motors_stop)
        except Exception as e:
            logger.error(f"arrêt des moteurs : {e}")
        self._running = False
        if self._future is not None:
            try:
                self._future.result(timeout=3)      # la boucle a fini son tour et rendu le fil
            except Exception as e:
                logger.error(f"fin de la boucle robot : {e}")

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # ------------------------------------------------------------------ observations
    def require(self, names: list[str]):
        """Observations à lire à chaque tour (en plus de celles déjà demandées)."""
        with self._lock:
            self._wanted |= set(names)

    def latest(self) -> dict[str, Any]:
        with self._cond:
            return self._latest

    def wait_observation(self, newer_than: int | None = None, timeout: float = 2.0) -> dict[str, Any]:
        """Une observation plus récente que le numéro donné (par défaut : la prochaine)."""
        with self._cond:
            target = self._seq if newer_than is None else newer_than
            if not self._cond.wait_for(lambda: self._seq > target or self.error is not None or not self._running,
                                       timeout):
                raise TimeoutError("la boucle robot ne donne plus d'observation")
            if self.error is not None:
                raise RuntimeError(f"boucle robot : {self.error}")
            return self._latest

    def read(self, names: list[str], timeout: float = 2.0) -> dict[str, Any]:
        """Lecture par un nœud : demande ces observations si besoin, puis attend une observation plus récente que
        l'appel, prise avec ces observations activées."""
        names = set(names) & set(self.robot.get_observables())
        self.require(list(names))
        with self._cond:
            start = self._seq
            if not self._cond.wait_for(lambda: (self._seq > start and names <= self._latest_enabled)
                                       or self.error is not None or not self._running, timeout):
                raise TimeoutError("la boucle robot ne donne pas les observations demandées")
            if self.error is not None:
                raise RuntimeError(f"boucle robot : {self.error}")
            return self._latest

    def ready(self, names: list[str]) -> bool:
        """La dernière observation contient-elle ces grandeurs ?"""
        with self._cond:
            return set(names) & set(self.robot.get_observables()) <= self._latest_enabled

    # ------------------------------------------------------------------ actions
    def run_command(self, command: Commande, fps: float, duration_s: float, should_stop: Callable[[], bool],
                    until: Callable[[], bool] | None = None, needed: list[str] | None = None) -> dict[str, Any]:
        """Fait tourner une commande dans la boucle pendant duration_s, jusqu'à ce qu'elle s'arrête d'elle-même ou que
        until() soit vrai. Bloque jusqu'à la fin. Les moteurs s'arrêtent à la fin."""
        if needed:
            self.require(needed)
        job = _Command(command, fps, duration_s, until)
        with self._lock:
            if self._command is not None:
                raise RuntimeError("une autre action commande déjà le robot")
            self._command = job
        while not job.done.wait(0.02):
            if should_stop():
                job.cancel = True
            if not self._running:
                raise RuntimeError("la boucle robot est arrêtée")
        if job.error is not None:
            raise job.error
        if job.result.get("annule"):
            raise StopRequested
        return job.result

    def call(self, function: Callable[[], Any], timeout: float = 5.0) -> Any:
        """Exécute une fonction qui parle au robot (ex. motors_stop) dans la boucle, et attend son résultat."""
        if not self._running or threading.current_thread() is self._thread:
            return function()
        done, out = threading.Event(), []
        with self._lock:
            self._calls.append((function, done, out))
        if not done.wait(timeout):
            raise TimeoutError("la boucle robot ne répond pas")
        if out and isinstance(out[0], BaseException):
            raise out[0]
        return out[0] if out else None

    # ------------------------------------------------------------------ la boucle
    def _loop(self):
        from mir_utils.keyboard_listener import KeyQueue
        self._thread = threading.current_thread()
        next_tick = time.perf_counter()
        while self._running:
            try:
                with self._lock:
                    wanted = set(self._wanted)
                    calls, self._calls = self._calls, []
                    job = self._command
                for function, done, out in calls:
                    try:
                        out.append(function())
                    except BaseException as e:
                        out.append(e)
                    done.set()
                if wanted != self._enabled:
                    available = set(self.robot.get_observables())
                    self.robot.enable_observations_by_name(sorted(wanted & available))
                    self._enabled = wanted
                observation = self.robot.get_observation()
                with self._cond:
                    self._latest = observation
                    self.latest_time = time.time()
                    self._latest_enabled = set(self._enabled) & set(self.robot.get_observables())
                    self._seq += 1
                    self._cond.notify_all()
                if job is not None:
                    self._step(job, observation, KeyQueue)
                period = 1 / (job.fps if job is not None and not job.done.is_set() else self.fps)
            except Exception as e:
                logger.exception("boucle robot")
                self.error = e
                with self._cond:
                    self._cond.notify_all()
                break
            next_tick += period
            delay = next_tick - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.perf_counter()         # en retard : on ne rattrape pas
        with self._cond:
            self._cond.notify_all()

    def _step(self, job: _Command, observation: dict[str, Any], key_queue):
        """Un tour de l'action en cours (dans la boucle)."""
        try:
            if job.execution is None:
                job.execution = ExecutionCommande(self.robot, job.command, job.fps, clavier=key_queue())
                job.start = time.perf_counter()
            elapsed = time.perf_counter() - job.start
            reason = None
            if job.cancel:
                reason = "annule"
            elif elapsed >= job.duration_s:
                reason = "duree"
            elif job.until is not None and job.until():
                reason = "interrompu"
            elif not job.execution.tour(observation):
                reason = "fini_seul"
            if reason is None:
                return
            job.result = {"duree": round(elapsed, 1), "fini_seul": reason == "fini_seul",
                          "interrompu": reason == "interrompu", "annule": reason == "annule"}
        except BaseException as e:
            job.error = e
        try:
            if job.execution is not None:
                job.execution.arreter()
        except Exception as e:
            job.error = job.error or e
        with self._lock:
            self._command = None
        job.done.set()
