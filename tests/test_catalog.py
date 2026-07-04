"""Guard the purchase-enumeration behavior that regressed:

* purchases come from ``getUserPurchasesIds`` (not the under-reporting
  ``getUserPurchases``),
* ``album/get`` must NOT send the now-rejected ``extra`` argument.
"""

from app.qobuz.client import QobuzClient


def _client_with_capture(pages):
    client = QobuzClient(app_id="1")
    calls = []

    def fake_get(endpoint, params):
        calls.append((endpoint, params))
        if endpoint == "purchase/getUserPurchasesIds":
            return pages[min(params["offset"] // params["limit"], len(pages) - 1)]
        return {}

    client._get = fake_get  # type: ignore[assignment]
    return client, calls


def test_purchase_ids_uses_correct_endpoint_and_extracts_ids():
    page = {
        "albums": {"total": 2, "items": [{"id": "a1"}, {"id": "a2"}]},
        "tracks": {"total": 3, "items": [{"id": 10}, {"id": 11}, {"id": 12}]},
    }
    client, calls = _client_with_capture([page])
    album_ids, track_ids = client.get_user_purchase_ids()

    assert calls[0][0] == "purchase/getUserPurchasesIds"
    assert set(album_ids) == {"a1", "a2"}
    assert set(track_ids) == {10, 11, 12}


def test_purchase_ids_paginates_and_dedupes():
    pages = [
        {
            "albums": {"total": 2, "items": [{"id": "a1"}] * 500},
            "tracks": {"total": 501, "items": [{"id": i} for i in range(500)]},
        },
        {
            "albums": {"total": 2, "items": [{"id": "a2"}]},
            "tracks": {"total": 501, "items": [{"id": 500}]},
        },
    ]
    client, calls = _client_with_capture(pages)
    album_ids, track_ids = client.get_user_purchase_ids()

    assert len([c for c in calls if c[0] == "purchase/getUserPurchasesIds"]) == 2
    assert set(album_ids) == {"a1", "a2"}          # deduped
    assert len(track_ids) == 501                    # both pages merged


def test_get_album_sends_no_extra_argument():
    captured = {}

    client = QobuzClient(app_id="1")
    client._get = lambda ep, params: captured.update({"ep": ep, "params": params}) or {}
    client.get_album("abc")

    assert captured["ep"] == "album/get"
    assert "extra" not in captured["params"]
    assert captured["params"]["album_id"] == "abc"
