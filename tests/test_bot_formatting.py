"""Russian rendering: money, balances, dates, plurals."""

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from bot.formatting import (
    MINUS,
    NBSP,
    format_balance,
    format_date,
    format_day_with_weekday,
    format_money,
    format_time,
    lessons_word,
)

MSK = ZoneInfo("Europe/Moscow")


def test_money_uses_a_non_breaking_thousands_separator() -> None:
    assert format_money(Decimal("3000")) == f"3{NBSP}000{NBSP}₽"
    assert format_money(Decimal("1234567")) == f"1{NBSP}234{NBSP}567{NBSP}₽"
    assert format_money(Decimal("500")) == f"500{NBSP}₽"
    assert format_money(Decimal("0")) == f"0{NBSP}₽"


def test_money_rounds_kopecks_half_up() -> None:
    assert format_money(Decimal("1500.49")) == f"1{NBSP}500{NBSP}₽"
    assert format_money(Decimal("1500.50")) == f"1{NBSP}501{NBSP}₽"


def test_negative_money_uses_a_real_minus_sign() -> None:
    assert format_money(Decimal("-3000")) == f"{MINUS}3{NBSP}000{NBSP}₽"


def test_debt_is_shown_as_a_negative_balance() -> None:
    """A service balance of +3000 means "owes 3000"; users see it as −3 000 ₽."""
    assert format_balance(Decimal("3000.00")) == f"{MINUS}3{NBSP}000{NBSP}₽ (долг)"


def test_prepayment_is_shown_as_a_positive_balance() -> None:
    assert format_balance(Decimal("-1500.00")) == f"1{NBSP}500{NBSP}₽ (аванс)"


def test_zero_balance_has_no_label() -> None:
    assert format_balance(Decimal("0.00")) == f"0{NBSP}₽"


def test_dates_are_russian_and_localised() -> None:
    moment = datetime(2026, 9, 6, 11, 30, tzinfo=timezone.utc)

    assert format_date(moment, MSK) == "6 сентября 2026"
    assert format_day_with_weekday(moment, MSK) == "6 сентября, воскресенье"
    assert format_time(moment, MSK) == "14:30"


def test_a_naive_timestamp_is_read_as_utc() -> None:
    """SQLite hands back naive datetimes; they must not be read as system-local."""
    naive = datetime(2026, 9, 6, 11, 30)

    assert format_time(naive, MSK) == "14:30"


def test_late_utc_evening_is_already_tomorrow_in_moscow() -> None:
    moment = datetime(2026, 9, 6, 22, 0, tzinfo=timezone.utc)

    assert format_date(moment, MSK) == "7 сентября 2026"


def test_lesson_plurals() -> None:
    assert [lessons_word(n) for n in (1, 2, 5, 11, 21, 22, 25)] == [
        "занятие",
        "занятия",
        "занятий",
        "занятий",
        "занятие",
        "занятия",
        "занятий",
    ]
