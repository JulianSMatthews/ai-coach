# app/config.py
import zoneinfo
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # ── Database
    DATABASE_URL: str = "sqlite:///./ai_coach.db"  # Note this is a placeholder the variable is defined in .env

    # OpenAI
    OPENAI_API_KEY: str

    # Twilio
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_FROM: str
    TWILIO_TO: str | None = None  # optional fallback "to"

    # Fast-test scheduling
    TEST_FAST_SCHEDULE: bool = Field(False, env="TEST_FAST_SCHEDULE")
    FAST_MICRO_EVERY_MIN: int = Field(1, env="FAST_MICRO_EVERY_MIN")
    FAST_WEEKLY_EVERY_MIN: int = Field(7, env="FAST_WEEKLY_EVERY_MIN")
    FAST_REVIEW_AFTER_MIN: int = Field(30, env="FAST_REVIEW_AFTER_MIN")

    # Dev reset + seed user
    RESET_DB_ON_STARTUP: bool = Field(False, env="RESET_DB_ON_STARTUP")
    SEED_TEST_USER: bool = Field(False, env="SEED_TEST_USER")
    SEED_USER_NAME: str = Field("Test User", env="SEED_USER_NAME")
    SEED_USER_PHONE: str | None = Field(None, env="SEED_USER_PHONE")
    SEED_USER_TZ: str = Field("Europe/London", env="SEED_USER_TZ")

    # Default app timezone (used only if a user record has no tz)
    TZ_DEFAULT: str = Field("UTC", env="TZ_DEFAULT")

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # ignore unexpected keys instead of erroring
    )

settings = Settings()
DEFAULT_TZ = zoneinfo.ZoneInfo(settings.TZ_DEFAULT)