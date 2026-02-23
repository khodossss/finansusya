"""Tests for the Pydantic domain models."""

from __future__ import annotations

from datetime import datetime

from app.db.models import (
    ParsedTransaction,
    Transaction,
    TransactionSummary,
    TransactionType,
    User,
    Workspace,
)


class TestTransactionType:
    def test_values(self):
        assert TransactionType.INCOME == "income"
        assert TransactionType.EXPENSE == "expense"

    def test_from_string(self):
        assert TransactionType("income") is TransactionType.INCOME
        assert TransactionType("expense") is TransactionType.EXPENSE


class TestWorkspace:
    def test_creation(self):
        ws = Workspace(id_hash="abc123")
        assert ws.id_hash == "abc123"
        assert ws.default_currency == "USD"
        assert isinstance(ws.created_at, datetime)

    def test_custom_currency(self):
        ws = Workspace(id_hash="abc123", default_currency="EUR")
        assert ws.default_currency == "EUR"


class TestUser:
    def test_defaults(self):
        u = User(telegram_user_id=1, name="Bob")
        assert u.workspace_id_hash is None

    def test_full(self):
        u = User(
            telegram_user_id=99,
            name="Alice",
            workspace_id_hash="xyz",
        )
        assert u.workspace_id_hash == "xyz"


class TestTransaction:
    def test_defaults(self):
        tx = Transaction(
            workspace_id_hash="ws1",
            user_id=1,
            type=TransactionType.EXPENSE,
            category="food",
            amount=10.0,
            currency="USD",
        )
        assert tx.id is None
        assert tx.description == ""
        assert tx.raw_text == ""
        assert isinstance(tx.timestamp, datetime)
        assert isinstance(tx.created_at, datetime)

    def test_income(self):
        tx = Transaction(
            workspace_id_hash="ws1",
            user_id=1,
            type=TransactionType.INCOME,
            category="salary",
            amount=5000,
            currency="ILS",
        )
        assert tx.type == TransactionType.INCOME


class TestParsedTransaction:
    def test_minimal(self):
        pt = ParsedTransaction(
            type=TransactionType.EXPENSE,
            amount=25.0,
            currency="USD",
            category="transport",
            description="Uber to office",
        )
        assert pt.datetime_str == "now"
        assert pt.is_transaction is True

    def test_not_a_transaction(self):
        pt = ParsedTransaction(is_transaction=False)
        assert pt.is_transaction is False
        assert pt.amount == 0.0
        assert pt.category == "other"

    def test_with_date(self):
        pt = ParsedTransaction(
            type=TransactionType.INCOME,
            amount=1200,
            currency="EUR",
            category="salary",
            datetime_str="2026-02-01T00:00:00",
            description="Monthly salary",
        )
        assert pt.datetime_str == "2026-02-01T00:00:00"


class TestTransactionSummary:
    def test_defaults(self):
        s = TransactionSummary()
        assert s.total_income == 0.0
        assert s.total_expenses == 0.0
        assert s.net == 0.0
        assert s.count == 0

    def test_net_calculation(self):
        s = TransactionSummary(
            total_income=1000,
            total_expenses=600,
            net=400,
            currency="USD",
            count=5,
        )
        assert s.net == s.total_income - s.total_expenses
