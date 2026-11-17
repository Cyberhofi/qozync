"""Activity: live sync progress, in-flight queue, and errors with retry."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ... import catalog
from ...sync import engine
from ..render import render

router = APIRouter()


@router.get("/activity")
def activity(request: Request):
    return render(request, "activity.html", active="activity", state=engine.STATE.snapshot())


@router.get("/activity/data")
def activity_data():
    """JSON polled by the Activity page to refresh progress without a reload."""
    return JSONResponse(
        {
            "state": engine.STATE.snapshot(),
            "counts": catalog.counts(),
            "has_pending": catalog.has_pending(),
            "downloading": catalog.downloading(),
            "errors": catalog.errors(50),
        }
    )


@router.post("/activity/retry/{qualified_id}")
def retry(qualified_id: str):
    catalog.retry(qualified_id)
    return RedirectResponse("/activity", status_code=303)


@router.post("/activity/retry-all")
def retry_all():
    catalog.retry_all()
    return RedirectResponse("/activity", status_code=303)
