"""
Behavior cloning : un petit CNN apprend à ramasser le dé à partir de l'image de la pince et des angles du bras.

MIR prépare les données (images redimensionnées et normalisées, angles et actions standardisés) :
le réseau reçoit un batch {"state": B×5, "cam_1": B×3×96×128} et prédit les 5 consignes des moteurs.

    uv run python robots/bras_4ddl_cam_V2/modeles/cnn_ramassage.py
"""
import torch
from torch import nn
import matplotlib.pyplot as plt
from mir_robot.mir_robot import chemin_robot
from mir_robot.training import load_data, save_model

DATASET = chemin_robot("bras_4ddl_cam_V2").parent / "datasets" / "ramassage_sim"    # hors de MIR
EPOCHS = 15

data = load_data(inputs=["state", "cam_1"], image_size=(96, 128), dataset=DATASET, batch_size=64)


class Policy(nn.Module):
    def __init__(self, n_state, n_actions):
        super().__init__()
        self.cnn = nn.Sequential(                                   # 3×96×128 -> 64 caractéristiques
            nn.Conv2d(3, 16, 5, stride=2, padding=2), nn.ReLU(),
            nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((3, 4)), nn.Flatten(),
            nn.Linear(64 * 3 * 4, 64), nn.ReLU(),
        )
        self.head = nn.Sequential(nn.Linear(64 + n_state, 128), nn.ReLU(), nn.Linear(128, n_actions))

    def forward(self, batch):
        return self.head(torch.cat([self.cnn(batch["cam_1"]), batch["state"]], dim=1))


model = Policy(data.n_state, data.n_actions).to(data.device)
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
    print(f"epoch {epoch + 1}/{EPOCHS} : train {train_losses[-1]:.4f}, val {val_losses[-1]:.4f}")
    plt.clf()
    plt.plot(train_losses, label="train")
    plt.plot(val_losses, label="val")
    plt.xlabel("epoch")
    plt.ylabel("loss (MSE)")
    plt.yscale("log")
    plt.legend()
    plt.pause(0.01)

save_model(model, data)
