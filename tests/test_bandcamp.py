"""Bandcamp parsing, format selection, and zip extraction."""

import io
import zipfile
from pathlib import Path

import pytest

from app.bandcamp.client import BandcampError, format_extension, select_download
from app.bandcamp.download import _extract_zip
from app.bandcamp.models import BandcampPurchase


def test_purchase_from_collection_maps_fields():
    raw = {
        "sale_item_type": "p",
        "sale_item_id": 12345,
        "item_type": "album",
        "band_name": "Some Band",
        "item_title": "The Album",
        "item_art_url": "http://img/art.jpg",
    }
    redownloads = {"p12345": "https://bandcamp.com/download?id=1&sig=x"}
    p = BandcampPurchase.from_collection(raw, redownloads)
    assert p is not None
    assert p.item_id == "p12345"
    assert p.item_type == "album"
    assert p.band == "Some Band"
    assert p.title == "The Album"
    assert p.redownload_url.startswith("https://bandcamp.com/download")


def test_purchase_skipped_without_redownload_url():
    raw = {"sale_item_type": "p", "sale_item_id": 999, "item_type": "track", "band_name": "X"}
    assert BandcampPurchase.from_collection(raw, {}) is None


def test_select_download_prefers_requested_format():
    blob = {
        "download_items": [
            {
                "artist": "Band",
                "title": "Album",
                "download_type": "a",
                "downloads": {
                    "flac": {"url": "https://dl/flac"},
                    "mp3-320": {"url": "https://dl/mp3"},
                },
            }
        ]
    }
    url, artist, title, is_album, fmt = select_download(blob, "flac")
    assert (url, artist, title, is_album, fmt) == ("https://dl/flac", "Band", "Album", True, "flac")


def test_select_download_falls_back_when_format_missing():
    blob = {"download_items": [{"download_type": "t", "downloads": {"mp3-320": {"url": "u"}}}]}
    url, _, _, is_album, fmt = select_download(blob, "flac")
    assert url == "u" and is_album is False and fmt == "mp3-320"


def test_select_download_errors_when_no_formats():
    with pytest.raises(BandcampError):
        select_download({"download_items": [{"downloads": {}}]}, "flac")


def test_format_extension():
    assert format_extension("flac") == ".flac"
    assert format_extension("alac") == ".m4a"
    assert format_extension("mp3-320") == ".mp3"


def test_extract_zip_flattens(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Band - Album/01 Track.flac", b"audio")
        zf.writestr("Band - Album/cover.jpg", b"jpeg")
        zf.writestr("nested/dir/02 Track.flac", b"more")
    zip_path = tmp_path / "album.zip"
    zip_path.write_bytes(buf.getvalue())

    dest = tmp_path / "out"
    _extract_zip(zip_path, dest)
    names = sorted(p.name for p in dest.iterdir())
    assert names == ["01 Track.flac", "02 Track.flac", "cover.jpg"]
    assert (dest / "01 Track.flac").read_bytes() == b"audio"
