"""Telegram profile → tutor row, for the bot side.

The database part lives in `app/services/tutors.py` because the API needs the
same lookup when it resolves a tutor from Mini App `initData`; it is re-exported
here so bot code keeps a single import.
"""

from aiogram.types import User

from app.services.tutors import FALLBACK_NAME, get_or_create_tutor, get_tutor

__all__ = ["FALLBACK_NAME", "display_name", "get_or_create_tutor", "get_tutor"]


def display_name(user: User) -> str:
    """Best available name from a Telegram profile."""
    return user.full_name or user.username or FALLBACK_NAME
