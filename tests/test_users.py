from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from src.bot.storage.users import UserStore


@pytest.fixture
async def users(tmp_path: Path) -> AsyncIterator[UserStore]:
    store = UserStore(str(tmp_path / "locations.db"))
    await store.initialize()
    yield store
    await store.close()


async def test_unknown_user(users: UserStore) -> None:
    assert await users.get(1) is None
    assert await users.list_users() == []


async def test_authorize_and_get(users: UserStore) -> None:
    await users.authorize(1, "alice")
    user = await users.get(1)
    assert user is not None
    assert user.username == "alice"
    assert user.blocked is False
    assert user.request_count == 0
    assert user.label == "@alice (1)"


async def test_authorize_twice_updates_username(users: UserStore) -> None:
    await users.authorize(1, "alice")
    await users.authorize(1, "alice_new")
    user = await users.get(1)
    assert user is not None
    assert user.username == "alice_new"


async def test_record_request_increments_counter(users: UserStore) -> None:
    await users.authorize(1, "alice")
    await users.record_request(1, "alice")
    await users.record_request(1, "alice")
    user = await users.get(1)
    assert user is not None
    assert user.request_count == 2
    assert user.last_request_at


async def test_set_blocked_toggles(users: UserStore) -> None:
    await users.authorize(1, "alice")
    await users.set_blocked(1, True)
    user = await users.get(1)
    assert user is not None and user.blocked is True

    await users.set_blocked(1, False)
    user = await users.get(1)
    assert user is not None and user.blocked is False
    assert user.username == "alice"


async def test_set_blocked_does_not_authorize(users: UserStore) -> None:
    await users.set_blocked(999, False)
    user = await users.get(999)
    assert user is not None
    assert user.blocked is False
    assert user.authorized is False


async def test_failed_attempts_are_counted(users: UserStore) -> None:
    assert await users.record_failed_attempt(5, "eve") == 1
    assert await users.record_failed_attempt(5, "eve") == 2
    user = await users.get(5)
    assert user is not None
    assert user.authorized is False
    assert user.failed_attempts == 2


async def test_authorize_clears_failed_attempts(users: UserStore) -> None:
    await users.record_failed_attempt(5, "eve")
    await users.authorize(5, "eve")
    user = await users.get(5)
    assert user is not None
    assert user.authorized is True
    assert user.failed_attempts == 0


async def test_block_unknown_user_id(users: UserStore) -> None:
    await users.set_blocked(999, True)
    user = await users.get(999)
    assert user is not None
    assert user.blocked is True
    assert user.label == "999"


async def test_find_by_username_is_case_insensitive(users: UserStore) -> None:
    await users.authorize(7, "Alice")
    assert (await users.find_by_username("@alice")) is not None
    assert (await users.find_by_username("ALICE")) is not None
    assert (await users.find_by_username("bob")) is None


async def test_list_users_puts_blocked_last(users: UserStore) -> None:
    await users.authorize(1, "alice")
    await users.authorize(2, "bob")
    await users.set_blocked(1, True)
    listed = await users.list_users()
    assert [u.user_id for u in listed] == [2, 1]
