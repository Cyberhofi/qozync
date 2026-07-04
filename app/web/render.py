"""Shared Jinja setup and a render helper that injects common page context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..db import counts_by_status

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _fmt_size(num: int | None) -> str:
    n = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


templates.env.filters["filesize"] = _fmt_size


def render(request: Request, template: str, **context: Any) -> HTMLResponse:
    counts = counts_by_status()
    base = {
        "request": request,
        "active": "",
        "counts": counts,
        "total_tracks": sum(counts.values()),
    }
    base.update(context)
    return templates.TemplateResponse(request=request, name=template, context=base)
