"""Orchestration: connect, refresh the purchase catalog, download what's missing.

A single global lock guarantees only one sync runs at a time (the scheduler and
the UI's "Sync now" both call :func:`run_sync`). Live progress is exposed via
:data:`STATE` for the Activity page.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from .. import applog, config
from ..db import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_SKIPPED,
    SessionLocal,
    Track,
    utcnow,
)
from ..qobuz import bundle
from ..qobuz.client import AuthError, QobuzClient, QobuzError, resolve_working_secret
from ..qobuz.models import QobuzTrack
from . import downloader, jellyfin

_MAX_ATTEMPTS = 4
_RATE_LIMIT_SECONDS = 0.7  # spacing between getFileUrl calls to stay polite

_lock = threading.Lock()


@dataclass
class SyncState:
    running: bool = False
    trigger: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    phase: str = "idle"
    current: str = ""
    total: int = 0
    done: int = 0
    new_downloads: int = 0
    errors: int = 0
    last_result: str = ""

    def snapshot(self) -> dict:
        return asdict(self)


STATE = SyncState()


# --------------------------------------------------------------------------- #
# Connect / credential bootstrap
# --------------------------------------------------------------------------- #
def _resolve_app_credentials() -> tuple[str, list[str]]:
    """Return (app_id, candidate_secrets), preferring manual overrides."""
    manual_id = config.get("qobuz_app_id")
    manual_secret = config.get("qobuz_app_secret")
    if manual_id and manual_secret:
        return manual_id, [manual_secret]
    creds = bundle.fetch_credentials()
    app_id = manual_id or creds.app_id
    secrets = [manual_secret] + creds.secrets if manual_secret else creds.secrets
    return app_id, secrets


def _first_owned_track_id(client: QobuzClient) -> Optional[int]:
    album_ids, track_ids = client.get_user_purchase_ids()
    if track_ids:
        return int(track_ids[0])
    for aid in album_ids:
        full = client.get_album(aid)
        items = (full.get("tracks") or {}).get("items") or []
        if items:
            return int(items[0]["id"])
    return None


def connect(email: str = "", password: str = "", token: str = "") -> str:
    """Establish a Qobuz session and persist it.

    Prefers a browser-obtained ``token`` (reliable); falls back to email/password
    (often blocked by Qobuz since April 2026). Resolves a working app secret and
    stores everything. Raises on failure so the UI can show the reason.
    """
    app_id, secrets = _resolve_app_credentials()
    client = QobuzClient(app_id=app_id)
    try:
        if token.strip():
            user = client.login_with_token(token)
            email = email or (user.get("user") or user).get("email", "") or "token user"
        else:
            client.login(email, password)
        token = client.token

        sample_id = _first_owned_track_id(client)
        if len(secrets) == 1:
            secret = secrets[0]
        elif sample_id is not None:
            secret = resolve_working_secret(app_id, token, secrets, sample_id)
        else:
            secret = secrets[0]  # nothing to validate against yet; trust first

        config.set_many(
            {
                "qobuz_email": email,
                "qobuz_token": token,
                "qobuz_app_id": app_id,
                "qobuz_app_secret": secret,
            }
        )
        applog.success(f"Connected to Qobuz as {email}")
        return "Connected successfully"
    finally:
        client.close()


def build_client() -> QobuzClient:
    cfg = config.qobuz_config()
    if not (cfg.token and cfg.app_id and cfg.app_secret):
        raise QobuzError("Qobuz is not connected — enter your credentials in Settings")
    return QobuzClient(app_id=cfg.app_id, app_secret=cfg.app_secret, token=cfg.token)


# --------------------------------------------------------------------------- #
# Catalog refresh
# --------------------------------------------------------------------------- #
def _upsert(track: QobuzTrack) -> bool:
    """Insert the track if new. Returns True if it was newly added."""
    with SessionLocal() as s:
        existing = s.get(Track, track.id)
        if existing is not None:
            # Keep metadata fresh but don't disturb download status.
            existing.title = track.title or existing.title
            existing.artist = track.artist or existing.artist
            existing.album = track.album or existing.album
            existing.album_artist = track.album_artist or existing.album_artist
            existing.cover_url = track.cover_url or existing.cover_url
            s.commit()
            return False
        s.add(
            Track(
                track_id=track.id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                album_artist=track.album_artist,
                album_id=track.album_id,
                composer=track.composer,
                year=track.year,
                track_number=track.track_number,
                disc_number=track.disc_number,
                total_tracks=track.total_tracks,
                duration=track.duration,
                cover_url=track.cover_url,
                status=STATUS_PENDING,
                purchased_at=utcnow(),
            )
        )
        s.commit()
        return True


def refresh_catalog(client: QobuzClient) -> int:
    """Enumerate everything owned and upsert each track. Returns new count.

    Source of truth is ``getUserPurchasesIds`` (albums + track ids). Albums are
    expanded to their tracks (rich album metadata); standalone track purchases
    are fetched individually. A track appearing in both — an album track that's
    also listed as a purchased track — is handled once via ``seen``.
    """
    new_count = 0
    seen: set[int] = set()
    album_ids, track_ids = client.get_user_purchase_ids()

    for aid in album_ids:
        try:
            full = client.get_album(aid)
        except QobuzError as e:
            applog.warning(f"Could not load album {aid}: {e}")
            continue
        for t in (full.get("tracks") or {}).get("items") or []:
            tid = int(t["id"])
            seen.add(tid)
            if _upsert(QobuzTrack.from_json(t, album=full)):
                new_count += 1

    for tid in track_ids:
        tid = int(tid)
        if tid in seen:
            continue
        seen.add(tid)
        try:
            t = client.get_track(tid)
        except QobuzError as e:
            applog.warning(f"Could not load track {tid}: {e}")
            continue
        if _upsert(QobuzTrack.from_json(t)):
            new_count += 1

    return new_count


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #
def _pending_tracks() -> list[Track]:
    with SessionLocal() as s:
        return list(
            s.query(Track)
            .filter(Track.status.in_([STATUS_PENDING, STATUS_ERROR]))
            .filter(Track.attempts < _MAX_ATTEMPTS)
            .order_by(Track.album_artist, Track.album, Track.disc_number, Track.track_number)
            .all()
        )


def _to_model(row: Track) -> QobuzTrack:
    return QobuzTrack(
        id=row.track_id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        album_artist=row.album_artist,
        album_id=row.album_id,
        composer=row.composer,
        year=row.year,
        track_number=row.track_number,
        disc_number=row.disc_number,
        total_tracks=row.total_tracks,
        duration=row.duration,
        cover_url=row.cover_url,
    )


def _set_status(track_id: int, **fields) -> None:
    with SessionLocal() as s:
        row = s.get(Track, track_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


def process_downloads(client: QobuzClient, preferred_format: int) -> int:
    """Download every pending/failed track. Returns count successfully downloaded."""
    rows = _pending_tracks()
    STATE.total = len(rows)
    STATE.done = 0
    downloaded = 0

    for row in rows:
        model = _to_model(row)
        STATE.current = f"{model.artist} — {model.title}"
        STATE.phase = "downloading"
        _set_status(row.track_id, status="downloading", attempts=row.attempts + 1)
        try:
            path, fmt, size = downloader.download(client, model, preferred_format)
            _set_status(
                row.track_id,
                status=STATUS_DONE,
                file_path=str(path),
                file_size=size,
                format_id=fmt,
                error="",
                downloaded_at=utcnow(),
            )
            downloaded += 1
            STATE.new_downloads += 1
            applog.info(f"Downloaded {model.artist} — {model.title}")
        except downloader.NotOwned:
            _set_status(row.track_id, status=STATUS_SKIPPED, error="not owned (sample only)")
        except (QobuzError, OSError) as e:
            _set_status(row.track_id, status=STATUS_ERROR, error=str(e)[:500])
            STATE.errors += 1
            applog.warning(f"Failed {model.artist} — {model.title}: {e}")
        finally:
            STATE.done += 1
            time.sleep(_RATE_LIMIT_SECONDS)

    return downloaded


# --------------------------------------------------------------------------- #
# Per-source runs
# --------------------------------------------------------------------------- #
def _run_qobuz() -> dict:
    """Refresh + download the Qobuz catalog. Skipped if not connected."""
    if not config.is_configured():
        return {"skipped": True}
    client = build_client()
    try:
        STATE.phase = "Qobuz: refreshing catalog"
        try:
            new_in_catalog = refresh_catalog(client)
        except AuthError as e:
            applog.error(f"Qobuz auth failed — reconnect required: {e}")
            return {"error": "auth"}
        applog.info(f"Qobuz catalog refreshed: {new_in_catalog} new purchase(s)")
        downloaded = process_downloads(client, config.qobuz_config().quality)
        return {"downloaded": downloaded, "new": new_in_catalog}
    finally:
        client.close()


def _run_bandcamp() -> dict:
    # Imported lazily so this module never hard-depends on the Bandcamp source.
    from ..bandcamp import sync as bc_sync

    return bc_sync.run(STATE)


# --------------------------------------------------------------------------- #
# Top-level run
# --------------------------------------------------------------------------- #
def run_sync(trigger: str = "manual") -> dict:
    """Run one full sync across all connected sources.

    Non-blocking-safe: returns immediately if a run is already in progress.
    """
    if not _lock.acquire(blocking=False):
        applog.info("Sync already in progress; ignoring trigger")
        return {"skipped": True, "reason": "already running"}

    STATE.running = True
    STATE.trigger = trigger
    STATE.started_at = utcnow().isoformat()
    STATE.finished_at = None
    STATE.phase = "starting"
    STATE.current = ""
    STATE.new_downloads = 0
    STATE.errors = 0
    STATE.done = 0
    STATE.total = 0
    applog.info(f"Sync started ({trigger})")

    total_downloaded = 0
    parts: list[str] = []
    try:
        for name, runner in (("Qobuz", _run_qobuz), ("Bandcamp", _run_bandcamp)):
            try:
                res = runner()
            except Exception as e:  # one source failing must not abort the other
                applog.error(f"{name} sync error: {e}")
                parts.append(f"{name}: error")
                continue
            if res.get("skipped"):
                continue
            if res.get("error"):
                parts.append(f"{name}: {res['error']}")
                continue
            total_downloaded += res.get("downloaded", 0)
            parts.append(f"{name}: {res.get('downloaded', 0)} dl, {res.get('new', 0)} new")

        if total_downloaded > 0:
            jellyfin.trigger_scan()

        STATE.last_result = " · ".join(parts) if parts else "nothing to sync (no sources connected)"
        applog.success(f"Sync finished: {STATE.last_result} ({STATE.errors} error(s))")
        return {"downloaded": total_downloaded, "errors": STATE.errors, "result": STATE.last_result}
    finally:
        STATE.running = False
        STATE.phase = "idle"
        STATE.current = ""
        STATE.finished_at = utcnow().isoformat()
        _lock.release()
