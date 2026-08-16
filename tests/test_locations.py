import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.bot.storage.locations import TIME_FORMAT, LocationStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[LocationStore]:
    store = LocationStore(str(tmp_path / "locations.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_get_latest_empty(store: LocationStore) -> None:
    assert await store.get_latest() is None
    assert await store.get_recent() == []


async def test_insert_and_get_latest(store: LocationStore) -> None:
    await store.insert(1.5, 2.5, "2026/01/02 03:04", 12.0)
    latest = await store.get_latest()
    assert latest is not None
    assert (latest.lat, latest.lon) == (1.5, 2.5)
    assert latest.recorded_at == "2026/01/02 03:04"
    assert latest.accuracy_m == 12.0
    assert latest.received_at


async def test_get_latest_returns_most_recent_insert(store: LocationStore) -> None:
    await store.insert(1.0, 1.0, "2026/01/02 03:04")
    await store.insert(2.0, 2.0, "2026/01/02 03:09")
    latest = await store.get_latest()
    assert latest is not None
    assert (latest.lat, latest.lon) == (2.0, 2.0)
    assert latest.accuracy_m is None


async def test_get_recent_is_oldest_first_and_limited(store: LocationStore) -> None:
    for i in range(5):
        await store.insert(float(i), float(i), None)
    points = await store.get_recent(limit=3)
    assert [p.lat for p in points] == [2.0, 3.0, 4.0]


async def test_get_recent_filters_by_hours(store: LocationStore, tmp_path: Path) -> None:
    await store.insert(1.0, 1.0, None)
    _backdate(tmp_path / "locations.db", hours=48)
    await store.insert(2.0, 2.0, None)

    points = await store.get_recent(limit=10, hours=6)
    assert [p.lat for p in points] == [2.0]


async def test_maps_url(store: LocationStore) -> None:
    await store.insert(55.75, 37.61, None)
    latest = await store.get_latest()
    assert latest is not None
    assert latest.maps_url == "https://maps.google.com/?q=55.75,37.61"
    assert latest.recorded_at == ""


async def test_prune_drops_points_outside_retention(tmp_path: Path) -> None:
    store = LocationStore(str(tmp_path / "locations.db"), retention_days=7)
    await store.initialize()
    try:
        await store.insert(1.0, 1.0, None)
        _backdate(tmp_path / "locations.db", hours=24 * 8)
        assert await store.prune() == 1
        assert await store.get_latest() is None
    finally:
        await store.close()


async def test_insert_prunes_old_points(tmp_path: Path) -> None:
    store = LocationStore(str(tmp_path / "locations.db"), retention_days=7)
    await store.initialize()
    try:
        await store.insert(1.0, 1.0, None)
        _backdate(tmp_path / "locations.db", hours=24 * 8)
        await store.insert(2.0, 2.0, None)
        points = await store.get_recent(limit=10)
        assert [p.lat for p in points] == [2.0]
    finally:
        await store.close()


async def test_insert_requires_initialize(tmp_path: Path) -> None:
    store = LocationStore(str(tmp_path / "locations.db"))
    with pytest.raises(RuntimeError):
        await store.insert(1.0, 1.0, None)


def _backdate(db_path: Path, hours: int) -> None:
    """Rewrite every stored point's received_at into the past."""
    stamp = (datetime.now(UTC) - timedelta(hours=hours)).strftime(TIME_FORMAT)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE locations SET received_at = ?", (stamp,))
