# Installation M.I.R

MIR s'installe avec [uv](https://docs.astral.sh/uv/), qui télécharge Python 3.12, crée l'environnement et installe
les versions exactes de LeRobot, MuJoCo, PyTorch... (fichier `uv.lock`). Ni conda, ni droits administrateur.

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
