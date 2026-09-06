"""Tutor-facing commands: /students, /today, /invite."""

import html
import logging
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonStatus, Student, Tutor
from app.services.balance import ZERO, get_balances
from app.services.invites import INVITE_TTL, create_invite
from app.services.lessons import day_bounds, lessons_in_range, set_lesson_status
from bot.callbacks import InviteCb, LessonStatusCb
from bot.formatting import (
    format_balance,
    format_date,
    format_day_with_weekday,
    format_money,
    format_time,
)
from bot.tutors import get_tutor

logger = logging.getLogger(__name__)

router = Router(name="tutor")

NOT_A_TUTOR = (
    "Эта команда для репетиторов. Отправьте /start, чтобы зарегистрироваться."
)
# Telegram stops exposing message bodies after 48 hours; the button survives in
# the chat but the message behind it can no longer be edited or replied to.
TOO_OLD = "Сообщение слишком старое. Откройте список заново командой /today."

STATUS_LABELS = {
    LessonStatus.planned: "🕓 Запланировано",
    LessonStatus.done: "✅ Проведено",
    LessonStatus.cancelled: "❌ Отменено",
    LessonStatus.moved: "↪️ Перенесено",
}

# Only these two are reachable from the /today buttons.
BUTTON_STATUSES = {
    LessonStatus.done: "Провёл",
    LessonStatus.cancelled: "Отменил",
}


async def _require_tutor(
    session: AsyncSession, tg_id: int, answer
) -> Tutor | None:
    """Resolve the sender to a tutor or explain why the command does not apply."""
    tutor = await get_tutor(session, tg_id)
    if tutor is None:
        await answer(NOT_A_TUTOR)
    return tutor


async def _active_students(session: AsyncSession, tutor_id: int) -> list[Student]:
    result = await session.execute(
        select(Student)
        .where(Student.tutor_id == tutor_id, Student.is_active.is_(True))
        .order_by(Student.name, Student.id)
    )
    return list(result.scalars().all())


@router.message(Command("students"))
async def students_command(message: Message, session: AsyncSession) -> None:
    tutor = await _require_tutor(session, message.from_user.id, message.answer)
    if tutor is None:
        return

    students = await _active_students(session, tutor.id)
    if not students:
        await message.answer("Учеников пока нет.")
        return

    balances = await get_balances(session, [s.id for s in students])
    lines = ["<b>Ваши ученики</b>", ""]
    for student in students:
        balance = balances[student.id].balance
        lines.append(
            f"• {html.escape(student.name)} — {format_balance(balance)}"
        )

    # `balance > 0` means "owes money", see app/services/balance.py.
    total_debt: Decimal = sum(
        (b.balance for b in balances.values() if b.balance > 0), ZERO
    )
    if total_debt > 0:
        lines += ["", f"Суммарный долг: <b>{format_money(total_debt)}</b>"]

    await message.answer("\n".join(lines))


def _lesson_text(lesson: Lesson, student: Student, tz: ZoneInfo) -> str:
    return (
        f"<b>{format_time(lesson.starts_at, tz)}</b> · "
        f"{html.escape(student.name)}\n"
        f"{format_money(lesson.price_snapshot)} · {STATUS_LABELS[lesson.status]}"
    )


def _lesson_keyboard(lesson_id: int) -> InlineKeyboardMarkup:
    """Both actions stay available so a mistaken tap can be corrected."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=LessonStatusCb(
                        lesson_id=lesson_id, status=status.value
                    ).pack(),
                )
                for status, label in BUTTON_STATUSES.items()
            ]
        ]
    )


@router.message(Command("today"))
async def today_command(message: Message, session: AsyncSession, tz: ZoneInfo) -> None:
    tutor = await _require_tutor(session, message.from_user.id, message.answer)
    if tutor is None:
        return

    now = datetime.now(tz)
    start, end = day_bounds(tz, now.date())
    lessons = await lessons_in_range(session, tutor.id, start, end)

    header = f"<b>Занятия на {format_day_with_weekday(now, tz)}</b>"
    if not lessons:
        await message.answer(f"{header}\n\nНа сегодня занятий нет 🎉")
        return

    await message.answer(header)
    for lesson, student in lessons:
        await message.answer(
            _lesson_text(lesson, student, tz),
            reply_markup=_lesson_keyboard(lesson.id),
        )


@router.callback_query(LessonStatusCb.filter())
async def set_status_callback(
    callback: CallbackQuery,
    callback_data: LessonStatusCb,
    session: AsyncSession,
    tz: ZoneInfo,
) -> None:
    """Apply "Провёл" / "Отменил" and redraw the lesson message."""
    tutor = await get_tutor(session, callback.from_user.id)
    if tutor is None:
        await callback.answer(NOT_A_TUTOR, show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer(TOO_OLD, show_alert=True)
        return

    status = LessonStatus(callback_data.status)
    lesson = await set_lesson_status(
        session, callback_data.lesson_id, tutor.id, status
    )
    if lesson is None:
        logger.warning(
            "tutor_id=%s tried to change lesson_id=%s it does not own",
            tutor.id,
            callback_data.lesson_id,
        )
        await callback.answer("Занятие не найдено.", show_alert=True)
        return

    student = await session.get(Student, lesson.student_id)
    logger.info(
        "lesson_id=%s status=%s by tutor_id=%s", lesson.id, status.value, tutor.id
    )

    try:
        await callback.message.edit_text(
            _lesson_text(lesson, student, tz),
            reply_markup=_lesson_keyboard(lesson.id),
        )
    except TelegramBadRequest as exc:
        # Same status tapped twice — the text is identical, nothing to redraw.
        if "message is not modified" not in str(exc):
            raise
    await callback.answer(STATUS_LABELS[status])


@router.message(Command("invite"))
async def invite_command(message: Message, session: AsyncSession) -> None:
    tutor = await _require_tutor(session, message.from_user.id, message.answer)
    if tutor is None:
        return

    students = await _active_students(session, tutor.id)
    if not students:
        await message.answer("Учеников пока нет — приглашать некого.")
        return

    builder = InlineKeyboardBuilder()
    for student in students:
        builder.button(
            text=student.name, callback_data=InviteCb(student_id=student.id)
        )
    builder.adjust(1)

    await message.answer(
        "Кому из учеников выдать ссылку для родителя?",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(InviteCb.filter())
async def invite_callback(
    callback: CallbackQuery,
    callback_data: InviteCb,
    session: AsyncSession,
    tz: ZoneInfo,
    bot_username: str,
) -> None:
    """Issue a one-shot invite for the picked student and show the deep link."""
    tutor = await get_tutor(session, callback.from_user.id)
    if tutor is None:
        await callback.answer(NOT_A_TUTOR, show_alert=True)
        return
    if not isinstance(callback.message, Message):
        await callback.answer(TOO_OLD, show_alert=True)
        return

    student = await session.get(Student, callback_data.student_id)
    if student is None or student.tutor_id != tutor.id:
        logger.warning(
            "tutor_id=%s tried to invite student_id=%s it does not own",
            tutor.id,
            callback_data.student_id,
        )
        await callback.answer("Ученик не найден.", show_alert=True)
        return

    invite = await create_invite(session, student.id)
    link = f"https://t.me/{bot_username}?start=parent_{invite.token}"
    logger.info(
        "invite issued student_id=%s tutor_id=%s expires_at=%s",
        student.id,
        tutor.id,
        invite.expires_at,
    )

    await callback.message.answer(
        f"Ссылка для родителя ученика <b>{html.escape(student.name)}</b>:\n\n"
        f"{link}\n\n"
        f"Одноразовая, действует до {format_date(invite.expires_at, tz)} "
        f"({INVITE_TTL.days} дней). Родитель откроет её и увидит баланс."
    )
    await callback.answer()
