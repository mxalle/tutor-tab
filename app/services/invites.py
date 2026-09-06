"""Parent invites: one-shot tokens that bind a parent's chat to a student.

The tutor asks the bot for a link, the bot renders it as a deep link
(`https://t.me/<bot>?start=parent_<token>`). When the parent opens it we write
their chat id into `students.parent_chat_id` and burn the invite.

An invite is redeemable while it is both unused and not expired.
"""

import enum
import secrets
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import ParentInvite, Student

INVITE_TTL = timedelta(days=7)
# 32 url-safe chars; `parent_` + token stays well under Telegram's 64-char
# limit for the /start payload, which also allows only [A-Za-z0-9_-].
TOKEN_BYTES = 24


class RedeemError(str, enum.Enum):
    """Why a token could not be redeemed."""

    not_found = "not_found"
    used = "used"
    expired = "expired"


class RedeemResult(NamedTuple):
    student: Student | None
    error: RedeemError | None

    @property
    def ok(self) -> bool:
        return self.student is not None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime) -> datetime:
    """Treat a naive timestamp as UTC.

    Postgres gives back `timestamptz` as aware, SQLite (tests) as naive.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


async def create_invite(
    session: AsyncSession, student_id: int, now: datetime | None = None
) -> ParentInvite:
    """Issue a fresh invite for a student. The caller must own the student."""
    now = now or _now()
    invite = ParentInvite(
        student_id=student_id,
        token=secrets.token_urlsafe(TOKEN_BYTES),
        expires_at=now + INVITE_TTL,
    )
    session.add(invite)
    await session.commit()
    await session.refresh(invite)
    return invite


async def redeem_invite(
    session: AsyncSession, token: str, parent_chat_id: int, now: datetime | None = None
) -> RedeemResult:
    """Bind `parent_chat_id` to the invited student and burn the invite.

    Returns the student on success, otherwise the reason it failed. Nothing is
    written unless the invite is valid.
    """
    now = now or _now()
    invite = (
        await session.execute(
            select(ParentInvite)
            .where(ParentInvite.token == token)
            .options(selectinload(ParentInvite.student))
        )
    ).scalar_one_or_none()

    if invite is None:
        return RedeemResult(None, RedeemError.not_found)
    if invite.used_at is not None:
        return RedeemResult(None, RedeemError.used)
    if _aware(invite.expires_at) <= now:
        return RedeemResult(None, RedeemError.expired)

    invite.used_at = now
    invite.student.parent_chat_id = parent_chat_id
    await session.commit()
    await session.refresh(invite.student)
    return RedeemResult(invite.student, None)


async def students_by_parent_chat(
    session: AsyncSession, parent_chat_id: int
) -> list[Student]:
    """Students this parent chat is attached to (usually one, siblings possible)."""
    result = await session.execute(
        select(Student)
        .where(Student.parent_chat_id == parent_chat_id)
        .order_by(Student.id)
    )
    return list(result.scalars().all())
