from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Payment, Student
from app.schemas import PaymentCreate, PaymentOut, PaymentUpdate

# TODO: drop the `tutor_id` query parameter once auth exists — the tutor must be
# resolved from validated Telegram WebApp initData instead of being client-supplied.
router = APIRouter(prefix="/payments", tags=["payments"])


async def _get_owned_student(
    session: AsyncSession, student_id: int, tutor_id: int
) -> Student:
    student = await session.get(Student, student_id)
    if student is None or student.tutor_id != tutor_id:
        raise HTTPException(status_code=404, detail="Student not found")
    return student


async def _get_owned_payment(
    session: AsyncSession, payment_id: int, tutor_id: int
) -> Payment:
    result = await session.execute(
        select(Payment)
        .join(Student, Student.id == Payment.student_id)
        .where(Payment.id == payment_id, Student.tutor_id == tutor_id)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


@router.post("", response_model=PaymentOut, status_code=http_status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentCreate,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Payment:
    student = await _get_owned_student(session, payload.student_id, tutor_id)

    payment = Payment(
        student_id=student.id,
        amount=payload.amount,
        paid_at=payload.paid_at or datetime.now(timezone.utc),
        comment=payload.comment,
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


@router.get("", response_model=list[PaymentOut])
async def list_payments(
    tutor_id: int = Query(...),
    student_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[Payment]:
    stmt = (
        select(Payment)
        .join(Student, Student.id == Payment.student_id)
        .where(Student.tutor_id == tutor_id)
    )
    if student_id is not None:
        stmt = stmt.where(Payment.student_id == student_id)
    result = await session.execute(stmt.order_by(Payment.paid_at, Payment.id))
    return list(result.scalars().all())


@router.get("/{payment_id}", response_model=PaymentOut)
async def get_payment(
    payment_id: int,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Payment:
    return await _get_owned_payment(session, payment_id, tutor_id)


@router.patch("/{payment_id}", response_model=PaymentOut)
async def update_payment(
    payment_id: int,
    payload: PaymentUpdate,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> Payment:
    payment = await _get_owned_payment(session, payment_id, tutor_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(payment, field, value)
    await session.commit()
    await session.refresh(payment)
    return payment


@router.delete("/{payment_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_payment(
    payment_id: int,
    tutor_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> None:
    payment = await _get_owned_payment(session, payment_id, tutor_id)
    await session.delete(payment)
    await session.commit()
