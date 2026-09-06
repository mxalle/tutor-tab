"""Bot entrypoint: `python -m bot.main`.

Long polling. Runs as its own process next to the API and shares its database
through `app.database.session_factory` — no HTTP calls between the two.
"""

import asyncio
import logging
import sys
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault

from app.config import settings
from app.database import engine, session_factory
from bot.handlers import build_router
from bot.middlewares import DbSessionMiddleware

logger = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="start", description="Начать работу"),
    BotCommand(command="students", description="Ученики и баланс"),
    BotCommand(command="today", description="Занятия на сегодня"),
    BotCommand(command="invite", description="Ссылка для родителя"),
    BotCommand(command="balance", description="Баланс ребёнка (для родителей)"),
]


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def build_dispatcher() -> Dispatcher:
    """Dispatcher wired to the shared database session factory."""
    dispatcher = Dispatcher()
    dispatcher.update.middleware(DbSessionMiddleware(session_factory))
    dispatcher.include_router(build_router())
    return dispatcher


async def run() -> None:
    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set — put it in .env (see .env.example)."
        )

    tz = ZoneInfo(settings.bot_timezone)
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()

    try:
        me = await bot.get_me()
        # Invite deep links are built from this, so it is resolved once at
        # startup and injected into every handler.
        logger.info("starting as @%s (id=%s), timezone %s", me.username, me.id, tz)

        await bot.set_my_commands(COMMANDS, scope=BotCommandScopeDefault())
        await dispatcher.start_polling(bot, bot_username=me.username, tz=tz)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    setup_logging()
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code:
            logger.error("%s", exc.code)
            sys.exit(1)
        logger.info("bot stopped")


if __name__ == "__main__":
    main()
