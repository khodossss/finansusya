"""Entry-point for running the bot."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import asyncio
from pathlib import Path

import uvicorn

from app.config import get_settings
from app.server import create_fastapi_app


def _setup_logging(log_dir: str) -> None:
    """Configure root logger with console + rotating file handlers."""
    log_fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    formatter = logging.Formatter(log_fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    # Rotating file handler (10 MB, keep 5 backups)
    log_path = Path(log_dir) / "bot.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    _setup_logging(settings.log_dir)
    errors = settings.validate()
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    settings.ensure_data_dir()
    app = create_fastapi_app(settings)

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
