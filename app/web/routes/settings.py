"""Settings: Qobuz connect, download prefs, Jellyfin, and sync controls."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ... import config
from ...bandcamp import sync as bc_sync
from ...bandcamp.client import BandcampError
from ...paths import MUSIC_DIR
from ...qobuz.client import FORMATS, QobuzError
from ...sync import engine, jellyfin, scheduler
from .. import security
from ..render import render

router = APIRouter()

# Bandcamp download formats offered in the UI (value -> label).
BANDCAMP_FORMATS = {
    "flac": "FLAC (lossless)",
    "alac": "ALAC (Apple lossless .m4a)",
    "wav": "WAV (uncompressed)",
    "aiff-lossless": "AIFF (uncompressed)",
    "mp3-320": "MP3 320kbps",
    "mp3-v0": "MP3 V0 (VBR)",
    "vorbis": "Ogg Vorbis",
    "aac-hi": "AAC (high)",
}


def _settings_context(request: Request, **extra):
    ctx = {
        "active": "settings",
        "connected": config.is_configured(),
        "email": config.get("qobuz_email"),
        "quality": config.get_int("quality", 27),
        "formats": FORMATS,
        "interval": config.get_int("sync_interval_hours", 6),
        "app_id": config.get("qobuz_app_id"),
        "has_app_secret": bool(config.get("qobuz_app_secret")),
        "jellyfin_url": config.get("jellyfin_url"),
        "has_jellyfin_key": bool(config.get("jellyfin_api_key")),
        "music_dir": str(MUSIC_DIR),
        "next_run": scheduler.next_run_time(),
        # Bandcamp
        "bandcamp_connected": config.bandcamp_is_configured(),
        "bandcamp_username": config.get("bandcamp_username"),
        "bandcamp_format": config.get("bandcamp_format", "flac"),
        "bandcamp_formats": BANDCAMP_FORMATS,
    }
    ctx.update(extra)
    return render(request, "settings.html", **ctx)


@router.get("/settings")
def settings_page(request: Request):
    return _settings_context(request)


@router.post("/settings/connect")
def connect(
    request: Request,
    method: str = Form("token"),
    email: str = Form(""),
    password: str = Form(""),
    token: str = Form(""),
):
    try:
        if method == "token":
            if not token.strip():
                raise QobuzError("Paste your auth token first.")
            message = engine.connect(token=token.strip())
        else:
            if not (email.strip() and password):
                raise QobuzError("Enter both email and password.")
            message = engine.connect(email=email.strip(), password=password)
        return _settings_context(request, notice=("success", message))
    except QobuzError as e:
        return _settings_context(request, notice=("error", f"Connection failed: {e}"))
    except Exception as e:  # bundle extraction / network
        return _settings_context(request, notice=("error", f"Could not connect: {e}"))


@router.post("/settings/disconnect")
def disconnect(request: Request):
    config.set_many({"qobuz_token": "", "qobuz_app_secret": ""})
    return _settings_context(request, notice=("success", "Disconnected from Qobuz."))


@router.post("/settings/bandcamp/connect")
def bandcamp_connect(request: Request, identity: str = Form("")):
    try:
        if not identity.strip():
            raise BandcampError("Paste your Bandcamp identity cookie first.")
        message = bc_sync.connect(identity.strip())
        return _settings_context(request, notice=("success", message))
    except BandcampError as e:
        return _settings_context(request, notice=("error", f"Bandcamp connection failed: {e}"))
    except Exception as e:  # network / parsing
        return _settings_context(request, notice=("error", f"Could not connect to Bandcamp: {e}"))


@router.post("/settings/bandcamp/disconnect")
def bandcamp_disconnect(request: Request):
    config.set_many({"bandcamp_identity": "", "bandcamp_fan_id": "", "bandcamp_username": ""})
    return _settings_context(request, notice=("success", "Disconnected from Bandcamp."))


@router.post("/settings/save")
def save(
    request: Request,
    quality: str = Form("27"),
    interval: str = Form("6"),
    app_id: str = Form(""),
    app_secret: str = Form(""),
    jellyfin_url: str = Form(""),
    jellyfin_api_key: str = Form(""),
    bandcamp_format: str = Form("flac"),
):
    updates = {
        "quality": quality,
        "sync_interval_hours": interval,
        "qobuz_app_id": app_id.strip(),
        "jellyfin_url": jellyfin_url.strip(),
        "bandcamp_format": bandcamp_format,
    }
    # Only overwrite secrets when a new value is supplied (blank = keep existing).
    if app_secret.strip():
        updates["qobuz_app_secret"] = app_secret.strip()
    if jellyfin_api_key.strip():
        updates["jellyfin_api_key"] = jellyfin_api_key.strip()
    config.set_many(updates)
    scheduler.reschedule()
    return _settings_context(request, notice=("success", "Settings saved."))


@router.post("/settings/test-jellyfin")
def test_jellyfin(url: str = Form(""), api_key: str = Form("")):
    # Fall back to stored key if the field was left blank (masked).
    key = api_key.strip() or config.get("jellyfin_api_key")
    ok, message = jellyfin.test_connection(url.strip(), key)
    return JSONResponse({"ok": ok, "message": message})


@router.post("/settings/sync-now")
def sync_now():
    scheduler.trigger_now("manual")
    return RedirectResponse("/activity", status_code=303)
