"""Telegram Mini App authentication: signature, freshness, debug escape hatch."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import InitDataError, parse_init_data
from app.config import settings
from app.models import Tutor
from tests.initdata import TEST_BOT_TOKEN, auth, make_init_data, sign

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


# --- parse_init_data --------------------------------------------------------


def test_valid_signature_is_accepted() -> None:
    raw = make_init_data(555, name="Anna Ivanova", auth_date=NOW)

    parsed = parse_init_data(raw, TEST_BOT_TOKEN, now=NOW)

    assert parsed.tg_id == 555
    assert parsed.name == "Anna Ivanova"
    assert parsed.auth_date == NOW


def test_tampered_payload_is_rejected() -> None:
    """Editing a field after signing invalidates the hash."""
    raw = make_init_data(555, auth_date=NOW).replace("555", "556")

    with pytest.raises(InitDataError, match="signature"):
        parse_init_data(raw, TEST_BOT_TOKEN, now=NOW)


def test_corrupted_hash_is_rejected() -> None:
    raw = make_init_data(555, auth_date=NOW)
    head, _, signature = raw.rpartition("=")
    broken = f"{head}={'0' * len(signature)}"

    with pytest.raises(InitDataError, match="signature"):
        parse_init_data(broken, TEST_BOT_TOKEN, now=NOW)


def test_signature_from_another_bot_token_is_rejected() -> None:
    raw = make_init_data(555, auth_date=NOW, token="424242:SOMEONE-ELSE")

    with pytest.raises(InitDataError, match="signature"):
        parse_init_data(raw, TEST_BOT_TOKEN, now=NOW)


def test_extra_field_appended_after_signing_is_rejected() -> None:
    raw = make_init_data(555, auth_date=NOW) + "&chat_instance=-42"

    with pytest.raises(InitDataError, match="signature"):
        parse_init_data(raw, TEST_BOT_TOKEN, now=NOW)


def test_extra_field_included_in_the_signature_is_accepted() -> None:
    """Telegram keeps adding fields; unknown ones just take part in the hash."""
    raw = make_init_data(555, auth_date=NOW, chat_instance="-42", signature="ed25519")

    assert parse_init_data(raw, TEST_BOT_TOKEN, now=NOW).tg_id == 555


def test_stale_auth_date_is_rejected() -> None:
    raw = make_init_data(555, auth_date=NOW - timedelta(hours=24, seconds=1))

    with pytest.raises(InitDataError, match="expired"):
        parse_init_data(raw, TEST_BOT_TOKEN, now=NOW)


def test_auth_date_just_inside_the_window_is_accepted() -> None:
    raw = make_init_data(555, auth_date=NOW - timedelta(hours=23, minutes=59))

    assert parse_init_data(raw, TEST_BOT_TOKEN, now=NOW).tg_id == 555


def test_missing_hash_is_rejected() -> None:
    with pytest.raises(InitDataError, match="hash"):
        parse_init_data("auth_date=1&user=%7B%22id%22%3A1%7D", TEST_BOT_TOKEN, now=NOW)


def test_empty_init_data_is_rejected() -> None:
    with pytest.raises(InitDataError, match="empty"):
        parse_init_data("", TEST_BOT_TOKEN, now=NOW)


def test_signed_but_userless_init_data_is_rejected() -> None:
    """A correct hash is not enough — we need to know who is calling."""
    raw = sign({"auth_date": str(int(NOW.timestamp()))})

    with pytest.raises(InitDataError, match="user"):
        parse_init_data(raw, TEST_BOT_TOKEN, now=NOW)


def test_signed_but_dateless_init_data_is_rejected() -> None:
    raw = sign({"user": '{"id": 555, "first_name": "Anna"}'})

    with pytest.raises(InitDataError, match="auth_date"):
        parse_init_data(raw, TEST_BOT_TOKEN, now=NOW)


def test_username_is_used_when_the_profile_has_no_name() -> None:
    raw = sign(
        {
            "auth_date": str(int(NOW.timestamp())),
            "user": '{"id": 555, "username": "anna"}',
        }
    )

    assert parse_init_data(raw, TEST_BOT_TOKEN, now=NOW).name == "anna"


def test_verification_without_a_bot_token_is_impossible() -> None:
    """Refuse to authenticate rather than to trust unverifiable data."""
    raw = make_init_data(555, auth_date=NOW)

    with pytest.raises(InitDataError, match="bot token"):
        parse_init_data(raw, "", now=NOW)


# --- the dependency, over HTTP ----------------------------------------------


async def test_request_without_authorization_is_401(client: AsyncClient) -> None:
    response = await client.get("/students")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "tma"


async def test_request_with_another_scheme_is_401(client: AsyncClient) -> None:
    raw = make_init_data(555)

    response = await client.get("/students", headers={"Authorization": f"Bearer {raw}"})

    assert response.status_code == 401


async def test_request_with_a_broken_signature_is_401(client: AsyncClient) -> None:
    raw = make_init_data(555, token="424242:SOMEONE-ELSE")

    response = await client.get("/students", headers={"Authorization": f"tma {raw}"})

    assert response.status_code == 401


async def test_request_with_a_stale_auth_date_is_401(client: AsyncClient) -> None:
    raw = make_init_data(555, auth_date=datetime.now(timezone.utc) - timedelta(days=2))

    response = await client.get("/students", headers={"Authorization": f"tma {raw}"})

    assert response.status_code == 401


async def test_the_scheme_is_case_insensitive(client: AsyncClient, tutor: Tutor) -> None:
    raw = make_init_data(tutor.tg_id)

    response = await client.get("/students", headers={"Authorization": f"TMA {raw}"})

    assert response.status_code == 200


async def test_a_tutor_only_sees_their_own_students(
    client: AsyncClient, tutor: Tutor, other_tutor: Tutor, student
) -> None:
    """The tutor comes from the signature, so ids cannot be swapped any more."""
    assert [s["id"] for s in (await client.get("/students", headers=auth(tutor))).json()] == [
        student.id
    ]
    assert (await client.get("/students", headers=auth(other_tutor))).json() == []


async def test_repeated_calls_do_not_duplicate_the_tutor(
    client: AsyncClient, session: AsyncSession
) -> None:
    for _ in range(3):
        assert (
            await client.get(
                "/students", headers={"Authorization": f"tma {make_init_data(4242)}"}
            )
        ).status_code == 200

    count = await session.scalar(
        select(func.count()).select_from(Tutor).where(Tutor.tg_id == 4242)
    )
    assert count == 1


# --- X-Debug-Tutor-Id -------------------------------------------------------


async def test_debug_header_is_ignored_in_production(
    client: AsyncClient, tutor: Tutor
) -> None:
    response = await client.get("/students", headers={"X-Debug-Tutor-Id": str(tutor.id)})

    assert settings.debug is False
    assert response.status_code == 401


async def test_debug_header_works_when_debug_is_on(
    client: AsyncClient, tutor: Tutor, student
) -> None:
    settings.debug = True

    response = await client.get("/students", headers={"X-Debug-Tutor-Id": str(tutor.id)})

    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == [student.id]


async def test_debug_header_with_an_unknown_id_is_401(client: AsyncClient) -> None:
    settings.debug = True

    response = await client.get("/students", headers={"X-Debug-Tutor-Id": "999"})

    assert response.status_code == 401
