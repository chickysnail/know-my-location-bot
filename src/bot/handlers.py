import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.history import format_history
from src.bot.storage.locations import LocationStore
from src.bot.storage.users import UserStore

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "This bot reports where I am, based on points my phone sends automatically.\n\n"
    "/where — my recent locations\n"
    "/help — this message"
)

LOCKED_TEXT = "This bot is password protected. Send: /start <password>"
WRONG_PASSWORD_TEXT = "Wrong password."
UNLOCKED_TEXT = "Access granted. Send /where to see my recent locations."
ADMIN_ONLY_TEXT = "Admins only."
USAGE_BLOCK_TEXT = "Usage: /block <user_id|@username>"
USAGE_UNBLOCK_TEXT = "Usage: /unblock <user_id|@username>"
NO_USERS_TEXT = "Nobody has unlocked the bot yet."


class BotHandlers:
    def __init__(
        self,
        locations: LocationStore,
        users: UserStore,
        access_password: str,
        admin_user_ids: list[int],
        allowed_user_ids: list[int],
        history_hours: int,
        history_points: int,
    ) -> None:
        self._locations = locations
        self._users = users
        self._access_password = access_password
        self._admin_user_ids = admin_user_ids
        self._allowed_user_ids = allowed_user_ids
        self._history_hours = history_hours
        self._history_points = history_points

    # --- commands -----------------------------------------------------

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.message, update.effective_user
        if message is None or user is None:
            return
        if await self._is_blocked(user.id):
            return

        password = " ".join(context.args or []).strip()
        if await self._is_authorized(user.id):
            await message.reply_text(HELP_TEXT)
            return
        if not password:
            await message.reply_text(LOCKED_TEXT)
            return
        await self._try_password(update, context, password)

    async def handle_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """A plain text message is treated as a password attempt."""
        message, user = update.message, update.effective_user
        if message is None or user is None or message.text is None:
            return
        if await self._is_blocked(user.id):
            return
        if await self._is_authorized(user.id):
            await message.reply_text(HELP_TEXT)
            return
        await self._try_password(update, context, message.text.strip())

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        if not await self._guard(update):
            return
        await update.message.reply_text(HELP_TEXT)

    async def where(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message, user = update.message, update.effective_user
        if message is None or user is None:
            return
        if not await self._guard(update):
            return

        await self._users.record_request(user.id, user.username or "")
        points = await self._locations.get_recent(
            limit=self._history_points, hours=self._history_hours
        )
        if not points:
            # Nothing inside the window — fall back to the last known point.
            latest = await self._locations.get_latest()
            points = [latest] if latest else []

        await message.reply_text(
            format_history(points, self._history_hours),
            disable_web_page_preview=True,
        )
        suffix = "" if points else " (no points stored yet)"
        await self._notify_admins(
            context, f"\U0001f440 {_user_label(user)} asked for my location{suffix}."
        )

    # --- admin commands -----------------------------------------------

    async def block(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._set_blocked(update, context, blocked=True, usage=USAGE_BLOCK_TEXT)

    async def unblock(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._set_blocked(update, context, blocked=False, usage=USAGE_UNBLOCK_TEXT)

    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.message
        if message is None or not await self._require_admin(update):
            return
        users = await self._users.list_users()
        if not users:
            await message.reply_text(NO_USERS_TEXT)
            return
        lines = []
        for u in users:
            marker = "\U0001f6ab" if u.blocked else "\u2705"
            last = u.last_request_at or "never"
            lines.append(f"{marker} {u.label} — {u.request_count} request(s), last {last}")
        await message.reply_text("\n".join(lines))

    async def _set_blocked(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        blocked: bool,
        usage: str,
    ) -> None:
        message = update.message
        if message is None or not await self._require_admin(update):
            return
        args = context.args or []
        if not args:
            await message.reply_text(usage)
            return

        target = args[0]
        user_id = int(target) if target.lstrip("-").isdigit() else None
        if user_id is None:
            known = await self._users.find_by_username(target)
            if known is None:
                await message.reply_text(
                    f"Unknown user {target}. Only users who unlocked the bot can be "
                    "referenced by username; use their numeric id otherwise."
                )
                return
            user_id = known.user_id

        await self._users.set_blocked(user_id, blocked)
        await message.reply_text(f"{'Blocked' if blocked else 'Unblocked'} {user_id}.")

    # --- helpers ------------------------------------------------------

    async def _try_password(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        attempt: str,
    ) -> None:
        message, user = update.message, update.effective_user
        if message is None or user is None:
            return
        if attempt != self._access_password:
            logger.warning("Wrong password attempt from %s", user.id)
            await message.reply_text(WRONG_PASSWORD_TEXT)
            await self._notify_admins(
                context, f"\u26a0\ufe0f Wrong password attempt by {_user_label(user)}."
            )
            return

        await self._users.authorize(user.id, user.username or "")
        await message.reply_text(UNLOCKED_TEXT)
        await self._notify_admins(
            context, f"\U0001f513 {_user_label(user)} unlocked the bot with the password."
        )

    async def _is_authorized(self, user_id: int) -> bool:
        if user_id in self._admin_user_ids or user_id in self._allowed_user_ids:
            return True
        known = await self._users.get(user_id)
        return known is not None and not known.blocked

    async def _is_blocked(self, user_id: int) -> bool:
        known = await self._users.get(user_id)
        return known is not None and known.blocked

    async def _guard(self, update: Update) -> bool:
        """Reply with a hint and return False when the user has no access."""
        user, message = update.effective_user, update.message
        if user is None:
            return False
        if await self._is_authorized(user.id):
            return True
        if message is not None:
            blocked = await self._is_blocked(user.id)
            if not blocked:
                await message.reply_text(LOCKED_TEXT)
            else:
                logger.warning("Ignored request from blocked user %d", user.id)
        return False

    async def _require_admin(self, update: Update) -> bool:
        user = update.effective_user
        if user is not None and user.id in self._admin_user_ids:
            return True
        if update.message is not None:
            await update.message.reply_text(ADMIN_ONLY_TEXT)
        return False

    async def _notify_admins(self, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        for admin_id in self._admin_user_ids:
            try:
                await context.bot.send_message(chat_id=admin_id, text=text)
            except Exception:
                logger.exception("Failed to notify admin %d", admin_id)


def _user_label(user: object) -> str:
    name = getattr(user, "username", None)
    user_id = getattr(user, "id", "unknown")
    return f"@{name} ({user_id})" if name else f"id {user_id}"
