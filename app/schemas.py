from datetime import datetime
from datetime import time as time_of_day
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import LessonStatus

Money = Field(max_digits=10, decimal_places=2)


# --- schedule ---------------------------------------------------------------


class ScheduleSlotIn(BaseModel):
    """A recurring weekly slot: weekday 0-6 (Monday first) and a local time."""

    weekday: int = Field(ge=0, le=6)
    time: time_of_day
    is_active: bool = True


class ScheduleSlotOut(ScheduleSlotIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int


# --- students ---------------------------------------------------------------


class StudentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    parent_chat_id: int | None = None
    is_active: bool = True
    schedule: list[ScheduleSlotIn] = Field(default_factory=list)


class StudentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    parent_chat_id: int | None = None
    is_active: bool | None = None
    # When present, replaces the whole schedule; omit it to leave it alone.
    schedule: list[ScheduleSlotIn] | None = None


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tutor_id: int
    name: str
    price: Decimal
    parent_chat_id: int | None
    is_active: bool
    created_at: datetime
    schedule: list[ScheduleSlotOut] = Field(default_factory=list)


# --- lessons ----------------------------------------------------------------


class LessonCreate(BaseModel):
    student_id: int
    starts_at: datetime
    status: LessonStatus = LessonStatus.planned


class LessonUpdate(BaseModel):
    # price_snapshot is intentionally not updatable: it is history.
    starts_at: datetime | None = None
    status: LessonStatus | None = None


class LessonStatusUpdate(BaseModel):
    status: LessonStatus


class LessonGenerate(BaseModel):
    """Fill the calendar from the weekly schedule, `days` ahead of today."""

    days: int = Field(default=14, ge=1, le=90)
    # None means every active student of the tutor.
    student_id: int | None = None


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    starts_at: datetime
    status: LessonStatus
    price_snapshot: Decimal
    created_at: datetime


class LessonsGeneratedOut(BaseModel):
    created: int
    skipped: int
    lessons: list[LessonOut]


# --- payments ---------------------------------------------------------------


class PaymentCreate(BaseModel):
    student_id: int
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    # defaults to "now" on the server when omitted
    paid_at: datetime | None = None
    comment: str | None = None


class PaymentUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    paid_at: datetime | None = None
    comment: str | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    student_id: int
    amount: Decimal
    paid_at: datetime
    comment: str | None
    created_at: datetime


# --- balance / summary ------------------------------------------------------


class BalanceOut(BaseModel):
    """A positive balance means the student owes money."""

    model_config = ConfigDict(from_attributes=True)

    student_id: int
    lessons_total: Decimal
    payments_total: Decimal
    balance: Decimal


class StudentBalanceOut(BaseModel):
    student_id: int
    name: str
    is_active: bool
    lessons_total: Decimal
    payments_total: Decimal
    balance: Decimal


class TutorSummaryOut(BaseModel):
    tutor_id: int
    students: list[StudentBalanceOut]
    # sum of positive balances, i.e. how much all students owe in total
    total_debt: Decimal
    month_start: datetime
    month_income: Decimal
