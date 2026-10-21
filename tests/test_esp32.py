"""Module capteur ESP32 : passage sur un autre réseau Wi-Fi par le câble, avec un module factice."""
from __future__ import annotations
from mir_robot_editor.capteurs.esp32_view_model import Esp32ViewModel


class DialoguesMuets:
    def information(self, *args): pass
    def error(self, *args): pass


class ModuleFactice:
    """Mémoire du firmware (NVS) : mêmes clés que esp32_sensor/src/main.cpp."""
    def __init__(self, **memoire):
        self.memoire = {"sensor_id": "lidar", "sensor_type": "esp_lidar", "ap1_ip": "auto", "ap2_ip": "auto",
                        "ap1_ssid": "", "ap1_pwd": "", "ap2_ssid": "", "ap2_pwd": ""} | memoire
        self.redemarre = False

    def __call__(self, port):        # se fait passer pour la classe LiaisonSerie
        return self

    def fermer(self): pass
    def lire_wifi(self): return {k: self.memoire[k] for k in ("ap1_ssid", "ap1_pwd", "ap2_ssid", "ap2_pwd")}
    def lire_configuration(self): return dict(self.memoire)
    def ecrire_wifi(self, reglages): self.memoire |= reglages
    def ecrire_configuration(self, reglages): self.memoire |= reglages
    def redemarrer(self): self.redemarre = True


def passer_sur(module, ssid, pwd, repondent):
    vm = Esp32ViewModel(DialoguesMuets(), serie=module, chercher=lambda timeout: repondent)
    vm.ssid, vm.mot_de_passe = ssid, pwd
    return vm._wifi_par_cable("/dev/factice")


def test_ancien_reseau_en_secours_et_ip_automatique():
    module = ModuleFactice(ap1_ssid="Ancien", ap1_pwd="vieux", ap1_ip="192.168.0.42")
    message = passer_sur(module, "Nouveau", "secret", [{"id": "lidar", "type": "esp_lidar", "ip": "10.0.0.7"}])
    m = module.memoire
    assert (m["ap1_ssid"], m["ap1_pwd"], m["ap1_ip"]) == ("Nouveau", "secret", "auto")
    assert (m["ap2_ssid"], m["ap2_pwd"], m["ap2_ip"]) == ("Ancien", "vieux", "192.168.0.42")
    assert module.redemarre
    assert message.startswith("✓") and "10.0.0.7" in message


def test_meme_reseau_ne_se_met_pas_en_secours(monkeypatch):
    monkeypatch.setattr("mir_robot_editor.capteurs.esp32_view_model.ATTENTE_RESEAU", 0.0)
    module = ModuleFactice(ap1_ssid="Maison", ap1_pwd="ancien", ap2_ssid="Ecole", ap2_pwd="x")
    message = passer_sur(module, "Maison", "nouveau", [])
    assert module.memoire["ap1_pwd"] == "nouveau"
    assert module.memoire["ap2_ssid"] == "Ecole"
    assert message.startswith("✗")        # personne ne répond sur le réseau


def test_autre_module_sur_le_reseau_ignore(monkeypatch):
    monkeypatch.setattr("mir_robot_editor.capteurs.esp32_view_model.ATTENTE_RESEAU", 0.0)
    message = passer_sur(ModuleFactice(), "Nouveau", "secret", [{"id": "meteo", "type": "esp_wheather", "ip": "1.2.3.4"}])
    assert message.startswith("✗")
