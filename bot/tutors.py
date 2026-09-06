"""Resolving a Telegram user to a tutor row."""

import logging

from aiogram.types import User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tutor

logger = logging.getLogger(__name__)

FALLBACK_NAME = "Репетитор"


def display_name(user: User) -> str:
    """Best available name from a Telegram profile."""
    return user.full_name or user.username or FALLBACK_NAME


async def get_tutor(session: AsyncSession, tg_id: int) -> Tutor | None:
    """The tutor behind a Telegram id, or None if this user never ran /start."""
    return (
        await session.execute(select(Tutor).where(Tutor.tg_id == tg_id))
    ).scalar_one_or_none()


async def get_or_create_tutor(
    session: AsyncSession, tg_id: int, name: str
) -> tuple[Tutor, bool]:
    """Find the tutor by Telegram id or register a new one.

    Returns `(tutor, created)`. An existing tutor keeps the name they were
    registered with — a Telegram profile rename must not silently rewrite it.
    """
    tutor = await get_tutor(session, tg_id)
    if tutor is not None:
        return tutor, False

    tutor = Tutor(tg_id=tg_id, name=name)
    session.add(tutor)
    await session.commit()
    await session.refresh(tutor)
    logger.info("registered tutor id=%s tg_id=%s", tutor.id, tg_id)
    return tutor, True
