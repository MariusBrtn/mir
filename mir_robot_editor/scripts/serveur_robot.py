"""
Le robot de l'application, prêté à un script qui tourne dans un autre programme Python (voir mir_robot/script.py).
Un fil d'exécution reçoit les appels du script (get_observation, send_action...) et les passe au robot.
"""
from __future__ import annotations
import logging
import secrets
import threading
from multiprocessing.connection import Connection, Listener
from typing import Any, Callable
from mir_robot.commande import verifier_action
from mir_robot.mir_robot import mirRobot

logger = logging.getLogger(__name__)


class ServeurRobot:
    def __init__(self, robot: Callable[[], mirRobot | None], figure: Callable[..., None]):
        self._robot = robot                     # robot courant (le robot simulé peut être reconstruit)
        self._figure = figure                   # figure(numero, titre, largeur, hauteur, rgba) : figure à afficher
        self._listener: Listener | None = None
        self._connexion: Connection | None = None
        self._thread: threading.Thread | None = None
        self._abonnements: set[str] | None = None

    def demarrer(self) -> tuple[str, str]:
        """Attend le script en arrière-plan ; renvoie l'adresse (« hôte:port ») et la clé à lui donner."""
        cle = secrets.token_hex(16)
        self._listener = Listener(("127.0.0.1", 0), authkey=cle.encode())
        self._abonnements = None
        hote, port = self._listener.address
        self._thread = threading.Thread(target=self._servir, daemon=True, name="mir_script_robot")
        self._thread.start()
        return f"{hote}:{port}", cle

    def arreter(self):
        for objet in (self._listener, self._connexion):
            if objet is not None:
                try:
                    objet.close()
                except OSError:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._listener = self._connexion = self._thread = None

    def _servir(self):
        try:
            self._connexion = self._listener.accept()       # type: ignore[union-attr]
            while True:
                methode, args = self._connexion.recv()
                try:
                    reponse = (True, self._executer(methode, args))
                except Exception as e:
                    message = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
                    reponse = (False, (type(e).__name__, str(message)))
                self._connexion.send(reponse)
        except (EOFError, OSError):
            pass        # script terminé ou arrêté
        except Exception:
            logger.exception("serveur du robot des scripts")

    # ------------------------------------------------------------------ appels du script
    def _executer(self, methode: str, args: tuple) -> Any:
        if methode == "figure":
            return self._figure(*args)
        robot = self._robot()
        if robot is None:
            raise RuntimeError("le robot n'est plus disponible")
        if methode == "get_observation":
            return self._get_observation(robot, args)
        if methode == "send_action":
            return robot.send_action(verifier_action(args[0], robot.action_features))
        if methode == "noms":
            return {"observations": list(robot.get_observables()), "actions": list(robot.action_features)}
        raise ValueError(f"appel inconnu : {methode}")

    def _get_observation(self, robot: mirRobot, noms: tuple[str, ...]) -> Any:
        disponibles = robot.get_observables()
        if not noms:
            voulues = list(disponibles)
        else:
            voulues = []
            for nom in noms:
                trouvees = [nom] if nom in disponibles else [k for k in disponibles if k.startswith(f"{nom}.")]
                if not trouvees:
                    raise KeyError(f"mesure inconnue : « {nom} ». Mesures disponibles : {', '.join(disponibles)}")
                voulues += [k for k in trouvees if k not in voulues]
        # on ne lit que les appareils utiles (une caméra lue pour rien ralentirait la boucle)
        if self._abonnements != set(voulues):
            robot.enable_observations_by_name(voulues)
            self._abonnements = set(voulues)
        observation = robot.get_observation()
        if len(noms) == 1 and noms[0] in disponibles:
            return observation.get(noms[0])
        return {k: observation[k] for k in voulues if k in observation}
