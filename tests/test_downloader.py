"""Path building, sanitization, and format capping."""

from app.qobuz.models import QobuzTrack
from app.sync import downloader


def _track(**kw):
    base = dict(
        id=1, title="Song", artist="Artist", album="Album", album_artist="Album Artist",
        album_id="a1", composer="", year=2021, track_number=3, disc_number=1,
        total_tracks=10, duration=200, cover_url="",
    )
    base.update(kw)
    return QobuzTrack(**base)


def test_sanitize_strips_illegal_chars():
    assert downloader.sanitize('a/b:c*d?"e') == "a_b_c_d__e"
    assert downloader.sanitize("   ") == "Unknown"
    assert downloader.sanitize("....") == "Unknown"


def test_target_path_flac_layout():
    p = downloader.target_path(_track(), 27)
    assert p.parent.name == "Album (2021)"
    assert p.parent.parent.name == "Album Artist"
    assert p.name == "03 - Song.flac"


def test_target_path_mp3_extension():
    assert downloader.target_path(_track(), 5).suffix == ".mp3"


def test_disc_prefix_for_multi_disc():
    p = downloader.target_path(_track(disc_number=2), 6)
    assert p.name.startswith("2-03 - ")


def test_choose_format_caps_at_track_max():
    t = _track()
    t.max_format_id = 6
    assert downloader.choose_format(27, t) == 6
    assert downloader.choose_format(5, t) == 5
