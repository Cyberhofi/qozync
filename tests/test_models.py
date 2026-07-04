"""Parsing the subset of Qobuz JSON we depend on."""

from app.qobuz.models import QobuzTrack


def test_from_json_pulls_core_fields():
    payload = {
        "id": 555,
        "title": "The Track",
        "track_number": 4,
        "media_number": 1,
        "duration": 233,
        "performer": {"name": "Track Artist"},
        "composer": {"name": "A Composer"},
        "album": {
            "id": "alb99",
            "title": "The Album",
            "tracks_count": 12,
            "release_date_original": "2019-05-01",
            "hires": True,
            "artist": {"name": "Album Artist"},
            "image": {"large": "http://img/large.jpg", "small": "http://img/small.jpg"},
        },
    }
    t = QobuzTrack.from_json(payload)
    assert t.id == 555
    assert t.title == "The Track"
    assert t.artist == "Track Artist"
    assert t.album == "The Album"
    assert t.album_artist == "Album Artist"
    assert t.composer == "A Composer"
    assert t.year == 2019
    assert t.track_number == 4
    assert t.total_tracks == 12
    assert t.cover_url == "http://img/large.jpg"
    assert t.max_format_id == 27  # hires flag


def test_from_json_tolerates_missing_album():
    t = QobuzTrack.from_json({"id": 1, "title": "x"})
    assert t.id == 1 and t.artist == "" and t.year is None
