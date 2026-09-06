"""Callback data schemas for inline keyboards."""

from aiogram.filters.callback_data import CallbackData


class LessonStatusCb(CallbackData, prefix="lesson"):
    """"Провёл" / "Отменил" under a lesson in /today."""

    lesson_id: int
    status: str


class InviteCb(CallbackData, prefix="invite"):
    """A student picked from the /invite list."""

    student_id: int
