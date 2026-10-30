#!/bin/bash
# Lancé par l'entrée MIR du menu des applications (créée par installer/linux/install_mir.sh) : la sortie va dans
# logs/application.log, comme avec l'application macOS et le raccourci Windows
MIR_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
if [ ! -x "$MIR_DIR/.venv/bin/python" ]; then
    message="MIR n'est pas installé correctement : relancez l'installateur de MIR."
    zenity --error --text="$message" 2>/dev/null || kdialog --error "$message" 2>/dev/null || notify-send MIR "$message"
    exit 1
fi
mkdir -p "$MIR_DIR/logs"
cd "$MIR_DIR"
# nom de la fenêtre sous X11 (StartupWMClass de mir.desktop) : le menu lui associe l'icône de MIR
export RESOURCE_NAME=mir
exec "$MIR_DIR/.venv/bin/python" -m mir_robot_editor.main >> "$MIR_DIR/logs/application.log" 2>&1
