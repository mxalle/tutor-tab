"""Building signed Telegram `initData` strings for tests.

The real thing is produced by Telegram and signed with the bot token; here we
sign it ourselves with the same algorithm and a fake token, which the `settings`
fixture in `conftest.py` installs for the duration of every test.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

# Never a real token: the format is `<bot id>:<secret>`, the value is arbitrary.
TEST_BOT_TOKEN = "424242:TEST-TOKEN"


def sign(fields: dict[str, str], token: str = TEST_BOT_TOKEN) -> str:
    """Render `fields` as an initData string with a valid Telegram `hash`."""
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data_check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    signature = hmac.new(
        secret, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode({**fields, "hash": signature})


def make_init_data(
    tg_id: int,
    name: str = "Anna",
    auth_date: datetime | None = None,
    token: str = TEST_BOT_TOKEN,
    **extra: str,
) -> str:
    """Signed initData for a Telegram user, as the Mini App would send it."""
    moment = auth_date or datetime.now(timezone.utc)
    first, _, last = name.partition(" ")
    user = {"id": tg_id, "first_name": first}
    if last:
        user["last_name"] = last
    return sign(
        {
            "auth_date": str(int(moment.timestamp())),
            "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
            "user": json.dumps(user, ensure_ascii=False),
            **extra,
        },
        token=token,
    )


def auth(tutor) -> dict[str, str]:
    """`Authorization` header impersonating a tutor row (or any Telegram id)."""
    tg_id = getattr(tutor, "tg_id", tutor)
    name = getattr(tutor, "name", "Anna")
    return {"Authorization": f"tma {make_init_data(tg_id, name)}"}
