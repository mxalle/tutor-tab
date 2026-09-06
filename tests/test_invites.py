"""Parent invites: issuing a token and redeeming it."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ParentInvite, Student, Tutor
from app.services.invites import (
    INVITE_TTL,
    RedeemError,
    create_invite,
    redeem_invite,
    students_by_parent_chat,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
PARENT_CHAT = 555001


async def test_create_invite_is_unused_and_expires_in_a_week(
    session: AsyncSession, student: Student
) -> None:
    invite = await create_invite(session, student.id, now=NOW)

    assert invite.student_id == student.id
    assert invite.token
    assert invite.used_at is None
    assert invite.expires_at.replace(tzinfo=timezone.utc) == NOW + INVITE_TTL
    assert INVITE_TTL == timedelta(days=7)


async def test_tokens_are_unique_and_url_safe(
    session: AsyncSession, student: Student
) -> None:
    tokens = {(await create_invite(session, student.id)).token for _ in range(10)}

    assert len(tokens) == 10
    for token in tokens:
        # Telegram only accepts A-Z a-z 0-9 _ - in a /start payload, max 64 chars.
        assert all(c.isalnum() or c in "-_" for c in token)
        assert len(f"parent_{token}") <= 64


async def test_redeem_binds_parent_chat_and_burns_the_invite(
    session: AsyncSession, student: Student
) -> None:
    invite = await create_invite(session, student.id, now=NOW)

    result = await redeem_invite(session, invite.token, PARENT_CHAT, now=NOW)

    assert result.ok
    assert result.error is None
    assert result.student.id == student.id
    await session.refresh(student)
    assert student.parent_chat_id == PARENT_CHAT
    await session.refresh(invite)
    assert invite.used_at is not None


async def test_invite_cannot_be_redeemed_twice(
    session: AsyncSession, student: Student
) -> None:
    invite = await create_invite(session, student.id, now=NOW)
    await redeem_invite(session, invite.token, PARENT_CHAT, now=NOW)

    second = await redeem_invite(session, invite.token, 999999, now=NOW)

    assert not second.ok
    assert second.error is RedeemError.used
    await session.refresh(student)
    # The first parent keeps the binding.
    assert student.parent_chat_id == PARENT_CHAT


async def test_expired_invite_is_rejected_and_changes_nothing(
    session: AsyncSession, student: Student
) -> None:
    invite = await create_invite(session, student.id, now=NOW)
    too_late = NOW + INVITE_TTL + timedelta(seconds=1)

    result = await redeem_invite(session, invite.token, PARENT_CHAT, now=too_late)

    assert not result.ok
    assert result.error is RedeemError.expired
    await session.refresh(student)
    assert student.parent_chat_id is None
    await session.refresh(invite)
    assert invite.used_at is None


async def test_invite_is_valid_up_to_the_last_second(
    session: AsyncSession, student: Student
) -> None:
    invite = await create_invite(session, student.id, now=NOW)
    last_moment = NOW + INVITE_TTL - timedelta(seconds=1)

    result = await redeem_invite(session, invite.token, PARENT_CHAT, now=last_moment)

    assert result.ok


async def test_unknown_token_is_rejected(
    session: AsyncSession, student: Student
) -> None:
    result = await redeem_invite(session, "no-such-token", PARENT_CHAT, now=NOW)

    assert not result.ok
    assert result.error is RedeemError.not_found
    await session.refresh(student)
    assert student.parent_chat_id is None


async def test_redeem_moves_binding_to_a_new_parent_chat(
    session: AsyncSession, student: Student
) -> None:
    """A fresh invite re-points the student at whoever opens it."""
    first = await create_invite(session, student.id, now=NOW)
    await redeem_invite(session, first.token, PARENT_CHAT, now=NOW)

    second = await create_invite(session, student.id, now=NOW)
    result = await redeem_invite(session, second.token, 777002, now=NOW)

    assert result.ok
    await session.refresh(student)
    assert student.parent_chat_id == 777002


async def test_students_by_parent_chat_finds_siblings(
    session: AsyncSession, tutor: Tutor, student: Student
) -> None:
    sibling = Student(tutor_id=tutor.id, name="Vasya", price=Decimal("2000.00"))
    session.add(sibling)
    await session.commit()

    for target in (student, sibling):
        invite = await create_invite(session, target.id, now=NOW)
        await redeem_invite(session, invite.token, PARENT_CHAT, now=NOW)

    found = await students_by_parent_chat(session, PARENT_CHAT)

    assert [s.id for s in found] == [student.id, sibling.id]


async def test_students_by_parent_chat_empty_for_unknown_chat(
    session: AsyncSession, student: Student
) -> None:
    assert await students_by_parent_chat(session, 424242) == []


async def test_deleting_a_student_removes_its_invites(
    session: AsyncSession, student: Student
) -> None:
    await create_invite(session, student.id, now=NOW)

    await session.delete(student)
    await session.commit()

    left = (await session.execute(select(ParentInvite))).scalars().all()
    assert left == []
