from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers import DENIED_TEXT, NO_DATA_TEXT, BotHandlers
from src.bot.storage.locations import LocationStore

AUTHORIZED_ID = 111
UNAUTHORIZED_ID = 222


def make_update(user_id: int) -> Any:
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.reply_text = AsyncMock()
    return update


@pytest.fixture
async def store(tmp_path: Path) -> LocationStore:
    store = LocationStore(str(tmp_path / "locations.db"))
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
def handlers(store: LocationStore) -> BotHandlers:
    return BotHandlers(store=store, allowed_user_ids=[AUTHORIZED_ID])


async def test_where_denies_unauthorized(handlers: BotHandlers, store: LocationStore) -> None:
    await store.insert(1.0, 2.0, "2026/01/02 03:04")
    update = make_update(UNAUTHORIZED_ID)
    await handlers.where(update, MagicMock())
    update.message.reply_text.assert_awaited_once_with(DENIED_TEXT)


async def test_where_replies_with_maps_link(handlers: BotHandlers, store: LocationStore) -> None:
    await store.insert(55.75, 37.61, "2026/01/02 03:04")
    update = make_update(AUTHORIZED_ID)
    await handlers.where(update, MagicMock())
    text = update.message.reply_text.await_args.args[0]
    assert "https://maps.google.com/?q=55.75,37.61" in text
    assert "2026/01/02 03:04" in text


async def test_where_without_data(handlers: BotHandlers) -> None:
    update = make_update(AUTHORIZED_ID)
    await handlers.where(update, MagicMock())
    update.message.reply_text.assert_awaited_once_with(NO_DATA_TEXT)


async def test_start_denies_unauthorized(handlers: BotHandlers) -> None:
    update = make_update(UNAUTHORIZED_ID)
    await handlers.start(update, MagicMock())
    update.message.reply_text.assert_awaited_once_with(DENIED_TEXT)
