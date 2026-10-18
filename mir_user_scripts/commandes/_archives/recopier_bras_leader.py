"""
Recopier le bras leader : exemple de téléopération avec un bras leader.

À chaque tour de boucle, MIR lit les positions du bras leader, appelle teleoperer(), puis envoie les consignes.
  leader : les positions du bras leader : leader["joint_1.position"]... (toujours le robot réel)
  robot  : les mesures du robot piloté : robot["joint_1.position"]...
"""
NOM = "Recopier le bras leader"
TELEOPERATEUR = "bras_leader"     # nom d'un robot du dossier mir/robots
FREQUENCE = 30


def teleoperer(leader, robot):
    consignes = dict(leader)
    # exemples de variantes :
    #   consignes["joint_1.position"] = -leader["joint_1.position"]       # sens inversé
    #   consignes["joint_5.position"] = 0.5 * leader["joint_5.position"]  # pince à mi-course
    return consignes
