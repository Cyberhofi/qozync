"""Dashboard: overview counts, storage, last/next sync, recent activity."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from ... import config
from ...db import STATUS_DONE, SessionLocal, Track
from ...sync import engine, scheduler
from ..render import render

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    with SessionLocal() as s:
        storage = s.scalar(
            select(func.coalesce(func.sum(Track.file_size), 0)).where(
                Track.status == STATUS_DONE
            )
        )
        recent = list(
            s.scalars(
                select(Track)
                .where(Track.status == STATUS_DONE)
                .order_by(Track.downloaded_at.desc())
                .limit(10)
            ).all()
        )
    return render(
        request,
        "dashboard.html",
        active="dashboard",
        connected=config.is_configured(),
        storage=storage,
        recent=recent,
        state=engine.STATE.snapshot(),
        next_run=scheduler.next_run_time(),
        last_result=engine.STATE.last_result,
    )
