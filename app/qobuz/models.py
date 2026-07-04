"""Lightweight dataclasses over the Qobuz JSON we actually use.

The API returns large, deeply nested objects; these parsers pull out only the
fields the downloader and tagger need and tolerate missing keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


def _year(date_str: Any) -> Optional[int]:
    if isinstance(date_str, str) and len(date_str) >= 4 and date_str[:4].isdigit():
        return int(date_str[:4])
    return None


def _largest_cover(image: dict[str, Any]) -> str:
    if not isinstance(image, dict):
        return ""
    for size in ("large", "back", "medium", "small", "thumbnail"):
        if image.get(size):
            return str(image[size])
    return ""


@dataclass
class QobuzTrack:
    id: int
    title: str
    artist: str
    album: str
    album_artist: str
    album_id: str
    composer: str
    year: Optional[int]
    track_number: Optional[int]
    disc_number: Optional[int]
    total_tracks: Optional[int]
    duration: Optional[int]
    cover_url: str
    max_format_id: Optional[int] = None  # best quality the account is entitled to

    @classmethod
    def from_json(cls, t: dict[str, Any], album: Optional[dict[str, Any]] = None) -> "QobuzTrack":
        album = album or t.get("album") or {}
        album_artist_obj = album.get("artist") or {}
        track_artist_obj = t.get("performer") or t.get("artist") or album_artist_obj
        # Hi-res flags let us cap the requested format to what's actually available.
        max_fmt = None
        if album.get("hires") or t.get("hires"):
            max_fmt = 27
        elif album.get("maximum_bit_depth") == 16 or t.get("maximum_sampling_rate"):
            max_fmt = 6
        return cls(
            id=int(t["id"]),
            title=str(t.get("title", "")).strip(),
            artist=str(track_artist_obj.get("name", "")).strip(),
            album=str(album.get("title", "")).strip(),
            album_artist=str(album_artist_obj.get("name", "")).strip(),
            album_id=str(album.get("id", "")),
            composer=str((t.get("composer") or {}).get("name", "")).strip(),
            year=_year(album.get("release_date_original") or album.get("released_at")),
            track_number=t.get("track_number"),
            disc_number=t.get("media_number") or t.get("disc_number") or 1,
            total_tracks=album.get("tracks_count"),
            duration=t.get("duration"),
            cover_url=_largest_cover(album.get("image") or {}),
            max_format_id=max_fmt,
        )


@dataclass
class Purchases:
    tracks: list[QobuzTrack] = field(default_factory=list)
    total: int = 0
