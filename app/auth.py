"""Telegram Mini App authentication.

Every request from the Mini App carries the raw `initData` string Telegram
handed to the page:

    Authorization: tma <initData>

`initData` is a urlencoded query string signed by Telegram with a key derived
from the bot token, so a valid signature proves the caller really is the
Telegram user described inside it. That is why no endpoint takes a `tutor_id`
any more: the tutor is resolved from the signature, not from the client.

The algorithm is Telegram's own (https://core.telegram.org/bots/webapps):

    secret_key       = HMAC_SHA256(key="WebAppData", msg=<bot token>)
    data_check_string = "\\n".join(sorted("<key>=<value>" for every field but `hash`))
    hash             = HMAC_SHA256(key=secret_key, msg=data_check_string).hexdigest()

On top of that we refuse anything older than `MAX_AGE`, so a leaked `initData`
string stops working within a day.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import Tutor
from app.services.tutors import FALLBACK_NAME, get_or_create_tutor

logger = logging.getLogger(__name__)

# `Authorization: tma <initData>`, the scheme Telegram suggests for Mini Apps.
SCHEME = "tma"
MAX_AGE = timedelta(hours=24)


class InitDataError(ValueError):
    """initData is malformed, wrongly signed or too old."""


class InitData(NamedTuple):
    """The part of a verified initData the application actually uses."""

    tg_id: int
    name: str
    auth_date: datetime
    user: dict


def _secret_key(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def _expected_hash(fields: dict[str, str], bot_token: str) -> str:
    """Telegram's hash over every field except `hash` itself, sorted by key."""
    data_check_string = "\n".join(
        f"{key}={fields[key]}" for key in sorted(fields) if key != "hash"
    )
    return hmac.new(
        _secret_key(bot_token), data_check_string.encode(), hashlib.sha256
    ).hexdigest()


def _display_name(user: dict) -> str:
    """Best available name from the `user` object inside initData."""
    full = " ".join(
        part for part in (user.get("first_name"), user.get("last_name")) if part
    ).strip()
    return full or user.get("username") or FALLBACK_NAME


def parse_init_data(
    raw: str,
    bot_token: str,
    now: datetime | None = None,
    max_age: timedelta = MAX_AGE,
) -> InitData:
    """Verify an initData string and pull the Telegram user out of it.

    Raises `InitDataError` on anything suspicious: a missing or wrong `hash`,
    a missing or unparsable `user`, an `auth_date` that is absent, not a
    number, or older than `max_age`.
    """
    if not bot_token:
        raise InitDataError("bot token is not configured")

    # keep_blank_values: an empty field still takes part in the signature.
    fields = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=False))
    if not fields:
        raise InitDataError("initData is empty")

    received_hash = fields.get("hash")
    if not received_hash:
        raise InitDataError("initData has no hash")

    # compare_digest: constant time, so the hash cannot be guessed byte by byte.
    if not hmac.compare_digest(_expected_hash(fields, bot_token), received_hash):
        raise InitDataError("initData signature does not match")

    try:
        auth_date = datetime.fromtimestamp(int(fields["auth_date"]), tz=timezone.utc)
    except (KeyError, ValueError) as exc:
        raise InitDataError("initData has no usable auth_date") from exc

    now = now or datetime.now(timezone.utc)
    if now - auth_date > max_age:
        raise InitDataError("initData is expired")

    try:
        user = json.loads(fields["user"])
        tg_id = int(user["id"])
    except (KeyError, ValueError, TypeError) as exc:
        raise InitDataError("initData has no usable user") from exc

    return InitData(
        tg_id=tg_id, name=_display_name(user), auth_date=auth_date, user=user
    )


def _unauthorized(reason: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=reason,
        headers={"WWW-Authenticate": SCHEME},
    )


async def _debug_tutor(session: AsyncSession, tutor_id: int) -> Tutor:
    """`X-Debug-Tutor-Id` escape hatch — only ever reachable with DEBUG=true."""
    tutor = await session.get(Tutor, tutor_id)
    if tutor is None:
        raise _unauthorized(f"No tutor with id={tutor_id}")
    logger.warning("authenticated tutor_id=%s via X-Debug-Tutor-Id", tutor.id)
    return tutor


async def get_current_tutor(
    authorization: str | None = Header(default=None),
    x_debug_tutor_id: int | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Tutor:
    """The tutor behind the request, registered on first sight.

    A tutor who opens the Mini App without ever having run `/start` in the bot
    is created here — the signature already proves who they are, and refusing
    would be a dead end with no way out of it.
    """
    if x_debug_tutor_id is not None and settings.debug:
        return await _debug_tutor(session, x_debug_tutor_id)

    if not authorization:
        raise _unauthorized("Authorization header is missing")

    scheme, _, raw = authorization.partition(" ")
    if scheme.lower() != SCHEME or not raw:
        raise _unauthorized(f"Expected an `Authorization: {SCHEME} <initData>` header")

    try:
        init_data = parse_init_data(raw, settings.telegram_bot_token)
    except InitDataError as exc:
        logger.info("rejected initData: %s", exc)
        raise _unauthorized(str(exc)) from exc

    tutor, created = await get_or_create_tutor(
        session, tg_id=init_data.tg_id, name=init_data.name
    )
    if created:
        logger.info("registered tutor id=%s from the mini app", tutor.id)
    return tutor


__all__ = [
    "InitData",
    "InitDataError",
    "MAX_AGE",
    "SCHEME",
    "get_current_tutor",
    "parse_init_data",
]
