import sys
import tty
import termios
from queue import Queue
from enum import Enum, auto
from pynput import keyboard

class Key(Enum):
    """Énumération des touches supportées"""
    # Lettres
    A = auto()
    B = auto()
    C = auto()
    D = auto()
    E = auto()
    F = auto()
    G = auto()
    H = auto()
    I = auto() # noqa: E741
    J = auto()
    K = auto()
    L = auto()
    M = auto()
    N = auto()
    O = auto() # noqa: E741
    P = auto()
    Q = auto() # noqa: E741
    R = auto()
    S = auto()
    T = auto()
    U = auto()
    V = auto()
    W = auto()
    X = auto()
    Y = auto()
    Z = auto()
    
    # Chiffres
    Digit0 = auto()
    Digit1 = auto()
    Digit2 = auto()
    Digit3 = auto()
    Digit4 = auto()
    Digit5 = auto()
    Digit6 = auto()
    Digit7 = auto()
    Digit8 = auto()
    Digit9 = auto()
    
    # Touches spéciales
    Space = auto()
    Enter = auto()
    Tab = auto()
    Backspace = auto()
    Esc = auto()
    Delete = auto()
    
    # Touches fléchées
    Left = auto()
    Right = auto()
    Up = auto()
    Down = auto()
    
    # Autres
    Plus = auto()
    Minus = auto()
    Dot = auto()
    Comma = auto()
    Colon = auto()
    Semicolon = auto()
    Apostrophe = auto()
    Quote = auto()
    Slash = auto()
    Backslash = auto()
    LBracket = auto()
    RBracket = auto()
    Equal = auto()
    
    # Touches non reconnues
    Unknown = auto()


SPECIAL_CHARS = {
    '+': Key.Plus, '-': Key.Minus, '.': Key.Dot, ',': Key.Comma, ':': Key.Colon, ';': Key.Semicolon,
    "'": Key.Apostrophe, '"': Key.Quote, '/': Key.Slash, '\\': Key.Backslash, '[': Key.LBracket,
    ']': Key.RBracket, '=': Key.Equal,
}


def key_from_char(char):
    """Touche correspondant à un caractère (lettre, chiffre, ponctuation), None sinon."""
    if not char or len(char) != 1:
        return None
    if 'a' <= char <= 'z' or 'A' <= char <= 'Z':
        return Key[char.upper()]
    if '0' <= char <= '9':
        return Key[f'Digit{char}']
    return SPECIAL_CHARS.get(char)


class KeyQueue:
    """Touches fournies par une application (fenêtre Qt), avec la même interface que KeyboardListener.
    L'application appelle press(key) / release(key) ; la commande appelle get_key() ou is_pressed(key).
    Contrairement à KeyboardListener (pynput), aucun thread ni permission système : c'est la solution dans une
    application graphique, où pynput fait planter macOS quand il est démarré hors du thread principal."""

    def __init__(self):
        self.key_queue = Queue()
        self._pressed = set()

    def start(self):
        self.clear()

    def stop(self):
        pass

    def clear(self):
        while not self.key_queue.empty():
            self.key_queue.get_nowait()
        self._pressed.clear()

    def press(self, key):
        self._pressed.add(key)
        self.key_queue.put(key)

    def release(self, key):
        self._pressed.discard(key)

    def is_pressed(self, key) -> bool:
        """True tant que la touche est enfoncée (pour avancer en continu)."""
        return key in self._pressed

    def get_key(self):
        """Prochaine touche pressée, ou None. Non bloquant."""
        try:
            return self.key_queue.get_nowait()
        except Exception:
            return None

    def wait_key(self, timeout=None):
        try:
            return self.key_queue.get(timeout=timeout)
        except Exception:
            return None


class LazyKeyboardListener:
    """Clavier d'un script : KeyboardListener (pynput) démarré seulement si la commande s'en sert."""

    def __init__(self):
        self._listener = None

    def _ensure(self):
        if self._listener is None:
            self._listener = KeyboardListener()
            self._listener.start()
        return self._listener

    def get_key(self):
        return self._ensure().get_key()

    def wait_key(self, timeout=None):
        return self._ensure().wait_key(timeout)

    def is_pressed(self, key) -> bool:
        return self._ensure().is_pressed(key)

    def start(self):
        pass

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class KeyboardListener:
    """Capture les touches et les stocke dans une queue non-bloquante"""
    
    def __init__(self):
        self.key_queue = Queue()
        self.listener = None
        self._running = False
        self._pressed = set()       # touches enfoncées
        self.old_settings = None  # Pour restaurer le terminal
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.stop()
        except Exception:
            pass  # Silencieux en cas d'erreur
    
    def start(self):
        """Démarre l'écoute des touches en arrière-plan et active le mode raw"""
        if self._running:
            return
        qt = sys.modules.get("PySide6.QtWidgets")
        if qt is not None and qt.QApplication.instance() is not None:
            # dans une application Qt, pynput fait planter macOS (écoute démarrée hors du thread principal)
            raise RuntimeError("KeyboardListener ne peut pas être utilisé dans l'application MIR : "
                               "utiliser robot.clavier dans la commande (voir le modèle « Nouvelle… »)")
        
        # Sauvegarde et activation du mode raw (désactive l'echo)
        try:
            self.old_settings = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
        except Exception:
            pass  # Si pas possible (ex: pas de terminal), on continue quand même
        
        self._running = True
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.start()
    
    def stop(self):
        """Arrête l'écoute des touches et restaure le terminal"""
        if self._running and self.listener:
            self._running = False
            self.listener.stop()
            self.listener.join(timeout=0.5)  # Attendre que le listener s'arrête
        
        # Restaure les paramètres du terminal
        if self.old_settings:
            try:
                import sys
                sys.stdout.flush()
                sys.stderr.flush()
                # TCSAFLUSH vide aussi le buffer d'entrée
                termios.tcsetattr(sys.stdin, termios.TCSAFLUSH, self.old_settings)
                # Un petit délai pour laisser le terminal se stabiliser
                import time
                time.sleep(0.05)
            except Exception:
                pass
    
    def _on_press(self, key):
        """Callback appelé à chaque touche pressée"""
        parsed_key = self._parse_key(key)
        if parsed_key:
            self._pressed.add(parsed_key)
            self.key_queue.put(parsed_key)

    def _on_release(self, key):
        self._pressed.discard(self._parse_key(key))

    def is_pressed(self, key) -> bool:
        """True tant que la touche est enfoncée."""
        return key in self._pressed
    
    def _parse_key(self, pynput_key):
        """Convertit une touche pynput en enum Key"""
        try:
            # Touche avec caractère
            if isinstance(pynput_key, keyboard.Key):
                key_map = {
                    keyboard.Key.left: Key.Left,
                    keyboard.Key.right: Key.Right,
                    keyboard.Key.up: Key.Up,
                    keyboard.Key.down: Key.Down,
                    keyboard.Key.enter: Key.Enter,
                    keyboard.Key.space: Key.Space,
                    keyboard.Key.tab: Key.Tab,
                    keyboard.Key.backspace: Key.Backspace,
                    keyboard.Key.delete: Key.Delete,
                    keyboard.Key.esc: Key.Esc,
                }
                return key_map.get(pynput_key)
            else:
                # pynput.keyboard.KeyCode : caractère pressé
                return key_from_char(pynput_key.char)
        except AttributeError:
            pass
        
        return None
    
    def get_key(self):
        """
        Retourne la prochaine touche de la queue, ou None si vide.
        Non-bloquant.
        """
        try:
            return self.key_queue.get_nowait()
        except Exception:
            return None
    
    def wait_key(self, timeout=None):
        """
        Attend une touche (bloquant avec timeout optionnel).
        timeout en secondes.
        """
        try:
            return self.key_queue.get(timeout=timeout)
        except Exception:
            return None


# ==================== Exemple d'utilisation ====================
if __name__ == "__main__":
    import time
    
    print("Appuyez sur des touches (q pour quitter) :")
    print("- Flèches gauche/droite/haut/bas")
    print("- Lettres (A-Z)")
    print("- Chiffres (0-9)")
    print("- Espace, Entrée, Échap")
    print()
    
    with KeyboardListener() as kbd:
        while True:
            # Mode non-bloquant : vérifier s'il y a une touche
            key = kbd.get_key()
            
            if key is not None:
                print(f"Touche pressée : {key}\r")
                
                if key == Key.Esc or key == Key.Q:
                    print("Sortie...")
                    break
            else:
                # Pas de touche, faire quelque chose d'autre
                time.sleep(0.01)  # Éviter de consommer 100% CPU

