"""
Captures d'écran du site internet de MIR : la vraie application MIR, amenée dans l'état voulu par un scénario
(comme les tutos vidéo, voir enregistrer_tuto.py), puis photographiée. Les images vont dans site/images/appli.

Les robots fournis sont pris avec tous leurs exemples (démonstrations, modèles, flows), dans un dossier temporaire :
le dossier robots/ n'est pas modifié.

Lancer depuis le dossier mir :
    uv run python site/tutos/captures.py                  # toutes les captures
    uv run python site/tutos/captures.py essai-echelon    # seulement celles nommées
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enregistrer_tuto as tuto_module                          # noqa: E402  (fixe aussi QT_QPA_PLATFORM)
from enregistrer_tuto import ROBOTS_SOURCE, Tuto                # noqa: E402
from enregistreur import Enregistreur                           # noqa: E402

from PySide6.QtCore import QPoint, Qt                           # noqa: E402
from PySide6.QtGui import QImage                                # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget             # noqa: E402

import mir_robot.mir_robot as mir_robot_module                  # noqa: E402
import mir_robot_editor.main_viewmodel as main_viewmodel_module  # noqa: E402
from mir_robot_editor import habillage                          # noqa: E402
from mir_robot_editor.main_view import STEP_FLOW, STEP_PILOT     # noqa: E402
from mir_robot_editor.robot_model.structure_editor_view import StructureEditorView  # noqa: E402
from mir_utils.ui.theme import apply_theme                      # noqa: E402

SORTIE = Path(__file__).resolve().parent.parent / "images" / "appli"


def photo(e: Enregistreur, nom: str, widget: QWidget | None = None) -> None:
    """Photographie la fenêtre principale (avec les fenêtres ouvertes par-dessus), ou un seul widget."""
    e.app.processEvents()
    fichier = SORTIE / f"{nom}.png"
    if widget is not None:
        widget.grab().save(str(fichier), "PNG")
    else:
        e.filme = True
        e.image()
        e.filme = False
        QImage(str(e.dossier / f"{e.n_images - 1:05d}.png")).save(str(fichier), "PNG")   # PNG compressé
    print(fichier, flush=True)


def pendant(e: Enregistreur, secondes: float) -> None:
    """Laisse tourner l'appli en temps réel (le robot bouge)."""
    debut = time.perf_counter()
    e.attendre_que(lambda: time.perf_counter() - debut > secondes)


def cadrer(viewport, distance: float, azimut: float, elevation: float, vise=None) -> None:
    """Place la caméra de la vue 3D ; vise : point regardé (par défaut le premier corps, la base du robot)."""
    camera = viewport._camera
    camera.lookat[:] = viewport._data.xpos[1] if vise is None else vise
    camera.distance, camera.azimuth, camera.elevation = distance, azimut, elevation
    viewport._camera_moved_by_user = True
    viewport.update()


def ouvrir_robot(t: Tuto, e: Enregistreur, nom: str) -> None:
    e.reponses = [("Ouvrir un robot", nom)]
    t.fenetre._open_action.trigger()


def choisir_scene(t: Tuto, debut_du_nom: str) -> None:
    f = t.fenetre
    f._cb_scene.setCurrentIndex(f._cb_scene.findText(debut_du_nom, Qt.MatchFlag.MatchContains))
    f._on_scene_choisie(f._cb_scene.currentIndex())


def piloter_par_ia(t: Tuto, e: Enregistreur, modele: str, duree_s: float) -> None:
    f = t.fenetre
    f._steps.setCurrentRow(STEP_PILOT)
    f._modalites[3].on_click()
    ia = f.ia_view
    for i in range(ia.list_modeles.count()):
        if ia.list_modeles.item(i).text().startswith(modele):
            ia.list_modeles.setCurrentRow(i)
    ia.sp_duree.setValue(duree_s)
    e.attendre(0.3)
    ia.btn_demarrer.click()


def arreter_ia(t: Tuto, e: Enregistreur) -> None:
    ia = t.fenetre.ia_view
    if ia._view_model.is_running():
        ia._view_model.arreter()
    e.attendre_que(lambda: not ia._view_model.is_running(), max_s=15)


# ---------------------------------------------------------------------- captures
def structure(t: Tuto, e: Enregistreur) -> None:
    """L'éditeur de structure, avec le bras fourni : servos, jonction, pince, caméra."""
    ouvrir_robot(t, e, "bras_4ddl_cam_V2")

    def editeur(vue_model):
        vue = StructureEditorView(None, vue_model)
        vue.resize(1300, 800)
        e.ouvrir(vue)
        e.vue = vue
        vue_model._select(None)
        e.tourner_camera(35, 0.5)
        photo(e, "structure", vue)
        e.fenetres.remove(vue)
        e.vue = None
        vue_model.cancel()

    t.vm.execute_structure_editor(editeur)


def essai_echelon(t: Tuto, e: Enregistreur) -> None:
    """Piloter → Essais : deux échelons sur joint_2 (réglage par défaut, puis D = 0), courbes superposées."""
    ouvrir_robot(t, e, "bras_4ddl_cam_V2")
    f = t.fenetre
    essais = f.essais_view
    f._steps.setCurrentRow(STEP_PILOT)
    f._modalites[0].on_click()
    e.attendre(0.3)
    essais.cb_actionneur.setCurrentIndex(essais.cb_actionneur.findText("joint_2.position", Qt.MatchFlag.MatchStartsWith))
    essais.cb_sollicitation.setCurrentIndex(essais.cb_sollicitation.findText("Échelon", Qt.MatchFlag.MatchStartsWith))
    e.attendre(0.2)
    essais._param_widgets["finale"].setValue(45.0)
    essais._param_widgets["duree"].setValue(2.0)
    for nom, box in essais._grandeur_boxes.items():
        if box.isChecked() and not nom.endswith((".position", ".velocity")):
            box.setChecked(False)
    for d in (None, 0):
        if d is not None:
            essais._reglage_widgets["D"].setValue(d)
        essais.btn_lancer.click()
        e.attendre(0.1)
        e.attendre_que(lambda: not essais._view_model.is_running(), apres_s=0.5)
    for i in range(essais.list_essais.count()):
        essais.list_essais.item(i).setCheckState(Qt.CheckState.Checked)
    essais.list_essais.setCurrentRow(0)      # le réglage par défaut en trait épais, D = 0 par-dessus
    e.attendre(0.3)
    photo(e, "essai-echelon")


def imitation(t: Tuto, e: Enregistreur) -> None:
    """Piloter → IA : le modèle ACT, appris sur 50 démonstrations, ramasse le dé."""
    ouvrir_robot(t, e, "bras_4ddl_cam_V2")
    choisir_scene(t, "Ramassage")
    piloter_par_ia(t, e, "act_ramassage", 9.0)
    cadrer(t.fenetre.ia_view._viewport, 0.75, -150, -28, vise=(0.15, 0.0, 0.06))
    pendant(e, float(os.environ.get("INSTANT_IMITATION", 8.0)))
    photo(e, "imitation")
    arreter_ia(t, e)


def renforcement(t: Tuto, e: Enregistreur) -> None:
    """Piloter → IA : le robot mobile, appris par renforcement, explore la rue sans heurter les décombres."""
    ouvrir_robot(t, e, "test_mobile")
    choisir_scene(t, "Rue")
    piloter_par_ia(t, e, "errance_ppo", 0)
    pendant(e, float(os.environ.get("INSTANT_RENFORCEMENT", 8.0)))
    cadrer(t.fenetre.ia_view._viewport, 3.0, -120, -45)
    e.attendre(0.2)
    photo(e, "renforcement")
    arreter_ia(t, e)


def mir_flow(t: Tuto, e: Enregistreur) -> None:
    """MIR Flow : le graphe du robot mobile (errance, lidar, odométrie, recalage, carte) et la carte qu'il dessine."""
    ouvrir_robot(t, e, "test_mobile")
    f = t.fenetre
    f._steps.setCurrentRow(STEP_FLOW)
    choisir_scene(t, "Rue")
    e.attendre(0.5)
    flow = f.flow_view
    flow.btn_lancer.click()
    largeur, hauteur = 420, 380
    coin = QPoint(f.width() - largeur - 10, f.height() - hauteur - 10)
    debut = time.perf_counter()
    e.attendre_que(lambda: e.suivre_fenetres(coin) or
                   time.perf_counter() - debut > float(os.environ.get("INSTANT_FLOW", 14.0)))
    for fenetre in e.coins:
        fenetre.resize(largeur, hauteur)
    cadrer(flow._viewport, 3.0, -120, -45)
    e.attendre(0.3)
    photo(e, "mir-flow")
    flow._view_model.arreter()
    e.attendre_que(lambda: not flow._view_model.is_running(), max_s=5)
    for fenetre in list(e.coins):
        e.fermer(fenetre)


CAPTURES = {
    "structure": structure,
    "essai-echelon": essai_echelon,
    "imitation": imitation,
    "renforcement": renforcement,
    "mir-flow": mir_flow,
}


def main() -> None:
    demandes = sys.argv[1:] or list(CAPTURES)
    inconnus = [n for n in demandes if n not in CAPTURES]
    if inconnus:
        sys.exit(f"captures inconnues : {inconnus} ; possibles : {list(CAPTURES)}")
    SORTIE.mkdir(parents=True, exist_ok=True)
    if len(demandes) > 1:
        # une appli neuve par capture : changer de robot laisse des traces du précédent dans certaines vues
        for nom in demandes:
            subprocess.run([sys.executable, __file__, nom], check=True)
        return
    with tempfile.TemporaryDirectory() as robots:
        for robot in ("bras_4ddl_cam_V2", "test_mobile"):
            shutil.copytree(ROBOTS_SOURCE / robot, Path(robots) / robot)
        mir_robot_module.DOSSIER_ROBOTS = main_viewmodel_module.DOSSIER_ROBOTS = Path(robots)
        app = QApplication.instance() or QApplication(sys.argv)
        apply_theme(app)
        habillage.installer()
        t = Tuto(app)
        with tempfile.TemporaryDirectory() as images:
            t.e = Enregistreur(app, t.fenetre, Path(images))
            t.e.curseur_visible = False
            t.e.filme = False
            t.dialogues.e = t.e
            CAPTURES[demandes[0]](t, t.e)
            if t.e.reponses:
                raise RuntimeError(f"réponses prévues non utilisées : {t.e.reponses}")
        shutil.rmtree(robots, ignore_errors=True)    # os._exit saute le nettoyage du dossier temporaire
        os._exit(0)       # pas de fermeture de la fenêtre (elle demanderait d'enregistrer)


if __name__ == "__main__":
    main()
