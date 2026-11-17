"""Dashboard: overview counts, storage, last/next sync, recent activity."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ... import catalog, config
from ...sync import engine, scheduler
from ..render import render

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    return render(
        request,
        "dashboard.html",
        active="dashboard",
        qobuz_connected=config.is_configured(),
        bandcamp_connected=config.bandcamp_is_configured(),
        connected=config.is_configured() or config.bandcamp_is_configured(),
        storage=catalog.total_downloaded_size(),
        recent=catalog.recent_downloads(10),
        state=engine.STATE.snapshot(),
        next_run=scheduler.next_run_time(),
        last_result=engine.STATE.last_result,
    )
