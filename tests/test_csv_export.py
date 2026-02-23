"""Tests for the CSV export service."""

from __future__ import annotations

import csv
import io
from datetime import datetime

import pytest

from app.db.models import Transaction, TransactionType
from app.services.csv_export import (
    generate_csv,
    generate_csv_bytes,
    make_csv_filename,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_transactions() -> list[Transaction]:
    return [
        Transaction(
            id=1,
            workspace_id_hash="abc123",
            user_id=100,
            type=TransactionType.EXPENSE,
            category="food",
            amount=25.50,
            currency="USD",
            timestamp=datetime(2026, 2, 17, 10, 30),
            description="Lunch at cafe",
            raw_text="lunch 25.50",
        ),
        Transaction(
            id=2,
            workspace_id_hash="abc123",
            user_id=100,
            type=TransactionType.INCOME,
            category="salary",
            amount=5000.00,
            currency="USD",
            timestamp=datetime(2026, 2, 1, 9, 0),
            description="Monthly salary",
            raw_text="got salary 5000",
        ),
    ]


# ---------------------------------------------------------------------------
# generate_csv
# ---------------------------------------------------------------------------


class TestGenerateCsv:
    def test_header_row(self, sample_transactions):
        result = generate_csv(sample_transactions)
        reader = csv.reader(io.StringIO(result))
        header = next(reader)
        assert header == [
            "id", "date", "type", "category", "amount",
            "currency", "description", "user_id", "raw_text",
        ]

    def test_row_count(self, sample_transactions):
        result = generate_csv(sample_transactions)
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 3  # header + 2 data rows

    def test_row_values(self, sample_transactions):
        result = generate_csv(sample_transactions)
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)

        assert rows[0]["id"] == "1"
        assert rows[0]["type"] == "expense"
        assert rows[0]["category"] == "food"
        assert rows[0]["amount"] == "25.50"
        assert rows[0]["currency"] == "USD"
        assert rows[0]["description"] == "Lunch at cafe"

        assert rows[1]["type"] == "income"
        assert rows[1]["amount"] == "5000.00"

    def test_empty_list(self):
        result = generate_csv([])
        reader = csv.reader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) == 1  # header only

    def test_transaction_without_id(self):
        tx = Transaction(
            workspace_id_hash="x",
            user_id=1,
            type=TransactionType.EXPENSE,
            category="other",
            amount=10,
            currency="EUR",
        )
        result = generate_csv([tx])
        reader = csv.DictReader(io.StringIO(result))
        row = next(reader)
        assert row["id"] == ""


# ---------------------------------------------------------------------------
# generate_csv_bytes
# ---------------------------------------------------------------------------


class TestGenerateCsvBytes:
    def test_returns_bytes(self, sample_transactions):
        result = generate_csv_bytes(sample_transactions)
        assert isinstance(result, bytes)

    def test_utf8_decodable(self, sample_transactions):
        result = generate_csv_bytes(sample_transactions)
        decoded = result.decode("utf-8")
        assert "food" in decoded
        assert "salary" in decoded


# ---------------------------------------------------------------------------
# make_csv_filename
# ---------------------------------------------------------------------------


class TestMakeCsvFilename:
    def test_no_dates(self):
        name = make_csv_filename()
        today = datetime.utcnow().strftime("%Y-%m-%d")
        assert name == f"transactions_{today}.csv"

    def test_date_range(self):
        d1 = datetime(2026, 1, 1)
        d2 = datetime(2026, 1, 31)
        name = make_csv_filename(date_from=d1, date_to=d2)
        assert name == "transactions_2026-01-01_to_2026-01-31.csv"

    def test_date_from_only(self):
        d1 = datetime(2026, 2, 10)
        name = make_csv_filename(date_from=d1)
        assert name == "transactions_from_2026-02-10.csv"

    def test_ends_with_csv(self):
        assert make_csv_filename().endswith(".csv")
