"""Lesson queries and status changes used by the bot.

Lessons are stored in UTC. The bot talks to people in a local timezone, so the
range helpers here take a `ZoneInfo`, build the local day/month, and hand back
half-open `[start, end)` bounds in UTC.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonStatus, Student


def day_bounds(tz: ZoneInfo, day: date) -> tuple[datetime, datetime]:
    """UTC bounds of a local calendar day."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def month_bounds(tz: ZoneInfo, moment: datetime) -> tuple[datetime, datetime]:
    """UTC bounds of the local calendar month containing `moment`."""
    local = moment.astimezone(tz)
    start = datetime(local.year, local.month, 1, tzinfo=tz)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def lessons_in_range(
    session: AsyncSession, tutor_id: int, start: datetime, end: datetime
) -> list[tuple[Lesson, Student]]:
    """A tutor's lessons starting within `[start, end)`, earliest first."""
    result = await session.execute(
        select(Lesson, Student)
        .join(Student, Student.id == Lesson.student_id)
        .where(
            Student.tutor_id == tutor_id,
            Lesson.starts_at >= start,
            Lesson.starts_at < end,
        )
        .order_by(Lesson.starts_at, Lesson.id)
    )
    return [(lesson, student) for lesson, student in result.all()]


async def set_lesson_status(
    session: AsyncSession, lesson_id: int, tutor_id: int, status: LessonStatus
) -> Lesson | None:
    """Change a lesson's status, but only if `tutor_id` owns it.

    Returns the updated lesson, or None when it does not exist or belongs to
    someone else — the bot must not let one tutor touch another's schedule.
    """
    lesson = (
        await session.execute(
            select(Lesson)
            .join(Student, Student.id == Lesson.student_id)
            .where(Lesson.id == lesson_id, Student.tutor_id == tutor_id)
        )
    ).scalar_one_or_none()
    if lesson is None:
        return None

    lesson.status = status
    await session.commit()
    await session.refresh(lesson)
    return lesson


async def count_done_lessons(
    session: AsyncSession, student_id: int, start: datetime, end: datetime
) -> int:
    """How many lessons of a student were held within `[start, end)`."""
    total = await session.scalar(
        select(func.count())
        .select_from(Lesson)
        .where(
            Lesson.student_id == student_id,
            Lesson.status == LessonStatus.done,
            Lesson.starts_at >= start,
            Lesson.starts_at < end,
        )
    )
    return int(total or 0)
