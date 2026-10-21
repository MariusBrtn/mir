
from PySide6.QtWidgets import QPushButton
from PySide6.QtWidgets import QHBoxLayout
from PySide6.QtGui import QFontDatabase
from PySide6.QtCore import QSettings
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QDialog, 
    QCheckBox,
    QInputDialog,
)
from abc import ABC, abstractmethod
import sys
import traceback
from loguru import logger
import inspect
from enum import Enum
from pathlib import Path

class DialogResult(Enum):
    YES = 1
    NO = 2
    CANCEL = 3

class IDialogProvider(ABC):
    @abstractmethod
    def question_yes_no_cancel(self, title:str, text:str, parent:QWidget | None = None) -> DialogResult: ...

    @abstractmethod
    def question_yes_no(self, title:str, text:str, parent:QWidget | None = None) -> bool: ...

    @abstractmethod
    def information(self, title:str, text:str, parent:QWidget | None = None) -> None:  ...

    @abstractmethod
    def warning(self, title:str, text:str, parent:QWidget | None = None) -> None:  ...

    @abstractmethod
    def error(self, title:str, text:str, parent:QWidget | None = None) -> None:  ...
    
    @abstractmethod
    def open_file(self, title:str, init_directory:str, filters: str = "All files (*.*)", parent:QWidget|None=None, try_use_last_directory=True) -> str | None: ...
    
    @abstractmethod
    def save_file(self, title:str, init_directory:str, filters: str = "All files (*.*)", parent:QWidget|None=None, try_use_last_directory=True) -> str | None: ...

    @abstractmethod 
    def exception(self,
        exc: BaseException,
        title: str = "Une erreur est survenue",
        parent: QWidget | None = None) -> None : ...

    @abstractmethod
    def options(self, title:str, text:str, options:dict[str, str], parent:QWidget | None = None )->list[str]|None: ...

    def choose_item(self, title: str, label: str, items: list[str], current: str | None = None,
                    parent: QWidget | None = None) -> str | None:
        """Choisir un élément dans une liste ; None si l'utilisateur annule."""
        raise NotImplementedError

    def ask_text(self, title: str, label: str, default: str = "", parent: QWidget | None = None) -> str | None:
        """Saisir un texte ; None si l'utilisateur annule."""
        raise NotImplementedError


class QtDialogProvider(IDialogProvider):
    def __init__(self):
        self._parent = None
        self._settings = QSettings("mir", "mir_utils_dialogs")

    def setParent(self, parent:QWidget):
        self._parent = parent

    def question_yes_no_cancel(self, title:str, text:str, parent:QWidget | None = None) -> DialogResult:
        if parent is None:
            parent = self._parent
        # On construit la boîte manuellement pour imposer l'ordre Yes | No | Cancel,
        # indépendamment du style de la plateforme (Linux réordonne souvent les boutons).
        msg = QMessageBox(parent)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(QMessageBox.Icon.Question)
        btn_yes    = msg.addButton(QMessageBox.StandardButton.Yes)
        btn_no     = msg.addButton(QMessageBox.StandardButton.No)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(btn_no)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked is btn_yes:
            return DialogResult.YES
        elif clicked is btn_no:
            return DialogResult.NO
        else:
            return DialogResult.CANCEL

    def question_yes_no(self, title:str, text:str, parent:QWidget | None = None) -> bool:
        if parent is None:
            parent = self._parent
        result = QMessageBox.question(parent, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) # type: ignore
        return result == QMessageBox.StandardButton.Yes
        
    def information(self, title:str, text:str, parent:QWidget | None = None) -> None:
        if parent is None:
            parent = self._parent
        QMessageBox.information(parent, title, text)

    def error(self, title:str, text:str, parent:QWidget | None = None) -> None:
        if parent is None:
            parent = self._parent
        QMessageBox.critical(parent, title, text)

    def options(self, title:str, text:str, options:dict[str, str], parent:QWidget | None = None )->list[str]|None:
        dlg = OptionsDialog(parent)    
        return dlg.execute(caption=title, message=text, options=options)

    def warning(self, title:str, text:str, parent:QWidget | None = None) -> None:
        if parent is None:
            parent = self._parent
        QMessageBox.warning(parent, title, text)
    
    def _caller_key(self) -> str:
        caller = inspect.stack()[3].function
        return f"last_path/{caller}"

    def _get_last_path(self, default: str, try_use_last_directory) -> str:
        if not try_use_last_directory:
            return default
        key = self._caller_key()
        return str(Path(str(self._settings.value(key, default))).parent)

    def _set_last_path(self, path: str):
        key = self._caller_key()
        self._settings.setValue(key, path)

    def choose_item(self, title: str, label: str, items: list[str], current: str | None = None,
                    parent: QWidget | None = None) -> str | None:
        from mir_utils.ui.widgets import ask_item
        return ask_item(parent or self._parent, title, label, items, current)

    def ask_text(self, title: str, label: str, default: str = "", parent: QWidget | None = None) -> str | None:
        from mir_utils.ui.widgets import ask_text
        return ask_text(parent or self._parent, title, label, default)

    def open_file(self, title: str, init_directory: str,
                  filters: str = "All files (*.*)",
                  parent: QWidget | None = None,
                  try_use_last_directory=True) -> str | None:
        if parent is None:
            parent = self._parent
        start_dir = self._get_last_path(init_directory, try_use_last_directory)
        filename, _ = QFileDialog.getOpenFileName(parent, title, start_dir, filters)
        if filename:
            self._set_last_path(filename)
        return filename

    def save_file(self, title: str, init_directory: str,
                  filters: str = "All files (*.*)",
                  parent: QWidget | None = None,
                  try_use_last_directory=True) -> str | None:
        if parent is None:
            parent = self._parent
        start_dir = self._get_last_path(init_directory, try_use_last_directory)
        filename, _ = QFileDialog.getSaveFileName(parent, title, start_dir, filters)
        if filename:
            self._set_last_path(filename)
        return filename

    def exception(self, exc: BaseException, title: str = "Une erreur est survenue", parent: QWidget | None = None, traceback_str: str | None = None) -> None:
        if parent is None:
            parent = self._parent
        if traceback_str is None:
            traceback_str = traceback.format_exc()
        logger.error(f"{exc}:\n{traceback_str}")
        dlg = ExceptionDialog(
            exception=exc,
            traceback_str=traceback_str,
            title=title,
        )
        dlg.exec()                

class OptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowModality(Qt.WindowModality.WindowModal)
        self._checkboxes = {}
        self._result = None

        self._layout = QVBoxLayout(self)
        self._message_label = QLabel()
        self._layout.addWidget(self._message_label)

        # Zone des cases à cocher
        self._options_layout = QVBoxLayout()
        self._layout.addLayout(self._options_layout)

        buttons_layout = QHBoxLayout()
        btn_apply = QPushButton("Appliquer") 
        btn_cancel = QPushButton("Annuler") 
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_apply)
        buttons_layout.addWidget(btn_cancel)
               
        btn_apply.clicked.connect(self._apply)
        btn_cancel.clicked.connect(self.close)

        self._layout.addLayout(buttons_layout)

    def execute(self, caption: str, message: str, options: dict[str, str]):
        """
        caption : titre de la fenêtre
        message : texte affiché en haut
        options : dict clé => libellé
        Retourne la liste des clés sélectionnées si Appliquer est pressé,
        sinon None.
        """
        self.setWindowTitle(caption)
        self._message_label.setText(message)

        # Nettoyage si open() est appelé plusieurs fois
        for cb in self._checkboxes.values():
            cb.setParent(None)
        self._checkboxes.clear()

        # Création des cases à cocher
        for key, label in options.items():
            cb = QCheckBox(label)
            self._checkboxes[key] = cb
            self._options_layout.addWidget(cb)

        # Affichage modale
        self._result = None
        self.exec()
        return self._result
        
    def _apply(self):
        """Collecte les options cochées puis ferme la boîte."""
        selected = [
            key for key, cb in self._checkboxes.items()
            if cb.isChecked()
        ]
        self._result = selected
        self.close()


class ExceptionDialog(QMessageBox):
    """
    QMessageBox étendue pour afficher une exception et sa stack trace.

    Paramètres
    ----------
    exception : BaseException
        L'exception capturée.
    traceback_str : str, optional
        Résultat de traceback.format_exc(). Si non fourni, on tente
        de le reconstruire depuis l'exception.
    title : str
        Titre de la fenêtre.
    parent : QWidget | None
        Widget parent.
    """

    def __init__(
        self,
        exception: BaseException,
        traceback_str: str | None = None,
        title: str = "Une erreur est survenue",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)

        # ── Métadonnées de la boîte ──────────────────────────────────────
        self.setWindowTitle(title)
        self.setIcon(QMessageBox.Icon.Critical)
        self.setStandardButtons(QMessageBox.StandardButton.Ok)
        self.setDefaultButton(QMessageBox.StandardButton.Ok)

        # Message principal : type + message de l'exception
        exc_type = type(exception).__name__
        exc_msg = str(exception) or "(aucun message)"
        self.setText(f"<b>{exc_type}</b>")
        self.setInformativeText(exc_msg)

        # Stack trace fallback
        if traceback_str is None:
            traceback_str = "".join(
                traceback.format_exception(type(exception), exception, exception.__traceback__)
            )

        # ── Widget de stack trace ────────────────────────────────────────
        self._tb_widget = self._build_traceback_widget(traceback_str)

        # On injecte le widget dans le layout interne de QMessageBox.
        # Le layout de QMessageBox est un QGridLayout ; on ajoute une
        # ligne supplémentaire en bas (sous les boutons).
        grid = self.layout()
        row_count = grid.rowCount() # type: ignore
        grid.addWidget(self._tb_widget, row_count, 0, 1, grid.columnCount()) # type: ignore

        # Forcer la largeur : QMessageBox ignore souvent resize() seul,
        # on insère un spacer horizontal dans le grid pour contraindre la colonne.
        spacer = QSpacerItem(680, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        grid.addItem(spacer, row_count + 1, 0, 1, grid.columnCount()) # type: ignore
        self.setMinimumHeight(200)

    # ────────────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────────────

    def _build_traceback_widget(self, traceback_str: str) -> QWidget:
        """Construit le bloc « Stack trace » (label + QPlainTextEdit)."""
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)

        # Label
        label = QLabel("Stack trace :", container)
        label.setStyleSheet("color: #888; font-size: 11px; font-weight: bold;")
        layout.addWidget(label)

        # Zone de texte
        text_edit = QPlainTextEdit(container)
        text_edit.setReadOnly(True)
        text_edit.setPlainText(traceback_str.strip())
        text_edit.setMinimumHeight(120)
        text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Police monospace
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(9)
        text_edit.setFont(mono)

        # Style sobre, cohérent avec QMessageBox
        text_edit.setStyleSheet(
            """
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 6px;
            }
            QScrollBar:vertical {
                width: 10px;
                background: #2d2d2d;
            }
            QScrollBar::handle:vertical {
                background: #555;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )

        layout.addWidget(text_edit)

        # Scroll jusqu'en haut (le début de la trace est plus utile)
        cursor = text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        text_edit.setTextCursor(cursor)

        return container


# ════════════════════════════════════════════════════════════════════════
# Demo
# ════════════════════════════════════════════════════════════════════════

def _demo_exception() -> None:
    """Génère une exception avec une trace non triviale."""

    def level3():
        result = {}
        return result["missing_key"]  # KeyError

    def level2():
        level3()

    def level1():
        level2()

    level1()

def demo_exception():
    try:
        _demo_exception()
    except Exception as exc:
        tb = traceback.format_exc()
        dlg = ExceptionDialog(
            exception=exc,
            traceback_str=tb,
            title="Erreur inattendue",
        )
        dlg.exec()

def demo_options():
    dlg = OptionsDialog()
    result = dlg.execute("Options", "Veuillez choisir les options qui s'offrent à vous :", 
            {
            "option1": "Accueillir tous les invités", 
            "option2": "Faire une compote de nouilles", 
            "option3": "Mériter une récompense"})
    print(result)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    #demo_exception()
    demo_options()

    sys.exit(0)
    