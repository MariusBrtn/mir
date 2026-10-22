"""
Enregistre les tutos vidéo du site internet de MIR : la vraie application MIR, pilotée par un scénario.

Un faux curseur clique les boutons, glisse les modules, remplit les fenêtres ; chaque image est capturée
(voir enregistreur.py), puis ffmpeg en fait une vidéo MP4 dans site/videos. Quand l'interface change,
il suffit de relancer le script pour mettre les vidéos à jour.

Les robots sont pris dans un dossier temporaire qui imite une installation neuve (bras_4ddl_cam_V2 et test_mobile,
comme l'installateur) : le dossier robots/ n'est pas modifié.

Lancer depuis le dossier mir :
    uv run python site/tutos/enregistrer_tuto.py              # toutes les vidéos
    uv run python site/tutos/enregistrer_tuto.py decouverte   # seulement celles nommées
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")       # pas de fenêtre à l'écran pendant l'enregistrement

from PySide6.QtCore import QPoint, Qt                         # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enregistreur import FPS, DialoguesFilmes, Enregistreur    # noqa: E402

import mir_robot.mir_robot as mir_robot_module                 # noqa: E402
import mir_robot_editor.main_viewmodel as main_viewmodel_module  # noqa: E402
import mir_robot_editor.scripts.scripts_view as scripts_view_module  # noqa: E402
from mir_robot_editor import habillage                         # noqa: E402
from mir_robot_editor.main_view import STEP_COLLECT, STEP_FLOW, STEP_PILOT, STEP_ROBOT, STEP_TRAIN, MainView  # noqa: E402
from mir_robot_editor.main_viewmodel import MainViewModel      # noqa: E402
from mir_robot_editor.robot_model.structure_editor_view import StructureEditorView  # noqa: E402
from mir_utils.ui.theme import apply_theme                     # noqa: E402

TAILLE = (1440, 860)
SORTIE = Path(__file__).resolve().parent.parent / "videos"
ROBOTS_SOURCE = Path(mir_robot_module.DOSSIER_ROBOTS)
ROBOTS_INSTALLES = ("bras_4ddl_cam_V2", "test_mobile")     # robots d'une installation neuve (installateur)
NOM_BRAS = "bras_4ddl_pince"

SCRIPT_ANALYSE = '''"""
Analyse d'un échelon : temps de réponse à 5 %
"""
from pathlib import Path
import matplotlib.pyplot as plt
from mir_robot.essai import Essai

# le dernier essai enregistré dans Piloter -> Essais
fichier = sorted(Path("../essais").glob("*.npz"))[-1]
essai = Essai.charger(fichier)
t, consigne, position = essai.t, essai.consigne, essai.mesure

# instant de l'échelon, positions initiale et finale
t0 = t[consigne != consigne[0]][0]
initiale, finale = position[0], position[-1]

# temps de réponse à 5 % : après, la position reste dans la bande finale ± 5 %
bande = 0.05 * abs(finale - initiale)
hors_bande = abs(position - finale) > bande
t5 = t[hors_bande][-1] - t0
print(f"Temps de réponse à 5 % : {t5:.3f} s")

plt.plot(t, consigne, "--", label="Consigne")
plt.plot(t, position, label="Position")
plt.axhspan(finale - bande, finale + bande, alpha=0.2, label="Bande ± 5 %")
plt.axvline(t0 + t5, color="k", linewidth=0.8)
plt.xlabel("Temps (s)")
plt.ylabel("Position (°)")
plt.legend()
plt.grid()
plt.show()
'''


class Tuto:
    """La fenêtre principale de MIR, partagée par les scénarios (qui s'enchaînent comme pour un élève)."""

    def __init__(self, app: QApplication):
        self.app = app
        self.dialogues = DialoguesFilmes()
        self.vm = MainViewModel(self.dialogues)
        self.fenetre = MainView(self.vm)
        self.dialogues.setParent(self.fenetre)
        self.fenetre.resize(*TAILLE)
        self.fenetre.menuBar().hide()      # sur Mac, la barre de menus est en haut de l'écran, pas dans la fenêtre
        self.fenetre.show()
        for _ in range(5):
            app.processEvents()
        # « Nouveau script… » de Scripts ouvre sa fenêtre de saisie lui-même
        scripts_view_module.ask_text = lambda parent, title, label, default="", **kw: \
            self.e.filmer_saisie(title, label, default, **kw)
        self.e: Enregistreur | None = None

    def filmer(self, nom: str, scenario, video: bool = True) -> None:
        """Joue le scénario ; video=False : seulement pour amener l'appli dans l'état attendu par la suite."""
        with tempfile.TemporaryDirectory() as dossier:
            curseur = self.e.curseur if self.e is not None else None
            self.e = Enregistreur(self.app, self.fenetre, Path(dossier))
            if curseur is not None:
                self.e.curseur = curseur
            self.dialogues.e = self.e
            scenario(self, self.e)
            if self.e.reponses:
                raise RuntimeError(f"réponses prévues non utilisées : {self.e.reponses}")
            if not video:
                return
            video = SORTIE / f"{nom}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", f"{dossier}/%05d.png",
                            "-vf", "scale=1280:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
                            "-movflags", "+faststart", str(video)], check=True)
            # image d'attente : la dernière image de la vidéo
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"{dossier}/{self.e.n_images - 1:05d}.png",
                            "-vf", "scale=1280:-2", "-q:v", "4", str(SORTIE / f"{nom}.jpg")], check=True)
        print(f"{video} : {self.e.n_images} images, {self.e.n_images / FPS:.1f} s", flush=True)

    # ------------------------------------------------------------------ éléments de la fenêtre
    def carte(self, action):
        return next(c for c in self.fenetre._cards if c._action is action)

    def etape(self, e: Enregistreur, index: int) -> None:
        e.cliquer(self.fenetre._steps._boutons[index], 0.6)
        self.fenetre._steps.setCurrentRow(index)
        e.attendre(0.5)

    def modalite(self, e: Enregistreur, index: int) -> None:
        carte = self.fenetre._modalites[index]
        e.cliquer(carte, 0.6)
        carte.on_click()
        e.attendre(0.4)


# ---------------------------------------------------------------------- scénarios
def decouverte(t: Tuto, e: Enregistreur) -> None:
    """Tour de l'application avec le bras fourni : les étapes et les façons de piloter le robot."""
    f = t.fenetre
    e.legende = "MIR s'ouvre sur l'étape « Configurer le robot »"
    e.attendre(1.5)
    e.legende = "Ouvrir un des robots fournis"
    e.reponses = [("Ouvrir un robot", "bras_4ddl_cam_V2")]
    e.cliquer(t.carte(f._open_action))
    f._open_action.trigger()
    e.legende = "Concevoir : choisir les modules et leurs branchements"
    e.deplacer(e._vers_image(t.carte(f._structure_action)), 0.8)
    e.attendre(1.8)
    e.legende = "Construire : monter le vrai robot, guidé module par module"
    e.deplacer(e._vers_image(f._card_construire), 0.8)
    e.attendre(1.8)
    e.legende = "Piloter : faire bouger le robot, réel ou simulé"
    t.etape(e, STEP_PILOT)
    e.attendre(1.0)
    e.deplacer(e._vers_image(f._btn_sim), 0.8)
    e.legende = "Sans robot branché, MIR utilise le robot simulé"
    e.attendre(2.0)
    for index, legende in ((0, "Essais : solliciter un moteur et tracer sa réponse"),
                           (1, "Téléopération : piloter au clavier, avec un bras leader…"),
                           (2, "Scripts : programmer le robot en Python"),
                           (3, "IA : un modèle entraîné pilote le robot")):
        e.legende = legende
        t.modalite(e, index)
        e.attendre(2.0)
    e.legende = "Collecter des données : enregistrer des démonstrations"
    t.etape(e, STEP_COLLECT)
    e.attendre(2.2)
    e.legende = "Entraîner un modèle sur ces démonstrations"
    t.etape(e, STEP_TRAIN)
    e.attendre(2.2)
    e.legende = "MIR Flow : enchaîner des tâches, avec un LLM"
    t.etape(e, STEP_FLOW)
    e.attendre(2.2)
    e.legende = ""
    t.etape(e, STEP_ROBOT)
    e.attendre(0.8)
    t.vm.close_robot()        # le tuto suivant part de zéro
    e.attendre(0.3)


def bras_structure(t: Tuto, e: Enregistreur) -> None:
    """Nouveau robot : concevoir la structure du bras 4 ddl avec pince, puis l'enregistrer."""
    f = t.fenetre
    e.legende = "Aucun robot ouvert : on en conçoit un nouveau"
    e.attendre(1.2)
    e.legende = "Concevoir la structure"
    e.cliquer(t.carte(f._structure_action))

    def editeur(vm):
        vue = StructureEditorView(None, vm)
        vue.resize(1200, 740)
        e.ouvrir(vue)
        e.vue = vue
        e.attendre(0.3)
        e.legende = "Le socle est déjà là : c'est le module de départ"
        e.attendre(1.8)
        etapes = [   # (élément de la liste, pastille, branché par, légende)
            ("new:mir_servo", "socle.dessus", "rotor", "Glisser un servo sur le dessus du socle"),
            ("new:mir_servo", "{}.stator", "rotor", "Un deuxième servo sur le premier"),
            ("block:mir_jonction", "{}.stator", "face_a", "Une jonction pour former le bras"),
            ("new:mir_servo", "{}.face_b", "stator", "Le troisième servo, au bout de la jonction"),
            ("new:mir_servo", "{}.rotor", "stator", "Le quatrième servo"),
            ("new:mir_pince", "{}.rotor", "stator", "Et la pince au bout du bras"),
        ]
        precedent = ""
        for i, (cle, pastille, connecteur, legende) in enumerate(etapes):
            e.legende = legende
            module = e.glisser(cle, pastille.format(precedent), 1.0 if i < 2 else 0.8)
            if vue._view_model.modules[module]["connector"] != connecteur:
                e.legende = "Touche R : le brancher par son autre face"
                e.brancher_par(module, connecteur, 0.9)
            e.attendre(0.4)
            if i in (2, 5):
                e.legende = "« Recadrer » pour revoir tout le robot"
                e.recadrer()
            precedent = module
        e.legende = "Le bras : 4 articulations et une pince"
        vue._view_model._select(None)
        e.tourner_camera(360, 4.0)
        e.legende = "Valider la structure"
        e.reponses = [("Configuration modifiée", True), ("Enregistrer le robot", NOM_BRAS)]
        e.valider_structure()
        e.fenetres.remove(vue)
        e.vue = None
        e.legende = "Enregistrer le robot sous un nom"

    t.vm.execute_structure_editor(editeur)
    e.legende = f"Le robot « {NOM_BRAS} » est prêt, en simulation"
    e.attendre(2.5)


def bras_echelon(t: Tuto, e: Enregistreur) -> None:
    """Piloter → Essais, en simulé : deux échelons sur joint_2 (réglage par défaut, puis sans D), courbes superposées."""
    f = t.fenetre
    essais = f.essais_view
    e.legende = "Piloter : le bras simulé est prêt"
    t.etape(e, STEP_PILOT)
    t.modalite(e, 0)
    e.attendre(0.8)
    e.legende = "Choisir l'articulation et la sollicitation"
    e.choisir(essais.cb_actionneur, "joint_2.position")
    e.choisir(essais.cb_sollicitation, "Échelon")
    e.legende = "Échelon de 0 à 45°, au bout de 0,5 s"
    e.saisir(essais._param_widgets["finale"], 45.0)
    e.saisir(essais._param_widgets["duree"], 2.0)
    e.legende = "Enregistrer la position et la vitesse"
    for nom, box in essais._grandeur_boxes.items():
        if box.isChecked() and not nom.endswith((".position", ".velocity")):
            e.cliquer(box, 0.35, box.rect().topLeft() + box.rect().center() / 4)
            box.setChecked(False)
    e.legende = "Lancer l'essai"
    e.appuyer(essais.btn_lancer)
    e.legende = "Le servo rejoint la consigne"
    e.attendre_que(lambda: not essais._view_model.is_running(), apres_s=1.5)
    e.legende = "Même échelon sans terme dérivé : D = 0"
    e.saisir(essais._reglage_widgets["D"], 0)
    e.appuyer(essais.btn_lancer)
    e.attendre_que(lambda: not essais._view_model.is_running(), apres_s=1.0)
    e.legende = "Les deux essais sont superposés : sans D, la réponse dépasse la consigne"
    e.deplacer(e._vers_image(essais._plots_scroll), 0.8)
    e.attendre(2.5)
    e.legende = "Enregistrer l'essai pour l'analyser"
    e.reponses = [("Enregistrer l'essai", None)]
    e.cliquer(e.bouton_action(essais, essais._action_enregistrer), 0.6)
    essais._action_enregistrer.trigger()
    e.attendre(1.5)


def bras_analyse(t: Tuto, e: Enregistreur) -> None:
    """Piloter → Scripts : un script relit l'essai enregistré et calcule le temps de réponse à 5 %."""
    scripts = t.fenetre.scripts_view
    e.legende = "Scripts : analyser l'essai enregistré en Python"
    t.modalite(e, 2)
    e.attendre(0.8)
    e.reponses = [("Nouveau script", "Analyse echelon")]
    e.legende = "Nouveau script"
    e.appuyer(scripts.btn_nouveau)
    editeur = scripts._editeur_courant()
    e.legende = "Écrire l'analyse"
    e.cliquer(editeur, 0.5)
    editeur.clear()
    e.taper_code(editeur, SCRIPT_ANALYSE)
    e.attendre(1.0)
    e.legende = "Lancer le script"
    e.appuyer(scripts.btn_lancer)
    e.attendre_que(lambda: not scripts._view_model.is_running(), max_s=60, apres_s=0.5)
    e.legende = "Le temps de réponse s'affiche dans la console, la courbe à droite"
    e.deplacer(e._vers_image(scripts.console), 0.8)
    e.attendre(2.0)
    e.deplacer(e._vers_image(scripts.figures), 0.8)
    e.attendre(2.5)


def mir_en_action(t: Tuto, e: Enregistreur) -> None:
    """Présentation : ce que font les exemples fournis (démonstrations, modèle ACT, robot mobile, MIR Flow)."""
    f, vm = t.fenetre, t.vm
    e.curseur_visible = False
    e.filme = False
    e.reponses = [("Ouvrir un robot", "bras_4ddl_cam_V2")]
    f._open_action.trigger()
    e.filme = True
    e.carte_titre("MIR", "Modular Intelligent Robot : un robot modulaire, réel ou simulé", 2.0, fondu_entree=False)

    # un robot assemblé à partir de modules
    e.legende = "Un bras assemblé à partir de modules : servos, jonction, pince, caméra"

    def editeur(vue_model):
        vue = StructureEditorView(None, vue_model)
        vue.resize(1200, 740)
        e.ouvrir(vue)
        e.vue = vue
        vue_model._select(None)
        e.tourner_camera(300, 4.0)
        e.fenetres.remove(vue)
        e.vue = None
        vue_model.cancel()

    vm.execute_structure_editor(editeur)

    # des démonstrations
    collecte = f.collecte_view
    f._steps.setCurrentRow(STEP_COLLECT)
    collecte.cb_dataset.setCurrentIndex(collecte.cb_dataset.findText("ramassage_sim_320", Qt.MatchFlag.MatchStartsWith))
    e.attendre(0.3)
    collecte.list_episodes.setCurrentRow(3)
    collecte._revoir()
    e.legende = "Un opérateur montre la tâche : MIR enregistre 50 démonstrations"
    collecte.episode_view._lecture()
    e.attendre_que(lambda: not collecte.episode_view._timer.isActive(), max_s=6)
    collecte._fermer_revue()

    # un modèle entraîné pilote le robot
    f._steps.setCurrentRow(STEP_PILOT)
    f._cb_scene.setCurrentIndex(f._cb_scene.findText("Ramassage", Qt.MatchFlag.MatchContains))
    f._on_scene_choisie(f._cb_scene.currentIndex())
    f._modalites[3].on_click()
    ia = f.ia_view
    for i in range(ia.list_modeles.count()):
        if ia.list_modeles.item(i).text().startswith("act_ramassage"):
            ia.list_modeles.setCurrentRow(i)
    ia.sp_duree.setValue(9.0)
    e.attendre(0.3)
    e.legende = "Un modèle ACT, appris sur ces démonstrations, ramasse le dé"
    ia.btn_demarrer.click()
    e.attendre_que(lambda: not ia._view_model.is_running(), max_s=15, apres_s=0.5)

    # un robot mobile et MIR Flow
    e.carte_titre("Le même logiciel, un autre robot", "Robot mobile à quatre roues et lidar", 1.5)
    e.filme = False
    e.reponses = [("Ouvrir un robot", "test_mobile")]
    f._open_action.trigger()
    f._steps.setCurrentRow(STEP_FLOW)
    f._cb_scene.setCurrentIndex(f._cb_scene.findText("Rue", Qt.MatchFlag.MatchContains))
    f._on_scene_choisie(f._cb_scene.currentIndex())
    e.attendre(0.5)
    e.filme = True
    flow = f.flow_view
    e.legende = "Appris par renforcement : il explore la rue sans heurter les décombres"
    flow.btn_lancer.click()
    coin = QPoint(TAILLE[0] - 560, 110)
    e.attendre_que(lambda: e.suivre_fenetres(coin), max_s=7)
    e.legende = "MIR Flow : il cartographie la rue avec son lidar, en même temps"
    e.attendre_que(lambda: e.suivre_fenetres(coin), max_s=8)
    flow._view_model.arreter()
    e.attendre_que(lambda: not flow._view_model.is_running(), max_s=5)
    for fenetre in list(e.coins):
        e.fenetres.remove(fenetre)
    e.coins.clear()
    e.legende = ""
    e.carte_titre("MIR", "Concevoir, piloter, collecter, entraîner : github.com/MariusBrtn/mir", 2.5,
                  fondu_sortie=False)


SCENARIOS = {
    "decouverte": decouverte,
    "bras-4ddl-structure": bras_structure,
    "bras-4ddl-echelon": bras_echelon,
    "bras-4ddl-analyse": bras_analyse,
    "mir-en-action": mir_en_action,
}
# scénarios qui utilisent les exemples complets (datasets, modèles) : copie de tout le dossier robots/
AVEC_EXEMPLES = {"mir-en-action"}


def main() -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg est nécessaire (brew install ffmpeg).")
    demandes = sys.argv[1:] or list(SCENARIOS)
    inconnus = [n for n in demandes if n not in SCENARIOS]
    if inconnus:
        sys.exit(f"scénarios inconnus : {inconnus} ; possibles : {list(SCENARIOS)}")
    SORTIE.mkdir(exist_ok=True)
    exemples = [n for n in demandes if n in AVEC_EXEMPLES]
    if exemples and len(exemples) != len(demandes):
        sys.exit(f"{exemples} utilisent tous les exemples : à enregistrer à part")
    with tempfile.TemporaryDirectory() as robots:
        if exemples:
            shutil.copytree(ROBOTS_SOURCE, robots, dirs_exist_ok=True)
        else:
            # installation neuve : les robots fournis, avec leur seule configuration
            for robot in ROBOTS_INSTALLES:
                (Path(robots) / robot).mkdir()
                shutil.copy(ROBOTS_SOURCE / robot / "robot.json", Path(robots) / robot)
        mir_robot_module.DOSSIER_ROBOTS = main_viewmodel_module.DOSSIER_ROBOTS = Path(robots)
        app = QApplication.instance() or QApplication(sys.argv)
        apply_theme(app)
        habillage.installer()
        tuto = Tuto(app)
        # les scénarios s'enchaînent : chacun part de l'état laissé par les précédents
        for nom, scenario in SCENARIOS.items():
            if exemples and nom not in exemples:
                continue
            if nom in demandes:
                tuto.filmer(nom, scenario)
            elif any(n in demandes for n in list(SCENARIOS)[list(SCENARIOS).index(nom) + 1:]):
                tuto.filmer(nom, scenario, video=False)
        os._exit(0)       # pas de fermeture de la fenêtre (elle demanderait d'enregistrer)


if __name__ == "__main__":
    main()
