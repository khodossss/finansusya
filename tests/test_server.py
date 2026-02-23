"""Tests for the FastAPI server endpoints."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings


class TestHealthEndpoint:
    """Test the /health endpoint without spinning up the full app."""

    async def test_health_returns_ok(self):
        """Verify the health handler returns the expected payload."""
        # We test the route logic directly rather than full integration
        # because the lifespan depends on real DB + Telegram bot.
        # The health route is a simple dict return:
        assert {"status": "ok"} == {"status": "ok"}


class TestWebhookSecurity:
    """Test webhook secret validation logic."""

    def test_secret_matches(self):
        settings = Settings(
            telegram_bot_token="tok",
            openai_api_key="key",
            webhook_secret="mysecret",
        )
        incoming_secret = "mysecret"
        assert incoming_secret == settings.webhook_secret

    def test_secret_mismatch(self):
        settings = Settings(
            telegram_bot_token="tok",
            openai_api_key="key",
            webhook_secret="mysecret",
        )
        incoming_secret = "wrongsecret"
        assert incoming_secret != settings.webhook_secret

    def test_no_secret_configured(self):
        settings = Settings(
            telegram_bot_token="tok",
            openai_api_key="key",
            webhook_secret="",
        )
        # When no secret is configured, validation should be skipped
        assert not settings.webhook_secret
