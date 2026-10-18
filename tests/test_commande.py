"""Commandes : la boucle observation -> décision -> action, et la découverte des fichiers de commandes."""
import time
import pytest
from mir_devices.mir_device import DeviceAction
from mir_robot.commande import (Commande, ExecutionCommande, Parametre, decouvrir_commandes, executer,
                                verifier_action, verifier_fichier)

ACTIONS = {
    "joint_1.position": DeviceAction("joint_1", "position", 0.0, "float", "°", (-90.0, 90.0)),
    "pince.position": DeviceAction("pince", "position", 0, "int", "", (0, 100)),
}


# ---------------------------------------------------------------- vérification des actions

def test_action_inconnue_refusee():
    with pytest.raises(KeyError, match="joint_9.position"):
        verifier_action({"joint_9.position": 0.0}, ACTIONS)


def test_action_bornee_aux_butees_et_arrondie():
    assert verifier_action({"joint_1.position": 120.0}, ACTIONS) == {"joint_1.position": 90.0}
    assert verifier_action({"joint_1.position": -120.0}, ACTIONS) == {"joint_1.position": -90.0}
    assert verifier_action({"pince.position": 41.6}, ACTIONS) == {"pince.position": 42}


# ---------------------------------------------------------------- paramètres

class Consigne(Commande):
    nom = "Consigne fixe"
    parametres = {"valeur": Parametre(20.0, "°", "Valeur"), "tours": Parametre(30, "", "Nombre de tours")}

    def demarrer(self, robot):
        self.robot = robot
        self.n = 0
        self.arretee = False

    def action(self, observation):
        self.n += 1
        if self.n >= self.tours:
            self.terminer()
        return {"joint_1.position": self.valeur}

    def arreter(self):
        self.arretee = True


def test_parametres_par_defaut_et_au_constructeur():
    assert Consigne().valeur == 20.0
    assert Consigne(valeur=-10).valeur == -10
    with pytest.raises(TypeError, match="valuer"):
        Consigne(valuer=5)


# ---------------------------------------------------------------- exécution sur le robot simulé

def test_executer_amene_le_moteur_a_la_consigne(robot_simule):
    robot = robot_simule("bras_2ddl")
    commande = Consigne(valeur=25.0, tours=30)
    debut = time.perf_counter()
    executer(robot, commande, fps=30)
    assert commande.n == 30
    assert commande.arretee
    assert commande.robot.fps == 30 and "joint_1.position" in commande.robot.actions
    assert time.perf_counter() - debut == pytest.approx(1.0, abs=0.3)     # 30 tours à 30 Hz
    assert robot.get_observation()["joint_1.position"] == pytest.approx(25.0, abs=2.0)


def test_executer_s_arrete_apres_la_duree(robot_simule):
    commande = Consigne(tours=10_000)
    executer(robot_simule("bras_2ddl"), commande, fps=50, duree=0.4)
    assert 10 <= commande.n <= 25
    assert commande.arretee


def test_arreter_est_appelee_meme_si_la_commande_plante(robot_simule, clavier):
    class Plante(Consigne):
        def action(self, observation):
            raise ZeroDivisionError("bug de l'élève")

    commande = Plante()
    with pytest.raises(ZeroDivisionError):
        executer(robot_simule("bras_2ddl"), commande, fps=30)
    assert commande.arretee


def test_tour_renvoie_l_action_reellement_envoyee(robot_simule, clavier):
    class Excessive(Consigne):
        def action(self, observation):
            return {"joint_1.position": 500.0}

    robot = robot_simule("bras_2ddl")
    execution = ExecutionCommande(robot, Excessive(), fps=30, clavier=clavier)
    assert clavier.demarre
    assert execution.tour(robot.get_observation())
    assert execution.derniere_action["joint_1.position"] == robot.action_features["joint_1.position"].get_range()[1]
    execution.arreter()
    assert not clavier.demarre


# ---------------------------------------------------------------- découverte des fichiers

COMMANDE_OK = """
from mir_robot.commande import Commande

class Aller(Commande):
    nom = "Aller"
    famille = "robotique"
    def action(self, observation):
        return None

class Mesurer(Commande):
    famille = "essai"
    def action(self, observation):
        return None
"""


def test_decouvrir_commandes(tmp_path):
    (tmp_path / "ok.py").write_text(COMMANDE_OK)
    (tmp_path / "casse.py").write_text("import module_qui_n_existe_pas\n")
    (tmp_path / "_brouillon.py").write_text("raise RuntimeError('ne doit pas être chargé')\n", encoding="utf-8")

    trouvees = decouvrir_commandes([tmp_path])
    assert set(trouvees.commandes) == {"Aller", "Mesurer"}       # nom affiché, ou nom de la classe
    assert trouvees.fichiers["Aller"] == tmp_path / "ok.py"
    assert list(trouvees.erreurs) == [tmp_path / "casse.py"]
    assert set(decouvrir_commandes([tmp_path], familles=("robotique",)).commandes) == {"Aller"}


def test_verifier_fichier_donne_la_ligne_de_l_erreur(tmp_path):
    fichier = tmp_path / "eleve.py"
    fichier.write_text(COMMANDE_OK)
    assert verifier_fichier(fichier) == (["Aller", "Mesurer"], None, None)

    fichier.write_text("from mir_robot.commande import Commande\n\nclass A(Commande)\n    pass\n")
    noms, erreur, ligne = verifier_fichier(fichier)
    assert noms == [] and "syntaxe" in erreur and ligne == 3

    fichier.write_text("x = 1\ny = x / 0\n")
    noms, erreur, ligne = verifier_fichier(fichier)
    assert "ZeroDivisionError" in erreur and ligne == 2

    fichier.write_text("x = 1\n")
    assert "aucune classe" in verifier_fichier(fichier)[1]


def test_commandes_fournies_et_utilisateur_se_chargent():
    trouvees = decouvrir_commandes()
    assert not trouvees.erreurs, trouvees.erreurs
    assert {"Échelon", "Rampe", "Sinus", "Créneau"} <= set(trouvees.commandes)
