"""
Errance (PPO)

Apprentissage par renforcement : le robot apprend, par essais et erreurs dans la rue simulée, à rouler sans rien
percuter (tâche décrite dans errance_env.py). Pas besoin de dataset : le robot produit lui-même ses expériences.
PPO (Stable-Baselines3) fait tourner 8 rues en parallèle, une par cœur du processeur.
Durée : environ 12 minutes pour 1 million de pas sur un Mac récent. ■ arrête l'entraînement sans rien enregistrer.
Le modèle enregistré se choisit ensuite dans Piloter → IA (choisir la scène « Rue encombrée » en simulé).
"""
import matplotlib.pyplot as plt
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.vec_env import SubprocVecEnv
from mir_robot.rl import save_rl_model
from errance_env import ErranceEnv, ErranceRobot

TOTAL_STEPS = 1_000_000
N_ENVS = 8


class Courbes(BaseCallback):
    """Après chaque série d'essais : affiche la récompense et la durée moyennes des derniers épisodes."""

    def __init__(self):
        super().__init__()
        self.steps, self.rewards, self.lengths = [], [], []

    def _on_rollout_end(self):
        episodes = self.model.ep_info_buffer          # 100 derniers épisodes terminés
        if not episodes:
            return
        self.steps.append(self.num_timesteps)
        self.rewards.append(sum(e["r"] for e in episodes) / len(episodes))
        self.lengths.append(sum(e["l"] for e in episodes) / len(episodes) / ErranceRobot.fps)
        print(f"{self.num_timesteps:>9} pas : récompense {self.rewards[-1]:6.1f}, durée {self.lengths[-1]:4.1f} s")
        plt.clf()
        plt.subplot(2, 1, 1)
        plt.plot(self.steps, self.rewards)
        plt.ylabel("récompense par épisode")
        plt.subplot(2, 1, 2)
        plt.plot(self.steps, self.lengths)
        plt.ylabel("durée de l'épisode (s)")
        plt.xlabel("pas d'entraînement")
        plt.pause(0.01)

    def _on_step(self):
        return True


# les rues parallèles tournent dans d'autres programmes Python, qui relisent ce fichier : sans ce « if », chacun
# relancerait l'entraînement
if __name__ == "__main__":
    env = make_vec_env(ErranceEnv, n_envs=N_ENVS, seed=0, vec_env_cls=SubprocVecEnv)
    model = PPO("MlpPolicy", env, n_steps=1024, batch_size=256, n_epochs=10, learning_rate=3e-4, gamma=0.99,
                policy_kwargs={"net_arch": [128, 128]}, device="cpu", seed=0)
    model.learn(total_timesteps=TOTAL_STEPS, callback=Courbes())
    env.close()
    save_rl_model(model, ErranceRobot)
