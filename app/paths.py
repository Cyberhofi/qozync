"""Filesystem locations and the encryption key.

Everything the service persists lives under two directories:

* ``CONFIG_DIR`` — the SQLite database, the auto-generated Fernet key.
* ``MUSIC_DIR``  — the downloaded, tagged audio files.

In Docker these are mounted volumes (``/config`` and ``/music``). For local
development on Windows/macOS they default to ``./config`` and ``./music`` next
to the project so nothing needs to be configured to run.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

_BASE = Path(__file__).resolve().parent.parent


def _dir_from_env(var: str, default: Path) -> Path:
    path = Path(os.environ.get(var, str(default)))
    path.mkdir(parents=True, exist_ok=True)
    return path


CONFIG_DIR: Path = _dir_from_env("QOBUZ_CONFIG_DIR", _BASE / "config")
MUSIC_DIR: Path = _dir_from_env("QOBUZ_MUSIC_DIR", _BASE / "music")

DB_PATH: Path = CONFIG_DIR / "qobuz.db"


def load_or_create_key() -> bytes:
    """Return the Fernet key used to encrypt secrets at rest.

    Preference order: ``SECRET_KEY`` env var, then a ``secret.key`` file in the
    config volume, otherwise generate one and persist it (so restarts can still
    decrypt previously stored tokens).
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key.encode() if not isinstance(env_key, bytes) else env_key

    key_file = CONFIG_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_bytes().strip()

    key = Fernet.generate_key()
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass  # best-effort; not supported on all platforms
    return key
