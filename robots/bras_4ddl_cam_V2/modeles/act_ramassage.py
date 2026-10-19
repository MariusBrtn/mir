"""
ACT ramassage

ACT (LeRobot) sur les démonstrations de ramassage du dé (dataset ramassage_sim_320, images 320 x 240).
Il prédit des séquences de 20 actions et en exécute 10 avant de regarder à nouveau.
Environ 0,4 s par pas sur un Mac récent : 5000 pas ≈ 30 min. Résultat obtenu le 19/10 : 7 dés soulevés sur 20.
"""
from mir_robot.lerobot_policies import train_lerobot

train_lerobot(policy="act", steps=5000, batch_size=8, chunk_size=20, n_action_steps=10)
