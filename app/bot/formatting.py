"""Formatting helpers for Telegram messages."""

from __future__ import annotations

from app.db.models import Transaction, TransactionSummary


def format_transaction_confirmation(tx: Transaction) -> str:
    """Pretty confirmation after recording a transaction."""
    type_emoji = "💰" if tx.type.value == "income" else "💸"
    return (
        f"{type_emoji} *Recorded*\n"
        f"  • Type: `{tx.type.value.capitalize()}`\n"
        f"  • Category: `{tx.category}`\n"
        f"  • Amount: `{tx.amount:,.2f} {tx.currency}`\n"
        f"  • Date: `{tx.timestamp.strftime('%Y-%m-%d %H:%M')}`\n"
        f"  • Description: _{tx.description}_"
    )


def format_transaction_details(tx: Transaction) -> str:
    """Transaction details without the header — used for notifications."""
    return (
        f"  • Type: `{tx.type.value.capitalize()}`\n"
        f"  • Category: `{tx.category}`\n"
        f"  • Amount: `{tx.amount:,.2f} {tx.currency}`\n"
        f"  • Date: `{tx.timestamp.strftime('%Y-%m-%d %H:%M')}`\n"
        f"  • Description: _{tx.description}_"
    )


def format_transaction_row(
    tx: Transaction,
    *,
    show_user: bool = False,
    user_names: dict[int, str] | None = None,
) -> str:
    """One-line summary of a transaction for list views."""
    emoji = "💰" if tx.type.value == "income" else "💸"
    sign = "" if tx.type.value == "income" else "-"
    line = (
        f"{emoji} `{tx.timestamp.strftime('%Y-%m-%d')}` "
        f"| {tx.category} | {sign}{tx.amount:,.2f} {tx.currency}"
    )
    if tx.description:
        line += f" — _{tx.description}_"
    if show_user:
        name = (user_names or {}).get(tx.user_id)
        line += f" | {name}" if name else f" | user {tx.user_id}"
    return line


def format_transaction_list(
    transactions: list[Transaction],
    user_names: dict[int, str] | None = None,
) -> str:
    """Format a list of transactions with a header."""
    if not transactions:
        return "📭 No transactions found."

    lines = [f"📋 *Transactions* ({len(transactions)} total)\n"]
    for tx in transactions:
        lines.append(
            format_transaction_row(tx, show_user=True, user_names=user_names)
        )
    return "\n".join(lines)


def format_summary(summary: TransactionSummary) -> str:
    """Format a transaction summary block."""
    lines = [f"\n📊 *Summary* ({summary.count} transactions)"]
    if summary.initial_balance != 0:
        lines.append(f"  🏦 Initial:  `{summary.initial_balance:,.2f} {summary.currency}`")
    lines.append(f"  💰 Income:   `{summary.total_income:,.2f} {summary.currency}`")
    lines.append(f"  💸 Expenses: `{summary.total_expenses:,.2f} {summary.currency}`")
    lines.append(f"  📈 Net:      `{summary.net:,.2f} {summary.currency}`")
    return "\n".join(lines)
