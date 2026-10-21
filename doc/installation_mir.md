# Installation M.I.R

MIR s'installe avec [uv](https://docs.astral.sh/uv/), qui télécharge Python 3.12, crée l'environnement et installe
les versions exactes de LeRobot, MuJoCo, PyTorch... (fichier `uv.lock`). Ni conda, ni droits administrateur.

Il faut une connexion internet et environ **6 Go** libres. La première installation prend 5 à 15 minutes.

## Installation rapide sur Mac (Apple Silicon : M1 ou plus récent)

Ouvrir l'application **Terminal** (Spotlight → taper « Terminal »), coller cette ligne puis appuyer sur Entrée :
```bash
curl -LsSf https://raw.githubusercontent.com/MariusBrtn/mir/main/installer/macos/install_mir.sh | bash
```
Le script ([installer/macos/install_mir.sh](../installer/macos/install_mir.sh)) affiche 4 étapes :
1. il installe uv s'il manque ;
2. il télécharge MIR dans le dossier personnel, `~/MIR` ;
3. il installe les paquets (Python, PyTorch, MuJoCo, LeRobot…) dans `~/MIR/.venv` ;
4. il crée l'application **MIR** dans `~/Applications`, puis la lance.

Ensuite, MIR se lance comme une autre application : Launchpad, Spotlight, ou le Dock (y glisser l'application pour
l'y garder).

- **Mettre à jour** : relancer la même ligne. Les fichiers déjà présents dans `~/MIR/robots/` (le travail de l'élève)
  ne sont pas remplacés ; un exemple déjà présent ne reçoit donc pas ses mises à jour.
- **En cas de problème** : le journal de l'application est dans `~/MIR/logs/application.log`.
- **Mac Intel** : non pris en charge, PyTorch n'existe plus pour ces Mac.
- **Désinstaller** : supprimer `~/Applications/MIR.app` et le dossier `~/MIR` (et, si on n'en veut plus, uv :
  `~/.local/bin/uv` et son cache `~/.cache/uv`).

Pourquoi une ligne dans le Terminal plutôt qu'un fichier à double-cliquer : macOS bloque les applications non signées
téléchargées depuis internet. Ce qui est récupéré par `curl`, et l'application créée sur place, ne sont pas bloqués.

## Installation pas à pas (Windows, macOS, Linux)

Elle fait la même chose à la main ; c'est aussi celle des développeurs (dossier `git clone`, mis à jour par `git pull`).

### 1. installer uv (une seule fois)

sous Windows, depuis PowerShell :
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
sous Linux et macOS, depuis le terminal :
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

### 2. récupérer MIR

```bash
git clone https://github.com/MariusBrtn/mir
```

---

### 3. installer MIR

depuis le dossier `mir` :
```bash
uv sync
```
(ou double-clic sur `install.bat` sous Windows, `./install.sh` sous Linux et macOS)

La première installation télécharge quelques Go (PyTorch surtout). Pour mettre à jour MIR : `git pull` puis `uv sync`.

---

### 4. lancer MIR

depuis le dossier `mir` :
```bash
uv run mir           # l'application
uv run mir-esp32     # l'outil de configuration des capteurs ESP32
uv run pytest        # les tests (en simulation, sans matériel)
```
Un script : `uv run python mon_script.py`. Dans VS Code, choisir l'interpréteur `mir/.venv`.

---

### pour réutiliser la librairie mir_utils (pas de dépendance lerobot):
pip install -e "git+ssh://git@github.com/MichelBtn/mir.git#subdirectory=mir_utils"
ou en local :
pip install -e /chemin/local/mir/mir_utils
