"""Activity: live sync progress, in-flight queue, and errors with retry."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from ...db import (
    STATUS_DOWNLOADING,
    STATUS_ERROR,
    STATUS_PENDING,
    SessionLocal,
    Track,
    counts_by_status,
)
from ...sync import engine
from ..render import render

router = APIRouter()


@router.get("/activity")
def activity(request: Request):
    return render(request, "activity.html", active="activity", state=engine.STATE.snapshot())


@router.get("/activity/data")
def activity_data():
    """JSON polled by the Activity page to refresh progress without a reload."""
    with SessionLocal() as s:
        errors = list(
            s.scalars(
                select(Track).where(Track.status == STATUS_ERROR)
                .order_by(Track.updated_at.desc()).limit(50)
            ).all()
        )
        pending = s.scalar(select(Track.track_id).where(Track.status == STATUS_PENDING).limit(1))
        downloading = list(
            s.scalars(
                select(Track).where(Track.status == STATUS_DOWNLOADING).limit(20)
            ).all()
        )
    return JSONResponse(
        {
            "state": engine.STATE.snapshot(),
            "counts": counts_by_status(),
            "has_pending": pending is not None,
            "downloading": [f"{t.artist} — {t.title}" for t in downloading],
            "errors": [
                {"id": t.track_id, "name": f"{t.artist} — {t.title}", "error": t.error}
                for t in errors
            ],
        }
    )


@router.post("/activity/retry/{track_id}")
def retry(track_id: int):
    with SessionLocal() as s:
        row = s.get(Track, track_id)
        if row is not None:
            row.status = STATUS_PENDING
            row.error = ""
            row.attempts = 0
            s.commit()
    return RedirectResponse("/activity", status_code=303)


@router.post("/activity/retry-all")
def retry_all():
    with SessionLocal() as s:
        for row in s.scalars(select(Track).where(Track.status == STATUS_ERROR)).all():
            row.status = STATUS_PENDING
            row.error = ""
            row.attempts = 0
        s.commit()
    return RedirectResponse("/activity", status_code=303)
