"""Un bras leader comme périphérique de téléopération : un bras MIR qu'on manipule à la main."""
from __future__ import annotations
from typing import Any
from mir_robot.teleop.teleoperator import Teleoperator


class LeaderArmTeleoperator(Teleoperator):
    """read() : les positions des articulations du bras leader, {"joint_1.position": 12.3, ...}.
    Sa configuration est leader_arm.json, dans le dossier teleop du robot (créée par « Créer le bras leader »).
    Dès qu'elle existe, MIR propose la téléopération « Bras leader » (recopie) : rien à écrire pour recopier.
    C'est toujours le bras leader réel, même quand le robot piloté est simulé. Ses servos restent sans couple."""
    config_name = "leader_arm"

    def connect(self) -> None:
        from mir_robot.mir_robot import mirRobot, mirRobotConfig
        path = self.config_file()
        if not path.exists():
            raise FileNotFoundError("Le bras leader n'est pas encore créé : construisez-le avec « Créer le bras leader » "
                                    f"(sa configuration sera enregistrée dans {path}).")
        self._robot = mirRobot(mirRobotConfig.load(str(path)))
        self._robot.connect()
        try:
            self._robot.configure()         # laisse les servos sans couple : on les manipule à la main
            if not self._robot.is_calibrated:
                raise RuntimeError("Les servos du bras leader ne sont pas calibrés : reconstruisez-le "
                                   "avec « Créer le bras leader ».")
            self._robot.enable_observations_by_name([n for n in self._robot.get_observables() if n.endswith(".position")])
        except BaseException:
            self._robot.disconnect()
            raise
        super().connect()

    def read(self) -> dict[str, Any]:
        return self._robot.get_observation()

    def disconnect(self) -> None:
        if getattr(self, "_robot", None) is not None:
            self._robot.disconnect()
            self._robot = None
        super().disconnect()
