"""Écrire ou modifier une téléopération en Python, depuis l'application."""
from __future__ import annotations
import re
import unicodedata
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from mir_robot.teleop.loading import check_teleop_file
from mir_utils.ui.code_editor import PythonCodeEditor
from mir_utils.ui.widgets import DialogFooter, DialogHeader, MessageLabel, dialog_frame, mono_font

MODELE_CLAVIER = '''"""
{nom} : téléopération au clavier.

À chaque tour de boucle, MIR appelle get_action(observation) puis envoie au robot ce qu'elle renvoie.
  self.read()  : l'état des touches, True si elle est enfoncée : keys["left"], keys["right"], keys["up"],
                 keys["down"], keys["space"], keys["a"], keys["1"]...
  observation  : les mesures du robot, ex. observation["joint_1.position"]
  self.fps     : tours de boucle par seconde
get_action renvoie l'action envoyée au robot, par exemple {{"joint_1.position": 30.0}}, ou None pour ne rien envoyer.
Les touches sont celles pressées dans la fenêtre de MIR. Échap arrête la téléopération.
"""
from mir_robot.teleop import KeyboardTeleoperator

SPEED = 30.0        # °/s tant que la flèche est enfoncée


class {classe}(KeyboardTeleoperator):
    name = "{nom}"
    description = "← → : tourner l'articulation 1"

    def connect(self):
        super().connect()
        self.target = None

    def get_action(self, observation):
        keys = self.read()
        if self.target is None:
            self.target = observation["joint_1.position"]     # on part de la position mesurée
        if keys["right"]:
            self.target += SPEED / self.fps
        if keys["left"]:
            self.target -= SPEED / self.fps
        return {{"joint_1.position": self.target}}
'''

MODELE_BRAS_LEADER = '''"""
{nom} : téléopération avec le bras leader.

À chaque tour de boucle, MIR appelle get_action(observation) puis envoie au robot ce qu'elle renvoie.
  self.read()  : les positions du bras leader, ex. {{"joint_1.position": 12.3, ...}}
  observation  : les mesures du robot, ex. observation["joint_1.position"]
get_action renvoie l'action envoyée au robot, par exemple {{"joint_1.position": 30.0}}, ou None pour ne rien envoyer.
"""
from mir_robot.teleop import LeaderArmTeleoperator


class {classe}(LeaderArmTeleoperator):
    name = "{nom}"
    description = "Le robot recopie le bras leader"

    def get_action(self, observation):
        leader = self.read()
        action = dict(leader)
        # exemples de variantes :
        #   action["joint_1.position"] = -leader["joint_1.position"]       # sens inversé
        #   action["joint_5.position"] = 0.5 * leader["joint_5.position"]  # pince à mi-course
        return action
'''


def nom_de_classe(nom: str) -> str:
    """Nom de classe Python à partir du nom affiché, ex. « Ma téléop » -> MaTeleop."""
    ascii_nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    classe = "".join(mot.capitalize() for mot in re.split(r"[^A-Za-z0-9]+", ascii_nom) if mot)
    return classe if classe and not classe[0].isdigit() else f"Teleop{classe}"


def nom_de_fichier(nom: str) -> str:
    ascii_nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z0-9]+", "_", ascii_nom).strip("_") or "ma_teleop") + ".py"


class CommandeEditorDialog(QDialog):
    """Éditeur d'un fichier de téléopération. saved est émis après chaque enregistrement."""
    saved = Signal(Path)

    def __init__(self, parent, fichier: Path, contenu_initial: str | None = None, modifiable: bool = True):
        super().__init__(parent)
        self._fichier = fichier
        self.setWindowTitle(f"Téléopération : {fichier.name}")
        self.resize(900, 700)
        footer = DialogFooter()
        btn_verifier = QPushButton("Vérifier")
        btn_verifier.setAutoDefault(False)
        btn_verifier.clicked.connect(self.verifier)
        footer.add_left(btn_verifier)
        footer.add_button("Fermer", self.close)
        self.btn_enregistrer = footer.add_button("Enregistrer", self.enregistrer, primary=True)
        self.btn_enregistrer.setEnabled(modifiable)
        layout = dialog_frame(self, DialogHeader(fichier.stem, str(fichier), icon="actions", kind="Téléopération"),
                              footer, scroll=False)
        self.findChild(DialogHeader).title_label().setFont(mono_font(18))
        self.findChild(DialogHeader).findChild(QLabel, "DialogSubtitle").setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        if not modifiable:
            info = MessageLabel()
            info.set_message("Téléopération fournie avec MIR : lecture seule. Pour la modifier, créez une nouvelle "
                             "téléopération et copiez-y ce code.")
            layout.addWidget(info)
        self.editor = PythonCodeEditor()
        self.editor.setPlainText(contenu_initial if contenu_initial is not None else fichier.read_text(encoding="utf-8"))
        self.editor.setReadOnly(not modifiable)
        self.editor.textChanged.connect(self.editor.clearErrorLine)
        layout.addWidget(self.editor, 1)
        self.status = MessageLabel()
        self.status.hide()
        layout.addWidget(self.status)

    def enregistrer(self) -> bool:
        self._fichier.parent.mkdir(parents=True, exist_ok=True)
        self._fichier.write_text(self.editor.toPlainText(), encoding="utf-8")
        ok = self._afficher_verification()
        self.saved.emit(self._fichier)
        return ok

    def verifier(self) -> bool:
        """Vérifie le texte en cours (même non enregistré) dans un fichier temporaire voisin."""
        if not self.editor.isReadOnly() and self.editor.document().isModified():
            brouillon = self._fichier.with_name(f"_verification_{self._fichier.name}")
            brouillon.write_text(self.editor.toPlainText(), encoding="utf-8")
            try:
                return self._afficher_verification(brouillon)
            finally:
                brouillon.unlink(missing_ok=True)
        return self._afficher_verification()

    def _afficher_verification(self, fichier: Path | None = None) -> bool:
        noms, erreur, ligne = check_teleop_file(fichier or self._fichier)
        if erreur is None:
            self.editor.clearErrorLine()
            self.status.set_message(f"✓ OK : {', '.join(noms)}")
            return True
        if ligne is not None:
            self.editor.setErrorLine(ligne)
        self.status.set_message(f"✗ {erreur}")
        return False
