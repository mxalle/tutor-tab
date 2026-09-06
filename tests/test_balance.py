from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonStatus, Payment, Student, Tutor
from app.services.balance import (
    get_balance,
    get_balances,
    get_month_income,
    month_bounds,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


async def add_lesson(
    session: AsyncSession,
    student: Student,
    status: LessonStatus,
    price: str,
    starts_at: datetime = NOW,
) -> Lesson:
    lesson = Lesson(
        student_id=student.id,
        starts_at=starts_at,
        status=status,
        price_snapshot=Decimal(price),
    )
    session.add(lesson)
    await session.commit()
    return lesson


async def add_payment(
    session: AsyncSession, student: Student, amount: str, paid_at: datetime = NOW
) -> Payment:
    payment = Payment(student_id=student.id, amount=Decimal(amount), paid_at=paid_at)
    session.add(payment)
    await session.commit()
    return payment


async def test_balance_is_zero_without_lessons_and_payments(
    session: AsyncSession, student: Student
) -> None:
    result = await get_balance(session, student.id)

    assert result.lessons_total == Decimal("0.00")
    assert result.payments_total == Decimal("0.00")
    assert result.balance == Decimal("0.00")


async def test_only_done_lessons_count(
    session: AsyncSession, student: Student
) -> None:
    await add_lesson(session, student, LessonStatus.done, "1500.00")
    await add_lesson(session, student, LessonStatus.planned, "1500.00")
    await add_lesson(session, student, LessonStatus.cancelled, "1500.00")
    await add_lesson(session, student, LessonStatus.moved, "1500.00")

    result = await get_balance(session, student.id)

    assert result.lessons_total == Decimal("1500.00")
    assert result.balance == Decimal("1500.00")


async def test_payments_are_subtracted(
    session: AsyncSession, student: Student
) -> None:
    await add_lesson(session, student, LessonStatus.done, "1500.00")
    await add_lesson(session, student, LessonStatus.done, "1500.00")
    await add_payment(session, student, "2000.00")

    result = await get_balance(session, student.id)

    assert result.lessons_total == Decimal("3000.00")
    assert result.payments_total == Decimal("2000.00")
    # positive balance == the student still owes 1000
    assert result.balance == Decimal("1000.00")


async def test_overpayment_gives_negative_balance(
    session: AsyncSession, student: Student
) -> None:
    await add_lesson(session, student, LessonStatus.done, "1500.00")
    await add_payment(session, student, "2000.00")

    result = await get_balance(session, student.id)

    assert result.balance == Decimal("-500.00")


async def test_balance_uses_price_snapshot_not_current_price(
    session: AsyncSession, student: Student
) -> None:
    await add_lesson(session, student, LessonStatus.done, "1500.00")

    student.price = Decimal("2000.00")
    await session.commit()

    result = await get_balance(session, student.id)

    assert result.lessons_total == Decimal("1500.00")


async def test_balance_ignores_other_students(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    other = Student(tutor_id=tutor.id, name="Masha", price=Decimal("1000.00"))
    session.add(other)
    await session.commit()

    await add_lesson(session, student, LessonStatus.done, "1500.00")
    await add_lesson(session, other, LessonStatus.done, "1000.00")
    await add_payment(session, other, "300.00")

    assert (await get_balance(session, student.id)).balance == Decimal("1500.00")
    assert (await get_balance(session, other.id)).balance == Decimal("700.00")


async def test_fractional_amounts_stay_exact(
    session: AsyncSession, student: Student
) -> None:
    await add_lesson(session, student, LessonStatus.done, "1499.99")
    await add_lesson(session, student, LessonStatus.done, "0.02")
    await add_payment(session, student, "0.01")

    result = await get_balance(session, student.id)

    assert result.lessons_total == Decimal("1500.01")
    assert result.balance == Decimal("1500.00")


async def test_get_balances_zero_fills_and_matches_single(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    quiet = Student(tutor_id=tutor.id, name="Kolya", price=Decimal("800.00"))
    session.add(quiet)
    await session.commit()
    await session.refresh(quiet)

    await add_lesson(session, student, LessonStatus.done, "1500.00")
    await add_payment(session, student, "500.00")

    balances = await get_balances(session, [student.id, quiet.id])

    assert set(balances) == {student.id, quiet.id}
    assert balances[student.id].balance == Decimal("1000.00")
    assert balances[quiet.id].balance == Decimal("0.00")
    assert balances[student.id] == await get_balance(session, student.id)


async def test_get_balances_with_no_ids(session: AsyncSession) -> None:
    assert await get_balances(session, []) == {}


async def test_month_income_counts_only_current_month(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    start, _ = month_bounds(NOW)

    await add_payment(session, student, "1000.00", paid_at=NOW)
    await add_payment(session, student, "250.00", paid_at=start)
    await add_payment(session, student, "9999.00", paid_at=start - timedelta(seconds=1))

    assert await get_month_income(session, tutor.id, NOW) == Decimal("1250.00")


async def test_month_income_is_per_tutor(
    session: AsyncSession, tutor: Tutor, other_tutor: Tutor, student: Student
) -> None:
    stranger = Student(
        tutor_id=other_tutor.id, name="Sveta", price=Decimal("1200.00")
    )
    session.add(stranger)
    await session.commit()

    await add_payment(session, student, "1000.00", paid_at=NOW)
    await add_payment(session, stranger, "700.00", paid_at=NOW)

    assert await get_month_income(session, tutor.id, NOW) == Decimal("1000.00")
    assert await get_month_income(session, other_tutor.id, NOW) == Decimal("700.00")


async def test_month_income_is_zero_without_payments(
    session: AsyncSession, tutor: Tutor
) -> None:
    assert await get_month_income(session, tutor.id, NOW) == Decimal("0.00")


def test_month_bounds_rolls_over_the_year() -> None:
    start, end = month_bounds(datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))

    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_month_bounds_within_a_year() -> None:
    start, end = month_bounds(NOW)

    assert start == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 1, tzinfo=timezone.utc)
