"""Library: paginated, filterable list of every purchase across all sources."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ... import catalog
from ..render import render

router = APIRouter()

_PAGE_SIZE = 100


@router.get("/library")
def library(
    request: Request,
    status: str = Query(""),
    q: str = Query(""),
    source: str = Query(""),
    page: int = Query(1, ge=1),
):
    rows, total = catalog.library_page(
        status=status, q=q, source=source, page=page, size=_PAGE_SIZE
    )
    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    return render(
        request,
        "library.html",
        active="library",
        rows=rows,
        status=status,
        q=q,
        source=source,
        page=page,
        pages=pages,
        total=total,
    )
