"""Bandcamp API client (unofficial, cookie-authenticated).

Bandcamp has no purchases API, so — like the Qobuz browser token — we ride the
user's session via their ``identity`` cookie. Bandcamp also fingerprints TLS, so
requests go through ``curl_cffi`` impersonating a real Chrome browser.

Flow:
  1. ``collection_summary`` → fan_id + username.
  2. the fan profile page's ``pagedata`` blob → first page of purchases + a
     pagination token, then ``fancollection/1/collection_items`` for the rest.
  3. each purchase's redownload page ``pagedata`` → a direct download URL per
     format (an album is a .zip, a single track is one file).
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from curl_cffi import requests as cffi

from .models import BandcampPurchase

BASE = "https://bandcamp.com"
_PAGEDATA_RE = re.compile(r'<div id="pagedata" data-blob="([^"]+)"')

# Format fallbacks if the preferred one isn't offered for an item.
_FORMAT_FALLBACKS = ["flac", "alac", "wav", "mp3-320", "mp3-v0", "vorbis"]
_EXT = {
    "flac": ".flac", "alac": ".m4a", "wav": ".wav", "aiff-lossless": ".aiff",
    "mp3-320": ".mp3", "mp3-v0": ".mp3", "vorbis": ".ogg", "aac-hi": ".m4a",
}


class BandcampError(RuntimeError):
    pass


class BandcampAuthError(BandcampError):
    """The identity cookie was missing, invalid, or expired."""


def format_extension(fmt: str) -> str:
    return _EXT.get(fmt, ".bin")


def select_download(blob: dict[str, Any], fmt: str) -> tuple[str, str, str, bool, str]:
    """From a download page's pagedata, pick (url, artist, title, is_album, format).

    Falls back to the best available format if the preferred one is missing.
    Pure function (no I/O) so it's unit-testable.
    """
    items = blob.get("download_items") or blob.get("digital_items") or []
    if not items:
        raise BandcampError("no downloadable items on the download page")
    di = items[0]
    downloads = di.get("downloads") or {}
    actual = next((f for f in [fmt, *_FORMAT_FALLBACKS] if f in downloads), "")
    if not actual:
        raise BandcampError(f"none of the requested formats are available ({fmt})")
    url = (downloads[actual] or {}).get("url")
    if not url:
        raise BandcampError(f"no URL for format {actual}")
    is_album = str(di.get("download_type") or di.get("tralbum_type") or "").lower() == "a"
    return url, str(di.get("artist", "")).strip(), str(di.get("title", "")).strip(), is_album, actual


class BandcampClient:
    def __init__(self, identity: str):
        if not identity.strip():
            raise BandcampAuthError("no Bandcamp identity cookie provided")
        self._s = cffi.Session(impersonate="chrome", timeout=60)
        self._s.cookies.set("identity", identity.strip(), domain=".bandcamp.com")

    # -- pagedata helper -----------------------------------------------------
    def _pagedata(self, url: str) -> dict[str, Any]:
        resp = self._s.get(url)
        if resp.status_code in (401, 403):
            raise BandcampAuthError(f"Bandcamp rejected the session ({resp.status_code})")
        resp.raise_for_status()
        m = _PAGEDATA_RE.search(resp.text)
        if not m:
            raise BandcampError(f"no pagedata blob at {url} (login expired?)")
        return json.loads(html.unescape(m.group(1)))

    # -- identity ------------------------------------------------------------
    def get_fan(self) -> tuple[str, str]:
        """Return (fan_id, username). Raises if the cookie isn't a logged-in fan."""
        resp = self._s.get(f"{BASE}/api/fan/2/collection_summary")
        if resp.status_code in (401, 403):
            raise BandcampAuthError("identity cookie is invalid or expired")
        resp.raise_for_status()
        data = resp.json()
        fan_id = data.get("fan_id")
        summary = data.get("collection_summary") or {}
        username = summary.get("username") or ""
        if not fan_id:
            raise BandcampAuthError("not logged in (no fan_id) — check the identity cookie")
        return str(fan_id), username

    # -- collection ----------------------------------------------------------
    def iter_purchases(self, fan_id: str, username: str) -> Iterator[BandcampPurchase]:
        """Yield every downloadable purchase in the fan's collection."""
        blob = self._pagedata(f"{BASE}/{username}")
        collection = (blob.get("item_cache") or {}).get("collection") or {}
        cdata = blob.get("collection_data") or {}
        redownloads: dict[str, str] = dict(cdata.get("redownload_urls") or {})

        seen: set[str] = set()
        for raw in collection.values():
            p = BandcampPurchase.from_collection(raw, redownloads)
            if p and p.item_id not in seen:
                seen.add(p.item_id)
                yield p

        token = cdata.get("last_token")
        while token:
            resp = self._s.post(
                f"{BASE}/api/fancollection/1/collection_items",
                json={"fan_id": int(fan_id), "older_than_token": token, "count": 100},
            )
            resp.raise_for_status()
            data = resp.json()
            redownloads.update(data.get("redownload_urls") or {})
            items = data.get("items") or []
            for raw in items:
                p = BandcampPurchase.from_collection(raw, redownloads)
                if p and p.item_id not in seen:
                    seen.add(p.item_id)
                    yield p
            if not data.get("more_available") or not items:
                break
            token = data.get("last_token")

    # -- download resolution -------------------------------------------------
    def resolve_download(self, redownload_url: str, fmt: str) -> tuple[str, str, str, bool, str]:
        """Return (url, artist, title, is_album, actual_format) for the item.

        Falls back to the best available format if the preferred one is missing.
        """
        return select_download(self._pagedata(redownload_url), fmt)

    # -- streaming download --------------------------------------------------
    def download(self, url: str, dest: Path, attempts: int = 4) -> int:
        """Stream ``url`` to ``dest`` (atomic via a temp file). Returns bytes."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        last_err: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                return self._stream(url, dest)
            except BandcampError as e:
                last_err = e
                time.sleep(2 + attempt * 3)  # Bandcamp may still be preparing the file
        raise BandcampError(f"download failed after {attempts} attempts: {last_err}")

    def _stream(self, url: str, dest: Path) -> int:
        tmp = dest.with_suffix(dest.suffix + ".part")
        written = 0
        with self._s.get(url, stream=True) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            # A real file is an attachment; an HTML body means "still preparing".
            if "text/html" in ctype and "attachment" not in resp.headers.get(
                "content-disposition", ""
            ):
                raise BandcampError("file not ready yet (Bandcamp still preparing)")
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
                        written += len(chunk)
        tmp.replace(dest)
        return written

    def close(self) -> None:
        try:
            self._s.close()
        except Exception:
            pass
