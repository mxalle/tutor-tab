from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Student, Tutor
from app.schemas import (
    BalanceOut,
    StudentBalanceOut,
    StudentCreate,
    StudentOut,
    StudentUpdate,
    TutorSummaryOut,
)
from app.services.balance import (
    ZERO,
    get_balance,
    get_balances,
    get_month_income,
    month_bounds,
)

# TODO: drop the `tutor_id` query parameter once auth exists — the tutor must be
# resolved from validated Telegram WebApp initData instead of being client-supplied.
router = APIRouter(tags=["students"])


async def _get_owned_student(
    session: AsyncSession, student_id: int, tutor_id: int
) -> Student:
    student = await session.get(Student, student_id)
    if student is None or student.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


@router.post(
    "/students", response_model=StudentOut, status_code=http_status.HTTP_201_CREATED
)
async def create_student(
    payload: StudentCreate,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Student:
    if await session.get(Tutor, tutor_id) is None:
        raise HTTPException(status_code=404, detail="Tutor not found")

    student = Student(tutor_id=tutor_id, **payload.model_dump())
    session.add(student)
    await session.commit()
    await session.refresh(student)
    return student


@router.get("/students", response_model=list[StudentOut])
async def list_students(
    tutor_id: int = Query(...),
    is_active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[Student]:
    stmt = select(Student).where(Student.tutor_id == tutor_id)
    if is_active is not None:
        stmt = stmt.where(Student.is_active.is_(is_active))
    result = await session.execute(stmt.order_by(Student.id))
    return list(result.scalars().all())


@router.get("/students/{student_id}", response_model=StudentOut)
async def get_student(
    student_id: int,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Student:
    return await _get_owned_student(session, student_id, tutor_id)


@router.patch("/students/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: int,
    payload: StudentUpdate,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Student:
    student = await _get_owned_student(session, student_id, tutor_id)
    # Changing `price` only affects future lessons: existing lessons keep the
    # price_snapshot taken when they were created.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(student, field, value)
    await session.commit()
    await session.refresh(student)
    return student


@router.delete("/students/{student_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: int,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> None:
    # Hard delete, lessons and payments go with it. To keep the history instead,
    # PATCH the student with is_active=false.
    student = await _get_owned_student(session, student_id, tutor_id)
    await session.delete(student)
    await session.commit()


@router.get("/students/{student_id}/balance", response_model=BalanceOut)
async def student_balance(
    student_id: int,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> BalanceOut:
    await _get_owned_student(session, student_id, tutor_id)
    return BalanceOut.model_validate(await get_balance(session, student_id))


@router.get("/tutors/{tutor_id}/summary", response_model=TutorSummaryOut, tags=["tutors"])
async def tutor_summary(
    tutor_id: int,
    session: AsyncSession = Depends(get_session),
) -> TutorSummaryOut:
    if await session.get(Tutor, tutor_id) is None:
        raise HTTPException(status_code=404, detail="Tutor not found")

    result = await session.execute(
        select(Student).where(Student.tutor_id == tutor_id).order_by(Student.id)
    )
    students = list(result.scalars().all())
    balances = await get_balances(session, [s.id for s in students])

    rows = [
        StudentBalanceOut(
            student_id=s.id,
            name=s.name,
            is_active=s.is_active,
            lessons_total=balances[s.id].lessons_total,
            payments_total=balances[s.id].payments_total,
            balance=balances[s.id].balance,
        )
        for s in students
    ]
    total_debt: Decimal = sum((r.balance for r in rows if r.balance > 0), ZERO)
    month_start, _ = month_bounds()

    return TutorSummaryOut(
        tutor_id=tutor_id,
        students=rows,
        total_debt=total_debt,
        month_start=month_start,
        month_income=await get_month_income(session, tutor_id),
    )
