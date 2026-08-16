import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.bot.storage.locations import LocationStore

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "This bot reports the latest location point it received.\n\n"
    "/where — show the latest location\n"
    "/help — show this message"
)

DENIED_TEXT = "You are not authorized to use this bot."
NO_DATA_TEXT = "No location points received yet."


class BotHandlers:
    def __init__(self, store: LocationStore, allowed_user_ids: list[int]) -> None:
        self._store = store
        self._allowed_user_ids = allowed_user_ids

    def _is_authorized(self, update: Update) -> bool:
        user = update.effective_user
        return user is not None and user.id in self._allowed_user_ids

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.message.reply_text(HELP_TEXT)  # type: ignore[union-attr]

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        await update.message.reply_text(HELP_TEXT)  # type: ignore[union-attr]

    async def where(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._guard(update):
            return
        location = await self._store.get_latest()
        if location is None:
            await update.message.reply_text(NO_DATA_TEXT)  # type: ignore[union-attr]
            return
        recorded = location.recorded_at or location.received_at
        await update.message.reply_text(  # type: ignore[union-attr]
            f"{location.maps_url}\nRecorded at: {recorded}"
        )

    async def _guard(self, update: Update) -> bool:
        """Reply with a denial and return False for unauthorized users."""
        if self._is_authorized(update):
            return True
        user = update.effective_user
        logger.warning("Denied request from user %s", user.id if user else "unknown")
        if update.message is not None:
            await update.message.reply_text(DENIED_TEXT)
        return False
