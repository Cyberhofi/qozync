"""Source-agnostic views over the catalog for the web layer.

Qobuz (per-track ``Track``) and Bandcamp (per-item ``BandcampItem``) live in
separate tables; this module presents them as one homogeneous list of rows so
the dashboard, library, and activity pages don't need to know about sources.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, or_, select

from .db import (
    STATUS_DONE,
    STATUS_DOWNLOADING,
    STATUS_ERROR,
    STATUS_PENDING,
    BandcampItem,
    SessionLocal,
    Track,
)


def _track_row(t: Track) -> dict[str, Any]:
    return {
        "source": "qobuz",
        "id": f"qobuz:{t.track_id}",
        "kind": "track",
        "title": t.title,
        "artist": t.artist,
        "album": t.album,
        "year": t.year,
        "status": t.status,
        "size": t.file_size,
        "downloaded_at": t.downloaded_at,
    }


def _bc_row(b: BandcampItem) -> dict[str, Any]:
    return {
        "source": "bandcamp",
        "id": f"bandcamp:{b.item_id}",
        "kind": b.item_type,
        "title": b.title,
        "artist": b.band,
        "album": b.title if b.item_type == "album" else "",
        "year": b.year,
        "status": b.status,
        "size": b.file_size,
        "downloaded_at": b.downloaded_at,
    }


def counts() -> dict[str, int]:
    """Combined per-status counts across both sources."""
    out: dict[str, int] = {}
    with SessionLocal() as s:
        for model in (Track, BandcampItem):
            for status, n in s.query(model.status, func.count()).group_by(model.status).all():
                out[status] = out.get(status, 0) + n
    return out


def total_downloaded_size() -> int:
    with SessionLocal() as s:
        q = s.scalar(
            select(func.coalesce(func.sum(Track.file_size), 0)).where(Track.status == STATUS_DONE)
        )
        b = s.scalar(
            select(func.coalesce(func.sum(BandcampItem.file_size), 0)).where(
                BandcampItem.status == STATUS_DONE
            )
        )
    return int(q or 0) + int(b or 0)


def recent_downloads(limit: int = 10) -> list[dict[str, Any]]:
    with SessionLocal() as s:
        tracks = s.scalars(
            select(Track).where(Track.status == STATUS_DONE)
            .order_by(Track.downloaded_at.desc()).limit(limit)
        ).all()
        items = s.scalars(
            select(BandcampItem).where(BandcampItem.status == STATUS_DONE)
            .order_by(BandcampItem.downloaded_at.desc()).limit(limit)
        ).all()
    rows = [_track_row(t) for t in tracks] + [_bc_row(b) for b in items]
    rows.sort(key=lambda r: (r["downloaded_at"] is not None, r["downloaded_at"]), reverse=True)
    return rows[:limit]


def library_page(
    status: str = "", q: str = "", source: str = "", page: int = 1, size: int = 100
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    with SessionLocal() as s:
        if source in ("", "qobuz"):
            stmt = select(Track)
            if status:
                stmt = stmt.where(Track.status == status)
            if q:
                like = f"%{q}%"
                stmt = stmt.where(
                    or_(Track.title.ilike(like), Track.artist.ilike(like), Track.album.ilike(like))
                )
            rows += [_track_row(t) for t in s.scalars(stmt).all()]
        if source in ("", "bandcamp"):
            stmt = select(BandcampItem)
            if status:
                stmt = stmt.where(BandcampItem.status == status)
            if q:
                like = f"%{q}%"
                stmt = stmt.where(
                    or_(BandcampItem.title.ilike(like), BandcampItem.band.ilike(like))
                )
            rows += [_bc_row(b) for b in s.scalars(stmt).all()]

    rows.sort(key=lambda r: ((r["artist"] or "").lower(), (r["album"] or "").lower(), (r["title"] or "").lower()))
    total = len(rows)
    start = (page - 1) * size
    return rows[start : start + size], total


def errors(limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as s:
        tracks = s.scalars(
            select(Track).where(Track.status == STATUS_ERROR)
            .order_by(Track.updated_at.desc()).limit(limit)
        ).all()
        items = s.scalars(
            select(BandcampItem).where(BandcampItem.status == STATUS_ERROR)
            .order_by(BandcampItem.updated_at.desc()).limit(limit)
        ).all()
    out = []
    for t in tracks:
        out.append({"id": f"qobuz:{t.track_id}", "name": f"{t.artist} — {t.title}",
                    "error": t.error, "source": "qobuz"})
    for b in items:
        out.append({"id": f"bandcamp:{b.item_id}", "name": f"{b.band} — {b.title}",
                    "error": b.error, "source": "bandcamp"})
    return out[:limit]


def downloading() -> list[str]:
    with SessionLocal() as s:
        tracks = s.scalars(
            select(Track).where(Track.status == STATUS_DOWNLOADING).limit(20)
        ).all()
        items = s.scalars(
            select(BandcampItem).where(BandcampItem.status == STATUS_DOWNLOADING).limit(20)
        ).all()
    return [f"{t.artist} — {t.title}" for t in tracks] + [f"{b.band} — {b.title}" for b in items]


def has_pending() -> bool:
    with SessionLocal() as s:
        t = s.scalar(select(Track.track_id).where(Track.status == STATUS_PENDING).limit(1))
        b = s.scalar(select(BandcampItem.item_id).where(BandcampItem.status == STATUS_PENDING).limit(1))
    return t is not None or b is not None


def _model_and_key(qualified_id: str) -> tuple[Optional[type], Any]:
    source, _, raw = qualified_id.partition(":")
    if source == "qobuz":
        try:
            return Track, int(raw)
        except ValueError:
            return None, None
    if source == "bandcamp":
        return BandcampItem, raw
    return None, None


def retry(qualified_id: str) -> None:
    model, key = _model_and_key(qualified_id)
    if model is None:
        return
    with SessionLocal() as s:
        row = s.get(model, key)
        if row is not None:
            row.status = STATUS_PENDING
            row.error = ""
            row.attempts = 0
            s.commit()


def retry_all() -> None:
    with SessionLocal() as s:
        for model in (Track, BandcampItem):
            for row in s.scalars(select(model).where(model.status == STATUS_ERROR)).all():
                row.status = STATUS_PENDING
                row.error = ""
                row.attempts = 0
        s.commit()
