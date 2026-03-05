"""FastAPI application — Telegram webhook + health endpoint."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from telegram import Update

from app.bot.handlers import create_bot_app
from app.config import Settings, get_settings
from app.db.repository import Repository

logger = logging.getLogger(__name__)

NGROK_API = os.getenv("NGROK_API_URL", "http://ngrok:4040")
NGROK_POLL_INTERVAL = 30  # seconds


# ---------------------------------------------------------------------------
# Ngrok URL watcher — polls ngrok and re-registers webhook when URL changes
# ---------------------------------------------------------------------------

async def _watch_ngrok(bot_app, settings: Settings) -> None:
    """Periodically poll ngrok for the current tunnel URL.

    If the URL changes (e.g. ngrok restarted), re-register the Telegram
    webhook automatically so the bot stays reachable.
    """
    current_url: str | None = settings.webhook_url or None

    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(NGROK_POLL_INTERVAL)
            try:
                resp = await client.get(f"{NGROK_API}/api/tunnels", timeout=5)
                tunnels = resp.json().get("tunnels", [])
                if not tunnels:
                    logger.warning("ngrok has no active tunnels")
                    continue
                new_url = tunnels[0]["public_url"]
            except Exception:
                logger.warning("Failed to poll ngrok", exc_info=True)
                continue

            if new_url != current_url:
                logger.info("ngrok URL changed: %s → %s", current_url, new_url)
                webhook_path = f"{new_url}/webhook"
                try:
                    await bot_app.bot.set_webhook(
                        url=webhook_path,
                        secret_token=settings.webhook_secret or None,
                    )
                    current_url = new_url
                    logger.info("Webhook re-registered → %s", webhook_path)
                except Exception:
                    logger.error("Failed to re-register webhook", exc_info=True)


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

    # Start background ngrok watcher
    watcher_task = asyncio.create_task(_watch_ngrok(bot_app, settings))

    yield

    # Shutdown
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass

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
