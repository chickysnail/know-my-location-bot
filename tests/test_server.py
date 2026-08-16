from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.bot.server import CoordinateError, create_app, parse_coordinates
from src.bot.storage.locations import LocationStore

TOKEN = "test-token"
PAYLOAD = {"coordinates": "55.751244,37.618423", "time": "2026/01/02 03:04"}


@pytest.fixture
async def store(tmp_path: Path) -> LocationStore:
    store = LocationStore(str(tmp_path / "locations.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def client(store: LocationStore) -> TestClient:
    client = TestClient(TestServer(create_app(store, TOKEN)))
    await client.start_server()
    yield client
    await client.close()


async def test_ingest_requires_token(client: TestClient, store: LocationStore) -> None:
    response = await client.post("/ingest", json=PAYLOAD)
    assert response.status == 401
    assert await store.get_latest() is None


async def test_ingest_rejects_wrong_token(client: TestClient) -> None:
    response = await client.post(
        "/ingest", json=PAYLOAD, headers={"X-Auth-Token": "nope"}
    )
    assert response.status == 401


async def test_ingest_stores_point(client: TestClient, store: LocationStore) -> None:
    response = await client.post(
        "/ingest", json=PAYLOAD, headers={"X-Auth-Token": TOKEN}
    )
    assert response.status == 200

    latest = await store.get_latest()
    assert latest is not None
    assert latest.lat == pytest.approx(55.751244)
    assert latest.lon == pytest.approx(37.618423)
    assert latest.recorded_at == "2026/01/02 03:04"


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


@pytest.mark.parametrize("raw", ["", "1.0", None, 42, "a,b"])
def test_parse_coordinates_rejects_invalid(raw: object) -> None:
    with pytest.raises(CoordinateError):
        parse_coordinates(raw)
