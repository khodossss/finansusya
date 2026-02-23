"""Async SQLite repository — single-file data-access layer."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from pathlib import Path

import aiosqlite

from app.db.models import Transaction, TransactionSummary, TransactionType, User, Workspace

# ---------------------------------------------------------------------------
# SQL DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id_hash          TEXT PRIMARY KEY,
    default_currency TEXT NOT NULL DEFAULT 'USD',
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    telegram_user_id  INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL,
    workspace_id_hash TEXT    REFERENCES workspaces(id_hash)
);

CREATE TABLE IF NOT EXISTS transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id_hash TEXT    NOT NULL REFERENCES workspaces(id_hash),
    user_id           INTEGER NOT NULL REFERENCES users(telegram_user_id),
    type              TEXT    NOT NULL CHECK(type IN ('income', 'expense')),
    category          TEXT    NOT NULL,
    amount            REAL    NOT NULL,
    currency          TEXT    NOT NULL,
    timestamp         TEXT    NOT NULL,
    description       TEXT    DEFAULT '',
    raw_text          TEXT    DEFAULT '',
    created_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_workspace ON transactions(workspace_id_hash);
CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp);
"""


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class Repository:
    """Thin async wrapper around SQLite for the finance bot."""

    def __init__(self, db_path: str = "data/finance.db") -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    # -- lifecycle -----------------------------------------------------------

    async def connect(self) -> None:
        """Open the database and ensure schema exists."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_DDL)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call `connect()` first.")
        return self._conn

    # -- workspaces ----------------------------------------------------------

    @staticmethod
    def generate_hash() -> str:
        """Create a short, unique workspace hash."""
        raw = secrets.token_bytes(16)
        return hashlib.sha256(raw).hexdigest()[:12]

    async def create_workspace(self, currency: str = "USD") -> Workspace:
        id_hash = self.generate_hash()
        now = datetime.utcnow().isoformat()
        await self.conn.execute(
            "INSERT INTO workspaces (id_hash, default_currency, created_at) VALUES (?, ?, ?)",
            (id_hash, currency, now),
        )
        await self.conn.commit()
        return Workspace(id_hash=id_hash, default_currency=currency, created_at=datetime.fromisoformat(now))

    async def get_workspace(self, id_hash: str) -> Workspace | None:
        cursor = await self.conn.execute(
            "SELECT id_hash, default_currency, created_at FROM workspaces WHERE id_hash = ?",
            (id_hash,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return Workspace(
            id_hash=row["id_hash"],
            default_currency=row["default_currency"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -- users ---------------------------------------------------------------

    async def upsert_user(self, user: User) -> None:
        await self.conn.execute(
            """
            INSERT INTO users (telegram_user_id, name, workspace_id_hash)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                name = excluded.name,
                workspace_id_hash = excluded.workspace_id_hash
            """,
            (user.telegram_user_id, user.name, user.workspace_id_hash),
        )
        await self.conn.commit()

    async def get_user(self, telegram_user_id: int) -> User | None:
        cursor = await self.conn.execute(
            "SELECT telegram_user_id, name, workspace_id_hash "
            "FROM users WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return User(
            telegram_user_id=row["telegram_user_id"],
            name=row["name"],
            workspace_id_hash=row["workspace_id_hash"],
        )

    async def get_workspace_user_names(
        self, workspace_id_hash: str,
    ) -> dict[int, str]:
        """Return a mapping of ``{telegram_user_id: name}`` for every user
        in the given workspace."""
        cursor = await self.conn.execute(
            "SELECT telegram_user_id, name FROM users "
            "WHERE workspace_id_hash = ?",
            (workspace_id_hash,),
        )
        rows = await cursor.fetchall()
        return {row["telegram_user_id"]: row["name"] for row in rows}

    async def update_workspace_currency(
        self, workspace_id_hash: str, new_currency: str,
    ) -> None:
        """Update the default currency for a workspace."""
        await self.conn.execute(
            "UPDATE workspaces SET default_currency = ? WHERE id_hash = ?",
            (new_currency, workspace_id_hash),
        )
        await self.conn.commit()

    # -- transactions --------------------------------------------------------

    async def add_transaction(self, tx: Transaction) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO transactions
                (workspace_id_hash, user_id, type, category, amount,
                 currency, timestamp, description, raw_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tx.workspace_id_hash,
                tx.user_id,
                tx.type.value,
                tx.category,
                tx.amount,
                tx.currency,
                tx.timestamp.isoformat(),
                tx.description,
                tx.raw_text,
                tx.created_at.isoformat(),
            ),
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_transaction(self, tx_id: int) -> Transaction | None:
        """Fetch a single transaction by its primary key."""
        cursor = await self.conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (tx_id,)
        )
        r = await cursor.fetchone()
        if not r:
            return None
        return Transaction(
            id=r["id"],
            workspace_id_hash=r["workspace_id_hash"],
            user_id=r["user_id"],
            type=TransactionType(r["type"]),
            category=r["category"],
            amount=r["amount"],
            currency=r["currency"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            description=r["description"],
            raw_text=r["raw_text"],
            created_at=datetime.fromisoformat(r["created_at"]),
        )

    async def update_transaction(self, tx_id: int, field: str, value: str) -> None:
        """Update a single allowed field on a transaction."""
        allowed = {"type", "category", "amount", "currency", "description"}
        if field not in allowed:
            raise ValueError(f"Cannot update field '{field}'. Allowed: {allowed}")
        await self.conn.execute(
            f"UPDATE transactions SET {field} = ? WHERE id = ?",
            (value, tx_id),
        )
        await self.conn.commit()

    async def delete_transaction(self, tx_id: int) -> bool:
        """Delete a transaction by ID.  Returns *True* if a row was removed."""
        cursor = await self.conn.execute(
            "DELETE FROM transactions WHERE id = ?", (tx_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def get_transactions(
        self,
        workspace_id_hash: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 200,
    ) -> list[Transaction]:
        query = "SELECT * FROM transactions WHERE workspace_id_hash = ?"
        params: list[object] = [workspace_id_hash]

        if date_from:
            query += " AND timestamp >= ?"
            params.append(date_from.isoformat())
        if date_to:
            query += " AND timestamp <= ?"
            params.append(date_to.isoformat())

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = await self.conn.execute(query, params)
        rows = await cursor.fetchall()

        return [
            Transaction(
                id=r["id"],
                workspace_id_hash=r["workspace_id_hash"],
                user_id=r["user_id"],
                type=TransactionType(r["type"]),
                category=r["category"],
                amount=r["amount"],
                currency=r["currency"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                description=r["description"],
                raw_text=r["raw_text"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    async def summarize_transactions(
        self,
        workspace_id_hash: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        currency: str = "USD",
    ) -> TransactionSummary:
        base = (
            "SELECT type, "
            "CASE WHEN category = 'initial balance' THEN 1 ELSE 0 END as is_initial, "
            "SUM(amount) as total, COUNT(*) as cnt "
            "FROM transactions WHERE workspace_id_hash = ?"
        )
        params: list[object] = [workspace_id_hash]

        if date_from:
            base += " AND timestamp >= ?"
            params.append(date_from.isoformat())
        if date_to:
            base += " AND timestamp <= ?"
            params.append(date_to.isoformat())

        base += " GROUP BY type, is_initial"

        cursor = await self.conn.execute(base, params)
        rows = await cursor.fetchall()

        income = 0.0
        expenses = 0.0
        initial_balance = 0.0
        count = 0
        for r in rows:
            total = r["total"] or 0.0
            cnt = r["cnt"] or 0
            count += cnt
            if r["is_initial"]:
                # Initial balance: income ➜ positive, expense ➜ negative
                initial_balance += total if r["type"] == "income" else -total
            else:
                if r["type"] == "income":
                    income = total
                else:
                    expenses = total

        return TransactionSummary(
            initial_balance=initial_balance,
            total_income=income,
            total_expenses=expenses,
            net=initial_balance + income - expenses,
            currency=currency,
            count=count,
        )

    async def get_categories(self, workspace_id_hash: str) -> list[str]:
        """Return distinct category names used in this workspace."""
        cursor = await self.conn.execute(
            "SELECT DISTINCT category FROM transactions "
            "WHERE workspace_id_hash = ? ORDER BY category",
            (workspace_id_hash,),
        )
        rows = await cursor.fetchall()
        return [r["category"] for r in rows]

    async def convert_all_transactions(
        self,
        workspace_id_hash: str,
        new_currency: str,
        converter,
    ) -> int:
        """Convert every transaction in the workspace to *new_currency*.

        *converter* must be an async callable ``(amount, from_cur, to_cur) -> float``.
        Returns the number of converted transactions.
        """
        cursor = await self.conn.execute(
            "SELECT id, amount, currency FROM transactions "
            "WHERE workspace_id_hash = ?",
            (workspace_id_hash,),
        )
        rows = await cursor.fetchall()

        count = 0
        for r in rows:
            old_cur = r["currency"]
            if old_cur == new_currency:
                continue
            new_amount = await converter(r["amount"], old_cur, new_currency)
            await self.conn.execute(
                "UPDATE transactions SET amount = ?, currency = ? WHERE id = ?",
                (new_amount, new_currency, r["id"]),
            )
            count += 1

        await self.conn.commit()
        return count

    # -- raw SQL for Q&A (read-only) ----------------------------------------

    async def execute_readonly_sql(self, sql: str, params: tuple = ()) -> list[dict]:
        """Execute a SELECT query and return rows as dicts. Raises on non-SELECT."""
        normalized = sql.strip().lower()
        if not normalized.startswith("select"):
            raise PermissionError("Only SELECT queries are allowed in Q&A mode.")

        cursor = await self.conn.execute(sql, params)
        columns = [d[0] for d in cursor.description] if cursor.description else []
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
