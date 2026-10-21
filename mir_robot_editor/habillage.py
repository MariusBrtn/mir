"""
En-têtes des fenêtres qui ne les construisent pas elles-mêmes (voir DialogBase.register_frame) : à la première
ouverture, la fenêtre reçoit un en-tête (son titre, une phrase, une icône) et son contenu passe dessous, sans
changement. Leur code n'est pas modifié.
"""
from mir_utils.ui.widgets import DialogBase

FENETRES = {
    "MotorConfigurationView": ("Mode, PID, vitesse et couple max des servos du robot construit et branché.", "reglages"),
    "CalibrationView": ("Le milieu et les butées de chaque servo, mesurés à la main.", "calibration",
                        "Calibrer les servos"),
    "RegistersView": ("Les registres du servo : lire, modifier, écrire.", "motor"),
    "EditConfigurationView": ("Le fichier de configuration du robot, à modifier directement.", "edit",
                              "Éditer la configuration"),
    "MotorConfigureIDsView": ("Les ID des servos trouvés sur le bus.", "servo_id", "Configurer les ID des servos"),
    "ScanDevicesView": ("Les servos, caméras et capteurs trouvés sur les ports série et sur le réseau.", "scan",
                        "Découvrir les appareils"),
    "ObservationsSelectionView": ("Les grandeurs que le robot enregistre et affiche.", "observations",
                                  "Choisir les observations"),
    "SensorConfigurationView": ("Les réglages du capteur.", "sensors"),
}


def installer():
    for nom, (phrase, icone, *titre) in FENETRES.items():
        DialogBase.register_frame(nom, phrase, icone, *titre)
