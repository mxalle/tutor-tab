"""The Mini App button under /start."""

from app.config import settings
from bot.handlers.start import MINIAPP_BUTTON, miniapp_keyboard


def test_button_opens_the_configured_url() -> None:
    keyboard = miniapp_keyboard("https://tutortab.example/app")

    (row,) = keyboard.inline_keyboard
    (button,) = row
    assert button.text == MINIAPP_BUTTON
    assert button.web_app.url == "https://tutortab.example/app"


def test_no_button_without_a_url() -> None:
    assert miniapp_keyboard("") is None


def test_no_button_for_plain_http() -> None:
    """Telegram rejects the whole message for a non-https web_app button."""
    assert miniapp_keyboard("http://localhost:8000/app") is None


def test_the_url_comes_from_settings_by_default() -> None:
    settings.miniapp_url = "https://tutortab.example/app"

    keyboard = miniapp_keyboard()

    assert keyboard.inline_keyboard[0][0].web_app.url == "https://tutortab.example/app"


def test_unset_settings_mean_no_button() -> None:
    settings.miniapp_url = ""

    assert miniapp_keyboard() is None
