"""FastAPI application entrypoint.

Wires up the DB, the admin-password gate (a lightweight middleware redirect),
the scheduler, and all routes. Run with ``uvicorn app.main:app``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from . import applog
from .db import init_db
from .paths import load_or_create_key
from .sync import scheduler
from .web.routes import register_routes

# Paths reachable without authentication.
_PUBLIC = {"/login", "/logout", "/health"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    applog.info("Service starting")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Qobuz Purchase Sync", lifespan=lifespan)


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC or path.startswith("/static"):
        return await call_next(request)
    if not request.session.get("auth"):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


# Added last so it sits OUTERMOST — SessionMiddleware must populate
# request.session before require_login reads it.
app.add_middleware(SessionMiddleware, secret_key=load_or_create_key().decode())


@app.get("/health")
def health():
    return {"status": "ok"}


register_routes(app)
