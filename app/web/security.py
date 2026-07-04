"""Admin password gate for the web UI.

The UI stores Qobuz credentials, so it sits behind a single admin password. The
password is stored as a PBKDF2 hash (itself Fernet-encrypted via the settings
layer). On first run no password exists and the login page becomes a setup page.
"""

from __future__ import annotations

import hashlib
import hmac
import os

from .. import config

_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return hmac.compare_digest(actual, expected)


def is_admin_configured() -> bool:
    return bool(config.get("admin_password_hash"))


def set_admin_password(password: str) -> None:
    config.set("admin_password_hash", hash_password(password))


def check_admin_password(password: str) -> bool:
    stored = config.get("admin_password_hash")
    return bool(stored) and verify_password(password, stored)
