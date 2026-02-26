"""Debounced workspace notifications for transaction changes.

When a user adds, edits, or removes a transaction, other members of the
same workspace are notified.  Edits are debounced with a configurable
delay (default 2 min) so that rapid successive edits produce only a
single notification per transaction.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS: int = 60  # 1 minute


@dataclass
class _PendingNotification:
    """Tracks a debounced notification for a single transaction."""

    actor_id: int
    target_user_ids: list[int]
    text: str  # fully-formatted Markdown message
    task: asyncio.Task[None] | None = None
    is_removal: bool = False


class NotificationService:
    """Manages debounced notifications for workspace transaction changes."""

    def __init__(self, bot: Bot, debounce_seconds: int = DEBOUNCE_SECONDS) -> None:
        self._bot = bot
        self._debounce = debounce_seconds
        # key = transaction id (int), value = pending notification
        self._pending: dict[int, _PendingNotification] = {}
        # tx_ids whose notifications have actually been delivered
        self._notified: set[int] = set()

    # -- public API ----------------------------------------------------------

    async def notify(
        self,
        *,
        tx_id: int,
        actor_id: int,
        target_user_ids: list[int],
        text: str,
    ) -> None:
        """Schedule (or reschedule) a notification for *tx_id*.

        If a notification for the same ``tx_id`` is already pending,
        its timer is reset and the message is replaced with *text*.
        """
        self._schedule(tx_id=tx_id, actor_id=actor_id,
                       target_user_ids=target_user_ids, text=text)

    async def notify_remove(
        self,
        *,
        tx_id: int,
        actor_id: int,
        target_user_ids: list[int],
        text: str,
    ) -> None:
        """Send a remove notification only if this tx was previously notified.

        If a pending (unsent) notification exists for *tx_id*, it is
        cancelled silently.  A remove notification is only sent when
        the workspace has already been told about this transaction.
        """
        # Cancel any pending unsent notification for this tx
        prev = self._pending.pop(tx_id, None)
        if prev and prev.task and not prev.task.done():
            prev.task.cancel()

        # Only notify removal if the tx was previously notified
        if tx_id not in self._notified:
            return

        self._notified.discard(tx_id)
        self._schedule(tx_id=tx_id, actor_id=actor_id,
                       target_user_ids=target_user_ids, text=text,
                       is_removal=True)

    # -- internals -----------------------------------------------------------

    def _schedule(
        self,
        *,
        tx_id: int,
        actor_id: int,
        target_user_ids: list[int],
        text: str,
        is_removal: bool = False,
    ) -> None:
        """Create or reset the debounce timer for *tx_id*."""
        # Cancel previous pending notification for this tx
        prev = self._pending.get(tx_id)
        if prev and prev.task and not prev.task.done():
            prev.task.cancel()

        pending = _PendingNotification(
            actor_id=actor_id,
            target_user_ids=target_user_ids,
            text=text,
            is_removal=is_removal,
        )
        pending.task = asyncio.create_task(self._delayed_send(tx_id, pending))
        self._pending[tx_id] = pending

    async def _delayed_send(self, tx_id: int, pending: _PendingNotification) -> None:
        """Wait for the debounce period, then send the notification."""
        try:
            await asyncio.sleep(self._debounce)
        except asyncio.CancelledError:
            return  # debounce reset — a newer notification replaced this one

        # Clean up tracking
        self._pending.pop(tx_id, None)

        # Mark as notified so we know remove notifications are warranted
        if not pending.is_removal:
            self._notified.add(tx_id)

        # Send to every workspace member except the actor
        for uid in pending.target_user_ids:
            if uid == pending.actor_id:
                continue
            try:
                await self._bot.send_message(
                    chat_id=uid,
                    text=pending.text,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                logger.warning(
                    "Failed to send notification to user %s",
                    uid, exc_info=True,
                )

    async def cancel_all(self) -> None:
        """Cancel every pending notification (call on shutdown)."""
        for pending in self._pending.values():
            if pending.task and not pending.task.done():
                pending.task.cancel()
        self._pending.clear()
