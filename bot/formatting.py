"""Russian-language rendering helpers: money, dates, pluralisation.

Money is rendered as "3 000 ₽" with a non-breaking space as the thousands
separator, so Telegram never wraps a number across two lines.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

NBSP = " "
MINUS = "−"  # real minus sign, hyphen looks like a list bullet in Telegram

MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

WEEKDAYS = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def format_money(amount: Decimal | int | float) -> str:
    """Render a sum as "3 000 ₽". Fractional kopecks are rounded away."""
    value = Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    sign = MINUS if value < 0 else ""
    digits = f"{abs(value):,}".replace(",", NBSP)
    return f"{sign}{digits}{NBSP}₽"


def format_balance(balance: Decimal) -> str:
    """Render a balance the way people read it: a debt is a negative number.

    `app/services/balance.py` deliberately returns a **positive** number when a
    student owes money (it is an invoice: lessons minus payments). People read a
    balance as a wallet instead, so the sign is flipped here — at the display
    edge only, the API contract and its tests stay untouched. See NOTES.md.
    """
    wallet = -Decimal(str(balance))
    if wallet < 0:
        return f"{format_money(wallet)} (долг)"
    if wallet > 0:
        return f"{format_money(wallet)} (аванс)"
    return format_money(0)


def _local(moment: datetime, tz: ZoneInfo) -> datetime:
    """Move a stored timestamp into `tz`, treating a naive one as UTC.

    Postgres returns `timestamptz` as aware, SQLite (tests) as naive; without
    this, a naive value would be read as system-local time.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz)


def format_date(moment: datetime, tz: ZoneInfo) -> str:
    """"6 сентября 2026" in the given timezone."""
    local = _local(moment, tz)
    return f"{local.day} {MONTHS_GENITIVE[local.month - 1]} {local.year}"


def format_day_with_weekday(moment: datetime, tz: ZoneInfo) -> str:
    """"6 сентября, воскресенье"."""
    local = _local(moment, tz)
    return (
        f"{local.day} {MONTHS_GENITIVE[local.month - 1]}, "
        f"{WEEKDAYS[local.weekday()]}"
    )


def format_time(moment: datetime, tz: ZoneInfo) -> str:
    """"14:30" in the given timezone."""
    return _local(moment, tz).strftime("%H:%M")


def plural(count: int, one: str, few: str, many: str) -> str:
    """Russian plural form: 1 занятие, 2 занятия, 5 занятий."""
    if count % 100 in range(11, 15):
        return many
    last = count % 10
    if last == 1:
        return one
    if last in (2, 3, 4):
        return few
    return many


def lessons_word(count: int) -> str:
    return plural(count, "занятие", "занятия", "занятий")
