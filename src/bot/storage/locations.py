import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiosqlite

logger = logging.getLogger(__name__)

TIME_FORMAT = "%Y-%m-%d %H:%M:%S UTC"


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    recorded_at: str
    received_at: str
    accuracy_m: float | None = None

    @property
    def maps_url(self) -> str:
        return f"https://maps.google.com/?q={self.lat},{self.lon}"

    @property
    def when(self) -> str:
        return self.recorded_at or self.received_at


class LocationStore:
    """Async SQLite store for received location points."""

    def __init__(self, db_path: str, retention_days: int = 7) -> None:
        self._db_path = db_path
        self._retention_days = retention_days
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                recorded_at TEXT,
                received_at TEXT NOT NULL,
                accuracy_m REAL
            )
        """)
        await self._migrate_accuracy_column()
        await self._db.commit()

    async def _migrate_accuracy_column(self) -> None:
        assert self._db is not None
        async with self._db.execute("PRAGMA table_info(locations)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if "accuracy_m" not in columns:
            await self._db.execute("ALTER TABLE locations ADD COLUMN accuracy_m REAL")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def insert(
        self,
        lat: float,
        lon: float,
        recorded_at: str | None,
        accuracy_m: float | None = None,
    ) -> None:
        db = self._require_db()
        await db.execute(
            "INSERT INTO locations (lat, lon, recorded_at, received_at, accuracy_m) "
            "VALUES (?, ?, ?, ?, ?)",
            (lat, lon, recorded_at, _utc_now(), accuracy_m),
        )
        await db.commit()
        await self.prune()

    async def prune(self) -> int:
        """Delete points older than the retention window. Returns rows deleted."""
        db = self._require_db()
        cutoff = (datetime.now(UTC) - timedelta(days=self._retention_days)).strftime(TIME_FORMAT)
        cursor = await db.execute("DELETE FROM locations WHERE received_at < ?", (cutoff,))
        await db.commit()
        deleted = cursor.rowcount or 0
        if deleted:
            logger.info("Pruned %d location points older than %s", deleted, cutoff)
        return deleted

    async def get_latest(self) -> Location | None:
        recent = await self.get_recent(limit=1)
        return recent[-1] if recent else None

    async def get_recent(self, limit: int = 10, hours: int | None = None) -> list[Location]:
        """Return up to `limit` most recent points, oldest first."""
        db = self._require_db()
        query = "SELECT lat, lon, recorded_at, received_at, accuracy_m FROM locations"
        params: list[object] = []
        if hours is not None:
            query += " WHERE received_at >= ?"
            params.append((datetime.now(UTC) - timedelta(hours=hours)).strftime(TIME_FORMAT))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        async with db.execute(query, params) as cursor:
            rows = list(await cursor.fetchall())
        return [_to_location(row) for row in reversed(rows)]

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("LocationStore is not initialized")
        return self._db


def _to_location(row: Sequence[object]) -> Location:
    lat, lon, recorded_at, received_at, accuracy_m = row
    return Location(
        lat=float(str(lat)),
        lon=float(str(lon)),
        recorded_at=str(recorded_at) if recorded_at is not None else "",
        received_at=str(received_at),
        accuracy_m=float(str(accuracy_m)) if accuracy_m is not None else None,
    )


def _utc_now() -> str:
    return datetime.now(UTC).strftime(TIME_FORMAT)
