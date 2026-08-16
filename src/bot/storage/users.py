import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import aiosqlite

logger = logging.getLogger(__name__)

TIME_FORMAT = "%Y-%m-%d %H:%M:%S UTC"

USER_COLUMNS = (
    "user_id, username, authorized_at, last_request_at, request_count, "
    "blocked, authorized, failed_attempts"
)


@dataclass(frozen=True)
class AuthorizedUser:
    user_id: int
    username: str
    authorized_at: str
    last_request_at: str
    request_count: int
    blocked: bool
    authorized: bool = False
    failed_attempts: int = 0

    @property
    def label(self) -> str:
        return f"@{self.username} ({self.user_id})" if self.username else str(self.user_id)


class UserStore:
    """Async SQLite store of everyone who has talked to the bot.

    A row means "seen", not "allowed": wrong password attempts and blocks create
    rows too, so access is decided by the `authorized` flag alone.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                authorized_at TEXT,
                last_request_at TEXT,
                request_count INTEGER DEFAULT 0,
                blocked INTEGER DEFAULT 0,
                authorized INTEGER DEFAULT 0,
                failed_attempts INTEGER DEFAULT 0
            )
        """)
        await self._migrate_access_columns()
        await self._db.commit()

    async def _migrate_access_columns(self) -> None:
        assert self._db is not None
        async with self._db.execute("PRAGMA table_info(users)") as cursor:
            columns = {str(row[1]) for row in await cursor.fetchall()}
        if "failed_attempts" not in columns:
            await self._db.execute(
                "ALTER TABLE users ADD COLUMN failed_attempts INTEGER DEFAULT 0"
            )
        if "authorized" not in columns:
            await self._db.execute("ALTER TABLE users ADD COLUMN authorized INTEGER DEFAULT 0")
            # Before this column existed, any unblocked row granted access; keep it.
            await self._db.execute("UPDATE users SET authorized = 1 WHERE blocked = 0")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def authorize(self, user_id: int, username: str) -> None:
        db = self._require_db()
        await db.execute(
            """
            INSERT INTO users (
                user_id, username, authorized_at, last_request_at, request_count,
                blocked, authorized, failed_attempts
            )
            VALUES (?, ?, ?, ?, 0, 0, 1, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                authorized = 1,
                blocked = 0,
                failed_attempts = 0
            """,
            (user_id, username, _utc_now(), _utc_now()),
        )
        await db.commit()

    async def get(self, user_id: int) -> AuthorizedUser | None:
        db = self._require_db()
        async with db.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return _to_user(row) if row is not None else None

    async def list_users(self) -> list[AuthorizedUser]:
        db = self._require_db()
        async with db.execute(
            f"SELECT {USER_COLUMNS} FROM users ORDER BY blocked, last_request_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [_to_user(row) for row in rows]

    async def record_request(self, user_id: int, username: str) -> None:
        db = self._require_db()
        await db.execute(
            "UPDATE users SET last_request_at = ?, request_count = request_count + 1, "
            "username = ? WHERE user_id = ?",
            (_utc_now(), username, user_id),
        )
        await db.commit()

    async def set_blocked(self, user_id: int, blocked: bool) -> None:
        """Block or unblock a user; unblocking alone never grants access."""
        db = self._require_db()
        await db.execute(
            """
            INSERT INTO users (
                user_id, username, authorized_at, last_request_at, blocked, authorized
            )
            VALUES (?, '', ?, ?, ?, 0)
            ON CONFLICT(user_id) DO UPDATE SET blocked = excluded.blocked
            """,
            (user_id, _utc_now(), _utc_now(), int(blocked)),
        )
        await db.commit()

    async def record_failed_attempt(self, user_id: int, username: str) -> int:
        """Count a wrong password attempt and return this user's new total."""
        db = self._require_db()
        await db.execute(
            """
            INSERT INTO users (
                user_id, username, authorized_at, last_request_at, request_count,
                blocked, authorized, failed_attempts
            )
            VALUES (?, ?, '', ?, 0, 0, 0, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                failed_attempts = failed_attempts + 1
            """,
            (user_id, username, _utc_now()),
        )
        await db.commit()
        async with db.execute(
            "SELECT failed_attempts FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(str(row[0])) if row is not None else 0

    async def find_by_username(self, username: str) -> AuthorizedUser | None:
        db = self._require_db()
        async with db.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE lower(username) = ?",
            (username.lstrip("@").lower(),),
        ) as cursor:
            row = await cursor.fetchone()
        return _to_user(row) if row is not None else None

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("UserStore is not initialized")
        return self._db


def _to_user(row: Sequence[object]) -> AuthorizedUser:
    (
        user_id,
        username,
        authorized_at,
        last_request_at,
        request_count,
        blocked,
        authorized,
        failed_attempts,
    ) = row
    return AuthorizedUser(
        user_id=int(str(user_id)),
        username=str(username) if username is not None else "",
        authorized_at=str(authorized_at) if authorized_at is not None else "",
        last_request_at=str(last_request_at) if last_request_at is not None else "",
        request_count=int(str(request_count)) if request_count is not None else 0,
        blocked=bool(blocked),
        authorized=bool(authorized),
        failed_attempts=int(str(failed_attempts)) if failed_attempts is not None else 0,
    )


def _utc_now() -> str:
    return datetime.now(UTC).strftime(TIME_FORMAT)
