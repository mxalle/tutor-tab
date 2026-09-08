"""Turning a weekly schedule into actual lessons.

A student's `schedule_slots` say "Tuesdays at 17:00" in local wall-clock time;
lessons are stored as absolute UTC moments. `generate_lessons` walks the next
`days` local days, converts every matching slot into a moment and creates the
lessons that are not there yet.

Running it twice is safe: a lesson is only created when the student has none
starting at exactly that moment, whatever its status.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lesson, LessonStatus, ScheduleSlot, Student

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 14


class Generated(NamedTuple):
    created: list[Lesson]
    # slots that already had a lesson — reported so the UI can say "nothing new"
    skipped: int


def _aware(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC (Postgres returns aware, SQLite naive)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def slot_moments(
    slots: list[ScheduleSlot], tz: ZoneInfo, first_day: date, days: int
) -> list[datetime]:
    """Every UTC moment `slots` produce over `days` local days from `first_day`."""
    moments = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        for slot in slots:
            if not slot.is_active or slot.weekday != day.weekday():
                continue
            local = datetime.combine(day, slot.time, tzinfo=tz)
            moments.append(local.astimezone(timezone.utc))
    return sorted(moments)


async def generate_lessons(
    session: AsyncSession,
    students: list[Student],
    tz: ZoneInfo,
    days: int = DEFAULT_DAYS,
    today: date | None = None,
) -> Generated:
    """Create the missing lessons of `students` for the next `days` days."""
    first_day = today or datetime.now(tz).date()
    window_start = datetime.combine(first_day, datetime.min.time(), tzinfo=tz)
    window_end = window_start + timedelta(days=days)
    start_utc = window_start.astimezone(timezone.utc)
    end_utc = window_end.astimezone(timezone.utc)

    ids = [student.id for student in students]
    if not ids:
        return Generated([], 0)

    existing = {
        (student_id, _aware(starts_at))
        for student_id, starts_at in (
            await session.execute(
                select(Lesson.student_id, Lesson.starts_at).where(
                    Lesson.student_id.in_(ids),
                    Lesson.starts_at >= start_utc,
                    Lesson.starts_at < end_utc,
                )
            )
        ).all()
    }

    created: list[Lesson] = []
    skipped = 0
    for student in students:
        for moment in slot_moments(student.schedule, tz, first_day, days):
            if (student.id, moment) in existing:
                skipped += 1
                continue
            lesson = Lesson(
                student_id=student.id,
                starts_at=moment,
                status=LessonStatus.planned,
                # Same rule as a hand-made lesson: freeze today's price.
                price_snapshot=student.price,
            )
            session.add(lesson)
            created.append(lesson)
            # Two slots at the same minute would otherwise create twins.
            existing.add((student.id, moment))

    if created:
        await session.commit()
        for lesson in created:
            await session.refresh(lesson)
    logger.info("generated %s lessons, %s already there", len(created), skipped)
    return Generated(created, skipped)
