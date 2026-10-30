import traceback
from mir_utils.logs import enable_logging
enable_logging()
import sys   #noqa E402
import logging #noqa E402
from logging.handlers import RotatingFileHandler #noqa E402
from pathlib import Path #noqa E402
from PySide6 import QtWidgets #noqa E402
from PySide6.QtCore import QLibraryInfo, QTranslator #noqa E402
from mir_robot_editor.main_view import MainView #noqa E402
from mir_robot_editor.main_viewmodel import MainViewModel #noqa E402
from mir_utils.ui.dialogs import QtDialogProvider #noqa E402
from mir_utils.ui.theme import apply_theme #noqa E402
from mir_robot_editor import habillage #noqa E402

dialogProvider = QtDialogProvider()

def global_exception_handler(exc_type, exc_value, exc_traceback):
    # Évite de bloquer la fermeture de l'application si l'erreur est fatale
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    # Extraction et formatage textuel de la pile d'appels
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    tb_text = "".join(tb_lines)

    print("==== Exception globale capturée ====", file=sys.stderr)
    print(tb_text, file=sys.stderr)
    print("====================================", file=sys.stderr)

    dialogProvider.exception(exc_value, traceback_str=tb_text)

# Redirection des exceptions non capturées de Python et PySide
sys.excepthook = global_exception_handler

class PrefixFilter(logging.Filter):

  def __init__(self, prefix):
    super().__init__()
    self.prefix = prefix

  def filter(self, record):
    return record.getMessage().startswith(self.prefix)


def enable_motor_bus_debug():
  debug_logger = logging.getLogger("lerobot.motors.motors_bus")

  # Évite les ajouts multiples de handlers si la fonction est appelée plusieurs fois
  if debug_logger.handlers:
    return

  # Définition et création du dossier de logs s'il n'existe pas
  log_dir = Path(__file__).resolve().parent.parent / "logs"
  log_dir.mkdir(parents=True, exist_ok=True)
  log_file = log_dir / "motor_bus_debug.log"

  # Configuration du Handler
  file_handler = RotatingFileHandler(
      log_file,
      maxBytes= 1024 * 1024,  # 1 Mo
      backupCount=3,
      encoding="utf-8",
  )
  file_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
  file_handler.addFilter(PrefixFilter("[MOTOR_BUS]"))

  # Configuration du Logger
  debug_logger.setLevel(logging.DEBUG)
  debug_logger.propagate = False
  debug_logger.addHandler(file_handler)

  debug_logger.debug("[MOTOR_BUS] ================== START ===================================================")

def main():
    """Point d'entrée de la commande mir (voir pyproject.toml à la racine)."""
    enable_motor_bus_debug()
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    # Linux : la fenêtre est celle de l'entrée mir.desktop du menu (icône de MIR dans la barre des tâches)
    app.setDesktopFileName("mir")
    apply_theme(app)
    habillage.installer()
    # boutons standard de Qt (Annuler, Oui, Non...) en français, comme le reste de MIR
    traduction = QTranslator(app)
    if traduction.load("qtbase_fr", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(traduction)
    mainViewModel = MainViewModel(dialogProvider)
    window = MainView(mainViewModel)
    dialogProvider.setParent(window)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
    