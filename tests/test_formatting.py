"""Tests for the formatting helpers."""

from __future__ import annotations

from datetime import datetime

from app.bot.formatting import (
    format_summary,
    format_transaction_confirmation,
    format_transaction_list,
    format_transaction_row,
)
from app.db.models import Transaction, TransactionSummary, TransactionType


class TestFormatTransactionConfirmation:
    def _make_tx(self, **overrides) -> Transaction:
        defaults = dict(
            workspace_id_hash="ws1",
            user_id=1,
            type=TransactionType.EXPENSE,
            category="groceries",
            amount=68.90,
            currency="ILS",
            timestamp=datetime(2026, 2, 17, 14, 30),
            description="Supermarket",
        )
        defaults.update(overrides)
        return Transaction(**defaults)

    def test_expense_has_emoji(self):
        text = format_transaction_confirmation(self._make_tx())
        assert "💸" in text
        assert "Expense" in text

    def test_income_has_emoji(self):
        text = format_transaction_confirmation(self._make_tx(type=TransactionType.INCOME))
        assert "💰" in text
        assert "Income" in text

    def test_contains_fields(self):
        text = format_transaction_confirmation(self._make_tx())
        assert "groceries" in text
        assert "68.90" in text
        assert "ILS" in text
        assert "Supermarket" in text
        assert "2026-02-17" in text


class TestFormatTransactionRow:
    def _make_tx(self, **overrides) -> Transaction:
        defaults = dict(
            workspace_id_hash="ws1",
            user_id=1,
            type=TransactionType.EXPENSE,
            category="transport",
            amount=38.20,
            currency="USD",
            timestamp=datetime(2026, 2, 15, 9, 0),
            description="Uber",
        )
        defaults.update(overrides)
        return Transaction(**defaults)

    def test_basic_format(self):
        text = format_transaction_row(self._make_tx())
        assert "💸" in text
        assert "transport" in text
        assert "-38.20" in text

    def test_income_no_negative(self):
        text = format_transaction_row(self._make_tx(type=TransactionType.INCOME))
        assert "💰" in text
        assert "| 38.20" in text  # no minus sign before amount

    def test_show_user_with_name(self):
        text = format_transaction_row(
            self._make_tx(), show_user=True, user_names={1: "Alice"},
        )
        assert "Alice" in text
        assert "user 1" not in text

    def test_show_user_fallback_to_id(self):
        text = format_transaction_row(self._make_tx(), show_user=True)
        assert "user 1" in text

    def test_no_user_by_default(self):
        text = format_transaction_row(self._make_tx(), show_user=False)
        assert "user" not in text


class TestFormatTransactionList:
    def test_empty(self):
        text = format_transaction_list([])
        assert "No transactions" in text

    def test_with_items(self):
        tx = Transaction(
            workspace_id_hash="ws",
            user_id=1,
            type=TransactionType.INCOME,
            category="salary",
            amount=5000,
            currency="USD",
            timestamp=datetime(2026, 2, 1),
        )
        text = format_transaction_list([tx])
        assert "1 total" in text
        assert "salary" in text


class TestFormatSummary:
    def test_format(self):
        s = TransactionSummary(
            total_income=5000,
            total_expenses=2000,
            net=3000,
            currency="USD",
            count=10,
        )
        text = format_summary(s)
        assert "5,000.00" in text
        assert "2,000.00" in text
        assert "3,000.00" in text
        assert "10 transactions" in text
        # No initial balance line when it's zero
        assert "Initial" not in text

    def test_format_with_initial_balance(self):
        s = TransactionSummary(
            initial_balance=3000,
            total_income=500,
            total_expenses=200,
            net=3300,
            currency="ILS",
            count=3,
        )
        text = format_summary(s)
        assert "🏦 Initial" in text
        assert "3,000.00" in text
        assert "500.00" in text
        assert "200.00" in text
        assert "3,300.00" in text

    def test_format_negative_initial(self):
        s = TransactionSummary(
            initial_balance=-1000,
            total_income=0,
            total_expenses=0,
            net=-1000,
            currency="USD",
            count=1,
        )
        text = format_summary(s)
        assert "-1,000.00" in text
        assert "Initial" in text
