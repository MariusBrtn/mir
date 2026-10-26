"""
Clé API du fournisseur de modèles (OpenAI), rangée dans le trousseau du système : Trousseau d'accès sur macOS,
Gestionnaire d'identification sur Windows, Secret Service sur Linux. Elle n'est jamais écrite dans un fichier de MIR
ni dans les journaux. La variable d'environnement OPENAI_API_KEY, si elle existe, est utilisée en priorité.
"""
from __future__ import annotations
import os

SERVICE = "MIR"
ACCOUNT = "openai_api_key"
ENV_VAR = "OPENAI_API_KEY"


def read_api_key() -> tuple[str | None, str | None]:
    """(clé, source) en une seule lecture du trousseau ; la source vaut « environment », « keychain » ou None.
    Sur macOS, chaque lecture peut faire demander le mot de passe de session : l'appeler le moins souvent possible."""
    key = os.environ.get(ENV_VAR)
    if key:
        return key, "environment"
    try:
        import keyring
        key = keyring.get_password(SERVICE, ACCOUNT)
    except Exception:
        return None, None
    return (key, "keychain") if key else (None, None)


def get_api_key() -> str | None:
    return read_api_key()[0]


def key_source() -> str | None:
    """« environment », « keychain » ou None (pas de clé)."""
    return read_api_key()[1]


def save_api_key(key: str) -> None:
    import keyring
    keyring.set_password(SERVICE, ACCOUNT, key.strip())


def delete_api_key() -> None:
    import keyring
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


def masked(key: str | None) -> str:
    """Pour l'affichage : « sk-…a1b2 »."""
    if not key:
        return ""
    return f"{key[:3]}…{key[-4:]}" if len(key) > 10 else "…"


def check_api_key(key: str) -> str | None:
    """Vérifie la clé auprès d'OpenAI. Renvoie None si elle est valable, sinon le message d'erreur."""
    from openai import OpenAI, AuthenticationError
    try:
        OpenAI(api_key=key.strip(), timeout=15).models.list()
        return None
    except AuthenticationError:
        return "Clé refusée par OpenAI."
    except Exception as e:
        return f"{type(e).__name__} : {e}"
