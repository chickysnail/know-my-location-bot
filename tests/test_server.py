from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.bot.server import CoordinateError, create_app, parse_accuracy, parse_coordinates
from src.bot.storage.locations import LocationStore

TOKEN = "test-token"
PAYLOAD = {
    "coordinates": "55.751244,37.618423",
    "accuracy": "18.5",
    "time": "2026/01/02 03:04",
}


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[LocationStore]:
    store = LocationStore(str(tmp_path / "locations.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def client(store: LocationStore) -> AsyncIterator[TestClient]:
    client = TestClient(TestServer(create_app(store, TOKEN, max_accuracy_m=500.0)))
    await client.start_server()
    yield client
    await client.close()


async def test_ingest_requires_token(client: TestClient, store: LocationStore) -> None:
    response = await client.post("/ingest", json=PAYLOAD)
    assert response.status == 401
    assert await store.get_latest() is None


async def test_ingest_rejects_wrong_token(client: TestClient) -> None:
    response = await client.post("/ingest", json=PAYLOAD, headers={"X-Auth-Token": "nope"})
    assert response.status == 401


async def test_ingest_stores_point(client: TestClient, store: LocationStore) -> None:
    response = await client.post("/ingest", json=PAYLOAD, headers={"X-Auth-Token": TOKEN})
    assert response.status == 200

    latest = await store.get_latest()
    assert latest is not None
    assert latest.lat == pytest.approx(55.751244)
    assert latest.lon == pytest.approx(37.618423)
    assert latest.recorded_at == "2026/01/02 03:04"
    assert latest.accuracy_m == pytest.approx(18.5)


async def test_ingest_without_accuracy(client: TestClient, store: LocationStore) -> None:
    response = await client.post(
        "/ingest",
        json={"coordinates": "1.0,2.0", "time": "2026/01/02 03:04"},
        headers={"X-Auth-Token": TOKEN},
    )
    assert response.status == 200
    latest = await store.get_latest()
    assert latest is not None
    assert latest.accuracy_m is None


async def test_ingest_discards_inaccurate_point(client: TestClient, store: LocationStore) -> None:
    response = await client.post(
        "/ingest",
        json={"coordinates": "1.0,2.0", "accuracy": "5000", "time": "2026/01/02 03:04"},
        headers={"X-Auth-Token": TOKEN},
    )
    assert response.status == 200
    assert (await response.json())["status"] == "discarded"
    assert await store.get_latest() is None


async def test_ingest_rejects_bad_coordinates(client: TestClient) -> None:
    response = await client.post(
        "/ingest",
        json={"coordinates": "not-a-point", "time": "2026/01/02 03:04"},
        headers={"X-Auth-Token": TOKEN},
    )
    assert response.status == 400


async def test_health(client: TestClient) -> None:
    response = await client.get("/health")
    assert response.status == 200


def test_parse_coordinates() -> None:
    assert parse_coordinates("55.751244,37.618423") == (55.751244, 37.618423)
    assert parse_coordinates(" -1.5 , 2.25 ") == (-1.5, 2.25)


def test_parse_coordinates_rejects_extra_components() -> None:
    with pytest.raises(CoordinateError):
        parse_coordinates("1.0,2.0,3.0")


def test_parse_coordinates_accepts_space_separator() -> None:
    assert parse_coordinates("55.75 37.61") == (55.75, 37.61)


def test_parse_coordinates_flags_unset_tasker_variable() -> None:
    with pytest.raises(CoordinateError, match="was not set"):
        parse_coordinates("%gl_coordinates")


@pytest.mark.parametrize("raw", ["", "1.0", None, 42, "a,b"])
def test_parse_coordinates_rejects_invalid(raw: object) -> None:
    with pytest.raises(CoordinateError):
        parse_coordinates(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("18.5", 18.5),
        (" 30 ", 30.0),
        (12, 12.0),
        (None, None),
        ("", None),
        ("%gl_coordinates_accuracy", None),
        ("-1", None),
    ],
)
def test_parse_accuracy(raw: object, expected: float | None) -> None:
    assert parse_accuracy(raw) == expected
