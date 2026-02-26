"""Tests for the notification service."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.notifications import NotificationService


@pytest.fixture()
def bot() -> MagicMock:
    """Fake Telegram Bot with an async send_message."""
    b = MagicMock()
    b.send_message = AsyncMock()
    return b


@pytest.fixture()
def notifier(bot: MagicMock) -> NotificationService:
    """NotificationService with a very short debounce for fast tests."""
    return NotificationService(bot, debounce_seconds=0)


class TestNotify:
    async def test_sends_to_other_users(self, notifier: NotificationService, bot: MagicMock):
        await notifier.notify(
            tx_id=1,
            actor_id=100,
            target_user_ids=[100, 200, 300],
            text="➕ *Alice* added:\n\n💸 *Recorded*\n  • Category: `groceries`",
        )
        await asyncio.sleep(0.05)

        # Should send to 200 and 300 but NOT 100 (the actor)
        assert bot.send_message.call_count == 2
        chat_ids = {call.kwargs["chat_id"] for call in bot.send_message.call_args_list}
        assert chat_ids == {200, 300}
        text = bot.send_message.call_args_list[0].kwargs["text"]
        assert "Alice" in text
        assert "groceries" in text

    async def test_no_notification_to_self(self, notifier: NotificationService, bot: MagicMock):
        await notifier.notify(
            tx_id=2,
            actor_id=100,
            target_user_ids=[100],
            text="➕ *Alice* added:\n\nsome tx",
        )
        await asyncio.sleep(0.05)
        bot.send_message.assert_not_called()

    async def test_edit_notification(self, notifier: NotificationService, bot: MagicMock):
        await notifier.notify(
            tx_id=5,
            actor_id=100,
            target_user_ids=[100, 200],
            text="✏️ *Bob* edited:\n\n💰 *Recorded*\n  • Category: `rent`",
        )
        await asyncio.sleep(0.05)

        bot.send_message.assert_called_once()
        text = bot.send_message.call_args.kwargs["text"]
        assert "Bob" in text
        assert "edited" in text

    async def test_remove_notification(self, notifier: NotificationService, bot: MagicMock):
        await notifier.notify(
            tx_id=10,
            actor_id=100,
            target_user_ids=[100, 200],
            text="🗑 *Carol* removed:\n\n💸 *Recorded*\n  • Category: `coffee`",
        )
        await asyncio.sleep(0.05)

        bot.send_message.assert_called_once()
        text = bot.send_message.call_args.kwargs["text"]
        assert "Carol" in text
        assert "removed" in text


class TestNotifyRemove:
    """Tests for notify_remove – only sends if tx was previously notified."""

    async def test_remove_skipped_when_never_notified(
        self, notifier: NotificationService, bot: MagicMock,
    ):
        """If a tx was never notified about, remove notification is skipped."""
        await notifier.notify_remove(
            tx_id=99,
            actor_id=100,
            target_user_ids=[100, 200],
            text="🗑 *Alice* removed:\n\nsome tx",
        )
        await asyncio.sleep(0.05)
        bot.send_message.assert_not_called()

    async def test_remove_sent_when_previously_notified(
        self, notifier: NotificationService, bot: MagicMock,
    ):
        """If a tx was notified about, remove notification is sent."""
        # First, notify about the tx (add)
        await notifier.notify(
            tx_id=50,
            actor_id=100,
            target_user_ids=[100, 200],
            text="➕ *Alice* added:\n\nsome tx",
        )
        await asyncio.sleep(0.05)
        assert bot.send_message.call_count == 1

        bot.send_message.reset_mock()

        # Now remove → should send
        await notifier.notify_remove(
            tx_id=50,
            actor_id=100,
            target_user_ids=[100, 200],
            text="🗑 *Alice* removed:\n\nsome tx",
        )
        await asyncio.sleep(0.05)
        assert bot.send_message.call_count == 1
        assert "removed" in bot.send_message.call_args.kwargs["text"]

    async def test_remove_cancels_pending_unsent(self, bot: MagicMock):
        """If a tx has a pending (unsent) notification, remove cancels it silently."""
        svc = NotificationService(bot, debounce_seconds=0.2)

        # Add notification – still pending (debounce not elapsed)
        await svc.notify(
            tx_id=60,
            actor_id=100,
            target_user_ids=[100, 200],
            text="➕ *Bob* added:\n\nsome tx",
        )

        # Immediately remove – pending add should be cancelled, no remove sent
        await svc.notify_remove(
            tx_id=60,
            actor_id=100,
            target_user_ids=[100, 200],
            text="🗑 *Bob* removed:\n\nsome tx",
        )
        await asyncio.sleep(0.3)

        # Nothing should have been sent
        bot.send_message.assert_not_called()

    async def test_remove_clears_notified_flag(
        self, notifier: NotificationService, bot: MagicMock,
    ):
        """After a remove notification, the tx_id is no longer in _notified."""
        await notifier.notify(
            tx_id=70, actor_id=100, target_user_ids=[100, 200],
            text="➕ add",
        )
        await asyncio.sleep(0.05)
        assert 70 in notifier._notified

        await notifier.notify_remove(
            tx_id=70, actor_id=100, target_user_ids=[100, 200],
            text="🗑 remove",
        )
        await asyncio.sleep(0.05)
        assert 70 not in notifier._notified


class TestDebounce:
    async def test_rapid_edits_send_only_once(self, bot: MagicMock):
        """Multiple edits within the debounce window → single notification."""
        svc = NotificationService(bot, debounce_seconds=0.1)

        for amount in (10, 20, 30):
            await svc.notify(
                tx_id=42,
                actor_id=100,
                target_user_ids=[100, 200],
                text=f"✏️ *Dave* edited:\n\n💸 *Recorded*\n  • Amount: `{amount}`",
            )
            await asyncio.sleep(0.03)

        # Wait for the debounce to fire
        await asyncio.sleep(0.15)

        # Only the last notification should have been sent
        assert bot.send_message.call_count == 1
        text = bot.send_message.call_args.kwargs["text"]
        assert "30" in text

    async def test_different_tx_ids_not_debounced(self, bot: MagicMock):
        """Notifications for different transactions are independent."""
        svc = NotificationService(bot, debounce_seconds=0)

        await svc.notify(
            tx_id=1, actor_id=100, target_user_ids=[100, 200],
            text="tx 1",
        )
        await svc.notify(
            tx_id=2, actor_id=100, target_user_ids=[100, 200],
            text="tx 2",
        )
        await asyncio.sleep(0.05)

        # Both should fire (different tx_ids)
        assert bot.send_message.call_count == 2


class TestCancelAll:
    async def test_cancel_prevents_send(self, bot: MagicMock):
        svc = NotificationService(bot, debounce_seconds=0.2)
        await svc.notify(
            tx_id=99, actor_id=100, target_user_ids=[100, 200],
            text="should not be sent",
        )
        await svc.cancel_all()
        await asyncio.sleep(0.3)

        bot.send_message.assert_not_called()


class TestSendFailure:
    async def test_send_failure_is_logged(self, notifier: NotificationService, bot: MagicMock):
        """If send_message fails for one user, others still get notified."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if kwargs["chat_id"] == 200:
                raise Exception("network error")

        bot.send_message.side_effect = side_effect

        await notifier.notify(
            tx_id=7, actor_id=100, target_user_ids=[100, 200, 300],
            text="test notification",
        )
        await asyncio.sleep(0.05)

        # Should have attempted to send to both 200 and 300
        assert call_count == 2
