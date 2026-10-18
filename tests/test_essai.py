"""Essais : sollicitations, essai sur le robot simulé, enregistrement et relecture."""
import numpy as np
import pytest
from mir_robot.commandes.sollicitations import Creneau, Echelon, Rampe, Sinus
from mir_robot.essai import CONSIGNE, Essai, decouvrir_analyses, lancer_essai


def test_sollicitations():
    echelon = Echelon(initiale=0, finale=30, instant=0.5)
    assert [echelon.consigne(t) for t in (0, 0.49, 0.5, 2)] == [0, 0, 30, 30]

    rampe = Rampe(initiale=0, finale=30, instant=0.5, montee=1.0)
    assert [rampe.consigne(t) for t in (0, 0.5, 1.0, 1.5, 3)] == pytest.approx([0, 0, 15, 30, 30])

    sinus = Sinus(centre=10, amplitude=20, periode=2)
    assert [sinus.consigne(t) for t in (0, 0.5, 1.0, 1.5)] == pytest.approx([10, 30, 10, -10], abs=1e-9)

    creneau = Creneau(basse=0, haute=30, periode=2)
    assert {creneau.consigne(0.1), creneau.consigne(1.1)} == {0, 30}


def test_echelon_sur_le_robot_simule(robot_simule, tmp_path):
    robot = robot_simule("bras_2ddl")
    fps = 50
    essai = lancer_essai(robot, Echelon(actionneur="joint_1.position", initiale=0, finale=20, instant=0.2, duree=1.0),
                         fps=fps, conditions={"simulation": True})

    assert len(essai.t) == pytest.approx(fps * 1.0, abs=5)
    assert np.all(np.diff(essai.t) > 0)
    assert essai.consigne[0] == 0 and essai.consigne[-1] == 20
    assert essai.mesure is not None
    assert essai.mesure[-1] == pytest.approx(20, abs=2)      # le moteur simulé a suivi l'échelon
    assert "joint_1.current" in essai and "joint_2.position" not in essai     # par défaut : le moteur sollicité
    assert essai.unite("joint_1.position") == "deg"
    assert essai.resume_sollicitation() == "Échelon 0 → 20°"
    assert essai.resume_sollicitation(fichier=True) == "Echelon_0-20deg"
    assert "simulé" in essai.titre()

    chemin = tmp_path / "essai.npz"
    essai.enregistrer(chemin)
    relu = Essai.charger(chemin)
    assert np.array_equal(relu.t, essai.t)
    assert np.array_equal(relu[CONSIGNE], essai.consigne)
    assert np.array_equal(relu.mesure, essai.mesure)
    assert relu.conditions["sollicitation"] == essai.conditions["sollicitation"]
    assert relu.conditions["simulation"] is True


def test_essai_interrompu(robot_simule):
    appels = []
    essai = lancer_essai(robot_simule("bras_2ddl"), Echelon(actionneur="joint_1.position", duree=5.0), fps=50,
                         progression=lambda t, obs, c: appels.append(t), arret=lambda: len(appels) >= 10)
    assert len(essai.t) == 10


def test_actionneur_inconnu(robot_simule):
    with pytest.raises(KeyError, match="joint_9.position"):
        lancer_essai(robot_simule("bras_2ddl"), Echelon(actionneur="joint_9.position"))


def test_analyses_utilisateur_se_chargent():
    assert not decouvrir_analyses().erreurs
