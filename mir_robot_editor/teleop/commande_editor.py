"""Écrire ou modifier une commande en Python, depuis l'application."""
from __future__ import annotations
import re
import unicodedata
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from mir_robot.commande import verifier_fichier
from mir_utils.ui.code_editor import PythonCodeEditor

MODELE_CLAVIER = '''"""
{nom} : téléopération au clavier.

À chaque tour de boucle, MIR lit le clavier, appelle teleoperer(), puis envoie les consignes au robot.
  clavier : l'état des touches, True si elle est enfoncée : clavier["gauche"], clavier["droite"], clavier["haut"],
            clavier["bas"], clavier["espace"], clavier["a"], clavier["1"]...
  robot   : les mesures du robot piloté : robot["joint_1.position"]...
La fonction renvoie les consignes, par exemple {{"joint_1.position": 30.0}}, ou None pour ne rien envoyer.
Les touches sont celles pressées dans la fenêtre de MIR.
"""
NOM = "{nom}"
TELEOPERATEUR = "clavier"
FREQUENCE = 30      # tours de boucle par seconde (modifiable dans l'interface)
PAS = 2.0           # degrés par tour de boucle, tant que la touche est enfoncée


def teleoperer(clavier, robot):
    position = robot["joint_1.position"]
    if clavier["droite"]:
        return {{"joint_1.position": position + PAS}}
    if clavier["gauche"]:
        return {{"joint_1.position": position - PAS}}
    return None
'''

MODELE_ROBOT = '''"""
{nom} : téléopération avec le robot « {teleoperateur} » (par exemple un bras leader).

À chaque tour de boucle, MIR lit les positions du téléopérateur, appelle teleoperer(), puis envoie les consignes.
  leader : les positions du téléopérateur : leader["joint_1.position"]... (toujours le robot réel)
  robot  : les mesures du robot piloté : robot["joint_1.position"]...
La fonction renvoie les consignes, par exemple {{"joint_1.position": 30.0}}, ou None pour ne rien envoyer.
"""
NOM = "{nom}"
TELEOPERATEUR = "{teleoperateur}"
FREQUENCE = 30      # tours de boucle par seconde (modifiable dans l'interface)


def teleoperer(leader, robot):
    # le robot piloté recopie les positions du leader
    return leader
'''


def nom_de_fichier(nom: str) -> str:
    ascii_nom = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    return (re.sub(r"[^a-z0-9]+", "_", ascii_nom).strip("_") or "ma_commande") + ".py"


class CommandeEditorDialog(QDialog):
    """Éditeur d'un fichier de commandes. saved est émis après chaque enregistrement."""
    saved = Signal(Path)

    def __init__(self, parent, fichier: Path, contenu_initial: str | None = None, modifiable: bool = True):
        super().__init__(parent)
        self._fichier = fichier
        self.setWindowTitle(f"Commande : {fichier.name}")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        chemin = QLabel(str(fichier))
        chemin.setStyleSheet("color: palette(placeholder-text);")
        chemin.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(chemin)
        if not modifiable:
            info = QLabel("Commande fournie avec MIR : lecture seule. Pour la modifier, créez une nouvelle commande "
                          "et copiez-y ce code.")
            info.setWordWrap(True)
            layout.addWidget(info)
        self.editor = PythonCodeEditor()
        self.editor.setPlainText(contenu_initial if contenu_initial is not None else fichier.read_text(encoding="utf-8"))
        self.editor.setReadOnly(not modifiable)
        self.editor.textChanged.connect(self.editor.clearErrorLine)
        layout.addWidget(self.editor, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        btn_verifier = QPushButton("Vérifier")
        btn_verifier.clicked.connect(self.verifier)
        buttons.addWidget(btn_verifier)
        buttons.addStretch(1)
        self.btn_enregistrer = QPushButton("Enregistrer")
        self.btn_enregistrer.setEnabled(modifiable)
        self.btn_enregistrer.clicked.connect(self.enregistrer)
        buttons.addWidget(self.btn_enregistrer)
        btn_fermer = QPushButton("Fermer")
        btn_fermer.clicked.connect(self.close)
        buttons.addWidget(btn_fermer)
        layout.addLayout(buttons)

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
        noms, erreur, ligne = verifier_fichier(fichier or self._fichier)
        if erreur is None:
            self.editor.clearErrorLine()
            self.status.setStyleSheet("color: #2e7d32;")
            self.status.setText(f"OK : {', '.join(noms)}")
            return True
        if ligne is not None:
            self.editor.setErrorLine(ligne)
        self.status.setStyleSheet("color: #d32f2f;")
        self.status.setText(erreur)
        return False
