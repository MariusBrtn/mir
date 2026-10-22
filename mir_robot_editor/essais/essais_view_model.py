"""
Étape Piloter → Essais : solliciter un actionneur, enregistrer sa réponse, comparer plusieurs essais
(par exemple le même essai sur le robot réel et sur le robot simulé).
"""
from __future__ import annotations
import time
import traceback
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable
import numpy as np
from loguru import logger
from PySide6.QtCore import Signal
from mir_devices.mir_device import ObservablePropertyFloat
from mir_robot.mir_robot import DOSSIER_ESSAIS as DOSSIER_ESSAIS_ROBOT, dossier_du_robot, mirRobot
from mir_robot.commande import CommandesDisponibles, decouvrir_commandes
from mir_robot.essai import Essai, Sollicitation, lancer_essai
from mir_utils.concurrency import BackgroundWorker
from mir_utils.ui.view_model_base import VMAction, ViewModelBase

# essais d'un robot pas encore enregistré (ceux d'un robot enregistré vont dans son dossier : robots/<robot>/essais)
DOSSIER_ESSAIS = Path(__file__).parent.parent.parent / "data" / "essais"
# réglages du moteur modifiables dans un essai : attribut de mirMotor -> (libellé, min, max)
REGLAGES_MOTEUR = {
    "P": ("P", 0, 255),
    "I": ("I", 0, 255),
    "D": ("D", 0, 255),
    "position_mode_velocity": ("Vitesse max (tr/min)", 1, 200),
    "torque_limit": ("Couple max (‰)", 0, 1000),
}


def _au_rythme_reel(monde) -> Callable[[float], float]:
    """avancer(duree) pour lancer_essai : la physique avance pas à pas, et on attend que l'horloge la rattrape
    (sans jamais attendre si le calcul prend du retard)."""
    debut = time.perf_counter()
    temps = 0.0

    def avancer(duree: float) -> float:
        nonlocal temps
        fait = monde.advance(duree)
        temps += fait
        attente = debut + temps - time.perf_counter()
        if attente > 0:
            time.sleep(attente)
        return fait
    return avancer


class EssaisVMAction(Enum):
    LANCER = auto()
    ARRETER = auto()
    OUVRIR = auto()
    ENREGISTRER = auto()


class EssaisViewModel(ViewModelBase[EssaisVMAction]):
    robot_changed = Signal()                 # actionneurs et grandeurs disponibles changés
    briques_changed = Signal()               # sollicitations relues
    essais_changed = Signal()                # liste des essais changée
    essai_termine = Signal(object)           # Essai
    busy_state_changed = Signal(bool)
    _essai_echoue = Signal(str)

    def __init__(self, dialog_provider, motor_settings: Callable[[str], dict[str, int]] | None = None,
                 apply_motor_settings: Callable[[str, dict[str, int]], None] | None = None,
                 conditions: Callable[[], dict[str, Any]] | None = None,
                 other_busy: Callable[[], bool] | None = None, sim_world: Callable[[], Any] | None = None):
        super().__init__(dialog_provider)
        self._actions[EssaisVMAction.LANCER] = VMAction("Lancer l'essai", "Amener l'actionneur à sa valeur initiale puis appliquer la sollicitation")
        self._actions[EssaisVMAction.ARRETER] = VMAction("Arrêter", "Interrompre l'essai en cours")
        self._actions[EssaisVMAction.OUVRIR] = VMAction("Ouvrir un essai...", "Ajouter à la liste un essai enregistré", enabled=True)
        self._actions[EssaisVMAction.ENREGISTRER] = VMAction("Enregistrer l'essai...", "Enregistrer l'essai sélectionné dans un fichier", enabled=True)
        self._motor_settings = motor_settings or (lambda motor: {})
        self._apply_motor_settings = apply_motor_settings
        self._conditions = conditions or (lambda: {})
        self._other_busy = other_busy or (lambda: False)
        self._sim_world = sim_world or (lambda: None)
        self._robot: mirRobot | None = None
        self._worker = BackgroundWorker()
        self._running = False
        self._stop = False
        self.sollicitations = CommandesDisponibles()
        self.essais: list[Essai] = []
        # en simulation, mesures de l'essai en cours (t, observation, consigne), pour les tracer pendant le mouvement
        self._en_direct: list[tuple[float, dict[str, Any], float]] = []
        # servos simulés dont l'essai a changé le PID : il revient au réglage par défaut en quittant les essais
        self._pid_simules_modifies: set[str] = set()
        self.refresh_briques()
        self._essai_echoue.connect(lambda tb: self._dialogProvider.error("L'essai a échoué", tb))

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, tb):
        self._worker.shutdown()

    # ------------------------------------------------------------------ robot
    def set_other_busy(self, other_busy):
        """other_busy() : True quand une autre activité utilise le robot (une seule à la fois)."""
        self._other_busy = other_busy

    def connect_to_robot(self, robot: mirRobot):
        self._robot = robot
        self._update_actions()
        self.robot_changed.emit()

    def disconnect_from_robot(self):
        if self._running:
            raise RuntimeError("Un essai est en cours")
        self._robot = None
        self._update_actions()
        self.robot_changed.emit()

    def is_simulation(self) -> bool:
        return bool(self._conditions().get("simulation"))

    def sim_world(self):
        """Monde simulé à afficher en 3D (None avec le robot réel)."""
        return self._sim_world() if self.is_simulation() else None

    def actionneurs(self) -> dict[str, str]:
        """Actionneurs sollicitables : nom de l'action -> unité."""
        if self._robot is None:
            return {}
        return {nom: action.get_unit() for nom, action in self._robot.action_features.items()}

    def unite(self, nom: str) -> str:
        """Unité d'une grandeur mesurée (ou d'une action) du robot connecté."""
        if self._robot is None:
            return ""
        prop = self._robot.get_observables().get(nom)
        if prop is not None:
            return getattr(prop, "unit", "")
        return self.actionneurs().get(nom, "")

    def grandeurs(self, actionneur: str) -> list[str]:
        """Grandeurs mesurables (scalaires) du moteur de l'actionneur."""
        if self._robot is None or not actionneur:
            return []
        moteur = actionneur.split(".")[0]
        # en simulation, la température est constante : rien à mesurer
        return [nom for nom, prop in self._robot.get_observables().items()
                if isinstance(prop, ObservablePropertyFloat) and nom.split(".")[0] == moteur
                and not (self.is_simulation() and nom.endswith(".temperature"))]

    def plage_grandeur(self, nom: str) -> tuple[float, float] | None:
        """Bornes d'une grandeur mesurée (pour tracer ses axes avant toute mesure)."""
        prop = self._robot.get_observables().get(nom) if self._robot is not None else None
        if isinstance(prop, ObservablePropertyFloat) and prop.min_value is not None and prop.max_value is not None:
            return float(prop.min_value), float(prop.max_value)
        return None

    def plage(self, actionneur: str) -> tuple[float, float] | None:
        if self._robot is None or actionneur not in self._robot.action_features:
            return None
        return self._robot.action_features[actionneur].get_range()

    def reglages(self, actionneur: str) -> dict[str, int]:
        """Réglages du moteur de l'actionneur. En simulation : le PID du servo simulé (le sien, pas celui de la
        configuration, qui est celui du servo réel)."""
        if not actionneur:
            return {}
        moteur = actionneur.split(".")[0]
        monde = self.sim_world()
        if monde is not None and moteur in monde.motors:
            return dict(zip(("P", "I", "D"), (float(v) for v in monde.get_pid(moteur))))
        return self._motor_settings(moteur)

    def restaurer_pid_simules(self):
        """En quittant les essais : les servos simulés reprennent leur PID par défaut (le seul utilisé ailleurs)."""
        monde = self.sim_world()
        if monde is not None:
            for moteur in self._pid_simules_modifies & set(monde.motors):
                monde.set_pid(moteur, monde.joints[moteur].pid)
        self._pid_simules_modifies.clear()

    # ------------------------------------------------------------------ briques
    def refresh_briques(self):
        self.sollicitations = decouvrir_commandes(familles=("essai",))
        erreurs = self.sollicitations.erreurs
        if erreurs:
            details = "\r\n\r\n".join(f"{fichier} :\r\n{erreur}" for fichier, erreur in erreurs.items())
            self._dialogProvider.warning("Fichiers non chargés", details)
        self.briques_changed.emit()

    # ------------------------------------------------------------------ essai
    def lancer(self, sollicitation_nom: str, actionneur: str, parametres: dict[str, float],
               grandeurs: list[str], fps: int, reglages: dict[str, int] | None = None):
        if self._robot is None or self._running:
            return
        if self._other_busy():
            self._dialogProvider.information("Essai impossible", "Arrêtez d'abord ce qui fait bouger le robot (Téléopération, Scripts ou Collecter des données).")
            return
        moteur = actionneur.split(".")[0]
        monde = self.sim_world()
        if monde is not None and moteur in monde.motors:
            # simulation : seul le PID du servo simulé change, le temps des essais ; la configuration n'est pas touchée
            pid = tuple(float((reglages or {}).get(k, v)) for k, v in zip(("P", "I", "D"), monde.get_pid(moteur)))
            if pid != tuple(monde.get_pid(moteur)):
                monde.set_pid(moteur, pid)
                self._pid_simules_modifies.add(moteur)
        elif reglages and reglages != self.reglages(actionneur) and self._apply_motor_settings is not None:
            # réglages modifiés : appliqués au moteur (et à la configuration) avant l'essai
            self._apply_motor_settings(moteur, reglages)
            if self._robot is None:
                return
        try:
            sollicitation: Sollicitation = self.sollicitations.commandes[sollicitation_nom](actionneur=actionneur, **parametres)
        except Exception as e:
            self._dialogProvider.exception(e, "Impossible de créer la sollicitation")
            return
        # la consigne doit se calculer sur toute la durée, avant de démarrer quoi que ce soit (ex. période nulle)
        try:
            for t in np.linspace(0.0, float(sollicitation.duree), 11):
                float(sollicitation.consigne(float(t)))
        except ZeroDivisionError:
            self._dialogProvider.information("Essai impossible", "Une durée ou une période de la sollicitation est "
                                             "nulle : donnez-lui une valeur plus grande que 0.")
            return
        except Exception as e:
            self._dialogProvider.exception(e, "La consigne de la sollicitation ne peut pas être calculée")
            return
        conditions = {**self._conditions(), "reglages_moteur": self.reglages(actionneur), "grandeurs": grandeurs}
        # en réel, rien n'est tracé pendant l'essai (l'affichage perturberait l'acquisition) ; en simulation, les
        # mesures sont gardées au fil de l'essai pour être tracées pendant le mouvement
        self._en_direct = []
        progression = (lambda t, observation, consigne: self._en_direct.append((t, observation, consigne))) \
            if self.is_simulation() else None
        self._stop = False
        self._running = True
        self._update_actions()
        self.busy_state_changed.emit(True)
        try:
            avancer = None
            if monde is not None:
                if moteur in monde.motors and not monde.is_velocity_motor(moteur):
                    # départ à la valeur initiale, immobile, quel que soit le PID (même s'il oscille)
                    monde.place_motor(moteur, sollicitation.consigne(0.0))
                # l'essai fait lui-même avancer la physique, un pas exact entre deux mesures (mesures régulières,
                # toutes nouvelles) ; il garde le rythme du temps réel pour que le mouvement reste lisible dans la 3D
                monde.stop_realtime()
                self._monde_arrete = monde
                avancer = _au_rythme_reel(monde)
            robot = self._robot
            self._worker.run(lambda: lancer_essai(robot, sollicitation, fps=fps, observations=grandeurs,
                                                  conditions=conditions, progression=progression,
                                                  arret=lambda: self._stop, avancer=avancer),
                             self._on_termine, self._on_echec, self)
        except Exception as e:
            self._fin()         # jamais d'essai bloqué « en cours »
            self._dialogProvider.exception(e, "L'essai n'a pas pu démarrer")

    def arreter(self):
        self._stop = True

    def arret_urgence(self):
        """Coupe le couple tout de suite, et encore à la fin de l'essai (qui maintient sinon les moteurs en position)."""
        self._stop = True
        self._urgence = True
        if self._robot is not None:
            self._robot.motors_emergency_stop()

    def is_running(self) -> bool:
        return self._running

    def mesures_en_direct(self) -> list[tuple[float, dict[str, Any], float]]:
        """Mesures de l'essai en cours en simulation (vide en réel) : [(t, observation, consigne)]."""
        return list(self._en_direct)

    def _fin(self):
        monde, self._monde_arrete = getattr(self, "_monde_arrete", None), None
        if monde is not None:
            monde.start_realtime()          # la physique reprend au rythme de l'horloge
        if getattr(self, "_urgence", False) and self._robot is not None:
            self._robot.motors_emergency_stop()
        self._urgence = False
        self._running = False
        self._update_actions()
        self.busy_state_changed.emit(False)

    def _on_termine(self, essai: Essai):
        self._fin()
        self.essais.append(essai)
        self.essais_changed.emit()
        self.essai_termine.emit(essai)

    def _on_echec(self, error: Exception):
        self._fin()
        self._essai_echoue.emit("".join(traceback.format_exception(error)))

    def _update_actions(self):
        self._actions[EssaisVMAction.LANCER].set_enabled(self._robot is not None and not self._running)
        self._actions[EssaisVMAction.ARRETER].set_enabled(self._running)

    # ------------------------------------------------------------------ liste des essais
    def ouvrir(self):
        chemin = self._dialogProvider.open_file("Ouvrir un essai", str(self._dossier_essais()), "Essai MIR (*.npz)")
        if not chemin:
            return
        try:
            self.essais.append(Essai.charger(chemin))
        except Exception as e:
            self._dialogProvider.exception(e, "Impossible d'ouvrir l'essai")
            return
        self.essais_changed.emit()

    def _dossier_essais(self) -> Path:
        """Dossier essais du robot ouvert (s'il est enregistré)."""
        configuration = self._conditions().get("configuration")
        return dossier_du_robot(configuration) / DOSSIER_ESSAIS_ROBOT if configuration else DOSSIER_ESSAIS

    def _chemin_par_defaut(self, essai: Essai) -> Path:
        # ex. 2026-10-16_12h55m29_joint_1_Echelon_0-30deg_500Hz_reel.npz
        mode = "simule" if essai.conditions.get("simulation") else "reel"
        moteur = essai.actionneur.split(".")[0]
        fps = essai.conditions.get("fps")
        date = str(essai.conditions.get("date") or time.strftime("%Y-%m-%d %H:%M:%S"))     # instant de l'essai
        date = date.replace(" ", "_").replace(":", "h", 1).replace(":", "m", 1)
        nom = f"{date}_{moteur}_{essai.resume_sollicitation(fichier=True)}" \
              f"{f'_{fps:g}Hz' if fps else ''}_{mode}"
        return self._dossier_essais() / f"{nom}.npz"

    def _enregistrer(self, essai: Essai, chemin: str | Path) -> bool:
        try:
            Path(chemin).parent.mkdir(parents=True, exist_ok=True)
            essai.enregistrer(chemin)
            return True
        except Exception as e:
            logger.error(f"essai non enregistré : {e}")
            self._dialogProvider.exception(e, "L'essai n'a pas pu être enregistré")
            return False

    def enregistrer(self, index: int):
        """Enregistre l'essai choisi, dans le fichier choisi par l'utilisateur."""
        if not 0 <= index < len(self.essais):
            return
        essai = self.essais[index]
        chemin = self._dialogProvider.save_file("Enregistrer l'essai", str(essai.chemin or self._chemin_par_defaut(essai)),
                                                "Essai MIR (*.npz)", try_use_last_directory=False)
        if not chemin:
            return
        if not chemin.endswith(".npz"):
            chemin += ".npz"
        if self._enregistrer(essai, chemin):
            self.essais_changed.emit()

    def retirer(self, indices: list[int]):
        """Retire ces essais de la liste (les fichiers enregistrés restent sur le disque) ; une seule confirmation
        si certains ne sont pas enregistrés."""
        indices = sorted({i for i in indices if 0 <= i < len(self.essais)}, reverse=True)
        if not indices:
            return
        perdus = sum(1 for i in indices if self.essais[i].chemin is None)
        texte = ("Cet essai n'est pas enregistré : il sera perdu." if len(indices) == 1 else
                 f"{perdus} essai{'s' if perdus > 1 else ''} sur {len(indices)} "
                 f"{'ne sont pas enregistrés : ils seront perdus' if perdus > 1 else 'n’est pas enregistré : il sera perdu'}.")
        if perdus and not self._dialogProvider.question_yes_no(
                "Retirer les essais", f"{texte}\r\nRetirer quand même ?"):
            return
        for i in indices:
            del self.essais[i]
        self.essais_changed.emit()
