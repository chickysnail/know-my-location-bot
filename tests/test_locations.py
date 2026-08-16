from pathlib import Path

import pytest

from src.bot.storage.locations import LocationStore


@pytest.fixture
async def store(tmp_path: Path) -> LocationStore:
    store = LocationStore(str(tmp_path / "locations.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_get_latest_empty(store: LocationStore) -> None:
    assert await store.get_latest() is None


async def test_insert_and_get_latest(store: LocationStore) -> None:
    await store.insert(1.5, 2.5, "2026/01/02 03:04")
    latest = await store.get_latest()
    assert latest is not None
    assert (latest.lat, latest.lon) == (1.5, 2.5)
    assert latest.recorded_at == "2026/01/02 03:04"
    assert latest.received_at


async def test_get_latest_returns_most_recent_insert(store: LocationStore) -> None:
    await store.insert(1.0, 1.0, "2026/01/02 03:04")
    await store.insert(2.0, 2.0, "2026/01/02 03:09")
    latest = await store.get_latest()
    assert latest is not None
    assert (latest.lat, latest.lon) == (2.0, 2.0)


async def test_maps_url(store: LocationStore) -> None:
    await store.insert(55.75, 37.61, None)
    latest = await store.get_latest()
    assert latest is not None
    assert latest.maps_url == "https://maps.google.com/?q=55.75,37.61"
    assert latest.recorded_at == ""


async def test_insert_requires_initialize(tmp_path: Path) -> None:
    store = LocationStore(str(tmp_path / "locations.db"))
    with pytest.raises(RuntimeError):
        await store.insert(1.0, 1.0, None)
