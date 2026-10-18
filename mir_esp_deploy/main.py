import sys
import traceback

from PySide6 import QtWidgets

from mir_utils.logs import enable_logging
from mir_utils.ui.dialogs import QtDialogProvider
from mir_esp_deploy.esp32_deploy_view import Esp32DeployView
from mir_esp_deploy.esp32_deploy_view_model import Esp32DeployViewModel

enable_logging()

dialogProvider = QtDialogProvider()


def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    print("==== Exception globale capturée ====", file=sys.stderr)
    print(tb_text, file=sys.stderr)
    print("====================================", file=sys.stderr)
    dialogProvider.exception(exc_value, traceback_str=tb_text)


sys.excepthook = global_exception_handler


def main():
    """Point d'entrée de la commande mir-esp32 (voir pyproject.toml à la racine)."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    view_model = Esp32DeployViewModel(dialogProvider)
    window = Esp32DeployView(view_model)
    dialogProvider.setParent(window)

    # Nettoyage du BackgroundWorker à la fermeture
    app.aboutToQuit.connect(lambda: view_model._worker.shutdown(wait=True))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
