"""
Étape Piloter → Scripts : l'élève écrit ses propres programmes Python (boucle d'asservissement, SLAM...) qui
commandent le robot avec get_observation / send_action. Chaque script tourne dans son propre programme Python :
une erreur ou une boucle sans fin ne bloque pas MIR, et ■ Arrêter l'interrompt à coup sûr.
"""
from __future__ import annotations
import re
import sys
import time
import unicodedata
from enum import Enum
from pathlib import Path
from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal
from mir_robot.mir_robot import mirRobot
from mir_robot.mpl_backend import DPI_ENV, TAILLE_ENV
from mir_robot.script import ADRESSE_ENV, CLE_ENV
from mir_robot_editor.scripts.serveur_robot import ServeurRobot
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import ViewModelBase

MODELE_SCRIPT = '''"""
{nom}

robot.get_observation()                 toutes les mesures du robot (dictionnaire)
robot.get_observation("{mesure}")   une seule mesure
robot.send_action({{"{action}": 30.0}})   envoie une consigne
robot.observations, robot.actions       les noms disponibles (voir aussi « Nom des variables » à gauche)
for t in boucle(frequence=50, duree=5):  boucle cadencée ; t = temps écoulé (s)
"""
from mir_robot.script import robot, boucle

print("Mesures disponibles :", robot.observations)

for t in boucle(frequence=20, duree=3):
    mesure = robot.get_observation("{mesure}")
    print(f"t = {{t:.2f}} s : {{mesure:.1f}}")
'''


class ScriptsVMAction(Enum):
    pass


def nom_de_fichier(nom: str) -> str:
    ascii_nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z0-9]+", "_", ascii_nom).strip("_") or "mon_script") + ".py"


class ScriptsViewModel(ViewModelBase[ScriptsVMAction]):
    busy_state_changed = Signal(bool)
    robot_changed = Signal()
    dossier_changed = Signal()
    sortie = Signal(str, bool)          # texte écrit par le script, True si c'est une erreur (stderr)
    script_termine = Signal(str)        # message de fin
    figure_recue = Signal(int, str, int, int, bytes)    # numéro, titre, largeur, hauteur, pixels RGBA

    def __init__(self, dialog_provider: IDialogProvider, other_busy=None, sim_world=None):
        super().__init__(dialog_provider)
        self._other_busy = other_busy or (lambda: False)
        self._sim_world = sim_world or (lambda: None)
        self._robot: mirRobot | None = None
        self._dossier: Path | None = None
        # figure_recue est émis depuis le fil du serveur : Qt la transmet à l'interface dans son propre fil
        self._serveur = ServeurRobot(lambda: self._robot, self.figure_recue.emit)
        self._process: QProcess | None = None
        self._debut = 0.0
        self._arret_demande = False
        self._urgence = False

    # ------------------------------------------------------------------ robot
    def set_other_busy(self, other_busy):
        """other_busy() : True quand une autre activité utilise le robot (une seule à la fois)."""
        self._other_busy = other_busy

    def connect_to_robot(self, robot: mirRobot):
        self._robot = robot
        self.robot_changed.emit()

    def disconnect_from_robot(self):
        if self.is_running():
            raise RuntimeError("Un script est en cours")
        self._robot = None
        self.robot_changed.emit()

    def has_robot(self) -> bool:
        return self._robot is not None

    def sim_world(self):
        return self._sim_world()

    def noms(self) -> tuple[list[str], list[str]]:
        """Noms des mesures et des consignes du robot."""
        if self._robot is None:
            return [], []
        return list(self._robot.get_observables()), list(self._robot.action_features)

    # ------------------------------------------------------------------ fichiers
    def set_dossier(self, dossier: Path | None):
        if dossier != self._dossier:
            self._dossier = dossier
            self.dossier_changed.emit()

    def dossier(self) -> Path | None:
        return self._dossier

    def fichiers(self) -> list[Path]:
        if self._dossier is None or not self._dossier.is_dir():
            return []
        return sorted(p for p in self._dossier.glob("*.py") if not p.name.startswith("_"))

    def nouveau(self, nom: str) -> Path | None:
        """Crée un script à partir du modèle ; None (et message) si c'est impossible."""
        if self._dossier is None:
            self._dialogProvider.information("Nouveau script", "Enregistrez d'abord le robot : ses scripts sont rangés "
                                             "dans son dossier.")
            return None
        fichier = self._dossier / nom_de_fichier(nom)
        if fichier.exists():
            self._dialogProvider.information("Nouveau script", f"Le fichier {fichier.name} existe déjà.")
            return None
        observations, actions = self.noms()
        mesure = next((n for n in observations if n.endswith(".position")), observations[0] if observations else "joint_1.position")
        action = next((n for n in actions if n.endswith(".position")), actions[0] if actions else "joint_1.position")
        self._dossier.mkdir(parents=True, exist_ok=True)
        fichier.write_text(MODELE_SCRIPT.format(nom=nom.replace('"', "'"), mesure=mesure, action=action), encoding="utf-8")
        return fichier

    # ------------------------------------------------------------------ exécution
    def is_running(self) -> bool:
        return self._process is not None

    def lancer(self, fichier: Path, taille_figures: tuple[int, int] = (640, 480), dpi_figures: float = 100):
        if self.is_running():
            return
        if self._robot is None:
            self._dialogProvider.information("Lancer le script", "Pas de robot : connectez le robot réel, ou ouvrez un "
                                             "robot qui a une structure pour utiliser le robot simulé.")
            return
        if self._other_busy():
            self._dialogProvider.information("Lancer le script", "Arrêtez d'abord le mouvement en cours "
                                             "(Essais, Téléopération ou Collecter des données).")
            return
        adresse, cle = self._serveur.demarrer()
        env = QProcessEnvironment.systemEnvironment()
        env.insert(ADRESSE_ENV, adresse)
        env.insert(CLE_ENV, cle)
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("MPLBACKEND", "module://mir_robot.mpl_backend")     # figures affichées dans MIR
        env.insert(TAILLE_ENV, f"{taille_figures[0]},{taille_figures[1]}")
        env.insert(DPI_ENV, f"{dpi_figures:g}")
        process = QProcess(self)
        process.setProcessEnvironment(env)
        process.setWorkingDirectory(str(fichier.parent))       # le script peut importer ses fichiers voisins
        process.readyReadStandardOutput.connect(lambda: self._lire(process, False))
        process.readyReadStandardError.connect(lambda: self._lire(process, True))
        process.finished.connect(lambda code, statut: self._fin(process, code, statut))
        process.errorOccurred.connect(lambda erreur: self._erreur(process, erreur))
        self._process = process
        self._arret_demande = self._urgence = False
        self._debut = time.perf_counter()
        self.busy_state_changed.emit(True)
        process.start(sys.executable, ["-u", str(fichier)])

    def arreter(self):
        if self._process is None:
            return
        self._arret_demande = True
        process = self._process
        process.terminate()
        # s'il ne s'est pas arrêté au bout d'1 s, on le tue ; minuteur lié au processus : annulé s'il est déjà supprimé
        QTimer.singleShot(1000, process, process.kill)

    def arret_urgence(self):
        """Coupe le couple des moteurs puis arrête le script."""
        self._urgence = True
        if self._robot is not None:
            try:
                self._robot.motors_emergency_stop()
            except Exception as e:
                self._dialogProvider.warning("Arrêt d'urgence", str(e))
        self.arreter()

    def _lire(self, process: QProcess, erreur: bool):
        data = process.readAllStandardError() if erreur else process.readAllStandardOutput()
        texte = bytes(data.data()).decode("utf-8", errors="replace")
        if texte:
            self.sortie.emit(texte, erreur)

    def _erreur(self, process: QProcess, erreur: QProcess.ProcessError):
        if erreur == QProcess.ProcessError.FailedToStart and process is self._process:
            self.sortie.emit(f"Impossible de lancer Python : {process.errorString()}\n", True)
            self._fin(process, -1, QProcess.ExitStatus.CrashExit)

    def _fin(self, process: QProcess, code: int, statut: QProcess.ExitStatus):
        if process is not self._process:
            return
        self._lire(process, False)
        self._lire(process, True)
        self._process = None
        self._serveur.arreter()
        duree = time.perf_counter() - self._debut
        if self._urgence:
            message = "Arrêt d'urgence : couple des moteurs coupé"
        elif self._arret_demande:
            message = f"Script arrêté au bout de {duree:.1f} s"
        elif statut == QProcess.ExitStatus.NormalExit and code == 0:
            message = f"Script terminé en {duree:.1f} s"
        else:
            message = f"Le script s'est arrêté sur une erreur (au bout de {duree:.1f} s)"
        # le script ne commande plus le robot : les moteurs s'arrêtent là où ils sont
        # (pas après un arrêt d'urgence : renvoyer une consigne réactiverait le couple)
        if not self._urgence and self._robot is not None:
            try:
                self._robot.motors_stop()
            except Exception as e:
                message += f" ; arrêt des moteurs impossible : {e}"
        process.deleteLater()
        self.script_termine.emit(message)
        self.busy_state_changed.emit(False)

    def quit(self):
        """Fermeture de l'application : le script ne doit pas survivre à MIR."""
        if self._process is not None:
            self._process.kill()
            self._process.waitForFinished(1000)
