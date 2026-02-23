"""Shared test fixtures."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from app.config import Settings
from app.db.models import Transaction, TransactionType, User
from app.db.repository import Repository


@pytest.fixture
def settings() -> Settings:
    """Settings instance with test values."""
    return Settings(
        telegram_bot_token="test-token-123",
        openai_api_key="sk-test-key",
        openai_model="gpt-4o-mini",
        database_path=":memory:",
    )


@pytest_asyncio.fixture
async def repo(tmp_path) -> Repository:
    """In-memory repository, connected and ready."""
    db_path = str(tmp_path / "test.db")
    r = Repository(db_path)
    await r.connect()
    yield r
    await r.close()


@pytest.fixture
def sample_user() -> User:
    return User(
        telegram_user_id=12345,
        name="Alice",
        workspace_id_hash="abc123hash",
    )


@pytest.fixture
def sample_transaction() -> Transaction:
    return Transaction(
        workspace_id_hash="abc123hash",
        user_id=12345,
        type=TransactionType.EXPENSE,
        category="groceries",
        amount=42.50,
        currency="USD",
        timestamp=datetime(2026, 2, 17, 10, 0, 0),
        description="Supermarket run",
        raw_text="supermarket 42.50",
    )
