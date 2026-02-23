"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Immutable application settings."""

    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    webhook_url: str = field(default_factory=lambda: os.getenv("WEBHOOK_URL", ""))
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", ""))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/finance.db"))
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    log_dir: str = field(default_factory=lambda: os.getenv("LOG_DIR", "logs"))

    def validate(self) -> list[str]:
        """Return a list of missing required settings."""
        errors: list[str] = []
        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is required")
        return errors

    def ensure_data_dir(self) -> None:
        """Create the parent directory for the database file if needed."""
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Factory that returns a validated Settings instance."""
    return Settings()
