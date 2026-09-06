"""Lesson status changes and the date ranges the bot asks for."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonStatus, Student, Tutor
from app.services.lessons import (
    count_done_lessons,
    day_bounds,
    lessons_in_range,
    month_bounds,
    set_lesson_status,
)

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)


async def add_lesson(
    session: AsyncSession,
    student: Student,
    starts_at: datetime = NOW,
    status: LessonStatus = LessonStatus.planned,
    price: str = "1500.00",
) -> Lesson:
    lesson = Lesson(
        student_id=student.id,
        starts_at=starts_at,
        status=status,
        price_snapshot=Decimal(price),
    )
    session.add(lesson)
    await session.commit()
    await session.refresh(lesson)
    return lesson


# --- set_lesson_status ------------------------------------------------------


async def test_marking_a_lesson_done(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    lesson = await add_lesson(session, student)

    updated = await set_lesson_status(session, lesson.id, tutor.id, LessonStatus.done)

    assert updated is not None
    assert updated.status is LessonStatus.done
    await session.refresh(lesson)
    assert lesson.status is LessonStatus.done


async def test_marking_a_lesson_cancelled(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    lesson = await add_lesson(session, student)

    updated = await set_lesson_status(
        session, lesson.id, tutor.id, LessonStatus.cancelled
    )

    assert updated.status is LessonStatus.cancelled


async def test_status_can_be_corrected_back(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    """A mistaken tap must be fixable: done -> cancelled -> done."""
    lesson = await add_lesson(session, student)

    await set_lesson_status(session, lesson.id, tutor.id, LessonStatus.done)
    await set_lesson_status(session, lesson.id, tutor.id, LessonStatus.cancelled)
    final = await set_lesson_status(session, lesson.id, tutor.id, LessonStatus.done)

    assert final.status is LessonStatus.done


async def test_status_change_flows_into_the_balance(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    """Only `done` lessons count, so the status button moves the balance."""
    from app.services.balance import get_balance

    lesson = await add_lesson(session, student, price="1500.00")
    assert (await get_balance(session, student.id)).balance == Decimal("0.00")

    await set_lesson_status(session, lesson.id, tutor.id, LessonStatus.done)
    assert (await get_balance(session, student.id)).balance == Decimal("1500.00")

    await set_lesson_status(session, lesson.id, tutor.id, LessonStatus.cancelled)
    assert (await get_balance(session, student.id)).balance == Decimal("0.00")


async def test_another_tutor_cannot_change_the_status(
    session: AsyncSession, other_tutor: Tutor, student: Student
) -> None:
    lesson = await add_lesson(session, student)

    result = await set_lesson_status(
        session, lesson.id, other_tutor.id, LessonStatus.done
    )

    assert result is None
    await session.refresh(lesson)
    assert lesson.status is LessonStatus.planned


async def test_unknown_lesson_returns_none(
    session: AsyncSession, tutor: Tutor
) -> None:
    assert await set_lesson_status(session, 4242, tutor.id, LessonStatus.done) is None


# --- ranges the bot queries -------------------------------------------------


def test_day_bounds_are_a_local_day_in_utc() -> None:
    start, end = day_bounds(MSK, date(2026, 9, 6))

    # Moscow is UTC+3 year round, so the local day starts at 21:00 UTC before it.
    assert start == datetime(2026, 9, 5, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 6, 21, 0, tzinfo=timezone.utc)


def test_month_bounds_follow_the_local_month_not_the_utc_one() -> None:
    """23:00 UTC on 31 December is already January in Moscow."""
    start, end = month_bounds(MSK, datetime(2026, 12, 31, 23, 0, tzinfo=timezone.utc))

    # January 2027 in Moscow, expressed in UTC.
    assert start == datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 31, 21, 0, tzinfo=timezone.utc)


def test_month_bounds_wrap_the_year() -> None:
    start, end = month_bounds(MSK, datetime(2026, 12, 15, 12, 0, tzinfo=timezone.utc))

    assert start == datetime(2026, 11, 30, 21, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 12, 31, 21, 0, tzinfo=timezone.utc)


async def test_today_lists_only_lessons_of_that_local_day(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    start, end = day_bounds(MSK, date(2026, 9, 6))
    await add_lesson(session, student, starts_at=start - timedelta(minutes=1))
    inside_early = await add_lesson(session, student, starts_at=start)
    inside_late = await add_lesson(session, student, starts_at=end - timedelta(minutes=1))
    await add_lesson(session, student, starts_at=end)

    found = await lessons_in_range(session, tutor.id, start, end)

    assert [lesson.id for lesson, _ in found] == [inside_early.id, inside_late.id]
    assert {s.id for _, s in found} == {student.id}


async def test_today_is_scoped_to_one_tutor(
    session: AsyncSession, tutor: Tutor, other_tutor: Tutor, student: Student
) -> None:
    stranger = Student(
        tutor_id=other_tutor.id, name="Kolya", price=Decimal("1000.00")
    )
    session.add(stranger)
    await session.commit()
    await add_lesson(session, student)
    await add_lesson(session, stranger)

    start, end = day_bounds(MSK, date(2026, 9, 6))
    found = await lessons_in_range(session, tutor.id, start, end)

    assert [s.id for _, s in found] == [student.id]


async def test_count_done_lessons_ignores_other_statuses_and_months(
    session: AsyncSession, student: Student
) -> None:
    start, end = month_bounds(MSK, NOW)
    await add_lesson(session, student, starts_at=NOW, status=LessonStatus.done)
    await add_lesson(session, student, starts_at=NOW, status=LessonStatus.done)
    await add_lesson(session, student, starts_at=NOW, status=LessonStatus.planned)
    await add_lesson(session, student, starts_at=NOW, status=LessonStatus.cancelled)
    await add_lesson(
        session, student, starts_at=start - timedelta(days=1), status=LessonStatus.done
    )

    assert await count_done_lessons(session, student.id, start, end) == 2
