"""
Ce qu'un script lancé depuis MIR (Piloter → Scripts) utilise pour commander le robot :

    from mir_robot.script import robot, boucle

    for t in boucle(frequence=50, duree=5):
        position = robot.get_observation("joint_1.position")
        robot.send_action({"joint_1.position": 30.0})

Le script tourne dans son propre programme Python ; le robot (réel ou simulé) reste dans l'application, qui reçoit
chaque appel de get_observation / send_action. Arrêter le script (bouton ■) arrête aussi les moteurs.
"""
from __future__ import annotations
import builtins
import os
import sys
import traceback
import time
from multiprocessing.connection import Client
from typing import Any, Iterator

ADRESSE_ENV = "MIR_SCRIPT_ADRESSE"      # « hôte:port » du serveur du robot, donné par l'application
CLE_ENV = "MIR_SCRIPT_CLE"


class RobotDistant:
    """Le robot de l'application, vu depuis le script. Mêmes méthodes qu'un robot MIR."""

    def __init__(self):
        self._connexion = None
        self._noms: dict[str, list[str]] | None = None

    def _appel(self, methode: str, *args: Any) -> Any:
        if self._connexion is None:
            adresse = os.environ.get(ADRESSE_ENV)
            if not adresse:
                raise RuntimeError("Pas de robot : lancez ce script depuis MIR (Piloter → Scripts, bouton ▶ Lancer).")
            hote, port = adresse.rsplit(":", 1)
            self._connexion = Client((hote, int(port)), authkey=os.environ[CLE_ENV].encode())
        self._connexion.send((methode, args))
        ok, resultat = self._connexion.recv()
        if ok:
            return resultat
        # l'erreur s'est produite dans l'application : on la relance ici, avec la ligne du script en cause
        type_nom, message = resultat
        type_erreur = getattr(builtins, type_nom, None)
        if not (isinstance(type_erreur, type) and issubclass(type_erreur, Exception)):
            type_erreur = RuntimeError
        raise type_erreur(message) from None

    def get_observation(self, *noms: str) -> Any:
        """Mesures du robot.
            robot.get_observation()                    -> toutes les mesures : {"joint_1.position": 12.3, ...}
            robot.get_observation("joint_1.position")  -> une seule mesure : 12.3
            robot.get_observation("joint_1")           -> les mesures de joint_1 : {"joint_1.position": ..., ...}
            robot.get_observation("joint_1.position", "joint_2.position") -> ces deux mesures (dictionnaire)
        """
        return self._appel("get_observation", *noms)

    def send_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """Envoie des consignes, ex. robot.send_action({"joint_1.position": 30.0}).
        Les valeurs sont bornées aux butées des moteurs ; renvoie les consignes réellement envoyées."""
        return self._appel("send_action", dict(action))

    @property
    def observations(self) -> list[str]:
        """Noms des mesures disponibles."""
        return self._liste_noms()["observations"]

    @property
    def actions(self) -> list[str]:
        """Noms des consignes possibles."""
        return self._liste_noms()["actions"]

    def _liste_noms(self) -> dict[str, list[str]]:
        if self._noms is None:
            self._noms = self._appel("noms")
        return self._noms

    def __repr__(self) -> str:
        return "<robot MIR>"


def boucle(frequence: float, duree: float | None = None) -> Iterator[float]:
    """Boucle cadencée : un tour toutes les 1/frequence secondes, pendant 'duree' secondes (sans fin si None).
    Donne à chaque tour le temps t (en s) écoulé depuis le début.
        for t in boucle(frequence=50, duree=5):
            ...
    Si un tour dure plus longtemps que la période, le tour suivant démarre aussitôt (la boucle prend du retard)."""
    if frequence <= 0:
        raise ValueError("la fréquence doit être positive")
    periode = 1 / frequence
    debut = time.perf_counter()
    prochain = debut
    tours = retards = 0
    while True:
        t = time.perf_counter() - debut
        if duree is not None and t > duree:
            if retards > max(1, 0.02 * tours):
                # la boucle n'a pas tenu sa fréquence : on le dit, c'est souvent la clé d'un asservissement raté
                print(f"⚠ boucle(frequence={frequence:g}) : {retards} tours sur {tours} ont duré plus que la période "
                      f"({periode * 1000:.3g} ms) : calculs, print ou figures trop fréquents ?", file=sys.stderr)
            return
        tours += 1
        yield t
        prochain += periode
        attente = prochain - time.perf_counter()
        if attente > 0:
            time.sleep(attente)
        else:
            if tours > 1:       # le premier tour comprend la connexion au robot : son retard ne compte pas
                retards += 1
            prochain = time.perf_counter()      # en retard : on ne rattrape pas les tours manqués


def _afficher_erreur(type_erreur, erreur, tb):
    """Erreur non rattrapée : la trace ne montre que les lignes de l'élève, pas celles de MIR (ce fichier)."""
    pile = [f for f in traceback.extract_tb(tb) if f.filename != __file__]
    lignes = ["Traceback (most recent call last):\n"] + traceback.format_list(pile) if pile else []
    if isinstance(erreur, KeyError) and len(erreur.args) == 1 and isinstance(erreur.args[0], str):
        lignes.append(f"KeyError: {erreur.args[0]}\n")     # sans les guillemets ajoutés par KeyError
    else:
        lignes += traceback.format_exception_only(type_erreur, erreur)
    sys.stderr.write("".join(lignes))


robot = RobotDistant()
if os.environ.get(ADRESSE_ENV):
    sys.excepthook = _afficher_erreur
