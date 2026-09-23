"""Database layer: SQLAlchemy models, session factory, and secret encryption.

Three tables:

* ``settings`` — a simple key/value store edited from the web UI. Secret values
  (Qobuz token, app secret, admin password hash, Jellyfin key) are Fernet-
  encrypted before they touch disk.
* ``tracks``   — one row per purchased track (an album purchase expands into its
  tracks). Holds both the catalog metadata and the download status, so the
  library view and the sync diff read from one place.
* ``logs``     — a rolling application log surfaced in the UI.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text, Integer, BigInteger, DateTime, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from .paths import DB_PATH, load_or_create_key

_fernet = Fernet(load_or_create_key())


def encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


# Download lifecycle for a track.
STATUS_PENDING = "pending"
STATUS_DOWNLOADING = "downloading"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"  # not actually owned (demo) — recorded so we stop retrying


class Track(Base):
    __tablename__ = "tracks"

    track_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(Text, default="")
    artist: Mapped[str] = mapped_column(Text, default="")
    album: Mapped[str] = mapped_column(Text, default="")
    album_artist: Mapped[str] = mapped_column(Text, default="")
    album_id: Mapped[str] = mapped_column(String(64), default="")
    composer: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    track_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    disc_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tracks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cover_url: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)
    format_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_path: Mapped[str] = mapped_column(Text, default="")
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    purchased_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    downloaded_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BandcampItem(Base):
    """One purchased Bandcamp item (an album or a standalone track).

    Bandcamp's download unit is the whole item (an album arrives as a zip that we
    extract), so — unlike Qobuz's per-track ``Track`` — the grain here is the
    purchase. Kept in its own table so the working Qobuz path is untouched.
    """

    __tablename__ = "bandcamp_items"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sale-item key, e.g. "p12345"
    item_type: Mapped[str] = mapped_column(String(16), default="album")  # album | track
    band: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    art_url: Mapped[str] = mapped_column(Text, default="")
    redownload_url: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING, index=True)
    fmt: Mapped[str] = mapped_column(String(24), default="")
    file_path: Mapped[str] = mapped_column(Text, default="")  # album folder or track file
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    purchased_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    downloaded_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class LogEntry(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, default="")


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def counts_by_status() -> dict[str, int]:
    """Return the number of tracks in each download status."""
    with SessionLocal() as s:
        rows = s.query(Track.status, func.count()).group_by(Track.status).all()
    return {status: n for status, n in rows}
