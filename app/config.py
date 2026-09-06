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


settings = Settings()
