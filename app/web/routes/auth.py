"""Login / first-run admin setup / logout."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..render import render
from .. import security

router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    if request.session.get("auth"):
        return RedirectResponse("/", status_code=303)
    return render(
        request, "login.html", setup=not security.is_admin_configured(), error=None
    )


@router.post("/login")
def login_submit(
    request: Request,
    password: str = Form(...),
    confirm: str = Form(""),
):
    setup = not security.is_admin_configured()
    if setup:
        if len(password) < 6:
            return render(request, "login.html", setup=True,
                          error="Password must be at least 6 characters.")
        if password != confirm:
            return render(request, "login.html", setup=True,
                          error="Passwords do not match.")
        security.set_admin_password(password)
        request.session["auth"] = True
        return RedirectResponse("/", status_code=303)

    if security.check_admin_password(password):
        request.session["auth"] = True
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", setup=False, error="Incorrect password.")


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
