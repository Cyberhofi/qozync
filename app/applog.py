"""Application logging that fans out to stdout and the ``logs`` table.

The UI's Logs page reads from the table; container operators read stdout. A
capped retention keeps the table from growing without bound.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select

from .db import LogEntry, SessionLocal

_MAX_ROWS = 2000

_stdout = logging.getLogger("qobuz")
if not _stdout.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _stdout.addHandler(_handler)
    _stdout.setLevel(logging.INFO)


def _write(level: str, message: str) -> None:
    getattr(_stdout, level if level != "success" else "info")(message)
    try:
        with SessionLocal() as s:
            s.add(LogEntry(level=level, message=message))
            # Trim oldest rows beyond the retention window.
            keep_ids = s.scalars(
                select(LogEntry.id).order_by(LogEntry.id.desc()).limit(_MAX_ROWS)
            ).all()
            if len(keep_ids) >= _MAX_ROWS:
                s.execute(delete(LogEntry).where(LogEntry.id < min(keep_ids)))
            s.commit()
    except Exception:  # logging must never take down a sync run
        _stdout.exception("failed to persist log entry")


def info(message: str) -> None:
    _write("info", message)


def warning(message: str) -> None:
    _write("warning", message)


def error(message: str) -> None:
    _write("error", message)


def success(message: str) -> None:
    _write("success", message)


def recent(limit: int = 200) -> list[LogEntry]:
    with SessionLocal() as s:
        return list(
            s.scalars(select(LogEntry).order_by(LogEntry.id.desc()).limit(limit)).all()
        )
