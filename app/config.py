"""Typed access to the key/value ``settings`` table.

Defaults come from environment variables (so a container can be pre-seeded) and
are overridden by whatever the user saves in the web UI. Secret-valued keys are
transparently encrypted on write and decrypted on read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .db import Setting, SessionLocal, encrypt, decrypt

# Keys whose values must never be stored in plaintext.
SECRET_KEYS = {
    "qobuz_token",
    "qobuz_app_secret",
    "jellyfin_api_key",
    "admin_password_hash",
}

# key -> (env var, default)
DEFAULTS: dict[str, tuple[str, str]] = {
    "qobuz_email": ("QOBUZ_EMAIL", ""),
    "qobuz_token": ("", ""),
    "qobuz_app_id": ("QOBUZ_APP_ID", ""),
    "qobuz_app_secret": ("QOBUZ_APP_SECRET", ""),
    # Preferred download quality (Qobuz format_id): 27=Hi-Res<=192k, 7=Hi-Res<=96k,
    # 6=FLAC CD, 5=MP3 320. The client falls back to the best the track offers.
    "quality": ("QOBUZ_QUALITY", "27"),
    "sync_interval_hours": ("QOBUZ_SYNC_INTERVAL_HOURS", "6"),
    "jellyfin_url": ("JELLYFIN_URL", ""),
    "jellyfin_api_key": ("JELLYFIN_API_KEY", ""),
    "admin_password_hash": ("", ""),
}


def get(key: str, default: str | None = None) -> str:
    with SessionLocal() as s:
        row = s.get(Setting, key)
        if row is not None and row.value != "":
            return decrypt(row.value) if key in SECRET_KEYS else row.value
    env_var, fallback = DEFAULTS.get(key, ("", default or ""))
    if env_var:
        return os.environ.get(env_var, fallback)
    return fallback if default is None else default


def set(key: str, value: str) -> None:
    stored = encrypt(value) if key in SECRET_KEYS else value
    with SessionLocal() as s:
        row = s.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=stored)
            s.add(row)
        else:
            row.value = stored
        s.commit()


def set_many(values: dict[str, str]) -> None:
    for k, v in values.items():
        set(k, v)


def get_int(key: str, default: int) -> int:
    try:
        return int(get(key, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class QobuzConfig:
    email: str
    token: str
    app_id: str
    app_secret: str
    quality: int


def qobuz_config() -> QobuzConfig:
    return QobuzConfig(
        email=get("qobuz_email"),
        token=get("qobuz_token"),
        app_id=get("qobuz_app_id"),
        app_secret=get("qobuz_app_secret"),
        quality=get_int("quality", 27),
    )


def is_configured() -> bool:
    """True once we hold a usable Qobuz session (token + app credentials)."""
    cfg = qobuz_config()
    return bool(cfg.token and cfg.app_id and cfg.app_secret)
