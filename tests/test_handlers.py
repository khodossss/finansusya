"""Tests for the Telegram bot handler helpers (mocked telegram objects)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.bot.handlers import _parse_date


class TestParseDate:
    def test_iso_format(self):
        result = _parse_date("2026-02-17")
        assert result == datetime(2026, 2, 17)

    def test_slash_format(self):
        result = _parse_date("17/02/2026")
        assert result == datetime(2026, 2, 17)

    def test_dot_format(self):
        result = _parse_date("17.02.2026")
        assert result == datetime(2026, 2, 17)

    def test_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_empty_string(self):
        assert _parse_date("") is None
