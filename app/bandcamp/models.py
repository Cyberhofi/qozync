"""Lightweight dataclass for a purchased Bandcamp item."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class BandcampPurchase:
    item_id: str          # sale-item key, e.g. "p12345" — unique per purchase
    item_type: str        # "album" | "track"
    band: str
    title: str
    art_url: str
    redownload_url: str
    year: Optional[int] = None

    @classmethod
    def from_collection(
        cls, raw: dict[str, Any], redownload_urls: dict[str, str]
    ) -> Optional["BandcampPurchase"]:
        """Build from a ``collection_items`` entry, or None if not downloadable."""
        sale_type = raw.get("sale_item_type") or "p"
        sale_id = raw.get("sale_item_id")
        if sale_id is None:
            return None
        key = f"{sale_type}{sale_id}"
        redownload = redownload_urls.get(key)
        if not redownload:
            return None  # e.g. a subscription/gift with no download
        item_type = "album" if (raw.get("item_type") or "").lower() == "album" else "track"
        return cls(
            item_id=key,
            item_type=item_type,
            band=str(raw.get("band_name", "")).strip(),
            title=str(raw.get("item_title", "")).strip(),
            art_url=str(raw.get("item_art_url", "") or raw.get("item_art", "")).strip(),
            redownload_url=redownload,
        )
