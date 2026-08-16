import hmac
import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from src.bot.history import format_history
from src.bot.storage.locations import LocationStore
from src.bot.storage.users import UserStore

logger = logging.getLogger(__name__)

WHERE_BUTTON_TEXT = "\U0001f4cd Where"
WHERE_KEYBOARD = ReplyKeyboardMarkup([[KeyboardButton(WHERE_BUTTON_TEXT)]], resize_keyboard=True)

HELP_TEXT = (
    "This bot reports where I am, based on points my phone sends automatically.\n\n"
    f"/where — my recent locations (or tap {WHERE_BUTTON_TEXT})\n"
    "/help — this message"
)

LOCKED_TEXT = "This bot is password protected. Send: /start <password>"
WRONG_PASSWORD_TEXT = "Wrong password."
UNLOCKED_TEXT = "Access granted. Send /where to see my recent locations."
LOCKOUT_TEXT = (
    "Too many wrong password attempts. Contact the owner of this bot directly "
    "to be given access."
)
ADMIN_ONLY_TEXT = "Admins only."
USAGE_BLOCK_TEXT = "Usage: /block <user_id|@username>"
USAGE_UNBLOCK_TEXT = "Usage: /unblock <user_id|@username>"
NO_USERS_TEXT = "Nobody has unlocked the bot yet."

# Wrong password attempts a user gets before they have to ask the owner directly.
MAX_PASSWORD_ATTEMPTS = 5

# Attempted passwords are relayed to admins; keep the message a sane size.
ATTEMPT_PREVIEW_LIMIT = 200


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
        await self._notify_admins(context, f"\U0001f44b {_user_label(user)} sent /start.")
        if await self._is_authorized(user.id):
            await message.reply_text(HELP_TEXT, reply_markup=WHERE_KEYBOARD)
            return
        if not password:
            await message.reply_text(await self._locked_text(user.id))
            return
        await self._try_password(update, context, password)

    async def handle_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """A plain text message is treated as a password attempt."""
        message, user = update.message, update.effective_user
        if message is None or user is None or message.text is None:
            return
        if await self._is_blocked(user.id):
            return
        text = message.text.strip()
        if text == WHERE_BUTTON_TEXT and await self._is_authorized(user.id):
            await self.where(update, context)
            return
        if await self._is_authorized(user.id):
            await message.reply_text(HELP_TEXT, reply_markup=WHERE_KEYBOARD)
            return
        await self._try_password(update, context, text)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        if not await self._guard(update):
            return
        await update.message.reply_text(HELP_TEXT, reply_markup=WHERE_KEYBOARD)

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
            marker = "\U0001f6ab" if u.blocked else "\u2705" if u.authorized else "\u2753"
            last = u.last_request_at or "never"
            attempts = f", {u.failed_attempts} wrong password(s)" if u.failed_attempts else ""
            lines.append(
                f"{marker} {u.label} — {u.request_count} request(s), last {last}{attempts}"
            )
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
        user_id = await self._resolve_target(update, context, usage)
        if user_id is None:
            return

        if blocked:
            await self._users.set_blocked(user_id, True)
            await message.reply_text(f"Blocked {user_id}.")
            return

        # Unblocking is how an admin hands out access: it also clears a lockout.
        known = await self._users.get(user_id)
        await self._users.authorize(user_id, known.username if known else "")
        await message.reply_text(f"Unblocked {user_id}, they now have access.")
        try:
            await context.bot.send_message(chat_id=user_id, text=UNLOCKED_TEXT)
        except Exception:
            logger.info("Could not tell %d about the granted access", user_id)

    async def _resolve_target(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        usage: str,
    ) -> int | None:
        """Turn the command's argument into a user id, replying when it cannot."""
        message = update.message
        if message is None:
            return None
        args = context.args or []
        if not args:
            await message.reply_text(usage)
            return None

        target = args[0]
        if target.lstrip("-").isdigit():
            return int(target)
        known = await self._users.find_by_username(target)
        if known is None:
            await message.reply_text(
                f"Unknown user {target}. Only users the bot has already seen can be "
                "referenced by username; use their numeric id otherwise."
            )
            return None
        return known.user_id

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
        if await self._is_locked_out(user.id):
            await message.reply_text(LOCKOUT_TEXT)
            return
        if not hmac.compare_digest(attempt, self._access_password):
            attempts = await self._users.record_failed_attempt(user.id, user.username or "")
            logger.warning("Wrong password attempt %d from %s", attempts, user.id)
            left = MAX_PASSWORD_ATTEMPTS - attempts
            await message.reply_text(
                LOCKOUT_TEXT if left <= 0 else f"{WRONG_PASSWORD_TEXT} {left} attempt(s) left."
            )
            await self._notify_admins(
                context,
                f"\u26a0\ufe0f Wrong password attempt {attempts}/{MAX_PASSWORD_ATTEMPTS} by "
                f"{_user_label(user)}, they tried: {_preview(attempt)}",
            )
            return

        await self._users.authorize(user.id, user.username or "")
        await message.reply_text(UNLOCKED_TEXT, reply_markup=WHERE_KEYBOARD)
        await self._notify_admins(
            context, f"\U0001f513 {_user_label(user)} unlocked the bot with the password."
        )

    async def _is_authorized(self, user_id: int) -> bool:
        if user_id in self._admin_user_ids or user_id in self._allowed_user_ids:
            return True
        known = await self._users.get(user_id)
        return known is not None and known.authorized and not known.blocked

    async def _is_locked_out(self, user_id: int) -> bool:
        known = await self._users.get(user_id)
        return known is not None and known.failed_attempts >= MAX_PASSWORD_ATTEMPTS

    async def _locked_text(self, user_id: int) -> str:
        return LOCKOUT_TEXT if await self._is_locked_out(user_id) else LOCKED_TEXT

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
                await message.reply_text(await self._locked_text(user.id))
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


def _preview(attempt: str) -> str:
    return repr(" ".join(attempt.split())[:ATTEMPT_PREVIEW_LIMIT])


def _user_label(user: object) -> str:
    name = getattr(user, "username", None)
    user_id = getattr(user, "id", "unknown")
    return f"@{name} ({user_id})" if name else f"id {user_id}"
