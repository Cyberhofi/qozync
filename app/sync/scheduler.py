"""Periodic sync scheduling and manual triggering.

APScheduler runs :func:`engine.run_sync` on the configured interval. "Sync now"
from the UI runs the same function on a throwaway thread so the request returns
immediately; the engine's own lock prevents overlap with a scheduled run.
"""

from __future__ import annotations

import threading

from apscheduler.schedulers.background import BackgroundScheduler

from .. import applog, config
from . import engine

_scheduler: BackgroundScheduler | None = None
_JOB_ID = "qobuz-sync"


def _scheduled_run() -> None:
    engine.run_sync(trigger="scheduled")


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.start()
    reschedule()


def reschedule() -> None:
    """(Re)create the interval job from the current settings."""
    if _scheduler is None:
        return
    hours = max(1, config.get_int("sync_interval_hours", 6))
    _scheduler.add_job(
        _scheduled_run,
        trigger="interval",
        hours=hours,
        id=_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    applog.info(f"Scheduled sync every {hours}h")


def next_run_time() -> str | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(_JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.isoformat()


def trigger_now(trigger: str = "manual") -> bool:
    """Start a sync in the background. Returns False if one is already running."""
    if engine.STATE.running:
        return False
    threading.Thread(
        target=engine.run_sync, kwargs={"trigger": trigger}, daemon=True
    ).start()
    return True


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
