#!/bin/bash
# Installe MIR sur macOS (Mac Apple Silicon), ou le met à jour. Dans un Terminal :
#     curl -LsSf https://raw.githubusercontent.com/MariusBrtn/mir/main/installer/macos/install_mir.sh | bash
#
# - installe uv s'il manque (sans droits administrateur) ;
# - télécharge MIR dans ~/MIR et installe ses paquets (dossier ~/MIR/.venv, quelques Go) ;
# - crée l'application MIR dans ~/Applications (Launchpad, Spotlight, Dock) et la lance.
# Relancer la même commande met MIR à jour : les fichiers déjà présents dans robots/ (le travail de l'élève) sont gardés.
#
# Pour essayer l'installateur avant publication (variables facultatives) :
#     MIR_SOURCE=/chemin/vers/mir  (dossier ou .zip local)   MIR_DIR=...   MIR_APP_DIR=...
#     bash installer/macos/install_mir.sh
set -euo pipefail

MIR_BRANCH="${MIR_BRANCH:-main}"
MIR_SOURCE="${MIR_SOURCE:-https://github.com/MariusBrtn/mir/archive/refs/heads/$MIR_BRANCH.zip}"
MIR_DIR="${MIR_DIR:-$HOME/MIR}"
MIR_APP_DIR="${MIR_APP_DIR:-$HOME/Applications}"
APP="$MIR_APP_DIR/MIR.app"

etape() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
echec() { printf '\n\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

# ------------------------------------------------------------------ vérifications
[ "$(uname -s)" = "Darwin" ] || echec "Cet installateur est pour macOS."
[ "$(uname -m)" = "arm64" ] || echec "MIR demande un Mac Apple Silicon (M1 ou plus récent) : PyTorch n'existe plus pour les Mac Intel."
if [ -d "$MIR_DIR/.git" ]; then
    echec "$MIR_DIR est un dépôt git : mettez-le à jour avec « git pull » puis « uv sync »."
fi
libre_go=$(df -g "$HOME" | awk 'NR==2 {print $4}')
[ "${libre_go:-0}" -ge 6 ] || echec "Il faut au moins 6 Go libres (il en reste ${libre_go} Go)."

# ------------------------------------------------------------------ uv
etape "1/4  Outil d'installation uv"
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
    echo "uv est déjà installé ($(uv --version))."
else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    command -v uv >/dev/null 2>&1 || echec "uv n'a pas pu être installé."
fi

# ------------------------------------------------------------------ téléchargement
etape "2/4  Téléchargement de MIR"
temp=$(mktemp -d)
trap 'rm -rf "$temp"' EXIT
if [ -d "$MIR_SOURCE" ]; then
    echo "Copie depuis $MIR_SOURCE"
    source_dir="$MIR_SOURCE"
else
    if [ -f "$MIR_SOURCE" ]; then
        cp "$MIR_SOURCE" "$temp/mir.zip"
    else
        echo "$MIR_SOURCE"
        curl -fL --progress-bar "$MIR_SOURCE" -o "$temp/mir.zip" || echec "Téléchargement impossible : vérifiez la connexion internet."
    fi
    unzip -q "$temp/mir.zip" -d "$temp/zip"
    source_dir=$(dirname "$(find "$temp/zip" -maxdepth 3 -name pyproject.toml -path '*/pyproject.toml' | awk '{ print length, $0 }' | sort -n | head -1 | cut -d' ' -f2-)")
fi
[ -f "$source_dir/pyproject.toml" ] && [ -f "$source_dir/uv.lock" ] || echec "Le téléchargement ne contient pas MIR."

mkdir -p "$MIR_DIR"
exclus=(--exclude .git --exclude .venv --exclude logs --exclude '__pycache__' --exclude '*.egg-info' --exclude .pytest_cache)
# le code est remplacé ; dans robots/, seuls les fichiers absents sont ajoutés (on ne touche pas au travail de l'élève)
rsync -a "${exclus[@]}" --exclude /robots "$source_dir/" "$MIR_DIR/"
if [ -d "$source_dir/robots" ]; then
    rsync -a --ignore-existing "${exclus[@]}" "$source_dir/robots/" "$MIR_DIR/robots/"
fi
echo "MIR est dans $MIR_DIR"

# ------------------------------------------------------------------ paquets
etape "3/4  Installation des paquets (Python, PyTorch, MuJoCo, LeRobot…) : 5 à 15 minutes la première fois"
(cd "$MIR_DIR" && uv sync) || echec "L'installation des paquets a échoué (voir les messages ci-dessus)."

# ------------------------------------------------------------------ application
etape "4/4  Application MIR"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$MIR_DIR/installer/macos/MIR.icns" "$APP/Contents/Resources/MIR.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>MIR</string>
    <key>CFBundleDisplayName</key><string>MIR</string>
    <key>CFBundleIdentifier</key><string>io.github.mariusbrtn.mir</string>
    <key>CFBundleExecutable</key><string>MIR</string>
    <key>CFBundleIconFile</key><string>MIR</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>0.1.0</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSBluetoothAlwaysUsageDescription</key><string>MIR envoie le réseau Wi-Fi aux modules capteurs en Bluetooth.</string>
    <key>NSLocalNetworkUsageDescription</key><string>MIR cherche les modules capteurs (caméra, lidar) sur le réseau local.</string>
    <key>NSCameraUsageDescription</key><string>MIR peut utiliser une caméra branchée sur l'ordinateur.</string>
</dict>
</plist>
PLIST
cat > "$APP/Contents/MacOS/MIR" <<LANCEUR
#!/bin/bash
# lance MIR installé dans $MIR_DIR (créé par installer/macos/install_mir.sh)
MIR_DIR="$MIR_DIR"
if [ ! -x "\$MIR_DIR/.venv/bin/python" ]; then
    osascript -e 'display alert "MIR n’est pas installé correctement" message "Relancez l’installateur de MIR."'
    exit 1
fi
mkdir -p "\$MIR_DIR/logs"
cd "\$MIR_DIR"
exec "\$MIR_DIR/.venv/bin/python" -m mir_robot_editor.main >> "\$MIR_DIR/logs/application.log" 2>&1
LANCEUR
chmod +x "$APP/Contents/MacOS/MIR"
touch "$APP"                     # le Finder relit l'icône

printf '\n\033[1;32m✓ MIR est installé.\033[0m\n'
echo "  Application : $APP (Launchpad, Spotlight ; glissez-la dans le Dock pour la garder)"
echo "  Dossier     : $MIR_DIR (robots, scripts, datasets)"
echo "  Mise à jour : relancez la même commande d'installation."
if [ -z "${MIR_NO_OPEN:-}" ]; then
    open "$APP"
fi
