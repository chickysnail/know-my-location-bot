from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers import (
    ADMIN_ONLY_TEXT,
    HELP_TEXT,
    LOCKED_TEXT,
    UNLOCKED_TEXT,
    WRONG_PASSWORD_TEXT,
    BotHandlers,
)
from src.bot.storage.locations import LocationStore
from src.bot.storage.users import UserStore

PASSWORD = "let-me-in"
ADMIN_ID = 1
STRANGER_ID = 2


def make_update(user_id: int, username: str = "", text: str = "") -> Any:
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.username = username
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context(*args: str) -> Any:
    context = MagicMock()
    context.args = list(args)
    context.bot.send_message = AsyncMock()
    return context


def replies(update: Any) -> list[str]:
    return [call.args[0] for call in update.message.reply_text.await_args_list]


@pytest.fixture
async def stores(tmp_path: Path) -> AsyncIterator[tuple[LocationStore, UserStore]]:
    locations = LocationStore(str(tmp_path / "locations.db"))
    users = UserStore(str(tmp_path / "locations.db"))
    await locations.initialize()
    await users.initialize()
    yield locations, users
    await locations.close()
    await users.close()


@pytest.fixture
def handlers(stores: tuple[LocationStore, UserStore]) -> BotHandlers:
    locations, users = stores
    return BotHandlers(
        locations=locations,
        users=users,
        access_password=PASSWORD,
        admin_user_ids=[ADMIN_ID],
        allowed_user_ids=[],
        history_hours=6,
        history_points=10,
    )


async def test_start_without_password_is_locked(handlers: BotHandlers) -> None:
    update = make_update(STRANGER_ID)
    await handlers.start(update, make_context())
    assert replies(update) == [LOCKED_TEXT]


async def test_where_requires_password(handlers: BotHandlers) -> None:
    update = make_update(STRANGER_ID)
    await handlers.where(update, make_context())
    assert replies(update) == [LOCKED_TEXT]


async def test_wrong_password_notifies_admin(handlers: BotHandlers) -> None:
    update = make_update(STRANGER_ID, "eve")
    context = make_context("nope")
    await handlers.start(update, context)
    assert replies(update) == [WRONG_PASSWORD_TEXT]
    notification = context.bot.send_message.await_args.kwargs["text"]
    assert "@eve (2)" in notification


async def test_correct_password_grants_access(
    handlers: BotHandlers, stores: tuple[LocationStore, UserStore]
) -> None:
    _, users = stores
    update = make_update(STRANGER_ID, "bob")
    await handlers.start(update, make_context(PASSWORD))
    assert replies(update) == [UNLOCKED_TEXT]
    user = await users.get(STRANGER_ID)
    assert user is not None and user.username == "bob"


async def test_plain_text_password_grants_access(handlers: BotHandlers) -> None:
    update = make_update(STRANGER_ID, "bob", text=PASSWORD)
    await handlers.handle_password(update, make_context())
    assert replies(update) == [UNLOCKED_TEXT]


async def test_where_after_unlock_reports_track(
    handlers: BotHandlers, stores: tuple[LocationStore, UserStore]
) -> None:
    locations, _ = stores
    await locations.insert(1.0, 1.0, "2026/01/02 01:00", 15.0)
    await locations.insert(2.0, 2.0, "2026/01/02 02:00", 25.0)

    await handlers.start(make_update(STRANGER_ID, "bob"), make_context(PASSWORD))
    update = make_update(STRANGER_ID, "bob")
    context = make_context()
    await handlers.where(update, context)

    text = replies(update)[0]
    assert "https://maps.google.com/?q=2.0,2.0" in text
    assert "\u00b125 m" in text
    assert "https://www.google.com/maps/dir/" in text
    assert "asked for my location" in context.bot.send_message.await_args.kwargs["text"]


async def test_blocked_user_is_ignored(
    handlers: BotHandlers, stores: tuple[LocationStore, UserStore]
) -> None:
    locations, users = stores
    await locations.insert(1.0, 1.0, "2026/01/02 01:00")
    await users.authorize(STRANGER_ID, "bob")
    await users.set_blocked(STRANGER_ID, True)

    update = make_update(STRANGER_ID, "bob")
    await handlers.where(update, make_context())
    assert replies(update) == []


async def test_admin_needs_no_password(
    handlers: BotHandlers, stores: tuple[LocationStore, UserStore]
) -> None:
    locations, _ = stores
    await locations.insert(1.0, 1.0, "2026/01/02 01:00")
    update = make_update(ADMIN_ID, "admin")
    await handlers.where(update, make_context())
    assert "https://maps.google.com/?q=1.0,1.0" in replies(update)[0]


async def test_block_by_username(
    handlers: BotHandlers, stores: tuple[LocationStore, UserStore]
) -> None:
    _, users = stores
    await users.authorize(STRANGER_ID, "bob")

    update = make_update(ADMIN_ID, "admin")
    await handlers.block(update, make_context("@bob"))
    user = await users.get(STRANGER_ID)
    assert user is not None and user.blocked is True

    await handlers.unblock(make_update(ADMIN_ID, "admin"), make_context("@bob"))
    user = await users.get(STRANGER_ID)
    assert user is not None and user.blocked is False


async def test_block_by_user_id_of_unknown_user(
    handlers: BotHandlers, stores: tuple[LocationStore, UserStore]
) -> None:
    _, users = stores
    await handlers.block(make_update(ADMIN_ID, "admin"), make_context("4242"))
    user = await users.get(4242)
    assert user is not None and user.blocked is True


async def test_block_by_unknown_username_reports_error(handlers: BotHandlers) -> None:
    update = make_update(ADMIN_ID, "admin")
    await handlers.block(update, make_context("@nobody"))
    assert "Unknown user @nobody" in replies(update)[0]


async def test_block_requires_admin(handlers: BotHandlers) -> None:
    update = make_update(STRANGER_ID, "bob")
    await handlers.block(update, make_context("4242"))
    assert replies(update) == [ADMIN_ONLY_TEXT]


async def test_users_command_lists_access(
    handlers: BotHandlers, stores: tuple[LocationStore, UserStore]
) -> None:
    _, users = stores
    await users.authorize(STRANGER_ID, "bob")
    await users.record_request(STRANGER_ID, "bob")

    update = make_update(ADMIN_ID, "admin")
    await handlers.users_command(update, make_context())
    listing = replies(update)[0]
    assert "@bob (2)" in listing
    assert "1 request(s)" in listing


async def test_help_for_authorized_user(handlers: BotHandlers) -> None:
    update = make_update(ADMIN_ID, "admin")
    await handlers.help_command(update, make_context())
    assert replies(update) == [HELP_TEXT]
