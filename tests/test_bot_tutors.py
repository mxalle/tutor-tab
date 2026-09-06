"""Resolving a Telegram user to a tutor row (the /start entry point)."""

from types import SimpleNamespace

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tutor
from bot.tutors import FALLBACK_NAME, display_name, get_or_create_tutor, get_tutor


async def test_start_registers_an_unknown_tutor(session: AsyncSession) -> None:
    tutor, created = await get_or_create_tutor(session, tg_id=777, name="Анна")

    assert created
    assert tutor.id is not None
    assert tutor.tg_id == 777
    assert tutor.name == "Анна"


async def test_start_is_idempotent(session: AsyncSession, tutor: Tutor) -> None:
    again, created = await get_or_create_tutor(
        session, tg_id=tutor.tg_id, name="Anna"
    )

    assert not created
    assert again.id == tutor.id
    total = await session.scalar(select(func.count()).select_from(Tutor))
    assert total == 1


async def test_a_telegram_rename_does_not_rewrite_the_stored_name(
    session: AsyncSession, tutor: Tutor
) -> None:
    again, _ = await get_or_create_tutor(
        session, tg_id=tutor.tg_id, name="Совсем другое имя"
    )

    assert again.name == tutor.name


async def test_get_tutor_returns_none_for_a_parent_only_user(
    session: AsyncSession,
) -> None:
    """Someone who arrived through an invite has no tutor row."""
    assert await get_tutor(session, 123456) is None


def test_display_name_falls_back_from_full_name_to_username() -> None:
    assert display_name(SimpleNamespace(full_name="Анна П", username="anna")) == "Анна П"
    assert display_name(SimpleNamespace(full_name="", username="anna")) == "anna"
    assert display_name(SimpleNamespace(full_name="", username=None)) == FALLBACK_NAME
