"""
Étape « Entraîner un modèle » : les scripts d'entraînement du robot (robots/<robot>/modeles/*.py), lancés comme ceux de
Piloter → Scripts (dans leur propre programme Python, ■ pour arrêter), avec le dataset choisi ici. Pas besoin du robot :
on peut entraîner pendant qu'on pilote. Les modèles entraînés se choisissent ensuite dans Piloter → IA.
"""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any
from PySide6.QtCore import QProcessEnvironment, Signal
from mir_robot.donnees import DatasetMIR, datasets_du_robot
from mir_robot.training import DATASET_ENV, MODELS_DIR, model_info, trained_models
from mir_robot_editor.scripts.scripts_view_model import ScriptsViewModel, nom_de_fichier
from mir_utils.ui.dialogs import IDialogProvider

PYTORCH, LEROBOT = "pytorch", "lerobot"
TYPES = {PYTORCH: "Mon réseau PyTorch (behavior cloning)", LEROBOT: "Modèle LeRobot (ACT, Diffusion)"}

MODELE_PYTORCH = '''"""
{nom}

Behavior cloning : un réseau PyTorch apprend à prédire les consignes du robot à partir de ses observations.
MIR prépare les données (images redimensionnées et normalisées, grandeurs et actions standardisées) :
le réseau reçoit un batch {{{doc_entrees}}} et prédit {n_actions} consignes.
Le modèle enregistré se choisit ensuite dans Piloter → IA.
"""
import torch
from torch import nn
import matplotlib.pyplot as plt
from mir_robot.training import load_data, save_model

EPOCHS = 15
data = load_data(inputs={entrees!r}{image_size}, batch_size=64)


{classe}

model = Policy(data.shapes, data.n_actions).to(data.device)
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
train_losses, val_losses = [], []

for epoch in range(EPOCHS):
    model.train()
    total = 0.0
    for batch in data.train_loader:
        loss = nn.functional.mse_loss(model(batch), batch["action"])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        total += loss.item()
    train_losses.append(total / len(data.train_loader))
    val_losses.append(data.evaluate(model))
    print(f"epoch {{epoch + 1}}/{{EPOCHS}} : train {{train_losses[-1]:.4f}}, val {{val_losses[-1]:.4f}}")
    plt.clf()
    plt.plot(train_losses, ".-", label="train")
    plt.plot(val_losses, ".-", label="val")
    plt.xlabel("epoch")
    plt.ylabel("loss (MSE)")
    plt.yscale("log")
    plt.legend()
    plt.pause(0.01)

save_model(model, data)
'''

CLASSE_CNN = '''class Policy(nn.Module):
    def __init__(self, shapes, n_actions):
        super().__init__()
        self.cnn = nn.Sequential(                       # image -> 64 caractéristiques
            nn.Conv2d(3, 16, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((3, 4)), nn.Flatten(),
            nn.Linear(64 * 3 * 4, 64), nn.ReLU(),
        )
        n_state = shapes["state"][0]
        self.head = nn.Sequential(nn.Linear(64 + n_state, 128), nn.ReLU(), nn.Linear(128, n_actions))

    def forward(self, batch):
        return self.head(torch.cat([self.cnn(batch["{camera}"]), batch["state"]], dim=1))'''

CLASSE_MLP = '''class Policy(nn.Module):
    def __init__(self, shapes, n_actions):
        super().__init__()
        n_state = shapes["state"][0]
        self.net = nn.Sequential(nn.Linear(n_state, 128), nn.ReLU(), nn.Linear(128, 128), nn.ReLU(),
                                 nn.Linear(128, n_actions))

    def forward(self, batch):
        return self.net(batch["state"])'''

MODELE_LEROBOT = '''"""
{nom}

Un modèle de LeRobot entraîné sur le dataset choisi dans MIR ; il se choisit ensuite dans Piloter → IA.
  policy="act"        ACT : prédit des séquences de chunk_size actions et en exécute n_action_steps avant de regarder
                      à nouveau (ce qui limite l'accumulation des erreurs) ;
  policy="diffusion"  Diffusion Policy (n_obs_steps=2 : regarde les deux dernières observations).
Durée : avec des images de 320 x 240, environ 0,4 s par pas sur un Mac récent (5000 pas : ~30 min) ;
avec des images de 640 x 480, quatre fois plus.
"""
from mir_robot.lerobot_policies import train_lerobot

train_lerobot(policy="act", steps=5000, batch_size=8, chunk_size=20, n_action_steps=10)
'''


class EntrainementViewModel(ScriptsViewModel):
    BESOIN_DU_ROBOT = False
    datasets_changed = Signal()
    modeles_changed = Signal()

    def __init__(self, dialog_provider: IDialogProvider):
        super().__init__(dialog_provider)
        self._dossier_robot: Path | None = None
        self._dataset: DatasetMIR | None = None

    # ------------------------------------------------------------------ robot, datasets, modèles
    def set_dossier_robot(self, dossier: Path | None):
        """Robot ouvert (son dossier), ou None : ses scripts d'entraînement, datasets et modèles."""
        self._dossier_robot = dossier
        self.set_dossier(dossier / MODELS_DIR if dossier is not None else None)
        noms = [ds.nom for ds in self.datasets()]
        if self._dataset is None or self._dataset.nom not in noms or self._dataset.dossier.parent.parent != dossier:
            self._dataset = self.datasets()[0] if noms else None
        self.datasets_changed.emit()
        self.modeles_changed.emit()

    def datasets(self) -> list[DatasetMIR]:
        return datasets_du_robot(self._dossier_robot) if self._dossier_robot is not None else []

    def dataset(self) -> DatasetMIR | None:
        return self._dataset

    def set_dataset(self, nom: str | None):
        self._dataset = next((ds for ds in self.datasets() if ds.nom == nom), None)

    def resume_dataset(self) -> str:
        ds = self._dataset
        if ds is None:
            return "Aucun dataset : enregistrez des démonstrations dans « Collecter des données »."
        try:
            fmt = ds.format()
            entrees = (["state"] if fmt.etat else []) + list(fmt.images) + list(fmt.tableaux)
            images = ", ".join(f"{nom} {forme[1]}×{forme[0]}" for nom, forme in fmt.images.items())
            return (f"{len(ds.episodes())} épisodes à {ds.fps():g} Hz\n"
                    f"entrées : {', '.join(entrees)}" + (f" ({images})" if images else "") +
                    f"\n{len(fmt.actions)} actions")
        except Exception as e:
            return f"Dataset illisible : {e}"

    def modeles(self) -> list[dict[str, Any]]:
        return [model_info(d) for d in trained_models(self._dossier_robot)] if self._dossier_robot is not None else []

    def supprimer_modele(self, dossier: str | Path):
        dossier = Path(dossier)
        if not self._dialogProvider.question_yes_no("Supprimer le modèle",
                                                    f"Supprimer le modèle {dossier.parent.name} du {dossier.name} ?\r\n"
                                                    "Ses poids sont effacés du disque."):
            return
        shutil.rmtree(dossier, ignore_errors=True)
        self.modeles_changed.emit()

    # ------------------------------------------------------------------ scripts
    def nouveau(self, nom: str, genre: str = PYTORCH) -> Path | None:
        """Crée un script d'entraînement à partir d'un modèle, adapté au dataset choisi ; None si impossible."""
        if self._dossier is None:
            self._dialogProvider.information("Nouveau script", "Enregistrez d'abord le robot : ses modèles sont rangés "
                                             "dans son dossier.")
            return None
        fichier = self._dossier / nom_de_fichier(nom)
        if fichier.exists():
            self._dialogProvider.information("Nouveau script", f"Le fichier {fichier.name} existe déjà.")
            return None
        titre = nom.replace('"', "'")
        if genre == LEROBOT:
            texte = MODELE_LEROBOT.format(nom=titre)
        else:
            fmt = self._dataset.format() if self._dataset is not None else None
            camera = next(iter(fmt.images), None) if fmt is not None else None
            entrees = ["state", camera] if camera else ["state"]
            doc = '"state": B×n' + (f', "{camera}": B×3×96×128' if camera else "")
            texte = MODELE_PYTORCH.format(
                nom=titre, doc_entrees=doc, n_actions=len(fmt.actions) if fmt is not None else "les",
                entrees=entrees, image_size=", image_size=(96, 128)" if camera else "",
                classe=CLASSE_CNN.format(camera=camera) if camera else CLASSE_MLP)
        self._dossier.mkdir(parents=True, exist_ok=True)
        fichier.write_text(texte, encoding="utf-8")
        return fichier

    # ------------------------------------------------------------------ exécution
    def _peut_lancer(self) -> bool:
        if self._dataset is None or not self._dataset.existe():
            self._dialogProvider.information("Entraîner", "Choisissez d'abord un dataset (enregistré dans « Collecter "
                                             "des données »).")
            return False
        return True

    def _environnement(self, env: QProcessEnvironment) -> None:
        env.insert(DATASET_ENV, str(self._dataset.dossier.resolve()))

    def _fin(self, process, code, statut):
        super()._fin(process, code, statut)
        self.modeles_changed.emit()          # un modèle vient peut-être d'être enregistré
