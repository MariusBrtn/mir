"""Le clavier comme périphérique de téléopération."""
from __future__ import annotations
from mir_robot.teleop.teleoperator import Teleoperator
from mir_utils.keyboard_listener import Key

# nom des touches dans le dictionnaire renvoyé par read()
KEY_NAMES: dict[Key, str] = {
    Key.Left: "left", Key.Right: "right", Key.Up: "up", Key.Down: "down", Key.Space: "space",
    Key.Enter: "enter", Key.Tab: "tab", Key.Backspace: "backspace", Key.Delete: "delete",
    Key.Plus: "+", Key.Minus: "-",
}
KEY_NAMES.update({Key[c]: c.lower() for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
KEY_NAMES.update({Key[f"Digit{d}"]: str(d) for d in range(10)})


class KeyboardTeleoperator(Teleoperator):
    """read() : l'état des touches, True si la touche est enfoncée :
    {"left": False, "right": True, "up": False, "down": False, "space": False, "a": False, "1": False, ...}
    Échap est réservée : elle arrête la téléopération."""

    def connect(self) -> None:
        if self.keyboard is None:
            raise RuntimeError("aucun clavier fourni par MIR")
        super().connect()

    def read(self) -> dict[str, bool]:
        while self.keyboard.get_key() is not None:      # les appuis en attente ne servent pas : seul l'état compte
            pass
        return {name: self.keyboard.is_pressed(key) for key, name in KEY_NAMES.items()}
