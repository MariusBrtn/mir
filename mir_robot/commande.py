"""
Commandes : ce qui choisit, à chaque tour de boucle, l'action à envoyer au robot à partir de son observation.

Un générateur de trajectoire, une loi de commande ou un modèle appris sont des commandes. Les téléopérations
s'écrivent avec mir_robot.teleop et sont exécutées comme des commandes.
Elles ont toutes la même forme, ce qui permet à MIR de les lancer de la même façon, depuis l'interface
ou depuis un script, sur le robot réel comme sur le robot simulé :

    from mir_robot.commande import Commande

    class MaCommande(Commande):
        nom = "Ma commande"
        description = "Ce que fait la commande"

        def demarrer(self, robot):          # facultatif : robot.actions, robot.observations, robot.fps
            ...
        def action(self, observation):      # obligatoire : renvoie {"joint_1.position": 30.0, ...} ou None
            ...
        def arreter(self):                  # facultatif
            ...

En script :

    executer(robot, MaCommande(), fps=30)
"""
from __future__ import annotations
import importlib.util
import inspect
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from loguru import logger
from mir_devices.mir_device import DeviceAction, ActionValue
from mir_utils.period_waiters import PeriodWaiterExact

# commandes fournies avec MIR
DOSSIER_COMMANDES_FOURNIES = Path(__file__).parent / "commandes"
# commandes écrites par l'utilisateur
DOSSIER_COMMANDES_UTILISATEUR = Path(__file__).parent.parent / "mir_user_scripts" / "commandes"


@dataclass
class Parametre:
    """Un réglage d'une commande, que l'interface présente dans un formulaire (et qu'un script passe au constructeur)."""
    defaut: Any
    unite: str = ""
    libelle: str = ""


@dataclass
class InfoRobot:
    """Ce qu'une commande sait du robot qu'elle commande."""
    actions: dict[str, DeviceAction]       # actions acceptées par le robot : nom, unité, plage
    observations: list[str]                # noms des observations reçues à chaque tour de boucle
    fps: float                             # fréquence de la boucle
    # clavier : clavier.get_key() (prochaine touche pressée ou None), clavier.is_pressed(Key.Left) ;
    # fourni par l'application (touches de sa fenêtre) ou, en script, par pynput
    clavier: Any = None


class Commande:
    """Classe de base des commandes.

    famille : où l'interface propose la commande ("essai", "teleop", "robotique" ; "" : partout où c'est possible).
    parametres : réglages de la commande, ex. {"amplitude": Parametre(20.0, "°", "Amplitude")} ; ils deviennent des
    attributs (self.amplitude) et se règlent dans l'interface ou au constructeur : MaCommande(amplitude=30)."""
    nom: str = ""
    description: str = ""
    famille: str = ""
    parametres: dict[str, Parametre] = {}

    def __init__(self, **valeurs: Any) -> None:
        self._termine = False
        inconnus = set(valeurs) - set(self.parametres)
        if inconnus:
            raise TypeError(f"{type(self).__name__} : paramètre(s) inconnu(s) {', '.join(sorted(inconnus))}")
        for nom, parametre in self.parametres.items():
            setattr(self, nom, valeurs.get(nom, parametre.defaut))

    def demarrer(self, robot: InfoRobot) -> None:
        """Appelée une fois, avant le premier tour de boucle."""
        pass

    def action(self, observation: dict[str, Any]) -> dict[str, ActionValue] | None:
        """Appelée à chaque tour de boucle. Renvoie l'action à envoyer au robot, ou None pour ne rien envoyer."""
        raise NotImplementedError(f"{type(self).__name__} doit définir la méthode action(self, observation)")

    def arreter(self) -> None:
        """Appelée une fois, après le dernier tour de boucle, même en cas d'erreur."""
        pass

    def terminer(self) -> None:
        """À appeler depuis la commande pour demander l'arrêt de la boucle."""
        self._termine = True

    @property
    def est_termine(self) -> bool:
        return self._termine

    @classmethod
    def nom_affiche(cls) -> str:
        return cls.nom or cls.__name__


@dataclass
class CommandesDisponibles:
    """Résultat de la recherche des commandes."""
    commandes: dict[str, type[Commande]] = field(default_factory=dict)     # nom affiché -> classe
    fichiers: dict[str, Path] = field(default_factory=dict)            # nom affiché -> fichier source
    erreurs: dict[Path, BaseException] = field(default_factory=dict)   # fichier -> erreur au chargement


def decouvrir_commandes(dossiers: list[Path] | None = None, classe_base: type = None,  # type: ignore[assignment]
                        familles: tuple[str, ...] | None = None) -> CommandesDisponibles:
    """Charge les fichiers .py des dossiers et renvoie les classes qu'ils définissent et qui dérivent de classe_base
    (Commande par défaut), éventuellement limitées à certaines familles.
    Les fichiers sont relus à chaque appel, pour prendre en compte les modifications.
    Les fichiers dont le nom commence par '_' sont ignorés."""
    if dossiers is None:
        dossiers = [DOSSIER_COMMANDES_FOURNIES, DOSSIER_COMMANDES_UTILISATEUR]
    if classe_base is None:
        classe_base = Commande
    resultat = CommandesDisponibles()
    for dossier in dossiers:
        if not dossier.is_dir():
            continue
        for fichier in sorted(dossier.glob("*.py")):
            if fichier.name.startswith("_"):
                continue
            try:
                module = _charger_module(fichier)
            except BaseException as e:
                logger.warning(f"commande non chargée : {fichier} : {e}")
                resultat.erreurs[fichier] = e
                continue
            try:
                classes = _classes_du_module(module, fichier, classe_base)
            except BaseException as e:
                logger.warning(f"commande non chargée : {fichier} : {e}")
                resultat.erreurs[fichier] = e
                continue
            for classe in classes:
                if familles is not None and getattr(classe, "famille", "") not in familles:
                    continue
                nom = classe.nom_affiche()
                if nom in resultat.commandes:
                    logger.warning(f"commande '{nom}' définie deux fois, {fichier} ignoré")
                    continue
                resultat.commandes[nom] = classe
                resultat.fichiers[nom] = fichier
    return resultat


def _classes_du_module(module, fichier: Path, classe_base: type) -> list[type]:
    """Classes dérivées de classe_base définies dans ce module (pas celles qu'il importe)."""
    return [classe for _, classe in inspect.getmembers(module, inspect.isclass)
            if issubclass(classe, classe_base) and classe is not classe_base and classe.__module__ == module.__name__]


def _charger_module(fichier: Path):
    nom_module = f"mir_commandes.{fichier.parent.name}.{fichier.stem}"
    spec = importlib.util.spec_from_file_location(nom_module, fichier)
    if spec is None or spec.loader is None:
        raise ImportError(f"impossible de charger {fichier}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom_module] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[nom_module]
        raise
    return module


def verifier_action(action: dict[str, ActionValue], actions: dict[str, DeviceAction]) -> dict[str, ActionValue]:
    """Vérifie les noms de l'action renvoyée par une commande et borne les valeurs aux plages des moteurs."""
    inconnues = [nom for nom in action if nom not in actions]
    if inconnues:
        raise KeyError(f"action(s) inconnue(s) : {', '.join(inconnues)}. "
                       f"Actions possibles : {', '.join(actions)}")
    verifiee: dict[str, ActionValue] = {}
    for nom, valeur in action.items():
        plage = actions[nom].get_range()
        if plage is not None:
            valeur = min(max(valeur, plage[0]), plage[1])
        if actions[nom].get_type() == "int":
            valeur = int(round(valeur))
        verifiee[nom] = valeur
    return verifiee


class ExecutionCommande:
    """Une commande en cours d'exécution sur un robot connecté et configuré (réel ou simulé).
    Utilisée par executer() et par l'interface, qui fait tourner sa propre boucle."""

    def __init__(self, robot, commande: Commande, fps: float, clavier: Any = None):
        from mir_utils.keyboard_listener import LazyKeyboardListener
        self.robot = robot
        self.commande = commande
        self._actions = robot.action_features
        self._clavier = clavier if clavier is not None else LazyKeyboardListener()
        self._clavier.start()
        commande.demarrer(InfoRobot(actions=self._actions, observations=list(robot.get_enabled_observables()), fps=fps,
                                    clavier=self._clavier))

    def tour(self, observation: dict[str, Any]) -> bool:
        """Un tour de boucle : demande l'action à la commande et l'envoie au robot.
        Renvoie False quand la commande a demandé l'arrêt."""
        action = self.commande.action(observation)
        if action:
            self.robot.send_action(verifier_action(action, self._actions))
        return not self.commande.est_termine

    def arreter(self, arreter_moteurs: bool = True) -> None:
        """Arrête la commande puis les moteurs, même si la commande échoue en s'arrêtant.
        arreter_moteurs=False après un arrêt d'urgence : renvoyer une consigne réactiverait le couple."""
        try:
            self.commande.arreter()
        finally:
            self._clavier.stop()
            if arreter_moteurs:
                self.robot.motors_stop()


def executer(robot, commande: Commande, fps: float = 30, duree: float | None = None) -> None:
    """Fait tourner la boucle observation -> commande -> action sur un robot connecté et configuré (réel ou simulé).
    S'arrête quand la commande appelle terminer(), après 'duree' secondes, ou sur Ctrl+C."""
    execution = ExecutionCommande(robot, commande, fps)
    debut = time.perf_counter()
    periode = PeriodWaiterExact(1 / fps)
    try:
        while duree is None or time.perf_counter() - debut < duree:
            if not execution.tour(robot.get_observation()):
                break
            periode.wait()
    except KeyboardInterrupt:
        pass
    finally:
        execution.arreter()


def verifier_fichier(fichier: Path, classe_base: type | None = None) -> tuple[list[str], str | None, int | None]:
    """Charge un fichier de commandes (ou d'analyses) pour le vérifier.
    Renvoie (noms des classes trouvées, message d'erreur ou None, numéro de la ligne en cause ou None)."""
    import traceback
    classe_base = classe_base or Commande
    try:
        module = _charger_module(fichier)
    except SyntaxError as e:
        return [], f"Erreur de syntaxe ligne {e.lineno} : {e.msg}", e.lineno
    except BaseException as e:
        lignes = [f.lineno for f in traceback.extract_tb(e.__traceback__) if Path(f.filename) == fichier]
        ligne = lignes[-1] if lignes else None
        return [], f"{type(e).__name__} : {e}" + (f" (ligne {ligne})" if ligne else ""), ligne
    try:
        noms = [classe.nom_affiche() for classe in _classes_du_module(module, fichier, classe_base)]
    except BaseException as e:
        return [], f"{type(e).__name__} : {e}", None
    if not noms:
        return [], f"aucune classe dérivée de {classe_base.__name__} dans ce fichier", None
    return noms, None, None
