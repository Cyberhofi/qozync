"""Route registration."""

from __future__ import annotations

from fastapi import FastAPI

from . import activity, auth, dashboard, library, logs, settings


def register_routes(app: FastAPI) -> None:
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(library.router)
    app.include_router(activity.router)
    app.include_router(logs.router)
    app.include_router(settings.router)
