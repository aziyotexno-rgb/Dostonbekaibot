"""Application configuration loaded strictly from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(raw_url: str) -> str:
    """Normalize Render/Heroku postgres:// URLs into async SQLAlchemy drivers."""
    url = raw_url.strip()
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram Bot API
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    allowed_telegram_id: int = Field(default=0, alias="ALLOWED_TELEGRAM_ID")

    # Gemini AI
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_MODEL")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./dostonbek_local.db",
        alias="DATABASE_URL",
    )

    # MTProto Userbot VoIP (@Yordamchiaidosa -> @D_admin_aka)
    telegram_api_id: int = Field(default=0, alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(default="", alias="TELEGRAM_API_HASH")
    telegram_session_string: str = Field(default="", alias="TELEGRAM_SESSION_STRING")
    caller_username: str = Field(default="@Yordamchiaidosa", alias="CALLER_USERNAME")
    callee_username: str = Field(default="@D_admin_aka", alias="CALLEE_USERNAME")

    # Defaults & Localization
    default_timezone: str = Field(default="Asia/Tashkent", alias="DEFAULT_TIMEZONE")
    default_voice_name: str = Field(
        default="uz-UZ-SardorNeural", alias="DEFAULT_VOICE_NAME"
    )
    default_voice_rate: str = Field(default="+0%", alias="DEFAULT_VOICE_RATE")
    audio_output_dir: Path = Field(
        default=Path("/tmp/dostonbek_audio"), alias="AUDIO_OUTPUT_DIR"
    )

    # Render Web Service & Webhook / Polling Mode
    enable_health_server: bool = Field(default=True, alias="ENABLE_HEALTH_SERVER")
    use_webhook: bool = Field(default=False, alias="USE_WEBHOOK")
    webhook_base_url: str = Field(default="", alias="WEBHOOK_BASE_URL")
    webhook_secret: str = Field(default="dostonbek-webhook-secret", alias="WEBHOOK_SECRET")
    port: int = Field(default=10000, alias="PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        return normalize_database_url(str(value))

    @field_validator("caller_username", "callee_username", mode="before")
    @classmethod
    def _ensure_at_prefix(cls, value: str) -> str:
        cleaned = str(value).strip()
        if cleaned and not cleaned.startswith("@"):
            return f"@{cleaned}"
        return cleaned

    def get_sensitive_values(self) -> list[str]:
        """Return non-empty secrets so logging filter can mask them."""
        candidates = [
            self.bot_token,
            self.gemini_api_key,
            self.telegram_api_hash,
            self.telegram_session_string,
            self.webhook_secret,
        ]
        if "@" in self.database_url and "://" in self.database_url:
            try:
                creds = self.database_url.split("://", 1)[1].split("@", 1)[0]
                if ":" in creds:
                    candidates.append(creds.split(":", 1)[1])
            except Exception:
                pass
        return [val for val in candidates if val and len(val) >= 6]

    def validate_for_runtime(self) -> None:
        """Fail fast on missing critical bot secrets at startup."""
        missing = []
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.allowed_telegram_id:
            missing.append("ALLOWED_TELEGRAM_ID")
        if missing:
            raise RuntimeError(
                f"Majburiy muhit o'zgaruvchilari topilmadi: {', '.join(missing)}"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.audio_output_dir.mkdir(parents=True, exist_ok=True)
    return settings
