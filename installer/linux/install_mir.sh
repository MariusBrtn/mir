#!/bin/bash
# Installe MIR sur Linux (PC 64 bits : Ubuntu, Debian, Fedora, Arch...), ou le met à jour. Dans un Terminal :
#     curl -LsSf https://raw.githubusercontent.com/MariusBrtn/mir/main/installer/linux/install_mir.sh | bash
# ou, si curl n'est pas installé (Ubuntu de base) :
#     wget -qO- https://raw.githubusercontent.com/MariusBrtn/mir/main/installer/linux/install_mir.sh | bash
#
# - installe uv s'il manque (sans droits administrateur) ;
# - télécharge MIR dans ~/MIR et installe ses paquets (dossier ~/MIR/.venv, quelques Go) ;
# - crée l'entrée MIR dans le menu des applications (et sur le Bureau), puis lance MIR ;
# - propose (mot de passe administrateur, facultatif) d'installer la bibliothèque libxcb-cursor dont Qt a besoin, et
#   d'ajouter le compte au groupe qui a le droit d'utiliser le port série (bus des servos).
# Relancer la même commande met MIR à jour : le dossier robots/ (le travail de l'élève) n'est pas touché.
#
# Pour essayer l'installateur avant publication (variables facultatives) :
#     MIR_SOURCE=/chemin/vers/mir  (dossier, .zip ou .tar.gz local)   MIR_DIR=...   MIR_NO_OPEN=1   MIR_NO_SUDO=1
#     bash installer/linux/install_mir.sh
set -euo pipefail

MIR_BRANCH="${MIR_BRANCH:-main}"
MIR_SOURCE="${MIR_SOURCE:-https://github.com/MariusBrtn/mir/archive/refs/heads/$MIR_BRANCH.tar.gz}"
MIR_DIR="${MIR_DIR:-$HOME/MIR}"
USER="${USER:-$(id -un)}"
APPLICATIONS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
# robots créés à la première installation (simulés tant qu'on ne les construit pas) : bras 4 ddl avec caméra,
# robot mobile avec lidar
ROBOTS_DE_DEPART="bras_4ddl_cam_V2 test_mobile"

etape() { printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
attention() { printf '\033[1;33m! %s\033[0m\n' "$1"; }
echec() { printf '\n\033[1;31m✗ %s\033[0m\n' "$1" >&2; exit 1; }
telecharger() {   # telecharger URL FICHIER, avec curl ou wget
    if command -v curl >/dev/null 2>&1; then curl -fL --progress-bar "$1" -o "$2"
    else wget -q --show-progress "$1" -O "$2"; fi
}
# Lancé par « curl | bash », le script arrive par l'entrée standard : les questions se lisent sur /dev/tty.
# demander QUESTION : vrai si l'élève répond oui (jamais sans terminal, ni avec MIR_NO_SUDO)
demander() {
    [ -z "${MIR_NO_SUDO:-}" ] && { : < /dev/tty; } 2>/dev/null || return 1
    local reponse
    printf '%s [O/n] ' "$1" > /dev/tty
    read -r reponse < /dev/tty || return 1
    case "$reponse" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# ------------------------------------------------------------------ vérifications
[ "$(uname -s)" = "Linux" ] || echec "Cet installateur est pour Linux."
case "$(uname -m)" in
    x86_64) libre_min=12 ;;     # PyTorch pour Linux PC embarque CUDA (cartes NVIDIA) : quelques Go de plus
    aarch64) libre_min=6 ;;
    *) echec "MIR demande un processeur 64 bits (ce PC : $(uname -m))." ;;
esac
if [ -d "$MIR_DIR/.git" ]; then
    echec "$MIR_DIR est un dépôt git : mettez-le à jour avec « git pull » puis « uv sync »."
fi
command -v curl >/dev/null 2>&1 || command -v wget >/dev/null 2>&1 || echec "Il faut curl ou wget pour télécharger MIR."
mkdir -p "$MIR_DIR"
libre_go=$(( $(df -Pk "$MIR_DIR" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
[ "$libre_go" -ge "$libre_min" ] || echec "Il faut au moins $libre_min Go libres (il en reste $libre_go Go)."

# ------------------------------------------------------------------ uv
etape "1/5  Outil d'installation uv"
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
    echo "uv est déjà installé ($(uv --version))."
else
    if command -v curl >/dev/null 2>&1; then curl -LsSf https://astral.sh/uv/install.sh | sh
    else wget -qO- https://astral.sh/uv/install.sh | sh; fi
    command -v uv >/dev/null 2>&1 || echec "uv n'a pas pu être installé."
fi

# ------------------------------------------------------------------ téléchargement
etape "2/5  Téléchargement de MIR"
temp=$(mktemp -d)
trap 'rm -rf "$temp"' EXIT
if [ -d "$MIR_SOURCE" ]; then
    echo "Copie depuis $MIR_SOURCE"
    source_dir="$MIR_SOURCE"
else
    mkdir "$temp/archive"
    case "$MIR_SOURCE" in *.zip) archive="$temp/mir.zip" ;; *) archive="$temp/mir.tar.gz" ;; esac
    if [ -f "$MIR_SOURCE" ]; then
        cp "$MIR_SOURCE" "$archive"
    else
        echo "$MIR_SOURCE"
        telecharger "$MIR_SOURCE" "$archive" || echec "Téléchargement impossible : vérifiez la connexion internet."
    fi
    case "$archive" in
        *.zip) command -v unzip >/dev/null 2>&1 || echec "Il faut unzip pour ouvrir $MIR_SOURCE."
               unzip -q "$archive" -d "$temp/archive" ;;
        *) tar -xzf "$archive" -C "$temp/archive" ;;
    esac
    source_dir=$(dirname "$(find "$temp/archive" -maxdepth 3 -name pyproject.toml | awk '{ print length, $0 }' | sort -n | head -1 | cut -d' ' -f2-)")
fi
[ -f "$source_dir/pyproject.toml" ] && [ -f "$source_dir/uv.lock" ] || echec "Le téléchargement ne contient pas MIR."

# le code est remplacé ; robots/ est le dossier de l'élève : au départ, seulement deux robots, avec leur seule
# configuration (pas de graphe MIR Flow, de script ni de modèle). Un robot déjà présent n'est jamais touché.
# (tar plutôt que rsync, qui n'est pas installé partout)
(cd "$source_dir" && tar -cf - --exclude=./.git --exclude=./.venv --exclude=./logs --exclude=./robots \
    --exclude='__pycache__' --exclude='*.egg-info' --exclude=.pytest_cache .) | tar -xf - --no-same-owner -C "$MIR_DIR"
for robot in $ROBOTS_DE_DEPART; do
    if [ ! -e "$MIR_DIR/robots/$robot" ] && [ -f "$source_dir/robots/$robot/robot.json" ]; then
        mkdir -p "$MIR_DIR/robots/$robot"
        cp "$source_dir/robots/$robot/robot.json" "$MIR_DIR/robots/$robot/"
    fi
done
echo "MIR est dans $MIR_DIR"

# ------------------------------------------------------------------ paquets
etape "3/5  Installation des paquets (Python, PyTorch, MuJoCo, LeRobot…) : 5 à 20 minutes la première fois"
# Python téléchargé par uv plutôt que celui de la distribution : toujours le même, quelle que soit la distribution
export UV_PYTHON_PREFERENCE=only-managed
if [ -f "$MIR_DIR/.venv/pyvenv.cfg" ] && ! grep -q "$(uv python dir)" "$MIR_DIR/.venv/pyvenv.cfg"; then
    echo "Environnement créé avec un autre Python : il est refait."
    rm -rf "$MIR_DIR/.venv"
fi
(cd "$MIR_DIR" && uv sync) || echec "L'installation des paquets a échoué (voir les messages ci-dessus)."

# ------------------------------------------------------------------ réglages du système (facultatifs)
etape "4/5  Réglages du système"
# Qt 6 (l'interface de MIR) a besoin de libxcb-cursor, absente de certaines distributions (Ubuntu, Debian)
if (ldconfig -p 2>/dev/null || /sbin/ldconfig -p 2>/dev/null) | grep -q 'libxcb-cursor\.so\.0'; then
    echo "Bibliothèque libxcb-cursor : présente."
else
    if command -v apt-get >/dev/null 2>&1; then paquet=libxcb-cursor0; installer_paquet=(apt-get install -y libxcb-cursor0)
    elif command -v dnf >/dev/null 2>&1; then paquet=xcb-util-cursor; installer_paquet=(dnf install -y xcb-util-cursor)
    elif command -v pacman >/dev/null 2>&1; then paquet=xcb-util-cursor; installer_paquet=(pacman -S --noconfirm xcb-util-cursor)
    elif command -v zypper >/dev/null 2>&1; then paquet=libxcb-cursor0; installer_paquet=(zypper install -y libxcb-cursor0)
    else paquet=libxcb-cursor; installer_paquet=(); fi
    attention "La bibliothèque $paquet manque : sans elle, la fenêtre de MIR peut refuser de s'ouvrir."
    if [ ${#installer_paquet[@]} -gt 0 ] && demander "L'installer maintenant (mot de passe administrateur) ?" \
        && sudo "${installer_paquet[@]}" < /dev/tty; then
        echo "$paquet est installée."
    else
        attention "À faire par un administrateur : sudo ${installer_paquet[*]:-<gestionnaire de paquets> $paquet}"
    fi
fi
# port série du bus des servos (/dev/ttyUSB0, /dev/ttyACM0) : réservé au groupe dialout (uucp sous Arch)
groupe_serie=dialout
for port in /dev/ttyUSB* /dev/ttyACM*; do
    [ -e "$port" ] && groupe_serie=$(stat -c %G "$port") && break
done
if ! getent group "$groupe_serie" >/dev/null 2>&1 && getent group uucp >/dev/null 2>&1; then groupe_serie=uucp; fi
if id -nG "$USER" | tr ' ' '\n' | grep -qx "$groupe_serie"; then
    echo "Port série : le compte $USER fait partie du groupe $groupe_serie."
else
    attention "Pour piloter un vrai robot, le compte $USER doit faire partie du groupe $groupe_serie (port série)."
    if demander "L'y ajouter maintenant (mot de passe administrateur) ?" && sudo usermod -aG "$groupe_serie" "$USER" < /dev/tty; then
        attention "Fait : fermez la session puis reconnectez-vous pour que ce soit pris en compte."
    else
        attention "À faire par un administrateur : sudo usermod -aG $groupe_serie $USER  (puis se reconnecter)"
    fi
fi

# ------------------------------------------------------------------ menu des applications
etape "5/5  Application MIR"
chmod +x "$MIR_DIR/installer/linux/lancer_mir.sh"
mkdir -p "$APPLICATIONS"
entree="$APPLICATIONS/mir.desktop"
cat > "$entree" <<DESKTOP
[Desktop Entry]
Type=Application
Name=MIR
GenericName=Robotique et IA
Comment=MIR (Modular Intelligent Robot) : plateforme pédagogique de robotique et d'IA
Exec="$MIR_DIR/installer/linux/lancer_mir.sh"
Path=$MIR_DIR
Icon=$MIR_DIR/installer/linux/MIR.png
Terminal=false
Categories=Education;Science;Robotics;
StartupWMClass=mir
DESKTOP
chmod +x "$entree"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPLICATIONS" 2>/dev/null || true
# copie sur le Bureau ; GNOME demande en plus de la marquer « de confiance » pour qu'elle se lance d'un double-clic
bureau=$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")
if [ -d "$bureau" ] && [ "$bureau" != "$HOME" ]; then
    cp "$entree" "$bureau/mir.desktop"
    gio set "$bureau/mir.desktop" metadata::trusted true 2>/dev/null || true
fi

printf '\n\033[1;32m✓ MIR est installé.\033[0m\n'
echo "  Application : menu des applications (cherchez « MIR »)"
echo "  Dossier     : $MIR_DIR (robots, scripts, datasets)"
echo "  Journal     : $MIR_DIR/logs/application.log"
echo "  Mise à jour : relancez la même commande d'installation."
if [ -z "${MIR_NO_OPEN:-}" ]; then
    # détaché du Terminal : MIR reste ouvert quand on le ferme
    nohup "$MIR_DIR/installer/linux/lancer_mir.sh" >/dev/null 2>&1 &
fi
