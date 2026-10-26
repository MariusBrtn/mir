# Lancé par le raccourci MIR (créé par installer/windows/install_mir.ps1) avec pythonw, qui n'a pas de console :
# la sortie va dans logs/application.log, comme avec l'application macOS
import sys
from pathlib import Path

logs = Path(__file__).resolve().parents[2] / "logs"
logs.mkdir(exist_ok=True)
sys.stdout = sys.stderr = open(logs / "application.log", "a", encoding="utf-8", buffering=1)

from mir_robot_editor.main import main   # noqa: E402

main()
