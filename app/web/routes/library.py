"""Library: paginated, filterable list of every purchased track."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import or_, select

from ...db import SessionLocal, Track
from ..render import render

router = APIRouter()

_PAGE_SIZE = 100


@router.get("/library")
def library(
    request: Request,
    status: str = Query(""),
    q: str = Query(""),
    page: int = Query(1, ge=1),
):
    with SessionLocal() as s:
        stmt = select(Track)
        if status:
            stmt = stmt.where(Track.status == status)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(Track.title.ilike(like), Track.artist.ilike(like), Track.album.ilike(like))
            )
        total = len(s.scalars(stmt).all())
        rows = list(
            s.scalars(
                stmt.order_by(Track.album_artist, Track.album, Track.disc_number, Track.track_number)
                .offset((page - 1) * _PAGE_SIZE)
                .limit(_PAGE_SIZE)
            ).all()
        )
    pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    return render(
        request,
        "library.html",
        active="library",
        rows=rows,
        status=status,
        q=q,
        page=page,
        pages=pages,
        total=total,
    )
