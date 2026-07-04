"""Trigger a Jellyfin library scan after new files are downloaded.

Fires a single ``POST /Library/Refresh`` per sync run (debounced by the engine,
not per track). Configured with a base URL and API key in Settings; a no-op when
either is missing. Never raises into the sync — failures are logged and swallowed.
"""

from __future__ import annotations

import httpx

from .. import applog, config


def _base_and_key() -> tuple[str, str]:
    url = config.get("jellyfin_url").rstrip("/")
    key = config.get("jellyfin_api_key")
    return url, key


def is_configured() -> bool:
    url, key = _base_and_key()
    return bool(url and key)


def test_connection(url: str, api_key: str) -> tuple[bool, str]:
    """Return (ok, message) — message is the server name/version or the error."""
    url = url.rstrip("/")
    if not url or not api_key:
        return False, "URL and API key are required"
    try:
        resp = httpx.get(
            f"{url}/System/Info",
            headers={"X-Emby-Token": api_key},
            timeout=15,
        )
        if resp.status_code == 401:
            return False, "Unauthorized — check the API key"
        resp.raise_for_status()
        info = resp.json()
        return True, f"{info.get('ServerName', 'Jellyfin')} {info.get('Version', '')}".strip()
    except httpx.HTTPError as e:
        return False, f"Connection failed: {e}"


def trigger_scan() -> bool:
    """Kick off a library refresh. Returns True if the request was accepted."""
    if not is_configured():
        return False
    url, key = _base_and_key()
    try:
        resp = httpx.post(
            f"{url}/Library/Refresh",
            headers={"X-Emby-Token": key},
            timeout=15,
        )
        resp.raise_for_status()
        applog.info("Triggered Jellyfin library scan")
        return True
    except httpx.HTTPError as e:
        applog.warning(f"Jellyfin scan trigger failed: {e}")
        return False
