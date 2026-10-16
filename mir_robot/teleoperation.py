"""
Téléopération par correspondance : un fichier de l'élève, sans classe.

    TELEOPERATEUR = "bras_leader"      # un robot du dossier mir/robots, ou "clavier"
    FREQUENCE = 30                     # facultatif : fréquence proposée dans l'interface (Hz)

    def teleoperer(teleoperateur, robot):
        return teleoperateur           # dictionnaire de consignes, ou None pour ne rien envoyer

À chaque tour de boucle, MIR lit le téléopérateur (dictionnaire de ce qu'il mesure), appelle teleoperer()
avec aussi les mesures du robot piloté, puis envoie les consignes. MIR ouvre et ferme lui-même le téléopérateur.

Ce que contient « teleoperateur » :
  - un robot (bras leader) : ses positions, ex. {"joint_1.position": 12.3, ...} ; c'est toujours le robot réel,
    même quand le robot piloté est simulé ;
  - "clavier" : l'état des touches, True si elle est enfoncée : {"gauche": False, "droite": True, "a": False, ...}
    (touches de la fenêtre de MIR, ou du clavier en script).
"""
from __future__ import annotations
from types import ModuleType
from typing import Any
from mir_robot.commande import Commande
from mir_utils.keyboard_listener import Key

CLAVIER = "clavier"
FAMILLE_TELEOP = "teleop"

# nom des touches pour les élèves
NOMS_TOUCHES: dict[Key, str] = {
    Key.Left: "gauche", Key.Right: "droite", Key.Up: "haut", Key.Down: "bas", Key.Space: "espace",
    Key.Enter: "entree", Key.Esc: "echap", Key.Tab: "tab", Key.Backspace: "retour", Key.Delete: "suppr",
    Key.Plus: "+", Key.Minus: "-",
}
NOMS_TOUCHES.update({Key[c]: c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
NOMS_TOUCHES.update({Key[f"Digit{d}"]: str(d) for d in range(10)})


class TeleoperateurClavier:
    """Le clavier comme téléopérateur : l'état des touches."""

    def __init__(self, clavier):
        self._clavier = clavier

    def lire(self) -> dict[str, bool]:
        while self._clavier.get_key() is not None:      # les appuis en attente ne servent pas ici : seul l'état compte
            pass
        return {nom: self._clavier.is_pressed(key) for key, nom in NOMS_TOUCHES.items()}

    def fermer(self):
        pass


class TeleoperateurRobot:
    """Un robot MIR comme téléopérateur (bras leader) : ses positions. Toujours le robot réel."""

    def __init__(self, nom: str):
        from mir_robot.mir_robot import chemin_robot, mirRobot, mirRobotConfig, robots_disponibles
        chemin = chemin_robot(nom)
        if not chemin.exists():
            raise FileNotFoundError(f"robot « {nom} » introuvable dans le dossier des robots "
                                    f"(robots disponibles : {', '.join(robots_disponibles()) or 'aucun'})")
        self._robot = mirRobot(mirRobotConfig.load(str(chemin)))
        self._robot.connect()
        try:
            self._robot.configure()
            self._robot.enable_observations_by_name([n for n in self._robot.get_observables() if n.endswith(".position")])
        except BaseException:
            self._robot.disconnect()
            raise

    def lire(self) -> dict[str, Any]:
        return self._robot.get_observation()

    def fermer(self):
        self._robot.disconnect()


def ouvrir_teleoperateur(nom: str, clavier):
    if nom == CLAVIER:
        return TeleoperateurClavier(clavier)
    return TeleoperateurRobot(nom)


class CommandeCorrespondance(Commande):
    """Commande construite à partir d'un fichier « TELEOPERATEUR + teleoperer() »."""
    famille = FAMILLE_TELEOP
    module: ModuleType
    frequence: float | None = None

    def demarrer(self, robot):
        self._actions = robot.actions
        self._teleoperateur = ouvrir_teleoperateur(self.module.TELEOPERATEUR, robot.clavier)

    def action(self, observation):
        entree = self._teleoperateur.lire()
        consignes = self.module.teleoperer(entree, observation)
        if consignes is None:
            return None
        if not isinstance(consignes, dict):
            raise TypeError(f"teleoperer() doit renvoyer un dictionnaire de consignes ou None, pas {type(consignes).__name__}")
        # ce qui vient tel quel du téléopérateur (ex. une articulation en trop sur le leader) est ignoré s'il ne
        # correspond à aucune action du robot piloté ; une consigne écrite à la main reste vérifiée (fautes de frappe)
        return {nom: v for nom, v in consignes.items() if nom in self._actions or nom not in entree}

    def arreter(self):
        if getattr(self, "_teleoperateur", None) is not None:
            self._teleoperateur.fermer()


def commande_depuis_module(module: ModuleType, nom_fichier: str) -> type[Commande] | None:
    """Classe de commande pour un fichier qui définit teleoperer() (None sinon)."""
    if not callable(getattr(module, "teleoperer", None)):
        return None
    if not isinstance(getattr(module, "TELEOPERATEUR", None), str):
        raise ValueError("le fichier doit définir TELEOPERATEUR = \"clavier\" ou le nom d'un robot, ex. \"bras_leader\"")
    doc = (module.__doc__ or "").strip().splitlines()
    attributs = {
        "nom": getattr(module, "NOM", nom_fichier),
        "description": getattr(module, "DESCRIPTION", doc[0] if doc else f"Téléopérateur : {module.TELEOPERATEUR}"),
        "module": module,
        "frequence": getattr(module, "FREQUENCE", None),
        "__module__": module.__name__,
    }
    return type(f"Correspondance_{nom_fichier}", (CommandeCorrespondance,), attributs)
