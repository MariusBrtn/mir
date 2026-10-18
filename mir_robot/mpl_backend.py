"""
Backend matplotlib des scripts lancés depuis MIR : les figures s'affichent dans la zone « Figures » de l'application
au lieu d'ouvrir des fenêtres. Le script utilise matplotlib normalement :
    plt.plot(t, x); plt.show()          -> figure affichée (show ne bloque pas)
    plt.pause(0.1)                      -> figure mise à jour pendant une boucle
À la fin du script, les figures pas encore affichées (ou modifiées depuis) le sont automatiquement.
Une figure est redessinée au plus 10 fois par seconde, et moins souvent si elle est longue à dessiner (le dessin prend
au plus ~20 % du temps) : dans une boucle rapide, les plt.show() / plt.pause() en trop ne coûtent rien.
Choisi par l'application avec MPLBACKEND=module://mir_robot.mpl_backend.
"""
from __future__ import annotations
import atexit
import os
import time
from matplotlib import rcParams
from matplotlib._pylab_helpers import Gcf
from matplotlib.backend_bases import FigureManagerBase, _Backend
from matplotlib.backends.backend_agg import FigureCanvasAgg

TAILLE_ENV = "MIR_FIGURE_TAILLE"        # « largeur,hauteur » en pixels de la zone Figures
DPI_ENV = "MIR_FIGURE_DPI"              # résolution : écrans haute définition (Retina) compris
PERIODE_MIN = 0.1                       # s entre deux affichages d'une même figure
PART_DESSIN = 0.2                       # part du temps du script consacrée au dessin d'une figure, au plus

# figures à la taille de la zone d'affichage (l'élève peut toujours choisir figsize)
if os.environ.get(TAILLE_ENV):
    largeur, hauteur = (int(v) for v in os.environ[TAILLE_ENV].split(","))
    rcParams["figure.figsize"] = (max(largeur, 200) / 100, max(hauteur, 150) / 100)
rcParams["figure.dpi"] = float(os.environ.get(DPI_ENV, 100))


def _envoyer(canvas: FigureCanvasAgg):
    from mir_robot.script import robot
    figure = canvas.figure
    image = canvas.buffer_rgba()
    titre = figure.get_label() or f"Figure {figure.number}"
    robot._appel("figure", figure.number, titre, image.shape[1], image.shape[0], bytes(image))


class FigureManagerMir(FigureManagerBase):
    def show(self):
        self.canvas.draw_idle()


class FigureCanvasMir(FigureCanvasAgg):
    manager_class = FigureManagerMir
    _dernier_envoi = 0.0
    _duree_dessin = 0.0

    def draw_idle(self, *args, **kwargs):
        """Dessin demandé par plt.show() / plt.pause() : seulement si la figure a changé, et pas trop souvent."""
        attente = max(PERIODE_MIN, self._duree_dessin / PART_DESSIN)
        if self.figure.stale and time.perf_counter() - self._dernier_envoi >= attente:
            self.draw()

    def start_event_loop(self, timeout=0):
        """Attente de plt.pause(timeout) : celle de matplotlib dure au moins 10 ms, ce qui ralentirait la boucle."""
        if timeout > 0:
            time.sleep(timeout)

    def draw(self):
        debut = time.perf_counter()
        super().draw()
        if not self.is_saving():            # plt.savefig dessine aussi : ce dessin-là reste dans le fichier
            _envoyer(self)
            self._dernier_envoi = time.perf_counter()
            self._duree_dessin = self._dernier_envoi - debut


@_Backend.export
class _BackendMir(_Backend):
    FigureCanvas = FigureCanvasMir
    FigureManager = FigureManagerMir
    mainloop = None                         # plt.show() ne bloque pas


@atexit.register
def _afficher_les_figures_restantes():
    for manager in Gcf.get_all_fig_managers():
        try:
            if manager.canvas.figure.stale:     # dernier état, même s'il vient d'être affiché il y a peu
                manager.canvas.draw()
        except Exception:
            pass        # l'application n'écoute plus (script arrêté) : rien à afficher
