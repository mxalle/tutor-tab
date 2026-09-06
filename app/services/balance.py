"""Balance calculation.

A balance is never stored in the database, it is always derived from the
lessons and payments of a student:

    balance = sum(price_snapshot of lessons with status=done) - sum(payments.amount)

With this formula a **positive** balance means the student owes the tutor money
(a debt) and a negative balance means the student has paid in advance.
See NOTES.md for why this sign convention was picked.
"""

from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonStatus, Payment, Student

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


class Balance(NamedTuple):
    student_id: int
    lessons_total: Decimal
    payments_total: Decimal
    balance: Decimal


def _money(value: object) -> Decimal:
    """Normalize a SQL SUM: None on empty sets, float on SQLite, Decimal on Postgres."""
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(CENTS)


def _build(student_id: int, lessons_total: object, payments_total: object) -> Balance:
    lessons = _money(lessons_total)
    payments = _money(payments_total)
    return Balance(
        student_id=student_id,
        lessons_total=lessons,
        payments_total=payments,
        balance=lessons - payments,
    )


def month_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    """Half-open [start, end) bounds of the calendar month containing `moment`."""
    moment = moment or datetime.now(timezone.utc)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def get_balance(session: AsyncSession, student_id: int) -> Balance:
    """Balance of a single student."""
    lessons_sum = (
        select(func.coalesce(func.sum(Lesson.price_snapshot), 0))
        .where(Lesson.student_id == student_id, Lesson.status == LessonStatus.done)
        .scalar_subquery()
    )
    payments_sum = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.student_id == student_id)
        .scalar_subquery()
    )
    lessons_total, payments_total = (
        await session.execute(select(lessons_sum, payments_sum))
    ).one()
    return _build(student_id, lessons_total, payments_total)


async def get_balances(
    session: AsyncSession, student_ids: Iterable[int]
) -> dict[int, Balance]:
    """Balances for many students at once, keyed by student id.

    Every requested id is present in the result; students without lessons or
    payments simply get a zero balance.
    """
    ids = list(student_ids)
    if not ids:
        return {}

    lessons = dict(
        (
            await session.execute(
                select(Lesson.student_id, func.sum(Lesson.price_snapshot))
                .where(
                    Lesson.student_id.in_(ids), Lesson.status == LessonStatus.done
                )
                .group_by(Lesson.student_id)
            )
        ).all()
    )
    payments = dict(
        (
            await session.execute(
                select(Payment.student_id, func.sum(Payment.amount))
                .where(Payment.student_id.in_(ids))
                .group_by(Payment.student_id)
            )
        ).all()
    )
    return {
        sid: _build(sid, lessons.get(sid), payments.get(sid)) for sid in ids
    }


async def get_month_income(
    session: AsyncSession, tutor_id: int, moment: datetime | None = None
) -> Decimal:
    """Money actually received by a tutor during the calendar month of `moment`.

    Income is counted from payments (`paid_at`), not from lessons held.
    """
    start, end = month_bounds(moment)
    total = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Student, Student.id == Payment.student_id)
        .where(
            Student.tutor_id == tutor_id,
            Payment.paid_at >= start,
            Payment.paid_at < end,
        )
    )
    return _money(total)
