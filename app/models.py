import enum
from datetime import datetime
from datetime import time as time_of_day
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class LessonStatus(str, enum.Enum):
    planned = "planned"
    done = "done"
    cancelled = "cancelled"
    moved = "moved"


lesson_status_enum = Enum(
    LessonStatus,
    name="lesson_status",
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class Tutor(Base):
    __tablename__ = "tutors"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    students: Mapped[list["Student"]] = relationship(
        back_populates="tutor", cascade="all, delete-orphan"
    )


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    tutor_id: Mapped[int] = mapped_column(
        ForeignKey("tutors.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Telegram chat of the student's parent, used for reminders later.
    parent_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tutor: Mapped["Tutor"] = relationship(back_populates="students")
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    invites: Mapped[list["ParentInvite"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    # Always loaded: a student is never shown without their schedule, and lazy
    # loading would blow up under async.
    schedule: Mapped[list["ScheduleSlot"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ScheduleSlot.weekday, ScheduleSlot.time, ScheduleSlot.id",
    )


class ScheduleSlot(Base):
    """One recurring weekly slot of a student: "Tuesdays at 17:00".

    `weekday` follows `date.weekday()` — 0 is Monday, 6 is Sunday. `time` is
    local wall-clock time in `settings.bot_timezone`; lessons generated from a
    slot are converted to UTC, so a slot survives a DST change unmoved.
    """

    __tablename__ = "schedule_slots"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_schedule_slots_weekday"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    weekday: Mapped[int] = mapped_column()
    time: Mapped[time_of_day] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    student: Mapped["Student"] = relationship(back_populates="schedule")


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[LessonStatus] = mapped_column(
        lesson_status_enum, default=LessonStatus.planned, server_default="planned"
    )
    # Copy of the student's price at the moment the lesson was created.
    price_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    student: Mapped["Student"] = relationship(back_populates="lessons")


class ParentInvite(Base):
    """One-shot link that binds a parent's Telegram chat to a student.

    The tutor generates an invite in the bot, sends the deep link to the parent;
    opening it writes the parent's chat id into `students.parent_chat_id` and
    stamps `used_at`. Invites expire, see `app/services/invites.py`.
    """

    __tablename__ = "parent_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    student: Mapped["Student"] = relationship(back_populates="invites")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    student: Mapped["Student"] = relationship(back_populates="payments")
