"""CSV export service for transactions."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from app.db.models import Transaction


# Column definitions -------------------------------------------------------

_COLUMNS = [
    "id",
    "date",
    "type",
    "category",
    "amount",
    "currency",
    "description",
    "user_id",
    "raw_text",
]


def generate_csv(transactions: list[Transaction]) -> str:
    """Return transactions as a CSV-formatted string (UTF-8)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_COLUMNS)
    writer.writeheader()

    for tx in transactions:
        writer.writerow(
            {
                "id": tx.id or "",
                "date": tx.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "type": tx.type.value,
                "category": tx.category,
                "amount": f"{tx.amount:.2f}",
                "currency": tx.currency,
                "description": tx.description,
                "user_id": tx.user_id,
                "raw_text": tx.raw_text,
            }
        )

    return buf.getvalue()


def generate_csv_bytes(transactions: list[Transaction]) -> bytes:
    """Return transactions as UTF-8-encoded CSV bytes (ready for sending)."""
    return generate_csv(transactions).encode("utf-8")


def make_csv_filename(
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> str:
    """Build a human-friendly filename for the CSV export."""
    today = datetime.utcnow().strftime("%Y-%m-%d")

    if date_from and date_to:
        start = date_from.strftime("%Y-%m-%d")
        end = date_to.strftime("%Y-%m-%d")
        return f"transactions_{start}_to_{end}.csv"

    if date_from:
        return f"transactions_from_{date_from.strftime('%Y-%m-%d')}.csv"

    return f"transactions_{today}.csv"
