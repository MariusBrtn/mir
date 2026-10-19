"""
Étape « Collecter des données » : enregistrer des démonstrations faites en téléopération, au format LeRobot.

La téléopération tourne en continu (on remet le robot en position entre deux démonstrations) ; une démonstration
s'enregistre pendant une durée fixe, après un court compte à rebours, puis on la revoit et on la valide ou on la
recommence. Les datasets sont rangés dans le dossier du robot : robots/<robot>/datasets/<nom>/.
"""
from __future__ import annotations
import subprocess
import sysconfig
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any
from loguru import logger
from PySide6.QtCore import Signal
from mir_devices.mir_device import ObservablePropertyBitmap, ObservablePropertyPolar
from mir_robot.commande import ExecutionCommande
from mir_robot.donnees import DatasetMIR, FormatDataset, datasets_du_robot, episode_depuis_trames
from mir_robot.mir_robot import mirRobot
from mir_robot.teleop.loading import discover_teleops
from mir_utils.concurrency import BackgroundWorker
from mir_utils.keyboard_listener import KeyQueue
from mir_utils.period_waiters import PeriodWaiterSafeForJitter
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import ViewModelBase

DECOMPTE_S = 3              # compte à rebours avant l'enregistrement d'une démonstration
AFFICHAGE_HZ = 15           # rafraîchissement de la vue en direct (caméra, lidar)
ERREURS_TOLEREES = 5        # lectures ratées d'affilée (bus moteur, capteur) avant d'arrêter la collecte


class Phase(Enum):
    ARRET = "arrêt"                     # téléopération arrêtée
    LIBRE = "libre"                     # téléopération active, rien n'est enregistré (remise en position)
    DECOMPTE = "décompte"
    ENREGISTREMENT = "enregistrement"
    REVUE = "revue"                     # démonstration terminée : à valider ou à recommencer


class CollecteVMAction(Enum):
    pass


def est_capteur(prop) -> bool:
    return isinstance(prop, (ObservablePropertyBitmap, ObservablePropertyPolar))


class CollecteViewModel(ViewModelBase[CollecteVMAction]):
    busy_state_changed = Signal(bool)            # téléopération active (une seule activité à la fois sur le robot)
    robot_changed = Signal()
    datasets_changed = Signal()
    phase_changed = Signal(object, float)        # Phase, temps restant ou écoulé (s)
    observation_ready = Signal(dict)             # pour la vue en direct
    episode_a_revoir = Signal(dict)              # démonstration enregistrée, pas encore validée
    sauvegarde_changed = Signal(bool)            # écriture d'un épisode en cours
    _fin_boucle = Signal(str)                    # émis depuis la boucle : message d'erreur ou ""

    def __init__(self, dialog_provider: IDialogProvider, other_busy=None, sim_world=None, conditions=None,
                 scene=None, choisir_scene=None, nom_scene=None):
        super().__init__(dialog_provider)
        self._other_busy = other_busy or (lambda: False)
        self._sim_world = sim_world or (lambda: None)
        self._conditions = conditions or (lambda: {})
        self._scene = scene or (lambda: "table vide")               # scène actuelle du robot simulé
        self._choisir_scene = choisir_scene or (lambda nom: False)
        self.nom_scene = nom_scene or (lambda nom: nom)             # nom affiché d'une scène notée dans un dataset
        self._alignement = False                # changer de scène reconstruit le robot : pas de ré-entrée
        self._robot: mirRobot | None = None
        self._dossier_robot: Path | None = None
        self._teleop_dir: Path | None = None
        self.keyboard = KeyQueue()
        self._boucle = BackgroundWorker()
        self._ecriture = BackgroundWorker()
        self._lock = threading.Lock()
        self._en_cours = False
        self._arret = False
        self._urgence = False
        self._phase = Phase.ARRET
        self._demande_demo = False
        self._trames: list[dict[str, Any]] = []
        self._format: FormatDataset | None = None
        self._fps = 20
        self._duree_s = 6.0
        self._teleop_nom = ""
        self._sauvegarde = False
        self._fin_boucle.connect(self._on_fin_boucle)

    # ------------------------------------------------------------------ robot et dossiers
    def set_other_busy(self, other_busy):
        """other_busy() : True quand une autre activité utilise le robot (une seule à la fois)."""
        self._other_busy = other_busy

    def connect_to_robot(self, robot: mirRobot):
        self._robot = robot
        self.robot_changed.emit()

    def disconnect_from_robot(self):
        if self._en_cours:
            raise RuntimeError("Une collecte est en cours")
        self._robot = None
        self.robot_changed.emit()

    def has_robot(self) -> bool:
        return self._robot is not None

    def sim_world(self):
        return self._sim_world()

    def set_dossier_robot(self, dossier: Path | None, teleop_dir: Path | None):
        self._dossier_robot, self._teleop_dir = dossier, teleop_dir
        self.datasets_changed.emit()

    def observables(self) -> dict:
        return dict(self._robot.get_observables()) if self._robot is not None else {}

    def actions(self) -> list[str]:
        return list(self._robot.action_features) if self._robot is not None else []

    def teleops(self) -> list[str]:
        return list(discover_teleops(self._teleop_dir).commandes)

    # ------------------------------------------------------------------ une scène par dataset (en simulé)
    @staticmethod
    def scene_du_dataset(ds: DatasetMIR | None) -> str | None:
        """Scène des épisodes simulés du dataset (celle du dernier), None s'il n'en a pas."""
        if ds is None or not ds.existe():
            return None
        scenes = [e.conditions.get("scene") for e in ds.episodes() if e.conditions.get("simulation")]
        return next((s for s in reversed(scenes) if s), None)

    def aligner_scene(self, ds: DatasetMIR | None) -> None:
        """En simulé : choisit la scène du dataset, pour que ses démonstrations restent dans la même scène."""
        scene = self.scene_du_dataset(ds)
        if self._alignement or scene is None or scene == self._scene() or self._en_cours:
            return
        self._alignement = True
        try:
            self._choisir_scene(scene)
        finally:
            self._alignement = False

    def conflit_de_scene(self, ds: DatasetMIR | None) -> str | None:
        """Message si la scène actuelle n'est pas celle du dataset (en simulé), sinon None."""
        scene = self.scene_du_dataset(ds)
        if scene is None or not self._conditions().get("simulation") or scene == self._scene():
            return None
        return (f"Les démonstrations de « {ds.nom} » ont été enregistrées dans la scène « {self.nom_scene(scene)} », "
                f"et la scène actuelle est « {self.nom_scene(self._scene())} ».\r\nUn dataset garde une seule scène : choisissez la sienne dans "
                "l'en-tête, ou créez un nouveau dataset.")

    def datasets(self) -> list[DatasetMIR]:
        return datasets_du_robot(self._dossier_robot) if self._dossier_robot is not None else []

    def nouveau_dataset(self, nom: str) -> DatasetMIR | None:
        if self._dossier_robot is None:
            self._dialogProvider.information("Nouveau dataset", "Enregistrez d'abord le robot : ses datasets sont "
                                             "rangés dans son dossier.")
            return None
        ds = DatasetMIR(self._dossier_robot / "datasets" / nom)
        if ds.dossier.exists():
            self._dialogProvider.information("Nouveau dataset", f"Le dataset « {nom} » existe déjà.")
            return None
        return ds        # le dossier n'est créé qu'avec le premier épisode validé

    # ------------------------------------------------------------------ téléopération et démonstrations
    def is_running(self) -> bool:
        return self._en_cours

    def phase(self) -> Phase:
        return self._phase

    def demarrer(self, teleop: str, fmt: FormatDataset, fps: int, duree_s: float):
        """Démarre la téléopération (sans enregistrer) : on peut mettre le robot en position."""
        if self._en_cours or self._robot is None:
            return
        if self._other_busy():
            self._dialogProvider.information("Collecte impossible", "Arrêtez d'abord ce qui fait bouger le robot "
                                             "(Essais, Téléopération ou Scripts).")
            return
        commandes = discover_teleops(self._teleop_dir)
        if teleop not in commandes.commandes:
            self._dialogProvider.information("Collecte impossible", f"Téléopération « {teleop} » introuvable.")
            return
        try:
            commande = commandes.commandes[teleop]()
        except Exception as e:
            self._dialogProvider.exception(e, "Impossible de créer la téléopération")
            return
        self._format, self._fps, self._duree_s, self._teleop_nom = fmt, fps, duree_s, teleop
        self._arret = self._urgence = self._demande_demo = False
        self._en_cours = True
        self.keyboard.clear()
        self.busy_state_changed.emit(True)
        self._set_phase(Phase.LIBRE)
        self._boucle.run(lambda: self._tourner(commande), lambda _: None, lambda e: self._fin_boucle.emit(str(e)))

    def demonstration(self):
        """Enregistre une démonstration (après le compte à rebours)."""
        if self._phase == Phase.LIBRE:
            with self._lock:
                self._demande_demo = True

    def arreter(self):
        self._arret = True

    def arret_urgence(self):
        self._urgence = True
        self._arret = True
        if self._robot is not None:
            try:
                self._robot.motors_emergency_stop()
            except Exception as e:
                logger.error(f"arrêt d'urgence : {e}")

    def _set_phase(self, phase: Phase, temps: float = 0.0):
        self._phase = phase
        self.phase_changed.emit(phase, temps)

    def _tourner(self, commande):
        """Boucle de la collecte (thread de fond) : téléopération à chaque tour, enregistrement pendant une démonstration."""
        robot, fmt, fps = self._robot, self._format, self._fps
        # grandeurs enregistrées, et positions dont les téléopérations ont besoin
        observables = robot.get_observables()
        noms = set(fmt.etat) | set(fmt.images) | set(fmt.tableaux) | {n for n in observables if n.endswith(".position")}
        robot.enable_observations_by_name([n for n in observables if n in noms])
        execution = ExecutionCommande(robot, commande, fps, clavier=self.keyboard)
        n_trames = max(1, int(round(self._duree_s * fps)))
        attente = PeriodWaiterSafeForJitter(1 / fps)
        derniere = {}                  # dernière consigne de chaque action (si la téléop n'envoie rien à un tour)
        dernier_affichage = 0.0
        debut_phase = time.perf_counter()
        phase = Phase.LIBRE
        trames: list[dict[str, Any]] = []
        erreur = ""
        erreurs_suivies = 0
        manquees = 0           # mesures ratées pendant l'enregistrement, remplacées par la précédente
        try:
            while not self._arret:
                try:
                    observation = robot.get_observation()
                    if not derniere:
                        derniere = {a: (0.0 if a.endswith(".velocity") else float(observation.get(a, 0.0)))
                                    for a in fmt.actions}
                    if not execution.tour(observation):
                        break                              # la téléopération s'est terminée (Échap)
                    erreurs_suivies = 0
                except (ConnectionError, TimeoutError, OSError) as e:
                    # lecture ratée (servo qui ne répond pas à temps, capteur wifi...) : passagère le plus souvent
                    erreurs_suivies += 1
                    logger.warning(f"collecte : lecture ratée ({erreurs_suivies}/{ERREURS_TOLEREES}) : {e}")
                    if erreurs_suivies > ERREURS_TOLEREES:
                        raise
                    if phase == Phase.ENREGISTREMENT and trames:
                        trames.append(trames[-1])
                        manquees += 1
                        if len(trames) >= n_trames:
                            self._fin_demo(trames, manquees)
                            phase = Phase.LIBRE
                    attente.wait()
                    continue
                if execution.derniere_action:
                    derniere.update(execution.derniere_action)
                maintenant = time.perf_counter()
                with self._lock:
                    demande, self._demande_demo = self._demande_demo, False
                if phase == Phase.LIBRE and demande:
                    phase, debut_phase = Phase.DECOMPTE, maintenant
                elif phase == Phase.DECOMPTE and maintenant - debut_phase >= DECOMPTE_S:
                    phase, debut_phase, trames, manquees = Phase.ENREGISTREMENT, maintenant, [], 0
                if phase == Phase.ENREGISTREMENT:
                    trames.append(fmt.trame(observation, derniere))
                    if len(trames) >= n_trames:
                        self._fin_demo(trames, manquees)
                        phase = Phase.LIBRE
                if phase in (Phase.DECOMPTE, Phase.ENREGISTREMENT):
                    ecoule = maintenant - debut_phase
                    self._set_phase(phase, DECOMPTE_S - ecoule if phase == Phase.DECOMPTE else ecoule)
                if maintenant - dernier_affichage >= 1 / AFFICHAGE_HZ:
                    dernier_affichage = maintenant
                    self.observation_ready.emit(observation)
                attente.wait()
        except Exception as e:
            logger.exception("collecte")
            erreur = f"{type(e).__name__} : {e}"
        finally:
            try:
                execution.arreter(arreter_moteurs=not self._urgence)
            except Exception as e:
                erreur = erreur or str(e)
            self._fin_boucle.emit(erreur)

    def _fin_demo(self, trames: list[dict[str, Any]], manquees: int):
        """Démonstration complète (thread de la boucle) : à revoir, puis à valider ou à recommencer."""
        self._trames = trames
        episode = episode_depuis_trames(self._format, self._fps, trames)
        episode["manquees"] = manquees
        self.episode_a_revoir.emit(episode)
        self._set_phase(Phase.REVUE)

    def _on_fin_boucle(self, erreur: str):
        self._en_cours = False
        if self._phase != Phase.REVUE:
            self._set_phase(Phase.ARRET)
        self.busy_state_changed.emit(False)
        if erreur:
            self._dialogProvider.error("La collecte s'est arrêtée", erreur)

    # ------------------------------------------------------------------ revue : valider ou recommencer
    def recommencer(self):
        """La démonstration n'est pas gardée ; la téléopération continue pour la refaire."""
        self._trames = []
        self._set_phase(Phase.LIBRE if self._en_cours else Phase.ARRET)

    def valider(self, dataset: DatasetMIR, tache: str):
        trames, self._trames = self._trames, []
        if not trames or self._format is None:
            return
        conditions = {**self._conditions(), "teleoperation": self._teleop_nom, "duree_s": self._duree_s}
        fmt, fps = self._format, self._fps
        self._sauvegarde = True
        self.sauvegarde_changed.emit(True)
        self._set_phase(Phase.LIBRE if self._en_cours else Phase.ARRET)
        self._ecriture.run(lambda: dataset.ajouter_episode(fmt, fps, trames, tache, conditions),
                           lambda _: self._fin_sauvegarde(), lambda e: self._fin_sauvegarde(e))

    def _fin_sauvegarde(self, erreur: Exception | None = None):
        self._sauvegarde = False
        self.sauvegarde_changed.emit(False)
        self.datasets_changed.emit()
        if erreur is not None:
            self._dialogProvider.error("L'épisode n'a pas pu être enregistré", f"{type(erreur).__name__} : {erreur}")

    def sauvegarde_en_cours(self) -> bool:
        return self._sauvegarde

    # ------------------------------------------------------------------ épisodes enregistrés
    def supprimer_episode(self, dataset: DatasetMIR, index: int):
        try:
            dataset.supprimer_episodes([index])
        except Exception as e:
            self._dialogProvider.error("Suppression impossible", f"{type(e).__name__} : {e}")
        self.datasets_changed.emit()

    def charger_episode(self, dataset: DatasetMIR, index: int) -> dict | None:
        try:
            return dataset.charger_episode(index)
        except Exception as e:
            self._dialogProvider.error("Lecture impossible", f"{type(e).__name__} : {e}")
            return None

    def ouvrir_visualiseur(self, dataset: DatasetMIR, index: int):
        """Visualiseur officiel de LeRobot (Rerun), dans sa propre fenêtre."""
        # dossier des commandes installées : à côté de python, sauf sous Windows (Scripts\)
        commande = [str(Path(sysconfig.get_path("scripts")) / "lerobot-dataset-viz"), "--repo-id", dataset.repo_id,
                    "--root", str(dataset.dossier), "--episode-index", str(index), "--num-workers", "0"]
        try:
            subprocess.Popen(commande)
        except OSError as e:
            self._dialogProvider.error("Visualiseur LeRobot", f"Impossible de lancer {commande[0]} : {e}")

    def quit(self):
        self._arret = True
