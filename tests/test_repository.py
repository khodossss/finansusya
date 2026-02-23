"""Tests for the SQLite repository layer."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.db.models import Transaction, TransactionType, User
from app.db.repository import Repository


# ---------------------------------------------------------------------------
# Workspace tests
# ---------------------------------------------------------------------------

class TestWorkspace:
    async def test_create_workspace(self, repo: Repository):
        ws = await repo.create_workspace()
        assert len(ws.id_hash) == 12
        assert ws.default_currency == "USD"
        assert isinstance(ws.created_at, datetime)

    async def test_create_workspace_with_currency(self, repo: Repository):
        ws = await repo.create_workspace(currency="EUR")
        assert ws.default_currency == "EUR"

    async def test_get_workspace(self, repo: Repository):
        ws = await repo.create_workspace(currency="ILS")
        found = await repo.get_workspace(ws.id_hash)
        assert found is not None
        assert found.id_hash == ws.id_hash
        assert found.default_currency == "ILS"

    async def test_get_workspace_not_found(self, repo: Repository):
        assert await repo.get_workspace("nonexistent") is None

    async def test_generate_hash_uniqueness(self):
        hashes = {Repository.generate_hash() for _ in range(100)}
        assert len(hashes) == 100  # all unique


# ---------------------------------------------------------------------------
# User tests
# ---------------------------------------------------------------------------

class TestUser:
    async def test_upsert_and_get(self, repo: Repository):
        ws = await repo.create_workspace(currency="EUR")
        user = User(
            telegram_user_id=111,
            name="TestUser",
            workspace_id_hash=ws.id_hash,
        )
        await repo.upsert_user(user)
        found = await repo.get_user(111)
        assert found is not None
        assert found.name == "TestUser"
        assert found.workspace_id_hash == ws.id_hash

    async def test_upsert_updates_existing(self, repo: Repository):
        ws = await repo.create_workspace(currency="ILS")
        user = User(telegram_user_id=222, name="OldName", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)

        updated = User(telegram_user_id=222, name="NewName", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(updated)

        found = await repo.get_user(222)
        assert found.name == "NewName"

    async def test_get_user_not_found(self, repo: Repository):
        assert await repo.get_user(99999) is None

    async def test_update_workspace_currency(self, repo: Repository):
        ws = await repo.create_workspace(currency="USD")
        await repo.update_workspace_currency(ws.id_hash, "EUR")
        found = await repo.get_workspace(ws.id_hash)
        assert found.default_currency == "EUR"


# ---------------------------------------------------------------------------
# Transaction tests
# ---------------------------------------------------------------------------

class TestTransactions:
    async def _setup_workspace_and_user(self, repo: Repository) -> tuple[str, int]:
        ws = await repo.create_workspace()
        user = User(telegram_user_id=333, name="TxUser", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)
        return ws.id_hash, 333

    async def test_add_and_list(self, repo: Repository):
        ws_id, uid = await self._setup_workspace_and_user(repo)
        tx = Transaction(
            workspace_id_hash=ws_id,
            user_id=uid,
            type=TransactionType.EXPENSE,
            category="food",
            amount=15.0,
            currency="USD",
            description="Lunch",
            raw_text="lunch 15",
        )
        tx_id = await repo.add_transaction(tx)
        assert isinstance(tx_id, int)

        txs = await repo.get_transactions(ws_id)
        assert len(txs) == 1
        assert txs[0].amount == 15.0
        assert txs[0].category == "food"

    async def test_date_filter(self, repo: Repository):
        ws_id, uid = await self._setup_workspace_and_user(repo)
        now = datetime.utcnow()

        for i in range(5):
            tx = Transaction(
                workspace_id_hash=ws_id,
                user_id=uid,
                type=TransactionType.EXPENSE,
                category="test",
                amount=10.0 * (i + 1),
                currency="USD",
                timestamp=now - timedelta(days=i),
            )
            await repo.add_transaction(tx)

        # Only last 2 days
        recent = await repo.get_transactions(
            ws_id,
            date_from=now - timedelta(days=1),
        )
        assert len(recent) == 2

    async def test_limit(self, repo: Repository):
        ws_id, uid = await self._setup_workspace_and_user(repo)
        for i in range(10):
            tx = Transaction(
                workspace_id_hash=ws_id,
                user_id=uid,
                type=TransactionType.INCOME,
                category="test",
                amount=1.0,
                currency="USD",
            )
            await repo.add_transaction(tx)

        limited = await repo.get_transactions(ws_id, limit=3)
        assert len(limited) == 3

    async def test_workspace_isolation(self, repo: Repository):
        """Transactions from different workspaces don't mix."""
        ws1 = await repo.create_workspace()
        ws2 = await repo.create_workspace()

        u1 = User(telegram_user_id=401, name="U1", workspace_id_hash=ws1.id_hash)
        u2 = User(telegram_user_id=402, name="U2", workspace_id_hash=ws2.id_hash)
        await repo.upsert_user(u1)
        await repo.upsert_user(u2)

        tx1 = Transaction(
            workspace_id_hash=ws1.id_hash, user_id=401,
            type=TransactionType.EXPENSE, category="a", amount=10, currency="USD",
        )
        tx2 = Transaction(
            workspace_id_hash=ws2.id_hash, user_id=402,
            type=TransactionType.INCOME, category="b", amount=20, currency="USD",
        )
        await repo.add_transaction(tx1)
        await repo.add_transaction(tx2)

        assert len(await repo.get_transactions(ws1.id_hash)) == 1
        assert len(await repo.get_transactions(ws2.id_hash)) == 1


# ---------------------------------------------------------------------------
# Summary tests
# ---------------------------------------------------------------------------

class TestSummary:
    async def test_summary(self, repo: Repository):
        ws = await repo.create_workspace()
        user = User(telegram_user_id=500, name="SumUser", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)

        income = Transaction(
            workspace_id_hash=ws.id_hash, user_id=500,
            type=TransactionType.INCOME, category="salary", amount=5000, currency="USD",
        )
        expense = Transaction(
            workspace_id_hash=ws.id_hash, user_id=500,
            type=TransactionType.EXPENSE, category="rent", amount=1500, currency="USD",
        )
        await repo.add_transaction(income)
        await repo.add_transaction(expense)

        summary = await repo.summarize_transactions(ws.id_hash)
        assert summary.total_income == 5000
        assert summary.total_expenses == 1500
        assert summary.net == 3500
        assert summary.count == 2

    async def test_summary_empty(self, repo: Repository):
        ws = await repo.create_workspace()
        summary = await repo.summarize_transactions(ws.id_hash)
        assert summary.total_income == 0
        assert summary.total_expenses == 0
        assert summary.initial_balance == 0
        assert summary.count == 0

    async def test_summary_separates_initial_balance(self, repo: Repository):
        ws = await repo.create_workspace()
        user = User(telegram_user_id=510, name="InitUser", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)

        # Initial balance (positive → income type)
        init_tx = Transaction(
            workspace_id_hash=ws.id_hash, user_id=510,
            type=TransactionType.INCOME, category="initial balance",
            amount=3000, currency="USD", description="Starting balance",
        )
        # Regular transactions
        income = Transaction(
            workspace_id_hash=ws.id_hash, user_id=510,
            type=TransactionType.INCOME, category="salary",
            amount=1000, currency="USD",
        )
        expense = Transaction(
            workspace_id_hash=ws.id_hash, user_id=510,
            type=TransactionType.EXPENSE, category="food",
            amount=200, currency="USD",
        )
        await repo.add_transaction(init_tx)
        await repo.add_transaction(income)
        await repo.add_transaction(expense)

        summary = await repo.summarize_transactions(ws.id_hash)
        assert summary.initial_balance == 3000
        assert summary.total_income == 1000
        assert summary.total_expenses == 200
        assert summary.net == 3800  # 3000 + 1000 - 200
        assert summary.count == 3

    async def test_summary_negative_initial_balance(self, repo: Repository):
        ws = await repo.create_workspace()
        user = User(telegram_user_id=511, name="NegInit", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)

        init_tx = Transaction(
            workspace_id_hash=ws.id_hash, user_id=511,
            type=TransactionType.EXPENSE, category="initial balance",
            amount=500, currency="USD", description="Starting balance",
        )
        await repo.add_transaction(init_tx)

        summary = await repo.summarize_transactions(ws.id_hash)
        assert summary.initial_balance == -500
        assert summary.total_income == 0
        assert summary.total_expenses == 0
        assert summary.net == -500
        assert summary.count == 1


# ---------------------------------------------------------------------------
# Get / Update single transaction
# ---------------------------------------------------------------------------

class TestGetAndUpdateTransaction:
    async def _make_tx(self, repo: Repository) -> tuple[str, int, int]:
        ws = await repo.create_workspace()
        user = User(telegram_user_id=700, name="EditUser", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)
        tx = Transaction(
            workspace_id_hash=ws.id_hash, user_id=700,
            type=TransactionType.EXPENSE, category="food",
            amount=25.0, currency="USD", description="Lunch",
        )
        tx_id = await repo.add_transaction(tx)
        return ws.id_hash, 700, tx_id

    async def test_get_transaction(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        tx = await repo.get_transaction(tx_id)
        assert tx is not None
        assert tx.id == tx_id
        assert tx.category == "food"

    async def test_get_transaction_not_found(self, repo: Repository):
        assert await repo.get_transaction(999999) is None

    async def test_update_category(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        await repo.update_transaction(tx_id, "category", "groceries")
        tx = await repo.get_transaction(tx_id)
        assert tx.category == "groceries"

    async def test_update_amount(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        await repo.update_transaction(tx_id, "amount", "99.99")
        tx = await repo.get_transaction(tx_id)
        assert tx.amount == 99.99

    async def test_update_type(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        await repo.update_transaction(tx_id, "type", "income")
        tx = await repo.get_transaction(tx_id)
        assert tx.type == TransactionType.INCOME

    async def test_update_currency(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        await repo.update_transaction(tx_id, "currency", "EUR")
        tx = await repo.get_transaction(tx_id)
        assert tx.currency == "EUR"

    async def test_update_description(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        await repo.update_transaction(tx_id, "description", "Dinner at restaurant")
        tx = await repo.get_transaction(tx_id)
        assert tx.description == "Dinner at restaurant"

    async def test_update_disallowed_field(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        with pytest.raises(ValueError, match="Cannot update field"):
            await repo.update_transaction(tx_id, "workspace_id_hash", "hacked")

    async def test_delete_transaction(self, repo: Repository):
        _, _, tx_id = await self._make_tx(repo)
        assert await repo.delete_transaction(tx_id) is True
        assert await repo.get_transaction(tx_id) is None

    async def test_delete_transaction_not_found(self, repo: Repository):
        assert await repo.delete_transaction(999999) is False


# ---------------------------------------------------------------------------
# Category tests
# ---------------------------------------------------------------------------

class TestCategories:
    async def test_get_categories_empty(self, repo: Repository):
        ws = await repo.create_workspace()
        cats = await repo.get_categories(ws.id_hash)
        assert cats == []

    async def test_get_categories_distinct(self, repo: Repository):
        ws = await repo.create_workspace()
        user = User(telegram_user_id=600, name="CatUser", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)

        for cat in ["food", "transport", "food", "rent", "transport"]:
            tx = Transaction(
                workspace_id_hash=ws.id_hash, user_id=600,
                type=TransactionType.EXPENSE, category=cat,
                amount=10, currency="USD",
            )
            await repo.add_transaction(tx)

        cats = await repo.get_categories(ws.id_hash)
        assert cats == ["food", "rent", "transport"]  # sorted, deduplicated


# ---------------------------------------------------------------------------
# Bulk currency conversion
# ---------------------------------------------------------------------------

class TestConvertAllTransactions:
    async def test_converts_amounts(self, repo: Repository):
        ws = await repo.create_workspace()
        user = User(telegram_user_id=800, name="ConvUser", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)

        for cur, amt in [("USD", 100.0), ("USD", 50.0), ("EUR", 200.0)]:
            tx = Transaction(
                workspace_id_hash=ws.id_hash, user_id=800,
                type=TransactionType.EXPENSE, category="test",
                amount=amt, currency=cur,
            )
            await repo.add_transaction(tx)

        async def fake_convert(amount, from_cur, to_cur):
            rates = {"USD": 3.5, "EUR": 4.0}
            return round(amount * rates.get(from_cur, 1.0), 2)

        count = await repo.convert_all_transactions(ws.id_hash, "ILS", fake_convert)
        assert count == 3

        txs = await repo.get_transactions(ws.id_hash)
        for tx in txs:
            assert tx.currency == "ILS"

        amounts = sorted(tx.amount for tx in txs)
        assert amounts == [175.0, 350.0, 800.0]

    async def test_skips_same_currency(self, repo: Repository):
        ws = await repo.create_workspace()
        user = User(telegram_user_id=801, name="SameUser", workspace_id_hash=ws.id_hash)
        await repo.upsert_user(user)

        tx = Transaction(
            workspace_id_hash=ws.id_hash, user_id=801,
            type=TransactionType.EXPENSE, category="test",
            amount=100.0, currency="ILS",
        )
        await repo.add_transaction(tx)

        async def should_not_be_called(amount, from_cur, to_cur):
            raise AssertionError("Should not convert same-currency transactions")

        count = await repo.convert_all_transactions(ws.id_hash, "ILS", should_not_be_called)
        assert count == 0


# ---------------------------------------------------------------------------
# Read-only SQL tests
# ---------------------------------------------------------------------------

class TestReadOnlySQL:
    async def test_select_works(self, repo: Repository):
        ws = await repo.create_workspace()
        rows = await repo.execute_readonly_sql(
            "SELECT id_hash FROM workspaces WHERE id_hash = ?",
            (ws.id_hash,),
        )
        assert len(rows) == 1
        assert rows[0]["id_hash"] == ws.id_hash

    async def test_reject_insert(self, repo: Repository):
        with pytest.raises(PermissionError):
            await repo.execute_readonly_sql("INSERT INTO workspaces VALUES ('x', 'y')")

    async def test_reject_delete(self, repo: Repository):
        with pytest.raises(PermissionError):
            await repo.execute_readonly_sql("DELETE FROM workspaces")

    async def test_reject_drop(self, repo: Repository):
        with pytest.raises(PermissionError):
            await repo.execute_readonly_sql("DROP TABLE workspaces")

    async def test_reject_update(self, repo: Repository):
        with pytest.raises(PermissionError):
            await repo.execute_readonly_sql("UPDATE workspaces SET id_hash = 'x'")
