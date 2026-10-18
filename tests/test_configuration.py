"""Configuration des robots : lecture, écriture, et complément à partir de la structure (conception sans matériel)."""
import pytest
from mir_robot.mir_robot import chemin_robot, mirRobotConfig, robots_disponibles
from mir_sim.config_from_structure import FIRST_MOTOR_ID, complete_config_from_structure
from mir_sim.model_builder import load_catalog
from mir_sim.config_from_structure import structure_hardware


@pytest.mark.parametrize("nom", robots_disponibles())
def test_chaque_robot_se_charge(nom):
    cfg = mirRobotConfig.load(str(chemin_robot(nom)))
    assert cfg.motor_bus is not None or cfg.sensors, f"{nom} : ni moteur ni capteur"


@pytest.mark.parametrize("nom", robots_disponibles())
def test_ecrire_puis_relire_donne_la_meme_configuration(nom, tmp_path):
    cfg = mirRobotConfig.load(str(chemin_robot(nom)))
    copie = tmp_path / "robot.json"
    cfg.save_as(str(copie))
    relue = mirRobotConfig.load(str(copie))
    assert relue.is_equal(cfg)
    assert mirRobotConfig.from_json(cfg.to_json()).motor_bus == cfg.motor_bus


def test_fichier_absent_ou_invalide(tmp_path):
    with pytest.raises(ValueError, match="pas été trouvé"):
        mirRobotConfig.load(str(tmp_path / "absent.json"))
    casse = tmp_path / "casse.json"
    casse.write_text("{ pas du json")
    with pytest.raises(ValueError, match="conforme"):
        mirRobotConfig.load(str(casse))


@pytest.mark.parametrize("nom", ["bras_2ddl", "bras_4ddl_cam_V2", "test_mobile"])
def test_structure_seule_donne_un_robot_complet(nom):
    """Un robot conçu dans l'éditeur, sans matériel : sa structure suffit à créer moteurs, capteurs et observations."""
    cfg = mirRobotConfig.load(str(chemin_robot(nom)))
    moteurs, capteurs = structure_hardware(cfg.structure, load_catalog())
    cfg.motor_bus = None
    cfg.sensors = {}
    cfg.observations = {}

    ajouts = complete_config_from_structure(cfg)

    assert ajouts
    assert cfg.motor_bus is not None and set(cfg.motor_bus.motors) == set(moteurs)
    ids = sorted(m.id for m in cfg.motor_bus.motors.values())
    assert ids == list(range(FIRST_MOTOR_ID, FIRST_MOTOR_ID + len(moteurs)))    # l'ID 1 reste libre (servo neuf)
    assert set(cfg.sensors) == set(capteurs)
    assert all(f"{m}.position" in cfg.observations for m in moteurs)
    assert all(c in cfg.observations for c in capteurs)


def test_completer_une_configuration_complete_ne_change_rien():
    cfg = mirRobotConfig.load(str(chemin_robot("bras_2ddl")))
    complete_config_from_structure(cfg)
    avant = cfg.get_deep_copy()
    assert complete_config_from_structure(cfg) == []
    assert cfg.is_equal(avant)
