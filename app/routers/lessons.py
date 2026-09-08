from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tutor
from app.config import settings
from app.database import get_session
from app.models import Lesson, LessonStatus, Student, Tutor
from app.schemas import (
    LessonCreate,
    LessonGenerate,
    LessonOut,
    LessonsGeneratedOut,
    LessonStatusUpdate,
    LessonUpdate,
)
from app.services.schedule import generate_lessons

router = APIRouter(prefix="/lessons", tags=["lessons"])


def _utc(moment: datetime) -> datetime:
    """A filter bound as UTC: naive means UTC, aware is converted."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


async def _get_owned_student(
    session: AsyncSession, student_id: int, tutor_id: int
) -> Student:
    student = await session.get(Student, student_id)
    if student is None or student.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


async def _get_owned_lesson(
    session: AsyncSession, lesson_id: int, tutor_id: int
) -> Lesson:
    result = await session.execute(
        select(Lesson)
        .join(Student, Student.id == Lesson.student_id)
        .where(Lesson.id == lesson_id, Student.tutor_id == tutor_id)
    )
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson


@router.post("", response_model=LessonOut, status_code=http_status.HTTP_201_CREATED)
async def create_lesson(
    payload: LessonCreate,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    student = await _get_owned_student(session, payload.student_id, tutor.id)

    lesson = Lesson(
        student_id=student.id,
        starts_at=payload.starts_at,
        status=payload.status,
        # Freeze the current price of the student into the lesson.
        price_snapshot=student.price,
    )
    session.add(lesson)
    await session.commit()
    await session.refresh(lesson)
    return lesson


@router.post(
    "/generate",
    response_model=LessonsGeneratedOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def generate_from_schedule(
    payload: LessonGenerate,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> LessonsGeneratedOut:
    """Fill the next `days` days from the students' weekly schedule.

    Lessons that already exist at the same minute are left alone, so calling
    this twice changes nothing the second time.
    """
    if payload.student_id is not None:
        students = [await _get_owned_student(session, payload.student_id, tutor.id)]
    else:
        result = await session.execute(
            select(Student)
            .where(Student.tutor_id == tutor.id, Student.is_active.is_(True))
            .order_by(Student.id)
        )
        students = list(result.scalars().all())

    generated = await generate_lessons(
        session, students, ZoneInfo(settings.bot_timezone), days=payload.days
    )
    return LessonsGeneratedOut(
        created=len(generated.created),
        skipped=generated.skipped,
        lessons=[LessonOut.model_validate(lesson) for lesson in generated.created],
    )


@router.get("", response_model=list[LessonOut])
async def list_lessons(
    tutor: Tutor = Depends(get_current_tutor),
    student_id: int | None = Query(default=None),
    status: LessonStatus | None = Query(default=None),
    starts_from: datetime | None = Query(
        default=None, description="Lessons starting at or after this moment"
    ),
    starts_to: datetime | None = Query(
        default=None, description="Lessons starting strictly before this moment"
    ),
    session: AsyncSession = Depends(get_session),
) -> list[Lesson]:
    stmt = (
        select(Lesson)
        .join(Student, Student.id == Lesson.student_id)
        .where(Student.tutor_id == tutor.id)
    )
    if student_id is not None:
        stmt = stmt.where(Lesson.student_id == student_id)
    if status is not None:
        stmt = stmt.where(Lesson.status == status)
    # The Mini App sends the bounds of the viewer's local day, so they arrive
    # with the phone's offset and are moved to UTC before being compared.
    if starts_from is not None:
        stmt = stmt.where(Lesson.starts_at >= _utc(starts_from))
    if starts_to is not None:
        stmt = stmt.where(Lesson.starts_at < _utc(starts_to))
    result = await session.execute(stmt.order_by(Lesson.starts_at, Lesson.id))
    return list(result.scalars().all())


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: int,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    return await _get_owned_lesson(session, lesson_id, tutor.id)


@router.patch("/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: int,
    payload: LessonUpdate,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    lesson = await _get_owned_lesson(session, lesson_id, tutor.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lesson, field, value)
    await session.commit()
    await session.refresh(lesson)
    return lesson


@router.patch("/{lesson_id}/status", response_model=LessonOut)
async def update_lesson_status(
    lesson_id: int,
    payload: LessonStatusUpdate,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    lesson = await _get_owned_lesson(session, lesson_id, tutor.id)
    lesson.status = payload.status
    await session.commit()
    await session.refresh(lesson)
    return lesson


@router.delete("/{lesson_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: int,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> None:
    lesson = await _get_owned_lesson(session, lesson_id, tutor.id)
    await session.delete(lesson)
    await session.commit()
