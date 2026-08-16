import logging

from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler

from src.bot.config import Settings
from src.bot.handlers import BotHandlers
from src.bot.server import run_server
from src.bot.storage.locations import LocationStore

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    setup_logging(settings.log_level)

    store = LocationStore(settings.database_path)
    handlers = BotHandlers(store=store, allowed_user_ids=settings.allowed_user_ids)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("where", handlers.where))

    server_runner: web.AppRunner | None = None

    async def post_init(app: Application) -> None:  # type: ignore[type-arg]
        nonlocal server_runner
        await store.initialize()
        server_runner = await run_server(store, settings.ingest_token, settings.port)
        logger.info("Bot started. Authorized users: %d", len(settings.allowed_user_ids))

    async def post_shutdown(app: Application) -> None:  # type: ignore[type-arg]
        if server_runner is not None:
            await server_runner.cleanup()
        await store.close()

    application.post_init = post_init
    application.post_shutdown = post_shutdown

    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
