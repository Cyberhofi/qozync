"""Qobuz REST client (api.json v0.2).

Covers exactly what the sync needs: authenticate, list purchases, enumerate an
album's tracks, resolve a signed download URL, and stream the file. Request
signing for ``track/getFileUrl`` is an MD5 over the method, its alphabetically
ordered params, a unix timestamp, and the app secret.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import httpx

API_BASE = "https://www.qobuz.com/api.json/0.2/"

# Qobuz's gateway rejects requests without a recognized browser User-Agent.
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0"

# format_id -> human label, best first.
FORMATS = {
    27: "FLAC (Hi-Res ≤192kHz/24-bit)",
    7: "FLAC (Hi-Res ≤96kHz/24-bit)",
    6: "FLAC (CD 44.1kHz/16-bit)",
    5: "MP3 320kbps",
}


class QobuzError(RuntimeError):
    pass


class AuthError(QobuzError):
    pass


class SignatureError(QobuzError):
    """The app secret produced an invalid request signature."""


class QobuzClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str = "",
        token: str = "",
        client: Optional[httpx.Client] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = token
        self._http = client or httpx.Client(timeout=30, follow_redirects=True)
        self._sync_headers()

    def _sync_headers(self) -> None:
        headers = {"X-App-Id": self.app_id, "User-Agent": DEFAULT_UA}
        if self.token:
            headers["X-User-Auth-Token"] = self.token
        self._http.headers.update(headers)

    # -- low level -----------------------------------------------------------
    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        resp = self._http.get(API_BASE + endpoint, params=params)
        return self._handle(resp)

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code == 401:
            raise AuthError(data.get("message", "unauthorized"))
        if resp.status_code >= 400:
            message = str(data.get("message", resp.text[:200]))
            if "signature" in message.lower():
                raise SignatureError(message)
            raise QobuzError(f"HTTP {resp.status_code}: {message}")
        return data

    # -- auth ----------------------------------------------------------------
    def login_with_token(self, user_auth_token: str) -> dict[str, Any]:
        """Adopt a user_auth_token obtained from the browser and validate it.

        This is the reliable path since Qobuz began rejecting programmatic
        email/password logins (April 2026). The token must have been minted for
        the same app_id we use — which it is, since both come from the current
        web player.
        """
        self.token = user_auth_token.strip()
        self._sync_headers()
        try:
            return self.validate()
        except AuthError as e:
            raise AuthError(
                "token was rejected — make sure it's current and copied in full"
            ) from e

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Exchange email/password for a user_auth_token.

        NOTE: Qobuz began returning 401 "User authentication is required" for
        programmatic logins in April 2026, so this frequently fails; prefer
        :meth:`login_with_token`. Kept because it still works for some accounts
        and may be restored. Tries plaintext then MD5 password, via GET.
        """
        last_err: Optional[Exception] = None
        for pwd in (password, hashlib.md5(password.encode()).hexdigest()):
            try:
                data = self._do_login(email, pwd)
                self.token = data["user_auth_token"]
                self._sync_headers()
                return data
            except AuthError as e:
                last_err = e
        raise AuthError(
            "email/password login was rejected by Qobuz. Since April 2026 Qobuz "
            "blocks app logins — use the auth-token method instead. "
            f"(server said: {last_err})"
        )

    def _do_login(self, email: str, password: str) -> dict[str, Any]:
        resp = self._http.get(
            API_BASE + "user/login",
            params={"email": email, "password": password, "app_id": self.app_id},
        )
        data = self._handle(resp)
        if "user_auth_token" not in data:
            raise AuthError(data.get("message", "login did not return a token"))
        return data

    def validate(self) -> dict[str, Any]:
        """Confirm the current token is accepted; returns the user object."""
        return self._get("user/get", {"app_id": self.app_id})

    # -- catalog -------------------------------------------------------------
    def get_user_purchase_ids(self) -> tuple[list[str], list[int]]:
        """Return (album_ids, track_ids) of everything owned.

        Uses ``purchase/getUserPurchasesIds`` — the endpoint the web player
        relies on. Unlike ``getUserPurchases`` it reports the complete set
        (the latter under-reports standalone track purchases). Paginated to be
        safe for large libraries.
        """
        albums: dict[str, None] = {}
        tracks: dict[int, None] = {}
        offset = 0
        page = 500
        while True:
            d = self._get(
                "purchase/getUserPurchasesIds",
                {"app_id": self.app_id, "limit": page, "offset": offset},
            )
            a = d.get("albums") or {}
            t = d.get("tracks") or {}
            a_items = a.get("items") or []
            t_items = t.get("items") or []
            for x in a_items:
                albums[str(x["id"])] = None
            for x in t_items:
                tracks[int(x["id"])] = None
            offset += page
            if (not a_items and not t_items) or offset >= max(
                a.get("total", 0), t.get("total", 0)
            ):
                break
        return list(albums.keys()), list(tracks.keys())

    def get_album(self, album_id: str) -> dict[str, Any]:
        # album/get returns the full track list by default; the previous
        # ``extra=tracks`` argument is now rejected with HTTP 400.
        return self._get("album/get", {"album_id": album_id})

    def get_track(self, track_id: int) -> dict[str, Any]:
        return self._get("track/get", {"track_id": track_id})

    def get_track_file_url(self, track_id: int, format_id: int) -> dict[str, Any]:
        ts = int(time.time())
        sig = self._sign(track_id, format_id, ts)
        return self._get(
            "track/getFileUrl",
            {
                "request_ts": ts,
                "request_sig": sig,
                "track_id": track_id,
                "format_id": format_id,
                "intent": "stream",
            },
        )

    def _sign(self, track_id: int, format_id: int, ts: int) -> str:
        # Params in alphabetical order: format_id, intent, track_id.
        raw = (
            f"trackgetFileUrlformat_id{format_id}intentstream"
            f"track_id{track_id}{ts}{self.app_secret}"
        )
        return hashlib.md5(raw.encode()).hexdigest()

    # -- download ------------------------------------------------------------
    def stream_download(
        self,
        url: str,
        dest: Path,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """Stream ``url`` to a temp file then atomically move into ``dest``.

        Returns the number of bytes written.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        written = 0
        with self._http.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("Content-Length", 0))
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 16):
                    fh.write(chunk)
                    written += len(chunk)
                    if on_progress:
                        on_progress(written, total)
        tmp.replace(dest)
        return written

    def close(self) -> None:
        self._http.close()


def resolve_working_secret(
    app_id: str,
    token: str,
    candidates: Iterable[str],
    sample_track_id: int,
) -> str:
    """Return the first candidate secret that yields a valid signature.

    Validation asks ``getFileUrl`` for one owned track: a wrong secret raises
    ``SignatureError``; anything else (including a successful URL) means the
    secret is good.
    """
    client = QobuzClient(app_id=app_id, token=token)
    try:
        for secret in candidates:
            client.app_secret = secret
            try:
                client.get_track_file_url(sample_track_id, 5)
                return secret
            except SignatureError:
                continue
            except QobuzError:
                # Non-signature error means the signature itself was accepted.
                return secret
        raise QobuzError("none of the extracted secrets produced a valid signature")
    finally:
        client.close()
