import asyncio

import pytest

from src.bot.monitoring import Heartbeat


@pytest.mark.asyncio
async def test_disabled_without_url() -> None:
    heartbeat = Heartbeat("", sender=_fail)
    assert not heartbeat.enabled
    heartbeat.start()
    await heartbeat.stop()


@pytest.mark.asyncio
async def test_pings_repeatedly_until_stopped() -> None:
    pings: list[str] = []

    async def sender(url: str) -> None:
        pings.append(url)

    heartbeat = Heartbeat("https://monitor.example/ping/abc", 0, sender=sender)
    heartbeat.start()
    while len(pings) < 3:
        await asyncio.sleep(0)
    await heartbeat.stop()
    before = len(pings)
    await asyncio.sleep(0)
    assert len(pings) == before
    assert pings[0] == "https://monitor.example/ping/abc"


@pytest.mark.asyncio
async def test_failed_ping_is_swallowed() -> None:
    heartbeat = Heartbeat("https://monitor.example/ping/abc", sender=_fail)
    assert await heartbeat.ping() is False


@pytest.mark.asyncio
async def test_loop_survives_a_failing_ping() -> None:
    attempts = 0

    async def flaky(url: str) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("monitor unreachable")

    heartbeat = Heartbeat("https://monitor.example/ping/abc", 0, sender=flaky)
    heartbeat.start()
    while attempts < 3:
        await asyncio.sleep(0)
    await heartbeat.stop()


async def _fail(url: str) -> None:
    raise RuntimeError("monitor unreachable")
