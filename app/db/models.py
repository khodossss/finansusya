"""Pydantic models for the finance domain."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    """Income or expense."""

    INCOME = "income"
    EXPENSE = "expense"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class Workspace(BaseModel):
    """A shared finance workspace identified by a hash."""

    id_hash: str
    default_currency: str = "USD"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(BaseModel):
    """A Telegram user profile linked to a workspace."""

    telegram_user_id: int
    name: str
    workspace_id_hash: str | None = None


class Transaction(BaseModel):
    """A single financial transaction."""

    id: int | None = None
    workspace_id_hash: str
    user_id: int
    type: TransactionType
    category: str
    amount: float
    currency: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    description: str = ""
    raw_text: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Parsed transaction from the LLM (before saving)
# ---------------------------------------------------------------------------

class ParsedTransaction(BaseModel):
    """Structured output returned by the LLM when parsing a user message."""

    is_transaction: bool = Field(
        default=True,
        description=(
            "True if the message describes a real financial transaction. "
            "False if the message is a question, greeting, or anything "
            "that is NOT a transaction."
        ),
    )
    type: TransactionType = TransactionType.EXPENSE
    amount: float = 0.0
    currency: str = "USD"
    category: str = "other"
    datetime_str: str = Field(
        default="now",
        description="ISO-8601 date/time string or the word 'now'.",
    )
    description: str = ""


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

class TransactionSummary(BaseModel):
    """Aggregated totals for a period."""

    initial_balance: float = 0.0
    total_income: float = 0.0
    total_expenses: float = 0.0
    net: float = 0.0
    currency: str = "USD"
    count: int = 0
