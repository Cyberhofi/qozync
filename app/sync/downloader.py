"""Turn a resolved Qobuz track into a tagged file on disk.

Responsibilities: pick the extension from the format actually served, build a
safe folder tree, stream the file, and write tags + embedded cover art. The
engine owns status/DB bookkeeping; this module is pure file work.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import httpx
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCOM, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK
from mutagen.mp3 import MP3

from ..paths import MUSIC_DIR
from ..qobuz.client import QobuzClient
from ..qobuz.models import QobuzTrack

_MP3_FORMATS = {5}
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class NotOwned(RuntimeError):
    """Qobuz returned a demo/sample instead of the full file — track not owned."""


def sanitize(name: str, fallback: str = "Unknown") -> str:
    """Make a string safe as a single path component (cross-platform)."""
    name = _INVALID.sub("_", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return name[:180] or fallback


def _extension(format_id: int) -> str:
    return ".mp3" if format_id in _MP3_FORMATS else ".flac"


def target_path(track: QobuzTrack, format_id: int) -> Path:
    artist = sanitize(track.album_artist or track.artist, "Unknown Artist")
    album = sanitize(track.album, "Unknown Album")
    if track.year:
        album = f"{album} ({track.year})"
    disc_prefix = ""
    if track.total_tracks and (track.disc_number or 1) > 1:
        disc_prefix = f"{track.disc_number}-"
    elif track.disc_number and track.disc_number > 1:
        disc_prefix = f"{track.disc_number}-"
    num = f"{track.track_number:02d}" if track.track_number else "00"
    title = sanitize(track.title, "Untitled")
    filename = f"{disc_prefix}{num} - {title}{_extension(format_id)}"
    return MUSIC_DIR / artist / album / filename


def choose_format(preferred: int, track: QobuzTrack) -> int:
    """Cap the preferred quality at what the track offers to avoid needless retries."""
    if track.max_format_id:
        return min(preferred, track.max_format_id)
    return preferred


def download(client: QobuzClient, track: QobuzTrack, preferred_format: int) -> tuple[Path, int, int]:
    """Download and tag one track.

    Returns (path, format_id, bytes). Raises ``NotOwned`` if Qobuz only serves a
    sample.
    """
    fmt = choose_format(preferred_format, track)
    info = client.get_track_file_url(track.id, fmt)

    if info.get("sample") or not info.get("url"):
        raise NotOwned(f"track {track.id} is not owned (sample only)")

    actual_fmt = int(info.get("format_id", fmt))
    dest = target_path(track, actual_fmt)
    if dest.exists() and dest.stat().st_size > 0:
        return dest, actual_fmt, dest.stat().st_size

    size = client.stream_download(info["url"], dest)
    try:
        _tag(dest, track, actual_fmt, client)
    except Exception:
        # A tagging failure shouldn't discard a good audio file; leave it untagged.
        pass
    return dest, actual_fmt, size


def _fetch_cover(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError:
        return None


def _tag(path: Path, track: QobuzTrack, format_id: int, client: QobuzClient) -> None:
    cover = _fetch_cover(track.cover_url)
    if format_id in _MP3_FORMATS:
        _tag_mp3(path, track, cover)
    else:
        _tag_flac(path, track, cover)


def _tag_flac(path: Path, t: QobuzTrack, cover: Optional[bytes]) -> None:
    audio = FLAC(path)
    audio["title"] = t.title
    audio["artist"] = t.artist
    audio["album"] = t.album
    audio["albumartist"] = t.album_artist or t.artist
    if t.composer:
        audio["composer"] = t.composer
    if t.year:
        audio["date"] = str(t.year)
    if t.track_number:
        audio["tracknumber"] = str(t.track_number)
    if t.total_tracks:
        audio["tracktotal"] = str(t.total_tracks)
    if t.disc_number:
        audio["discnumber"] = str(t.disc_number)
    if cover:
        pic = Picture()
        pic.type = 3  # front cover
        pic.mime = "image/jpeg"
        pic.data = cover
        audio.clear_pictures()
        audio.add_picture(pic)
    audio.save()


def _tag_mp3(path: Path, t: QobuzTrack, cover: Optional[bytes]) -> None:
    try:
        audio = MP3(path, ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
    except Exception:
        audio = MP3(path)
        audio.add_tags()
    tags = audio.tags
    tags.add(TIT2(encoding=3, text=t.title))
    tags.add(TPE1(encoding=3, text=t.artist))
    tags.add(TALB(encoding=3, text=t.album))
    tags.add(TPE2(encoding=3, text=t.album_artist or t.artist))
    if t.composer:
        tags.add(TCOM(encoding=3, text=t.composer))
    if t.year:
        tags.add(TDRC(encoding=3, text=str(t.year)))
    if t.track_number:
        trck = f"{t.track_number}/{t.total_tracks}" if t.total_tracks else str(t.track_number)
        tags.add(TRCK(encoding=3, text=trck))
    if t.disc_number:
        tags.add(TPOS(encoding=3, text=str(t.disc_number)))
    if cover:
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
    audio.save()
