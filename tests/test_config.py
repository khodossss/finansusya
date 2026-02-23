"""Tests for app.config."""

from __future__ import annotations

import os

from app.config import Settings


class TestSettings:
    def test_defaults(self):
        s = Settings(telegram_bot_token="tok", openai_api_key="key")
        assert s.openai_model == "gpt-4o-mini"
        assert s.host == "0.0.0.0"
        assert s.port == 8000

    def test_validate_passes_when_complete(self):
        s = Settings(telegram_bot_token="tok", openai_api_key="key")
        assert s.validate() == []

    def test_validate_reports_missing_token(self):
        s = Settings(telegram_bot_token="", openai_api_key="key")
        errors = s.validate()
        assert any("TELEGRAM_BOT_TOKEN" in e for e in errors)

    def test_validate_reports_missing_api_key(self):
        s = Settings(telegram_bot_token="tok", openai_api_key="")
        errors = s.validate()
        assert any("OPENAI_API_KEY" in e for e in errors)

    def test_validate_reports_multiple_missing(self):
        s = Settings(telegram_bot_token="", openai_api_key="")
        assert len(s.validate()) == 2

    def test_ensure_data_dir(self, tmp_path):
        db_path = str(tmp_path / "sub" / "deep" / "test.db")
        s = Settings(
            telegram_bot_token="tok",
            openai_api_key="key",
            database_path=db_path,
        )
        s.ensure_data_dir()
        assert (tmp_path / "sub" / "deep").is_dir()

    def test_frozen(self):
        s = Settings(telegram_bot_token="tok", openai_api_key="key")
        with __import__("pytest").raises(AttributeError):
            s.port = 9999  # type: ignore[misc]
