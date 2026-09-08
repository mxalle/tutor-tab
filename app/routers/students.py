from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_tutor
from app.config import settings
from app.database import get_session
from app.models import ScheduleSlot, Student, Tutor
from app.schemas import (
    BalanceOut,
    ParentInviteOut,
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
from app.services.invites import create_invite

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
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> Student:
    student = Student(
        tutor_id=tutor.id,
        **payload.model_dump(exclude={"schedule"}),
        schedule=[ScheduleSlot(**slot.model_dump()) for slot in payload.schedule],
    )
    session.add(student)
    await session.commit()
    await session.refresh(student)
    return student


@router.get("/students", response_model=list[StudentOut])
async def list_students(
    is_active: bool | None = Query(default=None),
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> list[Student]:
    stmt = select(Student).where(Student.tutor_id == tutor.id)
    if is_active is not None:
        stmt = stmt.where(Student.is_active.is_(is_active))
    result = await session.execute(stmt.order_by(Student.id))
    return list(result.scalars().all())


@router.get("/students/{student_id}", response_model=StudentOut)
async def get_student(
    student_id: int,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> Student:
    return await _get_owned_student(session, student_id, tutor.id)


@router.patch("/students/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: int,
    payload: StudentUpdate,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> Student:
    student = await _get_owned_student(session, student_id, tutor.id)
    # Changing `price` only affects future lessons: existing lessons keep the
    # price_snapshot taken when they were created.
    fields = payload.model_dump(exclude_unset=True, exclude={"schedule"})
    for field, value in fields.items():
        setattr(student, field, value)
    if payload.schedule is not None:
        # The schedule is replaced wholesale; lessons already generated from
        # the old slots stay where they are.
        student.schedule = [
            ScheduleSlot(**slot.model_dump()) for slot in payload.schedule
        ]
    await session.commit()
    await session.refresh(student)
    return student


@router.delete("/students/{student_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: int,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> None:
    # Hard delete, lessons and payments go with it. To keep the history instead,
    # PATCH the student with is_active=false.
    student = await _get_owned_student(session, student_id, tutor.id)
    await session.delete(student)
    await session.commit()


@router.get("/students/{student_id}/balance", response_model=BalanceOut)
async def student_balance(
    student_id: int,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> BalanceOut:
    await _get_owned_student(session, student_id, tutor.id)
    return BalanceOut.model_validate(await get_balance(session, student_id))


@router.post(
    "/students/{student_id}/invite",
    response_model=ParentInviteOut,
    status_code=http_status.HTTP_201_CREATED,
)
async def issue_parent_invite(
    student_id: int,
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> ParentInviteOut:
    """A one-shot link a parent opens to see their child's balance.

    The same invite the bot hands out with /invite; the Mini App needs it too,
    and issuing it here keeps both on one implementation.
    """
    student = await _get_owned_student(session, student_id, tutor.id)
    invite = await create_invite(session, student.id)
    link = (
        f"https://t.me/{settings.bot_username}?start=parent_{invite.token}"
        if settings.bot_username
        else None
    )
    return ParentInviteOut(
        student_id=student.id,
        token=invite.token,
        link=link,
        expires_at=invite.expires_at,
    )


@router.get("/tutors/me/summary", response_model=TutorSummaryOut, tags=["tutors"])
async def tutor_summary(
    tutor: Tutor = Depends(get_current_tutor),
    session: AsyncSession = Depends(get_session),
) -> TutorSummaryOut:
    result = await session.execute(
        select(Student).where(Student.tutor_id == tutor.id).order_by(Student.id)
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
        tutor_id=tutor.id,
        students=rows,
        total_debt=total_debt,
        month_start=month_start,
        month_income=await get_month_income(session, tutor.id),
    )
