"""Bandcamp sync: connect, refresh the purchase catalog, download what's missing.

Mirrors the Qobuz path in ``sync.engine`` but at album grain. The engine calls
:func:`run` inside a single sync run; the settings routes call :func:`connect`
and :func:`build_client`. Progress is written into the engine's shared state
object passed in (kept as a parameter so this module never imports the engine).
"""

from __future__ import annotations

import time

from .. import applog, config
from ..db import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PENDING,
    BandcampItem,
    SessionLocal,
    utcnow,
)
from . import download as bc_download
from .client import BandcampAuthError, BandcampClient, BandcampError
from .models import BandcampPurchase

_MAX_ATTEMPTS = 4
_RATE_LIMIT_SECONDS = 1.0


# --------------------------------------------------------------------------- #
# Connect
# --------------------------------------------------------------------------- #
def connect(identity: str) -> str:
    client = BandcampClient(identity)
    try:
        fan_id, username = client.get_fan()
        config.set_many(
            {
                "bandcamp_identity": identity.strip(),
                "bandcamp_fan_id": fan_id,
                "bandcamp_username": username,
            }
        )
        applog.success(f"Connected to Bandcamp as {username or fan_id}")
        return f"Connected to Bandcamp as {username or fan_id}"
    finally:
        client.close()


def build_client() -> BandcampClient:
    cfg = config.bandcamp_config()
    if not cfg.identity:
        raise BandcampError("Bandcamp is not connected — add your identity cookie in Settings")
    return BandcampClient(cfg.identity)


# --------------------------------------------------------------------------- #
# Catalog refresh
# --------------------------------------------------------------------------- #
def _upsert(p: BandcampPurchase) -> bool:
    with SessionLocal() as s:
        existing = s.get(BandcampItem, p.item_id)
        if existing is not None:
            existing.band = p.band or existing.band
            existing.title = p.title or existing.title
            existing.art_url = p.art_url or existing.art_url
            existing.redownload_url = p.redownload_url or existing.redownload_url
            s.commit()
            return False
        s.add(
            BandcampItem(
                item_id=p.item_id,
                item_type=p.item_type,
                band=p.band,
                title=p.title,
                art_url=p.art_url,
                redownload_url=p.redownload_url,
                status=STATUS_PENDING,
                purchased_at=utcnow(),
            )
        )
        s.commit()
        return True


def refresh_catalog(client: BandcampClient) -> int:
    cfg = config.bandcamp_config()
    new_count = 0
    for p in client.iter_purchases(cfg.fan_id, cfg.username):
        if _upsert(p):
            new_count += 1
    return new_count


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #
def _pending() -> list[BandcampItem]:
    with SessionLocal() as s:
        return list(
            s.query(BandcampItem)
            .filter(BandcampItem.status.in_([STATUS_PENDING, STATUS_ERROR]))
            .filter(BandcampItem.attempts < _MAX_ATTEMPTS)
            .order_by(BandcampItem.band, BandcampItem.title)
            .all()
        )


def _set_status(item_id: str, **fields) -> None:
    with SessionLocal() as s:
        row = s.get(BandcampItem, item_id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


def process_downloads(client: BandcampClient, fmt: str, state) -> int:
    rows = _pending()
    state.total = len(rows)
    state.done = 0
    downloaded = 0

    for row in rows:
        item = BandcampPurchase(
            item_id=row.item_id,
            item_type=row.item_type,
            band=row.band,
            title=row.title,
            art_url=row.art_url,
            redownload_url=row.redownload_url,
        )
        state.current = f"{item.band} — {item.title}"
        state.phase = "Bandcamp: downloading"
        _set_status(row.item_id, status="downloading", attempts=row.attempts + 1)
        try:
            path, size, actual_fmt = bc_download.download_item(client, item, fmt)
            _set_status(
                row.item_id,
                status=STATUS_DONE,
                file_path=str(path),
                file_size=size,
                fmt=actual_fmt,
                error="",
                downloaded_at=utcnow(),
            )
            downloaded += 1
            state.new_downloads += 1
            applog.info(f"Downloaded (Bandcamp) {item.band} — {item.title}")
        except (BandcampError, OSError) as e:
            _set_status(row.item_id, status=STATUS_ERROR, error=str(e)[:500])
            state.errors += 1
            applog.warning(f"Failed (Bandcamp) {item.band} — {item.title}: {e}")
        finally:
            state.done += 1
            time.sleep(_RATE_LIMIT_SECONDS)

    return downloaded


# --------------------------------------------------------------------------- #
# Top-level (called by the engine within a sync run)
# --------------------------------------------------------------------------- #
def run(state) -> dict:
    """Refresh + download the Bandcamp collection. Returns a small result dict."""
    if not config.bandcamp_is_configured():
        return {"skipped": True}

    try:
        client = build_client()
    except BandcampError as e:
        applog.warning(f"Bandcamp sync skipped: {e}")
        return {"error": str(e)}

    try:
        state.phase = "Bandcamp: refreshing catalog"
        try:
            new = refresh_catalog(client)
        except BandcampAuthError as e:
            applog.error(f"Bandcamp auth failed — reconnect required: {e}")
            return {"error": "auth"}
        applog.info(f"Bandcamp catalog refreshed: {new} new purchase(s)")

        downloaded = process_downloads(client, config.bandcamp_config().fmt, state)
        return {"downloaded": downloaded, "new": new}
    finally:
        client.close()
