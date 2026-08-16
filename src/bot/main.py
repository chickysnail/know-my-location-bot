import logging
from collections.abc import Iterable
from datetime import UTC, datetime

from aiohttp import web
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from src.bot.config import Settings
from src.bot.handlers import BotHandlers
from src.bot.monitoring import Heartbeat
from src.bot.server import run_server
from src.bot.storage.locations import LocationStore
from src.bot.storage.users import UserStore

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


async def notify_admins(bot: Bot, admin_user_ids: Iterable[int], text: str) -> None:
    for admin_id in admin_user_ids:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.warning("Could not send %r to admin %d", text, admin_id)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    setup_logging(settings.log_level)

    locations = LocationStore(settings.database_path, retention_days=settings.retention_days)
    users = UserStore(settings.database_path)
    handlers = BotHandlers(
        locations=locations,
        users=users,
        access_password=settings.access_password,
        admin_user_ids=settings.admin_user_ids,
        allowed_user_ids=settings.allowed_user_ids,
        history_hours=settings.history_hours,
        history_points=settings.history_points,
    )

    # Private chats only: in a group the password and every /where answer would be
    # readable by all members, and every group message would count as an attempt.
    private = filters.ChatType.PRIVATE

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", handlers.start, filters=private))
    application.add_handler(CommandHandler("help", handlers.help_command, filters=private))
    application.add_handler(CommandHandler("where", handlers.where, filters=private))
    application.add_handler(CommandHandler("block", handlers.block, filters=private))
    application.add_handler(CommandHandler("unblock", handlers.unblock, filters=private))
    application.add_handler(CommandHandler("users", handlers.users_command, filters=private))
    application.add_handler(
        MessageHandler(private & filters.TEXT & ~filters.COMMAND, handlers.handle_password)
    )

    server_runner: web.AppRunner | None = None
    heartbeat = Heartbeat(
        settings.heartbeat_url,
        settings.heartbeat_interval_seconds,
    )

    async def post_init(app: Application) -> None:  # type: ignore[type-arg]
        nonlocal server_runner
        await locations.initialize()
        await users.initialize()
        await locations.prune()
        server_runner = await run_server(
            locations,
            settings.ingest_token,
            settings.port,
            settings.max_accuracy_m,
        )
        logger.info(
            "Bot started. Admins: %d, retention: %d days",
            len(settings.admin_user_ids),
            settings.retention_days,
        )
        heartbeat.start()
        await notify_admins(
            app.bot, settings.admin_user_ids, f"\U0001f7e2 Bot started at {_now()}"
        )

    async def post_shutdown(app: Application) -> None:  # type: ignore[type-arg]
        # A clean shutdown (redeploy, SIGTERM) is announced here; a crash is caught
        # by the heartbeat monitor instead.
        await notify_admins(
            app.bot, settings.admin_user_ids, f"\U0001f534 Bot shutting down at {_now()}"
        )
        await heartbeat.stop()
        if server_runner is not None:
            await server_runner.cleanup()
        await locations.close()
        await users.close()

    application.post_init = post_init
    application.post_shutdown = post_shutdown

    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
