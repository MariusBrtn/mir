
from mir_robot.mir_robot import mirRobot, mirRobotConfig

from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.datasets.feature_utils import build_dataset_frame
from lerobot.utils.constants import ACTION, OBS_STR
from mir_utils.period_waiters import PeriodWaiterExact

import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk

import cv2
import time
import copy
import traceback


# ============================================================
# PARAMETRES
# ============================================================

FPS = 20
FRAME_PERIOD = 1.0 / FPS

TASK = "bras_4ddl_cam"

DATASET_REPO_ID = "local/mir_4ddl_cam_dice"

DATASET_ROOT = (
    "/Users/marius/Documents/Atelier Vectoriel/"
    "MIR/MIR-software/mir/mir_user_scripts/"
    "bras_leader_follower_cam/dataset_dice"
)

NUM_EPISODES = 30
EPISODE_TIME = 6
RESET_TIME = 5

N_FRAMES = int(FPS * EPISODE_TIME)

JOINT_NAMES = [
    "joint_1.position",
    "joint_2.position",
    "joint_3.position",
    "joint_4.position",
    "joint_5.position",
]

FEATURES = {
    "observation.state": {
        "dtype": "float32",
        "shape": (len(JOINT_NAMES),),
        "names": JOINT_NAMES,
    },
    "observation.images.cam_1": {
        "dtype": "video",
        "shape": (240, 320, 3),
        "names": ["height", "width", "channels"],
    },
    "action": {
        "dtype": "float32",
        "shape": (len(JOINT_NAMES),),
        "names": JOINT_NAMES,
    },
}


# ============================================================
# INITIALISATION DES ROBOTS
# ============================================================

leader_config = mirRobotConfig.load(
    "/Users/marius/Documents/Atelier Vectoriel/"
    "MIR/MIR-software/mir/mir_user_scripts/"
    "bras_leader_follower_cam/bras_leader.json"
)

follower_config = mirRobotConfig.load(
    "/Users/marius/Documents/Atelier Vectoriel/"
    "MIR/MIR-software/mir/mir_user_scripts/"
    "bras_leader_follower_cam/bras_follower_cam.json"
)

leader = mirRobot(leader_config)
follower = mirRobot(follower_config)

leader.connect()
leader.configure()
leader.enable_all_observations()

follower.connect()
follower.configure()
follower.enable_all_observations()


# ============================================================
# CREATION DU DATASET
# ============================================================

dataset = LeRobotDataset.create(
    repo_id=DATASET_REPO_ID,
    root=DATASET_ROOT,
    fps=FPS,
    features=FEATURES,
    robot_type="mir_robot",
    vcodec="h264",
    batch_encoding_size=1,
)


# ============================================================
# INTERFACE GRAPHIQUE
# ============================================================

class DatasetGUI:

    def __init__(self, root):

        self.root = root
        self.root.title("MIR - Enregistrement des démonstrations")
        self.root.geometry("760x650")

        # Etats :
        # idle, reset, recording, review, saving, done, error

        self.state = "idle"

        self.saved_count = 0
        self.demo_frames = []
        self.save_index = 0

        self.phase_start = 0.0

        self.photo = None
        self.closed = False
        self.dataset_finalized = False

        # Cadencement de l'acquisition
        self.period_waiter = PeriodWaiterExact(FRAME_PERIOD)

        # ----------------------------------------------------
        # TITRE
        # ----------------------------------------------------

        tk.Label(
            root,
            text="Collecte de démonstrations MIR",
            font=("Helvetica", 20, "bold"),
        ).pack(pady=12)

        # ----------------------------------------------------
        # PROGRESSION
        # ----------------------------------------------------

        self.progress_label = tk.Label(
            root,
            text="",
            font=("Helvetica", 13),
        )
        self.progress_label.pack()

        self.counter_label = tk.Label(
            root,
            text="",
            font=("Helvetica", 11),
        )
        self.counter_label.pack(pady=4)

        self.update_progress()

        # ----------------------------------------------------
        # CAMERA
        # ----------------------------------------------------

        self.camera_label = tk.Label(
            root,
            text="Initialisation de la caméra...",
            width=50,
            height=15,
            bg="black",
            fg="white",
        )
        self.camera_label.pack(pady=12)

        # ----------------------------------------------------
        # ETAT
        # ----------------------------------------------------

        self.status_label = tk.Label(
            root,
            text="Prêt. Place le leader en position initiale.",
            font=("Helvetica", 12),
            wraplength=680,
        )
        self.status_label.pack(pady=8)

        # ----------------------------------------------------
        # BOUTONS
        # ----------------------------------------------------

        buttons = tk.Frame(root)
        buttons.pack(pady=16)

        self.start_button = tk.Button(
            buttons,
            text="Préparer / démarrer",
            command=self.start_demo,
            width=22,
            height=2,
            bg="#d9ead3",
        )
        self.start_button.grid(row=0, column=0, padx=6)

        self.retry_button = tk.Button(
            buttons,
            text="Rejouer la démonstration",
            command=self.retry_demo,
            width=22,
            height=2,
            state="disabled",
        )
        self.retry_button.grid(row=0, column=1, padx=6)

        self.validate_button = tk.Button(
            buttons,
            text="Valider et passer à la suivante",
            command=self.validate_demo,
            width=26,
            height=2,
            bg="#cfe2f3",
            state="disabled",
        )
        self.validate_button.grid(
            row=1,
            column=0,
            columnspan=2,
            pady=10,
        )

        self.root.protocol("WM_DELETE_WINDOW", self.close)

        # Démarrage de la boucle
        self.root.after(0, self.tick)

    # ========================================================
    # PROGRESSION
    # ========================================================

    def update_progress(self):

        total = NUM_EPISODES

        if self.state == "done":
            current = total
        else:
            current = min(self.saved_count + 1, total)

        self.progress_label.config(
            text=f"Démonstration {current} / {total}"
        )

        self.counter_label.config(
            text=(
                f"Démonstrations validées : "
                f"{self.saved_count} / {total}"
            )
        )

    # ========================================================
    # DEMARRAGE D'UNE DEMONSTRATION
    # ========================================================

    def start_demo(self):

        if self.state != "idle":
            return

        if self.saved_count >= NUM_EPISODES:
            return

        self.demo_frames = []
        self.phase_start = time.monotonic()
        self.state = "reset"

        # Nouveau cycle de temporisation
        self.period_waiter.start()

        self.start_button.config(state="disabled")
        self.retry_button.config(state="disabled")
        self.validate_button.config(state="disabled")

        self.status_label.config(
            text=(
                f"Remise en position : {RESET_TIME} secondes. "
                "Le follower suit le leader."
            )
        )

    # ========================================================
    # REJOUER UNE DEMONSTRATION
    # ========================================================

    def retry_demo(self):

        if self.state != "review":
            return

        # Les trames précédentes n'ont pas été ajoutées au dataset.
        self.demo_frames = []

        self.phase_start = time.monotonic()
        self.state = "reset"

        self.period_waiter.start()

        self.start_button.config(state="disabled")
        self.retry_button.config(state="disabled")
        self.validate_button.config(state="disabled")

        self.status_label.config(
            text=(
                "Nouvelle tentative : "
                "remise en position du leader..."
            )
        )

    # ========================================================
    # VALIDER UNE DEMONSTRATION
    # ========================================================

    def validate_demo(self):

        if self.state != "review":
            return

        if len(self.demo_frames) != N_FRAMES:
            messagebox.showerror(
                "Démonstration incomplète",
                f"{len(self.demo_frames)} trames enregistrées "
                f"au lieu de {N_FRAMES}.",
            )
            return

        self.state = "saving"
        self.save_index = 0

        self.start_button.config(state="disabled")
        self.retry_button.config(state="disabled")
        self.validate_button.config(state="disabled")

        self.status_label.config(
            text="Enregistrement de l'épisode dans LeRobot..."
        )

        self.root.after(1, self.commit_next_frame)

    # ========================================================
    # ECRITURE PROGRESSIVE DU DATASET
    # ========================================================

    def commit_next_frame(self):

        if self.closed:
            return

        try:

            if self.save_index < len(self.demo_frames):

                dataset.add_frame(
                    self.demo_frames[self.save_index]
                )

                self.save_index += 1

                self.status_label.config(
                    text=(
                        "Écriture du dataset : "
                        f"{self.save_index}/{N_FRAMES} trames"
                    )
                )

                self.root.after(1, self.commit_next_frame)
                return

            # Toutes les trames sont écrites.
            dataset.save_episode()

            self.saved_count += 1
            self.demo_frames = []

            # Actualisation du compteur après validation
            self.update_progress()

            if self.saved_count >= NUM_EPISODES:

                self.state = "done"
                self.update_progress()

                self.status_label.config(
                    text="Collecte terminée. Finalisation du dataset..."
                )

                self.finalize_dataset()

                self.status_label.config(
                    text="Dataset finalisé avec succès."
                )

                self.start_button.config(state="disabled")
                self.retry_button.config(state="disabled")
                self.validate_button.config(state="disabled")

            else:

                self.state = "idle"

                self.update_progress()

                self.status_label.config(
                    text=(
                        "Épisode validé. Place le leader "
                        "en position initiale pour la suite."
                    )
                )

                self.start_button.config(state="normal")

        except Exception as exc:
            self.handle_error(exc)

    # ========================================================
    # PREPARATION DE LA CAMERA
    # ========================================================

    @staticmethod
    def prepare_camera(image):

        image = cv2.rotate(
            image,
            cv2.ROTATE_180,
        )

        image = cv2.resize(
            image,
            (320, 240),
            interpolation=cv2.INTER_AREA,
        )

        return image

    def display_camera(self, image):

        # PIL attend une image RGB.
        # On conserve l'image originale pour le dataset.
        pil_image = Image.fromarray(image)

        self.photo = ImageTk.PhotoImage(pil_image)

        self.camera_label.config(
            image=self.photo,
            width=320,
            height=240,
            text="",
        )

    # ========================================================
    # BOUCLE PRINCIPALE
    # ========================================================

    def tick(self):

        if self.closed:
            return

        tick_start = time.monotonic()

        try:

            # ------------------------------------------------
            # Observation du follower et récupération caméra
            # ------------------------------------------------

            observation = follower.get_observation()

            image = self.prepare_camera(
                observation["cam_1"]
            )

            observation["cam_1"] = image

            # ------------------------------------------------
            # Téléopération leader -> follower
            # ------------------------------------------------

            active = self.state in ("reset", "recording")

            if active:

                action = leader.get_observation()
                follower.send_action(action)

            else:
                action = None

            # ------------------------------------------------
            # Affichage caméra permanent
            # ------------------------------------------------

            self.display_camera(image)

            now = time.monotonic()

            # ================================================
            # PHASE 1 : REMISE EN POSITION
            # ================================================

            if self.state == "reset":

                elapsed = now - self.phase_start

                remaining = max(
                    0,
                    RESET_TIME - int(elapsed),
                )

                self.status_label.config(
                    text=(
                        f"Remise en position : "
                        f"{remaining} s restantes"
                    )
                )

                if elapsed >= RESET_TIME:

                    self.state = "recording"
                    self.phase_start = time.monotonic()
                    self.demo_frames = []

                    # Redémarrage du waiter au début
                    # de la phase d'enregistrement.
                    self.period_waiter.start()

                    self.status_label.config(
                        text="Enregistrement de la démonstration..."
                    )

            # ================================================
            # PHASE 2 : ENREGISTREMENT
            # ================================================

            elif self.state == "recording":

                observation_frame = build_dataset_frame(
                    dataset.features,
                    observation,
                    prefix=OBS_STR,
                )

                action_frame = build_dataset_frame(
                    dataset.features,
                    action,
                    prefix=ACTION,
                )

                frame = {
                    **observation_frame,
                    **action_frame,
                    "task": TASK,
                }

                # Copie profonde : les tableaux restent stables.
                self.demo_frames.append(
                    copy.deepcopy(frame)
                )

                elapsed = time.monotonic() - self.phase_start

                remaining = max(
                    0.0,
                    EPISODE_TIME - elapsed,
                )

                self.status_label.config(
                    text=(
                        f"Enregistrement : "
                        f"{len(self.demo_frames)}/{N_FRAMES} trames "
                        f"— {remaining:.1f} s restantes"
                    )
                )

                if len(self.demo_frames) >= N_FRAMES:

                    self.state = "review"

                    self.status_label.config(
                        text=(
                            "Démonstration terminée. "
                            "Vérifie le résultat, puis valide "
                            "ou rejoue la démonstration."
                        )
                    )

                    self.retry_button.config(state="normal")
                    self.validate_button.config(state="normal")

        except Exception as exc:

            self.handle_error(exc)
            return

        # ----------------------------------------------------
        # CADENCEMENT
        # ----------------------------------------------------

        if self.state in ("reset", "recording"):

            # PeriodWaiterExact assure la cadence de la
            # téléopération et de l'acquisition.
            self.period_waiter.wait()

            # Le waiter ayant assuré l'attente, on programme
            # immédiatement le prochain passage.
            self.root.after(1, self.tick)

        else:

            # Hors acquisition : cadence d'affichage classique.
            elapsed_tick = time.monotonic() - tick_start

            delay_ms = max(
                1,
                int((FRAME_PERIOD - elapsed_tick) * 1000),
            )

            self.root.after(delay_ms, self.tick)

    # ========================================================
    # FINALISATION
    # ========================================================

    def finalize_dataset(self):

        if self.dataset_finalized:
            return

        dataset.finalize()
        self.dataset_finalized = True

    # ========================================================
    # GESTION DES ERREURS
    # ========================================================

    def handle_error(self, exc):

        self.state = "error"

        self.start_button.config(state="disabled")
        self.retry_button.config(state="disabled")
        self.validate_button.config(state="disabled")

        details = traceback.format_exc()

        self.status_label.config(
            text=f"Erreur : {exc}"
        )

        print(details)

        messagebox.showerror(
            "Erreur pendant l'enregistrement",
            f"{exc}\n\nConsulte le terminal pour le détail.",
        )

    # ========================================================
    # FERMETURE
    # ========================================================

    def close(self):

        if self.state == "saving":

            messagebox.showinfo(
                "Enregistrement en cours",
                "Attends la fin de l'écriture de l'épisode.",
            )
            return

        if not messagebox.askyesno(
            "Quitter",
            "Quitter l'interface et finaliser le dataset ?",
        ):
            return

        try:

            self.finalize_dataset()

        except Exception as exc:

            messagebox.showerror(
                "Erreur de finalisation",
                str(exc),
            )
            return

        self.closed = True
        self.root.destroy()


# ============================================================
# LANCEMENT
# ============================================================

if NUM_EPISODES <= 0:
    raise ValueError("NUM_EPISODES doit être strictement positif.")

root = tk.Tk()
app = DatasetGUI(root)
root.mainloop()
