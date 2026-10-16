"""
Guide de montage : on assemble le robot physique module par module, en suivant sa structure.

Pour chaque module, la vue 3D montre où le poser (les modules déjà montés sont affichés, celui à poser est en
surbrillance). Les modules se fixent par pogo pins : brancher = fixer.
  - servo (ou pince) : MIR détecte le servo qu'on vient de brancher (neuf, ou réutilisé avec n'importe quel ID),
    puis on le calibre à la main (milieu, butée min, butée max) en voyant la 3D suivre le mouvement ; enfin on
    confirme que la 3D tourne dans le même sens que le module (sinon le sens est inversé dans la structure) ;
  - caméra : elle démarre seule à l'installation ; MIR la cherche sur le réseau et note son adresse ;
  - bloc (socle, jonction) : on confirme simplement qu'il est posé.
La configuration est complétée au fil du montage : port du bus, ID et calibration des servos, adresse des caméras.
"""
from __future__ import annotations
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any
import mujoco
import numpy as np
from loguru import logger
from PySide6.QtCore import QTimer, Signal
from mir_devices.mir_feetech_motor_bus import mirMotorCalibration
from mir_robot.mir_robot_config import mirRobotConfig
from mir_sim.model_builder import BuiltModel, ModelBuilder, load_catalog, motor_params_from_config
from mir_utils.ui.dialogs import IDialogProvider
from mir_utils.ui.view_model_base import VMAction, ViewModelBase
from mir_utils.ui import theme
from mir_robot_editor.assemblage.bus import ID_DE_COTE, MILIEU, PAS_PAR_TOUR, BusAssemblage, chercher_cameras

MARGE_CALIBRATION = 10                  # écart minimal (pas codeur) entre le milieu et chaque butée
SURBRILLANCE = np.array(theme.SELECTION_RGBA)
PERIODE_CAMERA = 20                     # recherche réseau des caméras tous les 20 tops (≈ 3 s)
IDS_COURANTS = set(range(0, 41))        # ID cherchés pour un servo qu'on branche (neuf : 1 ; réutilisé : souvent < 40)
IDS_RESERVES = set(range(ID_DE_COTE, 254))  # aussi : un servo resté de côté (guide interrompu, autre robot)


class Phase(Enum):
    PLACER = auto()         # poser le module (et attendre sa détection)
    MILIEU = auto()         # servo : articulation au milieu de sa course
    MINI = auto()           # servo : butée min
    MAXI = auto()           # servo : butée max
    SENS = auto()           # servo : la 3D tourne-t-elle dans le même sens ?
    FAIT = auto()


@dataclass
class Etape:
    module: str
    type: str                               # type du catalogue, ex. "mir_servo"
    genre: str                              # "socle", "bloc", "servo", "capteur"
    moteur: str | None = None
    capteurs: list[str] = field(default_factory=list)
    etat: str = "à faire"                   # "à faire", "en cours", "fait"

    def titre(self) -> str:
        quoi = {"socle": "Socle", "bloc": "Bloc", "servo": "Servo", "capteur": "Capteur"}[self.genre]
        return f"{quoi} : {self.module}"


def ordre_de_montage(structure: dict[str, Any], catalog: dict[str, dict[str, Any]]) -> list[Etape]:
    """Modules dans l'ordre où on peut les monter : la racine, puis chaque module après celui qui le porte."""
    modules = structure.get("modules", {})
    enfants: dict[str, list[str]] = {}
    racines = []
    for nom, inst in modules.items():
        if "on" in inst:
            enfants.setdefault(str(inst["on"]).partition(".")[0], []).append(nom)
        else:
            racines.append(nom)
    ordre: list[str] = []
    a_voir = list(reversed(racines))
    while a_voir:
        nom = a_voir.pop()
        ordre.append(nom)
        a_voir.extend(reversed(enfants.get(nom, [])))
    etapes = []
    for nom in ordre:
        inst = modules[nom]
        module = catalog.get(inst["type"], {})
        moteur = inst.get("motor") or next(iter(inst.get("motors", {}).values()), None)
        capteurs = list(inst.get("sensors", {}).values())
        if "on" not in inst:
            genre = "socle"
        elif moteur is not None:
            genre = "servo"
        elif capteurs:
            genre = "capteur"
        else:
            genre = "bloc"
        etapes.append(Etape(nom, inst["type"], genre, moteur, capteurs))
    return etapes


class AssemblageVMAction(Enum):
    SUIVANT = auto()
    RECOMMENCER = auto()


class AssemblageViewModel(ViewModelBase[AssemblageVMAction]):
    changed = Signal()                          # étape, consigne ou boutons changés
    model_changed = Signal(object, object)      # MjModel, MjData (modules montés + module à poser)
    redraw_required = Signal()

    def __init__(self, dialog_provider: IDialogProvider, config: mirRobotConfig, modules: list[str] | None = None):
        """modules : limiter le guide à ces modules (ex. recalibrer un moteur sur un robot déjà construit)."""
        super().__init__(dialog_provider)
        self._config = config.get_deep_copy()
        self._catalog = load_catalog()
        self.etapes = ordre_de_montage(self._config.structure or {}, self._catalog)
        self._partiel = modules is not None
        if self._partiel:
            self.etapes = [e for e in self.etapes if e.module in modules]
        self._finalise = False
        self.index = 0
        self.phase = Phase.PLACER
        self.info = ""
        self.detection = ""                     # comment le servo de l'étape a été reconnu
        self._bus: BusAssemblage | None = None
        self._ids_montes: set[int] = set()
        self._offset = 0
        self._mini = self._maxi = MILIEU
        self._position: int | None = None
        self._tops = 0
        self._recherche_servos: threading.Thread | None = None
        self._presents: set[int] | None = None          # résultat de la dernière recherche des servos
        self._erreur_recherche: Exception | None = None
        self._recherche_camera: threading.Thread | None = None
        self._cameras_trouvees: dict[str, str] = {}
        self._cameras_associees: set[str] = {c.ip for c in self._config.sensors.values() if getattr(c, "ip", None)}
        self._built: BuiltModel | None = None
        self._data: mujoco.MjData | None = None
        self._timer = QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._top)
        self._actions[AssemblageVMAction.SUIVANT] = VMAction("Suivant", "")
        self._actions[AssemblageVMAction.RECOMMENCER] = VMAction("Recommencer ce module", "Reprendre ce module depuis le début", enabled=True)

    def _enter_context(self):
        pass

    def _exit_context(self, exc_type, exc_value, traceback):
        self._timer.stop()
        if self._bus is not None:
            if not self._finalise:
                # guide interrompu : tous les servos mis de côté, terminés ou non, reprennent leur ID définitif
                try:
                    self._donner_ids_definitifs()
                except Exception as ex:
                    logger.warning(f"guide de montage : ID définitifs non écrits : {ex}")
            self._bus.fermer()

    def _donner_ids_definitifs(self):
        if self._partiel:
            return
        if self._recherche_servos is not None:
            self._recherche_servos.join(timeout=5)
        # tout servo encore sur son ID de côté, même si son module n'est pas terminé (sinon il reste sur 200...
        # et un autre servo reçoit le même ID au guide suivant : deux servos au même ID rendent le bus muet)
        attendus = self.moteurs_attendus()
        moteurs = [etape.moteur for etape in self.etapes if etape.moteur is not None]
        presents = self._bus.ids_presents({self._id_courant(m) for m in moteurs} | {attendus[m] for m in moteurs})
        for moteur in moteurs:
            courant, final = self._id_courant(moteur), attendus[moteur]
            if courant not in presents:
                continue
            if final in presents:
                logger.warning(f"guide de montage : {moteur} laissé à l'ID {courant}, l'ID {final} est déjà pris")
                continue
            self._bus.changer_id(moteur, courant, final)
            presents = (presents - {courant}) | {final}
            logger.info(f"guide de montage : {moteur} remis à son ID définitif {final} (était à {courant})")

    def _candidats(self) -> set[int]:
        """ID à chercher : ID courants, ID prévus par la configuration, ID réservés (mis de côté)."""
        attendus = self.moteurs_attendus()
        return IDS_COURANTS | IDS_RESERVES | set(attendus.values()) | {self._id_courant(m) for m in attendus}

    def _rechercher_servos(self):
        """Recherche des servos présents : en arrière-plan (un ping par ID, ≈ 30 ms par ID absent)."""
        if getattr(self._bus, "synchrone", False):
            self._presents = self._bus.ids_presents(self._candidats())
            return
        if self._recherche_servos is not None:
            return
        candidats = self._candidats()
        def chercher():
            try:
                self._presents = self._bus.ids_presents(candidats)
            except Exception as ex:
                self._erreur_recherche = ex
            finally:
                self._recherche_servos = None
        self._recherche_servos = threading.Thread(target=chercher, daemon=True)
        self._recherche_servos.start()

    def finaliser(self) -> bool:
        """Fin du montage : chaque servo reçoit son ID définitif. False (et message) en cas de problème."""
        try:
            self._donner_ids_definitifs()
        except Exception as ex:
            logger.exception(ex)
            self._dialogProvider.information("Fin du montage", f"Les servos n'ont pas pu recevoir leur ID définitif : {ex}")
            return False
        self._finalise = True
        return True

    # ------------------------------------------------------------------ démarrage
    def _id_courant(self, moteur: str) -> int:
        """ID du servo pendant le guide : de côté (montage complet), ou définitif (recalibration d'un robot construit)."""
        if self._partiel:
            return self.moteurs_attendus()[moteur]
        return ID_DE_COTE + list(self.moteurs_attendus()).index(moteur)

    def moteurs_attendus(self) -> dict[str, int]:
        bus = self._config.motor_bus
        return {nom: m.id for nom, m in bus.motors.items()} if bus is not None else {}

    def demarrer(self, bus: BusAssemblage, port: str | None):
        """Ouvre le bus (port du câble USB des servos) et commence le montage."""
        if self._config.motor_bus is not None:
            if port is not None:
                self._config.motor_bus.motor_port = port
            bus.ouvrir({moteur: self._id_courant(moteur) for moteur in self.moteurs_attendus()})
        self._bus = bus
        self.index = 0
        self._commencer_etape()
        self._timer.start()

    def titre(self) -> str:
        return "Recalibrer un servo" if self._partiel else "Construire le robot"

    def configuration(self) -> mirRobotConfig:
        """Configuration complétée par le montage (port, ID, calibrations, adresses, sens)."""
        return self._config

    def termine(self) -> bool:
        return self.index >= len(self.etapes)

    def etape(self) -> Etape | None:
        return None if self.termine() else self.etapes[self.index]

    # ------------------------------------------------------------------ consignes affichées
    def consigne(self) -> str:
        e = self.etape()
        if e is None:
            faits = sum(1 for x in self.etapes if x.etat == "fait")
            return (f"Montage terminé : {faits} module(s) monté(s) sur {len(self.etapes)}. "
                    "Cliquez sur Terminer pour enregistrer la configuration.")
        if e.genre in ("socle", "bloc"):
            return f"Posez le module « {e.module} » ({e.type.removeprefix('mir_')}) à l'endroit en surbrillance, " \
                   "puis cliquez sur « C'est posé »."
        if e.genre == "capteur":
            if self.phase == Phase.FAIT:
                return "Caméra détectée. Cliquez sur Suivant."
            return f"Branchez la caméra « {e.module} » à l'endroit en surbrillance. Elle démarre toute seule : " \
                   "MIR la cherche sur le réseau (cela peut prendre une minute)."
        textes = {
            Phase.PLACER: f"Branchez le servo « {e.module} » à l'endroit en surbrillance. "
                          "MIR le détecte dès qu'il est branché.",
            Phase.MILIEU: "Servo détecté. Tournez l'articulation à la main jusqu'au MILIEU de sa course, "
                          "puis cliquez sur Suivant.",
            Phase.MINI: "Tournez l'articulation jusqu'à sa BUTÉE dans un sens, sans forcer, puis cliquez sur Suivant.",
            Phase.MAXI: "Tournez maintenant l'articulation jusqu'à sa BUTÉE dans l'autre sens, puis cliquez sur Suivant.",
            Phase.SENS: "Tournez l'articulation à la main : la 3D tourne-t-elle dans le même sens que le module ?",
        }
        return textes.get(self.phase, "")

    def texte_suivant(self) -> str:
        e = self.etape()
        if e is None:
            return "Terminer"
        if e.genre in ("socle", "bloc"):
            return "C'est posé"
        return "Suivant"

    # ------------------------------------------------------------------ actions de l'utilisateur
    def suivant(self):
        e = self.etape()
        if e is None or self._bus is None:
            return
        try:
            if e.genre in ("socle", "bloc") or (e.genre == "capteur" and self.phase == Phase.FAIT):
                self._finir_etape("fait")
            elif e.genre == "servo" and self.phase == Phase.MILIEU:
                self._offset = self._bus.mettre_au_milieu(e.moteur)
                self._mini = self._maxi = MILIEU
                self._changer_phase(Phase.MINI)
            elif e.genre == "servo" and self.phase == Phase.MINI:
                self._changer_phase(Phase.MAXI)
            elif e.genre == "servo" and self.phase == Phase.MAXI:
                self._enregistrer_calibration(e)
        except Exception as ex:
            logger.exception(ex)
            self._dialogProvider.information("Problème avec le servo", f"{ex}\r\nVérifiez le branchement, puis "
                                             "« Recommencer ce module ».")

    def sens(self, meme_sens: bool):
        """Réponse à « la 3D tourne-t-elle dans le même sens ? » ; sinon, le sens est inversé dans la structure."""
        e = self.etape()
        if e is None or self.phase != Phase.SENS:
            return
        if not meme_sens:
            inst = self._config.structure["modules"][e.module]
            if int(inst.get("direction", 1)) < 0:
                inst.pop("direction", None)
            else:
                inst["direction"] = -1
        self._finir_etape("fait")

    def recommencer(self):
        if self.etape() is not None:
            self._commencer_etape()

    # ------------------------------------------------------------------ déroulé
    def _commencer_etape(self):
        e = self.etape()
        self.info = ""
        self.detection = ""
        self._presents = None           # une recherche lancée pour l'étape précédente ne compte pas
        self._position = None
        if e is not None:
            e.etat = "en cours"
            self.phase = Phase.PLACER
        self._construire_3d()
        self._update_actions()
        self.changed.emit()

    def _finir_etape(self, etat: str):
        e = self.etape()
        if e is None:
            return
        e.etat = etat
        if etat == "fait" and e.moteur is not None:
            self._ids_montes.add(self._id_courant(e.moteur))
        self.index += 1
        if self.termine():
            self._timer.stop()
            self._construire_3d()
            self._update_actions()
            self.changed.emit()
        else:
            self._commencer_etape()

    def _changer_phase(self, phase: Phase):
        self.phase = phase
        self._update_actions()
        self.changed.emit()

    def _update_actions(self):
        e = self.etape()
        attente = e is not None and self.phase == Phase.PLACER and e.genre in ("servo", "capteur")
        self._actions[AssemblageVMAction.SUIVANT].set_enabled(not attente and self.phase != Phase.SENS)

    def _enregistrer_calibration(self, e: Etape):
        if MILIEU - self._mini < MARGE_CALIBRATION or self._maxi - MILIEU < MARGE_CALIBRATION:
            self._dialogProvider.information("Calibration", "Les deux butées n'ont pas été atteintes : tournez "
                                             "l'articulation jusqu'au bout dans chaque sens.")
            self._changer_phase(Phase.MINI)
            return
        self._bus.fin_calibration(e.moteur, self._offset, self._mini, self._maxi)
        # réglages du moteur : ceux de la configuration (valeurs par défaut de MIR pour un robot conçu sans matériel)
        m = self._config.motor_bus.motors[e.moteur]
        self._bus.ecrire_reglages(e.moteur, {"P_Coefficient": m.P, "I_Coefficient": m.I, "D_Coefficient": m.D,
                                             "Torque_Limit": m.torque_limit,
                                             "Operating_Mode": int(getattr(m.operating_mode, "value", m.operating_mode))})
        self._config.motor_bus.calibration[e.moteur] = mirMotorCalibration(
            id=self.moteurs_attendus()[e.moteur], drive_mode=0, homing_offset=self._offset,   # ID définitif
            range_min=self._mini, range_max=self._maxi)
        self._changer_phase(Phase.SENS)

    # ------------------------------------------------------------------ boucle (détection, positions)
    def _top(self):
        e = self.etape()
        if e is None or self._bus is None:
            return
        self._tops += 1
        try:
            self._suivre_servos_valides()
            if e.genre == "servo" and self.phase == Phase.PLACER:
                if self._erreur_recherche is not None:
                    erreur, self._erreur_recherche = self._erreur_recherche, None
                    raise erreur
                if self._presents is not None:
                    presents, self._presents = self._presents, None
                    self._detecter_servo(e, presents)
                if self.phase == Phase.PLACER:
                    self._rechercher_servos()
            elif e.genre == "servo" and self.phase in (Phase.MILIEU, Phase.MINI, Phase.MAXI, Phase.SENS):
                self._suivre_position(e)
            elif e.genre == "capteur" and self.phase == Phase.PLACER:
                self._detecter_camera(e)
        except Exception as ex:
            self.info = f"Communication avec les servos impossible : {ex}"
            self.changed.emit()

    def _suivre_servos_valides(self):
        """Les servos déjà montés et calibrés continuent d'animer la 3D quand on les bouge à la main."""
        e = self.etape()
        valides = {etape.moteur for etape in self.etapes if etape.etat == "fait" and etape.moteur is not None}
        if self._partiel and self._config.motor_bus is not None:
            # recalibration : les autres servos du robot construit sont déjà calibrés
            valides |= set(self._config.motor_bus.calibration)
        for moteur in valides:
            if e is not None and moteur == e.moteur:
                continue
            try:
                position = self._bus.position(moteur)
            except Exception:
                continue        # servo débranché : sa position n'est plus lue
            self._poser_articulation(moteur, (position - MILIEU) * 360 / PAS_PAR_TOUR, redessiner=False)
        self.redraw_required.emit()

    def _detecter_servo(self, e: Etape, presents: set[int]):
        courant, final = self._id_courant(e.moteur), self.moteurs_attendus()[e.moteur]
        nouveaux = presents - self._ids_montes
        logger.debug(f"guide de montage : {e.module} ; servos sur le bus : {sorted(presents)} ; montés : {sorted(self._ids_montes)}")
        if courant in nouveaux:
            trouve = courant                     # déjà mis de côté (guide relancé)
        elif final in nouveaux:
            trouve = final                       # déjà à son ID définitif (module remonté)
        elif len(nouveaux) == 1:
            trouve = next(iter(nouveaux))        # le servo qu'on vient de brancher (neuf, ou réutilisé)
        else:
            self.info = ("Plusieurs nouveaux servos : ne branchez qu'un module à la fois." if nouveaux
                         else "En attente du servo… (vérifiez qu'il est bien enfoncé)")
            self.changed.emit()
            return
        if trouve != courant:
            self._bus.changer_id(e.moteur, trouve, courant)
            if courant not in self._bus.ids_presents({courant}):
                raise RuntimeError("le servo ne répond plus après le changement de son ID")
        logger.info(f"guide de montage : {e.module} détecté (ID {trouve}), mis à l'ID {courant}, ID définitif {final}")
        self.detection = "Servo détecté"
        self._bus.debut_calibration(e.moteur)
        self._changer_phase(Phase.MILIEU)

    def _suivre_position(self, e: Etape):
        position = self._bus.position(e.moteur)
        self._position = position
        if self.phase in (Phase.MINI, Phase.MAXI):
            # l'élève peut commencer par l'une ou l'autre butée : on garde les extrêmes atteints
            self._mini = min(self._mini, position)
            self._maxi = max(self._maxi, position)
        if self.phase != Phase.MILIEU:
            # après la mise au milieu, la position est connue : la 3D suit la main de l'élève
            self._poser_articulation(e.moteur, (position - MILIEU) * 360 / PAS_PAR_TOUR)
        self.info = f"Position : {position}" + (f" · course relevée : {self._mini} → {self._maxi}"
                                                 if self.phase in (Phase.MINI, Phase.MAXI) else "")
        self.changed.emit()

    def _detecter_camera(self, e: Etape):
        if self._recherche_camera is None and self._tops % PERIODE_CAMERA == 1:
            def chercher():
                try:
                    self._cameras_trouvees = chercher_cameras()
                except Exception as ex:
                    logger.warning(f"recherche des caméras : {ex}")
                finally:
                    self._recherche_camera = None
            self._recherche_camera = threading.Thread(target=chercher, daemon=True)
            self._recherche_camera.start()
        nouvelles = [ip for ip in self._cameras_trouvees.values() if ip not in self._cameras_associees]
        if not nouvelles:
            self.info = "Recherche de la caméra sur le réseau…"
            self.changed.emit()
            return
        ip = nouvelles[0]
        for capteur in e.capteurs:
            if capteur in self._config.sensors:
                self._config.sensors[capteur].ip = ip
        self._cameras_associees.add(ip)
        self.info = f"Caméra détectée : {ip}"
        self._changer_phase(Phase.FAIT)
        self._update_actions()

    # ------------------------------------------------------------------ vue 3D
    def _construire_3d(self):
        """Modules déjà montés et module à poser (en surbrillance)."""
        if not self._config.structure:
            return
        # robot déjà construit (guide partiel) : tout le robot est affiché ; sinon, les modules montés jusqu'ici
        montes = set(self._config.structure["modules"]) if self._partiel else {x.module for x in self.etapes[: self.index + 1]}
        structure = deepcopy(self._config.structure)
        structure["modules"] = {nom: inst for nom, inst in structure["modules"].items() if nom in montes}
        structure.pop("unplaced", None)
        try:
            self._built = ModelBuilder(structure, motor_params_from_config(self._config)).build()
        except Exception as ex:
            logger.warning(f"guide de montage : modèle 3D impossible : {ex}")
            return
        self._data = mujoco.MjData(self._built.model)
        mujoco.mj_forward(self._built.model, self._data)
        e = self.etape()
        if e is not None:
            model = self._built.model
            for geom in range(model.ngeom):
                if self._built.body_module.get(int(model.geom_bodyid[geom])) == e.module:
                    model.geom_rgba[geom] = 0.4 * model.geom_rgba[geom] + 0.6 * SURBRILLANCE
        self.model_changed.emit(self._built.model, self._data)

    def _poser_articulation(self, moteur: str, degres: float, redessiner: bool = True):
        if self._built is None or self._data is None or moteur not in self._built.joints:
            return
        info = self._built.joints[moteur]
        joint = self._built.model.joint(info.joint_name).id
        lo, hi = self._built.model.jnt_range[joint]
        self._data.qpos[self._built.model.jnt_qposadr[joint]] = np.clip(info.motor_to_sim_rad(degres), lo, hi)
        mujoco.mj_forward(self._built.model, self._data)
        if redessiner:
            self.redraw_required.emit()

    def sens_actuel_inverse(self) -> bool:
        e = self.etape()
        return e is not None and int(self._config.structure["modules"][e.module].get("direction", 1)) < 0
