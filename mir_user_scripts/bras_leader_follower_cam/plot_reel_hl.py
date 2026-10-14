"""
Superpose :
  - la démonstration (action réelle enregistrée)
  - les prédictions hors ligne (baseline, real_no_div, real_div255, real_bgr_div255)
  - les actions + états observés pendant l'inférence RÉELLE sur le robot

Lit comparison_act_real_pipeline.csv (généré par compare_act_real_pipeline.py).
Si real_run_log.csv existe (log complet de la boucle réelle), il est utilisé
à la place des 6 points saisis à la main.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent
COMPARISON_CSV = BASE_DIR / "comparison_act_real_pipeline.csv"
REAL_LOG_CSV = BASE_DIR / "real_run_log.csv"   # optionnel, voir snippet
OUTPUT_PNG = BASE_DIR / "comparison_with_real_run.png"

JOINTS = [f"joint_{i}" for i in range(1, 6)]
FPS = 20

# ------------------------------------------------------------
# Points relevés pendant l'inférence réelle (1 point / seconde)
# ------------------------------------------------------------
REAL_TIMES = np.array([0, 1, 2, 3, 4, 5], dtype=float)

REAL_STATES = np.array([
    [-55.384617, 31.912088, -80.7033, 78.54945, 11.692307],
    [-51.78022, 53.53846, -72.87912, 78.63736, 3.3406594],
    [-51.34066, 53.53846, -72.17583, 78.63736, 2.901099],
    [-51.164837, 53.53846, -72.17583, 78.63736, 2.2857144],
    [-51.076923, 53.53846, -72.17583, 78.63736, 2.0219781],
    [-51.076923, 53.53846, -72.17583, 78.63736, 1.9340659],
])

REAL_ACTIONS = np.array([
    [-52.74412536621094, 53.473751068115234, -71.02053833007812,
     80.32911682128906, 2.884345769882202],
    [-51.057491302490234, 52.72015380859375, -70.7922134399414,
     80.34243774414062, 2.914093017578125],
    [-50.65184783935547, 51.535545349121094, -70.92448425292969,
     80.32998657226562, 2.2764270305633545],
    [-50.57604217529297, 51.429344177246094, -70.62715148925781,
     80.3299331665039, 2.0978496074676514],
    [-50.647212982177734, 51.662506103515625, -70.83956146240234,
     80.32994079589844, 1.600722074508667],
    [-50.630638122558594, 51.72197723388672, -70.91938018798828,
     80.32982635498047, 1.7555463314056396],
])

# Log complet éventuel (colonnes : time_s, state_1..5, action_1..5)
if REAL_LOG_CSV.is_file():
    log = pd.read_csv(REAL_LOG_CSV)
    REAL_TIMES = log["time_s"].to_numpy()
    REAL_STATES = log[[f"state_{j}" for j in range(1, 6)]].to_numpy()
    REAL_ACTIONS = log[[f"action_{j}" for j in range(1, 6)]].to_numpy()
    print(f"Log réel complet chargé : {len(log)} points")
else:
    print("Pas de real_run_log.csv : utilisation des 6 points manuels.")

# ------------------------------------------------------------
# Données hors ligne
# ------------------------------------------------------------
df = pd.read_csv(COMPARISON_CSV)
t = df["time_s"].to_numpy()

# (suffixe colonne, label, style)
CURVES = [
    ("real", "Démo (action réelle enregistrée)",
     dict(color="black", lw=2.5)),
    ("baseline", "Hors ligne baseline (image 0-1)",
     dict(color="tab:blue", lw=4.5, alpha=0.35)),
    ("real_div255", "Hors ligne pipeline réel + /255",
     dict(color="tab:blue", lw=1.5, ls="--")),
    ("real_no_div", "Hors ligne pipeline réel SANS /255",
     dict(color="tab:red", lw=1.8)),
    ("real_bgr_div255", "Hors ligne pipeline réel + /255 + BGR",
     dict(color="tab:green", lw=1.2, ls=":")),
]

fig, axes = plt.subplots(5, 1, figsize=(14, 17), sharex=True)

for j, ax in enumerate(axes):
    for suffix, label, style in CURVES:
        ax.plot(t, df[f"{JOINTS[j]}_{suffix}"], label=label, **style)

    # Actions proposées par ACT pendant l'inférence réelle
    ax.plot(
        REAL_TIMES, REAL_ACTIONS[:, j],
        color="magenta", marker="X", ms=11, lw=1.2, ls="-",
        markeredgecolor="black", label="RÉEL : action envoyée par ACT",
        zorder=5,
    )
    # État mesuré pendant l'inférence réelle
    ax.plot(
        REAL_TIMES, REAL_STATES[:, j],
        color="magenta", marker="o", ms=8, lw=0, mfc="none",
        label="RÉEL : état mesuré du follower", zorder=5,
    )

    ax.set_ylabel(JOINTS[j])
    ax.grid(True, alpha=0.4)

axes[0].legend(loc="upper left", fontsize=8, ncol=2)
axes[-1].set_xlabel("Temps depuis le début de l'essai (s)")
fig.suptitle(
    "ACT : démo vs prédictions hors ligne vs inférence réelle sur le robot\n"
    "(alignement par temps écoulé depuis le début de l'essai)"
)
fig.tight_layout()
fig.savefig(OUTPUT_PNG, dpi=150)
print("Graphique enregistré :", OUTPUT_PNG)
plt.show()

# ------------------------------------------------------------
# Écarts numériques : réel vs hors ligne aux instants du run réel
# ------------------------------------------------------------
print("\nÉcart (action réelle ACT − prédiction hors ligne) aux instants du run :")
for suffix in ["baseline", "real_no_div"]:
    print(f"\n--- vs {suffix} ---")
    for k, tk in enumerate(REAL_TIMES):
        idx = int(np.argmin(np.abs(t - tk)))
        off = np.array([df[f"{J}_{suffix}"].iloc[idx] for J in JOINTS])
        print(f"t={tk:4.1f}s  écart = {np.round(REAL_ACTIONS[k] - off, 2)}")