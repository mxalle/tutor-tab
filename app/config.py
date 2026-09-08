from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "TutorTab"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://tutortab:tutortab@localhost:5432/tutortab"
    redis_url: str = "redis://localhost:6379/0"

    # Telegram bot (separate process, see bot/main.py). Empty by default so the
    # API keeps starting without it; the bot itself refuses to start without a token.
    telegram_bot_token: str = ""
    # Timezone the bot speaks in: "today", schedules and dates are rendered in it.
    # Lessons themselves are always stored in UTC.
    bot_timezone: str = "Europe/Moscow"
    # Bot username without the @, used to build parent invite deep links from
    # the API (the bot process learns it from get_me, the API cannot).
    bot_username: str = ""
    # Public https:// address of the Mini App (this app's /app path). Telegram
    # only opens web_app buttons over https, so an empty or plain-http value
    # means the bot simply shows no button.
    miniapp_url: str = ""


settings = Settings()
