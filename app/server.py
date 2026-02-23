"""FastAPI application — Telegram webhook + health endpoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from telegram import Update

from app.bot.handlers import create_bot_app
from app.config import Settings, get_settings
from app.db.repository import Repository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan: set up & tear down shared resources
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown logic."""
    settings: Settings = app.state.settings
    repo = Repository(settings.database_path)
    await repo.connect()
    app.state.repo = repo

    # Build the Telegram bot application
    bot_app = create_bot_app(settings, repo)
    await bot_app.initialize()
    await bot_app.start()

    # Register bot commands in Telegram's menu
    from telegram import BotCommand
    await bot_app.bot.set_my_commands([
        BotCommand("start", "Create or join a workspace"),
        BotCommand("help", "Show all available operations"),
        BotCommand("transactions", "List your transactions"),
        BotCommand("summary", "Income / expenses / net summary"),
        BotCommand("question", "Ask an AI question about your finances"),
        BotCommand("change_currency", "Change currency & convert transactions"),
        BotCommand("cancel", "Cancel current setup"),
    ])

    # Set the webhook (if configured)
    if settings.webhook_url:
        webhook_path = f"{settings.webhook_url}/webhook"
        await bot_app.bot.set_webhook(
            url=webhook_path,
            secret_token=settings.webhook_secret or None,
        )
        logger.info("Webhook set to %s", webhook_path)

    app.state.bot_app = bot_app

    yield

    # Shutdown
    # Cancel pending notifications
    notifier = bot_app.bot_data.get("notifier")
    if notifier:
        await notifier.cancel_all()
    await bot_app.stop()
    await bot_app.shutdown()
    await repo.close()


# ---------------------------------------------------------------------------
# FastAPI factory
# ---------------------------------------------------------------------------

def create_fastapi_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI app."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Finance Tracker Bot",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # -- Routes --------------------------------------------------------------

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/webhook")
    async def webhook(request: Request) -> Response:
        """Receive Telegram updates via webhook."""
        # Optional: verify secret token
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if settings.webhook_secret and secret != settings.webhook_secret:
            return Response(status_code=403)

        data = await request.json()
        bot_app = request.app.state.bot_app
        update = Update.de_json(data=data, bot=bot_app.bot)
        await bot_app.process_update(update)
        return Response(status_code=200)

    return app
