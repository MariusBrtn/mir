from typing import Any, Generic, TypeVar
from abc import abstractmethod
from PySide6.QtWidgets import (QWidget, QMainWindow, QDialog, QLabel, QHBoxLayout, QVBoxLayout, QLineEdit, QToolButton,
                               QPushButton, QFrame, QScrollArea)
from PySide6.QtCore import QSettings, Qt, QSize, Signal
from PySide6.QtGui import QKeyEvent, QIcon, QPixmap, QPainter, QColor, QFont, QFontDatabase
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

    # habillage des fenêtres qui ne construisent pas elles-mêmes leur en-tête :
    # {nom de la classe: (phrase, icône, titre ou "" pour le titre de la fenêtre)}
    _frames: dict[str, tuple[str, str, str]] = {}

    @classmethod
    def register_frame(cls, class_name: str, subtitle: str, icon: str, title: str = ""):
        """À la première ouverture, une fenêtre de cette classe reçoit un en-tête (titre, phrase, icône) ; son
        contenu passe dessous, sans changement."""
        cls._frames[class_name] = (subtitle, icon, title)

    def showEvent(self, event):
        if getattr(self, "_mir_frame", None) is None and type(self).__name__ in DialogBase._frames:
            subtitle, icon, title = DialogBase._frames[type(self).__name__]
            frame_existing(self, DialogHeader(title or self.windowTitle(), subtitle, icon=icon))
        super().showEvent(event)
        self._fit_to_content()

    def _fit_to_content(self):
        """Une fenêtre mise en place par dialog_frame, plus petite que son contenu (taille mémorisée d'une ancienne
        version, par exemple), s'agrandit à l'ouverture, sans dépasser l'écran."""
        frame = getattr(self, "_mir_frame", None)
        if frame is None:
            return
        header, contenu, footer = frame
        largeur = self.width()
        corps = contenu.heightForWidth(largeur) if contenu.hasHeightForWidth() else -1
        if corps < 0:
            corps = contenu.sizeHint().height()
        besoin = header.sizeHint().height() + corps + (footer.sizeHint().height() if footer is not None else 0)
        screen = self.screen()
        if screen is not None:
            besoin = min(besoin, screen.availableGeometry().height() - 60)
        if self.height() < besoin:
            self.resize(largeur, besoin)

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

# ---------------------------------------------------------------------- fenêtres : en-tête, sections, pied

def tinted_icon(icon_name: str, color: str, size: int) -> QPixmap:
    """L'icône, entièrement de la couleur donnée (les icônes de MIR sont d'une seule couleur)."""
    pixmap = IconFinder.find_icon(icon_name).pixmap(size, size)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return pixmap


def mono_font(size: int | None = None) -> QFont:
    """IBM Plex Mono : mesures, angles, ID, noms de modules et de nœuds, journaux."""
    family = theme.first_family(theme.MONO_FAMILIES)
    font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if size:
        font.setPixelSize(size)
    return font


def overline(text: str) -> QLabel:
    """Petit titre en capitales espacées, pour les zones secondaires (Entrée, Sortie, Journal...)."""
    label = QLabel(text.upper())
    label.setObjectName("Overline")
    font = label.font()
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    label.setFont(font)
    return label


class DialogHeader(QWidget):
    """En-tête d'une fenêtre : tuile d'icône, titre, phrase d'explication (et, au-dessus du titre, une famille)."""

    def __init__(self, title: str, subtitle: str = "", icon: str = "", tile_color: str = theme.INK,
                 icon_color: str = theme.SAND, kind: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DialogHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(14)
        self._tile = QLabel()
        self._tile.setFixedSize(40, 40)
        self._tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._tile)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self._kind = QLabel()
        self._kind.setObjectName("DialogKind")
        texts.addWidget(self._kind)
        self._title = QLabel()
        self._title.setObjectName("DialogTitle")
        texts.addWidget(self._title)
        self._subtitle = QLabel()
        self._subtitle.setObjectName("DialogSubtitle")
        self._subtitle.setWordWrap(True)
        texts.addWidget(self._subtitle)
        layout.addLayout(texts, 1)
        self._right = QHBoxLayout()
        self._right.setSpacing(8)
        layout.addLayout(self._right)
        self.set_content(title, subtitle, icon, tile_color, icon_color, kind)

    def set_content(self, title: str, subtitle: str = "", icon: str = "", tile_color: str = theme.INK,
                    icon_color: str = theme.SAND, kind: str = ""):
        self._title.setText(title)
        self._subtitle.setText(subtitle)
        self._subtitle.setVisible(bool(subtitle))
        self._kind.setText(kind.upper())
        self._kind.setStyleSheet(f"color: {tile_color};")
        self._kind.setVisible(bool(kind))
        self._tile.setVisible(bool(icon))
        if icon:
            self._tile.setStyleSheet(f"background: {tile_color}; border-radius: 10px;")
            self._tile.setPixmap(tinted_icon(icon, icon_color, 22))

    def set_tile_pixmap(self, pixmap: QPixmap, tile_color: str):
        """Tuile d'une icône déjà dessinée (par exemple l'icône d'un nœud MIR Flow)."""
        self._tile.setStyleSheet(f"background: {tile_color}; border-radius: 10px;")
        self._tile.setPixmap(pixmap)
        self._tile.setVisible(True)

    def title_label(self) -> QLabel:
        return self._title

    def add_right(self, widget: QWidget):
        """Un élément à droite de l'en-tête (état, bouton...)."""
        self._right.addWidget(widget)


class DialogFooter(QWidget):
    """Pied d'une fenêtre : les boutons à droite, sur fond panneau."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DialogFooter")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(22, 12, 22, 12)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)

    def add_button(self, text: str, callback: Callable | None = None, primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setAutoDefault(False)
        if primary:
            button.setObjectName("Primary")
        if callback is not None:
            button.clicked.connect(callback)
        self._layout.addWidget(button)
        return button

    def add_left(self, widget: QWidget):
        self._layout.insertWidget(self._layout.count() - 1, widget)


class Section(QFrame):
    """Carte d'une fenêtre, avec un titre (et un numéro en sable foncé, comme les étapes de l'accueil).
    Le contenu va dans section.body (QVBoxLayout)."""

    def __init__(self, title: str, number: int | None = None, hint: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Section")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(10)
        heading = QLabel()
        heading.setObjectName("SectionHeading")
        parts = []
        if number is not None:
            parts.append(f"<span style='font-family: \"IBM Plex Mono\"; color: {theme.SAND_DARK};'>{number}</span>&nbsp;&nbsp;")
        parts.append(title)
        if hint:
            parts.append(f"&nbsp;&nbsp;<span style='font-size: 12px; font-weight: 400; color: {theme.TEXT_MUTED};'>{hint}</span>")
        heading.setText("".join(parts))
        layout.addWidget(heading)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        layout.addLayout(self.body)


class MessageLabel(QLabel):
    """Message d'état sur un bandeau : « ✓ … » en vert, « ✗ … » en rouge, le reste en couleur de texte."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Message")
        self.setWordWrap(True)

    def set_message(self, text: str):
        etat = "ok" if text.startswith("✓") else "erreur" if text.startswith("✗") else ""
        self.setProperty("etat", etat)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText(text)
        self.setVisible(bool(text))


def dialog_frame(dialog: QDialog, header: DialogHeader, footer: DialogFooter | None = None,
                 margins: tuple[int, int, int, int] = (22, 16, 22, 16), scroll: bool = True) -> QVBoxLayout:
    """Met en place une fenêtre : en-tête, contenu, pied. Retourne le layout du contenu.
    scroll : le contenu défile quand la fenêtre est trop petite. Sans cela, Qt l'écrase et les lignes se
    chevauchent (il calcule mal la hauteur minimale d'une fenêtre qui contient du texte sur plusieurs lignes).
    False pour un contenu qui gère lui-même sa place (colonnes redimensionnables, zones qui défilent)."""
    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    root.addWidget(header)
    contenu = QWidget()
    contenu.setObjectName("DialogBody")
    body = QVBoxLayout(contenu)
    body.setContentsMargins(*margins)
    body.setSpacing(12)
    if scroll:
        zone = QScrollArea()
        zone.setObjectName("DialogBody")
        zone.setWidgetResizable(True)
        zone.setFrameShape(QFrame.Shape.NoFrame)
        zone.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        zone.setWidget(contenu)
        root.addWidget(zone, 1)
    else:
        root.addWidget(contenu, 1)
    if footer is not None:
        root.addWidget(footer)
    dialog._mir_frame = (header, contenu, footer)    # pour DialogBase.showEvent : agrandir une fenêtre trop petite
    return body


class ChoiceCard(QFrame):
    """Un choix parmi plusieurs (comme un bouton radio), présenté en carte : titre et description.
    Les cartes d'un même choix se regroupent avec ChoiceCard.group()."""
    toggled = Signal(bool)

    def __init__(self, title: str, description: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ChoiceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._checked = False
        self._group: list[ChoiceCard] = [self]
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        self._indicator = QLabel()
        self._indicator.setObjectName("ChoiceIndicator")
        self._indicator.setFixedSize(16, 16)
        layout.addWidget(self._indicator, 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self._title = QLabel(title)
        self._title.setObjectName("ChoiceTitle")
        texts.addWidget(self._title)
        self._description = QLabel(description)
        self._description.setObjectName("ChoiceDescription")
        self._description.setVisible(bool(description))   # sur une ligne : Qt calcule mal la hauteur d'un texte replié ici
        texts.addWidget(self._description)
        layout.addLayout(texts, 1)
        self._sync()

    @staticmethod
    def group(*cards: "ChoiceCard"):
        for card in cards:
            card._group = list(cards)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool):
        if checked:
            for other in self._group:
                if other is not self and other._checked:
                    other._checked = False
                    other._sync()
                    other.toggled.emit(False)
        if checked != self._checked:
            self._checked = checked
            self._sync()
            self.toggled.emit(checked)

    def _sync(self):
        self.setProperty("selected", "true" if self._checked else "false")
        for w in (self, self._indicator):
            w.style().unpolish(w)
            w.style().polish(w)

    def mouseReleaseEvent(self, event):
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(True)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(True)
        else:
            super().keyPressEvent(event)


def frame_existing(dialog: QDialog, header: DialogHeader, footer: DialogFooter | None = None, scroll: bool = True):
    """Ajoute un en-tête (et un pied) à une fenêtre déjà construite : son layout et ses widgets passent, tels quels,
    dans le contenu (Qt reprend un layout installé sur un autre widget, avec ses widgets)."""
    ancien = dialog.layout()
    if ancien is None:
        return
    contenu = QWidget()
    contenu.setObjectName("DialogBody")
    contenu.setLayout(ancien)
    root = QVBoxLayout(dialog)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)
    root.addWidget(header)
    if scroll:
        zone = QScrollArea()
        zone.setObjectName("DialogBody")
        zone.setWidgetResizable(True)
        zone.setFrameShape(QFrame.Shape.NoFrame)
        zone.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        zone.setWidget(contenu)
        root.addWidget(zone, 1)
    else:
        root.addWidget(contenu, 1)
    if footer is not None:
        root.addWidget(footer)
    dialog._mir_frame = (header, contenu, footer)


class AskDialog(QDialog):
    """Petite fenêtre au style Atelier : choisir dans une liste, ou saisir un texte (remplace QInputDialog)."""

    def __init__(self, parent: QWidget | None, title: str, label: str, subtitle: str = "", icon: str = "",
                 items: list[str] | None = None, current: str | None = None, default: str = "",
                 accept_text: str = "Valider"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        footer = DialogFooter()
        footer.add_button("Annuler", self.reject)
        self._ok = footer.add_button(accept_text, self.accept, primary=True)
        self._ok.setDefault(True)
        body = dialog_frame(self, DialogHeader(title, subtitle, icon=icon), footer, scroll=False)
        texte = QLabel(label)
        texte.setWordWrap(True)
        body.addWidget(texte)
        if items is not None:
            from PySide6.QtWidgets import QComboBox
            self._field = QComboBox()
            self._field.addItems(items)
            if current in items:
                self._field.setCurrentText(current)
            self._ok.setEnabled(bool(items))
        else:
            self._field = QLineEdit(default)
            self._field.selectAll()
            self._field.textChanged.connect(lambda t: self._ok.setEnabled(bool(t.strip())))
            self._ok.setEnabled(bool(default.strip()))
        body.addWidget(self._field)
        body.addStretch(1)
        self._field.setFocus()

    def value(self) -> str:
        return self._field.currentText() if not isinstance(self._field, QLineEdit) else self._field.text()


def ask_item(parent: QWidget | None, title: str, label: str, items: list[str], current: str | None = None,
             subtitle: str = "", icon: str = "", accept_text: str = "Valider") -> str | None:
    """Choisir un élément dans une liste ; None si l'utilisateur annule."""
    dialog = AskDialog(parent, title, label, subtitle, icon, items=items, current=current, accept_text=accept_text)
    return dialog.value() if dialog.exec() and dialog.value() else None


def ask_text(parent: QWidget | None, title: str, label: str, default: str = "", subtitle: str = "", icon: str = "",
             accept_text: str = "Valider") -> str | None:
    """Saisir un texte ; None si l'utilisateur annule."""
    dialog = AskDialog(parent, title, label, subtitle, icon, default=default, accept_text=accept_text)
    return dialog.value() if dialog.exec() else None
