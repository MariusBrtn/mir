from typing import Any, Generic, TypeVar
from abc import abstractmethod
from PySide6.QtWidgets import (QWidget, QMainWindow, QDialog, QLabel, QHBoxLayout, QLineEdit, QToolButton)
from PySide6.QtCore import QSettings, Qt, QSize
from PySide6.QtGui import QKeyEvent, QIcon
from pathlib import Path
from typing import Callable
from dataclasses import dataclass
from mir_utils.ui import theme

@dataclass
class stylesheets():
    labels_style = f"font-size: 10pt; border: 1px solid {theme.BORDER}; border-radius: 4px; background-color: {theme.PANEL}; font-family: 'IBM Plex Mono', monospace;"
    edit_style = f"font-size: 12pt; border: 1px solid {theme.BORDER_STRONG}; border-radius: 4px; background-color: {theme.SURFACE};"
    header_style = "font-size: 10pt; margin-top: 20px"
    css_button = "font-size=14"
    css_text_enabled = f"font-size: 10pt; border: 1px solid {theme.BORDER_STRONG}; border-radius: 4px; background-color: {theme.SURFACE};"
    css_text_disabled = f"font-size: 10pt; border: 1px solid {theme.BORDER}; border-radius: 4px; background-color: {theme.PANEL};"

class StateSavedView:
    """Mixin pour sauvegarder/restaurer la géométrie d'une fenêtre Qt."""
    
    def _init_state(self, name: str, default_width: int = 400, default_height: int = 300):
        self.name = name
        self.default_width = default_width
        self.default_height = default_height
        self.settings = QSettings("mir", "mir_utils_widgets")
        self.restore_state()

    def restore_state(self):
        geometry = self.settings.value(f"{self.name}/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry) # type: ignore
        else:
            self.resize(self.default_width, self.default_height) # type: ignore
        self._fit_to_screen()

    def _fit_to_screen(self):
        """Ramène la fenêtre dans l'écran (une géométrie mémorisée sur un écran plus grand rendrait ses bords inaccessibles)."""
        screen = self.screen() # type: ignore
        if screen is None:
            return
        available = screen.availableGeometry()
        # le cadre (barre de titre, bordures) s'ajoute à la taille de la fenêtre
        frame_w = self.frameGeometry().width() - self.width() # type: ignore
        frame_h = self.frameGeometry().height() - self.height() # type: ignore
        width = min(self.width(), available.width() - frame_w) # type: ignore
        height = min(self.height(), available.height() - frame_h) # type: ignore
        self.resize(width, height) # type: ignore
        # move() place le coin du cadre
        x = min(max(self.frameGeometry().x(), available.left()), available.left() + available.width() - width - frame_w) # type: ignore
        y = min(max(self.frameGeometry().y(), available.top()), available.top() + available.height() - height - frame_h) # type: ignore
        self.move(x, y) # type: ignore

    def closeEvent(self, event):
        self._save_state()
        super().closeEvent(event)  # type: ignore # MRO Python gère correctement la chaîne

    def done(self, result):
        """Appelé par accept(), reject() et la croix — spécifique à QDialog."""
        self._save_state()
        super().done(result)  # type: ignore # Ne sera résolu que si la classe hérite de QDialog

    def _save_state(self):
        self.settings.setValue(f"{self.name}/geometry", self.saveGeometry()) # type: ignore

    def save_custom_state(self, state_name: str, state:Any):
        self.settings.setValue(f"{self.name}/{state_name}", state)

    def restore_custom_state(self, state_name: str) -> Any:
        return self.settings.value(f"{self.name}/{state_name}")

class WindowBase(StateSavedView, QWidget):
    def __init__(self, parent, default_width=400, default_height=300, name:str|None=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        if name is None:
            name = self.__class__.__name__
        self._init_state(name, default_width, default_height)

class MainWindowBase(StateSavedView, QMainWindow):
    def __init__(self, parent, default_width=400, default_height=300, name:str|None=None, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        if name is None:
            name = self.__class__.__name__
        self._init_state(name, default_width, default_height)

class DialogBase(StateSavedView, QDialog):
    def __init__(self, parent, default_width=400, default_height=300, disable_esc:bool=False, name:str|None=None, *args, **kwargs):
        QDialog.__init__(self, parent, *args, **kwargs)
        self._disable_esc = disable_esc
        self.setSizeGripEnabled(True)   # poignée de redimensionnement en bas à droite
        if name is None:
            name = self.__class__.__name__
        self._init_state(name, default_width, default_height)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._disable_esc and event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

class ToolButton(QToolButton):
    def __init__(self, icon:str, callback:Callable, enabled:bool=True, tip:str="", border:bool=False, size:int=24):
        super().__init__()
        self.setIcon(IconFinder.find_icon(icon))
        self.setIconSize(QSize(size, size))
        self.setToolTip(tip)
        self.setEnabled(enabled)
        if not border:
            self.setStyleSheet("border: none")
        self.clicked.connect(callback)     

class IconFinder():
        _icons_directory = Path(__file__).parent / "icons"
    
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
        
        @staticmethod
        def find_icon(icon_name:str):
            if Path(icon_name).exists():
                return QIcon(icon_name)
            filepath =  IconFinder._icons_directory / f"{icon_name}.svg"
            if filepath.exists():
                return QIcon(str(filepath))
            filepath =  IconFinder._icons_directory / f"{icon_name}.png"
            if filepath.exists():
                return QIcon(str(filepath))
            return QIcon() 


T_Number = TypeVar("T_Number", float, int)

class NumberLineEdit(QWidget, Generic[T_Number]):
    def __init__(self, value:T_Number, width:int|None=None, parent: QWidget|None=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        self.tb = QLineEdit(text=str(value))
        self.tb.setAlignment(Qt.AlignmentFlag.AlignRight)
        if width:
            self.tb.setFixedWidth(width)
        self.bad_value = QLabel(" ")
        self.bad_value.setFixedWidth(8)
        self.bad_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.bad_value)
        layout.addWidget(self.tb)
        self.tb.editingFinished.connect(self.on_lost_focus)

    def _check(self):
        try:
            self.bad_value.setText(" ")            
            return self._convert(self.tb.text())
        except (ValueError, TypeError):
            self.bad_value.setText("❗")            
            return None

    def on_lost_focus(self):
        self._check()

    def __call__(self):
        return self._check()

    @abstractmethod
    def _convert(self, text:str) -> T_Number :
        raise NotImplementedError()
                
class DoubleLineEdit(NumberLineEdit[float]):
    def _convert(self, text:str) -> float:
        return float(text)

class IntLineEdit(NumberLineEdit[int]):
    def _convert(self, text:str) -> int:
        return int(text)