from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Lesson, LessonStatus, Student
from app.schemas import LessonCreate, LessonOut, LessonStatusUpdate, LessonUpdate

# TODO: drop the `tutor_id` query parameter once auth exists — the tutor must be
# resolved from validated Telegram WebApp initData instead of being client-supplied.
router = APIRouter(prefix="/lessons", tags=["lessons"])


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
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    student = await _get_owned_student(session, payload.student_id, tutor_id)

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


@router.get("", response_model=list[LessonOut])
async def list_lessons(
    tutor_id: int = Query(...),
    student_id: int | None = Query(default=None),
    status: LessonStatus | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[Lesson]:
    stmt = (
        select(Lesson)
        .join(Student, Student.id == Lesson.student_id)
        .where(Student.tutor_id == tutor_id)
    )
    if student_id is not None:
        stmt = stmt.where(Lesson.student_id == student_id)
    if status is not None:
        stmt = stmt.where(Lesson.status == status)
    result = await session.execute(stmt.order_by(Lesson.starts_at, Lesson.id))
    return list(result.scalars().all())


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: int,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    return await _get_owned_lesson(session, lesson_id, tutor_id)


@router.patch("/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: int,
    payload: LessonUpdate,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    lesson = await _get_owned_lesson(session, lesson_id, tutor_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lesson, field, value)
    await session.commit()
    await session.refresh(lesson)
    return lesson


@router.patch("/{lesson_id}/status", response_model=LessonOut)
async def update_lesson_status(
    lesson_id: int,
    payload: LessonStatusUpdate,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Lesson:
    lesson = await _get_owned_lesson(session, lesson_id, tutor_id)
    lesson.status = payload.status
    await session.commit()
    await session.refresh(lesson)
    return lesson


@router.delete("/{lesson_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: int,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> None:
    lesson = await _get_owned_lesson(session, lesson_id, tutor_id)
    await session.delete(lesson)
    await session.commit()
