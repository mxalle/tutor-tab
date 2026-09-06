"""/start — the fork between the two roles.

`/start` alone registers (or greets) a tutor. `/start parent_<token>` redeems a
parent invite. The same Telegram user may legitimately be both.
"""

import html
import logging

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.balance import get_balance
from app.services.invites import RedeemError, redeem_invite
from bot.formatting import format_balance
from bot.tutors import display_name, get_or_create_tutor

logger = logging.getLogger(__name__)

router = Router(name="start")

PARENT_PREFIX = "parent_"

TUTOR_GREETING = (
    "👋 Привет, {name}!\n\n"
    "Это TutorTab — помощник для учёта частных занятий. "
    "Я веду список учеников и считаю, кто сколько должен, "
    "показываю занятия на сегодня и отмечаю их проведёнными в один тап.\n"
    "Ещё я умею выдавать родителям ссылку, по которой они сами видят баланс.\n\n"
    "{commands}"
)

TUTOR_COMMANDS = (
    "<b>Команды:</b>\n"
    "/students — ученики и баланс\n"
    "/today — занятия на сегодня\n"
    "/invite — ссылка для родителя"
)

REDEEM_ERRORS = {
    RedeemError.not_found: (
        "Не нашёл такое приглашение. Возможно, в ссылке опечатка — "
        "попросите репетитора прислать её ещё раз."
    ),
    RedeemError.used: (
        "Эта ссылка уже использована. Если вы подключались с другого аккаунта, "
        "попросите у репетитора новую."
    ),
    RedeemError.expired: (
        "Срок действия ссылки истёк — она живёт 7 дней. "
        "Попросите у репетитора новую."
    ),
}


@router.message(CommandStart(deep_link=True))
async def start_with_payload(
    message: Message, command: CommandObject, session: AsyncSession
) -> None:
    """`/start parent_<token>` — attach this chat to a student."""
    payload = (command.args or "").strip()
    if not payload.startswith(PARENT_PREFIX):
        logger.info("unknown start payload from chat_id=%s", message.chat.id)
        await message.answer(
            "Не понял эту ссылку. Отправьте /start, чтобы начать заново."
        )
        return

    token = payload[len(PARENT_PREFIX) :]
    result = await redeem_invite(session, token, parent_chat_id=message.chat.id)

    if not result.ok:
        logger.info(
            "invite rejected chat_id=%s reason=%s", message.chat.id, result.error.value
        )
        await message.answer(REDEEM_ERRORS[result.error])
        return

    student = result.student
    balance = await get_balance(session, student.id)
    logger.info(
        "invite redeemed student_id=%s chat_id=%s", student.id, message.chat.id
    )
    await message.answer(
        f"Готово! Вы подключены к ученику <b>{html.escape(student.name)}</b>.\n\n"
        f"Текущий баланс: <b>{format_balance(balance.balance)}</b>\n\n"
        "Команда /balance покажет баланс и число занятий за текущий месяц."
    )


@router.message(CommandStart(deep_link=False))
async def start_plain(message: Message, session: AsyncSession) -> None:
    """`/start` — register the sender as a tutor, or greet a returning one."""
    tutor, created = await get_or_create_tutor(
        session, tg_id=message.from_user.id, name=display_name(message.from_user)
    )
    greeting = TUTOR_GREETING.format(
        name=html.escape(tutor.name), commands=TUTOR_COMMANDS
    )
    if not created:
        greeting = f"С возвращением, {html.escape(tutor.name)}!\n\n{TUTOR_COMMANDS}"
    await message.answer(greeting)
