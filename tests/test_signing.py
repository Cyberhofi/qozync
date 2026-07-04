"""The request signature must be an MD5 over method + ordered params + ts + secret."""

import hashlib

from app.qobuz.client import QobuzClient


def test_signature_matches_known_formula():
    client = QobuzClient(app_id="123456789", app_secret="s3cr3t")
    track_id, fmt, ts = 42, 27, 1_700_000_000
    expected = hashlib.md5(
        f"trackgetFileUrlformat_id{fmt}intentstreamtrack_id{track_id}{ts}s3cr3t".encode()
    ).hexdigest()
    assert client._sign(track_id, fmt, ts) == expected


def test_signature_changes_with_secret():
    ts = 1_700_000_000
    a = QobuzClient(app_id="1", app_secret="one")._sign(10, 6, ts)
    b = QobuzClient(app_id="1", app_secret="two")._sign(10, 6, ts)
    assert a != b
