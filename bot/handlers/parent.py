"""Parent-facing command: /balance."""

import html
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.balance import get_balance
from app.services.invites import students_by_parent_chat
from app.services.lessons import count_done_lessons, month_bounds
from bot.formatting import format_balance, lessons_word

logger = logging.getLogger(__name__)

router = Router(name="parent")

NO_LINK = (
    "Не нашёл ученика, привязанного к этому чату.\n\n"
    "Чтобы подключиться, откройте ссылку-приглашение от репетитора. "
    "Если ссылки нет — попросите его прислать её командой /invite."
)


@router.message(Command("balance"))
async def balance_command(
    message: Message, session: AsyncSession, tz: ZoneInfo
) -> None:
    """Balance and lessons held this month, for every student in this chat."""
    students = await students_by_parent_chat(session, message.chat.id)
    if not students:
        logger.info("no student bound to chat_id=%s", message.chat.id)
        await message.answer(NO_LINK)
        return

    start, end = month_bounds(tz, datetime.now(timezone.utc))

    blocks = []
    for student in students:
        balance = await get_balance(session, student.id)
        held = await count_done_lessons(session, student.id, start, end)
        blocks.append(
            f"<b>{html.escape(student.name)}</b>\n"
            f"Баланс: {format_balance(balance.balance)}\n"
            f"В этом месяце: {held} {lessons_word(held)}"
        )

    await message.answer("\n\n".join(blocks))
