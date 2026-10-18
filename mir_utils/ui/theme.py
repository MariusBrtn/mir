"""Thème « Atelier » : couleurs, palette Qt et feuille de style de l'interface.

Tout le style passe par ce fichier : les vues n'écrivent pas de couleur en dur, elles utilisent ces constantes ou
la palette Qt (palette(mid), palette(highlight)...). Les teintes reprennent les matières du robot (PLA noir et
sable, mats) et le bleu ardoise de la marque.
"""
from pathlib import Path
from string import Template
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

# matières du robot
INK = "#141417"            # PLA noir
SAND = "#DEC7A3"           # PLA sable
SAND_DARK = "#8A7350"      # sable foncé : accent lisible sur fond clair (numéros, liens)
SLATE = "#5A6B85"          # bleu ardoise de la marque

# fonds et bordures
WINDOW = "#FAF8F4"
SURFACE = "#FFFDF9"        # cartes, champs de saisie
PANEL = "#F2EDE4"          # colonne des étapes, encadrés, lignes alternées
BORDER = "#E2DACD"
BORDER_STRONG = "#CFC4B2"

# textes
TEXT = "#1C1C1F"
TEXT_MUTED = "#6B655C"
TEXT_DISABLED = "#A39B8F"

# états (jamais décoratifs)
OK = "#3F7A4A"
WARNING = "#B5651D"
ERROR = "#A63D32"

# mode du robot : on ne doit jamais confondre robot réel et robot simulé
REAL = "#B4472F"
SIM = SLATE
IDLE = TEXT_DISABLED
RUNNING = OK


def rgba(color: str, alpha: float = 1.0) -> list[float]:
    """Couleur hexadécimale -> [r, g, b, a] entre 0 et 1 (format MuJoCo)."""
    c = QColor(color)
    return [c.redF(), c.greenF(), c.blueF(), alpha]


# teintes de la vue 3D (MuJoCo), un peu plus claires que l'interface : l'éclairage les assombrit
MARKER_FREE_RGBA = rgba("#6F86A8", 0.95)        # connecteur libre : ardoise
MARKER_COMPATIBLE_RGBA = rgba("#4FA36A")        # connecteur où brancher : vert
MARKER_DIMMED_RGBA = [0.5, 0.5, 0.5, 0.25]      # connecteur incompatible : estompé
SELECTION_RGBA = rgba("#6F86A8")                # pièce sélectionnée ou mise en avant

# IBM Plex (licence libre OFL) est fournie avec le code : rien à installer sur les postes
FONTS_DIR = Path(__file__).parent / "fonts"
FONT_FAMILIES = ["IBM Plex Sans", "Inter", ".AppleSystemUIFont", "Segoe UI"]
# classes à qui macOS (et parfois Windows) donne leur propre police système : on leur impose la famille du thème
_FONT_CLASSES = ["QPushButton", "QToolButton", "QCheckBox", "QRadioButton", "QComboBox", "QLineEdit", "QAbstractSpinBox",
                 "QLabel", "QGroupBox", "QTabBar", "QMenu", "QMenuBar", "QHeaderView", "QAbstractItemView", "QListView",
                 "QTreeView", "QTableView", "QMessageBox", "QTipLabel", "QStatusBar", "QDockWidget", "QTextEdit",
                 "QPlainTextEdit", "QSlider", "QProgressBar"]
MONO_FAMILIES = ["IBM Plex Mono", "SF Mono", "Menlo", "Consolas"]

_QSS = Template("""
QToolTip { background: $INK; color: $WINDOW; border: none; padding: 5px 8px; border-radius: 4px; }

QPushButton {
    background: $SURFACE; color: $TEXT; border: 1px solid $BORDER_STRONG; border-radius: 8px;
    padding: 6px 14px; min-height: 20px;
}
QPushButton:hover { background: $PANEL; }
QPushButton:pressed { background: $BORDER; }
QPushButton:checked { background: $INK; color: $SAND; border-color: $INK; }
QPushButton:default { background: $INK; color: $WINDOW; border-color: $INK; }
QPushButton:disabled { color: $TEXT_DISABLED; border-color: $BORDER; background: $WINDOW; }

QToolButton { border: 1px solid transparent; border-radius: 6px; padding: 3px; }
QToolButton:hover { background: $PANEL; border-color: $BORDER; }
QToolButton:checked { background: $SAND; border-color: $SAND; }

QGroupBox { border: 1px solid $BORDER; border-radius: 9px; margin-top: 14px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: $TEXT; font-weight: 600; }

QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: $TEXT_MUTED; padding: 8px 16px; border: none;
               border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: $TEXT; }
QTabBar::tab:selected { color: $TEXT; border-bottom: 2px solid $INK; }
QTabBar::tab:disabled { color: $TEXT_DISABLED; }

QStatusBar { background: $PANEL; color: $TEXT_MUTED; border-top: 1px solid $BORDER; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: $TEXT_MUTED; padding-left: 10px; }

QMenu { background: $SURFACE; border: 1px solid $BORDER; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 20px; border-radius: 5px; }
QMenu::item:selected { background: $PANEL; color: $TEXT; }
QMenu::separator { height: 1px; background: $BORDER; margin: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: $BORDER_STRONG; border-radius: 3px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: $TEXT_DISABLED; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* fenêtre principale */
#Header { background: $WINDOW; border-bottom: 1px solid $BORDER; }
#Steps { background: $PANEL; border: none; border-right: 1px solid $BORDER; font-size: 15px; padding: 12px 10px; outline: 0; }
#Steps::item { padding: 10px 10px; border-radius: 8px; margin: 1px 0; color: $TEXT; }
#Steps::item:hover { background: $BORDER; }
#Steps::item:selected { background: $INK; color: $WINDOW; }
#Steps::item:disabled { color: $TEXT_DISABLED; }
#ActionCard { background: $SURFACE; border: 1px solid $BORDER; border-radius: 9px; }
#ActionCard:hover { background: $PANEL; border-color: $BORDER_STRONG; }
#ActionCard:focus { border-color: $INK; }
#ActionCard:disabled { background: transparent; border-style: dashed; }
#CardIcon { background: $PANEL; border-radius: 9px; }
#CardTitle { font-size: 15px; font-weight: 600; color: $TEXT; }
#CardDescription { color: $TEXT_MUTED; }
#CardTitle:disabled, #CardDescription:disabled { color: $TEXT_DISABLED; }
#CardChevron { font-size: 24px; color: $TEXT_DISABLED; padding-bottom: 3px; }
#SectionTitle { font-size: 16px; font-weight: 600; margin-top: 10px; }
#Muted { color: $TEXT_MUTED; }
#Etape { background: transparent; border: none; border-bottom: 3px solid transparent; border-radius: 0;
         padding: 8px 8px 6px 8px; font-size: 15px; color: $TEXT_MUTED; }
#Etape:hover { color: $TEXT; border-bottom-color: $BORDER_STRONG; background: transparent; }
#Etape:checked { color: $TEXT; font-weight: 600; border-bottom-color: $INK; background: transparent; }
#Etape:disabled { color: $TEXT_DISABLED; }
#SeparateurEntete { color: $BORDER; }
#RobotMenu { font-size: 15px; font-weight: 600; border: 1px solid transparent; border-radius: 8px; padding: 5px 8px; }
#RobotMenu:hover { background: $PANEL; border-color: $BORDER; }
#RobotMenu::menu-indicator { image: none; width: 0; }
#Urgence { background: $REAL; color: white; font-weight: 700; border: 1px solid $REAL; border-radius: 8px; padding: 7px 16px; }
#Urgence:hover { background: #8F3522; }
#Urgence:disabled { background: $WINDOW; color: $TEXT_DISABLED; border: 1px solid $BORDER; }
#ModaliteEnCours, #EtapeEnCours { color: $RUNNING; font-size: 13px; font-weight: 600; }

/* modalités de Piloter : une carte par façon de commander le robot */
#Modalites { background: $WINDOW; border-bottom: 1px solid $BORDER; }
#Modalite { background: $SURFACE; border: 1px solid $BORDER; border-radius: 10px; }
#Modalite:hover { background: $PANEL; border-color: $BORDER_STRONG; }
#Modalite[selected="true"] { background: $INK; border-color: $INK; }
#Modalite[selected="true"] #ModaliteTitre { color: $WINDOW; }
#Modalite[selected="true"] #ModaliteDescription { color: $SAND; }
#Modalite:disabled { background: transparent; border-style: dashed; }
#ModaliteTitre { font-size: 15px; font-weight: 600; color: $TEXT; }
#ModaliteDescription { color: $TEXT_MUTED; font-size: 12px; }
#ModaliteTitre:disabled, #ModaliteDescription:disabled { color: $TEXT_DISABLED; }
#Hint { background: $PANEL; color: $TEXT; padding: 8px 12px; font-size: 13px; border-bottom: 1px solid $BORDER; }
""")


def stylesheet() -> str:
    return _QSS.substitute({k: v for k, v in globals().items() if isinstance(v, str) and v.startswith("#")})


def _palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: WINDOW, QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE, QPalette.ColorRole.AlternateBase: PANEL,
        QPalette.ColorRole.Text: TEXT, QPalette.ColorRole.PlaceholderText: TEXT_MUTED,
        QPalette.ColorRole.Button: SURFACE, QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: SAND, QPalette.ColorRole.HighlightedText: INK,
        QPalette.ColorRole.ToolTipBase: INK, QPalette.ColorRole.ToolTipText: WINDOW,
        QPalette.ColorRole.Link: SAND_DARK, QPalette.ColorRole.BrightText: WINDOW,
        QPalette.ColorRole.Light: SURFACE, QPalette.ColorRole.Midlight: PANEL,
        QPalette.ColorRole.Mid: BORDER, QPalette.ColorRole.Dark: BORDER_STRONG, QPalette.ColorRole.Shadow: TEXT_DISABLED,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_DISABLED))
    return p


def _load_bundled_fonts() -> None:
    for path in sorted(FONTS_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))   # -1 si le fichier est illisible : on garde la police système


def first_family(candidates: list[str]) -> str | None:
    available = set(QFontDatabase.families())
    return next((f for f in candidates if f in available), None)


def apply_theme(app: QApplication) -> None:
    """À appeler une fois, juste après la création de la QApplication."""
    app.setStyle(QStyleFactory.create("Fusion"))   # même rendu sur macOS, Windows et Linux
    app.setPalette(_palette())
    _load_bundled_fonts()
    family = first_family(FONT_FAMILIES)
    if family:
        font = QFont(family)
        font.setPointSize(app.font().pointSize())
        app.setFont(font)
        for cls in _FONT_CLASSES:
            class_font = QApplication.font(cls)    # garde la taille choisie par le système pour cette classe
            class_font.setFamily(family)
            app.setFont(class_font, cls)
    app.setStyleSheet(stylesheet())
