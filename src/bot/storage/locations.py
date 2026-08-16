import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    recorded_at: str
    received_at: str

    @property
    def maps_url(self) -> str:
        return f"https://maps.google.com/?q={self.lat},{self.lon}"


class LocationStore:
    """Async SQLite store for received location points."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                recorded_at TEXT,
                received_at TEXT NOT NULL
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def insert(self, lat: float, lon: float, recorded_at: str | None) -> None:
        if self._db is None:
            raise RuntimeError("LocationStore is not initialized")
        received_at = _utc_now()
        await self._db.execute(
            "INSERT INTO locations (lat, lon, recorded_at, received_at) VALUES (?, ?, ?, ?)",
            (lat, lon, recorded_at, received_at),
        )
        await self._db.commit()

    async def get_latest(self) -> Location | None:
        if self._db is None:
            raise RuntimeError("LocationStore is not initialized")
        async with self._db.execute(
            "SELECT lat, lon, recorded_at, received_at FROM locations ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return Location(
            lat=float(row[0]),
            lon=float(row[1]),
            recorded_at=str(row[2]) if row[2] is not None else "",
            received_at=str(row[3]),
        )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
