"""Logs: recent application log tail."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ... import applog
from ..render import render

router = APIRouter()


@router.get("/logs")
def logs(request: Request):
    return render(request, "logs.html", active="logs", entries=applog.recent(300))
