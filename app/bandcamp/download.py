"""Download a purchased Bandcamp item to disk.

Albums arrive as a .zip that we extract into ``{Artist}/{Album}/``; single-track
purchases are saved directly under ``{Artist}/``. Bandcamp already embeds tags
and cover art, so no tagging step is needed — we just place the files.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from ..paths import MUSIC_DIR
from ..sync.downloader import sanitize
from .client import BandcampClient, format_extension
from .models import BandcampPurchase


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract audio/art into ``dest_dir``, flattening any nested paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            name = Path(member.filename).name  # flatten
            if not name:
                continue
            target = dest_dir / name
            with zf.open(member) as src, open(target, "wb") as out:
                out.write(src.read())


def download_item(
    client: BandcampClient, item: BandcampPurchase, fmt: str
) -> tuple[Path, int, str]:
    """Download one purchase. Returns (path, bytes, actual_format).

    Idempotent: an album folder that already has files, or an existing track
    file, is left in place.
    """
    url, artist, title, is_album, actual_fmt = client.resolve_download(item.redownload_url, fmt)
    artist_name = sanitize(artist or item.band, "Unknown Artist")
    artist_dir = MUSIC_DIR / artist_name

    if is_album:
        album_dir = artist_dir / sanitize(title or item.title, "Unknown Album")
        if album_dir.exists() and any(album_dir.iterdir()):
            return album_dir, _dir_size(album_dir), actual_fmt
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / f"{item.item_id}.zip"
            client.download(url, zip_path)
            _extract_zip(zip_path, album_dir)
        return album_dir, _dir_size(album_dir), actual_fmt

    # single track
    dest = artist_dir / f"{sanitize(title or item.title, 'Untitled')}{format_extension(actual_fmt)}"
    if dest.exists() and dest.stat().st_size > 0:
        return dest, dest.stat().st_size, actual_fmt
    size = client.download(url, dest)
    return dest, size, actual_fmt
